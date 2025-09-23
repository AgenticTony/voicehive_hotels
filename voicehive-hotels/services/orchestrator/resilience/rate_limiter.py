"""
Redis-based Rate Limiting Implementation
Supports sliding window, token bucket, and fixed window algorithms
"""

import asyncio
import time
from typing import Dict, Optional, Tuple, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timedelta

import redis.asyncio as aioredis
from pydantic import BaseModel

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.rate_limiter")


class RateLimitAlgorithm(str, Enum):
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitConfig:
    """Rate limiting configuration"""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_limit: int = 10
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW
    bypass_internal: bool = True


class RateLimitResult(BaseModel):
    """Rate limiting result"""
    allowed: bool
    current_usage: int
    remaining: int
    reset_time: datetime
    retry_after: Optional[int] = None
    limit_type: str = "requests_per_minute"


class RateLimitRule(BaseModel):
    """Rate limiting rule configuration"""
    path_pattern: str
    method: Optional[str] = None
    client_type: Optional[str] = None
    config: RateLimitConfig


class SlidingWindowRateLimiter:
    """Redis-based sliding window rate limiter"""
    
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
    
    async def check_limit(
        self, 
        key: str, 
        limit: int, 
        window_seconds: int
    ) -> Tuple[bool, int, int]:
        """
        Check rate limit using sliding window algorithm
        Returns: (allowed, current_count, remaining)
        """
        now = time.time()
        window_start = now - window_seconds
        
        # Use Redis pipeline for atomic operations
        pipe = self.redis.pipeline()
        
        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)
        
        # Count current requests in window
        pipe.zcard(key)
        
        # Add current request
        pipe.zadd(key, {str(now): now})
        
        # Set expiration
        pipe.expire(key, window_seconds)
        
        results = await pipe.execute()
        current_count = results[1] + 1  # +1 for the request we just added
        
        allowed = current_count <= limit
        remaining = max(0, limit - current_count)
        
        if not allowed:
            # Remove the request we just added since it's not allowed
            await self.redis.zrem(key, str(now))
        
        return allowed, current_count, remaining


