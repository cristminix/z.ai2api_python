#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Z.AI Provider Adapter
"""

import json
import time
import uuid
import httpx
import hmac
import hashlib
import base64
import asyncio
from urllib.parse import urlencode
import os
import uuid
import random
from datetime import datetime
from typing import Dict, List, Any, Optional, AsyncGenerator, Union
from app.utils.user_agent import get_random_user_agent
from app.utils.fe_version import get_latest_fe_version
from app.utils.signature import generate_signature
from app.providers.base import BaseProvider, ProviderConfig
from app.models.schemas import OpenAIRequest, Message
from app.core.config import settings
from app.utils.logger import get_logger
from app.utils.token_pool import get_token_pool
from app.utils.tool_call_handler import (
    process_messages_with_tools,
    parse_and_extract_tool_calls,
)

logger = get_logger()

def generate_uuid() -> str:
    """Generate UUID v4"""
    return str(uuid.uuid4())

def get_zai_dynamic_headers(chat_id: str = "") -> Dict[str, str]:
    """Generate Z.AI specific dynamic browser headers"""
    browser_choices = ["chrome", "chrome", "chrome", "edge", "edge", "firefox", "safari"]
    browser_type = random.choice(browser_choices)
    user_agent = get_random_user_agent(browser_type)
    fe_version = get_latest_fe_version()

    chrome_version = "139"
    edge_version = "139"

    if "Chrome/" in user_agent:
        try:
            chrome_version = user_agent.split("Chrome/")[1].split(".")[0]
        except:
            pass

    if "Edg/" in user_agent:
        try:
            edge_version = user_agent.split("Edg/")[1].split(".")[0]
            sec_ch_ua = f'"Microsoft Edge";v="{edge_version}", "Chromium";v="{chrome_version}", "Not_A Brand";v="24"'
        except:
            sec_ch_ua = f'"Not_A Brand";v="8", "Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}"'
    elif "Firefox/" in user_agent:
        sec_ch_ua = None
    else:
        sec_ch_ua = f'"Not_A Brand";v="8", "Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}"'

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "User-Agent": user_agent,
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        "X-FE-Version": fe_version,
        "Origin": "https://chat.z.ai",
    }

    if sec_ch_ua:
        headers["sec-ch-ua"] = sec_ch_ua
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = '"Windows"'

    if chat_id:
        headers["Referer"] = f"https://chat.z.ai/c/{chat_id}"
    else:
        headers["Referer"] = "https://chat.z.ai/"

    return headers

def _urlsafe_b64decode(data: str) -> bytes:
    """Decode a URL-safe base64 string with proper padding."""
    if isinstance(data, str):
        data_bytes = data.encode("utf-8")
    else:
        data_bytes = data
    padding = b"=" * (-len(data_bytes) % 4)
    return base64.urlsafe_b64decode(data_bytes + padding)


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    """Decode JWT payload without verification to extract metadata."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload_raw = _urlsafe_b64decode(parts[1])
        return json.loads(payload_raw.decode("utf-8", errors="ignore"))
    except Exception:
        return {}


def _extract_user_id_from_token(token: str) -> str:
    """Extract user_id from a JWT's payload. Fallback to 'guest'."""
    payload = _decode_jwt_payload(token) if token else {}
    for key in ("id", "user_id", "uid", "sub"):
        val = payload.get(key)
        if isinstance(val, (str, int)) and str(val):
            return str(val)
    return "guest"



