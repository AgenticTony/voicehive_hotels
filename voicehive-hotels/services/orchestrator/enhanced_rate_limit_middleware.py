"""
Enhanced Rate Limiting Middleware with Tenant-Aware Quotas
Provides per-tenant rate limiting and resource quota enforcement for VoiceHive Hotels.
"""

import asyncio
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

import redis.asyncio as redis
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.orchestrator.tenant_management import TenantManager, TenantMetadata
from services.orchestrator.logging_adapter import get_safe_logger

logger = get_safe_logger(__name__)


class RateLimitAlgorithm(str, Enum):
    """Rate limiting algorithms"""
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    TOKEN_BUCKET = "token_bucket"


class RateLimitScope(str, Enum):
    """Rate limit scope"""
    TENANT = "tenant"           # Per tenant limits
    USER = "user"              # Per user limits
    IP = "ip"                  # Per IP address limits
    ENDPOINT = "endpoint"      # Per endpoint limits
    GLOBAL = "global"          # Global system limits


class RateLimitConfig(BaseModel):
    """Enhanced rate limit configuration"""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_limit: int = 10
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.SLIDING_WINDOW

    # Tenant-specific enhancements
    scope: RateLimitScope = RateLimitScope.TENANT
    priority: int = 100  # Higher priority = evaluated first
    applies_to_roles: List[str] = []
    exclude_paths: List[str] = []

    # Grace period and warnings
    warning_threshold: float = 0.8  # Warn at 80% of limit
    grace_period_seconds: int = 0   # Grace period after limit exceeded

    # Auto-scaling
    auto_scale_enabled: bool = False
    scale_factor: float = 1.5       # Scale limit by this factor during bursts


class RateLimitResult(BaseModel):
    """Result of rate limit check"""
    allowed: bool
    limit: int
    remaining: int
    reset_time: int
    retry_after: Optional[int] = None
    scope: RateLimitScope
    tenant_id: Optional[str] = None
    warning: bool = False
    message: Optional[str] = None


