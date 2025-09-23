"""
Tests for Circuit Breaker Implementation
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerManager,
    CircuitState,
    CircuitBreakerOpenError,
    CircuitBreakerTimeoutError,
    circuit_breaker
)


@pytest.fixture
async def mock_redis():
    """Mock Redis client for testing"""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock()
    redis_mock.hgetall = AsyncMock(return_value={})
    redis_mock.hset = AsyncMock()
    redis_mock.expire = AsyncMock()
    return redis_mock


@pytest.fixture
def circuit_config():
    """Default circuit breaker configuration for testing"""
    return CircuitBreakerConfig(
        name="test_circuit",
        failure_threshold=3,
        recovery_timeout=10,
        timeout=5.0,
        expected_exception=(ValueError, RuntimeError)
    )


@pytest.fixture
async def circuit_breaker_instance(mock_redis, circuit_config):
    """Circuit breaker instance for testing"""
    return CircuitBreaker(circuit_config, mock_redis)


class TestCircuitBreaker:
    """Test circuit breaker functionality"""
    
    @pytest.mark.asyncio
    async def test_initial_state_closed(self, circuit_breaker_instance):
        """Test that circuit breaker starts in closed state"""
        state = await circuit_breaker_instance._get_state()
        assert state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_successful_call(self, circuit_breaker_instance):
        """Test successful function call through circuit breaker"""
        async def success_func():
            return "success"
        
        result = await circuit_breaker_instance.call(success_func)
        assert result == "success"
        
        stats = await circuit_breaker_instance.get_stats()
        assert stats.total_requests == 1
        assert stats.total_successes == 1
        assert stats.total_failures == 0
    
    @pytest.mark.asyncio
    async def test_failure_tracking(self, circuit_breaker_instance):
        """Test that failures are tracked correctly"""
        async def failing_func():
            raise ValueError("Test error")
        
        # First failure
        with pytest.raises(ValueError):
            await circuit_breaker_instance.call(failing_func)
        
        stats = await circuit_breaker_instance.get_stats()
        assert stats.failure_count == 1
        assert stats.total_failures == 1
        assert stats.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self, circuit_breaker_instance):
        """Test that circuit opens after failure threshold is reached"""
        async def failing_func():
            raise ValueError("Test error")
        
        # Reach failure threshold (3 failures)
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker_instance.call(failing_func)
        
        stats = await circuit_breaker_instance.get_stats()
        assert stats.state == CircuitState.OPEN
        assert stats.failure_count == 3
    
    @pytest.mark.asyncio
    async def test_circuit_open_blocks_calls(self, circuit_breaker_instance):
        """Test that open circuit blocks calls"""
        async def failing_func():
            raise ValueError("Test error")
        
        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker_instance.call(failing_func)
        
        # Next call should be blocked
        async def any_func():
            return "should not execute"
        
        with pytest.raises(CircuitBreakerOpenError):
            await circuit_breaker_instance.call(any_func)
    
    @pytest.mark.asyncio
    async def test_circuit_half_open_after_timeout(self, circuit_breaker_instance, mock_redis):
        """Test that circuit goes to half-open after recovery timeout"""
        # Mock time to simulate timeout passage
        circuit_breaker_instance.config.recovery_timeout = 0.1  # 100ms for testing
        
        async def failing_func():
            raise ValueError("Test error")
        
        # Open the circuit
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker_instance.call(failing_func)
        
        # Wait for recovery timeout
        await asyncio.sleep(0.2)
        
        # Mock Redis to return old failure time
        mock_redis.hgetall = AsyncMock(return_value={
            b'failure_count': b'3',
            b'last_failure_time': str(time.time() - 1).encode()  # 1 second ago
        })
        
        async def success_func():
            return "success"
        
        # Should transition to half-open and allow call
        result = await circuit_breaker_instance.call(success_func)
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_circuit_closes_after_success_threshold(self, circuit_breaker_instance):
        """Test that half-open circuit closes after success threshold"""
        circuit_breaker_instance.config.success_threshold = 2
        
        # Manually set to half-open state
        await circuit_breaker_instance._set_state(CircuitState.HALF_OPEN)
        
        async def success_func():
            return "success"
        
        # First success
        await circuit_breaker_instance.call(success_func)
        stats = await circuit_breaker_instance.get_stats()
        assert stats.state == CircuitState.HALF_OPEN
        
        # Second success should close circuit
        await circuit_breaker_instance.call(success_func)
        stats = await circuit_breaker_instance.get_stats()
        assert stats.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self, circuit_breaker_instance):
        """Test that failure in half-open state reopens circuit"""
        # Manually set to half-open state
        await circuit_breaker_instance._set_state(CircuitState.HALF_OPEN)
        
        async def failing_func():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            await circuit_breaker_instance.call(failing_func)
        
        stats = await circuit_breaker_instance.get_stats()
        assert stats.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self, circuit_breaker_instance):
        """Test function timeout handling"""
        circuit_breaker_instance.config.timeout = 0.1  # 100ms timeout
        
        async def slow_func():
            await asyncio.sleep(0.2)  # Slower than timeout
            return "should not complete"
        
        with pytest.raises(CircuitBreakerTimeoutError):
            await circuit_breaker_instance.call(slow_func)
    
    @pytest.mark.asyncio
    async def test_fallback_function(self, mock_redis, circuit_config):
        """Test fallback function execution when circuit is open"""
        async def fallback_func(*args, **kwargs):
            return "fallback_result"
        
        circuit_config.fallback_function = fallback_func
        circuit_breaker_instance = CircuitBreaker(circuit_config, mock_redis)
        
        # Open the circuit
        async def failing_func():
            raise ValueError("Test error")
        
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker_instance.call(failing_func)
        
        # Call should use fallback
        async def any_func():
            return "should not execute"
        
        result = await circuit_breaker_instance.call(any_func)
        assert result == "fallback_result"
    
    @pytest.mark.asyncio
    async def test_unexpected_exception_not_counted(self, circuit_breaker_instance):
        """Test that unexpected exceptions don't count as failures"""
        async def unexpected_error_func():
            raise TypeError("Unexpected error")  # Not in expected_exception
        
        with pytest.raises(TypeError):
            await circuit_breaker_instance.call(unexpected_error_func)
        
        stats = await circuit_breaker_instance.get_stats()
        assert stats.failure_count == 0  # Should not increment
        assert stats.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_reset_circuit_breaker(self, circuit_breaker_instance):
        """Test resetting circuit breaker"""
        # Open the circuit
        async def failing_func():
            raise ValueError("Test error")
        
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker_instance.call(failing_func)
        
        # Reset circuit
        await circuit_breaker_instance.reset()
        
        stats = await circuit_breaker_instance.get_stats()
        assert stats.state == CircuitState.CLOSED
        assert stats.failure_count == 0
        assert stats.success_count == 0


