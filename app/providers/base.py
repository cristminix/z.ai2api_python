#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Lapisan Abstrak Penyedia Dasar
Mendefinisikan spesifikasi antarmuka penyedia yang seragam
"""

import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, AsyncGenerator, Union
from dataclasses import dataclass

from app.models.schemas import OpenAIRequest, Message
from app.utils.logger import get_logger

logger = get_logger()


@dataclass
class ProviderConfig:
    """Konfigurasi Penyedia"""
    name: str
    api_endpoint: str
    timeout: int = 30
    headers: Optional[Dict[str, str]] = None
    extra_config: Optional[Dict[str, Any]] = None


@dataclass
class ProviderResponse:
    """Respon Penyedia"""
    success: bool
    content: str = ""
    error: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    extra_data: Optional[Dict[str, Any]] = None


class BaseProvider(ABC):
    """Kelas Abstrak Penyedia Dasar"""
    
    def __init__(self, config: ProviderConfig):
        """Inisialisasi Penyedia"""
        self.config = config
        self.name = config.name
        self.logger = get_logger()
        
    @abstractmethod
    async def chat_completion(
        self, 
        request: OpenAIRequest,
        **kwargs
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        """
        Antarmuka Penyelesaian Chat
        
        Args:
            request: Permintaan format OpenAI
            **kwargs: Parameter tambahan
            
        Returns:
            Non-streaming: Dict[str, Any] - Respon format OpenAI
            Streaming: AsyncGenerator[str, None] - Respon streaming format SSE
        """
        pass
    
    @abstractmethod
    async def transform_request(self, request: OpenAIRequest) -> Dict[str, Any]:
        """
        Mengubah permintaan OpenAI ke format penyedia spesifik
        
        Args:
            request: Permintaan format OpenAI
            
        Returns:
            Dict[str, Any]: Permintaan format penyedia spesifik
        """
        pass
    
    @abstractmethod
    async def transform_response(
        self, 
        response: Any, 
        request: OpenAIRequest
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        """
        Mengubah respon penyedia ke format OpenAI
        
        Args:
            response: Respon asli penyedia
            request: Permintaan asli (digunakan untuk membuat respon)
            
        Returns:
            Union[Dict[str, Any], AsyncGenerator[str, None]]: Respon format OpenAI
        """
        pass
    
    def get_supported_models(self) -> List[str]:
        """Mendapatkan daftar model yang didukung"""
        return []
    
    def create_chat_id(self) -> str:
        """Membuat ID chat"""
        return f"chatcmpl-{uuid.uuid4().hex}"
    
    def create_openai_chunk(
        self, 
        chat_id: str, 
        model: str, 
        delta: Dict[str, Any], 
        finish_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Membuat chunk respon streaming format OpenAI"""
        return {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
                "logprobs": None,
            }],
            "system_fingerprint": f"fp_{self.name}_001",
        }
    
    def create_openai_response(
        self,
        chat_id: str,
        model: str,
        content: str,
        usage: Optional[Dict[str, int]] = None
    ) -> Dict[str, Any]:
        """Membuat respon non-streaming format OpenAI"""
        return {
            "id": chat_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop",
                "logprobs": None,
            }],
            "usage": usage or {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            },
            "system_fingerprint": f"fp_{self.name}_001",
        }

    def create_openai_response_with_reasoning(
        self,
        chat_id: str,
        model: str,
        content: str,
        reasoning_content: str = None,
        usage: Optional[Dict[str, int]] = None
    ) -> Dict[str, Any]:
        """Membuat respon non-streaming format OpenAI dengan konten penalaran"""
        message = {
            "role": "assistant",
            "content": content
        }

        # Hanya tambahkan jika konten penalaran ada dan tidak kosong
        if reasoning_content and reasoning_content.strip():
            message["reasoning_content"] = reasoning_content

        return {
            "id": chat_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": "stop",
                "logprobs": None,
            }],
            "usage": usage or {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            },
            "system_fingerprint": f"fp_{self.name}_001",
        }

    async def format_sse_chunk(self, chunk: Dict[str, Any]) -> str:
        """Memformat chunk respon SSE"""
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    
    async def format_sse_done(self) -> str:
        """Memformat marker akhir SSE"""
        return "data: [DONE]\n\n"
    
    def log_request(self, request: OpenAIRequest):
        """Mencatat log permintaan"""
        self.logger.info(f"🔄 {self.name} Memproses permintaan: {request.model}")
        self.logger.debug(f"  Jumlah pesan: {len(request.messages)}")
        self.logger.debug(f"  Mode streaming: {request.stream}")
        
    def log_response(self, success: bool, error: Optional[str] = None):
        """Mencatat log respon"""
        if success:
            self.logger.info(f"✅ {self.name} Respon berhasil")
        else:
            self.logger.error(f"❌ {self.name} Respon gagal: {error}")
    
    def handle_error(self, error: Exception, context: str = "") -> Dict[str, Any]:
        """Penanganan error yang seragam"""
        error_msg = f"{self.name} {context} Error: {str(error)}"
        self.logger.error(error_msg)
        
        return {
            "error": {
                "message": error_msg,
                "type": "provider_error",
                "code": "internal_error"
            }
        }


class ProviderRegistry:
    """Registry Penyedia"""
    
    def __init__(self):
        self._providers: Dict[str, BaseProvider] = {}
        self._model_mapping: Dict[str, str] = {}
    
    def register(self, provider: BaseProvider, models: List[str]):
        """Mendaftarkan penyedia"""
        self._providers[provider.name] = provider
        for model in models:
            self._model_mapping[model] = provider.name
        logger.info(f"📝 Mendaftarkan penyedia: {provider.name}, model: {models}")
    
    def get_provider(self, model: str) -> Optional[BaseProvider]:
        """Mendapatkan penyedia berdasarkan model"""
        provider_name = self._model_mapping.get(model)
        if provider_name:
            return self._providers.get(provider_name)
        return None
    
    def get_provider_by_name(self, name: str) -> Optional[BaseProvider]:
        """Mendapatkan penyedia berdasarkan nama"""
        return self._providers.get(name)
    
    def list_models(self) -> List[str]:
        """Mendaftar semua model yang didukung"""
        return list(self._model_mapping.keys())
    
    def list_providers(self) -> List[str]:
        """Mendaftar semua penyedia"""
        return list(self._providers.keys())


# Registry penyedia global
provider_registry = ProviderRegistry()
