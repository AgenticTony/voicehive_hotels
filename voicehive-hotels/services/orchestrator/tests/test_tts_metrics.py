"""
Tests for TTS latency metrics.
Verifies that Prometheus metrics are correctly recorded for TTS operations.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone
import httpx

import sys
from pathlib import Path
# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tts_client import (
    TTSClient, 
    tts_synthesis_duration_seconds,
    tts_synthesis_total,
    tts_synthesis_errors
)


@pytest.mark.asyncio
async def test_tts_synthesis_success_metrics():
    """Test that successful TTS synthesis records correct metrics"""
    # Reset metrics
    tts_synthesis_duration_seconds._metrics.clear()
    tts_synthesis_total._metrics.clear()
    
    # Mock response data
    mock_response_data = {
        "audio_data": "base64_encoded_audio",
        "duration_ms": 1500.0,
        "engine_used": "elevenlabs",
        "voice_used": "rachel",
        "cached": False
    }
    
    # Create mock response
    mock_response = Mock()
    mock_response.json.return_value = mock_response_data
    mock_response.raise_for_status.return_value = None
    
    # Create TTS client with mocked HTTP client
    client = TTSClient(tts_url="http://test-tts:9000")
    
    with patch.object(client.http_client, 'post', return_value=mock_response) as mock_post:
        # Make the request
        result = await client.synthesize(
            text="Hello world",
            language="en-US",
            voice_id="test_voice"
        )
        
        # Verify the response
        assert result.audio_data == "base64_encoded_audio"
        assert result.engine_used == "elevenlabs"
        assert result.cached is False
        
        # Check that metrics were recorded
        # Duration metric
        duration_labels = ('en-US', 'elevenlabs', 'False')
        assert duration_labels in tts_synthesis_duration_seconds._metrics
        # Access the metric value correctly
        metric = tts_synthesis_duration_seconds._metrics[duration_labels]
        assert metric._sum.get() > 0  # Use .get() to access MutexValue
        
        # Total counter
        total_labels = ('en-US', 'elevenlabs', 'success')
        assert total_labels in tts_synthesis_total._metrics
        # Access counter value correctly
        counter = tts_synthesis_total._metrics[total_labels]
        assert counter._value.get() == 1  # Use .get() to access MutexValue
    
    # Cleanup
    await client.close()


@pytest.mark.asyncio
async def test_tts_synthesis_cached_metrics():
    """Test that cached responses are tracked separately"""
    # Reset metrics
    tts_synthesis_duration_seconds._metrics.clear()
    tts_synthesis_total._metrics.clear()
    
    # Mock response data for cached response
    mock_response_data = {
        "audio_data": "cached_audio",
        "duration_ms": 500.0,
        "engine_used": "azure",
        "voice_used": "jenny",
        "cached": True
    }
    
    # Create mock response
    mock_response = Mock()
    mock_response.json.return_value = mock_response_data
    mock_response.raise_for_status.return_value = None
    
    # Create TTS client
    client = TTSClient()
    
    with patch.object(client.http_client, 'post', return_value=mock_response):
        # Make request
        result = await client.synthesize(
            text="Cached text",
            language="de-DE"
        )
        
        # Verify cached response
        assert result.cached is True
        
        # Check metrics for cached response
        duration_labels = ('de-DE', 'azure', 'True')
        assert duration_labels in tts_synthesis_duration_seconds._metrics
        
        total_labels = ('de-DE', 'azure', 'success')
        assert total_labels in tts_synthesis_total._metrics
    
    await client.close()


@pytest.mark.asyncio
async def test_tts_synthesis_http_error_metrics():
    """Test that HTTP errors are tracked in metrics"""
    # Reset metrics
    tts_synthesis_errors._metrics.clear()
    tts_synthesis_total._metrics.clear()
    
    # Create mock HTTP error response
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=Mock(),
        response=mock_response
    )
    
    # Create TTS client
    client = TTSClient()
    
    with patch.object(client.http_client, 'post', return_value=mock_response):
        # Make request that will fail
        with pytest.raises(httpx.HTTPStatusError):
            await client.synthesize(
                text="Error text",
                language="fr-FR"
            )
        
        # Check error metrics (retries will increment the counter)
        error_labels = ('fr-FR', 'http_error')
        assert error_labels in tts_synthesis_errors._metrics
        # Tenacity will retry 3 times, so we expect 3 errors
        assert tts_synthesis_errors._metrics[error_labels]._value.get() == 3
        
        # Check total counter shows error (3 attempts)
        total_labels = ('fr-FR', 'unknown', 'error')
        assert total_labels in tts_synthesis_total._metrics
        assert tts_synthesis_total._metrics[total_labels]._value.get() == 3
    
    await client.close()


@pytest.mark.asyncio
async def test_tts_synthesis_general_error_metrics():
    """Test that general exceptions are tracked with error type"""
    # Reset metrics
    tts_synthesis_errors._metrics.clear()
    tts_synthesis_total._metrics.clear()
    
    # Create TTS client
    client = TTSClient()
    
    # Mock a connection error
    with patch.object(client.http_client, 'post', side_effect=httpx.ConnectError("Connection failed")):
        # Make request that will fail
        with pytest.raises(httpx.ConnectError):
            await client.synthesize(
                text="Connection error text",
                language="es-ES"
            )
        
        # Check error metrics with specific error type (3 retry attempts)
        error_labels = ('es-ES', 'ConnectError')
        assert error_labels in tts_synthesis_errors._metrics
        assert tts_synthesis_errors._metrics[error_labels]._value.get() == 3
        
        # Check total counter
        total_labels = ('es-ES', 'unknown', 'error')
        assert total_labels in tts_synthesis_total._metrics
        assert tts_synthesis_total._metrics[total_labels]._value.get() == 3
    
    await client.close()


@pytest.mark.asyncio
async def test_tts_latency_histogram():
    """Test that TTS latency is recorded in Prometheus histogram"""
    # Reset metrics
    tts_synthesis_duration_seconds._metrics.clear()
    
    # Create a mock response  
    mock_response_data = {
        "audio_data": "test_audio",
        "duration_ms": 250.0,  # 250ms response
        "engine_used": "elevenlabs",
        "voice_used": "test_voice",
        "cached": False
    }
    
    mock_response = Mock()
    mock_response.json.return_value = mock_response_data
    mock_response.raise_for_status.return_value = None
    
    client = TTSClient()
    
    # Make multiple requests to test histogram
    with patch.object(client.http_client, 'post', return_value=mock_response):
        # Make 3 requests
        for i in range(3):
            result = await client.synthesize(
                text=f"Test {i}",
                language="en-US"
            )
            assert result.engine_used == "elevenlabs"
        
        # Verify metric was recorded
        labels = ('en-US', 'elevenlabs', 'False')
        assert labels in tts_synthesis_duration_seconds._metrics
        
        # Get the histogram
        histogram = tts_synthesis_duration_seconds._metrics[labels]
        
        # Verify we have 3 observations recorded
        # The sum should be positive (3 times some latency)
        assert histogram._sum.get() > 0
        
        # Also verify the counter metrics
        counter_labels = ('en-US', 'elevenlabs', 'success')
        assert counter_labels in tts_synthesis_total._metrics
        assert tts_synthesis_total._metrics[counter_labels]._value.get() == 3
    
    await client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
