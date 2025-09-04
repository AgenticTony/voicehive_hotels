"""
Secure Logging Utilities for PMS Connectors
Provides structured logging with automatic PII redaction and correlation IDs
"""

import logging
import json
import time
import uuid
from typing import Dict, Any, Optional, Union
from contextvars import ContextVar
from functools import wraps
from datetime import datetime

from .pii_redactor import PIIRedactorFilter, redact_pii

# Context variable for correlation ID
correlation_id: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class StructuredFormatter(logging.Formatter):
    """
    Structured JSON formatter for logs with PII redaction
    
    Outputs logs in JSON format for better observability
    """
    
    def __init__(self, service_name: str = "voicehive-connectors"):
        super().__init__()
        self.service_name = service_name
        self.hostname = self._get_hostname()
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON with standard fields"""
        log_obj = {
            "@timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "hostname": self.hostname,
            "correlation_id": correlation_id.get(),
            "thread_name": record.threadName,
            "process_id": record.process,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if present
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'msecs', 
                          'filename', 'funcName', 'levelname', 'levelno',
                          'lineno', 'module', 'exc_info', 'exc_text',
                          'stack_info', 'pathname', 'process', 'processName',
                          'relativeCreated', 'thread', 'threadName', 'getMessage']:
                log_obj[key] = value
        
        return json.dumps(log_obj, default=str)
    
    @staticmethod
    def _get_hostname():
        """Get hostname for logging"""
        import socket
        try:
            return socket.gethostname()
        except:
            return "unknown"


class ConnectorLogger:
    """
    Enhanced logger for PMS connectors with built-in security and observability
    
    Features:
    - Automatic PII redaction
    - Correlation ID tracking
    - Performance metrics
    - Structured logging
    """
    
    def __init__(self, name: str, vendor: str, hotel_id: Optional[str] = None):
        self.logger = logging.getLogger(name)
        self.vendor = vendor
        self.hotel_id = hotel_id
        
        # Add PII redaction filter
        self.logger.addFilter(PIIRedactorFilter())
        
        # Set up structured logging if not already configured
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(StructuredFormatter())
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def with_correlation_id(self, correlation_id_val: Optional[str] = None) -> str:
        """Set or generate correlation ID for request tracking"""
        if correlation_id_val:
            correlation_id.set(correlation_id_val)
        else:
            correlation_id.set(str(uuid.uuid4()))
        return correlation_id.get()
    
    def log_api_call(self, 
                     operation: str,
                     request_data: Optional[Dict[str, Any]] = None,
                     response_data: Optional[Dict[str, Any]] = None,
                     duration_ms: Optional[float] = None,
                     status_code: Optional[int] = None,
                     error: Optional[Exception] = None):
        """Log API call with standardized fields"""
        
        log_data = {
            "vendor": self.vendor,
            "hotel_id": self.hotel_id,
            "operation": operation,
            "duration_ms": duration_ms,
            "status_code": status_code,
        }
        
        # Add request data (redacted)
        if request_data:
            from .pii_redactor import get_default_redactor
            redactor = get_default_redactor()
            log_data["request"] = redactor.redact_dict(request_data)
        
        # Add response data (redacted)
        if response_data:
            from .pii_redactor import get_default_redactor
            redactor = get_default_redactor()
            log_data["response"] = redactor.redact_dict(response_data)
        
        # Log based on outcome
        if error:
            log_data["error"] = str(error)
            log_data["error_type"] = type(error).__name__
            self.logger.error(f"API call failed: {operation}", extra=log_data)
        else:
            self.logger.info(f"API call completed: {operation}", extra=log_data)
    
    def log_reservation(self,
                       action: str,
                       reservation_id: Optional[str] = None,
                       confirmation_number: Optional[str] = None,
                       guest_name: Optional[str] = None,
                       room_type: Optional[str] = None,
                       arrival: Optional[str] = None,
                       departure: Optional[str] = None,
                       status: Optional[str] = None):
        """Log reservation operations with PII handled properly"""
        
        # Note: guest_name will be automatically redacted by PIIRedactorFilter
        log_data = {
            "vendor": self.vendor,
            "hotel_id": self.hotel_id,
            "action": action,
            "reservation_id": reservation_id,
            "confirmation_number": confirmation_number,  # Will be redacted
            "guest_name": guest_name,  # Will be redacted
            "room_type": room_type,
            "arrival": arrival,
            "departure": departure,
            "status": status,
        }
        
        self.logger.info(f"Reservation {action}", extra=log_data)
    
    def debug(self, msg: str, **kwargs):
        """Debug level logging with extra fields"""
        self.logger.debug(msg, extra={"vendor": self.vendor, "hotel_id": self.hotel_id, **kwargs})
    
    def info(self, msg: str, **kwargs):
        """Info level logging with extra fields"""
        self.logger.info(msg, extra={"vendor": self.vendor, "hotel_id": self.hotel_id, **kwargs})
    
    def warning(self, msg: str, **kwargs):
        """Warning level logging with extra fields"""
        self.logger.warning(msg, extra={"vendor": self.vendor, "hotel_id": self.hotel_id, **kwargs})
    
    def error(self, msg: str, exc_info=None, **kwargs):
        """Error level logging with extra fields"""
        self.logger.error(msg, exc_info=exc_info, extra={"vendor": self.vendor, "hotel_id": self.hotel_id, **kwargs})


def log_performance(operation: str):
    """
    Decorator to log performance metrics for async functions
    
    Usage:
        @log_performance("get_availability")
        async def get_availability(self, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            start_time = time.time()
            error = None
            
            try:
                result = await func(self, *args, **kwargs)
                return result
            except Exception as e:
                error = e
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                
                if hasattr(self, 'logger') and isinstance(self.logger, ConnectorLogger):
                    self.logger.log_api_call(
                        operation=operation,
                        duration_ms=duration_ms,
                        error=error
                    )
                elif hasattr(self, 'logger'):
                    # Fallback for standard logger
                    if error:
                        self.logger.error(
                            f"{operation} failed in {duration_ms:.2f}ms: {error}",
                            extra={"operation": operation, "duration_ms": duration_ms}
                        )
                    else:
                        self.logger.info(
                            f"{operation} completed in {duration_ms:.2f}ms",
                            extra={"operation": operation, "duration_ms": duration_ms}
                        )
        
        return wrapper
    return decorator


def sanitize_url(url: str) -> str:
    """
    Sanitize URL for logging by removing sensitive query parameters
    
    Args:
        url: URL to sanitize
        
    Returns:
        Sanitized URL safe for logging
    """
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    
    sensitive_params = {
        'api_key', 'apikey', 'key', 'token', 'secret',
        'password', 'pwd', 'auth', 'authorization',
        'client_secret', 'client_id', 'access_token',
        'refresh_token', 'session', 'sid'
    }
    
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    
    # Redact sensitive parameters
    sanitized_params = {}
    for param, values in query_params.items():
        if param.lower() in sensitive_params:
            sanitized_params[param] = ['<REDACTED>']
        else:
            sanitized_params[param] = values
    
    # Reconstruct URL
    sanitized_query = urlencode(sanitized_params, doseq=True)
    sanitized_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        sanitized_query,
        parsed.fragment
    ))
    
    return sanitized_url
