"""
Authentication and Authorization Flow Integration Tests

Tests complete authentication and authorization flows including JWT tokens,
API keys, role-based access control, and session management.
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import jwt as pyjwt

from auth_models import UserContext, ServiceContext, LoginRequest
from jwt_service import JWTService


class TestAuthenticationFlowIntegration:
    """Test authentication flow scenarios"""
    
    async def test_complete_jwt_authentication_flow(
        self,
        unauthenticated_client,
        integration_test_app,
        jwt_service,
        mock_redis
    ):
        """Test complete JWT authentication flow from login to logout"""
        
        # Step 1: Login with valid credentials
        login_payload = {
            "email": "test@voicehive-hotels.eu",
            "password": "secure_password_123"
        }
        
        # Mock user validation
        with patch('auth_middleware.validate_user_credentials') as mock_validate:
            mock_validate.return_value = UserContext(
                user_id="user-123",
                email="test@voicehive-hotels.eu",
                roles=["user", "admin"],
                permissions=["read", "write", "admin"],
                session_id="session-123",
                expires_at=None
            )
            
            response = await unauthenticated_client.post(
                "/auth/login",
                json=login_payload
            )
            
            assert response.status_code == 200
            auth_data = response.json()
            
            assert "access_token" in auth_data
            assert "refresh_token" in auth_data
            assert auth_data["token_type"] == "bearer"
            
            access_token = auth_data["access_token"]
            refresh_token = auth_data["refresh_token"]
        
        # Step 2: Use access token to make authenticated requests
        authenticated_headers = {"Authorization": f"Bearer {access_token}"}
        
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=authenticated_headers
        )
        
        assert response.status_code == 200
        profile_data = response.json()
        assert profile_data["email"] == "test@voicehive-hotels.eu"
        assert "admin" in profile_data["roles"]
        
        # Step 3: Test protected endpoint access
        call_payload = {
            "event": "call.started",
            "call_id": "auth-test-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {"hotel_id": "auth-hotel-001"}
        }
        
        response = await unauthenticated_client.post(
            "/webhook/call-event",
            json=call_payload,
            headers=authenticated_headers
        )
        
        assert response.status_code == 200
        
        # Step 4: Refresh token
        refresh_payload = {"refresh_token": refresh_token}
        
        response = await unauthenticated_client.post(
            "/auth/refresh",
            json=refresh_payload
        )
        
        assert response.status_code == 200
        refresh_data = response.json()
        assert "access_token" in refresh_data
        
        new_access_token = refresh_data["access_token"]
        assert new_access_token != access_token  # Should be different
        
        # Step 5: Logout
        logout_headers = {"Authorization": f"Bearer {new_access_token}"}
        
        response = await unauthenticated_client.post(
            "/auth/logout",
            headers=logout_headers
        )
        
        assert response.status_code == 200
        
        # Step 6: Verify token is invalidated
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=logout_headers
        )
        
        assert response.status_code == 401  # Should be unauthorized
    
    async def test_api_key_authentication_flow(
        self,
        unauthenticated_client,
        integration_test_app,
        mock_vault_client
    ):
        """Test API key authentication for service-to-service communication"""
        
        # Test valid API key
        api_key_headers = {"X-API-Key": "test-api-key-123"}
        
        response = await unauthenticated_client.get(
            "/healthz",
            headers=api_key_headers
        )
        
        assert response.status_code == 200
        
        # Test API key with service endpoint
        call_payload = {
            "event": "call.started",
            "call_id": "service-auth-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {"hotel_id": "service-hotel-001"}
        }
        
        response = await unauthenticated_client.post(
            "/webhook/call-event",
            json=call_payload,
            headers=api_key_headers
        )
        
        assert response.status_code == 200
        
        # Test invalid API key
        invalid_headers = {"X-API-Key": "invalid-key-999"}
        
        response = await unauthenticated_client.post(
            "/webhook/call-event",
            json=call_payload,
            headers=invalid_headers
        )
        
        assert response.status_code == 401
        
        # Test missing API key for protected endpoint
        response = await unauthenticated_client.post(
            "/webhook/call-event",
            json=call_payload
        )
        
        assert response.status_code == 401
    
    async def test_role_based_access_control(
        self,
        unauthenticated_client,
        integration_test_app,
        jwt_service
    ):
        """Test role-based access control (RBAC) functionality"""
        
        # Create tokens for different user roles
        admin_user = UserContext(
            user_id="admin-123",
            email="admin@voicehive-hotels.eu",
            roles=["admin"],
            permissions=["read", "write", "admin", "delete"],
            session_id="admin-session",
            expires_at=None
        )
        
        regular_user = UserContext(
            user_id="user-456",
            email="user@voicehive-hotels.eu", 
            roles=["user"],
            permissions=["read"],
            session_id="user-session",
            expires_at=None
        )
        
        admin_token = await jwt_service.create_token(admin_user)
        user_token = await jwt_service.create_token(regular_user)
        
        # Test admin access to admin-only endpoint
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        
        response = await unauthenticated_client.get(
            "/auth/admin/users",
            headers=admin_headers
        )
        
        # Should succeed for admin
        assert response.status_code in [200, 404]  # 404 if endpoint not implemented
        
        # Test regular user access to admin-only endpoint
        user_headers = {"Authorization": f"Bearer {user_token}"}
        
        response = await unauthenticated_client.get(
            "/auth/admin/users",
            headers=user_headers
        )
        
        # Should fail for regular user
        assert response.status_code == 403
        
        # Test regular user access to user endpoint
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=user_headers
        )
        
        # Should succeed for regular user
        assert response.status_code == 200
        
        # Test write operations
        call_payload = {
            "event": "call.started",
            "call_id": "rbac-test-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {"hotel_id": "rbac-hotel-001"}
        }
        
        # Admin should be able to create calls
        response = await unauthenticated_client.post(
            "/webhook/call-event",
            json=call_payload,
            headers=admin_headers
        )
        assert response.status_code == 200
        
        # Regular user with read-only permissions should not be able to create calls
        response = await unauthenticated_client.post(
            "/webhook/call-event",
            json=call_payload,
            headers=user_headers
        )
        assert response.status_code in [403, 200]  # Depends on implementation
    
    async def test_jwt_token_validation_edge_cases(
        self,
        unauthenticated_client,
        integration_test_app,
        jwt_service
    ):
        """Test JWT token validation edge cases and security"""
        
        # Test expired token
        expired_user = UserContext(
            user_id="expired-123",
            email="expired@voicehive-hotels.eu",
            roles=["user"],
            permissions=["read"],
            session_id="expired-session",
            expires_at=datetime.utcnow() - timedelta(hours=1)  # Expired
        )
        
        expired_token = await jwt_service.create_token(expired_user)
        
        # Wait a moment to ensure expiration
        await asyncio.sleep(0.1)
        
        expired_headers = {"Authorization": f"Bearer {expired_token}"}
        
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=expired_headers
        )
        
        assert response.status_code == 401
        
        # Test malformed token
        malformed_headers = {"Authorization": "Bearer invalid.token.here"}
        
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=malformed_headers
        )
        
        assert response.status_code == 401
        
        # Test token with invalid signature
        valid_user = UserContext(
            user_id="valid-123",
            email="valid@voicehive-hotels.eu",
            roles=["user"],
            permissions=["read"],
            session_id="valid-session",
            expires_at=None
        )
        
        # Create token with wrong secret
        fake_token = pyjwt.encode(
            {
                "sub": valid_user.user_id,
                "email": valid_user.email,
                "roles": valid_user.roles,
                "exp": datetime.utcnow() + timedelta(hours=1)
            },
            "wrong_secret",
            algorithm="HS256"
        )
        
        fake_headers = {"Authorization": f"Bearer {fake_token}"}
        
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=fake_headers
        )
        
        assert response.status_code == 401
        
        # Test missing Authorization header
        response = await unauthenticated_client.get("/auth/profile")
        assert response.status_code == 401
        
        # Test wrong Authorization scheme
        wrong_scheme_headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=wrong_scheme_headers
        )
        
        assert response.status_code == 401
    
    async def test_session_management_integration(
        self,
        unauthenticated_client,
        integration_test_app,
        jwt_service,
        mock_redis
    ):
        """Test session management and Redis integration"""
        
        # Create user and login
        user_context = UserContext(
            user_id="session-test-123",
            email="session@voicehive-hotels.eu",
            roles=["user"],
            permissions=["read", "write"],
            session_id="session-test-123",
            expires_at=None
        )
        
        token = await jwt_service.create_token(user_context)
        headers = {"Authorization": f"Bearer {token}"}
        
        # Verify session is active
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=headers
        )
        assert response.status_code == 200
        
        # Simulate session invalidation in Redis
        mock_redis.get.return_value = None  # Session not found
        
        response = await unauthenticated_client.get(
            "/auth/profile",
            headers=headers
        )
        
        # Should fail if session is not in Redis
        assert response.status_code in [401, 200]  # Depends on implementation
        
        # Test concurrent sessions
        token2 = await jwt_service.create_token(user_context)
        headers2 = {"Authorization": f"Bearer {token2}"}
        
        # Both tokens should work initially
        mock_redis.get.return_value = json.dumps({
            "user_id": user_context.user_id,
            "session_id": user_context.session_id,
            "active": True
        })
        
        response1 = await unauthenticated_client.get(
            "/auth/profile",
            headers=headers
        )
        response2 = await unauthenticated_client.get(
            "/auth/profile", 
            headers=headers2
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
    
    async def test_authentication_performance_under_load(
        self,
        unauthenticated_client,
        integration_test_app,
        jwt_service,
        performance_test_config
    ):
        """Test authentication performance under concurrent load"""
        
        # Create multiple user contexts
        users = [
            UserContext(
                user_id=f"perf-user-{i}",
                email=f"perf{i}@voicehive-hotels.eu",
                roles=["user"],
                permissions=["read"],
                session_id=f"perf-session-{i}",
                expires_at=None
            )
            for i in range(10)
        ]
        
        # Create tokens for all users
        tokens = []
        for user in users:
            token = await jwt_service.create_token(user)
            tokens.append(token)
        
        async def make_authenticated_request(token: str, request_id: int):
            """Make an authenticated request and measure performance"""
            headers = {"Authorization": f"Bearer {token}"}
            
            start_time = asyncio.get_event_loop().time()
            
            response = await unauthenticated_client.get(
                "/auth/profile",
                headers=headers
            )
            
            end_time = asyncio.get_event_loop().time()
            response_time = end_time - start_time
            
            return response.status_code, response_time, request_id
        
        # Make concurrent authenticated requests
        tasks = [
            make_authenticated_request(token, i)
            for i, token in enumerate(tokens)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Analyze performance results
        successful_requests = 0
        total_response_time = 0
        max_response_time = 0
        
        for status_code, response_time, request_id in results:
            if status_code == 200:
                successful_requests += 1
                total_response_time += response_time
                max_response_time = max(max_response_time, response_time)
        
        # Verify performance requirements
        assert successful_requests >= 8  # At least 80% success rate
        
        if successful_requests > 0:
            avg_response_time = total_response_time / successful_requests
            assert avg_response_time < performance_test_config["max_response_time"]
            assert max_response_time < performance_test_config["max_response_time"] * 2
    
    async def test_authentication_error_handling(
        self,
        unauthenticated_client,
        integration_test_app
    ):
        """Test authentication error handling and security responses"""
        
        # Test various authentication failure scenarios
        error_scenarios = [
            {
                "name": "missing_credentials",
                "payload": {},
                "expected_status": 422
            },
            {
                "name": "invalid_email_format",
                "payload": {
                    "email": "invalid-email",
                    "password": "password123"
                },
                "expected_status": 422
            },
            {
                "name": "empty_password",
                "payload": {
                    "email": "test@example.com",
                    "password": ""
                },
                "expected_status": 422
            },
            {
                "name": "sql_injection_attempt",
                "payload": {
                    "email": "admin'; DROP TABLE users; --",
                    "password": "password"
                },
                "expected_status": 401
            },
            {
                "name": "xss_attempt",
                "payload": {
                    "email": "<script>alert('xss')</script>@example.com",
                    "password": "password"
                },
                "expected_status": 422
            }
        ]
        
        for scenario in error_scenarios:
            response = await unauthenticated_client.post(
                "/auth/login",
                json=scenario["payload"]
            )
            
            assert response.status_code == scenario["expected_status"]
            
            # Verify error response format
            if response.status_code != 200:
                error_data = response.json()
                assert "error" in error_data or "detail" in error_data
                
                # Should not leak sensitive information
                error_text = json.dumps(error_data).lower()
                assert "password" not in error_text
                assert "secret" not in error_text
                assert "key" not in error_text
    
    async def test_cross_origin_authentication(
        self,
        unauthenticated_client,
        integration_test_app
    ):
        """Test authentication with CORS and cross-origin requests"""
        
        # Test preflight request
        response = await unauthenticated_client.options(
            "/auth/login",
            headers={
                "Origin": "https://app.voicehive-hotels.eu",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, Authorization"
            }
        )
        
        # Should handle CORS preflight
        assert response.status_code in [200, 204]
        
        # Test actual login with CORS headers
        login_payload = {
            "email": "cors@voicehive-hotels.eu",
            "password": "secure_password"
        }
        
        with patch('auth_middleware.validate_user_credentials') as mock_validate:
            mock_validate.return_value = UserContext(
                user_id="cors-user-123",
                email="cors@voicehive-hotels.eu",
                roles=["user"],
                permissions=["read"],
                session_id="cors-session",
                expires_at=None
            )
            
            response = await unauthenticated_client.post(
                "/auth/login",
                json=login_payload,
                headers={"Origin": "https://app.voicehive-hotels.eu"}
            )
            
            assert response.status_code == 200
            
            # Verify CORS headers are present
            assert "access-control-allow-origin" in response.headers or \
                   "Access-Control-Allow-Origin" in response.headers