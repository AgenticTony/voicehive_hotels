"""
Circuit Breaker Implementation for External Service Calls
Implements Hystrix-style circuit breaker with exponential backoff and half-open state testing
"""

import asyncio
import time
from typing import Callable, Any, Optional, Dict, List
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import functools

import redis.asyncio as aioredis
from pydantic import BaseModel

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.circuit_breaker")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration"""
    failure_threshold: int = 5
    recovery_timeout: int = 60  # seconds
    expected_exception: tuple = (Exception,)
    success_threshold: int = 3  # for half-open state
    timeout: float = 30.0  # request timeout
    fallback_function: Optional[Callable] = None
    name: Optional[str] = None


class CircuitBreakerStats(BaseModel):
    """Circuit breaker statistics"""
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_time: Optional[datetime]
    last_success_time: Optional[datetime]
    total_requests: int
    total_failures: int
    total_successes: int
    next_attempt_time: Optional[datetime]


class CircuitBreakerOpenError(Exception):
    """Exception raised when circuit breaker is open"""
    def __init__(self, circuit_name: str, next_attempt_time: datetime):
        self.circuit_name = circuit_name
        self.next_attempt_time = next_attempt_time
        super().__init__(f"Circuit breaker '{circuit_name}' is open. Next attempt at {next_attempt_time}")


class CircuitBreakerTimeoutError(Exception):
    """Exception raised when circuit breaker times out"""
    pass


