"""
Rate Limiting Middleware for FastAPI
Integrates with Redis-based rate limiter and provides per-client, per-endpoint limiting
"""

import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as aioredis

from rate_limiter import RateLimiter, RateLimitConfig, RateLimitRule, RateLimitAlgorithm
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.rate_limit_middleware")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting requests
    """
    
    def __init__(
        self, 
        app,
        redis_url: str,
        default_config: Optional[RateLimitConfig] = None,
        rules: Optional[list] = None
    ):
        super().__init__(app)
        self.redis_url = redis_url
        self.redis_client: Optional[aioredis.Redis] = None
        self.rate_limiter: Optional[RateLimiter] = None
        self.default_config = default_config or RateLimitConfig()
        self.rules = rules or []
        
        # Paths to exclude from rate limiting
        self.excluded_paths = {
            "/healthz",
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc"
        }
        
        # Internal service identifiers
        self.internal_service_headers = {
            "X-Internal-Service",
            "X-Service-Token"
        }
    
    async def setup_redis(self):
        """Initialize Redis connection and rate limiter"""
        if not self.redis_client:
            try:
                self.redis_client = aioredis.from_url(
                    self.redis_url,
                    decode_responses=False,
                    max_connections=20
                )
                
                # Test connection
                await self.redis_client.ping()
                
                self.rate_limiter = RateLimiter(self.redis_client)
                
                # Add configured rules
                for rule_config in self.rules:
                    rule = RateLimitRule(**rule_config)
                    self.rate_limiter.add_rule(rule)
                
                logger.info("rate_limit_middleware_initialized", redis_url=self.redis_url)
                
            except Exception as e:
                logger.error("rate_limit_redis_connection_failed", error=str(e))
                # Continue without rate limiting if Redis is unavailable
                self.redis_client = None
                self.rate_limiter = None
    
    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting"""
        
        # Initialize Redis connection if needed
        if self.redis_client is None:
            await self.setup_redis()
        
        # Skip rate limiting if Redis is unavailable
        if self.rate_limiter is None:
            logger.warning("rate_limiting_disabled_redis_unavailable")
            return await call_next(request)
        
        # Skip rate limiting for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)
        
        # Extract client information
        client_info = await self._extract_client_info(request)
        
        # Skip rate limiting for internal services
        if client_info["client_type"] == "internal":
            return await call_next(request)
        
        try:
            # Check rate limit
            result = await self.rate_limiter.check_rate_limit(
                client_id=client_info["client_id"],
                path=request.url.path,
                method=request.method,
                client_type=client_info["client_type"]
            )
            
            # Add rate limit headers to response
            start_time = time.time()
            response = await call_next(request)
            
            # Add rate limiting headers
            self._add_rate_limit_headers(response, result)
            
            # Log rate limit info
            processing_time = time.time() - start_time
            logger.info(
                "request_processed",
                client_id=client_info["client_id"],
                path=request.url.path,
                method=request.method,
                allowed=result.allowed,
                current_usage=result.current_usage,
                remaining=result.remaining,
                processing_time=processing_time
            )
            
            return response
            
        except Exception as e:
            logger.error("rate_limit_check_failed", error=str(e))
            # Continue without rate limiting if check fails
            return await call_next(request)
    
    async def _extract_client_info(self, request: Request) -> Dict[str, str]:
        """Extract client identification information from request"""
        
        # Check for internal service headers
        for header in self.internal_service_headers:
            if header in request.headers:
                return {
                    "client_id": f"internal:{request.headers[header]}",
                    "client_type": "internal"
                }
        
        # Check for API key in Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            # For JWT tokens, we'll use a hash of the token as client ID
            import hashlib
            client_id = hashlib.sha256(token.encode()).hexdigest()[:16]
            return {
                "client_id": f"jwt:{client_id}",
                "client_type": "authenticated"
            }
        elif auth_header.startswith("ApiKey "):
            api_key = auth_header[7:]
            return {
                "client_id": f"apikey:{api_key[:16]}",
                "client_type": "api"
            }
        
        # Fall back to IP address
        client_ip = self._get_client_ip(request)
        return {
            "client_id": f"ip:{client_ip}",
            "client_type": "anonymous"
        }
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request"""
        # Check for forwarded headers (behind proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to direct connection IP
        if hasattr(request, "client") and request.client:
            return request.client.host
        
        return "unknown"
    
    def _add_rate_limit_headers(self, response: Response, result):
        """Add rate limiting headers to response"""
        response.headers["X-RateLimit-Limit"] = str(result.current_usage + result.remaining)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(result.reset_time.timestamp()))
        
        if not result.allowed and result.retry_after:
            response.headers["Retry-After"] = str(result.retry_after)


class RateLimitExceededError(HTTPException):
    """Custom exception for rate limit exceeded"""
    
    def __init__(self, result, detail: str = "Rate limit exceeded"):
        super().__init__(
            status_code=429,
            detail=detail,
            headers={
                "Retry-After": str(result.retry_after) if result.retry_after else "60",
                "X-RateLimit-Limit": str(result.current_usage + result.remaining),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(result.reset_time.timestamp()))
            }
        )


def create_rate_limit_rules() -> list:
    """Create default rate limiting rules for different endpoints"""
    
    rules = [
        # Authentication endpoints - stricter limits
        {
            "path_pattern": r"/auth/login",
            "method": "POST",
            "config": RateLimitConfig(
                requests_per_minute=5,
                requests_per_hour=20,
                requests_per_day=100,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )
        },
        
        # API endpoints - moderate limits
        {
            "path_pattern": r"/api/.*",
            "config": RateLimitConfig(
                requests_per_minute=100,
                requests_per_hour=1000,
                requests_per_day=10000,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )
        },
        
        # Webhook endpoints - higher limits for legitimate traffic
        {
            "path_pattern": r"/webhook/.*",
            "config": RateLimitConfig(
                requests_per_minute=200,
                requests_per_hour=2000,
                requests_per_day=20000,
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET
            )
        },
        
        # Call endpoints - streaming audio needs higher limits
        {
            "path_pattern": r"/call/.*",
            "config": RateLimitConfig(
                requests_per_minute=500,
                requests_per_hour=5000,
                requests_per_day=50000,
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
                burst_limit=50
            )
        },
        
        # GDPR endpoints - moderate limits
        {
            "path_pattern": r"/gdpr/.*",
            "config": RateLimitConfig(
                requests_per_minute=30,
                requests_per_hour=300,
                requests_per_day=1000,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )
        },
        
        # Anonymous users - stricter limits
        {
            "path_pattern": r".*",
            "client_type": "anonymous",
            "config": RateLimitConfig(
                requests_per_minute=20,
                requests_per_hour=200,
                requests_per_day=1000,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW
            )
        }
    ]
    
    return rules


async def rate_limit_exception_handler(request: Request, exc: RateLimitExceededError):
    """Custom exception handler for rate limit exceeded"""
    
    logger.warning(
        "rate_limit_exceeded_response",
        path=request.url.path,
        method=request.method,
        client_ip=request.headers.get("X-Forwarded-For", "unknown"),
        user_agent=request.headers.get("User-Agent", "unknown")
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": exc.detail,
                "retry_after": exc.headers.get("Retry-After"),
                "limit": exc.headers.get("X-RateLimit-Limit"),
                "reset_time": exc.headers.get("X-RateLimit-Reset")
            }
        },
        headers=exc.headers
    )