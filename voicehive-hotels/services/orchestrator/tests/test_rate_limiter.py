"""
Tests for Rate Limiter Implementation
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from rate_limiter import (
    RateLimiter, 
    RateLimitConfig, 
    RateLimitRule, 
    RateLimitAlgorithm,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
    FixedWindowRateLimiter
)


@pytest.fixture
async def mock_redis():
    """Mock Redis client for testing"""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.pipeline = MagicMock()
    redis_mock.execute = AsyncMock(return_value=[None, 1, None, None])
    redis_mock.zremrangebyscore = AsyncMock()
    redis_mock.zcard = AsyncMock(return_value=1)
    redis_mock.zadd = AsyncMock()
    redis_mock.expire = AsyncMock()
    redis_mock.zrem = AsyncMock()
    redis_mock.incr = AsyncMock(return_value=1)
    redis_mock.decr = AsyncMock(return_value=0)
    redis_mock.eval = AsyncMock(return_value=[1, 10, 0])
    redis_mock.keys = AsyncMock(return_value=[])
    redis_mock.delete = AsyncMock()
    return redis_mock


@pytest.fixture
def rate_limit_config():
    """Default rate limit configuration for testing"""
    return RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=100,
        requests_per_day=1000,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW
    )


@pytest.fixture
async def rate_limiter(mock_redis, rate_limit_config):
    """Rate limiter instance for testing"""
    limiter = RateLimiter(mock_redis)
    limiter.default_config = rate_limit_config
    return limiter


class TestSlidingWindowRateLimiter:
    """Test sliding window rate limiter"""
    
    @pytest.mark.asyncio
    async def test_check_limit_allowed(self, mock_redis):
        """Test rate limit check when request is allowed"""
        limiter = SlidingWindowRateLimiter(mock_redis)
        
        # Mock pipeline execution
        pipeline_mock = MagicMock()
        pipeline_mock.execute = AsyncMock(return_value=[None, 5, None, None])
        mock_redis.pipeline.return_value = pipeline_mock
        
        allowed, current, remaining = await limiter.check_limit("test_key", 10, 60)
        
        assert allowed is True
        assert current == 6  # 5 + 1 for current request
        assert remaining == 4
    
    @pytest.mark.asyncio
    async def test_check_limit_exceeded(self, mock_redis):
        """Test rate limit check when limit is exceeded"""
        limiter = SlidingWindowRateLimiter(mock_redis)
        
        # Mock pipeline execution - limit exceeded
        pipeline_mock = MagicMock()
        pipeline_mock.execute = AsyncMock(return_value=[None, 10, None, None])
        mock_redis.pipeline.return_value = pipeline_mock
        
        allowed, current, remaining = await limiter.check_limit("test_key", 10, 60)
        
        assert allowed is False
        assert current == 11  # 10 + 1 for current request
        assert remaining == 0


class TestTokenBucketRateLimiter:
    """Test token bucket rate limiter"""
    
    @pytest.mark.asyncio
    async def test_check_limit_allowed(self, mock_redis):
        """Test token bucket when tokens are available"""
        limiter = TokenBucketRateLimiter(mock_redis)
        
        # Mock Lua script result - request allowed
        mock_redis.eval = AsyncMock(return_value=[1, 9, 1])
        
        allowed, current, remaining = await limiter.check_limit("test_key", 10, 0.1, 1)
        
        assert allowed is True
        assert current == 9
        assert remaining == 1
    
    @pytest.mark.asyncio
    async def test_check_limit_no_tokens(self, mock_redis):
        """Test token bucket when no tokens available"""
        limiter = TokenBucketRateLimiter(mock_redis)
        
        # Mock Lua script result - no tokens
        mock_redis.eval = AsyncMock(return_value=[0, 0, 10])
        
        allowed, current, remaining = await limiter.check_limit("test_key", 10, 0.1, 1)
        
        assert allowed is False
        assert current == 0
        assert remaining == 10


class TestFixedWindowRateLimiter:
    """Test fixed window rate limiter"""
    
    @pytest.mark.asyncio
    async def test_check_limit_allowed(self, mock_redis):
        """Test fixed window when under limit"""
        limiter = FixedWindowRateLimiter(mock_redis)
        
        mock_redis.incr = AsyncMock(return_value=5)
        
        allowed, current, remaining = await limiter.check_limit("test_key", 10, 60)
        
        assert allowed is True
        assert current == 5
        assert remaining == 5
    
    @pytest.mark.asyncio
    async def test_check_limit_exceeded(self, mock_redis):
        """Test fixed window when limit exceeded"""
        limiter = FixedWindowRateLimiter(mock_redis)
        
        mock_redis.incr = AsyncMock(return_value=11)
        mock_redis.decr = AsyncMock(return_value=10)
        
        allowed, current, remaining = await limiter.check_limit("test_key", 10, 60)
        
        assert allowed is False
        assert current == 10  # Decremented back
        assert remaining == 0


class TestRateLimiter:
    """Test main rate limiter class"""
    
    @pytest.mark.asyncio
    async def test_add_rule(self, rate_limiter):
        """Test adding rate limiting rules"""
        rule = RateLimitRule(
            path_pattern=r"/api/.*",
            method="GET",
            config=RateLimitConfig(requests_per_minute=5)
        )
        
        rate_limiter.add_rule(rule)
        
        assert len(rate_limiter.rules) == 1
        assert rate_limiter.rules[0] == rule
    
    @pytest.mark.asyncio
    async def test_get_config_for_request_matching_rule(self, rate_limiter):
        """Test getting config for request that matches a rule"""
        rule = RateLimitRule(
            path_pattern=r"/api/.*",
            method="GET",
            config=RateLimitConfig(requests_per_minute=5)
        )
        rate_limiter.add_rule(rule)
        
        config = rate_limiter.get_config_for_request("/api/test", "GET", "api")
        
        assert config.requests_per_minute == 5
    
    @pytest.mark.asyncio
    async def test_get_config_for_request_no_match(self, rate_limiter):
        """Test getting config for request that doesn't match any rule"""
        config = rate_limiter.get_config_for_request("/other", "GET", "api")
        
        assert config == rate_limiter.default_config
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_internal_bypass(self, rate_limiter):
        """Test rate limit bypass for internal services"""
        result = await rate_limiter.check_rate_limit(
            "internal_service", "/api/test", "GET", "internal"
        )
        
        assert result.allowed is True
        assert result.limit_type == "bypass_internal"
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(self, rate_limiter, mock_redis):
        """Test rate limit check when request is allowed"""
        # Mock sliding window limiter
        rate_limiter.sliding_window.check_limit = AsyncMock(return_value=(True, 1, 9))
        
        result = await rate_limiter.check_rate_limit(
            "test_client", "/api/test", "GET", "api"
        )
        
        assert result.allowed is True
        assert result.current_usage == 1
        assert result.remaining == 9
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_exceeded(self, rate_limiter, mock_redis):
        """Test rate limit check when limit is exceeded"""
        # Mock sliding window limiter - limit exceeded
        rate_limiter.sliding_window.check_limit = AsyncMock(return_value=(False, 11, 0))
        
        result = await rate_limiter.check_rate_limit(
            "test_client", "/api/test", "GET", "api"
        )
        
        assert result.allowed is False
        assert result.current_usage == 11
        assert result.remaining == 0
        assert result.retry_after is not None
    
    @pytest.mark.asyncio
    async def test_get_client_stats(self, rate_limiter, mock_redis):
        """Test getting client statistics"""
        mock_redis.keys = AsyncMock(return_value=[
            b"rate_limit:client1:/api/test:minute",
            b"rate_limit:client1:/api/other:minute"
        ])
        mock_redis.zcard = AsyncMock(return_value=5)
        
        stats = await rate_limiter.get_client_stats("client1")
        
        assert "minute" in stats
        assert "/api/test" in stats["minute"]
        assert stats["minute"]["/api/test"] == 5
    
    @pytest.mark.asyncio
    async def test_reset_client_limits(self, rate_limiter, mock_redis):
        """Test resetting client rate limits"""
        mock_redis.keys = AsyncMock(return_value=[
            b"rate_limit:client1:/api/test:minute",
            b"rate_limit:client1:/api/test:hour"
        ])
        
        await rate_limiter.reset_client_limits("client1", "/api/test")
        
        mock_redis.delete.assert_called_once()


