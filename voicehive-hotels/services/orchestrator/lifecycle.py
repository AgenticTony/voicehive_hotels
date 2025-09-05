"""
Application lifecycle management for VoiceHive Hotels Orchestrator
"""

from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from utils import PIIRedactor
from call_manager import CallManager
from logging_adapter import get_safe_logger
from config import GDPR_CONFIG, REDIS_URL, REGION, ENVIRONMENT, RegionValidator
from security import EncryptionService

# Use safe logger
logger = get_safe_logger("orchestrator.lifecycle")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Application lifespan manager - handles startup and shutdown"""
    # Startup
    logger.info("starting_orchestrator", region=REGION, environment=ENVIRONMENT)
    
    # Initialize Redis
    app.state.redis = await redis.from_url(REDIS_URL)
    
    # Initialize encryption
    app.state.encryption = EncryptionService()
    
    # Initialize PII redactor
    app.state.pii_redactor = PIIRedactor()
    
    # Initialize connector factory
    from connectors import ConnectorFactory
    app.state.connector_factory = ConnectorFactory()
    
    # Initialize call manager
    app.state.call_manager = CallManager(
        redis_client=app.state.redis,
        connector_factory=app.state.connector_factory
    )
    
    # Check TTS service health
    try:
        tts_healthy = await app.state.call_manager.tts_client.health_check()
        if tts_healthy:
            logger.info("tts_service_healthy", url=app.state.call_manager.tts_url)
        else:
            logger.warning("tts_service_unhealthy", url=app.state.call_manager.tts_url)
    except Exception as e:
        logger.error("tts_health_check_failed", error=str(e))
    
    # Validate region configuration
    for service, config in GDPR_CONFIG['regions']['services'].items():
        if not RegionValidator.validate_service_region(service, config.get('region', 'unknown')):
            logger.error("invalid_region_config", service=service)
            if ENVIRONMENT == "production":
                raise ValueError(f"Invalid region configuration for {service}")
    
    yield
    
    # Shutdown
    logger.info("shutting_down_orchestrator")
    try:
        if hasattr(app.state, 'call_manager') and getattr(app.state.call_manager, 'tts_client', None):
            await app.state.call_manager.tts_client.close()
    except Exception as e:
        logger.warning("tts_client_close_error", error=str(e))
    await app.state.redis.close()
