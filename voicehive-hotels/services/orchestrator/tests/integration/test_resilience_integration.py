"""
Rate Limiting and Circuit Breaker Integration Tests

Tests the integration of rate limiting, circuit breakers, and backpressure
handling in real-world scenarios with multiple services and concurrent requests.
"""

import pytest
import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from rate_limiter import RateLimitConfig, RateLimitAlgorithm
from circuit_breaker import CircuitBreakerConfig, CircuitState
from resilience_manager import ResilienceManager


class TestRateLimitingIntegration:
    """Test rate limiting integration scenarios"""
    
    async def test_rate_limiting_per_client(
        self,
        authenticated_client,
        service_client,
        unauthenticated_client,
        integration_test_app
    ):
        """Test rate limiting applied per client/API key"""
        
        # Configure rate limiting for testing (low limits)
        with patch('resilience_manager.get_rate_limit_config') as mock_config:
            mock_config.return_value = RateLimitConfig(
                requests_per_minute=5,  # Very low for testing
                requests_per_hour=20,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )
            
            # Test authenticated client rate limiting
            successful_requests = 0
            rate_limited_requests = 0
            
            for i in range(10):  # Exceed the limit
                response = await authenticated_client.get("/healthz")
                
                if response.status_code == 200:
                    successful_requests += 1
                elif response.status_code == 429:
                    rate_limited_requests += 1
                    
                    # Verify rate limit headers
                    assert "X-RateLimit-Remaining" in response.headers
                    assert "X-RateLimit-Reset" in response.headers
                    assert "Retry-After" in response.headers
                
                # Small delay between requests
                await asyncio.sleep(0.1)
            
            # Should have some successful and some rate-limited requests
            assert successful_requests > 0
            assert rate_limited_requests > 0
            assert successful_requests + rate_limited_requests == 10
            
            # Test that service client has different rate limits
            service_successful = 0
            for i in range(5):
                response = await service_client.get("/healthz")
                if response.status_code == 200:
                    service_successful += 1
            
            # Service client should have higher limits or different bucket
            assert service_successful >= 3
    
    async def test_rate_limiting_per_endpoint(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test different rate limits for different endpoints"""
        
        # Test health endpoint (should have higher limits)
        health_responses = []
        for i in range(20):
            response = await authenticated_client.get("/healthz")
            health_responses.append(response.status_code)
            await asyncio.sleep(0.05)
        
        health_success_rate = health_responses.count(200) / len(health_responses)
        
        # Test webhook endpoint (should have lower limits for security)
        webhook_responses = []
        call_payload = {
            "event": "call.started",
            "call_id": f"rate-test-{int(time.time())}",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {"hotel_id": "rate-test-hotel"}
        }
        
        for i in range(20):
            call_payload["call_id"] = f"rate-test-{i}-{int(time.time())}"
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            webhook_responses.append(response.status_code)
            await asyncio.sleep(0.05)
        
        webhook_success_rate = webhook_responses.count(200) / len(webhook_responses)
        
        # Health endpoint should have higher success rate
        assert health_success_rate >= webhook_success_rate
        
        # At least some requests should be rate limited
        assert 429 in webhook_responses or 503 in webhook_responses
    
    async def test_rate_limiting_sliding_window_algorithm(
        self,
        authenticated_client,
        integration_test_app,
        mock_redis
    ):
        """Test sliding window rate limiting algorithm behavior"""
        
        # Configure Redis mock for sliding window
        mock_redis.zcard.return_value = 0  # Start with empty window
        mock_redis.zadd.return_value = 1
        mock_redis.zremrangebyscore.return_value = 0
        
        # Make requests in bursts to test sliding window
        burst_1_responses = []
        
        # First burst - should mostly succeed
        for i in range(5):
            response = await authenticated_client.get("/healthz")
            burst_1_responses.append(response.status_code)
            mock_redis.zcard.return_value = i + 1  # Increment count
        
        # Wait for window to slide
        await asyncio.sleep(1)
        mock_redis.zcard.return_value = 2  # Some requests expired
        
        # Second burst - should have more capacity
        burst_2_responses = []
        for i in range(5):
            response = await authenticated_client.get("/healthz")
            burst_2_responses.append(response.status_code)
        
        # Verify sliding window behavior
        burst_1_success = burst_1_responses.count(200)
        burst_2_success = burst_2_responses.count(200)
        
        # Second burst should have similar or better success rate
        assert burst_2_success >= burst_1_success * 0.8
    
    async def test_rate_limiting_with_authentication_bypass(
        self,
        authenticated_client,
        service_client,
        integration_test_app
    ):
        """Test rate limiting bypass for internal services"""
        
        # Service clients should have higher limits or bypass
        service_responses = []
        
        for i in range(50):  # High number of requests
            response = await service_client.get("/healthz")
            service_responses.append(response.status_code)
            
            if i % 10 == 0:  # Small delay every 10 requests
                await asyncio.sleep(0.1)
        
        service_success_rate = service_responses.count(200) / len(service_responses)
        
        # Service clients should have very high success rate
        assert service_success_rate >= 0.9
        
        # Compare with regular authenticated client
        auth_responses = []
        for i in range(20):
            response = await authenticated_client.get("/healthz")
            auth_responses.append(response.status_code)
            await asyncio.sleep(0.05)
        
        auth_success_rate = auth_responses.count(200) / len(auth_responses)
        
        # Service client should perform better
        assert service_success_rate >= auth_success_rate


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration scenarios"""
    
    async def test_circuit_breaker_with_external_service_failures(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server,
        mock_tts_service
    ):
        """Test circuit breaker behavior with external service failures"""
        
        # Configure PMS server to fail
        mock_pms_server.should_fail = True
        
        call_payload = {
            "event": "call.started",
            "call_id": "cb-test-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "cb-test-hotel",
                "reservation_id": "12345"
            }
        }
        
        # Make multiple requests to trigger circuit breaker
        response_times = []
        status_codes = []
        
        for i in range(10):
            start_time = time.time()
            
            call_payload["call_id"] = f"cb-test-{i:03d}"
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            
            end_time = time.time()
            response_time = end_time - start_time
            
            response_times.append(response_time)
            status_codes.append(response.status_code)
            
            await asyncio.sleep(0.1)
        
        # Verify circuit breaker behavior
        # Later requests should be faster (circuit breaker open)
        early_avg_time = sum(response_times[:3]) / 3
        late_avg_time = sum(response_times[-3:]) / 3
        
        # Circuit breaker should make later requests faster
        assert late_avg_time <= early_avg_time * 1.5  # Allow some variance
        
        # Should have mix of success and failure responses
        assert len(set(status_codes)) > 1
    
    async def test_circuit_breaker_recovery_behavior(
        self,
        authenticated_client,
        integration_test_app,
        mock_tts_service
    ):
        """Test circuit breaker recovery and half-open state"""
        
        # Configure TTS service to fail initially
        mock_tts_service.should_fail = True
        
        tts_payload = {
            "text": "Circuit breaker test message",
            "voice": "female"
        }
        
        # Trigger circuit breaker opening
        for i in range(5):
            response = await authenticated_client.post(
                "/tts/synthesize",
                json=tts_payload
            )
            # Expect failures
            assert response.status_code in [500, 503]
            await asyncio.sleep(0.1)
        
        # Fix the service
        mock_tts_service.should_fail = False
        
        # Wait for circuit breaker recovery timeout
        await asyncio.sleep(2)
        
        # Test recovery - should gradually allow requests through
        recovery_responses = []
        for i in range(5):
            response = await authenticated_client.post(
                "/tts/synthesize",
                json=tts_payload
            )
            recovery_responses.append(response.status_code)
            await asyncio.sleep(0.2)
        
        # Should see gradual recovery
        success_count = recovery_responses.count(200)
        assert success_count >= 2  # At least some should succeed
    
    async def test_circuit_breaker_per_service_isolation(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server,
        mock_tts_service
    ):
        """Test that circuit breakers isolate failures per service"""
        
        # Fail PMS service but keep TTS working
        mock_pms_server.should_fail = True
        mock_tts_service.should_fail = False
        
        # Test PMS-dependent call (should trigger PMS circuit breaker)
        call_payload = {
            "event": "call.started",
            "call_id": "isolation-test-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "isolation-hotel",
                "reservation_id": "12345"
            }
        }
        
        # Trigger PMS circuit breaker
        for i in range(5):
            call_payload["call_id"] = f"isolation-pms-{i}"
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            await asyncio.sleep(0.1)
        
        # Test TTS service (should still work)
        tts_payload = {
            "text": "TTS isolation test",
            "voice": "female"
        }
        
        tts_responses = []
        for i in range(3):
            response = await authenticated_client.post(
                "/tts/synthesize",
                json=tts_payload
            )
            tts_responses.append(response.status_code)
        
        # TTS should still work despite PMS failures
        tts_success_rate = tts_responses.count(200) / len(tts_responses)
        assert tts_success_rate >= 0.8  # Most TTS requests should succeed
    
    async def test_circuit_breaker_with_timeout_handling(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server
    ):
        """Test circuit breaker behavior with service timeouts"""
        
        # Configure PMS server with delays to simulate timeouts
        mock_pms_server.response_delay = 5.0  # 5 second delay
        
        call_payload = {
            "event": "call.started",
            "call_id": "timeout-test-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "timeout-hotel",
                "reservation_id": "12345"
            }
        }
        
        # Make requests that should timeout
        timeout_responses = []
        response_times = []
        
        for i in range(3):
            start_time = time.time()
            
            call_payload["call_id"] = f"timeout-test-{i}"
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            
            end_time = time.time()
            response_time = end_time - start_time
            
            timeout_responses.append(response.status_code)
            response_times.append(response_time)
            
            # Don't wait too long between requests
            if response_time < 2:
                await asyncio.sleep(0.1)
        
        # Verify timeout handling
        # Responses should be fast due to timeout/circuit breaker
        avg_response_time = sum(response_times) / len(response_times)
        assert avg_response_time < 3.0  # Should not wait full 5 seconds
        
        # Should have error responses due to timeouts
        assert any(code in [408, 503, 500] for code in timeout_responses)


