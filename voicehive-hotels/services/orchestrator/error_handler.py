"""
Centralized error handling system with structured logging and alerting
"""

import traceback
from typing import Dict, Any, Optional, Type
from datetime import datetime, timezone
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from error_models import (
    VoiceHiveError, ErrorResponse, ErrorDetail, ErrorSeverity, ErrorCategory,
    ERROR_CODE_TO_HTTP_STATUS, SEVERITY_ALERT_ROUTING,
    AuthenticationError, AuthorizationError, ValidationError, RateLimitError,
    CircuitBreakerError, ExternalServiceError, DatabaseError, PMSConnectorError, SystemError
)
from correlation_middleware import get_correlation_id, CorrelationIDLogger
from alerting_system import AlertingSystem

logger = CorrelationIDLogger("error_handler")


class ErrorHandler:
    """
    Centralized error handling with structured responses and alerting
    """
    
    def __init__(self, alerting_system: Optional[AlertingSystem] = None):
        self.alerting_system = alerting_system
        
        # Map exception types to error handlers
        self.exception_handlers: Dict[Type[Exception], callable] = {
            VoiceHiveError: self._handle_voicehive_error,
            HTTPException: self._handle_http_exception,
            StarletteHTTPException: self._handle_starlette_http_exception,
            ValidationError: self._handle_validation_error,
            ValueError: self._handle_value_error,
            KeyError: self._handle_key_error,
            AttributeError: self._handle_attribute_error,
            ConnectionError: self._handle_connection_error,
            TimeoutError: self._handle_timeout_error,
            PermissionError: self._handle_permission_error,
            Exception: self._handle_generic_exception
        }
    
    async def handle_error(self, request: Request, error: Exception) -> JSONResponse:
        """
        Handle any error and return standardized response
        
        Args:
            request: FastAPI request object
            error: Exception that occurred
        
        Returns:
            JSONResponse with standardized error format
        """
        correlation_id = get_correlation_id() or getattr(request.state, 'correlation_id', None)
        
        # Find appropriate handler
        handler = self._get_error_handler(type(error))
        
        # Handle the error
        error_detail = await handler(error, request, correlation_id)
        
        # Create response
        error_response = ErrorResponse(
            error=error_detail,
            request_id=correlation_id,
            path=str(request.url.path),
            method=request.method
        )
        
        # Log the error
        await self._log_error(error_detail, request, error)
        
        # Send alerts if needed
        await self._send_alerts(error_detail, request, error)
        
        # Determine HTTP status code
        status_code = ERROR_CODE_TO_HTTP_STATUS.get(error_detail.code, 500)
        
        # For HTTP exceptions, use the original status code if available
        if hasattr(error, 'status_code'):
            status_code = error.status_code
        
        # Create response headers
        headers = {}
        if error_detail.retry_after:
            headers["Retry-After"] = str(error_detail.retry_after)
        
        # Add correlation ID header
        if error_detail.correlation_id:
            headers["X-Correlation-ID"] = error_detail.correlation_id
        
        return JSONResponse(
            status_code=status_code,
            content=error_response.model_dump(),
            headers=headers
        )
    
    def _get_error_handler(self, exception_type: Type[Exception]) -> callable:
        """Get the appropriate error handler for an exception type"""
        # Check for exact match first
        if exception_type in self.exception_handlers:
            return self.exception_handlers[exception_type]
        
        # Check for inheritance match
        for exc_type, handler in self.exception_handlers.items():
            if issubclass(exception_type, exc_type):
                return handler
        
        # Default to generic handler
        return self.exception_handlers[Exception]
    
    async def _handle_voicehive_error(self, error: VoiceHiveError, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle VoiceHive custom errors"""
        error_detail = error.to_error_detail()
        error_detail.correlation_id = correlation_id or error_detail.correlation_id
        return error_detail
    
    async def _handle_http_exception(self, error: HTTPException, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle FastAPI HTTP exceptions"""
        # Map HTTP status codes to our error codes
        status_code_mapping = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED", 
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            422: "UNPROCESSABLE_ENTITY",
            429: "TOO_MANY_REQUESTS",
            500: "INTERNAL_SERVER_ERROR",
            502: "BAD_GATEWAY",
            503: "SERVICE_UNAVAILABLE",
            504: "GATEWAY_TIMEOUT"
        }
        
        error_code = status_code_mapping.get(error.status_code, f"HTTP_{error.status_code}")
        
        return ErrorDetail(
            code=error_code,
            message=error.detail,
            correlation_id=correlation_id,
            category=ErrorCategory.VALIDATION if error.status_code < 500 else ErrorCategory.SYSTEM,
            severity=ErrorSeverity.LOW if error.status_code < 500 else ErrorSeverity.HIGH,
            details={"status_code": error.status_code}
        )
    
    async def _handle_starlette_http_exception(self, error: StarletteHTTPException, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle Starlette HTTP exceptions"""
        return ErrorDetail(
            code=f"HTTP_{error.status_code}",
            message=error.detail,
            correlation_id=correlation_id,
            category=ErrorCategory.VALIDATION if error.status_code < 500 else ErrorCategory.SYSTEM,
            severity=ErrorSeverity.LOW if error.status_code < 500 else ErrorSeverity.HIGH,
            details={"status_code": error.status_code}
        )
    
    async def _handle_validation_error(self, error: ValidationError, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle validation errors"""
        # If it's our custom ValidationError, preserve the details
        if hasattr(error, 'details') and error.details:
            details = error.details.copy()
        else:
            details = {"validation_error": str(error)}
            
        return ErrorDetail(
            code="VALIDATION_ERROR",
            message=str(error),
            correlation_id=correlation_id,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            details=details
        )
    
    async def _handle_value_error(self, error: ValueError, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle value errors"""
        return ErrorDetail(
            code="INVALID_VALUE",
            message=f"Invalid value provided: {str(error)}",
            correlation_id=correlation_id,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            details={"original_error": str(error)}
        )
    
    async def _handle_key_error(self, error: KeyError, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle key errors"""
        return ErrorDetail(
            code="MISSING_FIELD",
            message=f"Required field missing: {str(error)}",
            correlation_id=correlation_id,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            details={"missing_key": str(error)}
        )
    
    async def _handle_attribute_error(self, error: AttributeError, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle attribute errors"""
        return ErrorDetail(
            code="ATTRIBUTE_ERROR",
            message=f"Attribute error: {str(error)}",
            correlation_id=correlation_id,
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.MEDIUM,
            details={"attribute_error": str(error)}
        )
    
    async def _handle_connection_error(self, error: ConnectionError, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle connection errors"""
        return ErrorDetail(
            code="CONNECTION_ERROR",
            message="Service temporarily unavailable due to connection issues",
            correlation_id=correlation_id,
            category=ErrorCategory.EXTERNAL_SERVICE,
            severity=ErrorSeverity.HIGH,
            details={"connection_error": str(error)},
            retry_after=30
        )
    
    async def _handle_timeout_error(self, error: TimeoutError, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle timeout errors"""
        return ErrorDetail(
            code="TIMEOUT_ERROR",
            message="Request timed out",
            correlation_id=correlation_id,
            category=ErrorCategory.EXTERNAL_SERVICE,
            severity=ErrorSeverity.HIGH,
            details={"timeout_error": str(error)},
            retry_after=60
        )
    
    async def _handle_permission_error(self, error: PermissionError, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle permission errors"""
        return ErrorDetail(
            code="PERMISSION_DENIED",
            message="Insufficient permissions to perform this operation",
            correlation_id=correlation_id,
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.HIGH,
            details={"permission_error": str(error)}
        )
    
    async def _handle_generic_exception(self, error: Exception, request: Request, correlation_id: str) -> ErrorDetail:
        """Handle generic exceptions"""
        return ErrorDetail(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
            correlation_id=correlation_id,
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.CRITICAL,
            details={
                "error_type": type(error).__name__,
                "error_message": str(error)
            }
        )
    
    async def _log_error(self, error_detail: ErrorDetail, request: Request, original_error: Exception):
        """Log error with appropriate level and context"""
        
        # Determine log level based on severity
        log_level_map = {
            ErrorSeverity.LOW: "info",
            ErrorSeverity.MEDIUM: "warning",
            ErrorSeverity.HIGH: "error",
            ErrorSeverity.CRITICAL: "critical"
        }
        
        log_level = log_level_map.get(error_detail.severity, "error")
        
        # Prepare log context
        log_context = {
            "error_code": error_detail.code,
            "error_category": error_detail.category,
            "error_severity": error_detail.severity,
            "correlation_id": error_detail.correlation_id,
            "path": str(request.url.path),
            "method": request.method,
            "user_agent": request.headers.get("user-agent"),
            "client_ip": request.client.host if request.client else None,
            "error_details": error_detail.details
        }
        
        # Add stack trace for critical errors
        if error_detail.severity == ErrorSeverity.CRITICAL:
            log_context["stack_trace"] = traceback.format_exception(
                type(original_error), original_error, original_error.__traceback__
            )
        
        # Log the error
        getattr(logger, log_level)(
            "request_error_occurred",
            **log_context
        )
    
    async def _send_alerts(self, error_detail: ErrorDetail, request: Request, original_error: Exception):
        """Send alerts based on error severity"""
        if not self.alerting_system:
            return
        
        # Get alert channels for this severity
        alert_channels = SEVERITY_ALERT_ROUTING.get(error_detail.severity, [])
        
        if not alert_channels:
            return
        
        # Prepare alert context
        alert_context = {
            "error_code": error_detail.code,
            "error_message": error_detail.message,
            "error_category": error_detail.category,
            "error_severity": error_detail.severity,
            "correlation_id": error_detail.correlation_id,
            "service": "orchestrator",
            "path": str(request.url.path),
            "method": request.method,
            "timestamp": error_detail.timestamp,
            "details": error_detail.details
        }
        
        # Send alerts
        try:
            await self.alerting_system.send_alert(
                title=f"Error in VoiceHive Orchestrator: {error_detail.code}",
                message=error_detail.message,
                severity=error_detail.severity,
                context=alert_context,
                channels=alert_channels
            )
        except Exception as e:
            logger.error(
                "failed_to_send_alert",
                error=str(e),
                original_error_code=error_detail.code,
                correlation_id=error_detail.correlation_id
            )


class GracefulDegradationHandler:
    """
    Handler for graceful degradation when external services fail
    """
    
    def __init__(self):
        self.fallback_responses = {
            "pms_connector": self._pms_connector_fallback,
            "tts_service": self._tts_service_fallback,
            "asr_service": self._asr_service_fallback,
            "ai_service": self._ai_service_fallback
        }
    
    async def handle_service_failure(self, service_name: str, operation: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle service failure with graceful degradation
        
        Args:
            service_name: Name of the failed service
            operation: Operation that failed
            context: Context information for fallback
        
        Returns:
            Fallback response
        """
        logger.warning(
            "service_failure_graceful_degradation",
            service=service_name,
            operation=operation,
            context=context
        )
        
        fallback_handler = self.fallback_responses.get(service_name)
        if fallback_handler:
            return await fallback_handler(operation, context)
        
        # Generic fallback
        return {
            "status": "degraded",
            "message": f"Service {service_name} is temporarily unavailable",
            "fallback_active": True,
            "retry_after": 60
        }
    
    async def _pms_connector_fallback(self, operation: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback for PMS connector failures"""
        if operation == "get_guest_info":
            return {
                "guest_name": "Valued Guest",
                "room_number": "Unknown",
                "preferences": {},
                "fallback_active": True,
                "message": "Guest information temporarily unavailable"
            }
        elif operation == "create_service_request":
            return {
                "request_id": f"fallback_{datetime.now(timezone.utc).isoformat()}",
                "status": "queued",
                "fallback_active": True,
                "message": "Service request queued for manual processing"
            }
        
        return {"fallback_active": True, "message": "PMS service temporarily unavailable"}
    
    async def _tts_service_fallback(self, operation: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback for TTS service failures"""
        return {
            "audio_url": None,
            "text": context.get("text", ""),
            "fallback_active": True,
            "message": "Text-to-speech service temporarily unavailable"
        }
    
    async def _asr_service_fallback(self, operation: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback for ASR service failures"""
        return {
            "transcript": "",
            "confidence": 0.0,
            "fallback_active": True,
            "message": "Speech recognition temporarily unavailable"
        }
    
    async def _ai_service_fallback(self, operation: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback for AI service failures"""
        return {
            "response": "I apologize, but I'm experiencing technical difficulties. Please try again later or contact the front desk for assistance.",
            "intent": "technical_difficulty",
            "fallback_active": True,
            "message": "AI service temporarily unavailable"
        }


# Global error handler instance
error_handler = ErrorHandler()
graceful_degradation = GracefulDegradationHandler()