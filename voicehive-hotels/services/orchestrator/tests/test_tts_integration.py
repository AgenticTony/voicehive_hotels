"""
Test TTS integration in the orchestrator service.
Tests the CallManager's ability to synthesize responses.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

from services.orchestrator.call_manager import CallManager, CallEvent, CallContext, CallState
from services.orchestrator.tts_client import TTSSynthesisResponse


class TestTTSIntegration:
    """Test suite for TTS integration in orchestrator"""
    
    @pytest.fixture
    async def mock_redis(self):
        """Mock Redis client"""
        redis = AsyncMock()
        redis.setex = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        return redis
    
    @pytest.fixture
    def mock_connector_factory(self):
        """Mock connector factory"""
        factory = Mock()
        factory.get_connector = Mock()
        return factory
    
    @pytest.fixture
    async def call_manager(self, mock_redis, mock_connector_factory):
        """Create CallManager instance with mocks"""
        # Mock TTS client
        with patch('services.orchestrator.call_manager.TTSClient') as mock_tts_client:
            # Create mock TTS client instance
            tts_client_instance = Mock()
            mock_tts_client.return_value = tts_client_instance
            
            manager = CallManager(
                redis_client=mock_redis,
                connector_factory=mock_connector_factory
            )
            
            # Replace with async mock for synthesize method
            manager.tts_client.synthesize = AsyncMock()
            
            return manager
    
    @pytest.mark.asyncio
    async def test_synthesize_response(self, call_manager):
        """Test TTS synthesis for a response"""
        # Mock TTS response
        mock_tts_response = TTSSynthesisResponse(
            audio_data="base64_encoded_audio_data",
            duration_ms=1500.0,
            engine_used="elevenlabs",
            voice_used="Rachel",
            cached=False,
            processing_time_ms=150.0
        )
        
        call_manager.tts_client.synthesize.return_value = mock_tts_response
        
        # Test synthesis
        result = await call_manager._synthesize_response(
            text="Welcome to VoiceHive Hotel",
            language="en-US"
        )
        
        # Verify result
        assert result is not None
        assert result.audio_data == "base64_encoded_audio_data"
        assert result.engine_used == "elevenlabs"
        assert result.duration_ms == 1500.0
        
        # Verify TTS client was called correctly
        call_manager.tts_client.synthesize.assert_called_once_with(
            text="Welcome to VoiceHive Hotel",
            language="en-US",
            speed=1.0,
            format="mp3",
            sample_rate=24000
        )
    
    @pytest.mark.asyncio
    async def test_language_code_mapping(self, call_manager):
        """Test language code mapping for TTS"""
        # Test short codes
        assert call_manager._map_language_code("en") == "en-US"
        assert call_manager._map_language_code("de") == "de-DE"
        assert call_manager._map_language_code("es") == "es-ES"
        assert call_manager._map_language_code("fr") == "fr-FR"
        
        # Test full codes (should pass through)
        assert call_manager._map_language_code("en-GB") == "en-GB"
        assert call_manager._map_language_code("pt-BR") == "pt-BR"
        
        # Test unknown code (defaults to en-US)
        assert call_manager._map_language_code("xx") == "en-US"
    
    @pytest.mark.asyncio
    async def test_handle_transcription_with_tts(self, call_manager):
        """Test transcription handling includes TTS synthesis"""
        # Create test context
        context = CallContext(
            call_id="test-call-123",
            room_name="test-room",
            detected_language="en",
            pms_data={"hotel_name": "Test Hotel"}
        )
        
        # Add to active calls
        call_manager.active_calls[context.call_id] = context
        
        # Mock OpenAI response
        mock_openai_response = Mock()
        mock_openai_response.choices = [Mock()]
        mock_openai_response.choices[0].message.content = "I can help you with that reservation."
        mock_openai_response.choices[0].message.tool_calls = None
        
        with patch.object(call_manager, 'openai_client') as mock_openai:
            mock_openai.chat.completions.create.return_value = mock_openai_response
            
            # Mock TTS response
            mock_tts_response = TTSSynthesisResponse(
                audio_data="base64_audio_reservation",
                duration_ms=2000.0,
                engine_used="azure",
                voice_used="en-US-AriaNeural",
                cached=True,
                processing_time_ms=50.0
            )
            
            call_manager.tts_client.synthesize.return_value = mock_tts_response
            
            # Create transcription event
            event = CallEvent(
                event="transcription",
                room_name="test-room",
                timestamp=datetime.now(timezone.utc).timestamp(),
                data={
                    "transcription": {
                        "text": "I need to check my reservation",
                        "is_final": True,
                        "language": "en"
                    }
                }
            )
            
            # Handle event
            result = await call_manager.handle_event(event)
            
            # Verify response includes TTS data
            assert result["status"] == "response_ready"
            assert result["action"] == "speak"
            assert result["text"] == "I can help you with that reservation."
            assert result["audio_data"] == "base64_audio_reservation"
            assert result["audio_format"] == "mp3"
            assert result["metadata"]["tts_engine"] == "azure"
            assert result["metadata"]["tts_cached"] is True
            assert result["metadata"]["tts_duration_ms"] == 2000.0
    
    @pytest.mark.asyncio
    async def test_tts_synthesis_failure_handling(self, call_manager):
        """Test handling when TTS synthesis fails"""
        # Mock TTS client to raise exception
        call_manager.tts_client.synthesize.side_effect = Exception("TTS service unavailable")
        
        # Test synthesis
        result = await call_manager._synthesize_response(
            text="Test message",
            language="en-US"
        )
        
        # Should return None on failure
        assert result is None
    
    @pytest.mark.asyncio
    async def test_greeting_with_tts(self, call_manager):
        """Test that initial greeting includes TTS synthesis"""
        # Create test context
        context = CallContext(
            call_id="test-call-456",
            room_name="test-room",
            detected_language="de",
            state=CallState.CONNECTING
        )
        
        # Add to active calls
        call_manager.active_calls[context.call_id] = context
        
        # Mock TTS response
        mock_tts_response = TTSSynthesisResponse(
            audio_data="base64_german_greeting",
            duration_ms=3000.0,
            engine_used="azure",
            voice_used="de-DE-KatjaNeural",
            cached=False,
            processing_time_ms=200.0
        )
        
        call_manager.tts_client.synthesize.return_value = mock_tts_response
        
        # Create call started event
        event = CallEvent(
            event="call_started",
            room_name="test-room",
            timestamp=datetime.now(timezone.utc).timestamp(),
            participant_sid="PA123",
            participant_identity="caller"
        )
        
        # Handle event
        result = await call_manager.handle_event(event)
        
        # Verify response includes German greeting with TTS
        assert result["status"] == "started"
        assert result["action"] == "speak"
        assert "Willkommen" in result["text"]  # German greeting
        assert result["language"] == "de"
        assert result["audio_data"] == "base64_german_greeting"
        assert result["metadata"]["tts_engine"] == "azure"
        
        # Verify TTS was called with German
        call_manager.tts_client.synthesize.assert_called_with(
            text=result["text"],
            language="de-DE",  # Should be mapped to full code
            speed=1.0,
            format="mp3",
            sample_rate=24000
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
