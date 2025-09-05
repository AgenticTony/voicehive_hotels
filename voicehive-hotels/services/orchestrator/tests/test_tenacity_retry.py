"""
Test Tenacity retry strategies are correctly configured
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone
import time

from services.orchestrator.tts_client import TTSClient
from services.orchestrator.call_manager import CallManager


class TestRetryStrategies:
    """Test suite for verifying Tenacity retry configurations"""
    
    @pytest.mark.asyncio
    async def test_tts_client_retries_on_failure(self):
        """Test that TTS client retries with exponential backoff"""
        # Create TTS client
        tts_client = TTSClient(tts_url="http://test:9000")
        
        # Mock HTTP client to fail twice then succeed
        call_count = 0
        
        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            if call_count < 3:
                # Fail first two attempts
                response = Mock()
                response.status_code = 500
                response.raise_for_status = Mock(side_effect=Exception("Server error"))
                raise Exception("Server error")
            else:
                # Succeed on third attempt
                response = Mock()
                response.status_code = 200
                response.json = Mock(return_value={
                    "audio_data": "base64_audio_data",
                    "duration_ms": 1000,
                    "engine_used": "elevenlabs",
                    "voice_used": "test_voice",
                    "cached": False
                })
                response.raise_for_status = Mock()
                return response
        
        tts_client.http_client.post = mock_post
        
        # Call synthesize - should retry and eventually succeed
        start_time = time.time()
        result = await tts_client.synthesize("Hello world", "en-US")
        elapsed = time.time() - start_time
        
        # Verify retry happened (3 calls total)
        assert call_count == 3
        # Verify exponential backoff happened (should take at least 1 second due to retries)
        assert elapsed > 1.0
        # Verify result is correct
        assert result.audio_data == "base64_audio_data"
        
    @pytest.mark.asyncio
    async def test_tts_client_reraises_after_max_attempts(self):
        """Test that TTS client re-raises exception after max retry attempts"""
        # Create TTS client
        tts_client = TTSClient(tts_url="http://test:9000")
        
        # Mock HTTP client to always fail
        async def mock_post(*args, **kwargs):
            raise Exception("Persistent server error")
        
        tts_client.http_client.post = mock_post
        
        # Call synthesize - should fail after 3 attempts
        with pytest.raises(Exception) as exc_info:
            await tts_client.synthesize("Hello world", "en-US")
        
        assert "Persistent server error" in str(exc_info.value)
        
    @pytest.mark.asyncio
    async def test_call_manager_retry_on_llm_failure(self):
        """Test that call manager retries LLM calls with exponential backoff"""
        # Set up mocks
        redis_client = Mock()
        connector_factory = Mock()
        
        call_manager = CallManager(
            redis_client=redis_client,
            connector_factory=connector_factory
        )
        
        # Create a call context
        from services.orchestrator.call_manager import CallContext, CallState
        
        context = CallContext(
            room_name="test-room",
            hotel_id="test-hotel",
            state=CallState.ACTIVE,
            detected_language="en",
            pms_data={"hotel_name": "Test Hotel"}
        )
        
        # Track retry attempts
        attempt_count = 0
        attempt_times = []
        
        # Mock _call_openai_with_functions to fail twice then succeed
        async def mock_openai_call(messages, tools):
            nonlocal attempt_count
            attempt_count += 1
            attempt_times.append(time.time())
            
            if attempt_count < 3:
                raise Exception("OpenAI API error")
            else:
                return "Hello, how can I help you?"
        
        call_manager._call_openai_with_functions = mock_openai_call
        call_manager._detect_intent = Mock(return_value="greeting")
        
        # Call _process_user_input
        start_time = time.time()
        result = await call_manager._process_user_input(context, "Hello")
        elapsed = time.time() - start_time
        
        # Verify retries happened
        assert attempt_count == 3
        # Verify exponential backoff (should have delays between attempts)
        assert elapsed > 1.0
        # Verify backoff is exponential (second delay > first delay)
        if len(attempt_times) >= 3:
            first_delay = attempt_times[1] - attempt_times[0]
            second_delay = attempt_times[2] - attempt_times[1]
            # Allow some variance but second delay should generally be longer
            assert second_delay > first_delay * 0.8
        
        # Verify result
        assert result["text"] == "Hello, how can I help you?"
        assert result["language"] == "en"
        assert result["intent"] == "greeting"
        
    @pytest.mark.asyncio
    async def test_call_manager_reraises_after_max_attempts(self):
        """Test that call manager re-raises after max retry attempts"""
        # Set up mocks
        redis_client = Mock()
        connector_factory = Mock()
        
        call_manager = CallManager(
            redis_client=redis_client,
            connector_factory=connector_factory
        )
        
        # Create a call context
        from services.orchestrator.call_manager import CallContext, CallState
        
        context = CallContext(
            room_name="test-room",
            hotel_id="test-hotel",
            state=CallState.ACTIVE,
            detected_language="en",
            pms_data={"hotel_name": "Test Hotel"}
        )
        
        # Mock to always fail
        async def mock_openai_call(messages, tools):
            raise Exception("Persistent OpenAI error")
        
        call_manager._call_openai_with_functions = mock_openai_call
        call_manager._detect_intent = Mock(return_value="greeting")
        
        # Should raise after 3 attempts
        with pytest.raises(Exception) as exc_info:
            await call_manager._process_user_input(context, "Hello")
        
        assert "Persistent OpenAI error" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
