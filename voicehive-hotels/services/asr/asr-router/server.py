#!/usr/bin/env python3
"""
ASR Router Service - Hybrid Granary/Whisper Architecture
Intelligently routes ASR requests to the most appropriate engine:
- NVIDIA Granary (Parakeet-tdt) for 25 EU languages (premium accuracy)
- OpenAI Whisper for global language coverage (fallback)

Implements the architecture specified in Sprint 3 requirements.
"""

import asyncio
import os
import logging
import uuid
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
import structlog
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()

# Prometheus metrics
asr_router_requests_total = Counter(
    'asr_router_requests_total',
    'Total ASR router requests',
    ['language', 'engine', 'status'],
)
asr_router_duration = Histogram(
    'asr_router_request_duration_seconds',
    'ASR router request duration',
    ['language', 'engine'],
)
asr_engine_selection = Counter(
    'asr_engine_selection_total',
    'ASR engine selection counts',
    ['engine', 'reason'],
)
asr_fallback_events = Counter(
    'asr_fallback_events_total',
    'ASR fallback events when primary engine fails',
    ['from_engine', 'to_engine', 'reason'],
)

# Create FastAPI app
app = FastAPI(
    title="VoiceHive ASR Router",
    version="1.0.0",
    description="Intelligent ASR routing between Granary (25 EU languages) and Whisper (global coverage)"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment configuration
GRANARY_SERVICE_URL = os.getenv("GRANARY_SERVICE_URL", "http://granary-asr-proxy:51052")
WHISPER_SERVICE_URL = os.getenv("WHISPER_SERVICE_URL", "http://whisper-asr-proxy:51053")
RIVA_SERVICE_URL = os.getenv("RIVA_SERVICE_URL", "http://riva-asr-proxy:51051")  # Fallback to existing Riva

# Request timeout settings
ASR_REQUEST_TIMEOUT = int(os.getenv("ASR_REQUEST_TIMEOUT", "30"))
ASR_FALLBACK_ENABLED = os.getenv("ASR_FALLBACK_ENABLED", "true").lower() == "true"

# 25 EU Languages supported by Granary (premium accuracy)
GRANARY_LANGUAGES = {
    "en-US", "en-GB", "de-DE", "fr-FR", "es-ES", "it-IT", "nl-NL",
    "sv-SE", "da-DK", "no-NO", "pt-PT", "ro-RO", "ca-ES", "pl-PL",
    "cs-CZ", "sk-SK", "hr-HR", "sl-SI", "bg-BG", "fi-FI", "hu-HU",
    "et-EE", "lv-LV", "lt-LT", "el-GR", "mt-MT"
}

# Global languages supported by Whisper (broad coverage)
WHISPER_LANGUAGES = {
    "ar-SA", "zh-CN", "zh-TW", "ja-JP", "ko-KR", "hi-IN", "th-TH",
    "vi-VN", "id-ID", "ms-MY", "tl-PH", "ur-PK", "fa-IR", "he-IL",
    "tr-TR", "ru-RU", "uk-UA", "bn-BD", "ta-IN", "te-IN", "mr-IN",
    "gu-IN", "kn-IN", "ml-IN", "pa-IN", "or-IN", "as-IN", "ne-NP",
    "si-LK", "my-MM", "km-KH", "lo-LA", "ka-GE", "hy-AM", "az-AZ",
    "kk-KZ", "ky-KG", "tg-TJ", "tk-TM", "uz-UZ", "mn-MN", "bo-CN"
}

# Request/Response models (compatible with both engines)
class TranscribeRequest(BaseModel):
    """Unified request model for ASR routing"""
    audio_data: str  # Base64 encoded audio
    language: str = Field(default="en-US", pattern="^[a-z]{2}-[A-Z]{2}$")
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    encoding: str = Field(default="LINEAR16", regex="^(LINEAR16|FLAC|MULAW)$")
    enable_word_time_offsets: bool = True
    enable_punctuation: bool = True
    enable_automatic_punctuation: bool = True
    max_alternatives: int = Field(default=1, ge=1, le=10)
    prefer_accuracy: bool = Field(default=True, description="Prefer accuracy over speed")


class TranscriptionResult(BaseModel):
    """Unified response model from ASR routing"""
    transcript: str
    confidence: float = Field(ge=0.0, le=1.0)
    words: Optional[List[Dict[str, Any]]] = None
    alternatives: Optional[List[Dict[str, Any]]] = None
    language: str
    processing_time_ms: float
    engine_used: str  # granary, whisper, or riva
    routing_reason: str


class LanguageDetectionRequest(BaseModel):
    """Request model for language detection"""
    audio_data: str  # Base64 encoded audio
    sample_rate: int = Field(default=16000, ge=8000, le=48000)


class LanguageDetectionResult(BaseModel):
    """Response model for language detection"""
    detected_language: str
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: List[Dict[str, float]] = []
    engine_used: str


class ASRRouter:
    """Intelligent ASR routing service implementing hybrid architecture"""

    def __init__(self):
        """Initialize the ASR router with engine configurations"""
        self.granary_languages = GRANARY_LANGUAGES
        self.whisper_languages = WHISPER_LANGUAGES
        self.fallback_enabled = ASR_FALLBACK_ENABLED
        self.http_client = httpx.AsyncClient(timeout=ASR_REQUEST_TIMEOUT)

    def _determine_engine(self, language: str, prefer_accuracy: bool = True) -> tuple[str, str]:
        """
        Determine the best ASR engine for a given language

        Returns:
            tuple: (engine_name, routing_reason)
        """
        # Primary routing: Granary for EU languages (premium accuracy)
        if language in self.granary_languages:
            asr_engine_selection.labels(engine="granary", reason="eu_language").inc()
            return "granary", f"EU language {language} - using Granary for premium accuracy"

        # Secondary routing: Whisper for global languages
        if language in self.whisper_languages:
            asr_engine_selection.labels(engine="whisper", reason="global_language").inc()
            return "whisper", f"Global language {language} - using Whisper for broad coverage"

        # Fallback routing
        if prefer_accuracy:
            # Try Granary first for unknown languages if accuracy is preferred
            asr_engine_selection.labels(engine="granary", reason="accuracy_preferred").inc()
            return "granary", f"Unknown language {language} - trying Granary for accuracy"
        else:
            # Use Whisper for unknown languages if speed is preferred
            asr_engine_selection.labels(engine="whisper", reason="speed_preferred").inc()
            return "whisper", f"Unknown language {language} - using Whisper for speed"

    async def _call_granary_service(self, request: TranscribeRequest) -> TranscriptionResult:
        """Call the Granary ASR service"""
        try:
            response = await self.http_client.post(
                f"{GRANARY_SERVICE_URL}/transcribe",
                json=request.dict(),
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            result_data = response.json()
            result_data["engine_used"] = "granary"
            return TranscriptionResult(**result_data)

        except httpx.HTTPError as e:
            logger.error("Granary service call failed",
                        error=str(e),
                        language=request.language)
            raise HTTPException(
                status_code=503,
                detail=f"Granary ASR service unavailable: {str(e)}"
            )

    async def _call_whisper_service(self, request: TranscribeRequest) -> TranscriptionResult:
        """Call the Whisper ASR service"""
        try:
            response = await self.http_client.post(
                f"{WHISPER_SERVICE_URL}/transcribe",
                json=request.dict(),
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            result_data = response.json()
            result_data["engine_used"] = "whisper"
            return TranscriptionResult(**result_data)

        except httpx.HTTPError as e:
            logger.error("Whisper service call failed",
                        error=str(e),
                        language=request.language)
            raise HTTPException(
                status_code=503,
                detail=f"Whisper ASR service unavailable: {str(e)}"
            )

    async def _call_riva_service(self, request: TranscribeRequest) -> TranscriptionResult:
        """Call the Riva ASR service (legacy fallback)"""
        try:
            response = await self.http_client.post(
                f"{RIVA_SERVICE_URL}/transcribe",
                json=request.dict(),
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            result_data = response.json()
            result_data["engine_used"] = "riva"
            return TranscriptionResult(**result_data)

        except httpx.HTTPError as e:
            logger.error("Riva service call failed",
                        error=str(e),
                        language=request.language)
            raise HTTPException(
                status_code=503,
                detail=f"Riva ASR service unavailable: {str(e)}"
            )

    async def transcribe(self, request: TranscribeRequest) -> TranscriptionResult:
        """
        Intelligent ASR transcription with engine routing and fallback

        Implements the hybrid architecture:
        1. Route to Granary for EU languages (premium accuracy)
        2. Route to Whisper for global languages (broad coverage)
        3. Fallback chain: Primary → Secondary → Riva (if enabled)
        """
        start_time = datetime.now(timezone.utc)

        # Determine primary engine
        primary_engine, routing_reason = self._determine_engine(
            request.language,
            request.prefer_accuracy
        )

        logger.info("ASR routing decision",
                   language=request.language,
                   primary_engine=primary_engine,
                   routing_reason=routing_reason)

        # Try primary engine
        try:
            if primary_engine == "granary":
                result = await self._call_granary_service(request)
            else:  # whisper
                result = await self._call_whisper_service(request)

            result.routing_reason = routing_reason

            # Record successful routing metrics
            asr_router_requests_total.labels(
                language=request.language,
                engine=primary_engine,
                status="success"
            ).inc()

            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            asr_router_duration.labels(
                language=request.language,
                engine=primary_engine
            ).observe(processing_time)

            return result

        except HTTPException as e:
            if not self.fallback_enabled:
                # Record failure and re-raise
                asr_router_requests_total.labels(
                    language=request.language,
                    engine=primary_engine,
                    status="error"
                ).inc()
                raise

            logger.warning("Primary ASR engine failed, attempting fallback",
                          primary_engine=primary_engine,
                          error=str(e))

            # Record fallback event
            fallback_engine = "whisper" if primary_engine == "granary" else "granary"
            asr_fallback_events.labels(
                from_engine=primary_engine,
                to_engine=fallback_engine,
                reason="primary_failed"
            ).inc()

        # Try fallback engine
        try:
            if primary_engine == "granary":
                # Fallback to Whisper
                result = await self._call_whisper_service(request)
                result.routing_reason = f"Fallback to Whisper - Granary failed: {routing_reason}"
                fallback_engine = "whisper"
            else:
                # Fallback to Granary
                result = await self._call_granary_service(request)
                result.routing_reason = f"Fallback to Granary - Whisper failed: {routing_reason}"
                fallback_engine = "granary"

            # Record successful fallback metrics
            asr_router_requests_total.labels(
                language=request.language,
                engine=fallback_engine,
                status="success_fallback"
            ).inc()

            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            asr_router_duration.labels(
                language=request.language,
                engine=fallback_engine
            ).observe(processing_time)

            return result

        except HTTPException as fallback_error:
            logger.error("Fallback ASR engine also failed",
                        primary_engine=primary_engine,
                        fallback_engine=fallback_engine,
                        fallback_error=str(fallback_error))

            # Try Riva as last resort
            try:
                result = await self._call_riva_service(request)
                result.routing_reason = f"Last resort fallback to Riva - both Granary and Whisper failed"

                asr_fallback_events.labels(
                    from_engine=fallback_engine,
                    to_engine="riva",
                    reason="fallback_failed"
                ).inc()

                asr_router_requests_total.labels(
                    language=request.language,
                    engine="riva",
                    status="success_last_resort"
                ).inc()

                return result

            except HTTPException:
                # All engines failed
                asr_router_requests_total.labels(
                    language=request.language,
                    engine="all",
                    status="total_failure"
                ).inc()

                raise HTTPException(
                    status_code=503,
                    detail="All ASR engines unavailable. Please try again later."
                )

    async def detect_language(self, request: LanguageDetectionRequest) -> LanguageDetectionResult:
        """Language detection with intelligent engine selection"""
        try:
            # Try Granary first for language detection (better for EU languages)
            response = await self.http_client.post(
                f"{GRANARY_SERVICE_URL}/detect-language",
                json=request.dict(),
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            result_data = response.json()
            result_data["engine_used"] = "granary"
            return LanguageDetectionResult(**result_data)

        except httpx.HTTPError:
            # Fallback to Whisper for language detection
            try:
                response = await self.http_client.post(
                    f"{WHISPER_SERVICE_URL}/detect-language",
                    json=request.dict(),
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()

                result_data = response.json()
                result_data["engine_used"] = "whisper"
                return LanguageDetectionResult(**result_data)

            except httpx.HTTPError as e:
                logger.error("Language detection failed on all engines", error=str(e))
                # Return default English
                return LanguageDetectionResult(
                    detected_language="en-US",
                    confidence=0.5,
                    alternatives=[],
                    engine_used="default"
                )

    async def get_engine_status(self) -> Dict[str, Any]:
        """Get status of all ASR engines"""
        engine_status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "engines": {}
        }

        # Check Granary
        try:
            response = await self.http_client.get(f"{GRANARY_SERVICE_URL}/health", timeout=5)
            engine_status["engines"]["granary"] = {
                "available": response.status_code == 200,
                "status": response.json() if response.status_code == 200 else {"error": "unhealthy"},
                "supported_languages": len(GRANARY_LANGUAGES)
            }
        except:
            engine_status["engines"]["granary"] = {
                "available": False,
                "status": {"error": "connection_failed"},
                "supported_languages": 0
            }

        # Check Whisper
        try:
            response = await self.http_client.get(f"{WHISPER_SERVICE_URL}/health", timeout=5)
            engine_status["engines"]["whisper"] = {
                "available": response.status_code == 200,
                "status": response.json() if response.status_code == 200 else {"error": "unhealthy"},
                "supported_languages": len(WHISPER_LANGUAGES)
            }
        except:
            engine_status["engines"]["whisper"] = {
                "available": False,
                "status": {"error": "connection_failed"},
                "supported_languages": 0
            }

        # Check Riva (fallback)
        try:
            response = await self.http_client.get(f"{RIVA_SERVICE_URL}/health", timeout=5)
            engine_status["engines"]["riva"] = {
                "available": response.status_code == 200,
                "status": response.json() if response.status_code == 200 else {"error": "unhealthy"},
                "supported_languages": 6  # Approximate
            }
        except:
            engine_status["engines"]["riva"] = {
                "available": False,
                "status": {"error": "connection_failed"},
                "supported_languages": 0
            }

        return engine_status


# Initialize ASR router
asr_router = ASRRouter()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    engine_status = await asr_router.get_engine_status()

    # Determine overall health
    granary_ok = engine_status["engines"]["granary"]["available"]
    whisper_ok = engine_status["engines"]["whisper"]["available"]

    overall_status = "healthy" if (granary_ok or whisper_ok) else "unhealthy"

    return {
        "status": overall_status,
        "service": "asr-router",
        "version": "1.0.0",
        "routing_strategy": "hybrid_granary_whisper",
        "fallback_enabled": asr_router.fallback_enabled,
        "engines": engine_status["engines"]
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/transcribe", response_model=TranscriptionResult)
async def transcribe_audio(request: TranscribeRequest):
    """Intelligent ASR transcription with engine routing"""
    logger.info("ASR router transcription request",
               language=request.language,
               prefer_accuracy=request.prefer_accuracy)
    return await asr_router.transcribe(request)


@app.post("/detect-language", response_model=LanguageDetectionResult)
async def detect_language(request: LanguageDetectionRequest):
    """Intelligent language detection with engine routing"""
    logger.info("ASR router language detection request")
    return await asr_router.detect_language(request)


@app.get("/supported-languages")
async def get_supported_languages():
    """Get comprehensive list of supported languages from all engines"""
    return {
        "granary_languages": {
            "codes": sorted(list(GRANARY_LANGUAGES)),
            "count": len(GRANARY_LANGUAGES),
            "description": "25 EU languages with premium accuracy"
        },
        "whisper_languages": {
            "codes": sorted(list(WHISPER_LANGUAGES)),
            "count": len(WHISPER_LANGUAGES),
            "description": "Global languages with broad coverage"
        },
        "total_unique_languages": len(GRANARY_LANGUAGES | WHISPER_LANGUAGES),
        "routing_strategy": "Granary for EU languages, Whisper for global languages",
        "fallback_enabled": asr_router.fallback_enabled
    }


@app.get("/engine-status")
async def get_engine_status():
    """Get detailed status of all ASR engines"""
    return await asr_router.get_engine_status()


@app.websocket("/transcribe-stream")
async def transcribe_stream(websocket: WebSocket):
    """WebSocket endpoint for streaming transcription with intelligent routing"""
    await websocket.accept()
    stream_id = str(uuid.uuid4())
    logger.info("ASR router streaming started", stream_id=stream_id)

    try:
        # Get initial configuration
        config_data = await websocket.receive_json()
        if config_data.get("type") != "config":
            await websocket.send_json({
                "type": "error",
                "message": "First message must be config"
            })
            return

        language = config_data.get("language", "en-US")
        prefer_accuracy = config_data.get("prefer_accuracy", True)

        # Determine engine for streaming
        engine, routing_reason = asr_router._determine_engine(language, prefer_accuracy)

        await websocket.send_json({
            "type": "config_ack",
            "language": language,
            "engine_selected": engine,
            "routing_reason": routing_reason
        })

        # Forward to appropriate engine's streaming endpoint
        if engine == "granary":
            engine_ws_url = f"{GRANARY_SERVICE_URL.replace('http', 'ws')}/transcribe-stream"
        else:  # whisper
            engine_ws_url = f"{WHISPER_SERVICE_URL.replace('http', 'ws')}/transcribe-stream"

        # Proxy the WebSocket connection
        async with websocket:
            # For now, implement basic message forwarding
            # Future enhancement: implement proper WebSocket proxying
            await websocket.send_json({
                "type": "info",
                "message": f"Routing to {engine} engine",
                "routing_reason": routing_reason
            })

    except WebSocketDisconnect:
        logger.info("Client disconnected", stream_id=stream_id)
    except Exception as e:
        logger.error("Streaming error", error=str(e), stream_id=stream_id)


@app.on_event("startup")
async def startup_event():
    """Initialize ASR router on startup"""
    logger.info("Starting ASR Router Service",
                granary_url=GRANARY_SERVICE_URL,
                whisper_url=WHISPER_SERVICE_URL,
                riva_url=RIVA_SERVICE_URL,
                fallback_enabled=ASR_FALLBACK_ENABLED)

    # Perform initial health check
    engine_status = await asr_router.get_engine_status()
    logger.info("Initial engine status check", engines=engine_status["engines"])


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down ASR Router Service")
    await asr_router.http_client.aclose()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=51050,  # Main router port
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["default"],
            },
        }
    )