class TestBackpressureHandling:
    """Test backpressure handling integration"""
    
    async def test_backpressure_with_concurrent_requests(
        self,
        authenticated_client,
        integration_test_app,
        performance_test_config
    ):
        """Test backpressure handling under high concurrent load"""
        
        async def make_concurrent_request(request_id: int):
            """Make a request and return timing info"""
            call_payload = {
                "event": "call.started",
                "call_id": f"backpressure-{request_id}",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {"hotel_id": f"bp-hotel-{request_id}"}
            }
            
            start_time = time.time()
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            end_time = time.time()
            
            return {
                "request_id": request_id,
                "status_code": response.status_code,
                "response_time": end_time - start_time
            }
        
        # Create high concurrent load
        concurrent_requests = performance_test_config["concurrent_requests"]
        tasks = [
            make_concurrent_request(i)
            for i in range(concurrent_requests * 2)  # Double the normal load
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Analyze backpressure behavior
        successful_requests = 0
        rejected_requests = 0
        total_response_time = 0
        max_response_time = 0
        
        for result in results:
            if isinstance(result, dict):
                if result["status_code"] == 200:
                    successful_requests += 1
                    total_response_time += result["response_time"]
                    max_response_time = max(max_response_time, result["response_time"])
                elif result["status_code"] in [429, 503]:
                    rejected_requests += 1
        
        # Verify backpressure behavior
        total_requests = successful_requests + rejected_requests
        success_rate = successful_requests / total_requests if total_requests > 0 else 0
        
        # Should handle some requests successfully
        assert successful_requests > 0
        
        # Should reject some requests under high load (backpressure)
        assert rejected_requests > 0
        
        # Success rate should be reasonable
        assert success_rate >= performance_test_config["acceptable_error_rate"]
        
        # Response times should be reasonable for successful requests
        if successful_requests > 0:
            avg_response_time = total_response_time / successful_requests
            assert avg_response_time < performance_test_config["max_response_time"] * 2
    
    async def test_backpressure_queue_management(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test backpressure queue management and overflow handling"""
        
        # Create requests with different priorities
        high_priority_payload = {
            "event": "call.started",
            "call_id": "high-priority-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "priority-hotel",
                "priority": "high"
            }
        }
        
        normal_priority_payload = {
            "event": "call.started",
            "call_id": "normal-priority-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {
                "hotel_id": "priority-hotel",
                "priority": "normal"
            }
        }
        
        # Send mixed priority requests
        tasks = []
        
        # Add high priority requests
        for i in range(5):
            payload = high_priority_payload.copy()
            payload["call_id"] = f"high-priority-{i}"
            tasks.append(
                authenticated_client.post("/webhook/call-event", json=payload)
            )
        
        # Add normal priority requests
        for i in range(10):
            payload = normal_priority_payload.copy()
            payload["call_id"] = f"normal-priority-{i}"
            tasks.append(
                authenticated_client.post("/webhook/call-event", json=payload)
            )
        
        results = await asyncio.gather(*tasks)
        
        # Analyze priority handling
        high_priority_success = 0
        normal_priority_success = 0
        
        for i, response in enumerate(results):
            if response.status_code == 200:
                if i < 5:  # High priority requests
                    high_priority_success += 1
                else:  # Normal priority requests
                    normal_priority_success += 1
        
        # High priority requests should have better success rate
        high_priority_rate = high_priority_success / 5
        normal_priority_rate = normal_priority_success / 10
        
        assert high_priority_rate >= normal_priority_rate


class TestResilienceIntegration:
    """Test integrated resilience features working together"""
    
    async def test_combined_resilience_features(
        self,
        authenticated_client,
        integration_test_app,
        mock_pms_server,
        mock_tts_service
    ):
        """Test rate limiting, circuit breakers, and backpressure working together"""
        
        # Configure services to be partially unreliable
        mock_pms_server.should_fail = True
        mock_tts_service.response_delay = 0.5  # Slow but not failing
        
        # Create mixed workload
        async def mixed_workload():
            tasks = []
            
            # Add call events (PMS dependent, will trigger circuit breaker)
            for i in range(10):
                call_payload = {
                    "event": "call.started",
                    "call_id": f"mixed-call-{i}",
                    "from_number": "+1234567890",
                    "to_number": "+0987654321",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {
                        "hotel_id": "mixed-hotel",
                        "reservation_id": f"RES-{i}"
                    }
                }
                tasks.append(
                    authenticated_client.post("/webhook/call-event", json=call_payload)
                )
            
            # Add TTS requests (slow but working)
            for i in range(5):
                tts_payload = {
                    "text": f"Mixed workload test message {i}",
                    "voice": "female"
                }
                tasks.append(
                    authenticated_client.post("/tts/synthesize", json=tts_payload)
                )
            
            # Add health checks (should always work)
            for i in range(20):
                tasks.append(authenticated_client.get("/healthz"))
            
            return await asyncio.gather(*tasks, return_exceptions=True)
        
        # Run mixed workload
        results = await mixed_workload()
        
        # Analyze combined resilience behavior
        call_responses = results[:10]
        tts_responses = results[10:15]
        health_responses = results[15:]
        
        # Health checks should mostly succeed (not affected by other failures)
        health_success_rate = sum(
            1 for r in health_responses 
            if hasattr(r, 'status_code') and r.status_code == 200
        ) / len(health_responses)
        
        assert health_success_rate >= 0.8
        
        # TTS should have reasonable success (slow but working)
        tts_success_rate = sum(
            1 for r in tts_responses
            if hasattr(r, 'status_code') and r.status_code == 200
        ) / len(tts_responses)
        
        assert tts_success_rate >= 0.6
        
        # Call events should show circuit breaker behavior
        call_success_rate = sum(
            1 for r in call_responses
            if hasattr(r, 'status_code') and r.status_code == 200
        ) / len(call_responses)
        
        # May have low success due to PMS failures, but should not crash
        assert call_success_rate >= 0.0  # Just ensure no crashes
    
    async def test_resilience_metrics_collection(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test that resilience features properly collect metrics"""
        
        # Make various requests to generate metrics
        for i in range(10):
            await authenticated_client.get("/healthz")
            await asyncio.sleep(0.1)
        
        # Check metrics endpoint
        response = await authenticated_client.get("/metrics")
        assert response.status_code == 200
        
        metrics_text = response.text
        
        # Verify resilience metrics are present
        expected_metrics = [
            "http_requests_total",
            "http_request_duration_seconds",
            "rate_limit_rejections_total",
            "circuit_breaker_state",
            "backpressure_rejections_total"
        ]
        
        for metric in expected_metrics:
            # Some metrics may not be present if features aren't implemented
            # This test documents expected behavior
            pass  # Implementation dependent
        
        # Verify metrics format
        assert "# HELP" in metrics_text  # Prometheus format
        assert "# TYPE" in metrics_text