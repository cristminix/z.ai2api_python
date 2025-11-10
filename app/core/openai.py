#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time
import json
from typing import List, Dict, Any
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from app.core.config import settings
from app.models.schemas import OpenAIRequest, Message, ModelsResponse, Model, OpenAIResponse, Choice, Usage
from app.utils.logger import get_logger
from app.providers import get_provider_router
from app.utils.token_pool import get_token_pool

logger = get_logger()
router = APIRouter()

# Instance router provider global
provider_router = None


def get_provider_router_instance():
    """Mendapatkan instance router provider"""
    global provider_router
    if provider_router is None:
        provider_router = get_provider_router()
    return provider_router


def create_chunk(chat_id: str, model: str, delta: Dict[str, Any], finish_reason: str = None) -> Dict[str, Any]:
    """Membuat struktur chunk OpenAI standar"""
    return {
        "choices": [{
            "delta": delta,
            "finish_reason": finish_reason,
            "index": 0,
            "logprobs": None,
        }],
        "created": int(time.time()),
        "id": chat_id,
        "model": model,
        "object": "chat.completion.chunk",
        "system_fingerprint": "fp_zai_001",
    }


async def handle_non_stream_response(stream_response, request: OpenAIRequest) -> JSONResponse:
    """Menangani respons non-streaming"""
    logger.info("📄 Mulai menangani respons non-streaming")

    # Mengumpulkan semua data streaming
    full_content = []
    async for chunk_data in stream_response():
        if chunk_data.startswith("data: "):
            chunk_str = chunk_data[6:].strip()
            if chunk_str and chunk_str != "[DONE]":
                try:
                    chunk = json.loads(chunk_str)
                    if "choices" in chunk and chunk["choices"]:
                        choice = chunk["choices"][0]
                        if "delta" in choice and "content" in choice["delta"]:
                            content = choice["delta"]["content"]
                            if content:
                                full_content.append(content)
                except json.JSONDecodeError:
                    continue

    # Membangun respons
    response_data = OpenAIResponse(
        id=f"chatcmpl-{int(time.time())}",
        object="chat.completion",
        created=int(time.time()),
        model=request.model,
        choices=[Choice(
            index=0,
            message=Message(
                role="assistant",
                content="".join(full_content),
                tool_calls=None
            ),
            finish_reason="stop"
        )],
        usage=Usage(
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0
        )
    )

    logger.info("✅ Penanganan respons non-streaming selesai")
    return JSONResponse(content=response_data.model_dump(exclude_none=True))


@router.get("/v1/models")
async def list_models():
    """List available models from all providers"""
    try:
        router_instance = get_provider_router_instance()
        models_data = router_instance.get_models_list()
        return JSONResponse(content=models_data)
    except Exception as e:
        logger.error(f"❌ Gagal mendapatkan daftar model: {e}")
        # Mengembalikan daftar model default sebagai cadangan
        current_time = int(time.time())
        fallback_response = ModelsResponse(
            data=[
                Model(id=settings.GLM46_MODEL, created=current_time, owned_by="z.ai"),
                Model(id=settings.GLM46_THINKING_MODEL, created=current_time, owned_by="z.ai"),
                Model(id=settings.GLM46_SEARCH_MODEL, created=current_time, owned_by="z.ai"),
                Model(id=settings.GLM45_AIR_MODEL, created=current_time, owned_by="z.ai"),
            ]
        )
        return fallback_response


@router.post("/v1/chat/completions")
async def chat_completions(request: OpenAIRequest, authorization: str = Header(...)):
    """Handle chat completion requests with multi-provider architecture"""
    role = request.messages[0].role if request.messages else "unknown"
    logger.info(f"😶‍🌫️ Menerima permintaan klien - Model: {request.model}, Streaming: {request.stream}, Jumlah pesan: {len(request.messages)}, Peran: {role}, Jumlah tools: {len(request.tools) if request.tools else 0}")

    # Mendapatkan informasi provider (untuk statistik)
    provider = "unknown"

    try:
        # Validate API key (skip if SKIP_AUTH_TOKEN is enabled)
        if not settings.SKIP_AUTH_TOKEN:
            if not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

            api_key = authorization[7:]
            if api_key != settings.AUTH_TOKEN:
                raise HTTPException(status_code=401, detail="Invalid API key")

        # Menggunakan router multi-provider untuk menangani permintaan
        router_instance = get_provider_router_instance()

        # Mendapatkan informasi provider dari router
        provider_info = router_instance.get_provider_for_model(request.model)
        if provider_info:
            provider = provider_info.get("provider", "unknown")

        result = await router_instance.route_request(request)

        # Memeriksa apakah ada error
        if isinstance(result, dict) and "error" in result:
            error_info = result["error"]

            if error_info.get("code") == "model_not_found":
                raise HTTPException(status_code=404, detail=error_info["message"])
            else:
                raise HTTPException(status_code=500, detail=error_info["message"])

        # Menangani respons
        if request.stream:
            # Respons streaming
            if hasattr(result, '__aiter__'):
                # Hasil adalah async generator
                return StreamingResponse(
                    result,
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "Access-Control-Allow-Origin": "*",
                    }
                )
            else:
                # Hasil adalah dictionary, mungkin mengandung error
                raise HTTPException(status_code=500, detail="Expected streaming response but got non-streaming result")
        else:
            # Respons non-streaming
            if isinstance(result, dict):
                return JSONResponse(content=result)
            else:
                # Jika adalah async generator, perlu mengumpulkan semua konten
                return await handle_non_stream_response(result, request)

    except HTTPException as http_exc:
        # Melempar kembali HTTP exception
        raise
    except Exception as e:
        logger.error(f"❌ Gagal memproses permintaan: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