class CircuitBreaker:
    """
    Circuit breaker implementation with Redis persistence for distributed systems
    """
    
    def __init__(
        self, 
        config: CircuitBreakerConfig,
        redis_client: Optional[aioredis.Redis] = None
    ):
        self.config = config
        self.redis = redis_client
        self.name = config.name or f"circuit_{id(self)}"
        
        # Local state (used when Redis is not available)
        self._local_state = CircuitState.CLOSED
        self._local_failure_count = 0
        self._local_success_count = 0
        self._local_last_failure_time = None
        self._local_last_success_time = None
        self._local_total_requests = 0
        self._local_total_failures = 0
        self._local_total_successes = 0
        
        # Redis keys
        self._state_key = f"circuit_breaker:{self.name}:state"
        self._stats_key = f"circuit_breaker:{self.name}:stats"
        
        logger.info("circuit_breaker_created", name=self.name, config=config)
    
    async def _get_state(self) -> CircuitState:
        """Get current circuit breaker state"""
        if self.redis:
            try:
                state = await self.redis.get(self._state_key)
                return CircuitState(state.decode()) if state else CircuitState.CLOSED
            except Exception as e:
                logger.warning("circuit_breaker_redis_error", name=self.name, error=str(e))
        
        return self._local_state
    
    async def _set_state(self, state: CircuitState):
        """Set circuit breaker state"""
        if self.redis:
            try:
                await self.redis.set(self._state_key, state.value, ex=3600)  # 1 hour expiration
            except Exception as e:
                logger.warning("circuit_breaker_redis_error", name=self.name, error=str(e))
        
        self._local_state = state
        logger.info("circuit_breaker_state_changed", name=self.name, state=state.value)
    
    async def _get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics"""
        if self.redis:
            try:
                stats = await self.redis.hgetall(self._stats_key)
                if stats:
                    return {
                        'failure_count': int(stats.get(b'failure_count', 0)),
                        'success_count': int(stats.get(b'success_count', 0)),
                        'last_failure_time': float(stats.get(b'last_failure_time', 0)),
                        'last_success_time': float(stats.get(b'last_success_time', 0)),
                        'total_requests': int(stats.get(b'total_requests', 0)),
                        'total_failures': int(stats.get(b'total_failures', 0)),
                        'total_successes': int(stats.get(b'total_successes', 0))
                    }
            except Exception as e:
                logger.warning("circuit_breaker_redis_error", name=self.name, error=str(e))
        
        return {
            'failure_count': self._local_failure_count,
            'success_count': self._local_success_count,
            'last_failure_time': self._local_last_failure_time if isinstance(self._local_last_failure_time, (int, float)) else (self._local_last_failure_time.timestamp() if self._local_last_failure_time else 0),
            'last_success_time': self._local_last_success_time if isinstance(self._local_last_success_time, (int, float)) else (self._local_last_success_time.timestamp() if self._local_last_success_time else 0),
            'total_requests': self._local_total_requests,
            'total_failures': self._local_total_failures,
            'total_successes': self._local_total_successes
        }
    
    async def _update_stats(self, **updates):
        """Update circuit breaker statistics"""
        if self.redis:
            try:
                await self.redis.hset(self._stats_key, mapping=updates)
                await self.redis.expire(self._stats_key, 3600)  # 1 hour expiration
            except Exception as e:
                logger.warning("circuit_breaker_redis_error", name=self.name, error=str(e))
        
        # Update local stats as backup
        for key, value in updates.items():
            if hasattr(self, f'_local_{key}'):
                setattr(self, f'_local_{key}', value)
    
    async def _should_attempt_reset(self) -> bool:
        """Check if circuit breaker should attempt to reset from open to half-open"""
        stats = await self._get_stats()
        last_failure_time = stats.get('last_failure_time', 0)
        
        if last_failure_time == 0:
            return True
        
        time_since_failure = time.time() - last_failure_time
        return time_since_failure >= self.config.recovery_timeout
    
    async def _on_success(self):
        """Handle successful request"""
        now = time.time()
        state = await self._get_state()
        stats = await self._get_stats()
        
        success_count = stats.get('success_count', 0) + 1
        total_successes = stats.get('total_successes', 0) + 1
        
        await self._update_stats(
            success_count=success_count,
            failure_count=0,  # Reset failure count on success
            last_success_time=now,
            total_successes=total_successes
        )
        
        if state == CircuitState.HALF_OPEN:
            if success_count >= self.config.success_threshold:
                await self._set_state(CircuitState.CLOSED)
                logger.info("circuit_breaker_closed", name=self.name, success_count=success_count)
        elif state == CircuitState.OPEN:
            # Shouldn't happen, but handle gracefully
            await self._set_state(CircuitState.HALF_OPEN)
    
    async def _on_failure(self, exception: Exception):
        """Handle failed request"""
        now = time.time()
        stats = await self._get_stats()
        
        failure_count = stats.get('failure_count', 0) + 1
        total_failures = stats.get('total_failures', 0) + 1
        
        await self._update_stats(
            failure_count=failure_count,
            success_count=0,  # Reset success count on failure
            last_failure_time=now,
            total_failures=total_failures
        )
        
        state = await self._get_state()
        
        if failure_count >= self.config.failure_threshold:
            if state != CircuitState.OPEN:
                await self._set_state(CircuitState.OPEN)
                logger.warning(
                    "circuit_breaker_opened", 
                    name=self.name, 
                    failure_count=failure_count,
                    exception=str(exception)
                )
        elif state == CircuitState.HALF_OPEN:
            await self._set_state(CircuitState.OPEN)
            logger.warning("circuit_breaker_reopened", name=self.name, exception=str(exception))
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection
        """
        state = await self._get_state()
        stats = await self._get_stats()
        
        # Update total requests
        total_requests = stats.get('total_requests', 0) + 1
        await self._update_stats(total_requests=total_requests)
        
        if state == CircuitState.OPEN:
            if await self._should_attempt_reset():
                await self._set_state(CircuitState.HALF_OPEN)
                logger.info("circuit_breaker_half_open", name=self.name)
            else:
                next_attempt = datetime.fromtimestamp(
                    stats.get('last_failure_time', 0) + self.config.recovery_timeout
                )
                if self.config.fallback_function:
                    logger.info("circuit_breaker_fallback", name=self.name)
                    return await self._execute_with_timeout(
                        self.config.fallback_function, *args, **kwargs
                    )
                raise CircuitBreakerOpenError(self.name, next_attempt)
        
        try:
            result = await self._execute_with_timeout(func, *args, **kwargs)
            await self._on_success()
            return result
        except self.config.expected_exception as e:
            await self._on_failure(e)
            raise
        except Exception as e:
            # Unexpected exceptions don't count as failures
            logger.warning("circuit_breaker_unexpected_error", name=self.name, error=str(e))
            raise
    
    async def _execute_with_timeout(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with timeout"""
        try:
            if asyncio.iscoroutinefunction(func):
                return await asyncio.wait_for(func(*args, **kwargs), timeout=self.config.timeout)
            else:
                # Run sync function in thread pool
                loop = asyncio.get_event_loop()
                return await asyncio.wait_for(
                    loop.run_in_executor(None, functools.partial(func, *args, **kwargs)),
                    timeout=self.config.timeout
                )
        except asyncio.TimeoutError:
            raise CircuitBreakerTimeoutError(f"Function timed out after {self.config.timeout}s")
    
    async def get_stats(self) -> CircuitBreakerStats:
        """Get current circuit breaker statistics"""
        state = await self._get_state()
        stats = await self._get_stats()
        
        last_failure_time = None
        if stats.get('last_failure_time', 0) > 0:
            last_failure_time = datetime.fromtimestamp(stats['last_failure_time'])
        
        last_success_time = None
        if stats.get('last_success_time', 0) > 0:
            last_success_time = datetime.fromtimestamp(stats['last_success_time'])
        
        next_attempt_time = None
        if state == CircuitState.OPEN and last_failure_time:
            next_attempt_time = last_failure_time + timedelta(seconds=self.config.recovery_timeout)
        
        return CircuitBreakerStats(
            state=state,
            failure_count=stats.get('failure_count', 0),
            success_count=stats.get('success_count', 0),
            last_failure_time=last_failure_time,
            last_success_time=last_success_time,
            total_requests=stats.get('total_requests', 0),
            total_failures=stats.get('total_failures', 0),
            total_successes=stats.get('total_successes', 0),
            next_attempt_time=next_attempt_time
        )
    
    async def reset(self):
        """Reset circuit breaker to closed state (admin function)"""
        await self._set_state(CircuitState.CLOSED)
        await self._update_stats(
            failure_count=0,
            success_count=0,
            last_failure_time=0,
            last_success_time=0
        )
        logger.info("circuit_breaker_reset", name=self.name)


class CircuitBreakerManager:
    """Manages multiple circuit breakers"""
    
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self.redis = redis_client
        self.breakers: Dict[str, CircuitBreaker] = {}
    
    def get_or_create_breaker(
        self, 
        name: str, 
        config: Optional[CircuitBreakerConfig] = None
    ) -> CircuitBreaker:
        """Get existing circuit breaker or create new one"""
        if name not in self.breakers:
            if config is None:
                config = CircuitBreakerConfig(name=name)
            else:
                config.name = name
            
            self.breakers[name] = CircuitBreaker(config, self.redis)
            logger.info("circuit_breaker_registered", name=name)
        
        return self.breakers[name]
    
    async def get_all_stats(self) -> Dict[str, CircuitBreakerStats]:
        """Get statistics for all circuit breakers"""
        stats = {}
        for name, breaker in self.breakers.items():
            stats[name] = await breaker.get_stats()
        return stats
    
    async def reset_all(self):
        """Reset all circuit breakers (admin function)"""
        for breaker in self.breakers.values():
            await breaker.reset()
        logger.info("all_circuit_breakers_reset", count=len(self.breakers))


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 60,
    expected_exception: tuple = (Exception,),
    timeout: float = 30.0,
    fallback_function: Optional[Callable] = None,
    redis_client: Optional[aioredis.Redis] = None
):
    """
    Decorator for applying circuit breaker to functions
    """
    config = CircuitBreakerConfig(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        expected_exception=expected_exception,
        timeout=timeout,
        fallback_function=fallback_function
    )
    
    breaker = CircuitBreaker(config, redis_client)
    
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)
        return wrapper
    
    return decorator