class TokenBucketRateLimiter:
    """Redis-based token bucket rate limiter"""
    
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
    
    async def check_limit(
        self, 
        key: str, 
        capacity: int, 
        refill_rate: float,
        tokens_requested: int = 1
    ) -> Tuple[bool, int, int]:
        """
        Check rate limit using token bucket algorithm
        Returns: (allowed, current_tokens, remaining_tokens)
        """
        now = time.time()
        
        # Lua script for atomic token bucket operations
        lua_script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local tokens_requested = tonumber(ARGV[3])
        local now = tonumber(ARGV[4])
        
        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1]) or capacity
        local last_refill = tonumber(bucket[2]) or now
        
        -- Calculate tokens to add based on time elapsed
        local time_elapsed = now - last_refill
        local tokens_to_add = time_elapsed * refill_rate
        tokens = math.min(capacity, tokens + tokens_to_add)
        
        local allowed = tokens >= tokens_requested
        if allowed then
            tokens = tokens - tokens_requested
        end
        
        -- Update bucket state
        redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
        redis.call('EXPIRE', key, 3600)  -- 1 hour expiration
        
        return {allowed and 1 or 0, math.floor(tokens), capacity - math.floor(tokens)}
        """
        
        result = await self.redis.eval(
            lua_script, 
            1, 
            key, 
            capacity, 
            refill_rate, 
            tokens_requested, 
            now
        )
        
        allowed = bool(result[0])
        current_tokens = int(result[1])
        used_tokens = int(result[2])
        
        return allowed, current_tokens, capacity - used_tokens


class FixedWindowRateLimiter:
    """Redis-based fixed window rate limiter"""
    
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
    
    async def check_limit(
        self, 
        key: str, 
        limit: int, 
        window_seconds: int
    ) -> Tuple[bool, int, int]:
        """
        Check rate limit using fixed window algorithm
        Returns: (allowed, current_count, remaining)
        """
        now = time.time()
        window_start = int(now // window_seconds) * window_seconds
        window_key = f"{key}:{window_start}"
        
        # Increment counter atomically
        current_count = await self.redis.incr(window_key)
        
        # Set expiration on first request in window
        if current_count == 1:
            await self.redis.expire(window_key, window_seconds)
        
        allowed = current_count <= limit
        remaining = max(0, limit - current_count)
        
        if not allowed:
            # Decrement since request is not allowed
            await self.redis.decr(window_key)
            current_count -= 1
        
        return allowed, current_count, remaining


class RateLimiter:
    """Main rate limiter class that coordinates different algorithms"""
    
    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self.sliding_window = SlidingWindowRateLimiter(redis_client)
        self.token_bucket = TokenBucketRateLimiter(redis_client)
        self.fixed_window = FixedWindowRateLimiter(redis_client)
        
        # Default rate limiting rules
        self.rules: List[RateLimitRule] = []
        self.default_config = RateLimitConfig()
    
    def add_rule(self, rule: RateLimitRule):
        """Add a rate limiting rule"""
        self.rules.append(rule)
        logger.info("rate_limit_rule_added", pattern=rule.path_pattern, config=rule.config)
    
    def get_config_for_request(self, path: str, method: str, client_type: str) -> RateLimitConfig:
        """Get rate limiting configuration for a specific request"""
        for rule in self.rules:
            if self._matches_rule(rule, path, method, client_type):
                return rule.config
        return self.default_config
    
    def _matches_rule(self, rule: RateLimitRule, path: str, method: str, client_type: str) -> bool:
        """Check if a request matches a rate limiting rule"""
        import re
        
        # Check path pattern
        if not re.match(rule.path_pattern, path):
            return False
        
        # Check method if specified
        if rule.method and rule.method.upper() != method.upper():
            return False
        
        # Check client type if specified
        if rule.client_type and rule.client_type != client_type:
            return False
        
        return True
    
    async def check_rate_limit(
        self, 
        client_id: str, 
        path: str, 
        method: str = "GET",
        client_type: str = "api"
    ) -> RateLimitResult:
        """
        Check rate limit for a request
        """
        config = self.get_config_for_request(path, method, client_type)
        
        # Skip rate limiting for internal services if configured
        if config.bypass_internal and client_type == "internal":
            return RateLimitResult(
                allowed=True,
                current_usage=0,
                remaining=999999,
                reset_time=datetime.now() + timedelta(minutes=1),
                limit_type="bypass_internal"
            )
        
        # Check different time windows
        checks = [
            ("minute", config.requests_per_minute, 60),
            ("hour", config.requests_per_hour, 3600),
            ("day", config.requests_per_day, 86400)
        ]
        
        for window_name, limit, window_seconds in checks:
            if limit <= 0:  # Skip if limit is 0 or negative
                continue
                
            key = f"rate_limit:{client_id}:{path}:{window_name}"
            
            if config.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                allowed, current, remaining = await self.sliding_window.check_limit(
                    key, limit, window_seconds
                )
            elif config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                refill_rate = limit / window_seconds
                allowed, current, remaining = await self.token_bucket.check_limit(
                    key, limit, refill_rate
                )
            else:  # FIXED_WINDOW
                allowed, current, remaining = await self.fixed_window.check_limit(
                    key, limit, window_seconds
                )
            
            if not allowed:
                retry_after = self._calculate_retry_after(window_seconds, current, limit)
                reset_time = datetime.now() + timedelta(seconds=retry_after)
                
                logger.warning(
                    "rate_limit_exceeded",
                    client_id=client_id,
                    path=path,
                    window=window_name,
                    current=current,
                    limit=limit
                )
                
                return RateLimitResult(
                    allowed=False,
                    current_usage=current,
                    remaining=0,
                    reset_time=reset_time,
                    retry_after=retry_after,
                    limit_type=f"requests_per_{window_name}"
                )
        
        # If we get here, all checks passed
        return RateLimitResult(
            allowed=True,
            current_usage=1,
            remaining=config.requests_per_minute - 1,
            reset_time=datetime.now() + timedelta(minutes=1),
            limit_type="requests_per_minute"
        )
    
    def _calculate_retry_after(self, window_seconds: int, current: int, limit: int) -> int:
        """Calculate retry-after time in seconds"""
        if window_seconds <= 60:  # For minute windows
            return 60
        elif window_seconds <= 3600:  # For hour windows
            return 300  # 5 minutes
        else:  # For day windows
            return 3600  # 1 hour
    
    async def get_client_stats(self, client_id: str) -> Dict[str, Dict]:
        """Get current rate limiting stats for a client"""
        stats = {}
        
        for window_name, window_seconds in [("minute", 60), ("hour", 3600), ("day", 86400)]:
            key_pattern = f"rate_limit:{client_id}:*:{window_name}"
            keys = await self.redis.keys(key_pattern)
            
            window_stats = {}
            for key in keys:
                path = key.decode().split(':')[2]  # Extract path from key
                count = await self.redis.zcard(key) if window_seconds <= 3600 else await self.redis.get(key)
                window_stats[path] = int(count) if count else 0
            
            stats[window_name] = window_stats
        
        return stats
    
    async def reset_client_limits(self, client_id: str, path: Optional[str] = None):
        """Reset rate limits for a client (admin function)"""
        if path:
            pattern = f"rate_limit:{client_id}:{path}:*"
        else:
            pattern = f"rate_limit:{client_id}:*"
        
        keys = await self.redis.keys(pattern)
        if keys:
            await self.redis.delete(*keys)
            logger.info("rate_limits_reset", client_id=client_id, path=path, keys_deleted=len(keys))