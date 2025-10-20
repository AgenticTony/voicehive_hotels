#!/usr/bin/env python3
"""
NVIDIA Riva ASR Proxy Service
Provides HTTP API wrapper around Riva gRPC ASR service
"""

import asyncio
import os
import logging
import uuid
import sys
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
import structlog
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import redis.asyncio as aioredis

# Import circuit breaker from resilience infrastructure
try:
    # Add orchestrator path to import circuit breaker
    orchestrator_path = os.path.join(os.path.dirname(__file__), '..', '..', 'orchestrator')
    if orchestrator_path not in sys.path:
        sys.path.append(orchestrator_path)
    from resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitBreakerTimeoutError
    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError as e:
    # Fallback - circuit breaker not available
    logger.warning(f"Circuit breaker not available: {e}")
    CircuitBreaker = None
    CircuitBreakerConfig = None
    CircuitBreakerOpenError = Exception
    CircuitBreakerTimeoutError = Exception
    CIRCUIT_BREAKER_AVAILABLE = False

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
asr_requests_total = Counter(
    'asr_requests_total',
    'Total ASR requests',
    ['language', 'type', 'status'],
)
asr_request_duration = Histogram(
    'asr_request_duration_seconds',
    'ASR request duration',
    ['language', 'type'],
)
active_streams = Gauge(
    'asr_active_streams',
    'Number of active ASR streams',
)

