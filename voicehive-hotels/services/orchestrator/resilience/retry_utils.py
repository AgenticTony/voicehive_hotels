"""
Retry utilities with exponential backoff for external service calls
"""

import asyncio
import random
from typing import Callable, Any, Optional, Type, Tuple, Union, List
from functools import wraps
from datetime import datetime, timedelta, timezone

from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
    before_sleep_log, after_log, RetryError
)

from logging_adapter import get_safe_logger
from error_models import ExternalServiceError, ErrorSeverity

logger = get_safe_logger("retry_utils")


class RetryConfig:
    """Configuration for retry behavior"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
        non_retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions or (
            ConnectionError,
            TimeoutError,
            OSError,
            asyncio.TimeoutError
        )
        self.non_retryable_exceptions = non_retryable_exceptions or (
            ValueError,
            TypeError,
            KeyError,
            AttributeError
        )


# Default retry configurations for different service types
DEFAULT_RETRY_CONFIGS = {
    "database": RetryConfig(
        max_attempts=3,
        base_delay=0.5,
        max_delay=10.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError)
    ),
    "external_api": RetryConfig(
        max_attempts=3,
        base_delay=1.0,
        max_delay=30.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError)
    ),
    "pms_connector": RetryConfig(
        max_attempts=5,
        base_delay=2.0,
        max_delay=60.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError)
    ),
    "tts_service": RetryConfig(
        max_attempts=3,
        base_delay=1.0,
        max_delay=20.0,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError)
    ),
    "redis": RetryConfig(
        max_attempts=2,
        base_delay=0.1,
        max_delay=1.0,
        retryable_exceptions=(ConnectionError, TimeoutError)
    )
}


def create_retry_decorator(config: RetryConfig, service_name: str = "unknown"):
    """
    Create a retry decorator with the specified configuration
    
    Args:
        config: RetryConfig instance
        service_name: Name of the service for logging
    
    Returns:
        Configured retry decorator
    """
    
    def should_retry(exception):
        """Determine if an exception should trigger a retry"""
        # Don't retry non-retryable exceptions
        if isinstance(exception, config.non_retryable_exceptions):
            return False
        
        # Retry retryable exceptions
        if isinstance(exception, config.retryable_exceptions):
            return True
        
        # For HTTP errors, check status codes
        if hasattr(exception, 'status_code'):
            # Retry on 5xx server errors and some 4xx errors
            return exception.status_code >= 500 or exception.status_code in [408, 429]
        
        return False
    
    def log_retry_attempt(retry_state):
        """Log retry attempts"""
        logger.warning(
            "retry_attempt",
            service=service_name,
            attempt=retry_state.attempt_number,
            exception=str(retry_state.outcome.exception()) if retry_state.outcome.failed else None,
            next_sleep=retry_state.next_action.sleep if hasattr(retry_state.next_action, 'sleep') else None
        )
    
    def log_final_attempt(retry_state):
        """Log final attempt result"""
        if retry_state.outcome.failed:
            logger.error(
                "retry_exhausted",
                service=service_name,
                attempts=retry_state.attempt_number,
                final_exception=str(retry_state.outcome.exception())
            )
        else:
            logger.info(
                "retry_succeeded",
                service=service_name,
                attempts=retry_state.attempt_number
            )
    
    # Create wait strategy with jitter if enabled
    if config.jitter:
        wait_strategy = wait_exponential(
            multiplier=config.base_delay,
            max=config.max_delay,
            exp_base=config.exponential_base
        ) + wait_exponential(
            multiplier=0.1,  # Small jitter component
            max=config.max_delay * 0.1,
            exp_base=config.exponential_base
        )
    else:
        wait_strategy = wait_exponential(
            multiplier=config.base_delay,
            max=config.max_delay,
            exp_base=config.exponential_base
        )
    
    return retry(
        stop=stop_after_attempt(config.max_attempts),
        wait=wait_strategy,
        retry=retry_if_exception_type(config.retryable_exceptions),
        before_sleep=log_retry_attempt,
        after=log_final_attempt,
        reraise=True
    )


def with_retry(
    service_name: str,
    config_name: Optional[str] = None,
    custom_config: Optional[RetryConfig] = None
):
    """
    Decorator to add retry logic to functions
    
    Args:
        service_name: Name of the service for logging
        config_name: Name of predefined config to use
        custom_config: Custom RetryConfig to use
    
    Returns:
        Decorated function with retry logic
    """
    
    # Determine which config to use
    if custom_config:
        config = custom_config
    elif config_name and config_name in DEFAULT_RETRY_CONFIGS:
        config = DEFAULT_RETRY_CONFIGS[config_name]
    else:
        config = DEFAULT_RETRY_CONFIGS["external_api"]
    
    retry_decorator = create_retry_decorator(config, service_name)
    
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await retry_decorator(func)(*args, **kwargs)
            except RetryError as e:
                # Convert RetryError to our custom exception
                original_exception = e.last_attempt.exception()
                raise ExternalServiceError(
                    service=service_name,
                    message=f"Operation failed after {config.max_attempts} attempts: {str(original_exception)}",
                    details={
                        "attempts": config.max_attempts,
                        "original_error": str(original_exception),
                        "error_type": type(original_exception).__name__
                    }
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return retry_decorator(func)(*args, **kwargs)
            except RetryError as e:
                # Convert RetryError to our custom exception
                original_exception = e.last_attempt.exception()
                raise ExternalServiceError(
                    service=service_name,
                    message=f"Operation failed after {config.max_attempts} attempts: {str(original_exception)}",
                    details={
                        "attempts": config.max_attempts,
                        "original_error": str(original_exception),
                        "error_type": type(original_exception).__name__
                    }
                )
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class RetryableOperation:
    """
    Context manager for retryable operations with detailed tracking
    """
    
    def __init__(
        self,
        operation_name: str,
        service_name: str,
        config: Optional[RetryConfig] = None,
        correlation_id: Optional[str] = None
    ):
        self.operation_name = operation_name
        self.service_name = service_name
        self.config = config or DEFAULT_RETRY_CONFIGS["external_api"]
        self.correlation_id = correlation_id
        self.start_time = None
        self.attempts = 0
        self.last_exception = None
    
    async def __aenter__(self):
        self.start_time = datetime.now(timezone.utc)
        logger.info(
            "retryable_operation_started",
            operation=self.operation_name,
            service=self.service_name,
            correlation_id=self.correlation_id,
            max_attempts=self.config.max_attempts
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        if exc_type is None:
            logger.info(
                "retryable_operation_completed",
                operation=self.operation_name,
                service=self.service_name,
                correlation_id=self.correlation_id,
                attempts=self.attempts,
                duration_seconds=duration
            )
        else:
            logger.error(
                "retryable_operation_failed",
                operation=self.operation_name,
                service=self.service_name,
                correlation_id=self.correlation_id,
                attempts=self.attempts,
                duration_seconds=duration,
                error=str(exc_val),
                error_type=exc_type.__name__
            )
    
    async def execute(self, func: Callable, *args, **kwargs):
        """
        Execute a function with retry logic
        
        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
        
        Returns:
            Function result
        
        Raises:
            ExternalServiceError: If all retry attempts fail
        """
        for attempt in range(1, self.config.max_attempts + 1):
            self.attempts = attempt
            
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                if attempt > 1:
                    logger.info(
                        "retry_succeeded",
                        operation=self.operation_name,
                        service=self.service_name,
                        correlation_id=self.correlation_id,
                        attempt=attempt
                    )
                
                return result
                
            except Exception as e:
                self.last_exception = e
                
                # Check if we should retry
                should_retry = self._should_retry(e)
                
                if not should_retry or attempt == self.config.max_attempts:
                    # Final attempt or non-retryable error
                    raise ExternalServiceError(
                        service=self.service_name,
                        message=f"{self.operation_name} failed after {attempt} attempts: {str(e)}",
                        details={
                            "operation": self.operation_name,
                            "attempts": attempt,
                            "original_error": str(e),
                            "error_type": type(e).__name__,
                            "correlation_id": self.correlation_id
                        }
                    )
                
                # Calculate delay for next attempt
                delay = self._calculate_delay(attempt)
                
                logger.warning(
                    "retry_attempt_failed",
                    operation=self.operation_name,
                    service=self.service_name,
                    correlation_id=self.correlation_id,
                    attempt=attempt,
                    error=str(e),
                    next_delay=delay
                )
                
                await asyncio.sleep(delay)
    
    def _should_retry(self, exception: Exception) -> bool:
        """Determine if an exception should trigger a retry"""
        # Don't retry non-retryable exceptions
        if isinstance(exception, self.config.non_retryable_exceptions):
            return False
        
        # Retry retryable exceptions
        if isinstance(exception, self.config.retryable_exceptions):
            return True
        
        # For HTTP errors, check status codes
        if hasattr(exception, 'status_code'):
            return exception.status_code >= 500 or exception.status_code in [408, 429]
        
        return False
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for next retry attempt"""
        base_delay = self.config.base_delay * (self.config.exponential_base ** (attempt - 1))
        
        # Add jitter if enabled
        if self.config.jitter:
            jitter = random.uniform(0, base_delay * 0.1)
            base_delay += jitter
        
        return min(base_delay, self.config.max_delay)


# Convenience functions for common retry patterns
async def retry_database_operation(func: Callable, *args, **kwargs):
    """Retry a database operation with appropriate configuration"""
    async with RetryableOperation("database_operation", "database", DEFAULT_RETRY_CONFIGS["database"]) as op:
        return await op.execute(func, *args, **kwargs)


async def retry_external_api_call(service_name: str, func: Callable, *args, **kwargs):
    """Retry an external API call with appropriate configuration"""
    async with RetryableOperation("api_call", service_name, DEFAULT_RETRY_CONFIGS["external_api"]) as op:
        return await op.execute(func, *args, **kwargs)


async def retry_pms_connector_call(connector_name: str, func: Callable, *args, **kwargs):
    """Retry a PMS connector call with appropriate configuration"""
    async with RetryableOperation("pms_call", connector_name, DEFAULT_RETRY_CONFIGS["pms_connector"]) as op:
        return await op.execute(func, *args, **kwargs)