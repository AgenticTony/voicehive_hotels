"""
Audit Logging System for VoiceHive Hotels
Provides comprehensive audit logging for all sensitive operations with GDPR compliance
"""

import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from dataclasses import dataclass, asdict
from contextlib import contextmanager
from fastapi import Request
from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.audit")


class AuditEventType(str, Enum):
    """Types of audit events"""
    
    # Authentication events
    LOGIN_SUCCESS = "auth.login.success"
    LOGIN_FAILURE = "auth.login.failure"
    LOGOUT = "auth.logout"
    TOKEN_REFRESH = "auth.token.refresh"
    TOKEN_REVOKE = "auth.token.revoke"
    
    # Authorization events
    ACCESS_GRANTED = "authz.access.granted"
    ACCESS_DENIED = "authz.access.denied"
    PERMISSION_CHECK = "authz.permission.check"
    ROLE_ASSIGNMENT = "authz.role.assignment"
    
    # Data access events
    DATA_READ = "data.read"
    DATA_CREATE = "data.create"
    DATA_UPDATE = "data.update"
    DATA_DELETE = "data.delete"
    DATA_EXPORT = "data.export"
    
    # PII events
    PII_ACCESS = "pii.access"
    PII_REDACTION = "pii.redaction"
    PII_RETENTION = "pii.retention"
    
    # System events
    CONFIG_CHANGE = "system.config.change"
    ADMIN_ACTION = "system.admin.action"
    SECURITY_VIOLATION = "system.security.violation"
    
    # Business events
    CALL_START = "business.call.start"
    CALL_END = "business.call.end"
    BOOKING_ACCESS = "business.booking.access"
    PAYMENT_PROCESS = "business.payment.process"
    
    # Webhook events
    WEBHOOK_RECEIVED = "webhook.received"
    WEBHOOK_PROCESSED = "webhook.processed"
    WEBHOOK_FAILED = "webhook.failed"