class TestCircuitBreakerManager:
    """Test circuit breaker manager"""
    
    @pytest.mark.asyncio
    async def test_create_circuit_breaker(self, mock_redis):
        """Test creating circuit breaker through manager"""
        manager = CircuitBreakerManager(mock_redis)
        config = CircuitBreakerConfig(name="test")
        
        breaker = manager.get_or_create_breaker("test", config)
        
        assert breaker is not None
        assert "test" in manager.breakers
        assert manager.breakers["test"] == breaker
    
    @pytest.mark.asyncio
    async def test_get_existing_circuit_breaker(self, mock_redis):
        """Test getting existing circuit breaker"""
        manager = CircuitBreakerManager(mock_redis)
        config = CircuitBreakerConfig(name="test")
        
        breaker1 = manager.get_or_create_breaker("test", config)
        breaker2 = manager.get_or_create_breaker("test")  # Should return same instance
        
        assert breaker1 is breaker2
    
    @pytest.mark.asyncio
    async def test_get_all_stats(self, mock_redis):
        """Test getting stats for all circuit breakers"""
        manager = CircuitBreakerManager(mock_redis)
        
        # Create multiple breakers
        config1 = CircuitBreakerConfig(name="test1")
        config2 = CircuitBreakerConfig(name="test2")
        
        manager.get_or_create_breaker("test1", config1)
        manager.get_or_create_breaker("test2", config2)
        
        stats = await manager.get_all_stats()
        
        assert "test1" in stats
        assert "test2" in stats
        assert len(stats) == 2
    
    @pytest.mark.asyncio
    async def test_reset_all_circuit_breakers(self, mock_redis):
        """Test resetting all circuit breakers"""
        manager = CircuitBreakerManager(mock_redis)
        
        # Create and open some breakers
        config = CircuitBreakerConfig(name="test", failure_threshold=1)
        breaker = manager.get_or_create_breaker("test", config)
        
        # Cause failure to open circuit
        async def failing_func():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            await breaker.call(failing_func)
        
        # Reset all
        await manager.reset_all()
        
        stats = await breaker.get_stats()
        assert stats.state == CircuitState.CLOSED


class TestCircuitBreakerDecorator:
    """Test circuit breaker decorator"""
    
    @pytest.mark.asyncio
    async def test_decorator_success(self):
        """Test successful function call with decorator"""
        @circuit_breaker(
            name="test_decorator",
            failure_threshold=2,
            recovery_timeout=10
        )
        async def decorated_func(value):
            return f"result: {value}"
        
        result = await decorated_func("test")
        assert result == "result: test"
    
    @pytest.mark.asyncio
    async def test_decorator_failure_tracking(self):
        """Test failure tracking with decorator"""
        @circuit_breaker(
            name="test_decorator_fail",
            failure_threshold=2,
            recovery_timeout=10,
            expected_exception=(ValueError,)
        )
        async def decorated_func():
            raise ValueError("Test error")
        
        # First failure
        with pytest.raises(ValueError):
            await decorated_func()
        
        # Second failure should open circuit
        with pytest.raises(ValueError):
            await decorated_func()
        
        # Third call should be blocked
        with pytest.raises(CircuitBreakerOpenError):
            await decorated_func()


if __name__ == "__main__":
    pytest.main([__file__])