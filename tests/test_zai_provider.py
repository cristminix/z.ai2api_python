#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Tests for ZAI Provider
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import json
from app.providers.zai_provider import ZAIProvider, get_zai_dynamic_headers, _extract_user_id_from_token
from app.models.schemas import OpenAIRequest, Message
from app.core.config import settings
from app.providers.base import ProviderConfig


class TestZAIProvider:
    """Test cases for ZAIProvider class"""

    def setup_method(self):
        """Setup method to initialize provider instance for each test"""
        config = ProviderConfig(
            name="zai",
            api_endpoint="https://chat.z.ai/api/v1/chat/completions",
            timeout=30,
            headers={}
        )
        self.provider = ZAIProvider()

    def test_provider_initialization(self):
        """Test ZAIProvider initialization"""
        assert self.provider.name == "zai"
        assert self.provider.base_url == "https://chat.z.ai"
        assert self.provider.auth_url == "https://chat.z.ai/api/v1/auths/"
        assert hasattr(self.provider, 'model_mapping')
        assert len(self.provider.model_mapping) > 0

    def test_get_supported_models(self):
        """Test get_supported_models method"""
        models = self.provider.get_supported_models()
        assert isinstance(models, list)
        assert len(models) > 0
        # Check that some expected models are in the list
        expected_models = [
            settings.GLM45_MODEL,
            settings.GLM45_THINKING_MODEL,
            settings.GLM45_SEARCH_MODEL,
            settings.GLM46_MODEL,
        ]
        for model in expected_models:
            if model:  # Only check if the setting is not empty
                assert model in models

    @pytest.mark.asyncio
    async def test_get_token_anonymous_mode(self):
        """Test get_token method in anonymous mode"""
        # Mock settings to enable anonymous mode
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.ANONYMOUS_MODE = True
            mock_settings.HTTP_PROXY = None
            mock_settings.HTTPS_PROXY = None
            mock_settings.SOCKS5_PROXY = None

            # Mock httpx.AsyncClient
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.get.return_value = AsyncMock()
                mock_client.get.return_value.status_code = 200
                mock_client.get.return_value.json.return_value = {
                    "token": "mocked_guest_token",
                    "email": "guest-user@guest.com"
                }
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None

                token = await self.provider.get_token()
                assert token == "mocked_guest_token"

    @pytest.mark.asyncio
    async def test_get_token_non_anonymous_mode_with_token_pool(self):
        """Test get_token method in non-anonymous mode with token pool"""
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.ANONYMOUS_MODE = False
            mock_settings.AUTH_TOKEN = "test-auth-token"
            mock_settings.HTTP_PROXY = None
            mock_settings.HTTPS_PROXY = None
            mock_settings.SOCKS5_PROXY = None

            # Mock token pool
            with patch('app.providers.zai_provider.get_token_pool') as mock_token_pool:
                mock_pool_instance = MagicMock()
                mock_pool_instance.get_next_token.return_value = "pooled-token"
                mock_token_pool.return_value = mock_pool_instance

                token = await self.provider.get_token()
                assert token == "pooled-token"

    @pytest.mark.asyncio
    async def test_get_token_non_anonymous_mode_with_config_token(self):
        """Test get_token method in non-anonymous mode with config token"""
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.ANONYMOUS_MODE = False
            mock_settings.AUTH_TOKEN = "configured-auth-token"
            mock_settings.HTTP_PROXY = None
            mock_settings.HTTPS_PROXY = None
            mock_settings.SOCKS5_PROXY = None

            # Mock token pool to return empty
            with patch('app.providers.zai_provider.get_token_pool') as mock_token_pool:
                mock_pool_instance = MagicMock()
                mock_pool_instance.get_next_token.return_value = None
                mock_token_pool.return_value = mock_pool_instance

                token = await self.provider.get_token()
                assert token == "configured-auth-token"

    @pytest.mark.asyncio
    async def test_transform_request_basic(self):
        """Test basic request transformation"""
        # Create a basic OpenAI request
        request = OpenAIRequest(
            model=settings.GLM45_MODEL,
            messages=[
                Message(role="user", content="Hello, world!")
            ],
            stream=False
        )

        # Mock token retrieval
        with patch.object(self.provider, 'get_token') as mock_get_token:
            mock_get_token.return_value = "test-token"

            # Mock the get_latest_fe_version function
            with patch('app.providers.zai_provider.get_latest_fe_version') as mock_fe_version:
                mock_fe_version.return_value = "1.0.0"

                # Mock the generate_signature function
                with patch('app.providers.zai_provider.generate_signature') as mock_signature:
                    mock_signature.return_value = {"signature": "test-signature"}

                    transformed = await self.provider.transform_request(request)

                    # Check the structure of the transformed request
                    assert 'url' in transformed
                    assert 'headers' in transformed
                    assert 'body' in transformed
                    assert 'token' in transformed
                    assert 'chat_id' in transformed
                    assert 'model' in transformed

                    # Check that the body has expected structure
                    body = transformed['body']
                    assert body['stream'] is True  # Always true for ZAI
                    assert body['model'] in self.provider.model_mapping.values()
                    assert len(body['messages']) == 1
                    assert body['messages'][0]['role'] == 'user'
                    assert body['messages'][0]['content'] == 'Hello, world!'

    @pytest.mark.asyncio
    async def test_transform_request_with_tools(self):
        """Test request transformation with tools"""
        # Create a request with tools
        request = OpenAIRequest(
            model=settings.GLM45_MODEL,
            messages=[
                Message(role="user", content="What's the weather?")
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get weather information",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string"}
                            },
                            "required": ["location"]
                        }
                    }
                }
            ],
            stream=False
        )

        # Mock token retrieval
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.TOOL_SUPPORT = True
            mock_settings.GLM45_THINKING_MODEL = "glm-4.5-thinking"

            with patch.object(self.provider, 'get_token') as mock_get_token:
                mock_get_token.return_value = "test-token"

                with patch('app.providers.zai_provider.get_latest_fe_version') as mock_fe_version:
                    mock_fe_version.return_value = "1.0.0"

                    with patch('app.providers.zai_provider.generate_signature') as mock_signature:
                        mock_signature.return_value = {"signature": "test-signature"}

                        # Mock process_messages_with_tools
                        with patch('app.providers.zai_provider.process_messages_with_tools') as mock_process:
                            mock_process.return_value = [
                                {
                                    "role": "user",
                                    "content": "What's the weather? [TOOL_CALL: get_weather(location='Beijing')]"
                                }
                            ]

                            transformed = await self.provider.transform_request(request)

                            # Verify tools were processed
                            assert 'tools' in transformed['body']
                            assert transformed['body']['tools'] is None  # Tools should be set to None after processing
                            mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_transform_request_multimodal_content(self):
        """Test request transformation with multimodal content"""
        # Create a request with multimodal content (text + image)
        image_data_url = "data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="

        request = OpenAIRequest(
            model=settings.GLM45V_MODEL,
            messages=[
                Message(
                    role="user",
                    content=[
                        {"type": "text", "text": "Describe this image"},
                        {"type": "image_url", "image_url": {"url": image_data_url}}
                    ]
                )
            ],
            stream=False
        )

        # Mock token retrieval
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.ANONYMOUS_MODE = False
            mock_settings.HTTP_PROXY = None
            mock_settings.HTTPS_PROXY = None
            mock_settings.SOCKS5_PROXY = None

            with patch.object(self.provider, 'get_token') as mock_get_token:
                mock_get_token.return_value = "test-token"

                with patch('app.providers.zai_provider.get_latest_fe_version') as mock_fe_version:
                    mock_fe_version.return_value = "1.0.0"

                    with patch('app.providers.zai_provider.generate_signature') as mock_signature:
                        mock_signature.return_value = {"signature": "test-signature"}

                        # Mock the upload_image method
                        with patch.object(self.provider, 'upload_image') as mock_upload:
                            mock_upload.return_value = {
                                "id": "mock-file-id",
                                "name": "mock-image.jpg",
                                "url": "/api/v1/files/mock-file-id/content"
                            }

                            transformed = await self.provider.transform_request(request)

                            # Verify that files were processed
                            assert 'files' in transformed['body']
                            assert len(transformed['body']['files']) > 0

    @pytest.mark.asyncio
    async def test_upload_image_anonymous_mode(self):
        """Test image upload in anonymous mode"""
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.ANONYMOUS_MODE = True

            # Should return None in anonymous mode
            result = await self.provider.upload_image(
                "data:image/jpeg;base64,testdata",
                "chat123",
                "token123",
                "user123"
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_upload_image_success(self):
        """Test successful image upload"""
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.ANONYMOUS_MODE = False
            mock_settings.HTTP_PROXY = None
            mock_settings.HTTPS_PROXY = None
            mock_settings.SOCKS5_PROXY = None

            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.post.return_value = AsyncMock()
                mock_client.post.return_value.status_code = 200
                mock_client.post.return_value.json.return_value = {
                    "id": "file123",
                    "filename": "test.jpg",
                    "size": 12345
                }
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None

                result = await self.provider.upload_image(
                    "data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
                    "chat123",
                    "token123",
                    "user123"
                )

                assert result is not None
                assert result["id"] == "file123"
                assert result["name"] == "test.jpg"

    @pytest.mark.asyncio
    async def test_upload_image_failure(self):
        """Test image upload failure"""
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.ANONYMOUS_MODE = False
            mock_settings.HTTP_PROXY = None
            mock_settings.HTTPS_PROXY = None
            mock_settings.SOCKS5_PROXY = None

            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.post.return_value = AsyncMock()
                mock_client.post.return_value.status_code = 500
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None

                result = await self.provider.upload_image(
                    "data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
                    "chat123",
                    "token123",
                    "user123"
                )

                assert result is None

    @pytest.mark.asyncio
    async def test_chat_completion_streaming(self):
        """Test streaming chat completion"""
        request = OpenAIRequest(
            model=settings.GLM45_MODEL,
            messages=[
                Message(role="user", content="Hello")
            ],
            stream=True
        )

        # Mock the transform_request method to return a mock transformed request
        with patch.object(self.provider, 'transform_request') as mock_transform:
            mock_transform.return_value = {
                "url": "https://test.url",
                "headers": {"Authorization": "Bearer test-token"},
                "body": {"model": "test-model"},
                "token": "test-token",
                "chat_id": "test-chat-id",
                "model": settings.GLM45_MODEL
            }

            # Mock the _create_stream_response method
            with patch.object(self.provider, '_create_stream_response') as mock_stream_response:
                mock_stream_response.return_value = AsyncMock()
                mock_stream_response.return_value.__aiter__ = lambda self: self
                mock_stream_response.return_value.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

                result = await self.provider.chat_completion(request)

                # Should return a generator for streaming
                assert hasattr(result, '__aiter__')

    @pytest.mark.asyncio
    async def test_chat_completion_non_streaming_success(self):
        """Test non-streaming chat completion with success"""
        request = OpenAIRequest(
            model=settings.GLM45_MODEL,
            messages=[
                Message(role="user", content="Hello")
            ],
            stream=False
        )

        # Mock the transform_request method
        with patch.object(self.provider, 'transform_request') as mock_transform:
            mock_transform.return_value = {
                "url": "https://test.url",
                "headers": {"Authorization": "Bearer test-token"},
                "body": {"model": "test-model"},
                "token": "test-token",
                "chat_id": "test-chat-id",
                "model": settings.GLM45_MODEL
            }

            # Mock httpx client
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                response_mock = AsyncMock()
                response_mock.is_success = True
                response_mock.json = AsyncMock(return_value={"choices": [{"message": {"content": "Hi there"}}]})
                mock_client.post.return_value = response_mock
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None

                with patch.object(self.provider, 'transform_response') as mock_transform_resp:
                    mock_transform_resp.return_value = {"choices": [{"message": {"content": "Hi there"}}]}

                    result = await self.provider.chat_completion(request)

                    assert "choices" in result
                    assert result["choices"][0]["message"]["content"] == "Hi there"

    @pytest.mark.asyncio
    async def test_chat_completion_non_streaming_error(self):
        """Test non-streaming chat completion with error"""
        request = OpenAIRequest(
            model=settings.GLM45_MODEL,
            messages=[
                Message(role="user", content="Hello")
            ],
            stream=False
        )

        # Mock the transform_request method
        with patch.object(self.provider, 'transform_request') as mock_transform:
            mock_transform.return_value = {
                "url": "https://test.url",
                "headers": {"Authorization": "Bearer test-token"},
                "body": {"model": "test-model"},
                "token": "test-token",
                "chat_id": "test-chat-id",
                "model": settings.GLM45_MODEL
            }

            # Mock httpx client to return error
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = AsyncMock()
                response_mock = AsyncMock()
                response_mock.is_success = False
                response_mock.status_code = 400
                response_mock.aread = AsyncMock(return_value=b'Bad Request')
                mock_client.post.return_value = response_mock
                mock_client_class.return_value.__aenter__.return_value = mock_client
                mock_client_class.return_value.__aexit__.return_value = None

                result = await self.provider.chat_completion(request)

                # Should return error response
                assert "error" in result
                assert result["error"]["type"] == "provider_error"

    def test_get_zai_dynamic_headers(self):
        """Test the get_zai_dynamic_headers function"""
        headers = get_zai_dynamic_headers()
        assert "Content-Type" in headers
        assert "Accept" in headers
        assert "User-Agent" in headers
        assert headers["Content-Type"] == "application/json"
        assert "application/json" in headers["Accept"]

        # Test with chat_id
        headers_with_id = get_zai_dynamic_headers(chat_id="test-chat-id")
        assert "Referer" in headers_with_id
        assert "test-chat-id" in headers_with_id["Referer"]

    def test_extract_user_id_from_token(self):
        """Test the _extract_user_id_from_token function"""
        # Test with a mock JWT-like token
        # This is a simple test - in real JWT, the payload would be properly encoded
        mock_token = "header.payload.signature"
        result = _extract_user_id_from_token(mock_token)
        assert result == "guest"  # Should fallback to guest for invalid JWT

    def test_mark_token_failure(self):
        """Test mark_token_failure method"""
        with patch('app.providers.zai_provider.get_token_pool') as mock_token_pool:
            mock_pool_instance = MagicMock()
            mock_token_pool.return_value = mock_pool_instance

            self.provider.mark_token_failure("test-token", Exception("test error"))

            mock_pool_instance.mark_token_failure.assert_called_once_with("test-token", Exception("test error"))


class TestZAIProviderStreaming:
    """Test cases for ZAIProvider streaming functionality"""

    def setup_method(self):
        """Setup method to initialize provider instance for each test"""
        self.provider = ZAIProvider()

    @pytest.mark.asyncio
    async def test_handle_stream_response_basic(self):
        """Test basic stream response handling"""
        request = OpenAIRequest(
            model=settings.GLM45_MODEL,
            messages=[
                Message(role="user", content="Hello")
            ],
            stream=True
        )

        # Mock response object
        mock_response = AsyncMock()
        mock_lines = [
            'data: {"type": "chat:completion", "data": {"phase": "answer", "delta_content": "Hello", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}}',
            'data: [DONE]'
        ]

        # Create an async iterator for the mock response
        async def async_iter_lines():
            for line in mock_lines:
                yield line

        mock_response.aiter_lines = async_iter_lines

        transformed = {
            "chat_id": "test-chat-id",
            "model": settings.GLM45_MODEL
        }

        chunks = []
        async for chunk in self.provider._handle_stream_response(
            mock_response,
            "test-chat-id",
            settings.GLM45_MODEL,
            request,
            transformed
        ):
            chunks.append(chunk)

        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_handle_stream_response_with_tools(self):
        """Test stream response handling with tool calls"""
        with patch('app.providers.zai_provider.settings') as mock_settings:
            mock_settings.TOOL_SUPPORT = True

            request = OpenAIRequest(
                model=settings.GLM45_MODEL,
                messages=[
                    Message(role="user", content="Use the weather tool")
                ],
                tools=[{
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get weather information"
                    }
                }],
                stream=True
            )

            # Mock response with tool call content
            mock_response = AsyncMock()
            mock_lines = [
                'data: {"type": "chat:completion", "data": {"phase": "answer", "delta_content": "{\\"name\\": \\"get_weather\\", \\"arguments\\": {\\"location\\": \\"Beijing\\"}}", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}}',
                'data: [DONE]'
            ]

            async def async_iter_lines():
                for line in mock_lines:
                    yield line

            mock_response.aiter_lines = async_iter_lines

            transformed = {
                "chat_id": "test-chat-id",
                "model": settings.GLM45_MODEL
            }

            chunks = []
            with patch('app.providers.zai_provider.parse_and_extract_tool_calls') as mock_parse:
                mock_parse.return_value = ([{
                    "id": "call_123",
                    "function": {"name": "get_weather", "arguments": '{"location": "Beijing"}'},
                    "type": "function"
                }], "")

                async for chunk in self.provider._handle_stream_response(
                    mock_response,
                    "test-chat-id",
                    settings.GLM45_MODEL,
                    request,
                    transformed
                ):
                    chunks.append(chunk)

            assert len(chunks) > 0


if __name__ == "__main__":
    pytest.main([__file__])