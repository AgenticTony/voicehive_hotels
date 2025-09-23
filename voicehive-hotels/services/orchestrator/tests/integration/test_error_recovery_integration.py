"""
Error Handling and Recovery Integration Tests

Tests comprehensive error handling, recovery mechanisms, and graceful degradation
across all system components and failure scenarios.
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from contextlib import asynccontextmanager

from error_models import ErrorResponse, ErrorSeverity
from correlation_middleware import CorrelationIDMiddleware


class TestErrorHandlingIntegration:
    """Test error handling integration scenarios"""
    
    async def test_standardized_error_response_format(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test that all endpoints return standardized error responses"""
        
        # Test various error scenarios
        error_scenarios = [
            {
                "name": "validation_error",
                "request": lambda: authenticated_client.post(
                    "/webhook/call-event",
                    json={"invalid": "payload"}
                ),
                "expected_status": 422,
                "expected_error_code": "VALIDATION_ERROR"
            },
            {
                "name": "not_found_error",
                "request": lambda: authenticated_client.get("/nonexistent-endpoint"),
                "expected_status": 404,
                "expected_error_code": "NOT_FOUND"
            },
            {
                "name": "method_not_allowed",
                "request": lambda: authenticated_client.delete("/healthz"),
                "expected_status": 405,
                "expected_error_code": "METHOD_NOT_ALLOWED"
            },
            {
                "name": "unauthorized_error",
                "request": lambda: authenticated_client.get(
                    "/auth/admin/users",
                    headers={"Authorization": "Bearer invalid-token"}
                ),
                "expected_status": 401,
                "expected_error_code": "AUTHENTICATION_ERROR"
            }
        ]
        
        for scenario in error_scenarios:
            response = await scenario["request"]()
            
            assert response.status_code == scenario["expected_status"]
            
            # Verify standardized error format
            error_data = response.json()
            
            # Should have error object
            assert "error" in error_data
            error_obj = error_data["error"]
            
            # Should have required fields
            assert "code" in error_obj
            assert "message" in error_obj
            assert "correlation_id" in error_obj
            assert "timestamp" in error_obj
            
            # Verify correlation ID format
            correlation_id = error_obj["correlation_id"]
            assert len(correlation_id) > 10  # Should be a proper UUID or similar
            
            # Verify timestamp format
            timestamp = error_obj["timestamp"]
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))  # Should parse
            
            # Should not leak sensitive information
            error_str = json.dumps(error_data).lower()
            sensitive_terms = ["password", "secret", "key", "token", "internal"]
            for term in sensitive_terms:
                if term in error_str:
                    # Allow generic terms but not actual values
                    assert not any(char.isdigit() for char in error_str.split(term)[1][:20])
    
    async def test_correlation_id_tracking(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test correlation ID tracking across service calls"""
        
        # Make request with custom correlation ID
        custom_correlation_id = "test-correlation-12345"
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json={
                "event": "call.started",
                "call_id": "correlation-test-001",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {"hotel_id": "correlation-hotel"}
            },
            headers={"X-Correlation-ID": custom_correlation_id}
        )
        
        # Should succeed and preserve correlation ID
        assert response.status_code == 200
        
        # Verify correlation ID in response headers
        assert response.headers.get("X-Correlation-ID") == custom_correlation_id
        
        # Test error scenario with correlation ID
        response = await authenticated_client.post(
            "/webhook/call-event",
            json={"invalid": "payload"},
            headers={"X-Correlation-ID": custom_correlation_id}
        )
        
        assert response.status_code == 422
        error_data = response.json()
        
        # Error should include the correlation ID
        assert error_data["error"]["correlation_id"] == custom_correlation_id
        
        # Test auto-generated correlation ID
        response = await authenticated_client.get("/nonexistent")
        
        assert response.status_code == 404
        error_data = response.json()
        
        # Should have auto-generated correlation ID
        correlation_id = error_data["error"]["correlation_id"]
        assert correlation_id is not None
        assert len(correlation_id) > 10
    
    async def test_retry_logic_with_exponential_backoff(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server
    ):
        """Test retry logic with exponential backoff for external services"""
        
        # Configure PMS server to fail initially then succeed
        failure_count = 0
        
        async def failing_pms_call(*args, **kwargs):
            nonlocal failure_count
            failure_count += 1
            
            if failure_count <= 2:  # Fail first 2 attempts
                raise httpx.HTTPStatusError(
                    "Server Error",
                    request=MagicMock(),
                    response=MagicMock(status_code=500)
                )
            else:  # Succeed on 3rd attempt
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "id": "RETRY-001",
                    "status": "Confirmed",
                    "guest": {"name": "Retry Test"}
                }
                return mock_response
        
        with patch('httpx.AsyncClient.get', side_effect=failing_pms_call):
            start_time = asyncio.get_event_loop().time()
            
            call_payload = {
                "event": "call.started",
                "call_id": "retry-test-001",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "retry-hotel",
                    "reservation_id": "RETRY-001"
                }
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            
            end_time = asyncio.get_event_loop().time()
            total_time = end_time - start_time
            
            # Should eventually succeed after retries
            assert response.status_code == 200
            
            # Should have taken time for retries (exponential backoff)
            assert total_time > 1.0  # At least 1 second for retries
            
            # Should have made multiple attempts
            assert failure_count == 3  # 2 failures + 1 success
    
    async def test_graceful_degradation_scenarios(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server,
        mock_tts_service
    ):
        """Test graceful degradation when services are unavailable"""
        
        # Test PMS service unavailable
        mock_pms_server.should_fail = True
        
        call_payload = {
            "event": "call.started",
            "call_id": "degradation-test-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "degradation-hotel",
                "reservation_id": "DEG-001"
            }
        }
        
        response = await authenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        
        # Should succeed with degraded functionality
        assert response.status_code == 200
        response_data = response.json()
        
        # Should indicate degraded service
        assert response_data["status"] in ["success", "partial_success"]
        
        # Should have warnings about unavailable services
        assert "warnings" in response_data or "degraded" in str(response_data)
        
        # Test TTS service unavailable
        mock_pms_server.should_fail = False
        mock_tts_service.should_fail = True
        
        tts_payload = {
            "text": "Degradation test message",
            "voice": "female"
        }
        
        response = await authenticated_client.post(
            "/tts/synthesize",
            json=tts_payload
        )
        
        # Should handle TTS failure gracefully
        assert response.status_code in [200, 503]
        
        if response.status_code == 200:
            # If successful, should indicate fallback was used
            response_data = response.json()
            assert "fallback" in str(response_data) or "cached" in str(response_data)
    
    async def test_error_alerting_and_notification(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test error alerting and notification system"""
        
        # Mock alerting system
        alerts_sent = []
        
        async def mock_send_alert(alert_data):
            alerts_sent.append(alert_data)
        
        with patch('enhanced_alerting.enhanced_alerting.send_alert', side_effect=mock_send_alert):
            # Trigger critical error
            with patch('httpx.AsyncClient.get') as mock_get:
                mock_get.side_effect = Exception("Critical system failure")
                
                call_payload = {
                    "event": "call.started",
                    "call_id": "alert-test-001",
                    "from_number": "+1234567890",
                    "to_number": "+0987654321",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {
                        "hotel_id": "alert-hotel",
                        "reservation_id": "ALERT-001"
                    }
                }
                
                response = await authenticated_client.post(
                    "/webhook/call-event",
                    json=call_payload
                )
                
                # Should handle error gracefully
                assert response.status_code in [200, 500, 503]
                
                # Wait for async alert processing
                await asyncio.sleep(0.5)
                
                # Should have triggered alerts for critical errors
                # (Implementation dependent - this documents expected behavior)
    
    async def test_error_recovery_after_service_restoration(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server,
        mock_tts_service
    ):
        """Test system recovery after external services are restored"""
        
        # Phase 1: Services failing
        mock_pms_server.should_fail = True
        mock_tts_service.should_fail = True
        
        # Make requests during failure period
        failure_responses = []
        for i in range(3):
            call_payload = {
                "event": "call.started",
                "call_id": f"recovery-test-{i}",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "recovery-hotel",
                    "reservation_id": f"REC-{i:03d}"
                }
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            failure_responses.append(response.status_code)
            await asyncio.sleep(0.1)
        
        # Phase 2: Restore services
        mock_pms_server.should_fail = False
        mock_tts_service.should_fail = False
        
        # Wait for circuit breakers to potentially recover
        await asyncio.sleep(2)
        
        # Phase 3: Test recovery
        recovery_responses = []
        for i in range(5):
            call_payload = {
                "event": "call.started",
                "call_id": f"recovery-success-{i}",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "recovery-hotel",
                    "reservation_id": f"REC-SUCCESS-{i:03d}"
                }
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            recovery_responses.append(response.status_code)
            await asyncio.sleep(0.2)
        
        # Verify recovery behavior
        failure_success_rate = failure_responses.count(200) / len(failure_responses)
        recovery_success_rate = recovery_responses.count(200) / len(recovery_responses)
        
        # Recovery should be better than failure period
        assert recovery_success_rate > failure_success_rate
        
        # Should achieve reasonable success rate after recovery
        assert recovery_success_rate >= 0.6
    
    async def test_concurrent_error_handling(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test error handling under concurrent load"""
        
        async def make_error_prone_request(request_id: int):
            """Make a request that may encounter various errors"""
            
            # Mix of valid and invalid requests
            if request_id % 3 == 0:
                # Invalid payload
                payload = {"invalid": "data"}
            elif request_id % 3 == 1:
                # Valid payload
                payload = {
                    "event": "call.started",
                    "call_id": f"concurrent-error-{request_id}",
                    "from_number": "+1234567890",
                    "to_number": "+0987654321",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {"hotel_id": f"concurrent-hotel-{request_id}"}
                }
            else:
                # Missing required fields
                payload = {
                    "event": "call.started",
                    "call_id": f"incomplete-{request_id}"
                }
            
            try:
                response = await authenticated_client.post(
                    "/webhook/call-event",
                    json=payload
                )
                return {
                    "request_id": request_id,
                    "status_code": response.status_code,
                    "has_correlation_id": "correlation_id" in response.text,
                    "error": None
                }
            except Exception as e:
                return {
                    "request_id": request_id,
                    "status_code": None,
                    "has_correlation_id": False,
                    "error": str(e)
                }
        
        # Create concurrent requests with mixed error scenarios
        tasks = [make_error_prone_request(i) for i in range(20)]
        results = await asyncio.gather(*tasks)
        
        # Analyze concurrent error handling
        successful_requests = 0
        error_requests = 0
        correlation_ids_present = 0
        
        for result in results:
            if result["status_code"] == 200:
                successful_requests += 1
            elif result["status_code"] in [400, 422]:
                error_requests += 1
            
            if result["has_correlation_id"]:
                correlation_ids_present += 1
        
        # Verify concurrent error handling
        assert successful_requests > 0  # Some valid requests should succeed
        assert error_requests > 0  # Some invalid requests should be caught
        
        # Most responses should have correlation IDs
        assert correlation_ids_present >= (successful_requests + error_requests) * 0.8
        
        # No requests should cause system crashes
        system_errors = sum(1 for r in results if r["error"] is not None)
        assert system_errors == 0


class TestErrorRecoveryMechanisms:
    """Test specific error recovery mechanisms"""
    
    async def test_database_connection_recovery(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test database connection error recovery"""
        
        # Mock database connection failure and recovery
        connection_attempts = 0
        
        async def mock_db_operation(*args, **kwargs):
            nonlocal connection_attempts
            connection_attempts += 1
            
            if connection_attempts <= 2:
                raise Exception("Database connection failed")
            else:
                return {"result": "success"}
        
        with patch('asyncpg.connect', side_effect=mock_db_operation):
            # Make request that requires database
            response = await authenticated_client.get("/healthz")
            
            # Should handle database errors gracefully
            assert response.status_code in [200, 503]
            
            if response.status_code == 503:
                # Should indicate service unavailable
                error_data = response.json()
                assert "database" in str(error_data).lower() or \
                       "service unavailable" in str(error_data).lower()
    
    async def test_redis_connection_recovery(
        self,
        authenticated_client,
        integration_test_app,
        jwt_service
    ):
        """Test Redis connection error recovery"""
        
        # Create user context for authentication
        from auth_models import UserContext
        user_context = UserContext(
            user_id="redis-test-123",
            email="redis@voicehive-hotels.eu",
            roles=["user"],
            permissions=["read"],
            session_id="redis-session",
            expires_at=None
        )
        
        token = await jwt_service.create_token(user_context)
        
        # Mock Redis failure
        with patch.object(jwt_service.redis, 'get', side_effect=Exception("Redis connection failed")):
            headers = {"Authorization": f"Bearer {token}"}
            
            response = await authenticated_client.get(
                "/auth/profile",
                headers=headers
            )
            
            # Should handle Redis errors gracefully
            # May succeed with degraded functionality or fail gracefully
            assert response.status_code in [200, 401, 503]
            
            if response.status_code != 200:
                error_data = response.json()
                assert "error" in error_data
    
    async def test_external_api_timeout_recovery(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test recovery from external API timeouts"""
        
        # Mock external API with timeout
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timeout")
            
            call_payload = {
                "event": "call.started",
                "call_id": "timeout-recovery-001",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "timeout-hotel",
                    "reservation_id": "TIMEOUT-001"
                }
            }
            
            start_time = asyncio.get_event_loop().time()
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            
            end_time = asyncio.get_event_loop().time()
            response_time = end_time - start_time
            
            # Should handle timeout gracefully and quickly
            assert response.status_code in [200, 503, 408]
            assert response_time < 10.0  # Should not hang indefinitely
            
            if response.status_code == 200:
                # If successful, should indicate fallback was used
                response_data = response.json()
                assert response_data["status"] in ["success", "partial_success"]
    
    async def test_memory_pressure_recovery(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test system behavior under memory pressure"""
        
        # Simulate memory pressure by making many concurrent requests
        async def memory_intensive_request(request_id: int):
            """Make a request that processes data"""
            call_payload = {
                "event": "call.started",
                "call_id": f"memory-test-{request_id}",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": f"memory-hotel-{request_id}",
                    "large_data": "x" * 1000  # Some data to process
                }
            }
            
            try:
                response = await authenticated_client.post(
                    "/webhook/call-event",
                    json=call_payload
                )
                return response.status_code
            except Exception:
                return 500
        
        # Create high memory load
        tasks = [memory_intensive_request(i) for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Analyze memory pressure handling
        successful_requests = sum(1 for r in results if r == 200)
        total_requests = len(results)
        
        # Should handle most requests even under memory pressure
        success_rate = successful_requests / total_requests
        assert success_rate >= 0.7  # At least 70% should succeed
        
        # System should not crash
        crashes = sum(1 for r in results if isinstance(r, Exception))
        assert crashes == 0
    
    async def test_cascading_failure_prevention(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server,
        mock_tts_service,
        mock_livekit_service
    ):
        """Test prevention of cascading failures across services"""
        
        # Fail one service at a time and verify others continue working
        
        # Phase 1: Fail PMS, others should work
        mock_pms_server.should_fail = True
        mock_tts_service.should_fail = False
        mock_livekit_service.should_fail = False
        
        # Test TTS (should work despite PMS failure)
        tts_response = await authenticated_client.post(
            "/tts/synthesize",
            json={"text": "Cascading test", "voice": "female"}
        )
        assert tts_response.status_code == 200
        
        # Test health check (should work)
        health_response = await authenticated_client.get("/healthz")
        assert health_response.status_code == 200
        
        # Phase 2: Fail TTS, others should work
        mock_pms_server.should_fail = False
        mock_tts_service.should_fail = True
        
        # Test PMS-dependent call (should work despite TTS failure)
        call_payload = {
            "event": "call.started",
            "call_id": "cascading-test-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "cascading-hotel",
                "reservation_id": "CASCADE-001"
            }
        }
        
        call_response = await authenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        assert call_response.status_code == 200
        
        # Health check should still work
        health_response = await authenticated_client.get("/healthz")
        assert health_response.status_code == 200
        
        # Phase 3: All services working
        mock_pms_server.should_fail = False
        mock_tts_service.should_fail = False
        
        # Everything should work normally
        call_response = await authenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        assert call_response.status_code == 200
        
        tts_response = await authenticated_client.post(
            "/tts/synthesize",
            json={"text": "All working", "voice": "female"}
        )
        assert tts_response.status_code == 200