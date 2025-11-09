#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Faktori dan mekanisme routing penyedia
Bertanggung jawab untuk secara otomatis memilih penyedia yang sesuai berdasarkan nama model
"""

import time
from typing import Dict, List, Optional, Union, AsyncGenerator, Any
from app.providers.base import BaseProvider, provider_registry
from app.providers.zai_provider import ZAIProvider
from app.providers.k2think_provider import K2ThinkProvider
from app.providers.longcat_provider import LongCatProvider
from app.models.schemas import OpenAIRequest
from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger()


class ProviderFactory:
    """Faktori penyedia"""
    
    def __init__(self):
        self._initialized = False
        self._default_provider = "zai"
    
    def initialize(self):
        """Inisialisasi semua penyedia"""
        if self._initialized:
            return

        try:
            # Mendaftarkan penyedia Z.AI
            zai_provider = ZAIProvider()
            provider_registry.register(
                zai_provider,
                zai_provider.get_supported_models()
            )
            
            # Mendaftarkan penyedia K2Think
            k2think_provider = K2ThinkProvider()
            provider_registry.register(
                k2think_provider,
                k2think_provider.get_supported_models()
            )
            
            # Mendaftarkan penyedia LongCat
            longcat_provider = LongCatProvider()
            provider_registry.register(
                longcat_provider,
                longcat_provider.get_supported_models()
            )
            
            self._initialized = True
            
        except Exception as e:
            logger.error(f"❌ Gagal menginisialisasi faktori penyedia: {e}")
            raise

    def get_provider_for_model(self, model: str) -> Optional[BaseProvider]:
        """Mendapatkan penyedia berdasarkan nama model"""
        if not self._initialized:
            self.initialize()
        
        # Pertama coba dapatkan dari pemetaan konfigurasi
        provider_mapping = settings.provider_model_mapping
        provider_name = provider_mapping.get(model)
        
        if provider_name:
            provider = provider_registry.get_provider_by_name(provider_name)
            if provider:
                logger.debug(f"🎯 Model {model} dipetakan ke penyedia {provider_name}")
                return provider
        
        # Coba langsung dari registry
        provider = provider_registry.get_provider(model)
        if provider:
            logger.debug(f"🎯 Model {model} menemukan penyedia {provider.name}")
            return provider
        
        # Gunakan penyedia default
        default_provider = provider_registry.get_provider_by_name(self._default_provider)
        if default_provider:
            logger.warning(f"⚠️ Model {model} tidak menemukan penyedia khusus, menggunakan penyedia default {self._default_provider}")
            return default_provider
        
        logger.error(f"❌ Tidak dapat menemukan penyedia untuk model {model}")
        return None
    
    def list_supported_models(self) -> List[str]:
        """Mencantumkan semua model yang didukung"""
        if not self._initialized:
            self.initialize()
        return provider_registry.list_models()
    
    def list_providers(self) -> List[str]:
        """Mencantumkan semua penyedia"""
        if not self._initialized:
            self.initialize()
        return provider_registry.list_providers()
    
    def get_models_for_provider(self, provider_name: str) -> List[str]:
        """Mendapatkan model yang didukung oleh penyedia tertentu"""
        if not self._initialized:
            self.initialize()
        
        provider = provider_registry.get_provider_by_name(provider_name)
        if provider:
            return provider.get_supported_models()
        return []


class ProviderRouter:
    """Router penyedia"""
    
    def __init__(self):
        self.factory = ProviderFactory()
    
    async def route_request(
        self, 
        request: OpenAIRequest,
        **kwargs
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        """Rute permintaan ke penyedia yang sesuai"""
        logger.info(f"🚦 Rute permintaan: model={request.model}, stream={request.stream}")
        
        # Dapatkan penyedia
        provider = self.factory.get_provider_for_model(request.model)
        if not provider:
            error_msg = f"Model tidak didukung: {request.model}"
            logger.error(f"❌ {error_msg}")
            return {
                "error": {
                    "message": error_msg,
                    "type": "invalid_request_error",
                    "code": "model_not_found"
                }
            }
        
        logger.info(f"✅ Menggunakan penyedia: {provider.name}")
        
        try:
            # Panggil penyedia untuk menangani permintaan
            result = await provider.chat_completion(request, **kwargs)
            logger.info(f"🎉 Penanganan permintaan selesai: {provider.name}")
            return result
            
        except Exception as e:
            error_msg = f"Penyedia {provider.name} gagal menangani permintaan: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return provider.handle_error(e, "pemrosesan rute")
    
    def get_provider_for_model(self, model: str) -> Optional[Dict[str, str]]:
        """
        Dapatkan informasi penyedia yang sesuai dengan model

        Returns:
            Kamus berisi nama penyedia, misalnya {"provider": "zai"}
        """
        provider = self.factory.get_provider_for_model(model)
        if provider:
            return {"provider": provider.name}
        return None

    def get_models_list(self) -> Dict[str, Any]:
        """Dapatkan daftar model (format OpenAI)"""
        models = []
        current_time = int(time.time())

        # Dapatkan model berdasarkan penyedia
        for provider_name in self.factory.list_providers():
            provider_models = self.factory.get_models_for_provider(provider_name)
            for model in provider_models:
                models.append({
                    "id": model,
                    "object": "model",
                    "created": current_time,
                    "owned_by": provider_name
                })

        return {
            "object": "list",
            "data": models
        }


# Instance router global
_router: Optional[ProviderRouter] = None

def get_provider_router() -> ProviderRouter:
    """Dapatkan router penyedia global"""
    global _router
    if _router is None:
        _router = ProviderRouter()
        # Pastikan factory telah diinisialisasi
        _router.factory.initialize()
    return _router


def initialize_providers():
    """Inisialisasi sistem penyedia"""
    logger.info("🚀 Inisialisasi sistem penyedia...")
    router = get_provider_router()
    logger.info("✅ Sistem penyedia selesai diinisialisasi")
    return router

