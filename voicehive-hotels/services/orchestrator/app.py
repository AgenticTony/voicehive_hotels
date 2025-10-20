"""
VoiceHive Hotels Orchestrator Service
Production-ready orchestrator with GDPR compliance and EU region validation
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

# Import modules
from logging_adapter import get_safe_logger
from lifecycle import app_lifespan
from models import HealthCheckResponse
from config import get_config, load_config, ConfigurationError, RegionValidator
from config_drift_monitor import initialize_drift_monitoring, start_drift_monitoring
from environment_config_validator import validate_environment_config
from immutable_config_manager import create_config_version
from health import router as health_router
from routers.webhook import router as webhook_router
from routers.gdpr import router as gdpr_router
from routers.call import router as call_router
from routers.auth import router as auth_router, initialize_auth_services
from routers.resilience import router as resilience_router

# Authentication imports
from jwt_service import JWTService
from vault_client import VaultClient, MockVaultClient
from auth_middleware import AuthenticationMiddleware

# Secrets management imports
from secrets_manager import initialize_secrets_manager, get_secrets_manager
from secret_rotation_automation import initialize_rotation_orchestrator, get_rotation_orchestrator
from secret_lifecycle_manager import initialize_lifecycle_manager, get_lifecycle_manager
from secret_audit_system import initialize_audit_system, get_audit_system

# Resilience imports
from resilience_manager import initialize_resilience_for_app, get_resilience_manager
from resilience_config import get_resilience_config

# OpenTelemetry setup
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.semconv.resource import ResourceAttributes
    OTEL_AVAILABLE = True
except ImportError:
    trace = None  # type: ignore
    OTEL_AVAILABLE = False

# Configure logging
try:
    import structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
except ImportError:
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)

# Logger
logger = get_safe_logger("orchestrator")

# Initialize secure configuration system
async def initialize_secure_configuration():
    """Initialize secure configuration management system"""
    try:
        # Load configuration with strict validation
        config = load_config()
        
        # Validate environment-specific requirements
        validation_report = await validate_environment_config(config)
        
        if not validation_report.is_compliant():
            critical_violations = [v for v in validation_report.violations 
                                 if v.severity.value in ['critical', 'error']]
            if critical_violations:
                logger.critical(
                    "configuration_compliance_failed",
                    violations_count=len(critical_violations),
                    violations=[v.to_dict() for v in critical_violations]
                )
                raise ConfigurationError("Configuration compliance validation failed")
        
        # Initialize drift monitoring
        await initialize_drift_monitoring(
            environment=config.environment,
            config=config,
            approved_by="system_startup"
        )
        
        # Create immutable configuration version
        await create_config_version(
            config=config,
            created_by="system_startup",
            change_description="Initial configuration version on startup",
            tags=["startup", "system"]
        )
        
        logger.info(
            "secure_configuration_initialized",
            environment=config.environment,
            region=config.region,
            compliance_score=validation_report.compliance_score
        )
        
        return config
        
    except Exception as e:
        logger.critical(
            "secure_configuration_initialization_failed",
            error=str(e)
        )
        raise

# Create FastAPI app
app = FastAPI(
    title="VoiceHive Hotels Orchestrator",
    description="GDPR-compliant AI receptionist orchestrator with secure configuration management",
    version="1.0.0",
    lifespan=app_lifespan
)

# Configuration will be initialized during startup
app._config = None

# Middleware will be configured after secure configuration is loaded

# Initialize secure configuration first
@app.on_event("startup")
async def startup_configuration():
    """Initialize secure configuration management system on startup"""
    try:
        config = await initialize_secure_configuration()
        app._config = config

        # Initialize database
        from database.connection import initialize_database
        await initialize_database()
        logger.info("database_connection_initialized")

        # Initialize authentication services with secure configuration
        redis_url = f"redis://{config.redis.host}:{config.redis.port}/{config.redis.db}"
        jwt_service = JWTService(redis_url=redis_url)
        
        if config.environment.value == "production":
            vault_client = VaultClient(vault_url=config.external_services.vault_url)
        else:
            vault_client = MockVaultClient()  # Use mock for development
        
        # Store services in app for lifecycle management
        app._jwt_service = jwt_service
        app._vault_client = vault_client
        
        # Initialize auth services
        initialize_auth_services(jwt_service, vault_client)
        
        # Configure middleware with secure configuration
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.security.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
        
        # Add trusted host middleware for security
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        app.add_middleware(
            TrustedHostMiddleware, 
            allowed_hosts=[
                "localhost",
                "127.0.0.1",
                "*.voicehive-hotels.eu",
                "*.voicehive-hotels.com"
            ]
        )
        
        # Add authentication middleware
        app.add_middleware(AuthenticationMiddleware, jwt_service=jwt_service, vault_client=vault_client)
        
        logger.info("configuration_and_auth_services_initialized")
        
    except Exception as e:
        logger.critical("startup_configuration_failed", error=str(e))
        raise

# Initialize resilience components (rate limiting, circuit breakers, backpressure)
@app.on_event("startup")
async def startup_resilience():
    """Initialize resilience components on startup"""
    try:
        config = get_config()
        resilience_config = get_resilience_config(config.environment.value)
        await initialize_resilience_for_app(app, resilience_config, config.environment.value)
        logger.info("resilience_components_initialized", environment=config.environment.value)
    except Exception as e:
        logger.error("resilience_initialization_failed", error=str(e))
        # Continue startup even if resilience fails - components will work in degraded mode

# Initialize monitoring and observability components
@app.on_event("startup")
async def startup_monitoring():
    """Initialize monitoring and observability components on startup"""
    try:
        # Initialize enhanced alerting system
        from enhanced_alerting import enhanced_alerting, setup_default_alert_rules, setup_default_sla_targets
        
        # Setup default alert rules and SLA targets
        setup_default_alert_rules()
        setup_default_sla_targets()
        
        # Add notification channels if configured
        import os
        slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
        pagerduty_key = os.getenv("PAGERDUTY_INTEGRATION_KEY")
        
        if slack_webhook:
            from enhanced_alerting import SlackNotificationChannel
            slack_channel = SlackNotificationChannel(slack_webhook)
            enhanced_alerting.add_notification_channel(slack_channel)
            logger.info("slack_notification_channel_added")
        
        if pagerduty_key:
            from enhanced_alerting import PagerDutyNotificationChannel
            pagerduty_channel = PagerDutyNotificationChannel(pagerduty_key)
            enhanced_alerting.add_notification_channel(pagerduty_channel)
            logger.info("pagerduty_notification_channel_added")
        
        # Start the alerting system
        await enhanced_alerting.start()
        
        config = get_config()
        logger.info("monitoring_components_initialized", environment=config.environment.value)
    except Exception as e:
        logger.error("monitoring_initialization_failed", error=str(e))
        # Continue startup even if monitoring fails

# Initialize configuration drift monitoring
@app.on_event("startup")
async def startup_drift_monitoring():
    """Initialize configuration drift monitoring on startup"""
    try:
        # Start drift monitoring in background
        import asyncio
        asyncio.create_task(start_drift_monitoring())
        
        logger.info("configuration_drift_monitoring_started")
    except Exception as e:
        logger.error("drift_monitoring_initialization_failed", error=str(e))
        # Continue startup even if drift monitoring fails

@app.on_event("shutdown")
async def shutdown_monitoring():
    """Shutdown monitoring components and database"""
    try:
        from enhanced_alerting import enhanced_alerting
        await enhanced_alerting.stop()

        # Flush any pending traces
        from distributed_tracing import enhanced_tracer
        enhanced_tracer.flush_traces()

        # Close database connections
        from database.connection import close_database
        await close_database()
        logger.info("database_connections_closed")

        logger.info("monitoring_components_shutdown")
    except Exception as e:
        logger.error("monitoring_shutdown_failed", error=str(e))

# OpenTelemetry instrumentation - Following official best practices
if OTEL_AVAILABLE:
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.semconv.resource import ResourceAttributes
    
    # Configure resource with service information
    try:
        config = get_config()
        environment = config.environment.value
    except:
        environment = "unknown"
    
    resource = Resource.create({
        ResourceAttributes.SERVICE_NAME: "voicehive-orchestrator",
        ResourceAttributes.SERVICE_VERSION: "1.0.0",
        ResourceAttributes.DEPLOYMENT_ENVIRONMENT: environment,
    })
    
    # Set up tracer provider with resource
    trace.set_tracer_provider(TracerProvider(resource=resource))
    tracer = trace.get_tracer(__name__)
    
    # Configure exporters based on environment
    if ENVIRONMENT == "production":
        otlp_exporter = OTLPSpanExporter(endpoint="http://tempo:4317", insecure=True)
        span_processor = BatchSpanProcessor(otlp_exporter)
        trace.get_tracer_provider().add_span_processor(span_processor)
    
    # Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)

# Include routers
app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(gdpr_router)
app.include_router(call_router)
app.include_router(auth_router)
app.include_router(resilience_router)

# Include performance optimization router
from routers.performance import router as performance_router
app.include_router(performance_router)

# Include monitoring and observability router
from routers.monitoring import router as monitoring_router
app.include_router(monitoring_router)

# Include SLO monitoring router
from routers.slo import router as slo_router
app.include_router(slo_router)

# Health check endpoint (root level)
@app.get("/healthz", response_model=HealthCheckResponse)
async def health_check():
    """Health check endpoint with region validation"""
    services_status = {}
    
    # Check each service region
    for service in ["livekit", "twilio", "azure_openai", "elevenlabs"]:
        region = RegionValidator.get_service_region(service)
        is_valid = RegionValidator.validate_service_region(service, region)
        services_status[service] = f"{region} ({'valid' if is_valid else 'invalid'})"
    
    # Check TTS service health
    try:
        if hasattr(app.state, 'call_manager') and app.state.call_manager.tts_client:
            tts_healthy = await app.state.call_manager.tts_client.health_check()
            services_status["tts_router"] = "healthy" if tts_healthy else "unhealthy"
        else:
            services_status["tts_router"] = "not_initialized"
    except Exception:
        services_status["tts_router"] = "error"
    
    return HealthCheckResponse(
        status="healthy",
        region=REGION,
        version="1.0.0",
        gdpr_compliant=all("invalid" not in status for status in services_status.values()),
        services=services_status
    )

# Prometheus metrics endpoint - Following official FastAPI integration pattern
from prometheus_client import make_asgi_app, CollectorRegistry, multiprocess
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Import comprehensive error handling
from error_middleware import (
    ComprehensiveErrorMiddleware, 
    validation_exception_handler,
    http_exception_handler,
    generic_exception_handler
)
from correlation_middleware import CorrelationIDMiddleware
from pydantic import ValidationError as PydanticValidationError

# Import security hardening components
from input_validation_middleware import InputValidationMiddleware, ValidationConfig
from security_headers_middleware import SecurityHeadersMiddleware, get_production_security_config, get_development_security_config
from webhook_security import WebhookSecurityManager, WebhookConfig
from audit_logging import AuditLogger, get_audit_logger, AuditMiddleware
from enhanced_pii_redactor import EnhancedPIIRedactor, create_gdpr_compliant_config
from secure_config_manager import SecureConfigManager

# Initialize security components
logger.info("initializing_security_components")

# Input validation
validation_config = ValidationConfig()
if ENVIRONMENT == "development":
    # Relax some validation rules for development
    validation_config.max_string_length = 50000
    validation_config.blocked_patterns = validation_config.blocked_patterns[:3]  # Fewer patterns

# Security headers
if ENVIRONMENT == "production":
    security_headers_config = get_production_security_config()
else:
    security_headers_config = get_development_security_config()

# Webhook security
webhook_config = WebhookConfig()
webhook_security_manager = WebhookSecurityManager(webhook_config)

# Audit logging
audit_logger = get_audit_logger()

# Enhanced PII redaction
pii_config = create_gdpr_compliant_config()
enhanced_pii_redactor = EnhancedPIIRedactor(pii_config)

# Store security components in app state for access by other components
app.state.webhook_security_manager = webhook_security_manager
app.state.audit_logger = audit_logger
app.state.enhanced_pii_redactor = enhanced_pii_redactor

# Add security middleware (order matters - most specific first)
app.add_middleware(SecurityHeadersMiddleware, config=security_headers_config, environment=ENVIRONMENT)
app.add_middleware(InputValidationMiddleware, config=validation_config)
app.add_middleware(AuditMiddleware, audit_logger=audit_logger)

# Add correlation ID middleware
app.add_middleware(CorrelationIDMiddleware)

# Add comprehensive error handling middleware
app.add_middleware(ComprehensiveErrorMiddleware)

# Register specific exception handlers
app.add_exception_handler(PydanticValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

logger.info("security_components_initialized", environment=ENVIRONMENT)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "VoiceHive Hotels Orchestrator",
        "version": "1.0.0",
        "region": REGION,
        "docs": "/docs"
    }


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(
        app, 
        host=os.getenv("HOST", "0.0.0.0"), 
        port=int(os.getenv("PORT", "8080"))
    )