class TestRateLimitRule:
    """Test rate limit rule matching"""
    
    def test_matches_rule_path_only(self):
        """Test rule matching with path pattern only"""
        from rate_limiter import RateLimiter
        
        limiter = RateLimiter(None)
        rule = RateLimitRule(
            path_pattern=r"/api/.*",
            config=RateLimitConfig()
        )
        
        assert limiter._matches_rule(rule, "/api/test", "GET", "api") is True
        assert limiter._matches_rule(rule, "/other", "GET", "api") is False
    
    def test_matches_rule_with_method(self):
        """Test rule matching with method constraint"""
        from rate_limiter import RateLimiter
        
        limiter = RateLimiter(None)
        rule = RateLimitRule(
            path_pattern=r"/api/.*",
            method="POST",
            config=RateLimitConfig()
        )
        
        assert limiter._matches_rule(rule, "/api/test", "POST", "api") is True
        assert limiter._matches_rule(rule, "/api/test", "GET", "api") is False
    
    def test_matches_rule_with_client_type(self):
        """Test rule matching with client type constraint"""
        from rate_limiter import RateLimiter
        
        limiter = RateLimiter(None)
        rule = RateLimitRule(
            path_pattern=r".*",
            client_type="anonymous",
            config=RateLimitConfig()
        )
        
        assert limiter._matches_rule(rule, "/api/test", "GET", "anonymous") is True
        assert limiter._matches_rule(rule, "/api/test", "GET", "authenticated") is False


if __name__ == "__main__":
    pytest.main([__file__])