"""
Shared dependencies for FastAPI endpoints
"""

from fastapi import HTTPException, Request, Header, Depends
import redis.asyncio as redis

from production_vault_client import ProductionVaultClient, get_production_vault_client
from auth_models import ServiceContext
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.core.dependencies")


async def verify_api_key(
    x_api_key: str = Header(...),
    vault_client: ProductionVaultClient = Depends(get_production_vault_client)
) -> ServiceContext:
    """Verify API key against Vault and return service context"""
    try:
        # Validate API key format first (quick check)
        if not x_api_key.startswith("vh_"):
            logger.warning("invalid_api_key_format", api_key_prefix=x_api_key[:10])
            raise HTTPException(status_code=401, detail="Invalid API key format")

        # Validate against Vault (production validation)
        service_context = await vault_client.validate_api_key(x_api_key)

        logger.info("api_key_validated",
                   service_name=service_context.service_name,
                   permissions_count=len(service_context.permissions))

        return service_context

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error("api_key_validation_error", error=str(e))
        raise HTTPException(status_code=401, detail="API key validation failed")


async def get_redis(request: Request) -> redis.Redis:
    """Get Redis client from app state"""
    return request.app.state.redis
