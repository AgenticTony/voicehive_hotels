"""
Shared dependencies for FastAPI endpoints
"""

from fastapi import HTTPException, Request, Header
import redis.asyncio as redis


async def verify_api_key(x_api_key: str = Header(...)) -> str:
    """Verify API key and extract hotel information"""
    # In production, validate against Vault or database
    if not x_api_key.startswith("vh_"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key


async def get_redis(request: Request) -> redis.Redis:
    """Get Redis client from app state"""
    return request.app.state.redis
