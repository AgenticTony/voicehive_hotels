"""
Safe logging adapter for structlog/stdlib compatibility.
Provides a consistent interface that works with both structlog and standard library logging.
"""

from typing import Any, Dict, Optional
import logging


class SafeLogger:
    """
    Safe logging adapter that handles both structlog and stdlib logging gracefully.
    Prevents kwarg issues when structlog is not available by converting to extra dict.
    """
    
    def __init__(self, logger: Any):
        self._logger = logger
        self._is_structlog = hasattr(logger, 'bind')
    
    def _log(self, log_level: str, event: str, **kwargs) -> None:
        """
        Internal method to handle logging with proper formatting.
        
        Args:
            log_level: Log level (debug, info, warning, error, critical)
            event: Event name/message
            **kwargs: Additional context fields
        """
        if self._is_structlog:
            # Structlog can handle kwargs directly
            getattr(self._logger, log_level)(event, **kwargs)
        else:
            # Standard library logger needs special handling
            # Extract special kwargs that stdlib recognizes
            special_kwargs = {}
            for key in ['exc_info', 'stack_info', 'stacklevel']:
                if key in kwargs:
                    special_kwargs[key] = kwargs.pop(key)
            
            # Handle user-provided 'extra' dict
            user_extra = kwargs.pop('extra', {})
            
            # Build final extra dict
            extra_dict = {}
            if user_extra:
                extra_dict.update(user_extra)
            
            # Put remaining kwargs under 'fields' to avoid LogRecord conflicts
            if kwargs:
                extra_dict['fields'] = kwargs
            
            # Call stdlib logger with special kwargs
            getattr(self._logger, log_level)(event, extra=extra_dict, **special_kwargs)
    
    def bind(self, **kwargs) -> 'SafeLogger':
        """
        Bind context to logger if structlog, otherwise return self.
        
        Args:
            **kwargs: Context to bind
            
        Returns:
            New SafeLogger with bound context (structlog) or self (stdlib)
        """
        if self._is_structlog:
            return SafeLogger(self._logger.bind(**kwargs))
        else:
            # For stdlib, we can't truly bind, but return self for chaining
            return self
    
    def debug(self, event: str, **kwargs) -> None:
        """Log a debug message with optional context."""
        self._log('debug', event, **kwargs)
    
    def info(self, event: str, **kwargs) -> None:
        """Log an info message with optional context."""
        self._log('info', event, **kwargs)
    
    def warning(self, event: str, **kwargs) -> None:
        """Log a warning message with optional context."""
        self._log('warning', event, **kwargs)
    
    def error(self, event: str, **kwargs) -> None:
        """Log an error message with optional context."""
        self._log('error', event, **kwargs)
    
    def critical(self, event: str, **kwargs) -> None:
        """Log a critical message with optional context."""
        self._log('critical', event, **kwargs)
    
    # Alias warn to warning for compatibility
    warn = warning


def get_safe_logger(name: Optional[str] = None) -> SafeLogger:
    """
    Get a safe logger instance that works with both structlog and stdlib.
    
    Args:
        name: Optional logger name (used for stdlib logger)
        
    Returns:
        SafeLogger instance
    """
    try:
        import structlog
        logger = structlog.get_logger(name) if name else structlog.get_logger()
    except ImportError:
        # Fallback to standard library logger
        logger = logging.getLogger(name or __name__)
    
    return SafeLogger(logger)
