"""
VoiceHive Hotels Orchestrator Service
Production-ready orchestrator with GDPR compliance and EU region validation
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

# Import modules
from logging_adapter import get_safe_logger
from lifecycle import app_lifespan
from models import HealthCheckResponse
from config import REGION, ENVIRONMENT, RegionValidator
from health import router as health_router
from routers.webhook import router as webhook_router
from routers.gdpr import router as gdpr_router
from routers.call import router as call_router

# OpenTelemetry setup
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
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

# Create FastAPI app
app = FastAPI(
    title="VoiceHive Hotels Orchestrator",
    description="GDPR-compliant AI receptionist orchestrator",
    version="1.0.0",
    lifespan=app_lifespan
)

# Add security middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://*.voicehive-hotels.eu"],  # Only EU domains
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

# OpenTelemetry instrumentation
if ENVIRONMENT == "production" and OTEL_AVAILABLE:
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer(__name__)
    otlp_exporter = OTLPSpanExporter(endpoint="http://tempo:4317", insecure=True)
    span_processor = BatchSpanProcessor(otlp_exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)
    FastAPIInstrumentor.instrument_app(app)

# Include routers
app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(gdpr_router)
app.include_router(call_router)

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

# Metrics endpoint
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

# Error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "request_id": request.headers.get("X-Request-ID")}
    )


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
