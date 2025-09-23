"""
Authentication System Load Testing

Tests the authentication and authorization system's performance under
high load conditions including JWT validation, API key verification,
and session management.
"""

import pytest
import asyncio
import time
from typing import List, Dict, Any
from datetime import datetime, timedelta
import json
import random
import string

from .conftest import LoadTestRunner, LoadTestMetrics, PerformanceMonitor


class TestAuthenticationSystemLoad:
    """Test authentication system performance under load"""
    
    @pytest.mark.asyncio
    async def test_jwt_authentication_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test JWT authentication under high load"""
        
        performance_monitor.start_monitoring()
        
        # Generate test user credentials
        test_users = [
            {
                "email": f"user{i}@voicehive-hotels.eu",
                "password": f"testpass{i}",
                "user_id": f"user_{i}"
            }
            for i in range(100)  # 100 test users
        ]
        
        try:
            # Test login operations under load
            login_metrics = await load_test_runner.run_concurrent_requests(
                endpoint="/auth/login",
                method="POST",
                payload=lambda: random.choice(test_users),  # Random user each time
                concurrent_users=load_test_config["concurrent_users"],
                requests_per_user=load_test_config["requests_per_user"],
                delay_between_requests=0.1
            )
            
            # Validate login performance
            assert login_metrics.error_rate <= load_test_config["max_error_rate"], \
                f"Login error rate {login_metrics.error_rate:.2%} exceeds threshold"
            
            assert login_metrics.avg_response_time <= load_test_config["max_response_time"], \
                f"Login avg response time {login_metrics.avg_response_time:.2f}s exceeds threshold"
            
            print(f"\n=== JWT Authentication Load Test Results ===")
            print(f"Login Operations: {login_metrics.total_requests}")
            print(f"Success Rate: {(login_metrics.successful_requests/login_metrics.total_requests)*100:.1f}%")
            print(f"Average Response Time: {login_metrics.avg_response_time:.3f}s")
            print(f"Logins per Second: {login_metrics.requests_per_second:.1f}")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_jwt_validation_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        jwt_service,
        test_user_context,
        load_test_config: Dict[str, Any]
    ):
        """Test JWT token validation under load"""
        
        performance_monitor.start_monitoring()
        
        # Pre-generate valid JWT tokens
        valid_tokens = []
        for i in range(50):
            user_context = test_user_context.copy()
            user_context.user_id = f"load_test_user_{i}"
            user_context.email = f"loadtest{i}@voicehive-hotels.eu"
            
            token = await jwt_service.create_token(user_context)
            valid_tokens.append(token)
        
        # Generate some expired/invalid tokens for testing
        invalid_tokens = [
            "invalid.jwt.token",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature",
            ""  # Empty token
        ]
        
        try:
            # Test protected endpoint access with valid tokens
            valid_token_metrics = []
            
            for i in range(0, len(valid_tokens), 10):  # Test in batches
                batch_tokens = valid_tokens[i:i+10]
                
                for token in batch_tokens:
                    headers = {"Authorization": f"Bearer {token}"}
                    
                    metrics = await load_test_runner.run_concurrent_requests(
                        endpoint="/api/v1/protected/user-profile",
                        method="GET",
                        headers=headers,
                        concurrent_users=load_test_config["concurrent_users"] // 5,
                        requests_per_user=load_test_config["requests_per_user"] // 5,
                        delay_between_requests=0.05
                    )
                    
                    valid_token_metrics.append(metrics)
            
            # Test with invalid tokens
            invalid_token_results = []
            
            for invalid_token in invalid_tokens:
                headers = {"Authorization": f"Bearer {invalid_token}"}
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/api/v1/protected/user-profile",
                    method="GET",
                    headers=headers,
                    concurrent_users=load_test_config["concurrent_users"] // 10,
                    requests_per_user=5,  # Fewer requests for invalid tokens
                    delay_between_requests=0.1
                )
                
                invalid_token_results.append(metrics)
            
            # Analyze valid token performance
            if valid_token_metrics:
                avg_valid_response_time = sum(m.avg_response_time for m in valid_token_metrics) / len(valid_token_metrics)
                avg_valid_error_rate = sum(m.error_rate for m in valid_token_metrics) / len(valid_token_metrics)
                
                assert avg_valid_error_rate <= load_test_config["max_error_rate"], \
                    f"Valid token error rate {avg_valid_error_rate:.2%} exceeds threshold"
                
                assert avg_valid_response_time <= load_test_config["max_response_time"], \
                    f"Valid token avg response time {avg_valid_response_time:.2f}s exceeds threshold"
            
            # Invalid tokens should be rejected quickly
            for metrics in invalid_token_results:
                # Invalid tokens should result in 401 errors (which count as "successful" rejections)
                # Response time should be fast for invalid tokens
                assert metrics.avg_response_time <= 0.1, \
                    f"Invalid token rejection should be fast, got {metrics.avg_response_time:.3f}s"
            
            print(f"\n=== JWT Validation Load Test Results ===")
            if valid_token_metrics:
                total_valid_requests = sum(m.total_requests for m in valid_token_metrics)
                print(f"Valid Token Requests: {total_valid_requests}")
                print(f"Average Response Time: {avg_valid_response_time:.3f}s")
                print(f"Average Error Rate: {avg_valid_error_rate:.2%}")
            
            print(f"Invalid Token Tests: {len(invalid_token_results)} scenarios")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_api_key_validation_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        mock_vault_client,
        load_test_config: Dict[str, Any]
    ):
        """Test API key validation under load"""
        
        performance_monitor.start_monitoring()
        
        # Pre-populate vault with test API keys
        test_api_keys = []
        for i in range(20):
            api_key = f"test-api-key-{i}-{''.join(random.choices(string.ascii_letters + string.digits, k=16))}"
            service_name = f"test-service-{i}"
            permissions = ["read", "write"] if i % 2 == 0 else ["read"]
            
            await mock_vault_client.store_api_key(service_name, api_key, permissions)
            test_api_keys.append(api_key)
        
        # Generate invalid API keys
        invalid_api_keys = [
            "invalid-api-key-123",
            "expired-api-key-456",
            "",
            "malformed-key"
        ]
        
        try:
            # Test valid API key authentication
            valid_key_metrics = []
            
            for api_key in test_api_keys[:10]:  # Test subset to avoid overwhelming
                headers = {"X-API-Key": api_key}
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/api/v1/service/status",
                    method="GET",
                    headers=headers,
                    concurrent_users=load_test_config["concurrent_users"] // 4,
                    requests_per_user=load_test_config["requests_per_user"] // 4,
                    delay_between_requests=0.1
                )
                
                valid_key_metrics.append(metrics)
            
            # Test invalid API key handling
            invalid_key_metrics = []
            
            for invalid_key in invalid_api_keys:
                headers = {"X-API-Key": invalid_key}
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/api/v1/service/status",
                    method="GET",
                    headers=headers,
                    concurrent_users=load_test_config["concurrent_users"] // 10,
                    requests_per_user=3,
                    delay_between_requests=0.1
                )
                
                invalid_key_metrics.append(metrics)
            
            # Analyze valid API key performance
            if valid_key_metrics:
                avg_valid_response_time = sum(m.avg_response_time for m in valid_key_metrics) / len(valid_key_metrics)
                avg_valid_error_rate = sum(m.error_rate for m in valid_key_metrics) / len(valid_key_metrics)
                
                assert avg_valid_error_rate <= load_test_config["max_error_rate"], \
                    f"Valid API key error rate {avg_valid_error_rate:.2%} exceeds threshold"
                
                # API key validation should be fast (cached in Vault)
                assert avg_valid_response_time <= load_test_config["max_response_time"] * 1.5, \
                    f"Valid API key response time {avg_valid_response_time:.2f}s exceeds threshold"
            
            # Invalid API keys should be rejected quickly
            for metrics in invalid_key_metrics:
                assert metrics.avg_response_time <= 0.2, \
                    f"Invalid API key rejection should be fast, got {metrics.avg_response_time:.3f}s"
            
            print(f"\n=== API Key Validation Load Test Results ===")
            if valid_key_metrics:
                total_valid_requests = sum(m.total_requests for m in valid_key_metrics)
                print(f"Valid API Key Requests: {total_valid_requests}")
                print(f"Average Response Time: {avg_valid_response_time:.3f}s")
                print(f"Average Error Rate: {avg_valid_error_rate:.2%}")
            
            print(f"Invalid API Key Tests: {len(invalid_key_metrics)} scenarios")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_session_management_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        memory_leak_detector,
        load_test_config: Dict[str, Any]
    ):
        """Test session management under load"""
        
        performance_monitor.start_monitoring()
        memory_leak_detector.set_baseline()
        
        # Session management operations
        session_operations = [
            {
                "operation": "create_session",
                "endpoint": "/auth/login",
                "method": "POST",
                "weight": 0.3
            },
            {
                "operation": "validate_session",
                "endpoint": "/auth/validate",
                "method": "POST",
                "weight": 0.4
            },
            {
                "operation": "refresh_token",
                "endpoint": "/auth/refresh",
                "method": "POST",
                "weight": 0.2
            },
            {
                "operation": "logout",
                "endpoint": "/auth/logout",
                "method": "POST",
                "weight": 0.1
            }
        ]
        
        try:
            session_results = []
            
            # Pre-create some sessions for validation/refresh/logout tests
            active_sessions = []
            for i in range(50):
                # Simulate session creation
                session_data = {
                    "session_id": f"session_{i}_{int(time.time())}",
                    "user_id": f"user_{i}",
                    "token": f"token_{i}_{int(time.time())}"
                }
                active_sessions.append(session_data)
            
            for operation in session_operations:
                num_users = max(1, int(load_test_config["concurrent_users"] * operation["weight"]))
                
                # Create operation-specific payload
                if operation["operation"] == "create_session":
                    payload = {
                        "email": "loadtest@voicehive-hotels.eu",
                        "password": "testpassword"
                    }
                elif operation["operation"] == "validate_session":
                    payload = {
                        "session_id": random.choice(active_sessions)["session_id"] if active_sessions else "test_session"
                    }
                elif operation["operation"] == "refresh_token":
                    payload = {
                        "refresh_token": random.choice(active_sessions)["token"] if active_sessions else "test_token"
                    }
                elif operation["operation"] == "logout":
                    payload = {
                        "session_id": random.choice(active_sessions)["session_id"] if active_sessions else "test_session"
                    }
                else:
                    payload = {}
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint=operation["endpoint"],
                    method=operation["method"],
                    payload=payload,
                    concurrent_users=num_users,
                    requests_per_user=load_test_config["requests_per_user"],
                    delay_between_requests=0.1
                )
                
                session_results.append((operation["operation"], metrics))
                
                # Take memory snapshot after each operation type
                memory_leak_detector.take_snapshot(f"after_{operation['operation']}")
                
                # Validate session operation performance
                assert metrics.error_rate <= load_test_config["max_error_rate"], \
                    f"Session {operation['operation']} error rate {metrics.error_rate:.2%} exceeds threshold"
            
            # Check for memory leaks in session management
            memory_report = memory_leak_detector.get_report()
            
            # Session management should not leak memory significantly
            assert not memory_report["potential_leak"], \
                f"Potential memory leak detected in session management: {memory_report}"
            
            print(f"\n=== Session Management Load Test Results ===")
            for operation, metrics in session_results:
                print(f"{operation}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.avg_response_time:.3f}s avg, "
                      f"{metrics.error_rate:.2%} error rate")
            
            print(f"Memory Report: {memory_report}")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_role_based_access_control_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test RBAC system under load"""
        
        performance_monitor.start_monitoring()
        
        # Different user roles and their permissions
        user_roles = [
            {
                "role": "admin",
                "permissions": ["read", "write", "delete", "admin"],
                "endpoints": [
                    "/api/v1/admin/users",
                    "/api/v1/admin/system",
                    "/api/v1/hotels/manage"
                ]
            },
            {
                "role": "manager",
                "permissions": ["read", "write"],
                "endpoints": [
                    "/api/v1/hotels/manage",
                    "/api/v1/reservations/manage"
                ]
            },
            {
                "role": "staff",
                "permissions": ["read"],
                "endpoints": [
                    "/api/v1/reservations/view",
                    "/api/v1/guests/view"
                ]
            },
            {
                "role": "guest",
                "permissions": ["read_own"],
                "endpoints": [
                    "/api/v1/profile",
                    "/api/v1/reservations/own"
                ]
            }
        ]
        
        try:
            rbac_results = []
            
            for role_config in user_roles:
                print(f"\nTesting RBAC for role: {role_config['role']}")
                
                # Test each endpoint for this role
                for endpoint in role_config["endpoints"]:
                    # Create user context for this role
                    headers = {
                        "Authorization": f"Bearer test-token-{role_config['role']}",
                        "X-User-Role": role_config["role"],
                        "X-User-Permissions": ",".join(role_config["permissions"])
                    }
                    
                    metrics = await load_test_runner.run_concurrent_requests(
                        endpoint=endpoint,
                        method="GET",
                        headers=headers,
                        concurrent_users=load_test_config["concurrent_users"] // len(user_roles),
                        requests_per_user=load_test_config["requests_per_user"] // len(role_config["endpoints"]),
                        delay_between_requests=0.1
                    )
                    
                    rbac_results.append((f"{role_config['role']}_{endpoint}", metrics))
                    
                    # RBAC checks should be fast
                    assert metrics.avg_response_time <= load_test_config["max_response_time"], \
                        f"RBAC check for {role_config['role']} on {endpoint} too slow: {metrics.avg_response_time:.2f}s"
            
            # Test unauthorized access attempts
            unauthorized_tests = []
            
            # Staff trying to access admin endpoints
            admin_endpoints = [ep for role in user_roles if role["role"] == "admin" for ep in role["endpoints"]]
            
            for endpoint in admin_endpoints[:2]:  # Test subset
                headers = {
                    "Authorization": "Bearer test-token-staff",
                    "X-User-Role": "staff",
                    "X-User-Permissions": "read"
                }
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint=endpoint,
                    method="GET",
                    headers=headers,
                    concurrent_users=load_test_config["concurrent_users"] // 10,
                    requests_per_user=3,
                    delay_between_requests=0.1
                )
                
                unauthorized_tests.append((f"unauthorized_{endpoint}", metrics))
                
                # Unauthorized access should be rejected quickly
                assert metrics.avg_response_time <= 0.1, \
                    f"Unauthorized access rejection should be fast for {endpoint}"
            
            print(f"\n=== RBAC Load Test Results ===")
            for test_name, metrics in rbac_results:
                print(f"{test_name}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.avg_response_time:.3f}s avg, "
                      f"{metrics.error_rate:.2%} error rate")
            
            print(f"\nUnauthorized Access Tests:")
            for test_name, metrics in unauthorized_tests:
                print(f"{test_name}: {metrics.avg_response_time:.3f}s avg response")
                
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_authentication_mixed_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        memory_leak_detector,
        load_test_config: Dict[str, Any]
    ):
        """Test mixed authentication operations under realistic load"""
        
        performance_monitor.start_monitoring()
        memory_leak_detector.set_baseline()
        
        # Realistic authentication workload distribution
        auth_operations = [
            {"operation": "jwt_validation", "weight": 0.6, "endpoint": "/api/v1/protected/status"},
            {"operation": "api_key_validation", "weight": 0.2, "endpoint": "/api/v1/service/health"},
            {"operation": "login", "weight": 0.1, "endpoint": "/auth/login"},
            {"operation": "logout", "weight": 0.05, "endpoint": "/auth/logout"},
            {"operation": "token_refresh", "weight": 0.05, "endpoint": "/auth/refresh"}
        ]
        
        try:
            # Run mixed authentication load test
            tasks = []
            
            for operation in auth_operations:
                num_users = max(1, int(load_test_config["concurrent_users"] * operation["weight"]))
                
                # Create appropriate headers/payload for each operation
                if operation["operation"] == "jwt_validation":
                    headers = {"Authorization": "Bearer valid-test-token"}
                    payload = None
                elif operation["operation"] == "api_key_validation":
                    headers = {"X-API-Key": "valid-test-api-key"}
                    payload = None
                elif operation["operation"] == "login":
                    headers = None
                    payload = {"email": "test@voicehive-hotels.eu", "password": "testpass"}
                elif operation["operation"] == "logout":
                    headers = {"Authorization": "Bearer valid-test-token"}
                    payload = {"session_id": "test-session"}
                elif operation["operation"] == "token_refresh":
                    headers = None
                    payload = {"refresh_token": "valid-refresh-token"}
                else:
                    headers = None
                    payload = None
                
                method = "POST" if payload else "GET"
                
                task = load_test_runner.run_concurrent_requests(
                    endpoint=operation["endpoint"],
                    method=method,
                    payload=payload,
                    headers=headers,
                    concurrent_users=num_users,
                    requests_per_user=load_test_config["requests_per_user"],
                    delay_between_requests=0.1
                )
                
                tasks.append((operation["operation"], task))
            
            # Execute all authentication operations concurrently
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            
            memory_leak_detector.take_snapshot("after_mixed_auth_load")
            
            # Analyze mixed load results
            total_requests = 0
            total_errors = 0
            operation_results = []
            
            for i, (operation_name, _) in enumerate(tasks):
                if isinstance(results[i], LoadTestMetrics):
                    metrics = results[i]
                    total_requests += metrics.total_requests
                    total_errors += metrics.failed_requests
                    operation_results.append((operation_name, metrics))
                    
                    # Validate each operation type
                    assert metrics.error_rate <= load_test_config["max_error_rate"], \
                        f"Mixed auth {operation_name} error rate {metrics.error_rate:.2%} exceeds threshold"
            
            overall_error_rate = total_errors / total_requests if total_requests > 0 else 0
            
            assert overall_error_rate <= load_test_config["max_error_rate"], \
                f"Overall mixed auth error rate {overall_error_rate:.2%} exceeds threshold"
            
            # Check for memory leaks
            memory_report = memory_leak_detector.get_report()
            assert not memory_report["potential_leak"], \
                f"Potential memory leak detected in mixed auth operations: {memory_report}"
            
            print(f"\n=== Mixed Authentication Load Test Results ===")
            print(f"Total Requests: {total_requests}")
            print(f"Overall Error Rate: {overall_error_rate:.2%}")
            
            for operation, metrics in operation_results:
                print(f"{operation}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.avg_response_time:.3f}s avg, "
                      f"{metrics.error_rate:.2%} error rate")
            
            print(f"Memory Report: {memory_report}")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()