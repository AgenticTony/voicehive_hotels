"""
Application lifecycle management for VoiceHive Hotels Orchestrator
Enhanced with performance optimization components
"""

import os
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from utils import PIIRedactor
from call_manager import CallManager
from logging_adapter import get_safe_logger
from config import GDPR_CONFIG, REDIS_URL, REGION, ENVIRONMENT, RegionValidator
from security import EncryptionService

# Performance optimization imports
from connection_pool_manager import (
    get_connection_pool_manager, 
    initialize_default_pools,
    ConnectionPoolConfig
)
from intelligent_cache import get_cache_manager, CacheConfig
from audio_memory_optimizer import get_audio_memory_optimizer, BufferConfig
from performance_monitor import (
    get_performance_monitor, 
    initialize_performance_monitoring,
    PerformanceConfig
)

# Use safe logger
logger = get_safe_logger("orchestrator.lifecycle")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Application lifespan manager - handles startup and shutdown with performance optimization"""
    # Startup
    logger.info("starting_orchestrator", region=REGION, environment=ENVIRONMENT)
    
    try:
        # Initialize Redis connection using connection pool manager
        # Following official Redis documentation best practices for production usage
        pool_manager = get_connection_pool_manager()
        redis_pool = await pool_manager.get_redis_pool("default")
        app.state.redis = redis_pool.redis  # Use pooled Redis client
        logger.info("redis_connection_pool_initialized", pool_name="default")
        
        # Initialize performance optimization components
        await _initialize_performance_components(app)
        
        # Initialize core services
        await _initialize_core_services(app)
        
        # Initialize authentication services
        await _initialize_auth_services(app)
        
        # Perform health checks
        await _perform_startup_health_checks(app)
        
        # Validate region configuration
        _validate_region_configuration()
        
        logger.info("orchestrator_startup_completed", region=REGION, environment=ENVIRONMENT)
        
    except Exception as e:
        logger.error("orchestrator_startup_failed", error=str(e))
        raise
    
    yield
    
    # Shutdown
    logger.info("shutting_down_orchestrator")
    
    try:
        # Shutdown performance monitoring
        if hasattr(app.state, 'performance_monitor'):
            await app.state.performance_monitor.stop_monitoring()
            logger.info("performance_monitoring_stopped")
        
        # Close audio memory optimizer
        if hasattr(app.state, 'audio_optimizer'):
            await app.state.audio_optimizer.close()
            logger.info("audio_optimizer_closed")
        
        # Close cache manager
        if hasattr(app.state, 'cache_manager'):
            await app.state.cache_manager.close_all()
            logger.info("cache_manager_closed")
        
        # Close connection pools
        if hasattr(app.state, 'connection_pool_manager'):
            await app.state.connection_pool_manager.close_all()
            logger.info("connection_pools_closed")
        
        # Close call manager and TTS client
        if hasattr(app.state, 'call_manager'):
            if hasattr(app.state.call_manager, 'tts_client'):
                await app.state.call_manager.tts_client.close()
            logger.info("call_manager_closed")
        
        # Close Redis connection
        if hasattr(app.state, 'redis'):
            await app.state.redis.close()
            logger.info("redis_connection_closed")
        
        logger.info("orchestrator_shutdown_completed")
        
    except Exception as e:
        logger.error("orchestrator_shutdown_error", error=str(e))


async def _initialize_performance_components(app: FastAPI):
    """Initialize performance optimization components"""
    logger.info("initializing_performance_components")
    
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")
    
    # Initialize connection pool manager
    pool_config = ConnectionPoolConfig(
        db_min_size=int(os.getenv("DB_POOL_MIN_SIZE", "5")),
        db_max_size=int(os.getenv("DB_POOL_MAX_SIZE", "20")),
        redis_max_connections=int(os.getenv("REDIS_POOL_MAX_CONNECTIONS", "25")),
        http_max_connections=int(os.getenv("HTTP_POOL_MAX_CONNECTIONS", "100")),
        max_memory_mb=int(os.getenv("MAX_MEMORY_MB", "512"))
    )
    
    app.state.connection_pool_manager = await initialize_default_pools(
        database_url=database_url,
        redis_url=REDIS_URL,
        config=pool_config
    )
    logger.info("connection_pools_initialized")
    
    # Initialize intelligent cache manager
    cache_config = CacheConfig(
        memory_max_size=int(os.getenv("CACHE_MEMORY_MAX_SIZE", "1000")),
        memory_max_bytes=int(os.getenv("CACHE_MEMORY_MAX_BYTES", str(50 * 1024 * 1024))),
        default_ttl_seconds=int(os.getenv("CACHE_DEFAULT_TTL", "300")),
        redis_enabled=os.getenv("CACHE_REDIS_ENABLED", "true").lower() == "true"
    )
    
    app.state.cache_manager = get_cache_manager(app.state.redis)
    
    # Create default caches
    app.state.tts_cache = app.state.cache_manager.create_cache("tts_responses", cache_config)
    app.state.pms_cache = app.state.cache_manager.create_cache("pms_data", cache_config)
    app.state.auth_cache = app.state.cache_manager.create_cache("auth_tokens", cache_config)
    
    await app.state.cache_manager.initialize_all()
    logger.info("intelligent_cache_initialized")
    
    # Initialize audio memory optimizer
    buffer_config = BufferConfig(
        max_buffer_size_mb=int(os.getenv("AUDIO_BUFFER_MAX_SIZE_MB", "10")),
        chunk_size_bytes=int(os.getenv("AUDIO_CHUNK_SIZE", "4096")),
        gc_threshold_mb=int(os.getenv("AUDIO_GC_THRESHOLD_MB", "50")),
        enable_compression=os.getenv("AUDIO_COMPRESSION_ENABLED", "true").lower() == "true"
    )
    
    app.state.audio_optimizer = get_audio_memory_optimizer(buffer_config)
    await app.state.audio_optimizer.initialize()
    logger.info("audio_memory_optimizer_initialized")
    
    # Initialize performance monitoring
    perf_config = PerformanceConfig(
        system_metrics_interval=int(os.getenv("PERF_SYSTEM_INTERVAL", "30")),
        application_metrics_interval=int(os.getenv("PERF_APP_INTERVAL", "60")),
        memory_threshold_mb=int(os.getenv("PERF_MEMORY_THRESHOLD_MB", "512")),
        cpu_threshold_percent=float(os.getenv("PERF_CPU_THRESHOLD", "80.0")),
        enable_alerting=os.getenv("PERF_ALERTING_ENABLED", "true").lower() == "true"
    )
    
    app.state.performance_monitor = await initialize_performance_monitoring(
        config=perf_config,
        redis_client=app.state.redis
    )
    logger.info("performance_monitoring_initialized")


async def _initialize_core_services(app: FastAPI):
    """Initialize core application services"""
    logger.info("initializing_core_services")
    
    # Initialize encryption
    app.state.encryption = EncryptionService()
    
    # Initialize PII redactor
    app.state.pii_redactor = PIIRedactor()
    
    # Initialize connector factory
    from connectors import ConnectorFactory
    app.state.connector_factory = ConnectorFactory()
    
    # Initialize call manager with optimized TTS client
    app.state.call_manager = CallManager(
        redis_client=app.state.redis,
        connector_factory=app.state.connector_factory
    )
    
    # Replace TTS client with enhanced version if available
    try:
        from enhanced_tts_client import create_default_tts_client
        enhanced_tts_client = await create_default_tts_client(app.state.redis)
        app.state.call_manager.tts_client = enhanced_tts_client
        logger.info("enhanced_tts_client_initialized")
    except Exception as e:
        logger.warning("enhanced_tts_client_init_failed", error=str(e))
    
    logger.info("core_services_initialized")


async def _initialize_auth_services(app: FastAPI):
    """Initialize authentication services"""
    logger.info("initializing_auth_services")
    
    # Initialize JWT service with connection pool
    if hasattr(app, '_jwt_service'):
        await app._jwt_service.initialize()
        logger.info("jwt_service_initialized")
    
    # Initialize Vault client
    if hasattr(app, '_vault_client'):
        vault_initialized = await app._vault_client.initialize()
        if vault_initialized:
            logger.info("vault_client_initialized")
        else:
            logger.warning("vault_client_initialization_failed")
    
    logger.info("auth_services_initialized")


async def _perform_startup_health_checks(app: FastAPI):
    """Perform health checks on startup"""
    logger.info("performing_startup_health_checks")
    
    # Check Redis connection
    try:
        await app.state.redis.ping()
        logger.info("redis_health_check_passed")
    except Exception as e:
        logger.error("redis_health_check_failed", error=str(e))
    
    # Check connection pools
    try:
        pool_health = await app.state.connection_pool_manager.health_check()
        logger.info("connection_pool_health_check", results=pool_health)
    except Exception as e:
        logger.error("connection_pool_health_check_failed", error=str(e))
    
    # Check cache systems
    try:
        cache_health = await app.state.cache_manager.health_check_all()
        logger.info("cache_health_check", results=cache_health)
    except Exception as e:
        logger.error("cache_health_check_failed", error=str(e))
    
    # Check TTS service
    try:
        if hasattr(app.state.call_manager, 'tts_client'):
            tts_healthy = await app.state.call_manager.tts_client.health_check()
            if tts_healthy:
                logger.info("tts_service_healthy", url=getattr(app.state.call_manager, 'tts_url', 'unknown'))
            else:
                logger.warning("tts_service_unhealthy")
    except Exception as e:
        logger.error("tts_health_check_failed", error=str(e))
    
    logger.info("startup_health_checks_completed")


def _validate_region_configuration():
    """Validate GDPR region configuration"""
    logger.info("validating_region_configuration")
    
    for service, config in GDPR_CONFIG['regions']['services'].items():
        if not RegionValidator.validate_service_region(service, config.get('region', 'unknown')):
            logger.error("invalid_region_config", service=service)
            if ENVIRONMENT == "production":
                raise ValueError(f"Invalid region configuration for {service}")
    
    logger.info("region_configuration_validated")
