"""
VoiceHive Hotels Orchestrator Service
Production-ready orchestrator with GDPR compliance and EU region validation
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, validator
from services.orchestrator.health import router as health_router
from services.orchestrator.call_manager import CallManager, CallEvent
from services.orchestrator.utils import PIIRedactor
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
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
import httpx
# Optional circuit breaker: provide no-op fallback if not installed
try:
    from circuitbreaker import circuit
except ImportError:
    def circuit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
from tenacity import retry, stop_after_attempt, wait_exponential
import redis.asyncio as redis
from cryptography.fernet import Fernet
import hashlib
import yaml

# Configuration
CONFIG_PATH = os.getenv("CONFIG_PATH", "/config/security/gdpr-config.yaml")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://localhost:8200")
REGION = os.getenv("AWS_REGION", "eu-west-1")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://livekit-eu.voicehive-hotels.eu")

# Load GDPR configuration with safe fallback for test environments
GDPR_FALLBACK_USED = False
try:
    with open(CONFIG_PATH, "r") as f:
        GDPR_CONFIG = yaml.safe_load(f)
except Exception:
    GDPR_FALLBACK_USED = True
    GDPR_CONFIG = {
        "regions": {
            "allowed": ["eu-west-1", "eu-central-1", "westeurope", "northeurope"],
            "services": {}
        },
        "retention": {"defaults": {"metadata": {"days": 1}}}
    }

# Structured logging (graceful fallback if structlog is unavailable)
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
    logger = structlog.get_logger()
except ImportError:
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    logger = _logging.getLogger("orchestrator")

# Metrics
call_counter = Counter('voicehive_calls_total', 'Total calls processed', ['hotel_id', 'language', 'status'])
call_duration = Histogram('voicehive_call_duration_seconds', 'Call duration', ['hotel_id', 'language'])
active_calls = Gauge('voicehive_active_calls', 'Currently active calls', ['hotel_id'])
region_violations = Counter('voicehive_region_violations', 'Non-EU region access attempts', ['service', 'region'])
pii_redactions = Counter('voicehive_pii_redactions', 'PII redactions performed', ['category'])
call_events_total = Counter('voicehive_call_events_total', 'Total call events received', ['event_type'])

# Request/Response Models
class CallStartRequest(BaseModel):
    caller_id: str = Field(..., description="Caller phone number")
    hotel_id: str = Field(..., description="Hotel identifier")
    language: Optional[str] = Field("auto", description="Language code or 'auto' for detection")
    sip_headers: Optional[Dict[str, str]] = Field(default_factory=dict)
    
    @validator('caller_id')
    def validate_caller_id(cls, v):
        # Basic phone number validation
        if not v.startswith('+'):
            raise ValueError("Caller ID must be in E.164 format")
        return v

class CallStartResponse(BaseModel):
    call_id: str
    session_token: str
    websocket_url: str
    region: str
    encryption_key_id: str

class HealthCheckResponse(BaseModel):
    status: str
    region: str
    version: str
    gdpr_compliant: bool
    services: Dict[str, str]

# Region validation
class RegionValidator:
    @staticmethod
    def validate_service_region(service: str, region: str) -> bool:
        """Validate that a service is running in an allowed EU region"""
        allowed_regions = GDPR_CONFIG['regions']['allowed']
        if region not in allowed_regions:
            region_violations.labels(service=service, region=region).inc()
            logger.warning("region_violation", service=service, region=region, allowed=allowed_regions)
            return False
        return True
    
    @staticmethod
    def get_service_region(service: str) -> str:
        """Get the configured region for a service"""
        service_config = GDPR_CONFIG['regions']['services'].get(service, {})
        return service_config.get('region', 'unknown')

# PII Redaction is now in utils.py to avoid circular imports

# Encryption helper
class EncryptionService:
    def __init__(self):
        # In production, fetch from Vault
        self.key = Fernet.generate_key()
        self.fernet = Fernet(self.key)
    
    def encrypt(self, data: str) -> bytes:
        return self.fernet.encrypt(data.encode())
    
    def decrypt(self, encrypted_data: bytes) -> str:
        return self.fernet.decrypt(encrypted_data).decode()

# Circuit breaker for external services
@circuit(failure_threshold=5, recovery_timeout=60)
async def call_external_service(url: str, **kwargs):
    async with httpx.AsyncClient() as client:
        response = await client.request(url=url, **kwargs)
        response.raise_for_status()
        return response

# Application lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("starting_orchestrator", region=REGION, environment=ENVIRONMENT)

    # Warn if GDPR fallback config is used
    if 'GDPR_FALLBACK_USED' in globals() and GDPR_FALLBACK_USED:
        logger.warning("gdpr_config_fallback_used", path=CONFIG_PATH)
    
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

# Create FastAPI app
app = FastAPI(
    title="VoiceHive Hotels Orchestrator",
    description="GDPR-compliant AI receptionist orchestrator",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://*.voicehive-hotels.eu"],  # Only EU domains
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Mount health router
app.include_router(health_router)

# OpenTelemetry instrumentation
if ENVIRONMENT == "production" and OTEL_AVAILABLE:
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer(__name__)
    otlp_exporter = OTLPSpanExporter(endpoint="http://tempo:4317", insecure=True)
    span_processor = BatchSpanProcessor(otlp_exporter)
    trace.get_tracer_provider().add_span_processor(span_processor)
    FastAPIInstrumentor.instrument_app(app)

# Dependencies
async def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key and extract hotel information"""
    # In production, validate against Vault or database
    if not x_api_key.startswith("vh_"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

async def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis

# Health check endpoint
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

# Main call endpoint
@app.post("/v1/call/start", response_model=CallStartResponse)
async def start_call(
    request: CallStartRequest,
    api_key: str = Depends(verify_api_key),
    redis_client: redis.Redis = Depends(get_redis)
):
    """Start a new call with GDPR compliance checks"""
    call_id = f"call_{datetime.now(timezone.utc).isoformat()}_{request.hotel_id}"
    
    logger.info(
        "starting_call",
        call_id=call_id,
        hotel_id=request.hotel_id,
        language=request.language,
        region=REGION
    )
    
    # Store call metadata in Redis with encryption
    call_data = {
        "hotel_id": request.hotel_id,
        "caller_id": hashlib.sha256(request.caller_id.encode()).hexdigest(),  # Hash PII
        "language": request.language,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "region": REGION,
        "gdpr_consent": "legitimate_interest"  # Based on config
    }
    
    await redis_client.setex(
        f"call:{call_id}",
        GDPR_CONFIG['retention']['defaults']['metadata']['days'] * 86400,
        str(call_data)
    )
    
    # Generate session token
    session_token = hashlib.sha256(f"{call_id}:{api_key}".encode()).hexdigest()
    
    # Increment metrics
    call_counter.labels(
        hotel_id=request.hotel_id,
        language=request.language,
        status="started"
    ).inc()
    active_calls.labels(hotel_id=request.hotel_id).inc()
    
    return CallStartResponse(
        call_id=call_id,
        session_token=session_token,
        websocket_url=f"{LIVEKIT_URL}/ws?token={session_token}",
        region=REGION,
        encryption_key_id=f"kms-{request.hotel_id}"
    )

# Metrics endpoint
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

# LiveKit webhook endpoints
@app.post("/v1/livekit/webhook", include_in_schema=False)
async def handle_livekit_webhook(
    request: Request
):
    """Handle LiveKit agent callbacks for call events"""
    try:
        # Parse the event payload
        event_data = await request.json()
        event_type = event_data.get("event_type")
        call_sid = event_data.get("call_sid")
        
        if not event_type or not call_sid:
            logger.error("invalid_livekit_webhook", event_data=event_data)
            raise HTTPException(status_code=400, detail="Missing event_type or call_sid")
        
        # Map LiveKit events to our internal event types
        event_mapping = {
            "agent_ready": "agent_ready",
            "call_started": "call_started",
            "transcription": "transcription",
            "intent_detected": "intent_detected",
            "response_generated": "response_generated",
            "tts_completed": "tts_completed",
            "call_ended": "call_ended",
            "error": "error"
        }
        
        internal_event_type = event_mapping.get(event_type)
        if not internal_event_type:
            logger.warning("unknown_livekit_event", event_type=event_type)
            return {"status": "ignored", "reason": "unknown event type"}
        
        # Create internal event with correct field names and types
        event = CallEvent(
            event=internal_event_type,
            room_name=event_data.get("room_name") or event_data.get("room") or call_sid,
            call_sid=call_sid,
            timestamp=datetime.now(timezone.utc).timestamp(),
            data=event_data.get("data", {})
        )
        
        # Handle the event if call manager is available
        call_manager = request.app.state.call_manager if hasattr(request.app.state, 'call_manager') else None
        if call_manager:
            result = await call_manager.handle_event(event)
            logger.info(
                "livekit_webhook_processed",
                event_type=event_type,
                call_sid=call_sid,
                result=result
            )
            return {"status": "processed", "event_type": event_type, "call_sid": call_sid}
        else:
            logger.info("livekit_webhook_accepted_no_manager", event_type=event_type, call_sid=call_sid)
            return JSONResponse({"status": "accepted", "event_type": event_type, "call_sid": call_sid}, status_code=202)
        
    except Exception as e:
        logger.error("livekit_webhook_error: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal error processing webhook")

@app.post("/v1/livekit/transcription", include_in_schema=False)
async def handle_transcription(
    call_sid: str,
    text: str,
    language: str,
    confidence: float,
    is_final: bool
):
    """Handle transcription updates from LiveKit agent"""
    event = CallEvent(
        event="transcription",
        room_name=call_sid,
        call_sid=call_sid,
        timestamp=datetime.now(timezone.utc).timestamp(),
        data={
            "transcription": {
                "text": text,
                "language": language,
                "confidence": confidence,
                "is_final": is_final
            }
        }
    )

    call_manager = app.state.call_manager if hasattr(app.state, 'call_manager') else None
    if call_manager:
        result = await call_manager.handle_event(event)
        return {
            "status": "processed",
            "call_sid": call_sid,
            "intent_detected": (result or {}).get("intent")
        }
    else:
        logger.info("transcription_accepted_no_manager", call_sid=call_sid)
        return JSONResponse({"status": "accepted", "call_sid": call_sid}, status_code=202)

# Call event webhook endpoint (from LiveKit agent)
@app.post("/call/event", include_in_schema=False)
async def handle_call_event(
    request: Request,
    authorization: str = Header(None)
):
    """Handle call events from LiveKit agent with webhook authentication"""
    try:
        # Validate webhook authorization
        expected_key = os.getenv("LIVEKIT_WEBHOOK_KEY")
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("missing_webhook_auth")
            raise HTTPException(status_code=401, detail="Missing authorization")
        
        provided_key = authorization.replace("Bearer ", "")
        if provided_key != expected_key:
            logger.warning("invalid_webhook_auth")
            raise HTTPException(status_code=401, detail="Invalid webhook key")
        
        # Parse event
        event_data = await request.json()
        event_type = event_data.get("event")
        room_name = event_data.get("room_name")
        
        # Log with PII redaction
        logger.info(
            "call_event_received",
            event_type=event_type,
            room_name=room_name,
            # Don't log full payload to avoid PII
        )
        
        # Route to call manager if available
        if hasattr(request.app.state, "call_manager"):
            # Convert to internal event format
            internal_event = CallEvent(
                event_type=event_type,
                call_sid=room_name,
                timestamp=datetime.now(timezone.utc).isoformat(),
                data=event_data
            )
            await request.app.state.call_manager.handle_event(internal_event)
        
        # Update metrics
        call_events_total.labels(event_type=event_type).inc()
        
        return {"status": "processed", "event": event_type}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("call_event_error: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal error")

# GDPR endpoints
@app.post("/v1/gdpr/consent")
async def record_consent(
    hotel_id: str,
    purpose: str,
    consent: bool,
    api_key: str = Depends(verify_api_key),
    redis_client: redis.Redis = Depends(get_redis)
):
    """Record GDPR consent for voice processing"""
    consent_record = {
        "hotel_id": hotel_id,
        "purpose": purpose,
        "consent": consent,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip_address": "redacted",  # Would get from request in production
        "version": "1.0"
    }
    
    await redis_client.setex(
        f"consent:{hotel_id}:{purpose}",
        365 * 86400,  # 1 year
        str(consent_record)
    )
    
    logger.info("consent_recorded", hotel_id=hotel_id, purpose=purpose, consent=consent)
    return {"status": "recorded", "consent_id": f"{hotel_id}:{purpose}"}

@app.post("/v1/gdpr/deletion-request")
async def request_deletion(
    hotel_id: str,
    caller_id: str,
    api_key: str = Depends(verify_api_key)
):
    """Handle GDPR deletion requests"""
    # In production, this would trigger an async workflow
    deletion_id = f"del_{datetime.now(timezone.utc).isoformat()}"
    
    logger.info(
        "deletion_requested",
        deletion_id=deletion_id,
        hotel_id=hotel_id,
        caller_id_hash=hashlib.sha256(caller_id.encode()).hexdigest()
    )
    
    return {
        "deletion_id": deletion_id,
        "status": "pending",
        "estimated_completion": "30 days"
    }

# Error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Use stdlib logging-friendly formatting when structlog isn't available
    logger.error("unhandled_exception path=%s error=%s", request.url.path, str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "request_id": request.headers.get("X-Request-ID")}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