class AuditSeverity(str, Enum):
    """Severity levels for audit events"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AuditContext:
    """Context information for audit events"""
    
    # Request context
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    session_id: Optional[str] = None
    
    # User context
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_roles: Optional[List[str]] = None
    
    # Client context
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    client_id: Optional[str] = None
    
    # Service context
    service_name: str = "orchestrator"
    service_version: Optional[str] = None
    environment: Optional[str] = None
    
    # Location context
    region: Optional[str] = None
    data_center: Optional[str] = None


@dataclass
class AuditEvent:
    """Audit event data structure"""
    
    # Event identification
    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    
    # Event details
    severity: AuditSeverity
    description: str
    
    # Context
    context: AuditContext
    
    # Event-specific data
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    action: Optional[str] = None
    
    # Results
    success: bool = True
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    
    # Additional data (will be redacted for PII)
    metadata: Optional[Dict[str, Any]] = None
    
    # Compliance fields
    gdpr_lawful_basis: Optional[str] = None
    data_subject_id: Optional[str] = None
    retention_period: Optional[int] = None  # days
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        data = asdict(self)
        
        # Convert datetime to ISO format
        data['timestamp'] = self.timestamp.isoformat()
        
        # Convert enums to values
        data['event_type'] = self.event_type.value
        data['severity'] = self.severity.value
        
        return data


class AuditLogger:
    """Audit logging manager with PII redaction and compliance features"""
    
    def __init__(self, 
                 service_name: str = "orchestrator",
                 environment: str = "production",
                 enable_pii_redaction: bool = True):
        self.service_name = service_name
        self.environment = environment
        self.enable_pii_redaction = enable_pii_redaction
        
        # Import PII redactor if available
        if enable_pii_redaction:
            try:
                from config.security.pii_redactor import get_default_redactor
                self.pii_redactor = get_default_redactor()
            except ImportError:
                logger.warning("PII redactor not available, audit logs may contain sensitive data")
                self.pii_redactor = None
        else:
            self.pii_redactor = None
    
    def log_event(self, 
                  event_type: AuditEventType,
                  description: str,
                  context: Optional[AuditContext] = None,
                  severity: AuditSeverity = AuditSeverity.MEDIUM,
                  resource_type: Optional[str] = None,
                  resource_id: Optional[str] = None,
                  action: Optional[str] = None,
                  success: bool = True,
                  error_code: Optional[str] = None,
                  error_message: Optional[str] = None,
                  metadata: Optional[Dict[str, Any]] = None,
                  gdpr_lawful_basis: Optional[str] = None,
                  data_subject_id: Optional[str] = None,
                  retention_period: Optional[int] = None):
        """Log an audit event"""
        
        # Generate event ID
        event_id = self._generate_event_id()
        
        # Use default context if none provided
        if context is None:
            context = AuditContext(
                service_name=self.service_name,
                environment=self.environment
            )
        
        # Create audit event
        event = AuditEvent(
            event_id=event_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            severity=severity,
            description=description,
            context=context,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            success=success,
            error_code=error_code,
            error_message=error_message,
            metadata=metadata,
            gdpr_lawful_basis=gdpr_lawful_basis,
            data_subject_id=data_subject_id,
            retention_period=retention_period
        )
        
        # Process and log the event
        self._process_and_log_event(event)
    
    def log_authentication_event(self,
                                event_type: AuditEventType,
                                user_id: Optional[str] = None,
                                user_email: Optional[str] = None,
                                success: bool = True,
                                error_message: Optional[str] = None,
                                context: Optional[AuditContext] = None):
        """Log authentication-related events"""
        
        if context:
            context.user_id = user_id
            context.user_email = user_email
        
        self.log_event(
            event_type=event_type,
            description=f"Authentication event: {event_type.value}",
            context=context,
            severity=AuditSeverity.HIGH if not success else AuditSeverity.MEDIUM,
            resource_type="user",
            resource_id=user_id,
            action="authenticate",
            success=success,
            error_message=error_message,
            gdpr_lawful_basis="legitimate_interest",
            retention_period=90  # 90 days for auth logs
        )
    
    def log_data_access_event(self,
                             action: str,
                             resource_type: str,
                             resource_id: Optional[str] = None,
                             data_subject_id: Optional[str] = None,
                             success: bool = True,
                             context: Optional[AuditContext] = None,
                             metadata: Optional[Dict[str, Any]] = None):
        """Log data access events"""
        
        event_type_map = {
            "read": AuditEventType.DATA_READ,
            "create": AuditEventType.DATA_CREATE,
            "update": AuditEventType.DATA_UPDATE,
            "delete": AuditEventType.DATA_DELETE,
            "export": AuditEventType.DATA_EXPORT
        }
        
        event_type = event_type_map.get(action.lower(), AuditEventType.DATA_READ)
        
        self.log_event(
            event_type=event_type,
            description=f"Data {action} on {resource_type}",
            context=context,
            severity=AuditSeverity.HIGH if action in ["delete", "export"] else AuditSeverity.MEDIUM,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            success=success,
            metadata=metadata,
            gdpr_lawful_basis="contract" if resource_type in ["booking", "guest"] else "legitimate_interest",
            data_subject_id=data_subject_id,
            retention_period=2555 if resource_type in ["booking", "payment"] else 365  # 7 years for financial, 1 year for others
        )
    
    def log_pii_event(self,
                     action: str,
                     pii_types: List[str],
                     data_subject_id: Optional[str] = None,
                     context: Optional[AuditContext] = None,
                     metadata: Optional[Dict[str, Any]] = None):
        """Log PII-related events"""
        
        event_type_map = {
            "access": AuditEventType.PII_ACCESS,
            "redaction": AuditEventType.PII_REDACTION,
            "retention": AuditEventType.PII_RETENTION
        }
        
        event_type = event_type_map.get(action.lower(), AuditEventType.PII_ACCESS)
        
        self.log_event(
            event_type=event_type,
            description=f"PII {action}: {', '.join(pii_types)}",
            context=context,
            severity=AuditSeverity.HIGH,
            resource_type="pii",
            action=action,
            metadata={
                "pii_types": pii_types,
                **(metadata or {})
            },
            gdpr_lawful_basis="consent",
            data_subject_id=data_subject_id,
            retention_period=2555  # 7 years for PII audit logs
        )
    
    def log_security_event(self,
                          description: str,
                          severity: AuditSeverity = AuditSeverity.HIGH,
                          context: Optional[AuditContext] = None,
                          metadata: Optional[Dict[str, Any]] = None):
        """Log security-related events"""
        
        self.log_event(
            event_type=AuditEventType.SECURITY_VIOLATION,
            description=description,
            context=context,
            severity=severity,
            resource_type="security",
            action="violation",
            success=False,
            metadata=metadata,
            gdpr_lawful_basis="legitimate_interest",
            retention_period=2555  # 7 years for security logs
        )
    
    def create_context_from_request(self, request: Request, user_context: Optional[Dict[str, Any]] = None) -> AuditContext:
        """Create audit context from FastAPI request"""
        
        # Extract correlation ID
        correlation_id = request.headers.get("X-Correlation-ID")
        
        # Extract client IP
        client_ip = self._get_client_ip(request)
        
        # Extract user agent
        user_agent = request.headers.get("User-Agent")
        
        # Create context
        context = AuditContext(
            request_id=getattr(request.state, 'request_id', None),
            correlation_id=correlation_id,
            client_ip=client_ip,
            user_agent=user_agent,
            service_name=self.service_name,
            environment=self.environment
        )
        
        # Add user context if provided
        if user_context:
            context.user_id = user_context.get("user_id")
            context.user_email = user_context.get("user_email")
            context.user_roles = user_context.get("roles")
            context.session_id = user_context.get("session_id")
            context.client_id = user_context.get("client_id")
        
        return context
    
    @contextmanager
    def audit_operation(self,
                       operation_name: str,
                       resource_type: str,
                       resource_id: Optional[str] = None,
                       context: Optional[AuditContext] = None):
        """Context manager for auditing operations"""
        
        start_time = datetime.now(timezone.utc)
        
        # Log operation start
        self.log_event(
            event_type=AuditEventType.DATA_READ,  # Will be updated based on actual operation
            description=f"Operation started: {operation_name}",
            context=context,
            severity=AuditSeverity.LOW,
            resource_type=resource_type,
            resource_id=resource_id,
            action="start",
            metadata={"operation": operation_name, "start_time": start_time.isoformat()}
        )
        
        try:
            yield
            
            # Log successful completion
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            
            self.log_event(
                event_type=AuditEventType.DATA_READ,
                description=f"Operation completed: {operation_name}",
                context=context,
                severity=AuditSeverity.LOW,
                resource_type=resource_type,
                resource_id=resource_id,
                action="complete",
                success=True,
                metadata={
                    "operation": operation_name,
                    "duration_seconds": duration,
                    "end_time": end_time.isoformat()
                }
            )
            
        except Exception as e:
            # Log failure
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            
            self.log_event(
                event_type=AuditEventType.DATA_READ,
                description=f"Operation failed: {operation_name}",
                context=context,
                severity=AuditSeverity.HIGH,
                resource_type=resource_type,
                resource_id=resource_id,
                action="fail",
                success=False,
                error_message=str(e),
                metadata={
                    "operation": operation_name,
                    "duration_seconds": duration,
                    "end_time": end_time.isoformat()
                }
            )
            raise
    
    def _process_and_log_event(self, event: AuditEvent):
        """Process and log the audit event"""
        
        # Convert to dictionary
        event_data = event.to_dict()
        
        # Redact PII if enabled
        if self.pii_redactor and event_data.get('metadata'):
            event_data['metadata'] = self.pii_redactor.redact_dict(event_data['metadata'])
        
        # Log the event
        logger.info(
            "audit_event",
            **event_data
        )
        
        # For critical events, also log to a separate audit trail
        if event.severity == AuditSeverity.CRITICAL:
            logger.critical(
                "critical_audit_event",
                event_id=event.event_id,
                event_type=event.event_type.value,
                description=event.description
            )
    
    def _generate_event_id(self) -> str:
        """Generate unique event ID"""
        import uuid
        return str(uuid.uuid4())
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP from request"""
        # Check forwarded headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to direct connection
        if hasattr(request, "client") and request.client:
            return request.client.host
        
        return "unknown"


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def audit_event(event_type: AuditEventType, description: str, **kwargs):
    """Convenience function to log audit events"""
    audit_logger = get_audit_logger()
    audit_logger.log_event(event_type, description, **kwargs)