class TenantRateLimitMiddleware:
    """Enhanced rate limiting middleware with tenant awareness"""

    def __init__(
        self,
        redis_client: redis.Redis,
        tenant_manager: TenantManager,
        default_config: Optional[RateLimitConfig] = None
    ):
        self.redis = redis_client
        self.tenant_manager = tenant_manager
        self.default_config = default_config or RateLimitConfig()

        # Cache for rate limit configurations
        self.config_cache: Dict[str, RateLimitConfig] = {}
        self.cache_ttl = 300  # 5 minute cache TTL

        # Default rate limit rules by endpoint pattern
        self.default_rules = self._create_default_rules()

        # Performance metrics
        self.metrics = {
            "requests_checked": 0,
            "requests_blocked": 0,
            "cache_hits": 0,
            "cache_misses": 0
        }

    def _create_default_rules(self) -> Dict[str, RateLimitConfig]:
        """Create default rate limiting rules by endpoint"""
        return {
            # Authentication endpoints - stricter limits
            r"/auth/login": RateLimitConfig(
                requests_per_minute=5,
                requests_per_hour=20,
                requests_per_day=100,
                scope=RateLimitScope.IP,
                priority=1
            ),
            r"/auth/register": RateLimitConfig(
                requests_per_minute=2,
                requests_per_hour=10,
                requests_per_day=20,
                scope=RateLimitScope.IP,
                priority=1
            ),

            # Call endpoints - higher limits for streaming
            r"/call/.*": RateLimitConfig(
                requests_per_minute=500,
                requests_per_hour=5000,
                requests_per_day=50000,
                burst_limit=50,
                scope=RateLimitScope.TENANT,
                auto_scale_enabled=True,
                priority=10
            ),

            # Webhook endpoints - moderate limits
            r"/webhook/.*": RateLimitConfig(
                requests_per_minute=100,
                requests_per_hour=1000,
                requests_per_day=10000,
                scope=RateLimitScope.TENANT,
                priority=20
            ),

            # API endpoints - standard limits
            r"/api/.*": RateLimitConfig(
                requests_per_minute=60,
                requests_per_hour=1000,
                requests_per_day=10000,
                scope=RateLimitScope.TENANT,
                priority=30
            ),

            # Health checks - very high limits
            r"/health": RateLimitConfig(
                requests_per_minute=1000,
                requests_per_hour=60000,
                requests_per_day=1000000,
                scope=RateLimitScope.GLOBAL,
                priority=100
            )
        }

    async def __call__(self, request: Request, call_next):
        """Rate limiting middleware handler"""
        start_time = time.time()

        try:
            # Check rate limits
            result = await self.check_rate_limit(request)

            if not result.allowed:
                # Request blocked by rate limit
                self.metrics["requests_blocked"] += 1

                logger.warning(
                    "rate_limit_exceeded",
                    tenant_id=result.tenant_id,
                    scope=result.scope.value,
                    path=request.url.path,
                    remaining=result.remaining,
                    reset_time=result.reset_time
                )

                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Rate limit exceeded",
                        "message": result.message or "Too many requests",
                        "retry_after": result.retry_after,
                        "limit": result.limit,
                        "remaining": result.remaining,
                        "reset_time": result.reset_time
                    },
                    headers={
                        "X-RateLimit-Limit": str(result.limit),
                        "X-RateLimit-Remaining": str(result.remaining),
                        "X-RateLimit-Reset": str(result.reset_time),
                        "Retry-After": str(result.retry_after or 60)
                    }
                )

            # Request allowed - add rate limit headers
            response = await call_next(request)

            # Add rate limit headers to response
            response.headers["X-RateLimit-Limit"] = str(result.limit)
            response.headers["X-RateLimit-Remaining"] = str(result.remaining)
            response.headers["X-RateLimit-Reset"] = str(result.reset_time)
            response.headers["X-RateLimit-Scope"] = result.scope.value

            if result.tenant_id:
                response.headers["X-RateLimit-Tenant"] = result.tenant_id

            if result.warning:
                response.headers["X-RateLimit-Warning"] = "Approaching rate limit"

            # Track successful request
            processing_time = time.time() - start_time
            await self._track_request(request, result, processing_time)

            return response

        except Exception as e:
            logger.error("rate_limit_middleware_error", error=str(e))
            # Continue processing on error - don't block requests
            return await call_next(request)

    async def check_rate_limit(self, request: Request) -> RateLimitResult:
        """Check rate limits for a request"""
        self.metrics["requests_checked"] += 1

        # Extract request context
        tenant_id = await self._extract_tenant_id(request)
        user_id = await self._extract_user_id(request)
        client_ip = self._get_client_ip(request)
        endpoint = request.url.path

        # Get applicable rate limit configuration
        config = await self._get_rate_limit_config(endpoint, tenant_id)

        # Determine rate limit key based on scope
        limit_key = self._build_rate_limit_key(config.scope, tenant_id, user_id, client_ip, endpoint)

        # Check tenant quota if applicable
        if tenant_id and config.scope == RateLimitScope.TENANT:
            quota_check = await self._check_tenant_quota(tenant_id, endpoint)
            if not quota_check.allowed:
                return quota_check

        # Perform rate limit check based on algorithm
        if config.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
            result = await self._check_sliding_window(limit_key, config)
        elif config.algorithm == RateLimitAlgorithm.FIXED_WINDOW:
            result = await self._check_fixed_window(limit_key, config)
        elif config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
            result = await self._check_token_bucket(limit_key, config)
        else:
            result = await self._check_sliding_window(limit_key, config)  # Default

        # Add context to result
        result.scope = config.scope
        result.tenant_id = tenant_id

        # Check for warnings
        if result.allowed and result.remaining <= (config.warning_threshold * result.limit):
            result.warning = True
            result.message = f"Warning: {result.remaining} requests remaining"

        return result

    async def _check_sliding_window(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Sliding window rate limiting algorithm"""
        now = time.time()
        window_start = now - 60  # 1 minute window

        pipe = self.redis.pipeline()

        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)

        # Count current requests
        pipe.zcard(key)

        # Add current request
        pipe.zadd(key, {str(now): now})

        # Set expiry
        pipe.expire(key, 120)  # 2 minute expiry

        results = await pipe.execute()
        current_count = results[1]

        # Calculate remaining requests
        limit = config.requests_per_minute
        remaining = max(0, limit - current_count - 1)  # -1 for current request

        # Calculate reset time
        reset_time = int(now + 60)

        allowed = current_count < limit
        retry_after = None if allowed else 60

        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_time=reset_time,
            retry_after=retry_after,
            scope=RateLimitScope.TENANT  # Will be overridden by caller
        )

    async def _check_fixed_window(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Fixed window rate limiting algorithm"""
        now = time.time()
        window = int(now / 60) * 60  # Current minute window
        window_key = f"{key}:{window}"

        # Increment counter for current window
        current_count = await self.redis.incr(window_key)

        # Set expiry for window
        if current_count == 1:
            await self.redis.expire(window_key, 120)

        limit = config.requests_per_minute
        remaining = max(0, limit - current_count)
        reset_time = int(window + 60)

        allowed = current_count <= limit
        retry_after = None if allowed else (reset_time - int(now))

        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_time=reset_time,
            retry_after=retry_after,
            scope=RateLimitScope.TENANT
        )

    async def _check_token_bucket(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Token bucket rate limiting algorithm"""
        now = time.time()

        # Get bucket state
        bucket_data = await self.redis.get(key)

        if bucket_data:
            bucket = json.loads(bucket_data)
            last_refill = bucket.get("last_refill", now)
            tokens = bucket.get("tokens", config.burst_limit)
        else:
            last_refill = now
            tokens = config.burst_limit

        # Refill tokens based on time elapsed
        time_elapsed = now - last_refill
        refill_rate = config.requests_per_minute / 60  # tokens per second
        tokens_to_add = time_elapsed * refill_rate
        tokens = min(config.burst_limit, tokens + tokens_to_add)

        # Check if request can be served
        allowed = tokens >= 1

        if allowed:
            tokens -= 1

        # Save bucket state
        bucket_state = {
            "tokens": tokens,
            "last_refill": now
        }
        await self.redis.setex(key, 3600, json.dumps(bucket_state))

        # Calculate reset time (when bucket will be full)
        reset_time = int(now + ((config.burst_limit - tokens) / refill_rate))
        retry_after = None if allowed else max(1, int((1 - tokens) / refill_rate))

        return RateLimitResult(
            allowed=allowed,
            limit=config.burst_limit,
            remaining=int(tokens),
            reset_time=reset_time,
            retry_after=retry_after,
            scope=RateLimitScope.TENANT
        )

    async def _check_tenant_quota(self, tenant_id: str, endpoint: str) -> RateLimitResult:
        """Check tenant-specific resource quotas"""
        # Determine resource type based on endpoint
        if "/call/" in endpoint:
            resource_type = "calls_daily"
        elif "/api/" in endpoint:
            resource_type = "api_requests"
        else:
            # No quota check needed
            return RateLimitResult(
                allowed=True,
                limit=999999,
                remaining=999999,
                reset_time=int(time.time() + 86400),
                scope=RateLimitScope.TENANT
            )

        # Check quota availability
        quota_available = await self.tenant_manager.check_quota_available(
            tenant_id, resource_type, 1
        )

        if not quota_available:
            tenant = await self.tenant_manager.get_tenant(tenant_id)
            if tenant:
                quota = tenant.resource_quota
                usage = tenant.current_usage

                if resource_type == "calls_daily":
                    limit = quota.calls_per_day
                    used = usage.calls_count
                else:
                    limit = quota.api_requests_per_hour
                    used = usage.api_requests_count

                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_time=int(time.time() + 86400),  # Reset at midnight
                    retry_after=3600,  # Try again in 1 hour
                    scope=RateLimitScope.TENANT,
                    message=f"Tenant quota exceeded for {resource_type}"
                )

        return RateLimitResult(
            allowed=True,
            limit=999999,
            remaining=999999,
            reset_time=int(time.time() + 86400),
            scope=RateLimitScope.TENANT
        )

    async def _get_rate_limit_config(self, endpoint: str, tenant_id: Optional[str]) -> RateLimitConfig:
        """Get rate limit configuration for endpoint and tenant"""
        # Check cache first
        cache_key = f"rate_config:{tenant_id}:{endpoint}"
        if cache_key in self.config_cache:
            self.metrics["cache_hits"] += 1
            return self.config_cache[cache_key]

        self.metrics["cache_misses"] += 1

        # Get tenant-specific configuration if available
        config = None
        if tenant_id:
            # This would query the tenant_rate_limits table in production
            # For now, use default configuration
            pass

        # Fall back to default rules
        if not config:
            for pattern, default_config in self.default_rules.items():
                if self._matches_pattern(endpoint, pattern):
                    config = default_config
                    break

        # Final fallback to system default
        if not config:
            config = self.default_config

        # Cache the configuration
        self.config_cache[cache_key] = config

        # Schedule cache cleanup
        asyncio.create_task(self._cleanup_cache_entry(cache_key))

        return config

    def _matches_pattern(self, endpoint: str, pattern: str) -> bool:
        """Check if endpoint matches rate limit pattern"""
        import re
        return bool(re.match(pattern, endpoint))

    def _build_rate_limit_key(
        self,
        scope: RateLimitScope,
        tenant_id: Optional[str],
        user_id: Optional[str],
        client_ip: str,
        endpoint: str
    ) -> str:
        """Build rate limit key based on scope"""
        prefix = "rate_limit"

        if scope == RateLimitScope.TENANT and tenant_id:
            return f"{prefix}:tenant:{tenant_id}"
        elif scope == RateLimitScope.USER and user_id:
            return f"{prefix}:user:{user_id}"
        elif scope == RateLimitScope.IP:
            return f"{prefix}:ip:{client_ip}"
        elif scope == RateLimitScope.ENDPOINT:
            return f"{prefix}:endpoint:{endpoint.replace('/', '_')}"
        else:
            return f"{prefix}:global"

    async def _extract_tenant_id(self, request: Request) -> Optional[str]:
        """Extract tenant ID from request"""
        # Check JWT token first
        if hasattr(request.state, "user_context") and request.state.user_context:
            user_context = request.state.user_context
            if hasattr(user_context, "hotel_ids") and user_context.hotel_ids:
                return user_context.hotel_ids[0]  # Use first hotel as default

        # Check request body for hotel_id
        if request.method == "POST":
            try:
                body = await request.body()
                if body:
                    # Reset body stream for downstream processing
                    async def receive():
                        return {"type": "http.request", "body": body}
                    request._receive = receive

                    # Parse JSON and look for hotel_id
                    try:
                        data = json.loads(body)
                        if isinstance(data, dict) and "hotel_id" in data:
                            return data["hotel_id"]
                    except json.JSONDecodeError:
                        pass
            except:
                pass

        # Check query parameters
        return request.query_params.get("hotel_id")

    async def _extract_user_id(self, request: Request) -> Optional[str]:
        """Extract user ID from request"""
        if hasattr(request.state, "user_context") and request.state.user_context:
            return getattr(request.state.user_context, "user_id", None)
        return None

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request"""
        # Check X-Forwarded-For header first (for load balancers)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        # Check X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to client IP
        return request.client.host if request.client else "unknown"

    async def _track_request(self, request: Request, result: RateLimitResult, processing_time: float):
        """Track request for analytics and monitoring"""
        # Track usage if tenant-scoped
        if result.tenant_id and result.scope == RateLimitScope.TENANT:
            try:
                await self.tenant_manager.track_resource_usage(
                    result.tenant_id,
                    "api_requests",
                    1
                )
            except Exception as e:
                logger.error("failed_to_track_usage", tenant_id=result.tenant_id, error=str(e))

        # Log metrics
        logger.debug(
            "request_processed",
            tenant_id=result.tenant_id,
            scope=result.scope.value,
            path=request.url.path,
            allowed=result.allowed,
            remaining=result.remaining,
            processing_time_ms=processing_time * 1000
        )

    async def _cleanup_cache_entry(self, cache_key: str):
        """Clean up cache entry after TTL"""
        await asyncio.sleep(self.cache_ttl)
        self.config_cache.pop(cache_key, None)

    async def get_metrics(self) -> Dict[str, Any]:
        """Get rate limiting metrics"""
        return {
            **self.metrics,
            "config_cache_size": len(self.config_cache),
            "cache_hit_rate": (
                self.metrics["cache_hits"] /
                (self.metrics["cache_hits"] + self.metrics["cache_misses"])
                if (self.metrics["cache_hits"] + self.metrics["cache_misses"]) > 0
                else 0
            ),
            "block_rate": (
                self.metrics["requests_blocked"] / self.metrics["requests_checked"]
                if self.metrics["requests_checked"] > 0
                else 0
            )
        }

    async def reset_tenant_limits(self, tenant_id: str, scope: Optional[str] = None):
        """Reset rate limits for a tenant"""
        pattern = f"rate_limit:tenant:{tenant_id}"
        if scope:
            pattern += f":{scope}"
        pattern += "*"

        # Find matching keys
        keys = []
        async for key in self.redis.scan_iter(match=pattern):
            keys.append(key)

        # Delete keys in batches
        if keys:
            for i in range(0, len(keys), 100):
                batch = keys[i:i+100]
                await self.redis.delete(*batch)

        logger.info("tenant_rate_limits_reset", tenant_id=tenant_id, keys_deleted=len(keys))

    async def update_tenant_config(self, tenant_id: str, endpoint_pattern: str, config: RateLimitConfig):
        """Update rate limit configuration for a tenant"""
        # In production, this would update the tenant_rate_limits table
        # For now, we'll invalidate the cache

        cache_pattern = f"rate_config:{tenant_id}:*"
        keys_to_remove = [key for key in self.config_cache.keys() if key.startswith(f"rate_config:{tenant_id}:")]

        for key in keys_to_remove:
            self.config_cache.pop(key, None)

        logger.info("tenant_rate_config_updated", tenant_id=tenant_id, pattern=endpoint_pattern)