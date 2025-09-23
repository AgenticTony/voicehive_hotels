"""
Standardized error models and exceptions for VoiceHive Hotels Orchestrator
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
import uuid


class ErrorSeverity(str, Enum):
    """Error severity levels for alerting and routing"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(str, Enum):
    """Error categories for classification"""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    RATE_LIMIT = "rate_limit"
    CIRCUIT_BREAKER = "circuit_breaker"
    EXTERNAL_SERVICE = "external_service"
    DATABASE = "database"
    NETWORK = "network"
    BUSINESS_LOGIC = "business_logic"
    SYSTEM = "system"
    PMS_CONNECTOR = "pms_connector"


class ErrorDetail(BaseModel):
    """Detailed error information"""
    code: str = Field(..., description="Error code for programmatic handling")
    message: str = Field(..., description="Human-readable error message")
    correlation_id: str = Field(..., description="Unique correlation ID for tracing")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    category: ErrorCategory = Field(..., description="Error category")
    severity: ErrorSeverity = Field(..., description="Error severity level")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error context")
    retry_after: Optional[int] = Field(None, description="Retry after seconds for recoverable errors")
    service: str = Field("orchestrator", description="Service that generated the error")


class ErrorResponse(BaseModel):
    """Standardized error response format"""
    error: ErrorDetail
    request_id: Optional[str] = Field(None, description="Request ID if available")
    path: Optional[str] = Field(None, description="Request path")
    method: Optional[str] = Field(None, description="HTTP method")


# Custom Exception Classes
class VoiceHiveError(Exception):
    """Base exception for all VoiceHive errors"""
    
    def __init__(
        self,
        message: str,
        code: str,
        category: ErrorCategory,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        details: Optional[Dict[str, Any]] = None,
        retry_after: Optional[int] = None,
        correlation_id: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.category = category
        self.severity = severity
        self.details = details or {}
        self.retry_after = retry_after
        self.correlation_id = correlation_id or str(uuid.uuid4())
    
    def to_error_detail(self) -> ErrorDetail:
        """Convert exception to ErrorDetail model"""
        return ErrorDetail(
            code=self.code,
            message=self.message,
            correlation_id=self.correlation_id,
            category=self.category,
            severity=self.severity,
            details=self.details,
            retry_after=self.retry_after
        )


class AuthenticationError(VoiceHiveError):
    """Authentication related errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="AUTHENTICATION_FAILED",
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.HIGH,
            details=details
        )


class AuthorizationError(VoiceHiveError):
    """Authorization related errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="AUTHORIZATION_FAILED",
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.HIGH,
            details=details
        )


class ValidationError(VoiceHiveError):
    """Input validation errors"""
    
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        error_details = details or {}
        if field:
            error_details["field"] = field
        
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.LOW,
            details=error_details
        )


class RateLimitError(VoiceHiveError):
    """Rate limiting errors"""
    
    def __init__(self, message: str, retry_after: int, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.MEDIUM,
            details=details,
            retry_after=retry_after
        )


class CircuitBreakerError(VoiceHiveError):
    """Circuit breaker errors"""
    
    def __init__(self, service: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Circuit breaker open for service: {service}",
            code="CIRCUIT_BREAKER_OPEN",
            category=ErrorCategory.CIRCUIT_BREAKER,
            severity=ErrorSeverity.HIGH,
            details=details
        )


class ExternalServiceError(VoiceHiveError):
    """External service errors"""
    
    def __init__(self, service: str, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        error_details = details or {}
        if status_code:
            error_details["status_code"] = status_code
        error_details["service"] = service
        
        super().__init__(
            message=f"External service error ({service}): {message}",
            code="EXTERNAL_SERVICE_ERROR",
            category=ErrorCategory.EXTERNAL_SERVICE,
            severity=ErrorSeverity.HIGH,
            details=error_details
        )


class DatabaseError(VoiceHiveError):
    """Database related errors"""
    
    def __init__(self, message: str, operation: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        error_details = details or {}
        if operation:
            error_details["operation"] = operation
        
        super().__init__(
            message=message,
            code="DATABASE_ERROR",
            category=ErrorCategory.DATABASE,
            severity=ErrorSeverity.CRITICAL,
            details=error_details
        )


class PMSConnectorError(VoiceHiveError):
    """PMS connector specific errors"""
    
    def __init__(self, connector: str, message: str, details: Optional[Dict[str, Any]] = None):
        error_details = details or {}
        error_details["connector"] = connector
        
        super().__init__(
            message=f"PMS connector error ({connector}): {message}",
            code="PMS_CONNECTOR_ERROR",
            category=ErrorCategory.PMS_CONNECTOR,
            severity=ErrorSeverity.HIGH,
            details=error_details
        )


class SystemError(VoiceHiveError):
    """System level errors"""
    
    def __init__(self, message: str, component: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        error_details = details or {}
        if component:
            error_details["component"] = component
        
        super().__init__(
            message=message,
            code="SYSTEM_ERROR",
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.CRITICAL,
            details=error_details
        )


# Error code mappings for HTTP status codes
ERROR_CODE_TO_HTTP_STATUS = {
    "AUTHENTICATION_FAILED": 401,
    "AUTHORIZATION_FAILED": 403,
    "VALIDATION_ERROR": 400,
    "RATE_LIMIT_EXCEEDED": 429,
    "CIRCUIT_BREAKER_OPEN": 503,
    "EXTERNAL_SERVICE_ERROR": 502,
    "DATABASE_ERROR": 500,
    "PMS_CONNECTOR_ERROR": 502,
    "SYSTEM_ERROR": 500,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "INTERNAL_ERROR": 500,
    "BAD_REQUEST": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "METHOD_NOT_ALLOWED": 405,
    "UNPROCESSABLE_ENTITY": 422,
    "TOO_MANY_REQUESTS": 429,
    "INTERNAL_SERVER_ERROR": 500,
    "BAD_GATEWAY": 502,
    "SERVICE_UNAVAILABLE": 503,
    "GATEWAY_TIMEOUT": 504,
    "INVALID_VALUE": 400,
    "MISSING_FIELD": 400,
    "ATTRIBUTE_ERROR": 500,
    "CONNECTION_ERROR": 503,
    "TIMEOUT_ERROR": 504,
    "PERMISSION_DENIED": 403
}


# Severity to alert routing mapping
SEVERITY_ALERT_ROUTING = {
    ErrorSeverity.LOW: ["logs"],
    ErrorSeverity.MEDIUM: ["logs", "metrics"],
    ErrorSeverity.HIGH: ["logs", "metrics", "slack"],
    ErrorSeverity.CRITICAL: ["logs", "metrics", "slack", "pagerduty"]
}