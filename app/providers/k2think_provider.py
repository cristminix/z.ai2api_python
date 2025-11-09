#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Konektor Penyedia K2Think
"""

import json
import re
import time
import uuid
import httpx
from typing import Dict, List, Any, Optional, AsyncGenerator, Union

from app.providers.base import BaseProvider, ProviderConfig
from app.models.schemas import OpenAIRequest, Message
from app.utils.logger import get_logger

logger = get_logger()


class K2ThinkProvider(BaseProvider):
    """Penyedia K2Think"""
    
    def __init__(self):
        config = ProviderConfig(
            name="k2think",
            api_endpoint="https://www.k2think.ai/api/guest/chat/completions",
            timeout=30,
            headers={
                'Accept': 'text/event-stream',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                'Content-Type': 'application/json',
                'Origin': 'https://www.k2think.ai',
                'Pragma': 'no-cache',
                'Referer': 'https://www.k2think.ai/guest',
                'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"macOS"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            }
        )
        super().__init__(config)

        # Konfigurasi spesifik K2Think
        self.handshake_url = "https://www.k2think.ai/guest"
        self.new_chat_url = "https://www.k2think.ai/api/v1/chats/guest/new"
        
        # Ekspresi reguler untuk parsing konten - menggunakan flag DOTALL agar . cocok dengan karakter newline
        self.reasoning_pattern = re.compile(r'<details type="reasoning"[^>]*>.*?<summary>.*?</summary>(.*?)</details>', re.DOTALL)
        self.answer_pattern = re.compile(r'<answer>(.*?)</answer>', re.DOTALL)
    
    def get_supported_models(self) -> List[str]:
        """Mendapatkan daftar model yang didukung"""
        return ["MBZUAI-IFM/K2-Think"]
    
    def parse_cookies(self, headers) -> str:
        """Parsing Cookie"""
        cookies = []
        for key, value in headers.items():
            if key.lower() == 'set-cookie':
                cookies.append(value.split(';')[0])
        return '; '.join(cookies)
    
    def extract_reasoning_and_answer(self, content: str) -> tuple[str, str]:
        """Mengekstrak konten penalaran dan jawaban"""
        if not content:
            return "", ""
        
        try:
            reasoning_match = self.reasoning_pattern.search(content)
            reasoning = reasoning_match.group(1).strip() if reasoning_match else ""
            
            answer_match = self.answer_pattern.search(content)
            answer = answer_match.group(1).strip() if answer_match else ""
            
            return reasoning, answer
        except Exception as e:
            self.logger.error(f"Kesalahan ekstraksi konten K2: {e}")
            return "", ""
    
    def calculate_delta(self, previous: str, current: str) -> str:
        """Menghitung peningkatan konten"""
        if not previous:
            return current
        if not current or len(current) < len(previous):
            return ""
        return current[len(previous):]
    
    def parse_api_response(self, obj: Any) -> tuple[str, bool]:
        """Parsing respons API"""
        if not obj or not isinstance(obj, dict):
            return "", False
        
        if obj.get("done") is True:
            return "", True
        
        choices = obj.get("choices", [])
        if choices and len(choices) > 0:
            delta = choices[0].get("delta", {})
            return delta.get("content", ""), False
        
        content = obj.get("content")
        if isinstance(content, str):
            return content, False
        
        return "", False
    
    async def get_k2_auth_data(self, request: OpenAIRequest) -> Dict[str, Any]:
        """Mendapatkan data otentikasi K2Think"""
        # 1. Permintaan jabat tangan - menggunakan Accept-Encoding yang lebih sederhana untuk menghindari masalah Brotli
        headers_for_handshake = {**self.config.headers}
        headers_for_handshake['Accept-Encoding'] = 'gzip, deflate'  # menghapus br dan zstd

        async with httpx.AsyncClient() as client:
            handshake_response = await client.get(
                self.handshake_url,
                headers=headers_for_handshake,
                follow_redirects=True
            )
            if not handshake_response.is_success:
                try:
                    # Menggunakan properti text httpx, yang akan otomatis menangani dekompresi dan encoding
                    error_text = handshake_response.text
                    raise Exception(f"Gagal handshake K2: {handshake_response.status_code} {error_text[:200]}")
                except Exception as e:
                    raise Exception(f"Gagal handshake K2: {handshake_response.status_code}")
            
            initial_cookies = self.parse_cookies(handshake_response.headers)
        
        # 2. Menyiapkan pesan
        prepared_messages = self.prepare_k2_messages(request.messages)
        first_user_message = next((m for m in prepared_messages if m["role"] == "user"), None)
        if not first_user_message:
            raise Exception("Tidak menemukan pesan pengguna untuk menginisialisasi percakapan")
        
        # 3. Membuat percakapan baru
        message_id = str(uuid.uuid4())
        now = int(time.time() * 1000)
        model_id = request.model or "MBZUAI-IFM/K2-Think"
        
        new_chat_payload = {
            "chat": {
                "id": "",
                "title": "Guest Chat",
                "models": [model_id],
                "params": {},
                "history": {
                    "messages": {
                        message_id: {
                            "id": message_id,
                            "parentId": None,
                            "childrenIds": [],
                            "role": "user",
                            "content": first_user_message["content"],
                            "timestamp": now // 1000,
                            "models": [model_id]
                        }
                    },
                    "currentId": message_id
                },
                "messages": [{
                    "id": message_id,
                    "parentId": None,
                    "childrenIds": [],
                    "role": "user",
                    "content": first_user_message["content"],
                    "timestamp": now // 1000,
                    "models": [model_id]
                }],
                "tags": [],
                "timestamp": now
            }
        }
        
        headers_with_cookies = {**self.config.headers, 'Cookie': initial_cookies}
        headers_with_cookies['Accept-Encoding'] = 'gzip, deflate'  # menghapus br dan zstd

        async with httpx.AsyncClient() as client:
            new_chat_response = await client.post(
                self.new_chat_url,
                headers=headers_with_cookies,
                json=new_chat_payload,
                follow_redirects=True
            )
            if not new_chat_response.is_success:
                try:
                    # Menggunakan properti text httpx, yang akan otomatis menangani dekompresi dan encoding
                    error_text = new_chat_response.text
                except Exception:
                    error_text = f"Status: {new_chat_response.status_code}"
                raise Exception(f"Gagal membuat percakapan baru K2: {new_chat_response.status_code} {error_text[:200]}")

            try:
                new_chat_data = new_chat_response.json()
            except Exception as e:
                # Jika parsing JSON gagal, coba ambil konten asli
                try:
                    # Menggunakan properti text httpx, yang akan otomatis menangani dekompresi dan encoding
                    content_str = new_chat_response.text
                    self.logger.debug(f"Konten respons K2 asli: {content_str[:500]}")
                    raise Exception(f"Gagal parsing JSON respons K2: {e}, konten asli: {content_str[:200]}")
                except Exception as decode_error:
                    # Jika text juga gagal, coba manual handling
                    try:
                        raw_bytes = new_chat_response.content
                        content_str = raw_bytes.decode('utf-8', errors='replace')
                        raise Exception(f"Gagal parsing respons K2: {e}, konten decoding manual: {content_str[:200]}")
                    except Exception:
                        raise Exception(f"Gagal parsing respons K2 sepenuhnya: {e}, kesalahan decoding: {decode_error}")
            conversation_id = new_chat_data.get("id")
            if not conversation_id:
                raise Exception("Tidak bisa mendapatkan conversation_id dari endpoint K2 /new")
            
            chat_specific_cookies = self.parse_cookies(new_chat_response.headers)
        
        # 4. Menggabungkan Cookie akhir
        base_cookies = [initial_cookies, chat_specific_cookies]
        base_cookies = [c for c in base_cookies if c]
        final_cookie = '; '.join(base_cookies) + '; guest_conversation_count=1'
        
        # 5. Membangun payload permintaan akhir
        final_payload = {
            "stream": True,
            "model": model_id,
            "messages": prepared_messages,
            "conversation_id": conversation_id,
            "params": {}
        }
        
        # Menambahkan parameter opsional
        if request.temperature is not None:
            final_payload["params"]["temperature"] = request.temperature
        if request.max_tokens is not None:
            final_payload["params"]["max_tokens"] = request.max_tokens
        
        final_headers = {**self.config.headers, 'Cookie': final_cookie}
        
        return {
            "payload": final_payload,
            "headers": final_headers
        }
    
    def prepare_k2_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Menyiapkan format pesan K2Think"""
        result = []
        system_content = ""
        
        for msg in messages:
            if msg.role == "system":
                system_content = system_content + "\n\n" + msg.content if system_content else msg.content
            else:
                content = msg.content
                if isinstance(content, list):
                    # Menangani konten multimodal, mengekstrak teks
                    text_parts = [part.text for part in content if hasattr(part, 'text') and part.text]
                    content = "\n".join(text_parts)
                
                result.append({
                    "role": msg.role,
                    "content": content
                })
        
        # Menggabungkan pesan sistem ke pesan pengguna pertama
        if system_content:
            first_user_idx = next((i for i, m in enumerate(result) if m["role"] == "user"), -1)
            if first_user_idx >= 0:
                result[first_user_idx]["content"] = f"{system_content}\n\n{result[first_user_idx]['content']}"
            else:
                result.insert(0, {"role": "user", "content": system_content})
        
        return result

    async def _handle_stream_request(
        self,
        transformed: Dict[str, Any],
        request: OpenAIRequest
    ) -> AsyncGenerator[str, None]:
        """Menangani permintaan stream - langsung di dalam konteks client.stream"""
        chat_id = self.create_chat_id()
        model = transformed["model"]

        # Menyiapkan header permintaan
        headers_for_request = {**transformed["headers"]}
        headers_for_request['Accept-Encoding'] = 'gzip, deflate'

        self.logger.info(f"🌊 Memulai permintaan stream K2Think")

        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                transformed["url"],
                headers=headers_for_request,
                json=transformed["payload"]
            ) as response:
                if not response.is_success:
                    error_msg = f"Kesalahan API K2Think: {response.status_code}"
                    self.log_response(False, error_msg)
                    # Untuk respons stream, kita perlu menghasilkan informasi error
                    yield await self.format_sse_chunk({
                        "error": {
                            "message": error_msg,
                            "type": "provider_error",
                            "code": "api_error"
                        }
                    })
                    return

                # Mengirim blok peran awal
                yield await self.format_sse_chunk(
                    self.create_openai_chunk(chat_id, model, {"role": "assistant"})
                )

                # Menangani data stream
                accumulated_content = ""
                previous_reasoning = ""
                previous_answer = ""
                reasoning_phase = True
                chunk_count = 0

                try:
                    async for line in response.aiter_lines():
                        chunk_count += 1
                        self.logger.debug(f"📦 Menerima blok data #{chunk_count}: {line[:100]}...")

                        if not line.startswith("data:"):
                            continue

                        data_str = line[5:].strip()
                        if self._is_end_marker(data_str):
                            self.logger.debug(f"🏁 Mendeteksi penanda akhir: {data_str}")
                            continue

                        content = self._parse_data_string(data_str)
                        if not content:
                            continue

                        accumulated_content = content
                        current_reasoning, current_answer = self.extract_reasoning_and_answer(accumulated_content)

                        # Menangani fase penalaran
                        if reasoning_phase and current_reasoning:
                            delta = self.calculate_delta(previous_reasoning, current_reasoning)
                            if delta.strip():
                                self.logger.debug(f"🧠 Peningkatan penalaran: {delta[:50]}...")
                                yield await self.format_sse_chunk(
                                    self.create_openai_chunk(chat_id, model, {"reasoning_content": delta})
                                )
                                previous_reasoning = current_reasoning

                        # Beralih ke fase jawaban
                        if current_answer and reasoning_phase:
                            reasoning_phase = False
                            self.logger.debug("🔄 Beralih ke fase jawaban")
                            # Mengirim konten penalaran yang tersisa
                            final_reasoning_delta = self.calculate_delta(previous_reasoning, current_reasoning)
                            if final_reasoning_delta.strip():
                                yield await self.format_sse_chunk(
                                    self.create_openai_chunk(chat_id, model, {"reasoning_content": final_reasoning_delta})
                                )

                        # Menangani fase jawaban
                        if not reasoning_phase and current_answer:
                            delta = self.calculate_delta(previous_answer, current_answer)
                            if delta.strip():
                                self.logger.debug(f"💬 Peningkatan jawaban: {delta[:50]}...")
                                yield await self.format_sse_chunk(
                                    self.create_openai_chunk(chat_id, model, {"content": delta})
                                )
                                previous_answer = current_answer

                except Exception as e:
                    self.logger.error(f"Kesalahan penanganan respons stream: {e}")
                    yield await self.format_sse_chunk({
                        "error": {
                            "message": f"Kesalahan pemrosesan stream: {str(e)}",
                            "type": "stream_error",
                            "code": "processing_error"
                        }
                    })
                    return

                # Mengirim blok akhir
                self.logger.info(f"✅ Respons stream K2Think selesai, memproses total {chunk_count} blok data")
                yield await self.format_sse_chunk(
                    self.create_openai_chunk(chat_id, model, {}, "stop")
                )
                yield await self.format_sse_done()

    async def transform_request(self, request: OpenAIRequest) -> Dict[str, Any]:
        """Mengonversi permintaan OpenAI ke format K2Think"""
        self.logger.info(f"🔄 Mengonversi permintaan OpenAI ke format K2Think: {request.model}")
        
        auth_data = await self.get_k2_auth_data(request)
        
        return {
            "url": self.config.api_endpoint,
            "headers": auth_data["headers"],
            "payload": auth_data["payload"],
            "model": request.model
        }
    
    async def chat_completion(
        self,
        request: OpenAIRequest
    ) -> Union[Dict[str, Any], AsyncGenerator[str, None]]:
        """Antarmuka pelengkap obrolan"""
        self.log_request(request)

        try:
            # Mengonversi permintaan
            transformed = await self.transform_request(request)

            # Mengirim permintaan - menggunakan pengaturan kompresi yang lebih kompatibel
            headers_for_request = {**transformed["headers"]}
            headers_for_request['Accept-Encoding'] = 'gzip, deflate'  # menghapus br dan zstd

            if request.stream:
                # Permintaan stream - langsung menangani respons stream di sini
                return self._handle_stream_request(transformed, request)
            else:
                # Permintaan non-stream - menggunakan client.post() tradisional
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        transformed["url"],
                        headers=headers_for_request,
                        json=transformed["payload"]
                    )

                    if not response.is_success:
                        error_msg = f"Kesalahan API K2Think: {response.status_code}"
                        self.log_response(False, error_msg)
                        return self.handle_error(Exception(error_msg))

                    # Mengonversi respons non-stream
                    return await self.transform_response(response, request, transformed)

        except Exception as e:
            self.log_response(False, str(e))
            return self.handle_error(e, "pemrosesan permintaan")
    
    async def transform_response(
        self,
        response: httpx.Response,
        request: OpenAIRequest,
        transformed: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Mengonversi respons K2Think ke format OpenAI - hanya untuk permintaan non-stream"""
        chat_id = self.create_chat_id()
        model = transformed["model"]

        # Permintaan stream sekarang ditangani langsung oleh _handle_stream_request
        # Di sini hanya menangani permintaan non-stream
        return await self._handle_non_stream_response(response, chat_id, model)

    def _is_end_marker(self, data: str) -> bool:
        """Memeriksa apakah ini adalah penanda akhir"""
        return not data or data in ["-1", "[DONE]", "DONE", "done"]
    
    def _parse_data_string(self, data_str: str) -> str:
        """Parsing string data"""
        try:
            obj = json.loads(data_str)
            content, is_done = self.parse_api_response(obj)
            return "" if is_done else content
        except:
            return data_str
    
    async def _handle_non_stream_response(
        self,
        response: httpx.Response,
        chat_id: str,
        model: str
    ) -> Dict[str, Any]:
        """Menangani respons non-stream K2Think"""
        # Menggabungkan konten stream - menggunakan aiter_lines httpx, yang akan otomatis menangani dekompresi
        final_content = ""

        try:
            # Menggunakan aiter_lines(), httpx akan otomatis menangani kompresi dan encoding
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()
                if self._is_end_marker(data_str):
                    continue

                content = self._parse_data_string(data_str)
                if content:
                    final_content = content

        except Exception as e:
            self.logger.error(f"Kesalahan penanganan respons non-stream: {e}")
            raise

        # Mengekstrak konten penalaran dan jawaban
        reasoning, answer = self.extract_reasoning_and_answer(final_content)

        # Membersihkan format konten
        reasoning = reasoning.replace("\\n", "\n") if reasoning else ""
        answer = answer.replace("\\n", "\n") if answer else final_content

        # Membuat respons yang berisi konten penalaran
        return self.create_openai_response_with_reasoning(chat_id, model, answer, reasoning)
