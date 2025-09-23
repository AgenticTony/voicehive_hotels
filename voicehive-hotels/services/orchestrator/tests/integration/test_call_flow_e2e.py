"""
End-to-End Call Flow Integration Tests

Tests the complete call flow from incoming webhook to TTS response,
including all middleware, authentication, and service integrations.
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
import httpx

from models import CallEvent, CallEventType


class TestCallFlowEndToEnd:
    """Test complete call flow scenarios"""
    
    async def test_complete_call_flow_authenticated(
        self, 
        authenticated_client, 
        integration_test_app,
        mock_pms_server,
        mock_tts_service,
        mock_livekit_service
    ):
        """Test complete authenticated call flow from start to finish"""
        
        # Step 1: Start a new call
        call_payload = {
            "event": "call.started",
            "call_id": "test-call-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "hotel-123",
                "reservation_id": "12345"
            }
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        assert response.status_code == 200
        
        # Verify call was processed
        call_data = response.json()
        assert call_data["status"] == "success"
        assert call_data["call_id"] == "test-call-001"
        
        # Step 2: Simulate guest interaction - room service request
        interaction_payload = {
            "event": "call.interaction",
            "call_id": "test-call-001",
            "interaction_type": "room_service_request",
            "guest_input": "I would like to order room service",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=interaction_payload
        )
        assert response.status_code == 200
        
        # Verify PMS was called to get reservation details
        assert mock_pms_server.call_count == 1
        
        # Step 3: Generate TTS response
        tts_payload = {
            "text": "I'll be happy to help you with room service. What would you like to order?",
            "voice": "female",
            "language": "en-US"
        }
        
        response = await authenticated_client.post(
            "/tts/synthesize",
            json=tts_payload
        )
        assert response.status_code == 200
        
        # Verify TTS service was called
        assert mock_tts_service.call_count == 1
        
        # Step 4: End the call
        end_payload = {
            "event": "call.ended",
            "call_id": "test-call-001",
            "duration": 120,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=end_payload
        )
        assert response.status_code == 200
        
        # Verify call metrics were recorded
        metrics_response = await authenticated_client.get("/metrics")
        assert metrics_response.status_code == 200
        metrics_text = metrics_response.text
        assert "call_duration_seconds" in metrics_text
        assert "call_total" in metrics_text
    
    async def test_call_flow_with_pms_integration(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server
    ):
        """Test call flow with PMS connector integration"""
        
        # Setup PMS server with reservation data
        mock_pms_server.reservations["67890"] = {
            "id": "67890",
            "guest_name": "Jane Smith",
            "room_number": "205",
            "check_in": "2024-01-15",
            "check_out": "2024-01-18",
            "status": "checked_in",
            "preferences": {
                "language": "en",
                "dietary_restrictions": ["vegetarian"]
            }
        }
        
        # Start call with reservation lookup
        call_payload = {
            "event": "call.started",
            "call_id": "test-call-002",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "hotel-456",
                "reservation_id": "67890",
                "room_number": "205"
            }
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        assert response.status_code == 200
        
        # Verify reservation was fetched
        assert mock_pms_server.call_count == 1
        
        # Test guest information request
        info_payload = {
            "event": "call.interaction",
            "call_id": "test-call-002",
            "interaction_type": "guest_info_request",
            "guest_input": "What are my reservation details?",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=info_payload
        )
        assert response.status_code == 200
        
        response_data = response.json()
        assert "Jane Smith" in str(response_data)
        assert "205" in str(response_data)
    
    async def test_call_flow_error_handling(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server,
        mock_tts_service
    ):
        """Test call flow error handling and recovery"""
        
        # Configure PMS to fail
        mock_pms_server.should_fail = True
        
        call_payload = {
            "event": "call.started",
            "call_id": "test-call-003",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "hotel-789",
                "reservation_id": "99999"  # Non-existent reservation
            }
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        
        # Should still succeed with graceful degradation
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["status"] == "success"
        
        # Verify error was logged but call continued
        assert "error" in response_data.get("warnings", [])
        
        # Reset PMS and test TTS failure
        mock_pms_server.should_fail = False
        mock_tts_service.should_fail = True
        
        tts_payload = {
            "text": "Test message",
            "voice": "female"
        }
        
        response = await authenticated_client.post(
            "/tts/synthesize",
            json=tts_payload
        )
        
        # Should return error but not crash
        assert response.status_code in [500, 503]  # Server error or service unavailable
        
    async def test_concurrent_call_flows(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server,
        mock_tts_service
    ):
        """Test handling multiple concurrent call flows"""
        
        async def simulate_call_flow(call_id: str):
            """Simulate a complete call flow"""
            # Start call
            call_payload = {
                "event": "call.started",
                "call_id": call_id,
                "from_number": f"+123456{call_id[-4:]}",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "hotel-concurrent",
                    "reservation_id": "12345"
                }
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            assert response.status_code == 200
            
            # Interaction
            interaction_payload = {
                "event": "call.interaction",
                "call_id": call_id,
                "interaction_type": "greeting",
                "guest_input": "Hello",
                "timestamp": datetime.utcnow().isoformat()
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=interaction_payload
            )
            assert response.status_code == 200
            
            # End call
            end_payload = {
                "event": "call.ended",
                "call_id": call_id,
                "duration": 60,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=end_payload
            )
            assert response.status_code == 200
            
            return call_id
        
        # Run 5 concurrent call flows
        call_ids = [f"concurrent-call-{i:03d}" for i in range(5)]
        tasks = [simulate_call_flow(call_id) for call_id in call_ids]
        
        completed_calls = await asyncio.gather(*tasks)
        
        # Verify all calls completed successfully
        assert len(completed_calls) == 5
        assert set(completed_calls) == set(call_ids)
        
        # Verify PMS was called for each call
        assert mock_pms_server.call_count >= 5
    
    async def test_call_flow_with_gdpr_compliance(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test call flow with GDPR compliance and PII redaction"""
        
        # Call with PII data that should be redacted
        call_payload = {
            "event": "call.started",
            "call_id": "test-call-gdpr",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "hotel-gdpr",
                "guest_data": {
                    "name": "John Doe",
                    "email": "john.doe@example.com",
                    "phone": "+1234567890",
                    "credit_card": "4111-1111-1111-1111"
                }
            }
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        assert response.status_code == 200
        
        # Verify PII was redacted in logs (check response doesn't contain raw PII)
        response_data = response.json()
        response_str = json.dumps(response_data)
        
        # Should not contain raw credit card or email
        assert "4111-1111-1111-1111" not in response_str
        assert "john.doe@example.com" not in response_str
        
        # Should contain redacted versions
        assert "[REDACTED]" in response_str or "[MASKED]" in response_str
    
    async def test_call_flow_performance_metrics(
        self,
        authenticated_client,
        integration_test_app,
        performance_test_config
    ):
        """Test call flow performance and collect metrics"""
        
        start_time = asyncio.get_event_loop().time()
        
        # Perform a standard call flow
        call_payload = {
            "event": "call.started",
            "call_id": "test-call-perf",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "hotel-perf",
                "reservation_id": "12345"
            }
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        
        end_time = asyncio.get_event_loop().time()
        response_time = end_time - start_time
        
        # Verify performance requirements
        assert response.status_code == 200
        assert response_time < performance_test_config["max_response_time"]
        
        # Check metrics endpoint
        metrics_response = await authenticated_client.get("/metrics")
        assert metrics_response.status_code == 200
        
        metrics_text = metrics_response.text
        
        # Verify key metrics are present
        assert "http_requests_total" in metrics_text
        assert "http_request_duration_seconds" in metrics_text
        assert "call_total" in metrics_text
        
    async def test_call_flow_with_circuit_breaker_integration(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server
    ):
        """Test call flow behavior when circuit breakers are triggered"""
        
        # Configure PMS to fail consistently to trigger circuit breaker
        mock_pms_server.should_fail = True
        
        # Make multiple calls to trigger circuit breaker
        for i in range(5):
            call_payload = {
                "event": "call.started",
                "call_id": f"test-call-cb-{i}",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "hotel-cb",
                    "reservation_id": "12345"
                }
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            
            # First few calls should succeed with degraded service
            # Later calls should be faster due to circuit breaker
            assert response.status_code in [200, 503]
        
        # Reset PMS and verify circuit breaker recovery
        mock_pms_server.should_fail = False
        
        # Wait for circuit breaker to potentially recover
        await asyncio.sleep(1)
        
        # Make another call - should eventually succeed
        recovery_payload = {
            "event": "call.started",
            "call_id": "test-call-recovery",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "hotel-recovery",
                "reservation_id": "12345"
            }
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=recovery_payload
        )
        assert response.status_code == 200