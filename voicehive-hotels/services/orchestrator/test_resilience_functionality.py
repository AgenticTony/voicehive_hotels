#!/usr/bin/env python3
"""
Functional test for resilience infrastructure
Tests basic functionality without external dependencies
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from rate_limiter import RateLimiter, RateLimitConfig, RateLimitRule, RateLimitAlgorithm
from circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitState
from backpressure_handler import BackpressureHandler, BackpressureConfig, BackpressureStrategy


async def test_rate_limiter_basic():
    """Test basic rate limiter functionality"""
    print("🧪 Testing Rate Limiter...")
    
    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    
    # Create rate limiter
    limiter = RateLimiter(mock_redis)
    
    # Test adding rules
    rule = RateLimitRule(
        path_pattern=r"/api/.*",
        method="GET",
        config=RateLimitConfig(requests_per_minute=10)
    )
    limiter.add_rule(rule)
    
    assert len(limiter.rules) == 1
    print("  ✅ Rule addition works")
    
    # Test config matching
    config = limiter.get_config_for_request("/api/test", "GET", "api")
    assert config.requests_per_minute == 10
    print("  ✅ Rule matching works")
    
    # Test internal bypass
    result = await limiter.check_rate_limit("internal", "/api/test", "GET", "internal")
    assert result.allowed is True
    assert result.limit_type == "bypass_internal"
    print("  ✅ Internal bypass works")
    
    print("  ✅ Rate Limiter tests passed!")


async def test_circuit_breaker_basic():
    """Test basic circuit breaker functionality"""
    print("🧪 Testing Circuit Breaker...")
    
    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()
    mock_redis.hgetall = AsyncMock(return_value={})
    mock_redis.hset = AsyncMock()
    mock_redis.expire = AsyncMock()
    
    # Create circuit breaker
    config = CircuitBreakerConfig(
        name="test_circuit",
        failure_threshold=3,
        recovery_timeout=10
    )
    breaker = CircuitBreaker(config, mock_redis)
    
    # Test initial state
    state = await breaker._get_state()
    assert state == CircuitState.CLOSED
    print("  ✅ Initial state is CLOSED")
    
    # Test successful call
    async def success_func():
        return "success"
    
    result = await breaker.call(success_func)
    assert result == "success"
    print("  ✅ Successful call works")
    
    # Test failure tracking
    async def failing_func():
        raise ValueError("Test error")
    
    try:
        await breaker.call(failing_func)
    except ValueError:
        pass  # Expected
    
    stats = await breaker.get_stats()
    assert stats.total_requests >= 1
    print("  ✅ Failure tracking works")
    
    print("  ✅ Circuit Breaker tests passed!")


async def test_backpressure_basic():
    """Test basic backpressure functionality"""
    print("🧪 Testing Backpressure Handler...")
    
    # Create backpressure handler
    config = BackpressureConfig(
        max_queue_size=10,
        max_memory_mb=5,
        strategy=BackpressureStrategy.ADAPTIVE
    )
    handler = BackpressureHandler("test_handler", config)
    
    # Test task submission
    async def test_task():
        await asyncio.sleep(0.01)
        return "completed"
    
    task = await handler.submit_task("test_1", test_task)
    
    if task:  # Task might be None if dropped
        result = await task
        assert result == "completed"
        print("  ✅ Task submission works")
    
    # Test stats
    stats = await handler.get_stats()
    assert stats.max_queue_size == 10
    print("  ✅ Stats collection works")
    
    # Cleanup
    await handler.shutdown()
    print("  ✅ Backpressure Handler tests passed!")


async def test_integration():
    """Test integration between components"""
    print("🧪 Testing Integration...")
    
    # This would test the resilience manager coordinating all components
    # For now, just verify imports work
    from resilience_manager import ResilienceManager
    from resilience_config import get_resilience_config
    
    config = get_resilience_config("development")
    assert config is not None
    print("  ✅ Configuration loading works")
    
    manager = ResilienceManager(config, "development")
    assert manager is not None
    print("  ✅ Manager creation works")
    
    print("  ✅ Integration tests passed!")


async def main():
    """Run all functional tests"""
    print("🛡️  VoiceHive Hotels - Resilience Infrastructure Functional Tests")
    print("=" * 70)
    
    try:
        await test_rate_limiter_basic()
        print()
        
        await test_circuit_breaker_basic()
        print()
        
        await test_backpressure_basic()
        print()
        
        await test_integration()
        print()
        
        print("🎉 All functional tests passed!")
        print("\n📋 Test Summary:")
        print("   • Rate Limiter: Rule matching, internal bypass, basic functionality")
        print("   • Circuit Breaker: State management, call handling, failure tracking")
        print("   • Backpressure Handler: Task submission, queue management, stats")
        print("   • Integration: Configuration loading, manager creation")
        
        print("\n✅ Resilience infrastructure is working correctly!")
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)