# Audit middleware for FastAPI
class AuditMiddleware:
    """Middleware to automatically audit HTTP requests"""
    
    def __init__(self, app, audit_logger: Optional[AuditLogger] = None):
        self.app = app
        self.audit_logger = audit_logger or get_audit_logger()
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Create request object for context
            from fastapi import Request
            request = Request(scope, receive)
            
            # Create audit context
            context = self.audit_logger.create_context_from_request(request)
            
            # Log request
            self.audit_logger.log_event(
                event_type=AuditEventType.DATA_READ,  # Default, will be refined based on method
                description=f"HTTP {request.method} {request.url.path}",
                context=context,
                severity=AuditSeverity.LOW,
                resource_type="endpoint",
                action=request.method.lower(),
                metadata={
                    "path": str(request.url.path),
                    "query_params": dict(request.query_params)
                }
            )
        
        await self.app(scope, receive, send)


# Example usage
if __name__ == "__main__":
    # Test audit logging
    audit_logger = AuditLogger()
    
    # Test authentication event
    context = AuditContext(
        user_id="user123",
        user_email="test@example.com",
        client_ip="192.168.1.1"
    )
    
    audit_logger.log_authentication_event(
        event_type=AuditEventType.LOGIN_SUCCESS,
        user_id="user123",
        user_email="test@example.com",
        context=context
    )
    
    # Test data access event
    audit_logger.log_data_access_event(
        action="read",
        resource_type="booking",
        resource_id="booking123",
        data_subject_id="guest456",
        context=context
    )
    
    # Test PII event
    audit_logger.log_pii_event(
        action="access",
        pii_types=["email", "phone"],
        data_subject_id="guest456",
        context=context
    )
    
    print("Audit logging test completed")