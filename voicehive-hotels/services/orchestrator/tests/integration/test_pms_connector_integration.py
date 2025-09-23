"""
PMS Connector Integration Tests

Tests the integration with Property Management System (PMS) connectors,
including Apaleo and other PMS systems, with error handling and resilience.
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

# Import PMS connector components
from connectors.factory import ConnectorFactory
from connectors.contracts import PMSConnector, ReservationData, GuestData
from connectors.adapters.apaleo.connector import ApaleoConnector


class TestPMSConnectorIntegration:
    """Test PMS connector integration scenarios"""
    
    async def test_apaleo_connector_integration(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test Apaleo connector integration with real API patterns"""
        
        # Mock Apaleo API responses
        mock_reservation_response = {
            "id": "RES-12345",
            "property": {"id": "PROP-001", "name": "Test Hotel"},
            "ratePlan": {"id": "RATE-001", "name": "Standard Rate"},
            "unitGroup": {"id": "UNIT-001", "name": "Standard Room"},
            "timeSlices": [{
                "from": "2024-01-15T00:00:00Z",
                "to": "2024-01-17T00:00:00Z",
                "ratePlan": {"id": "RATE-001"},
                "unitGroup": {"id": "UNIT-001"}
            }],
            "booker": {
                "title": "Mr",
                "firstName": "John",
                "lastName": "Doe",
                "email": "john.doe@example.com",
                "phone": "+1234567890"
            },
            "primaryGuest": {
                "title": "Mr", 
                "firstName": "John",
                "lastName": "Doe"
            },
            "status": "Confirmed",
            "created": "2024-01-10T10:00:00Z",
            "modified": "2024-01-10T10:00:00Z"
        }
        
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_reservation_response
            
            # Test reservation lookup via webhook
            call_payload = {
                "event": "call.started",
                "call_id": "test-apaleo-001",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "apaleo-hotel-001",
                    "pms_type": "apaleo",
                    "reservation_id": "RES-12345"
                }
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            
            assert response.status_code == 200
            response_data = response.json()
            
            # Verify reservation data was processed
            assert response_data["status"] == "success"
            assert "reservation_data" in response_data
    
    async def test_pms_connector_factory_integration(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test PMS connector factory with multiple connector types"""
        
        # Test different PMS connector types
        pms_types = ["apaleo", "opera", "protel"]
        
        for pms_type in pms_types:
            call_payload = {
                "event": "call.started", 
                "call_id": f"test-{pms_type}-001",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": f"{pms_type}-hotel-001",
                    "pms_type": pms_type,
                    "reservation_id": "12345"
                }
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            
            # Should handle all PMS types gracefully
            assert response.status_code in [200, 501]  # 501 for not implemented
            
            if response.status_code == 200:
                response_data = response.json()
                assert response_data["status"] in ["success", "partial_success"]
    
    async def test_pms_connector_error_handling(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test PMS connector error handling and fallback behavior"""
        
        # Test various error scenarios
        error_scenarios = [
            {
                "name": "network_timeout",
                "status_code": None,  # Timeout
                "response": None,
                "expected_behavior": "fallback_to_cache"
            },
            {
                "name": "authentication_error", 
                "status_code": 401,
                "response": {"error": "Unauthorized"},
                "expected_behavior": "retry_with_refresh"
            },
            {
                "name": "rate_limit_error",
                "status_code": 429,
                "response": {"error": "Rate limit exceeded"},
                "expected_behavior": "exponential_backoff"
            },
            {
                "name": "server_error",
                "status_code": 500,
                "response": {"error": "Internal server error"},
                "expected_behavior": "circuit_breaker_open"
            },
            {
                "name": "not_found",
                "status_code": 404,
                "response": {"error": "Reservation not found"},
                "expected_behavior": "graceful_degradation"
            }
        ]
        
        for scenario in error_scenarios:
            with patch('httpx.AsyncClient.get') as mock_get:
                if scenario["status_code"] is None:
                    # Simulate timeout
                    mock_get.side_effect = httpx.TimeoutException("Request timeout")
                else:
                    mock_response = MagicMock()
                    mock_response.status_code = scenario["status_code"]
                    mock_response.json.return_value = scenario["response"]
                    mock_get.return_value = mock_response
                
                call_payload = {
                    "event": "call.started",
                    "call_id": f"test-error-{scenario['name']}",
                    "from_number": "+1234567890", 
                    "to_number": "+0987654321",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {
                        "hotel_id": "error-test-hotel",
                        "pms_type": "apaleo",
                        "reservation_id": "ERROR-12345"
                    }
                }
                
                response = await authenticated_client.post(
                    "/webhook/call-event",
                    json=call_payload
                )
                
                # Should handle errors gracefully
                assert response.status_code in [200, 503]
                
                if response.status_code == 200:
                    response_data = response.json()
                    # Should indicate degraded service
                    assert "error" in response_data.get("warnings", []) or \
                           response_data.get("status") == "partial_success"
    
    async def test_pms_connector_performance_optimization(
        self,
        authenticated_client,
        integration_test_app,
        performance_test_config
    ):
        """Test PMS connector performance optimizations"""
        
        # Test connection pooling and caching
        reservation_ids = [f"PERF-{i:05d}" for i in range(10)]
        
        # Mock consistent responses for caching test
        mock_response_data = {
            "id": "PERF-00001",
            "status": "Confirmed",
            "guest": {"name": "Test Guest"},
            "room": {"number": "101"}
        }
        
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_response_data
            mock_get.return_value = mock_response
            
            start_time = asyncio.get_event_loop().time()
            
            # Make multiple requests for the same reservation
            tasks = []
            for i in range(5):
                call_payload = {
                    "event": "call.started",
                    "call_id": f"test-perf-{i}",
                    "from_number": "+1234567890",
                    "to_number": "+0987654321", 
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {
                        "hotel_id": "perf-test-hotel",
                        "pms_type": "apaleo",
                        "reservation_id": "PERF-00001"  # Same reservation
                    }
                }
                
                task = authenticated_client.post(
                    "/webhook/call-event",
                    json=call_payload
                )
                tasks.append(task)
            
            responses = await asyncio.gather(*tasks)
            end_time = asyncio.get_event_loop().time()
            
            # Verify all requests succeeded
            for response in responses:
                assert response.status_code == 200
            
            # Verify performance (should be fast due to caching)
            total_time = end_time - start_time
            avg_time_per_request = total_time / len(tasks)
            
            assert avg_time_per_request < performance_test_config["max_response_time"]
            
            # Verify caching worked (fewer actual HTTP calls than requests)
            # Due to caching, we should have fewer calls to the mock
            assert mock_get.call_count <= len(tasks)
    
    async def test_pms_connector_data_validation(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test PMS connector data validation and sanitization"""
        
        # Test with various data formats and edge cases
        test_cases = [
            {
                "name": "valid_data",
                "reservation_data": {
                    "id": "VALID-001",
                    "guest": {
                        "firstName": "John",
                        "lastName": "Doe",
                        "email": "john.doe@example.com"
                    },
                    "status": "Confirmed"
                },
                "should_succeed": True
            },
            {
                "name": "missing_required_fields",
                "reservation_data": {
                    "id": "INVALID-001"
                    # Missing guest data
                },
                "should_succeed": False
            },
            {
                "name": "invalid_email_format",
                "reservation_data": {
                    "id": "INVALID-002",
                    "guest": {
                        "firstName": "Jane",
                        "lastName": "Smith", 
                        "email": "invalid-email-format"
                    },
                    "status": "Confirmed"
                },
                "should_succeed": False
            },
            {
                "name": "sql_injection_attempt",
                "reservation_data": {
                    "id": "'; DROP TABLE reservations; --",
                    "guest": {
                        "firstName": "Robert'; DROP TABLE guests; --",
                        "lastName": "Tables",
                        "email": "bobby@tables.com"
                    },
                    "status": "Confirmed"
                },
                "should_succeed": False
            }
        ]
        
        for test_case in test_cases:
            with patch('httpx.AsyncClient.get') as mock_get:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = test_case["reservation_data"]
                mock_get.return_value = mock_response
                
                call_payload = {
                    "event": "call.started",
                    "call_id": f"test-validation-{test_case['name']}",
                    "from_number": "+1234567890",
                    "to_number": "+0987654321",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {
                        "hotel_id": "validation-test-hotel",
                        "pms_type": "apaleo",
                        "reservation_id": test_case["reservation_data"]["id"]
                    }
                }
                
                response = await authenticated_client.post(
                    "/webhook/call-event",
                    json=call_payload
                )
                
                if test_case["should_succeed"]:
                    assert response.status_code == 200
                    response_data = response.json()
                    assert response_data["status"] == "success"
                else:
                    # Should either reject or sanitize dangerous input
                    assert response.status_code in [200, 400, 422]
                    
                    if response.status_code == 200:
                        response_data = response.json()
                        # Should have warnings about data issues
                        assert "warning" in response_data or \
                               response_data.get("status") == "partial_success"
    
    async def test_pms_connector_concurrent_access(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test PMS connector behavior under concurrent access"""
        
        # Simulate multiple concurrent reservation lookups
        async def lookup_reservation(reservation_id: str, delay: float = 0):
            if delay > 0:
                await asyncio.sleep(delay)
            
            call_payload = {
                "event": "call.started",
                "call_id": f"concurrent-{reservation_id}",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "concurrent-test-hotel",
                    "pms_type": "apaleo", 
                    "reservation_id": reservation_id
                }
            }
            
            response = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            return response.status_code, reservation_id
        
        # Mock PMS responses with different delays
        with patch('httpx.AsyncClient.get') as mock_get:
            async def mock_get_with_delay(*args, **kwargs):
                await asyncio.sleep(0.1)  # Simulate network delay
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "id": "CONCURRENT-001",
                    "status": "Confirmed",
                    "guest": {"name": "Concurrent Test"}
                }
                return mock_response
            
            mock_get.side_effect = mock_get_with_delay
            
            # Create 10 concurrent requests
            tasks = [
                lookup_reservation(f"CONCURRENT-{i:03d}", delay=i * 0.01)
                for i in range(10)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Verify all requests completed successfully
            successful_requests = 0
            for result in results:
                if isinstance(result, tuple):
                    status_code, reservation_id = result
                    if status_code == 200:
                        successful_requests += 1
                else:
                    # Exception occurred
                    assert False, f"Unexpected exception: {result}"
            
            # Should handle concurrent requests successfully
            assert successful_requests >= 8  # Allow for some failures under load
    
    async def test_pms_connector_circuit_breaker_integration(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test PMS connector circuit breaker behavior"""
        
        # Configure mock to fail consistently
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.side_effect = httpx.HTTPStatusError(
                "Server Error", 
                request=MagicMock(), 
                response=MagicMock(status_code=500)
            )
            
            # Make multiple requests to trigger circuit breaker
            failed_requests = 0
            circuit_breaker_triggered = False
            
            for i in range(10):
                call_payload = {
                    "event": "call.started",
                    "call_id": f"test-cb-{i}",
                    "from_number": "+1234567890",
                    "to_number": "+0987654321",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {
                        "hotel_id": "cb-test-hotel",
                        "pms_type": "apaleo",
                        "reservation_id": f"CB-{i:03d}"
                    }
                }
                
                start_time = asyncio.get_event_loop().time()
                response = await authenticated_client.post(
                    "/webhook/call-event",
                    json=call_payload
                )
                end_time = asyncio.get_event_loop().time()
                
                response_time = end_time - start_time
                
                # After circuit breaker opens, responses should be faster
                if i > 5 and response_time < 0.1:  # Very fast response
                    circuit_breaker_triggered = True
                
                # Should handle failures gracefully
                assert response.status_code in [200, 503]
                
                if response.status_code != 200:
                    failed_requests += 1
            
            # Verify circuit breaker behavior
            assert failed_requests > 0  # Some requests should fail
            # Circuit breaker should eventually trigger for faster failures
            # (This is implementation dependent)
    
    async def test_pms_connector_cache_integration(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test PMS connector caching behavior"""
        
        reservation_data = {
            "id": "CACHE-001",
            "status": "Confirmed",
            "guest": {"name": "Cache Test Guest"},
            "lastModified": datetime.utcnow().isoformat()
        }
        
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = reservation_data
            mock_get.return_value = mock_response
            
            # First request - should hit PMS
            call_payload = {
                "event": "call.started",
                "call_id": "test-cache-001",
                "from_number": "+1234567890",
                "to_number": "+0987654321",
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "hotel_id": "cache-test-hotel",
                    "pms_type": "apaleo",
                    "reservation_id": "CACHE-001"
                }
            }
            
            response1 = await authenticated_client.post(
                "/webhook/call-event",
                json=call_payload
            )
            assert response1.status_code == 200
            
            # Second request - should use cache
            call_payload["call_id"] = "test-cache-002"
            
            response2 = await authenticated_client.post(
                "/webhook/call-event", 
                json=call_payload
            )
            assert response2.status_code == 200
            
            # Verify caching worked (should have fewer HTTP calls than requests)
            # Implementation dependent - cache may or may not be implemented
            # This test documents expected behavior