"""
Correlation ID middleware for distributed request tracing
"""

import uuid
from typing import Callable, Optional
from contextvars import ContextVar
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from logging_adapter import get_safe_logger

logger = get_safe_logger("correlation_middleware")

# Context variable to store correlation ID throughout request lifecycle
correlation_id_context: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle correlation IDs for distributed tracing
    
    This middleware:
    1. Extracts correlation ID from incoming requests
    2. Generates a new one if not present
    3. Stores it in context for use throughout the request
    4. Adds it to response headers
    5. Ensures it's available for logging
    """
    
    def __init__(
        self,
        app,
        header_name: str = "X-Correlation-ID",
        response_header_name: Optional[str] = None,
        generate_if_missing: bool = True
    ):
        super().__init__(app)
        self.header_name = header_name
        self.response_header_name = response_header_name or header_name
        self.generate_if_missing = generate_if_missing
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add correlation ID handling"""
        
        # Extract correlation ID from request headers
        correlation_id = request.headers.get(self.header_name)
        
        # Generate new correlation ID if missing and generation is enabled
        if not correlation_id and self.generate_if_missing:
            correlation_id = str(uuid.uuid4())
        
        # Store correlation ID in context
        if correlation_id:
            correlation_id_context.set(correlation_id)
            
            # Add to request state for easy access
            request.state.correlation_id = correlation_id
            
            logger.debug(
                "correlation_id_set",
                correlation_id=correlation_id,
                path=request.url.path,
                method=request.method,
                source="header" if request.headers.get(self.header_name) else "generated"
            )
        
        try:
            # Process the request
            response = await call_next(request)
            
            # Add correlation ID to response headers
            if correlation_id:
                response.headers[self.response_header_name] = correlation_id
            
            return response
            
        except Exception as e:
            # Ensure correlation ID is available even for error responses
            logger.error(
                "request_processing_error",
                correlation_id=correlation_id,
                path=request.url.path,
                method=request.method,
                error=str(e),
                error_type=type(e).__name__
            )
            raise
        
        finally:
            # Clear correlation ID from context
            correlation_id_context.set(None)


def get_correlation_id() -> Optional[str]:
    """
    Get the current correlation ID from context
    
    Returns:
        Current correlation ID or None if not set
    """
    return correlation_id_context.get()


def set_correlation_id(correlation_id: str) -> None:
    """
    Set the correlation ID in context
    
    Args:
        correlation_id: Correlation ID to set
    """
    correlation_id_context.set(correlation_id)


def generate_correlation_id() -> str:
    """
    Generate a new correlation ID
    
    Returns:
        New UUID-based correlation ID
    """
    return str(uuid.uuid4())


class CorrelationIDLogger:
    """
    Logger wrapper that automatically includes correlation ID in log entries
    """
    
    def __init__(self, logger_name: str):
        self.logger = get_safe_logger(logger_name)
    
    def _log_with_correlation(self, level: str, event: str, **kwargs):
        """Add correlation ID to log entry"""
        correlation_id = get_correlation_id()
        if correlation_id:
            kwargs['correlation_id'] = correlation_id
        
        getattr(self.logger, level)(event, **kwargs)
    
    def debug(self, event: str, **kwargs):
        """Log debug message with correlation ID"""
        self._log_with_correlation('debug', event, **kwargs)
    
    def info(self, event: str, **kwargs):
        """Log info message with correlation ID"""
        self._log_with_correlation('info', event, **kwargs)
    
    def warning(self, event: str, **kwargs):
        """Log warning message with correlation ID"""
        self._log_with_correlation('warning', event, **kwargs)
    
    def error(self, event: str, **kwargs):
        """Log error message with correlation ID"""
        self._log_with_correlation('error', event, **kwargs)
    
    def critical(self, event: str, **kwargs):
        """Log critical message with correlation ID"""
        self._log_with_correlation('critical', event, **kwargs)


def get_correlation_logger(name: str) -> CorrelationIDLogger:
    """
    Get a logger that automatically includes correlation IDs
    
    Args:
        name: Logger name
    
    Returns:
        CorrelationIDLogger instance
    """
    return CorrelationIDLogger(name)


# Utility functions for external service calls
def get_correlation_headers() -> dict:
    """
    Get headers dict with correlation ID for external service calls
    
    Returns:
        Dictionary with correlation ID header
    """
    correlation_id = get_correlation_id()
    if correlation_id:
        return {"X-Correlation-ID": correlation_id}
    return {}


def propagate_correlation_id(headers: dict) -> dict:
    """
    Add correlation ID to existing headers dict
    
    Args:
        headers: Existing headers dictionary
    
    Returns:
        Headers dictionary with correlation ID added
    """
    correlation_id = get_correlation_id()
    if correlation_id:
        headers = headers.copy()
        headers["X-Correlation-ID"] = correlation_id
    return headers


class CorrelationContext:
    """
    Context manager for setting correlation ID in async operations
    """
    
    def __init__(self, correlation_id: Optional[str] = None):
        self.correlation_id = correlation_id or generate_correlation_id()
        self.previous_id = None
    
    def __enter__(self):
        self.previous_id = get_correlation_id()
        set_correlation_id(self.correlation_id)
        return self.correlation_id
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        set_correlation_id(self.previous_id)
    
    async def __aenter__(self):
        return self.__enter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.__exit__(exc_type, exc_val, exc_tb)


# Decorator for functions that should have correlation ID context
def with_correlation_id(correlation_id: Optional[str] = None):
    """
    Decorator to ensure function runs with correlation ID context
    
    Args:
        correlation_id: Optional correlation ID to use, generates new one if None
    """
    def decorator(func):
        if hasattr(func, '__call__'):
            async def async_wrapper(*args, **kwargs):
                async with CorrelationContext(correlation_id):
                    return await func(*args, **kwargs)
            
            def sync_wrapper(*args, **kwargs):
                with CorrelationContext(correlation_id):
                    return func(*args, **kwargs)
            
            # Return appropriate wrapper
            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            else:
                return sync_wrapper
        return func
    return decorator