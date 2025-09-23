"""
Tests for comprehensive error handling system
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from fastapi import Request, HTTPException
from fastapi.testclient import TestClient

from error_models import (
    VoiceHiveError, ErrorSeverity, ErrorCategory, AuthenticationError,
    ValidationError, ExternalServiceError
)
from error_handler import ErrorHandler, GracefulDegradationHandler
from correlation_middleware import CorrelationIDMiddleware, set_correlation_id
from alerting_system import AlertingSystem, AlertingConfig, AlertRateLimiter
from retry_utils import RetryConfig, RetryableOperation, with_retry


class TestErrorModels:
    """Test error models and exceptions"""
    
    def test_voicehive_error_creation(self):
        """Test VoiceHive error creation"""
        error = VoiceHiveError(
            message="Test error",
            code="TEST_ERROR",
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.HIGH,
            details={"test": "data"}
        )
        
        assert error.message == "Test error"
        assert error.code == "TEST_ERROR"
        assert error.category == ErrorCategory.SYSTEM
        assert error.severity == ErrorSeverity.HIGH
        assert error.details == {"test": "data"}
        assert error.correlation_id is not None
    
    def test_error_detail_conversion(self):
        """Test conversion to ErrorDetail"""
        error = AuthenticationError("Invalid token")
        detail = error.to_error_detail()
        
        assert detail.code == "AUTHENTICATION_FAILED"
        assert detail.message == "Invalid token"
        assert detail.category == ErrorCategory.AUTHENTICATION
        assert detail.severity == ErrorSeverity.HIGH
    
    def test_validation_error_with_field(self):
        """Test validation error with field information"""
        error = ValidationError("Invalid email format", field="email")
        detail = error.to_error_detail()
        
        assert detail.code == "VALIDATION_ERROR"
        assert detail.details["field"] == "email"


class TestRetryUtils:
    """Test retry utilities"""
    
    @pytest.mark.asyncio
    async def test_retry_config(self):
        """Test retry configuration"""
        config = RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            retryable_exceptions=(ConnectionError,)
        )
        
        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert ConnectionError in config.retryable_exceptions
    
    @pytest.mark.asyncio
    async def test_retryable_operation_success(self):
        """Test successful operation with retry context"""
        async def successful_operation():
            return "success"
        
        async with RetryableOperation("test_op", "test_service") as op:
            result = await op.execute(successful_operation)
            assert result == "success"
    
    @pytest.mark.asyncio
    async def test_retryable_operation_failure(self):
        """Test operation that fails all retries"""
        call_count = 0
        
        async def failing_operation():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Connection failed")
        
        config = RetryConfig(max_attempts=2, base_delay=0.1)
        
        with pytest.raises(ExternalServiceError):
            async with RetryableOperation("test_op", "test_service", config) as op:
                await op.execute(failing_operation)
        
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_retry_decorator(self):
        """Test retry decorator"""
        call_count = 0
        
        @with_retry("test_service", custom_config=RetryConfig(max_attempts=2, base_delay=0.1))
        async def flaky_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Temporary failure")
            return "success"
        
        result = await flaky_function()
        assert result == "success"
        assert call_count == 2


class TestCorrelationMiddleware:
    """Test correlation ID middleware"""
    
    def test_correlation_id_generation(self):
        """Test correlation ID generation"""
        from correlation_middleware import generate_correlation_id
        
        id1 = generate_correlation_id()
        id2 = generate_correlation_id()
        
        assert id1 != id2
        assert len(id1) > 0
        assert len(id2) > 0
    
    def test_correlation_context(self):
        """Test correlation context manager"""
        from correlation_middleware import CorrelationContext, get_correlation_id
        
        test_id = "test-correlation-id"
        
        with CorrelationContext(test_id):
            assert get_correlation_id() == test_id
        
        # Should be cleared after context
        assert get_correlation_id() is None


class TestErrorHandler:
    """Test error handler"""
    
    @pytest.fixture
    def mock_request(self):
        """Create mock request"""
        request = Mock(spec=Request)
        request.url.path = "/test"
        request.method = "GET"
        request.headers = {"user-agent": "test-agent"}
        request.client.host = "127.0.0.1"
        request.state.correlation_id = "test-correlation-id"
        return request
    
    @pytest.mark.asyncio
    async def test_handle_voicehive_error(self, mock_request):
        """Test handling of VoiceHive custom errors"""
        handler = ErrorHandler()
        error = AuthenticationError("Invalid credentials")
        
        response = await handler.handle_error(mock_request, error)
        
        assert response.status_code == 401
        response_data = response.body.decode()
        assert "AUTHENTICATION_FAILED" in response_data
        assert "Invalid credentials" in response_data
    
    @pytest.mark.asyncio
    async def test_handle_http_exception(self, mock_request):
        """Test handling of HTTP exceptions"""
        handler = ErrorHandler()
        error = HTTPException(status_code=404, detail="Not found")
        
        response = await handler.handle_error(mock_request, error)
        
        assert response.status_code == 404
        response_data = response.body.decode()
        assert "Not found" in response_data
    
    @pytest.mark.asyncio
    async def test_handle_generic_exception(self, mock_request):
        """Test handling of generic exceptions"""
        handler = ErrorHandler()
        error = ValueError("Invalid value")
        
        response = await handler.handle_error(mock_request, error)
        
        assert response.status_code == 400
        response_data = response.body.decode()
        assert "INVALID_VALUE" in response_data


class TestGracefulDegradation:
    """Test graceful degradation handler"""
    
    @pytest.mark.asyncio
    async def test_pms_connector_fallback(self):
        """Test PMS connector fallback"""
        handler = GracefulDegradationHandler()
        
        result = await handler.handle_service_failure(
            "pms_connector",
            "get_guest_info",
            {"hotel_id": "test"}
        )
        
        assert result["fallback_active"] is True
        assert "guest_name" in result
        assert result["guest_name"] == "Valued Guest"
    
    @pytest.mark.asyncio
    async def test_tts_service_fallback(self):
        """Test TTS service fallback"""
        handler = GracefulDegradationHandler()
        
        result = await handler.handle_service_failure(
            "tts_service",
            "synthesize",
            {"text": "Hello world"}
        )
        
        assert result["fallback_active"] is True
        assert result["text"] == "Hello world"
        assert result["audio_url"] is None


class TestAlertingSystem:
    """Test alerting system"""
    
    def test_alert_rate_limiter(self):
        """Test alert rate limiting"""
        limiter = AlertRateLimiter(window_seconds=60, max_alerts=2)
        
        # First two alerts should be allowed
        assert limiter.should_send_alert("test_alert") is True
        assert limiter.should_send_alert("test_alert") is True
        
        # Third alert should be rate limited
        assert limiter.should_send_alert("test_alert") is False
    
    @pytest.mark.asyncio
    async def test_alerting_system_initialization(self):
        """Test alerting system initialization"""
        config = AlertingConfig(
            slack_webhook_url="https://hooks.slack.com/test",
            rate_limit_window=300,
            max_alerts_per_window=10
        )
        
        system = AlertingSystem(config)
        
        assert system.config.slack_webhook_url == "https://hooks.slack.com/test"
        assert system.rate_limiter.window_seconds == 300
        assert system.rate_limiter.max_alerts == 10
    
    @pytest.mark.asyncio
    async def test_send_alert_rate_limited(self):
        """Test alert sending with rate limiting"""
        config = AlertingConfig(rate_limit_window=60, max_alerts_per_window=1)
        system = AlertingSystem(config)
        
        context = {
            "error_code": "TEST_ERROR",
            "service": "test",
            "correlation_id": "test-id"
        }
        
        # First alert should succeed
        result1 = await system.send_alert(
            "Test Alert",
            "Test message",
            ErrorSeverity.HIGH,
            context,
            ["logs"]
        )
        assert result1 is True
        
        # Second alert should be rate limited
        result2 = await system.send_alert(
            "Test Alert",
            "Test message",
            ErrorSeverity.HIGH,
            context,
            ["logs"]
        )
        assert result2 is False


class TestIntegration:
    """Integration tests for error handling system"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_error_handling(self):
        """Test end-to-end error handling flow"""
        # Set correlation ID
        set_correlation_id("integration-test-id")
        
        # Create mock request
        request = Mock(spec=Request)
        request.url.path = "/test"
        request.method = "POST"
        request.headers = {"user-agent": "test-client"}
        request.client.host = "127.0.0.1"
        request.state.correlation_id = "integration-test-id"
        
        # Create error handler
        handler = ErrorHandler()
        
        # Test with authentication error
        auth_error = AuthenticationError(
            "Token expired",
            details={"token_type": "JWT", "expiry": "2023-01-01"}
        )
        
        response = await handler.handle_error(request, auth_error)
        
        # Verify response
        assert response.status_code == 401
        
        # Parse response body
        import json
        response_data = json.loads(response.body.decode())
        
        assert response_data["error"]["code"] == "AUTHENTICATION_FAILED"
        assert response_data["error"]["message"] == "Token expired"
        assert response_data["error"]["correlation_id"] == "integration-test-id"
        assert response_data["error"]["category"] == "authentication"
        assert response_data["error"]["severity"] == "high"
        assert response_data["request_id"] == "integration-test-id"
        assert response_data["path"] == "/test"
        assert response_data["method"] == "POST"


if __name__ == "__main__":
    pytest.main([__file__])