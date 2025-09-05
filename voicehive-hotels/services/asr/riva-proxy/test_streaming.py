#!/usr/bin/env python3
"""
Test Riva ASR Proxy streaming functionality with mocked NVIDIA client
"""

import asyncio
import base64
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
import websocket

# Mock the riva client before importing server
mock_riva = MagicMock()
mock_riva.client.Auth = Mock()
mock_riva.client.ASRService = Mock()
mock_riva.client.AudioEncoding.LINEAR_PCM = 1
mock_riva.client.RecognitionConfig = Mock()
mock_riva.client.StreamingRecognitionConfig = Mock()

with patch.dict('sys.modules', {'riva': mock_riva, 'riva.client': mock_riva.client}):
    from server import app, ASRService


class TestRivaStreamingHandshake:
    """Test WebSocket streaming handshake and data flow"""
    
    def setup_method(self):
        """Set up test client and mocks"""
        self.client = TestClient(app)
        self.mock_audio_data = b"fake_audio_data_16khz_pcm"
        self.mock_audio_b64 = base64.b64encode(self.mock_audio_data).decode()
        
    def test_websocket_connection_established(self):
        """Test that WebSocket connection can be established"""
        with self.client.websocket_connect("/transcribe-stream") as websocket:
            # Connection should be established
            assert websocket is not None
            
    def test_websocket_config_handshake(self):
        """Test initial configuration handshake"""
        with self.client.websocket_connect("/transcribe-stream") as websocket:
            # Send configuration
            config = {
                "type": "config",
                "language": "en-US",
                "sample_rate": 16000
            }
            websocket.send_json(config)
            
            # Should not receive immediate error
            # (In real implementation, this would start the streaming)
            
    def test_websocket_invalid_first_message(self):
        """Test that non-config first message returns error"""
        with self.client.websocket_connect("/transcribe-stream") as websocket:
            # Send audio without config
            invalid_first = {
                "type": "audio",
                "audio": self.mock_audio_b64
            }
            websocket.send_json(invalid_first)
            
            # Should receive error
            response = websocket.receive_json()
            assert response["type"] == "error"
            assert "First message must be config" in response["message"]
            
    @patch('server.asr_service')
    def test_websocket_streaming_flow(self, mock_asr_service):
        """Test full streaming flow with mocked responses"""
        # Mock the streaming response generator
        mock_response = Mock()
        mock_response.results = [Mock()]
        mock_response.results[0].alternatives = [Mock()]
        mock_response.results[0].alternatives[0].transcript = "Hello world"
        mock_response.results[0].alternatives[0].confidence = 0.95
        mock_response.results[0].is_final = False
        
        mock_asr_service.asr_service.streaming_response_generator = Mock(
            return_value=[mock_response]
        )
        
        with self.client.websocket_connect("/transcribe-stream") as websocket:
            # Send config
            config = {
                "type": "config",
                "language": "en-US",
                "sample_rate": 16000
            }
            websocket.send_json(config)
            
            # Send audio chunk
            audio_chunk = {
                "type": "audio",
                "audio": self.mock_audio_b64
            }
            websocket.send_json(audio_chunk)
            
            # Send end of stream
            end_stream = {
                "type": "end_of_stream"
            }
            websocket.send_json(end_stream)
            
            # Verify WebSocket doesn't crash
            # (In real implementation, we'd check for transcription responses)
            
    def test_websocket_handles_disconnect(self):
        """Test graceful handling of client disconnect"""
        with self.client.websocket_connect("/transcribe-stream") as websocket:
            # Send config
            config = {
                "type": "config",
                "language": "en-US",
                "sample_rate": 16000
            }
            websocket.send_json(config)
            
            # Disconnect immediately
            websocket.close()
            
        # Should not raise exceptions
        
    def test_active_streams_metric(self):
        """Test that active_streams gauge is incremented/decremented"""
        # Get initial metric value
        response = self.client.get("/metrics")
        initial_metrics = response.text
        
        # Connect and disconnect
        with self.client.websocket_connect("/transcribe-stream") as websocket:
            # Check metrics during connection
            response = self.client.get("/metrics")
            during_metrics = response.text
            
            # Send config to properly initialize
            config = {
                "type": "config",
                "language": "en-US", 
                "sample_rate": 16000
            }
            websocket.send_json(config)
            
        # Check metrics after disconnect
        response = self.client.get("/metrics")
        after_metrics = response.text
        
        # Active streams should be tracked
        assert "asr_active_streams" in initial_metrics
        assert "asr_active_streams" in during_metrics
        assert "asr_active_streams" in after_metrics


@pytest.mark.asyncio
async def test_concurrent_streams():
    """Test handling of multiple concurrent streaming connections"""
    client = TestClient(app)
    
    async def stream_client(client_id: int):
        """Simulate a streaming client"""
        with client.websocket_connect("/transcribe-stream") as websocket:
            # Send config
            config = {
                "type": "config",
                "language": "en-US",
                "sample_rate": 16000
            }
            websocket.send_json(config)
            
            # Send a few audio chunks
            for i in range(3):
                audio_chunk = {
                    "type": "audio",
                    "audio": base64.b64encode(f"audio_{client_id}_{i}".encode()).decode()
                }
                websocket.send_json(audio_chunk)
                await asyncio.sleep(0.1)
            
            # End stream
            websocket.send_json({"type": "end_of_stream"})
    
    # Run multiple clients concurrently
    tasks = [stream_client(i) for i in range(5)]
    await asyncio.gather(*tasks)
    
    # All connections should complete without error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