class ZAIProvider(BaseProvider):
    """Z.AI Provider"""
    
    def __init__(self):
        config = ProviderConfig(
            name="zai",
            api_endpoint=settings.API_ENDPOINT,
            timeout=30,
            headers=get_zai_dynamic_headers()
        )
        super().__init__(config)
        
        # Z.AI specific configuration
        self.base_url = "https://chat.z.ai"
        self.auth_url = f"{self.base_url}/api/v1/auths/"
        
        # Pemetaan model
        self.model_mapping = {
            settings.GLM45_MODEL: "0727-360B-API",  # GLM-4.5
            settings.GLM45_THINKING_MODEL: "0727-360B-API",  # GLM-4.5-Thinking
            settings.GLM45_SEARCH_MODEL: "0727-360B-API",  # GLM-4.5-Search
            settings.GLM45_AIR_MODEL: "0727-106B-API",  # GLM-4.5-Air
            settings.GLM45V_MODEL: "glm-4.5v",  # GLM-4.5V multimodal
            settings.GLM46_MODEL: "GLM-4-6-API-V1",  # GLM-4.6
            settings.GLM46_THINKING_MODEL: "GLM-4-6-API-V1",  # GLM-4.6-Thinking
            settings.GLM46_SEARCH_MODEL: "GLM-4-6-API-V1",  # GLM-4.6-Search
            settings.GLM46_ADVANCED_SEARCH_MODEL: "GLM-4-6-API-V1",  # GLM-4.6-advanced-search
        }
    
    def get_supported_models(self) -> List[str]:
        """Get supported model list"""
        return [
            settings.GLM45_MODEL,
            settings.GLM45_THINKING_MODEL,
            settings.GLM45_SEARCH_MODEL,
            settings.GLM45_AIR_MODEL,
            settings.GLM45V_MODEL,
            settings.GLM46_MODEL,
            settings.GLM46_THINKING_MODEL,
            settings.GLM46_SEARCH_MODEL,
            settings.GLM46_ADVANCED_SEARCH_MODEL,
        ]

    def _get_proxy_config(self) -> Optional[str]:
        """Get proxy configuration from settings"""
        # In httpx 0.28.1, proxy parameter expects a single URL string
        # Support HTTP_PROXY, HTTPS_PROXY and SOCKS5_PROXY
        
        if settings.HTTPS_PROXY:
            self.logger.info(f"🔄 Using HTTPS proxy: {settings.HTTPS_PROXY}")
            return settings.HTTPS_PROXY

        if settings.HTTP_PROXY:
            self.logger.info(f"🔄 Using HTTP proxy: {settings.HTTP_PROXY}")
            return settings.HTTP_PROXY

        if settings.SOCKS5_PROXY:
            self.logger.info(f"🔄 Using SOCKS5 proxy: {settings.SOCKS5_PROXY}")
            return settings.SOCKS5_PROXY

        return None

    async def get_token(self) -> str:
        """Mendapatkan token autentikasi"""
        # Jika mode anonim diaktifkan, hanya coba mendapatkan token tamu
        if settings.ANONYMOUS_MODE:
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    headers = get_zai_dynamic_headers()
                    self.logger.debug(f"Attempting to get guest token (attempt {retry_count + 1}): {self.auth_url}")
                    self.logger.debug(f"Request headers: {headers}")

                    # Get proxy configuration
                    proxies = self._get_proxy_config()

                    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, proxy=proxies) as client:
                        response = await client.get(self.auth_url, headers=headers)
                        
                        self.logger.debug(f"Kode status respons: {response.status_code}")
                        self.logger.debug(f"Header respons: {dict(response.headers)}")
                        
                        if response.status_code == 200:
                            data = response.json()
                            self.logger.debug(f"Data respons: {data}")
                            
                            token = data.get("token", "")
                            if token:
                                # Menentukan jenis token (dengan memeriksa email atau user_id)
                                email = data.get("email", "")
                                is_guest = "@guest.com" in email or "Guest-" in email
                                token_type = "Pengguna anonim" if is_guest else "Pengguna terautentikasi"
                                self.logger.info(f"✅ Pengambilan token berhasil ({token_type}): {token[:20]}...")
                                return token
                            else:
                                self.logger.warning(f"Field token tidak ditemukan dalam respons: {data}")
                        elif response.status_code == 405:
                            # WAF interception
                            self.logger.error(f"🚫 Permintaan diblokir oleh WAF (kode status 405), header permintaan mungkin diidentifikasi sebagai tidak normal, silakan coba lagi nanti...")
                            break
                        else:
                            self.logger.warning(f"Permintaan HTTP gagal, kode status: {response.status_code}")
                            try:
                                error_data = response.json()
                                self.logger.warning(f"Respons error: {error_data}")
                            except:
                                self.logger.warning(f"Teks respons error: {response.text}")
                                
                except httpx.TimeoutException as e:
                    self.logger.warning(f"Request timeout (attempt {retry_count + 1}): {e}")
                except httpx.ConnectError as e:
                    self.logger.warning(f"Connection error (attempt {retry_count + 1}): {e}")
                except httpx.HTTPStatusError as e:
                    self.logger.warning(f"HTTP status error (attempt {retry_count + 1}): {e}")
                except json.JSONDecodeError as e:
                    self.logger.warning(f"JSON parsing error (attempt {retry_count + 1}): {e}")
                except Exception as e:
                    self.logger.warning(f"Failed to get guest token asynchronously (attempt {retry_count + 1}): {e}")
                    import traceback
                    self.logger.debug(f"错误堆栈: {traceback.format_exc()}")
                
                retry_count += 1
                if retry_count < max_retries:
                    self.logger.info(f"Menunggu 2 detik sebelum mencoba kembali...")
                    await asyncio.sleep(2)

            # In anonymous mode, if getting guest token fails, return empty
            self.logger.error("❌ Gagal mendapatkan token tamu dalam mode anonim, sudah dicoba 3 kali")
            return ""

        # Mode non-anonim: pertama gunakan pool token untuk mendapatkan token cadangan
        token_pool = get_token_pool()
        if token_pool:
            token = token_pool.get_next_token()
            if token:
                self.logger.debug(f"Mendapatkan token dari pool: {token[:20]}...")
                return token

        # If token pool is empty or no available tokens, use configured AUTH_TOKEN
        if settings.AUTH_TOKEN and settings.AUTH_TOKEN != "sk-your-api-key":
            self.logger.debug(f"Using configured AUTH_TOKEN")
            return settings.AUTH_TOKEN

        self.logger.error("❌ Tidak bisa mendapatkan token autentikasi yang valid")
        return ""
    
    def mark_token_failure(self, token: str, error: Exception = None):
        """Tandai penggunaan token sebagai gagal"""
        token_pool = get_token_pool()
        if token_pool:
            token_pool.mark_token_failure(token, error)

    async def upload_image(self, data_url: str, chat_id: str, token: str, user_id: str) -> Optional[Dict]:
        """Upload base64 encoded image to Z.AI server

        Args:
            data_url: Image data in data:image/xxx;base64,... format
            chat_id: Current conversation ID
            token: Authentication token
            user_id: User ID

        Returns:
            Return complete file information dictionary on success, None on failure
        """
        if settings.ANONYMOUS_MODE or not data_url.startswith("data:"):
            return None

        try:
            # Mengurai data URL
            header, encoded = data_url.split(",", 1)
            mime_type = header.split(";")[0].split(":")[1] if ":" in header else "image/jpeg"

            # Mendekode data base64
            image_data = base64.b64decode(encoded)
            filename = str(uuid.uuid4())

            self.logger.debug(f"📤 Mengunggah gambar: {filename}, ukuran: {len(image_data)} byte")

            # Membangun permintaan unggah
            upload_url = f"{self.base_url}/api/v1/files/"
            headers = {
                "Accept": "*/*",
                "Accept-Language": "id-ID,id;q=0.9",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Origin": f"{self.base_url}",
                "Pragma": "no-cache",
                "Referer": f"{self.base_url}/c/{chat_id}",
                "Sec-Ch-Ua": '"Microsoft Edge";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
                "Authorization": f"Bearer {token}",
            }

            # Get proxy configuration
            proxies = self._get_proxy_config()

            # Menggunakan httpx untuk mengunggah file
            async with httpx.AsyncClient(timeout=30.0, proxy=proxies) as client:
                files = {
                    "file": (filename, image_data, mime_type)
                }
                response = await client.post(upload_url, files=files, headers=headers)

                if response.status_code == 200:
                    result = response.json()
                    file_id = result.get("id")
                    file_name = result.get("filename")
                    file_size = len(image_data)

                    self.logger.info(f"✅ Gambar berhasil diunggah: {file_id}_{file_name}")

                    # Mengembalikan informasi file yang sesuai dengan format Z.AI
                    current_timestamp = int(time.time())
                    return {
                        "type": "image",
                        "file": {
                            "id": file_id,
                            "user_id": user_id,
                            "hash": None,
                            "filename": file_name,
                            "data": {},
                            "meta": {
                                "name": file_name,
                                "content_type": mime_type,
                                "size": file_size,
                                "data": {},
                            },
                            "created_at": current_timestamp,
                            "updated_at": current_timestamp
                        },
                        "id": file_id,
                        "url": f"/api/v1/files/{file_id}/content",
                        "name": file_name,
                        "status": "uploaded",
                        "size": file_size,
                        "error": "",
                        "itemId": str(uuid.uuid4()),
                        "media": "image"
                    }
                else:
                    self.logger.error(f"❌ Unggah gambar gagal: {response.status_code} - {response.text}")
                    return None

        except Exception as e:
            self.logger.error(f"❌ Error unggah gambar: {e}")
            return None

    async def transform_request(self, request: OpenAIRequest) -> Dict[str, Any]:
        """Mengkonversi permintaan OpenAI ke format Z.AI"""
        self.logger.info(f"🔄 Converting OpenAI request to Z.AI format: {request.model}")

        # Mendapatkan token autentikasi
        token = await self.get_token()
        user_id = _extract_user_id_from_token(token)

        # Menghasilkan chat_id (digunakan untuk unggah gambar)
        chat_id = generate_uuid()

        # Memproses format pesan - Z.AI menggunakan field files terpisah untuk mengirimkan gambar
        messages = []
        files = []  # Simpan informasi file gambar yang diunggah

        for msg in request.messages:
            if isinstance(msg.content, str):
                # Pesan teks murni
                messages.append({
                    "role": msg.role,
                    "content": msg.content
                })
            elif isinstance(msg.content, list):
                # Konten multimodal: memisahkan teks dan gambar
                text_parts = []
                image_parts = []  # Simpan referensi gambar

                for part in msg.content:
                    if hasattr(part, 'type'):
                        if part.type == 'text' and hasattr(part, 'text'):
                            # Bagian teks
                            text_parts.append(part.text or '')
                        elif part.type == 'image_url' and hasattr(part, 'image_url'):
                            # Bagian gambar - ekstrak dan unggah
                            image_url = None
                            if hasattr(part.image_url, 'url'):
                                image_url = part.image_url.url
                            elif isinstance(part.image_url, dict) and 'url' in part.image_url:
                                image_url = part.image_url['url']

                            if image_url:
                                self.logger.debug(f"✅ Gambar terdeteksi: {image_url[:50]}...")

                                # Jika gambar berkode base64, unggah dan tambahkan ke array files
                                if image_url.startswith("data:") and not settings.ANONYMOUS_MODE:
                                    self.logger.info(f"🔄 Mengunggah gambar base64 ke server Z.AI")
                                    file_info = await self.upload_image(image_url, chat_id, token, user_id)

                                    if file_info:
                                        files.append(file_info)
                                        self.logger.info(f"✅ Gambar telah ditambahkan ke array files")

                                        # Menyimpan referensi gambar dalam pesan
                                        image_ref = f"{file_info['id']}_{file_info['name']}"
                                        image_parts.append({
                                            "type": "image_url",
                                            "image_url": {
                                                "url": image_ref
                                            }
                                        })
                                        self.logger.debug(f"📎 Referensi gambar: {image_ref}")
                                    else:
                                        # Unggah gagal, tambahkan pesan error
                                        self.logger.warning(f"⚠️ Unggah gambar gagal")
                                        text_parts.append("[Pesan sistem: Unggah gambar gagal]")
                                else:
                                    # Bukan gambar base64 atau mode anonim, gunakan URL asli langsung
                                    if not settings.ANONYMOUS_MODE:
                                        self.logger.warning(f"⚠️ Bukan gambar base64 atau mode anonim, mempertahankan URL asli")
                                    image_parts.append({
                                        "type": "image_url",
                                        "image_url": {"url": image_url}
                                    })
                    elif isinstance(part, dict):
                        # Konten dalam format kamus langsung
                        if part.get('type') == 'text':
                            text_parts.append(part.get('text', ''))
                        elif part.get('type') == 'image_url':
                            image_url = part.get('image_url', {}).get('url', '')
                            if image_url:
                                self.logger.debug(f"✅ Gambar terdeteksi: {image_url[:50]}...")

                                # Jika gambar berkode base64, unggah dan tambahkan ke array files
                                if image_url.startswith("data:") and not settings.ANONYMOUS_MODE:
                                    self.logger.info(f"🔄 Mengunggah gambar base64 ke server Z.AI")
                                    file_info = await self.upload_image(image_url, chat_id, token, user_id)

                                    if file_info:
                                        files.append(file_info)
                                        self.logger.info(f"✅ Gambar telah ditambahkan ke array files")

                                        # Menyimpan referensi gambar dalam pesan
                                        image_ref = f"{file_info['id']}_{file_info['name']}"
                                        image_parts.append({
                                            "type": "image_url",
                                            "image_url": {
                                                "url": image_ref
                                            }
                                        })
                                        self.logger.debug(f"📎 Referensi gambar: {image_ref}")
                                    else:
                                        # Unggah gagal, tambahkan pesan error
                                        self.logger.warning(f"⚠️ Unggah gambar gagal")
                                        text_parts.append("[Pesan sistem: Unggah gambar gagal]")
                                else:
                                    # Bukan gambar base64 atau mode anonim
                                    if not settings.ANONYMOUS_MODE:
                                        self.logger.warning(f"⚠️ Bukan gambar base64 atau mode anonim, mempertahankan URL asli")
                                    image_parts.append({
                                        "type": "image_url",
                                        "image_url": {"url": image_url}
                                    })
                    elif isinstance(part, str):
                        # Bagian string murni
                        text_parts.append(part)

                # Membangun konten pesan multimodal
                message_content = []

                # Menambahkan bagian teks
                combined_text = " ".join(text_parts).strip()
                if combined_text:
                    message_content.append({
                        "type": "text",
                        "text": combined_text
                    })

                # Menambahkan bagian gambar (mempertahankan referensi gambar dalam pesan)
                message_content.extend(image_parts)

                # Hanya menambahkan pesan jika ada konten
                if message_content:
                    messages.append({
                        "role": msg.role,
                        "content": message_content  # ✅ Array konten multimodal
                    })
        
        # Determine requested model characteristics
        # Mengekstrak teks pesan pengguna terakhir untuk penandatanganan
        last_user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, str):
                    # Pesan teks murni
                    last_user_text = content
                    break
                elif isinstance(content, list):
                    # Pesan multimodal: hanya ekstrak bagian teks untuk penandatanganan
                    texts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                    last_user_text = " ".join([t for t in texts if t]).strip()
                    break
        requested_model = request.model
        is_thinking = "-thinking" in requested_model.casefold()
        is_search = "-search" in requested_model.casefold()
        is_advanced_search = requested_model == settings.GLM46_ADVANCED_SEARCH_MODEL
        is_air = "-air" in requested_model.casefold()

        # Mendapatkan ID model upstream
        upstream_model_id = self.model_mapping.get(requested_model, "0727-360B-API")

        # ⚠️ Penting: proses pemanggilan tool sebelum membangun body!
        # Memproses dukungan tool - menggunakan metode injeksi prompt
        if settings.TOOL_SUPPORT and not is_thinking and request.tools:
            tool_choice = getattr(request, 'tool_choice', 'auto') or 'auto'
            messages = process_messages_with_tools(
                messages=messages,
                tools=request.tools,
                tool_choice=tool_choice
            )
            self.logger.info(f"🔧 Pemanggilan tool diinjeksi melalui injeksi prompt: {len(request.tools)} tool")

        # Membangun daftar server MCP
        mcp_servers = []
        if is_advanced_search:
            mcp_servers.append("advanced-search")
            self.logger.info("🔍 Model pencarian lanjutan terdeteksi, menambahkan server MCP advanced-search")

        # Membangun body permintaan upstream
        body = {
            "stream": True,  # Selalu menggunakan streaming
            "model": upstream_model_id,
            "messages": messages,  # ✅ messages sudah mengandung prompt tool
            "signature_prompt": last_user_text,  # Pesan pengguna terakhir untuk penandatanganan
            "files": files,  # Array file gambar
            "params": {},
            "features": {
                "image_generation": False,
                "web_search": is_search or is_advanced_search,
                "auto_web_search": is_search or is_advanced_search,
                "preview_mode": is_search or is_advanced_search,
                "flags": [],
                "features": [
                    {
                        "type": "mcp",
                        "server": "vibe-coding",
                        "status": "hidden"
                    },
                    {
                        "type": "mcp",
                        "server": "ppt-maker",
                        "status": "hidden"
                    },
                    {
                        "type": "mcp",
                        "server": "image-search",
                        "status": "hidden"
                    },
                    {
                        "type": "mcp",
                        "server": "deep-research",
                        "status": "hidden"
                    },
                    {
                        "type": "tool_selector",
                        "server": "tool_selector",
                        "status": "hidden"
                    },
                    {
                        "type": "mcp",
                        "server": "advanced-search",
                        "status": "hidden"
                    }
                ],
                "enable_thinking": is_thinking,
            },
            "background_tasks": {
                "title_generation": False,
                "tags_generation": False,
            },
            "mcp_servers": mcp_servers,
            "variables": {
                "{{USER_NAME}}": "Guest",
                "{{USER_LOCATION}}": "Unknown",
                "{{CURRENT_DATETIME}}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "{{CURRENT_DATE}}": datetime.now().strftime("%Y-%m-%d"),
                "{{CURRENT_TIME}}": datetime.now().strftime("%H:%M:%S"),
                "{{CURRENT_WEEKDAY}}": datetime.now().strftime("%A"),
                "{{CURRENT_TIMEZONE}}": "Asia/Shanghai",
                "{{USER_LANGUAGE}}": "zh-CN",
            },
            "model_item": {
                "id": upstream_model_id,
                "name": requested_model,
                "owned_by": "z.ai"
            },
            "chat_id": chat_id,
            "id": generate_uuid(),
        }

        # Tidak mengirimkan tools ke upstream, menggunakan metode prompt engineering
        body["tools"] = None
        
        # Memproses parameter lain
        if request.temperature is not None:
            body["params"]["temperature"] = request.temperature
        if request.max_tokens is not None:
            body["params"]["max_tokens"] = request.max_tokens
        
        # Penandatanganan HMAC lapisan ganda untuk metadata dan header
        user_id = _extract_user_id_from_token(token)
        timestamp_ms = int(time.time() * 1000)
        request_id = generate_uuid()
        fe_version = get_latest_fe_version()
        try:
            signing_metadata = f"requestId,{request_id},timestamp,{timestamp_ms},user_id,{user_id}"
            prompt_for_signature = last_user_text or ""
            signature_result = generate_signature(
                e=signing_metadata,
                t=prompt_for_signature,
                s=timestamp_ms,
            )
            signature = signature_result["signature"]
            logger.debug(f"[Z.AI] Pembuatan tanda tangan berhasil: {signature[:16]}... (user_id={user_id}, request_id={request_id})")
        except Exception as e:
            logger.error(f"[Z.AI] Pembuatan tanda tangan gagal: {e}")
            signature = ""

        # Membangun header permintaan
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-FE-Version": fe_version,
            "X-Signature": signature,
        }

        query_params = {
            "timestamp": str(timestamp_ms),
            "requestId": request_id,
            "user_id": user_id,
            "token": token,
            "version": "0.0.1",
            "platform": "web",
            "current_url": f"https://chat.z.ai/c/{chat_id}",
            "pathname": f"/c/{chat_id}",
            "signature_timestamp": str(timestamp_ms),
        }
        signed_url = f"{self.config.api_endpoint}?{urlencode(query_params)}"

        # Mencatat detail permintaan untuk debugging
        logger.debug(f"[Z.AI] Header permintaan: Authorization=Bearer *****, X-Signature={signature[:16] if signature else '(kosong)'}...")
        logger.debug(f"[Z.AI] Parameter URL: timestamp={timestamp_ms}, requestId={request_id}, user_id={user_id}")
        
        # Menyimpan token saat ini untuk penanganan error
        self._current_token = token

        return {
            "url": signed_url,
            "headers": headers,
            "body": body,
            "token": token,
            "chat_id": chat_id,
            "model": requested_model
        }
    
    async def chat_completion(
        self,
        request: OpenAIRequest,
        **kwargs
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        """Antarmuka penyelesaian obrolan"""
        self.log_request(request)

        try:
            # Mengkonversi permintaan
            transformed = await self.transform_request(request)

            # Mengembalikan respons berdasarkan jenis permintaan
            if request.stream:
                # Respons streaming
                return self._create_stream_response(request, transformed)
            else:
                # Get proxy configuration
                proxies = self._get_proxy_config()

                # Respons non-streaming
                async with httpx.AsyncClient(timeout=30.0, proxy=proxies) as client:
                    response = await client.post(
                        transformed["url"],
                        headers=transformed["headers"],
                        json=transformed["body"]
                    )

                    if not response.is_success:
                        error_msg = f"Z.AI API Error: {response.status_code}"
                        self.log_response(False, error_msg)
                        return self.handle_error(Exception(error_msg))

                    return await self.transform_response(response, request, transformed)

        except Exception as e:
            self.log_response(False, str(e))
            return self.handle_error(e, "Pemrosesan permintaan")

    
    async def _create_stream_response(
        self,
        request: OpenAIRequest,
        transformed: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:

        current_token = transformed.get("token", "")
        try:
            # Get proxy configuration
            proxies = self._get_proxy_config()

            async with httpx.AsyncClient(
                timeout=60.0,
                http2=True,
                proxy=proxies,
            ) as client:
                # self.logger.info(f"🎯 Sending request to Z.AI: {transformed['url']}")
                # self.logger.info(f"📦 请求体 model: {transformed['body']['model']}")
                # self.logger.info(f"📦 请求体 messages: {json.dumps(transformed['body']['messages'], ensure_ascii=False)}")
                async with client.stream(
                    "POST",
                    transformed["url"],
                    json=transformed["body"],
                    headers=transformed["headers"],
                ) as response:
                    if response.status_code != 200:
                        self.logger.error(f"❌ Upstream returned error: {response.status_code}")
                        error_text = await response.aread()
                        error_msg = error_text.decode('utf-8', errors='ignore')
                        if error_msg:
                            self.logger.error(f"❌ Error details: {error_msg}")

                        # Special handling for status code 405 (WAF blocking)
                        if response.status_code == 405:
                            self.logger.error(f"🚫 Request blocked by upstream WAF, possibly due to request headers or signature anomalies, please try again later...")
                            error_response = {
                                "error": {
                                    "message": "Request blocked by upstream WAF (405 Method Not Allowed), possibly due to request headers or signature anomalies, please try again later...",
                                    "type": "waf_blocked",
                                    "code": 405
                                }
                            }
                        else:
                            error_response = {
                                "error": {
                                    "message": f"Upstream error: {response.status_code}",
                                    "type": "upstream_error",
                                    "code": response.status_code
                                }
                            }
                        yield f"data: {json.dumps(error_response)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    if current_token and not settings.ANONYMOUS_MODE:
                        token_pool = get_token_pool()
                        if token_pool:
                            token_pool.mark_token_success(current_token)

                    chat_id = transformed["chat_id"]
                    model = transformed["model"]
                    async for chunk in self._handle_stream_response(response, chat_id, model, request, transformed):
                        yield chunk
                    return
        except Exception as e:
            self.logger.error(f"❌ Stream processing error: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            if current_token and not settings.ANONYMOUS_MODE:
                self.mark_token_failure(current_token, e)
            error_response = {
                "error": {
                    "message": str(e),
                    "type": "stream_error"
                }
            }
            yield f"data: {json.dumps(error_response)}\n\n"
            yield "data: [DONE]\n\n"
            return

    async def transform_response(
        self, 
        response: httpx.Response, 
        request: OpenAIRequest,
        transformed: Dict[str, Any]
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        """Mengkonversi respons Z.AI ke format OpenAI"""
        chat_id = transformed["chat_id"]
        model = transformed["model"]
        
        if request.stream:
            return self._handle_stream_response(response, chat_id, model, request, transformed)
        else:
            return await self._handle_non_stream_response(response, chat_id, model)
    
    async def _handle_stream_response(
        self,
        response: httpx.Response,
        chat_id: str,
        model: str,
        request: OpenAIRequest,
        transformed: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        """Memproses respons streaming Z.AI"""
        self.logger.info(f"✅ Respons Z.AI berhasil, mulai memproses stream SSE")

        # Memeriksa apakah pemanggilan tool diaktifkan (dengan memeriksa permintaan asli)
        has_tools = settings.TOOL_SUPPORT and request.tools is not None and len(request.tools) > 0

        # Buffer konten akumulatif, untuk ekstraksi pemanggilan tool
        buffered_content = ""
        has_sent_role = False

        # Status pemrosesan
        has_thinking = False
        thinking_signature = None

        # Memproses stream SSE
        buffer = ""
        line_count = 0
        self.logger.debug("📡 Mulai menerima data stream SSE...")

        try:
            async for line in response.aiter_lines():
                line_count += 1
                if not line:
                    continue

                # Akumulasi ke buffer untuk memproses baris data lengkap
                buffer += line + "\n"

                # Memeriksa apakah ada baris data lengkap
                while "\n" in buffer:
                    current_line, buffer = buffer.split("\n", 1)
                    if not current_line.strip():
                        continue

                    if current_line.startswith("data:"):
                        chunk_str = current_line[5:].strip()
                        if not chunk_str or chunk_str == "[DONE]":
                            if chunk_str == "[DONE]":
                                yield "data: [DONE]\n\n"
                            continue

                        self.logger.debug(f"📦 Mengurai chunk data: {chunk_str[:1000]}..." if len(chunk_str) > 1000 else f"📦 Mengurai chunk data: {chunk_str}")

                        try:
                            chunk = json.loads(chunk_str)

                            if chunk.get("type") == "chat:completion":
                                data = chunk.get("data", {})
                                phase = data.get("phase")

                                # Mencatat setiap fase (hanya saat fase berubah)
                                if phase and phase != getattr(self, '_last_phase', None):
                                    self.logger.info(f"📈 SSE Phase: {phase}")
                                    self._last_phase = phase

                                # Memproses konten berpikir
                                if phase == "thinking":
                                    if not has_thinking:
                                        has_thinking = True
                                        # Mengirim peran awal
                                        role_chunk = self.create_openai_chunk(
                                            chat_id,
                                            model,
                                            {"role": "assistant"}
                                        )
                                        yield await self.format_sse_chunk(role_chunk)

                                    delta_content = data.get("delta_content", "")
                                    if delta_content:
                                        # Memproses format konten berpikir
                                        if delta_content.startswith("<details"):
                                            content = (
                                                delta_content.split("</summary>\n>")[-1].strip()
                                                if "</summary>\n>" in delta_content
                                                else delta_content
                                            )
                                        else:
                                            content = delta_content

                                        thinking_chunk = self.create_openai_chunk(
                                            chat_id,
                                            model,
                                            {
                                                "role": "assistant",
                                                "reasoning_content": content
                                            }
                                        )
                                        yield await self.format_sse_chunk(thinking_chunk)

                                # Memproses konten jawaban
                                elif phase == "answer":
                                    delta_content = data.get("delta_content", "")
                                    edit_content = data.get("edit_content", "")

                                    # Mengakumulasi konten (untuk ekstraksi pemanggilan tool)
                                    if delta_content:
                                        buffered_content += delta_content
                                    elif edit_content:
                                        buffered_content = edit_content

                                    # Jika mengandung usage, berarti streaming berakhir
                                    if data.get("usage"):
                                        usage = data["usage"]
                                        self.logger.info(f"📦 Respons selesai - Statistik penggunaan: {json.dumps(usage)}")

                                        # Mencoba mengekstrak tool_calls dari buffer
                                        tool_calls = None

                                        if has_tools:
                                            tool_calls, _ = parse_and_extract_tool_calls(buffered_content)

                                        if tool_calls:
                                            # Pemanggilan tool ditemukan
                                            self.logger.info(f"🔧 Extracted {len(tool_calls)} tool calls from response")

                                            if not has_sent_role:
                                                role_chunk = self.create_openai_chunk(
                                                    chat_id,
                                                    model,
                                                    {"role": "assistant"}
                                                )
                                                yield await self.format_sse_chunk(role_chunk)
                                                has_sent_role = True

                                            # Mengirim pemanggilan tool
                                            for idx, tc in enumerate(tool_calls):
                                                tool_chunk = self.create_openai_chunk(
                                                    chat_id,
                                                    model,
                                                    {
                                                        "role": "assistant",
                                                        "tool_calls": [{
                                                            "index": idx,
                                                            "id": tc.get("id", f"call_{idx}"),
                                                            "type": "function",
                                                            "function": {
                                                                "name": tc.get("function", {}).get("name", ""),
                                                                "arguments": tc.get("function", {}).get("arguments", "")
                                                            }
                                                        }]
                                                    }
                                                )
                                                yield await self.format_sse_chunk(tool_chunk)

                                            # Mengirim chunk penyelesaian
                                            finish_chunk = self.create_openai_chunk(
                                                chat_id,
                                                model,
                                                {"role": "assistant"},
                                                "tool_calls"
                                            )
                                            finish_chunk["usage"] = usage
                                            yield await self.format_sse_chunk(finish_chunk)
                                            yield "data: [DONE]\n\n"

                                        else:
                                            # Tidak ada pemanggilan tool, konten streaming sudah dikirim di output inkremental di atas
                                            # Di sini hanya perlu mengirim chunk finish, jangan kirim konten lagi
                                            if not has_sent_role and not has_thinking:
                                                role_chunk = self.create_openai_chunk(
                                                    chat_id,
                                                    model,
                                                    {"role": "assistant"}
                                                )
                                                yield await self.format_sse_chunk(role_chunk)
                                                has_sent_role = True

                                            finish_chunk = self.create_openai_chunk(
                                                chat_id,
                                                model,
                                                {"role": "assistant", "content": ""},
                                                "stop"
                                            )
                                            finish_chunk["usage"] = usage
                                            yield await self.format_sse_chunk(finish_chunk)
                                            yield "data: [DONE]\n\n"
                                    else:
                                        # Selama proses streaming, keluarkan konten jawaban (bahkan jika ada pemanggilan tool harus ditampilkan)
                                        # Memproses akhir berpikir dan awal jawaban
                                        if edit_content and "</details>\n" in edit_content:
                                            if has_thinking:
                                                # Mengirim tanda tangan berpikir
                                                thinking_signature = str(int(time.time() * 1000))
                                                sig_chunk = self.create_openai_chunk(
                                                    chat_id,
                                                    model,
                                                    {
                                                        "role": "assistant",
                                                        "thinking": {
                                                            "content": "",
                                                            "signature": thinking_signature,
                                                        }
                                                    }
                                                )
                                                yield await self.format_sse_chunk(sig_chunk)

                                            # Mengekstrak konten jawaban
                                            content_after = edit_content.split("</details>\n")[-1]
                                            if content_after:
                                                content_chunk = self.create_openai_chunk(
                                                    chat_id,
                                                    model,
                                                    {
                                                        "role": "assistant",
                                                        "content": content_after
                                                    }
                                                )
                                                yield await self.format_sse_chunk(content_chunk)

                                        # Memproses konten inkremental
                                        elif delta_content:
                                            if not has_sent_role and not has_thinking:
                                                role_chunk = self.create_openai_chunk(
                                                    chat_id,
                                                    model,
                                                    {"role": "assistant"}
                                                )
                                                yield await self.format_sse_chunk(role_chunk)
                                                has_sent_role = True

                                            content_chunk = self.create_openai_chunk(
                                                chat_id,
                                                model,
                                                {
                                                    "role": "assistant",
                                                    "content": delta_content
                                                }
                                            )
                                            output_data = await self.format_sse_chunk(content_chunk)
                                            self.logger.debug(f"➡️ Mengeluarkan chunk konten ke klien: {output_data}")
                                            yield output_data

                        except json.JSONDecodeError as e:
                            self.logger.debug(f"❌ Error parsing JSON: {e}, konten: {chunk_str[:1000]}")
                        except Exception as e:
                            self.logger.error(f"❌ Error memproses chunk: {e}")

            self.logger.info(f"✅ Pemrosesan stream SSE selesai, diproses {line_count} baris data")

        except Exception as e:
            self.logger.error(f"❌ Error memproses respons streaming: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            # Mengirim chunk akhir error
            yield await self.format_sse_chunk(
                self.create_openai_chunk(chat_id, model, {}, "stop")
            )
            yield "data: [DONE]\n\n"
    
    async def _handle_non_stream_response(
        self,
        response: httpx.Response,
        chat_id: str,
        model: str
    ) -> Dict[str, Any]:
        """Memproses respons non-streaming

        Penjelasan: upstream selalu mengembalikan dalam bentuk SSE (transform_request tetap stream=True),
        oleh karena itu di sini perlu menggabungkan chunk data: dari aiter_lines(), mengekstrak usage, konten berpikir, dan konten jawaban,
        dan akhirnya menghasilkan respons format OpenAI sekali pakai.
        """
        final_content = ""
        reasoning_content = ""
        all_content_buffer = ""  # Buffer untuk menyimpan semua konten guna ekstraksi tool_call
        usage_info: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        try:
            async for line in response.aiter_lines():
                if not line:
                    continue

                line = line.strip()

                # Hanya memproses baris SSE yang dimulai dengan data:, baris lainnya coba diabaikan sebagai error/JSON
                if not line.startswith("data:"):
                    # Mencoba mengurai sebagai error JSON
                    try:
                        maybe_err = json.loads(line)
                        if isinstance(maybe_err, dict) and (
                            "error" in maybe_err or "code" in maybe_err or "message" in maybe_err
                        ):
                            # Penanganan error terpadu
                            msg = (
                                (maybe_err.get("error") or {}).get("message")
                                if isinstance(maybe_err.get("error"), dict)
                                else maybe_err.get("message")
                            ) or "Error dari upstream"
                            return self.handle_error(Exception(msg), "Respons API")
                    except Exception:
                        pass
                    continue

                data_str = line[5:].strip()
                if not data_str or data_str in ("[DONE]", "DONE", "done"):
                    continue

                # Mengurai chunk data SSE
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if chunk.get("type") != "chat:completion":
                    continue

                data = chunk.get("data", {})
                phase = data.get("phase")
                delta_content = data.get("delta_content", "")
                edit_content = data.get("edit_content", "")

                # Mencatat penggunaan (biasanya muncul di chunk terakhir, tapi di sini ditimpa setiap kali untuk menjaga yang terbaru)
                if data.get("usage"):
                    try:
                        usage_info = data["usage"]
                    except Exception:
                        pass

                # Agregasi fase berpikir (menghapus pembungkus <details><summary>...)
                if phase == "thinking":
                    if delta_content:
                        if delta_content.startswith("<details"):
                            cleaned = (
                                delta_content.split("</summary>\n>")[-1].strip()
                                if "</summary>\n>" in delta_content
                                else delta_content
                            )
                        else:
                            cleaned = delta_content
                        reasoning_content += cleaned
                        all_content_buffer += cleaned  # Tambahkan ke buffer untuk ekstraksi tool_call

                # Agregasi fase jawaban
                elif phase == "answer":
                    # Saat edit_content mengandung marker akhir berpikir dan jawaban bersamaan, ekstrak bagian jawaban
                    if edit_content and "</details>\n" in edit_content:
                        content_after = edit_content.split("</details>\n")[-1]
                        if content_after:
                            final_content += content_after
                            all_content_buffer += content_after  # Tambahkan ke buffer untuk ekstraksi tool_call
                    elif delta_content:
                        final_content += delta_content
                        all_content_buffer += delta_content  # Tambahkan ke buffer untuk ekstraksi tool_call

        except Exception as e:
            self.logger.error(f"❌ Error memproses respons non-streaming: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            # Mengembalikan respons error terpadu
            return self.handle_error(e, "Agregasi non-streaming")

        # Mengekstrak tool_calls dari buffer konten
        tool_calls = None

        if all_content_buffer.strip():
            tool_calls, cleaned_content = parse_and_extract_tool_calls(all_content_buffer)

            # Jika tool_calls ditemukan, gunakan konten yang telah dibersihkan
            if tool_calls:
                self.logger.info(f"🔧 Extracted {len(tool_calls)} tool calls from non-streaming response")
                # Gunakan konten yang telah dibersihkan dari tool JSON
                final_content = cleaned_content

        # Membersihkan dan mengembalikan
        final_content = (final_content or "").strip()
        reasoning_content = (reasoning_content or "").strip()

        # Jika tidak ada jawaban yang teragregasi, tapi ada konten berpikir, maka kembalikan konten berpikir sebagai fallback
        if not final_content and reasoning_content:
            final_content = reasoning_content

        # Mengembalikan respons standar yang mengandung konten penalaran dan/atau tool_calls (jika tidak ada penalaran maka tidak akan dibawa)
        if tool_calls:
            # Kembalikan dengan tool_calls
            message = {
                "role": "assistant",
                "tool_calls": tool_calls
            }

            # Tambahkan content jika ada
            if final_content:
                message["content"] = final_content

            # Tambahkan reasoning_content jika ada
            if reasoning_content and reasoning_content.strip():
                message["reasoning_content"] = reasoning_content

            return {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls",
                    "logprobs": None,
                }],
                "usage": usage_info,
                "system_fingerprint": f"fp_{self.name}_001",
            }
        else:
            # Kembalikan dengan hanya konten dan reasoning
            return self.create_openai_response_with_reasoning(
                chat_id,
                model,
                final_content,
                reasoning_content,
                usage_info,
            )