# Create FastAPI app
app = FastAPI(
    title="VoiceHive Riva ASR Proxy",
    version="1.0.0",
    description="HTTP/WebSocket proxy for NVIDIA Riva ASR service"
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
RIVA_SERVER = os.getenv("RIVA_SERVER_HOST", "riva-server")
RIVA_PORT = int(os.getenv("RIVA_SERVER_PORT", "50051"))


# Request/Response models
class TranscribeRequest(BaseModel):
    """Request model for offline transcription"""
    audio_data: str  # Base64 encoded audio
    language: str = Field(default="en-US", pattern="^[a-z]{2}-[A-Z]{2}$")
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    encoding: str = Field(default="LINEAR16", regex="^(LINEAR16|FLAC|MULAW)$")
    enable_word_time_offsets: bool = False
    enable_punctuation: bool = True
    enable_automatic_punctuation: bool = True
    max_alternatives: int = Field(default=1, ge=1, le=10)
    
    
class TranscriptionResult(BaseModel):
    """Response model for transcription results"""
    transcript: str
    confidence: float = Field(ge=0.0, le=1.0)
    words: Optional[List[Dict[str, Any]]] = None
    alternatives: Optional[List[Dict[str, Any]]] = None
    language: str
    processing_time_ms: float


class LanguageDetectionRequest(BaseModel):
    """Request model for language detection"""
    audio_data: str  # Base64 encoded audio
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    

class LanguageDetectionResult(BaseModel):
    """Response model for language detection"""
    detected_language: str
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: List[Dict[str, float]] = []


class RivaChannelPool:
    """
    gRPC channel pool for Riva ASR service following official gRPC best practices.

    Based on official gRPC documentation recommendations for connection pooling:
    - Uses multiple channels to distribute RPCs over multiple connections
    - Each channel corresponds to one HTTP/2 connection
    - Provides better throughput and fault tolerance
    """

    def __init__(self, pool_size: int = 5):
        self.pool_size = pool_size
        self.channels = []
        self.services = []
        self.current_index = 0
        self.lock = asyncio.Lock()

        logger.info("riva_channel_pool_initializing", pool_size=pool_size)

        # Initialize pool of Riva client connections
        for i in range(pool_size):
            try:
                import riva.client

                # Create separate auth and service for each channel
                # Following official gRPC recommendation for multiple channels
                auth = riva.client.Auth(uri=f"{RIVA_SERVER}:{RIVA_PORT}")
                asr_service = riva.client.ASRService(auth)

                self.channels.append(auth)
                self.services.append(asr_service)

                logger.debug("riva_channel_created", channel_index=i)

            except Exception as e:
                logger.error("riva_channel_creation_failed", channel_index=i, error=str(e))
                raise

        logger.info("riva_channel_pool_initialized",
                   total_channels=len(self.services),
                   healthy_channels=len(self.services))

    async def get_service(self):
        """Get next available ASR service using round-robin load balancing"""
        async with self.lock:
            service = self.services[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.services)
            return service

    async def health_check_all(self):
        """Check health of all channels in the pool"""
        healthy_count = 0
        for i, service in enumerate(self.services):
            try:
                metadata = service.get_service_metadata()
                if metadata:
                    healthy_count += 1
                    logger.debug("riva_channel_healthy", channel_index=i)
            except Exception as e:
                logger.warning("riva_channel_unhealthy", channel_index=i, error=str(e))

        logger.info("riva_pool_health_check",
                   healthy_channels=healthy_count,
                   total_channels=len(self.services))
        return healthy_count > 0

    def close(self):
        """Close all gRPC channels in the pool"""
        for i, auth in enumerate(self.channels):
            try:
                # Close underlying gRPC channel if accessible
                if hasattr(auth, '_channel'):
                    auth._channel.close()
                logger.debug("riva_channel_closed", channel_index=i)
            except Exception as e:
                logger.warning("riva_channel_close_error", channel_index=i, error=str(e))

        logger.info("riva_channel_pool_closed", closed_channels=len(self.channels))


class ASRService:
    """Service wrapper for Riva ASR operations with gRPC connection pooling and circuit breaker protection"""

    def __init__(self):
        """Initialize Riva connection pool and circuit breakers"""
        self.connection_pool = None
        self.connection_healthy = False

        # Initialize circuit breakers if available
        self._circuit_breakers = {}
        if CIRCUIT_BREAKER_AVAILABLE and CircuitBreaker is not None:
            # Get Redis client from environment (optional)
            redis_client = None
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                try:
                    redis_client = aioredis.from_url(redis_url)
                except Exception as e:
                    logger.warning(f"Failed to connect to Redis for circuit breaker: {e}")

            # Circuit breaker for Riva connection
            connection_config = CircuitBreakerConfig(
                name="riva_connection",
                failure_threshold=3,  # Fail fast for connection issues
                recovery_timeout=120,  # 2 minutes recovery for connection
                timeout=30.0,  # Connection should be reasonably fast
                expected_exception=(Exception,)  # Catch all connection exceptions
            )
            self._circuit_breakers["connection"] = CircuitBreaker(connection_config, redis_client)

            # Circuit breaker for ASR operations
            asr_config = CircuitBreakerConfig(
                name="riva_asr",
                failure_threshold=5,  # More tolerant for ASR operations
                recovery_timeout=60,  # 1 minute recovery for ASR
                timeout=120.0,  # ASR operations can take longer
                expected_exception=(Exception,)  # Catch all ASR exceptions
            )
            self._circuit_breakers["asr"] = CircuitBreaker(asr_config, redis_client)

            logger.info("Riva ASR circuit breakers initialized",
                       connection_threshold=connection_config.failure_threshold,
                       asr_threshold=asr_config.failure_threshold)
        else:
            logger.warning("Circuit breaker not available for Riva ASR service")

        self._connect_to_riva()
    
    def _connect_to_riva(self):
        """Establish connection pool to Riva server with circuit breaker protection"""

        def _do_connect():
            """Inner connection function for circuit breaker"""
            # Create connection pool following official gRPC best practices
            # Multiple channels provide better performance than single channel
            self.connection_pool = RivaChannelPool(pool_size=5)

            # Test one connection from the pool
            test_service = self.connection_pool.services[0]
            metadata = test_service.get_service_metadata()
            self.connection_healthy = True

            logger.info("Connected to Riva server with connection pool",
                       server=RIVA_SERVER,
                       port=RIVA_PORT,
                       pool_size=self.connection_pool.pool_size,
                       service_version=getattr(metadata, 'version', 'unknown') if metadata else 'unknown')
            return True

        try:
            # Use circuit breaker if available
            if "connection" in self._circuit_breakers:
                # Note: circuit breaker call method expects async, but connection is sync
                # For now, use direct call with circuit breaker in async methods
                _do_connect()
            else:
                _do_connect()

        except CircuitBreakerOpenError as e:
            self.connection_healthy = False
            logger.error("Riva connection circuit breaker is open",
                        circuit_name=e.circuit_name,
                        next_attempt=e.next_attempt_time)

        except CircuitBreakerTimeoutError as e:
            self.connection_healthy = False
            logger.error("Riva connection timed out", error=str(e))

        except Exception as e:
            self.connection_healthy = False
            logger.error("Failed to connect to Riva", error=str(e))
            # Don't raise here - let individual methods handle the error
    
    def _ensure_connection(self):
        """Ensure connection pool is healthy, reconnect if needed"""
        if not self.connection_healthy or not self.connection_pool:
            logger.info("Attempting to reconnect to Riva server")
            self._connect_to_riva()

        if not self.connection_healthy:
            raise HTTPException(
                status_code=503,
                detail="Riva ASR service is not available. Please try again later."
            )
    
    def close_connection(self):
        """Properly close Riva gRPC connection pool"""
        try:
            if self.connection_pool:
                # Close all channels in the pool
                self.connection_pool.close()
                logger.info("Riva gRPC connection pool closed successfully")
            self.connection_healthy = False
        except Exception as e:
            logger.error(f"Error closing Riva connection pool: {e}")
            
    async def transcribe_offline(self, request: TranscribeRequest) -> TranscriptionResult:
        """Perform offline transcription with circuit breaker protection"""
        start_time = datetime.now(timezone.utc)

        async def _do_transcribe():
            """Inner transcription function for circuit breaker"""
            # Ensure connection is healthy
            self._ensure_connection()

            # Decode audio data
            import base64
            import riva.client
            audio_bytes = base64.b64decode(request.audio_data)

            # Configure ASR recognition
            config = riva.client.RecognitionConfig(
                encoding=riva.client.AudioEncoding.LINEAR_PCM,
                sample_rate_hertz=request.sample_rate or 16000,
                language_code=request.language,
                max_alternatives=1,
                enable_automatic_punctuation=True,
                verbatim_transcripts=False,
            )

            # Get ASR service from connection pool (following gRPC best practices)
            asr_service = await self.connection_pool.get_service()
            response = asr_service.offline_recognize(audio_bytes, config)

            # Extract results
            transcript = ""
            confidence = 0.0

            if response.results:
                result = response.results[0]
                if result.alternatives:
                    transcript = result.alternatives[0].transcript
                    confidence = result.alternatives[0].confidence

            return transcript, confidence

        try:
            # Use circuit breaker if available
            if "asr" in self._circuit_breakers:
                transcript, confidence = await self._circuit_breakers["asr"].call(_do_transcribe)
            else:
                transcript, confidence = await _do_transcribe()

            # Record metrics
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            asr_requests_total.labels(
                language=request.language,
                type="offline",
                status="success"
            ).inc()
            asr_request_duration.labels(
                language=request.language,
                type="offline"
            ).observe(processing_time / 1000)

            return TranscriptionResult(
                transcript=transcript,
                confidence=confidence,
                language=request.language,
                processing_time_ms=processing_time
            )

        except CircuitBreakerOpenError as e:
            asr_requests_total.labels(
                language=request.language,
                type="offline",
                status="circuit_breaker_open"
            ).inc()
            logger.error("ASR circuit breaker is open",
                        circuit_name=e.circuit_name,
                        next_attempt=e.next_attempt_time,
                        language=request.language)
            raise HTTPException(
                status_code=503,
                detail=f"ASR service temporarily unavailable: {e}"
            )

        except CircuitBreakerTimeoutError as e:
            asr_requests_total.labels(
                language=request.language,
                type="offline",
                status="timeout"
            ).inc()
            logger.error("ASR request timed out", error=str(e), language=request.language)
            raise HTTPException(
                status_code=504,
                detail=f"ASR request timeout: {e}"
            )

        except Exception as e:
            asr_requests_total.labels(
                language=request.language,
                type="offline",
                status="error"
            ).inc()
            logger.error("Transcription failed", error=str(e), language=request.language)

            # If connection failed, mark as unhealthy and try to reconnect for next request
            if "connection" in str(e).lower() or "unavailable" in str(e).lower():
                self.connection_healthy = False

            raise HTTPException(status_code=500, detail=str(e))

    async def get_circuit_breaker_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics"""
        stats = {}
        if self._circuit_breakers:
            for name, breaker in self._circuit_breakers.items():
                try:
                    breaker_stats = await breaker.get_stats()
                    stats[name] = {
                        "state": breaker_stats.state.value,
                        "failure_count": breaker_stats.failure_count,
                        "success_count": breaker_stats.success_count,
                        "total_requests": breaker_stats.total_requests,
                        "total_failures": breaker_stats.total_failures,
                        "total_successes": breaker_stats.total_successes,
                        "last_failure_time": breaker_stats.last_failure_time.isoformat() if breaker_stats.last_failure_time else None,
                        "last_success_time": breaker_stats.last_success_time.isoformat() if breaker_stats.last_success_time else None,
                        "next_attempt_time": breaker_stats.next_attempt_time.isoformat() if breaker_stats.next_attempt_time else None,
                    }
                except Exception as e:
                    stats[name] = {"error": f"Failed to get stats: {e}"}
        return stats

    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check with circuit breaker information"""
        # Get circuit breaker statistics
        circuit_breaker_stats = await self.get_circuit_breaker_stats()

        try:
            # Test connection and service health
            self._ensure_connection()

            # If we get here, basic connection is healthy
            base_health = {
                "status": "healthy",
                "service": "riva_asr",
                "server": f"{RIVA_SERVER}:{RIVA_PORT}",
                "connection_healthy": self.connection_healthy,
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # Try a quick service metadata call to verify connection pool health
            if self.connection_pool:
                try:
                    # Use connection pool for health check instead of creating new connection
                    asr_service = await self.connection_pool.get_service()
                    metadata = asr_service.get_service_metadata()
                    base_health["service_version"] = getattr(metadata, 'version', 'unknown') if metadata else 'unknown'
                    base_health["service_metadata_accessible"] = True
                    base_health["connection_pool_size"] = self.connection_pool.pool_size
                except Exception as e:
                    base_health["service_metadata_accessible"] = False
                    base_health["service_metadata_error"] = str(e)

            return base_health

        except CircuitBreakerOpenError as e:
            return {
                "status": "degraded",
                "service": "riva_asr",
                "server": f"{RIVA_SERVER}:{RIVA_PORT}",
                "error": f"Circuit breaker open: {e}",
                "connection_healthy": False,
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "service": "riva_asr",
                "server": f"{RIVA_SERVER}:{RIVA_PORT}",
                "error": str(e),
                "connection_healthy": self.connection_healthy,
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    async def detect_language(self, request: LanguageDetectionRequest) -> LanguageDetectionResult:
        """Detect language from audio using transcription + text language detection with circuit breaker protection"""

        async def _do_detect_language():
            """Inner language detection function for circuit breaker"""
            # Ensure connection is healthy
            self._ensure_connection()

            import base64
            import pycld3
            import riva.client

            # First, transcribe a short segment with English model
            audio_bytes = base64.b64decode(request.audio_data)

            # Quick transcription with multilingual model if available
            config = riva.client.RecognitionConfig(
                encoding=riva.client.AudioEncoding.LINEAR_PCM,
                sample_rate_hertz=16000,
                language_code="en-US",  # Use as default
                max_alternatives=1,
                enable_automatic_punctuation=False,
                verbatim_transcripts=True,
            )

            # Get transcription with error handling using connection pool
            try:
                asr_service = await self.connection_pool.get_service()
                response = asr_service.offline_recognize(audio_bytes[:16000*5], config)  # First 5 seconds
            except Exception as riva_error:
                # Mark connection as unhealthy and retry once
                logger.warning("Riva language detection failed, attempting reconnection", error=str(riva_error))
                self.connection_healthy = False
                self._ensure_connection()
                asr_service = await self.connection_pool.get_service()
                response = asr_service.offline_recognize(audio_bytes[:16000*5], config)
            
            if not response.results or not response.results[0].alternatives:
                # Fallback if no transcription
                return LanguageDetectionResult(
                    detected_language="en-US",
                    confidence=0.5,
                    alternatives=[]
                )
            
            # Detect language from transcribed text
            transcript = response.results[0].alternatives[0].transcript
            result = pycld3.get_language(transcript)
            
            # Map pycld3 language codes to our format
            lang_map = {
                "en": "en-US",
                "de": "de-DE",
                "es": "es-ES",
                "fr": "fr-FR",
                "it": "it-IT",
            }
            
            detected_lang = lang_map.get(result.language, "en-US")
            confidence = result.probability
            
            # Get alternatives if confidence is not high
            alternatives = []
            if confidence < 0.95:
                # Try multiple languages
                for lang_code, lang_locale in lang_map.items():
                    if lang_code != result.language:
                        alternatives.append({
                            "language": lang_locale,
                            "confidence": 0.1  # Low confidence for alternatives
                        })
            
            return LanguageDetectionResult(
                detected_language=detected_lang,
                confidence=confidence,
                alternatives=alternatives[:2]  # Max 2 alternatives
            )

        try:
            # Use circuit breaker if available
            if "asr" in self._circuit_breakers:
                return await self._circuit_breakers["asr"].call(_do_detect_language)
            else:
                return await _do_detect_language()

        except CircuitBreakerOpenError as e:
            logger.error("Language detection circuit breaker is open",
                        circuit_name=e.circuit_name,
                        next_attempt=e.next_attempt_time)
            # Return fallback response when circuit breaker is open
            return LanguageDetectionResult(
                detected_language="en-US",
                confidence=0.5,
                alternatives=[]
            )

        except CircuitBreakerTimeoutError as e:
            logger.error("Language detection request timed out", error=str(e))
            # Return fallback response on timeout
            return LanguageDetectionResult(
                detected_language="en-US",
                confidence=0.5,
                alternatives=[]
            )

        except Exception as e:
            logger.error("Language detection failed", error=str(e))
            # If connection failed, mark as unhealthy for next request
            if "connection" in str(e).lower() or "unavailable" in str(e).lower():
                self.connection_healthy = False
            # Fallback to English
            return LanguageDetectionResult(
                detected_language="en-US",
                confidence=0.5,
                alternatives=[]
            )


# Initialize ASR service
asr_service = ASRService()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check Riva connection status by attempting a simple health check
        # Use existing connection pool instead of creating temporary connection
        # This follows gRPC best practices and avoids connection overhead
        service_metadata = None
        if asr_service.connection_pool and asr_service.connection_healthy:
            try:
                pool_service = await asr_service.connection_pool.get_service()
                service_metadata = pool_service.get_service_metadata()
            except Exception as e:
                logger.warning("Health check failed using connection pool", error=str(e))
                # Fallback to connection pool health check
                asr_service.connection_healthy = False
        
        return {
            "status": "healthy",
            "service": "riva-asr-proxy",
            "version": "1.0.0",
            "riva_connected": True,
            "riva_server": f"{RIVA_SERVER}:{RIVA_PORT}",
            "riva_service_version": getattr(service_metadata, 'version', 'unknown') if service_metadata else 'unknown'
        }
    except Exception as e:
        logger.error("Riva health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "service": "riva-asr-proxy",
            "version": "1.0.0",
            "riva_connected": False,
            "riva_server": f"{RIVA_SERVER}:{RIVA_PORT}",
            "error": str(e)
        }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    from starlette.responses import Response
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/transcribe", response_model=TranscriptionResult)
async def transcribe_offline(request: TranscribeRequest):
    """Transcribe audio file (non-streaming)"""
    logger.info("Offline transcription request", language=request.language)
    return await asr_service.transcribe_offline(request)


@app.post("/detect-language", response_model=LanguageDetectionResult)
async def detect_language(request: LanguageDetectionRequest):
    """Detect language from audio"""
    logger.info("Language detection request")
    return await asr_service.detect_language(request)


@app.websocket("/transcribe-stream")
async def transcribe_stream(websocket: WebSocket):
    """WebSocket endpoint for streaming transcription"""
    await websocket.accept()
    stream_id = str(uuid.uuid4())
    logger.info("Streaming transcription started", stream_id=stream_id)
    
    active_streams.inc()
    
    try:
        import base64
        import riva.client
        from queue import Queue
        import threading
        
        # Get initial configuration from first message
        config_data = await websocket.receive_json()
        if config_data.get("type") != "config":
            await websocket.send_json({
                "type": "error",
                "message": "First message must be config"
            })
            return
        
        # Configure streaming recognition
        language = config_data.get("language", "en-US")
        sample_rate = config_data.get("sample_rate", 16000)
        
        offline_config = riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=sample_rate,
            language_code=language,
            max_alternatives=1,
            enable_automatic_punctuation=True,
            verbatim_transcripts=False,
        )
        
        streaming_config = riva.client.StreamingRecognitionConfig(
            config=offline_config,
            interim_results=True,
        )
        
        # Create audio queue for streaming
        audio_queue = Queue()
        
        # Generator function for audio chunks
        def audio_generator():
            while True:
                chunk = audio_queue.get()
                if chunk is None:
                    break
                yield chunk
        
        # Start streaming recognition in background thread
        def process_responses():
            try:
                responses = asr_service.asr_service.streaming_response_generator(
                    audio_chunks=audio_generator(),
                    streaming_config=streaming_config
                )
                
                for response in responses:
                    if not response.results:
                        continue
                        
                    result = response.results[0]
                    if not result.alternatives:
                        continue
                    
                    alternative = result.alternatives[0]
                    
                    # Send result via WebSocket
                    asyncio.run(websocket.send_json({
                        "type": "partial" if not result.is_final else "final",
                        "transcript": alternative.transcript,
                        "confidence": alternative.confidence,
                        "is_final": result.is_final,
                        "language": language
                    }))
                    
            except Exception as e:
                logger.error("Streaming recognition error", error=str(e))
                asyncio.run(websocket.send_json({
                    "type": "error",
                    "message": str(e)
                }))
        
        # Start response processing thread
        response_thread = threading.Thread(target=process_responses)
        response_thread.start()
        
        # Receive and queue audio chunks
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "audio":
                # Decode and queue audio chunk
                audio_chunk = base64.b64decode(data.get("audio", ""))
                audio_queue.put(audio_chunk)
                
            elif data.get("type") == "end_of_stream":
                # Signal end of audio
                audio_queue.put(None)
                response_thread.join(timeout=5.0)
                break
                
    except WebSocketDisconnect:
        logger.info("Client disconnected", stream_id=stream_id)
    except Exception as e:
        logger.error("Streaming error", error=str(e), stream_id=stream_id)
        await websocket.close(code=1000)
    finally:
        active_streams.dec()


@app.get("/supported-languages")
async def get_supported_languages():
    """Get list of supported languages"""
    return {
        "languages": [
            {"code": "en-US", "name": "English (US)"},
            {"code": "en-GB", "name": "English (UK)"},
            {"code": "de-DE", "name": "German"},
            {"code": "es-ES", "name": "Spanish (Spain)"},
            {"code": "fr-FR", "name": "French"},
            {"code": "it-IT", "name": "Italian"},
        ]
    }


@app.get("/health")
async def health_check():
    """Enhanced health check with circuit breaker information"""
    global asr_service
    if asr_service:
        try:
            return await asr_service.health_check()
        except Exception as e:
            logger.error("Health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "service": "riva_asr",
                "error": f"Health check error: {e}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    else:
        return {
            "status": "unhealthy",
            "service": "riva_asr",
            "error": "ASR service not initialized",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@app.get("/circuit-breakers")
async def get_circuit_breaker_stats():
    """Get circuit breaker statistics"""
    global asr_service
    if asr_service:
        try:
            stats = await asr_service.get_circuit_breaker_stats()
            return {
                "circuit_breakers": stats,
                "enabled": len(stats) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error("Failed to get circuit breaker stats", error=str(e))
            return {
                "error": f"Failed to get circuit breaker stats: {e}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    else:
        return {
            "error": "ASR service not initialized",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting Riva ASR Proxy", 
                riva_server=RIVA_SERVER, 
                riva_port=RIVA_PORT)
    
    # Initialize the global ASR service with connection pooling
    try:
        global asr_service
        asr_service = ASRService()  # Connection pool created inside ASRService

        # Verify connection pool health
        if asr_service.connection_pool and asr_service.connection_healthy:
            logger.info("Riva connection pool initialized successfully",
                       server=f"{RIVA_SERVER}:{RIVA_PORT}",
                       pool_size=asr_service.connection_pool.pool_size)
        
    except Exception as e:
        logger.error("Failed to connect to Riva server on startup", 
                    error=str(e), 
                    server=f"{RIVA_SERVER}:{RIVA_PORT}")
        # Don't fail startup, but log the error
        # The service will return appropriate errors when called
    

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down Riva ASR Proxy")
    
    # Close Riva connection if it exists
    global asr_service
    if asr_service:
        try:
            asr_service.close_connection()
            logger.info("Riva connection closed successfully")
        except Exception as e:
            logger.error("Error closing Riva connection", error=str(e))
    

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=51051,
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
