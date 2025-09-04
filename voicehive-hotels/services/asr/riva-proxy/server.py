#!/usr/bin/env python3
"""
NVIDIA Riva ASR Proxy Service
Provides HTTP API wrapper around Riva gRPC ASR service
"""

import asyncio
import os
import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

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


class ASRService:
    """Service wrapper for Riva ASR operations"""
    
    def __init__(self):
        """Initialize connection to Riva server"""
        try:
            import riva.client
            
            # Create Riva authentication
            self.auth = riva.client.Auth(uri=f"{RIVA_SERVER}:{RIVA_PORT}")
            
            # Initialize ASR service
            self.asr_service = riva.client.ASRService(self.auth)
            
            logger.info("Connected to Riva server", server=RIVA_SERVER, port=RIVA_PORT)
        except Exception as e:
            logger.error("Failed to connect to Riva", error=str(e))
            raise
            
    async def transcribe_offline(self, request: TranscribeRequest) -> TranscriptionResult:
        """Perform offline transcription"""
        start_time = datetime.utcnow()
        
        try:
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
            
            # Call Riva ASR service
            response = self.asr_service.offline_recognize(audio_bytes, config)
            
            # Extract results
            transcript = ""
            confidence = 0.0
            
            if response.results:
                result = response.results[0]
                if result.alternatives:
                    transcript = result.alternatives[0].transcript
                    confidence = result.alternatives[0].confidence
            
            # Record metrics
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
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
            
        except Exception as e:
            asr_requests_total.labels(
                language=request.language,
                type="offline",
                status="error"
            ).inc()
            logger.error("Transcription failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
            
    async def detect_language(self, request: LanguageDetectionRequest) -> LanguageDetectionResult:
        """Detect language from audio using transcription + text language detection"""
        try:
            import base64
            import pycld3
            
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
            
            # Get transcription
            response = self.asr_service.offline_recognize(audio_bytes[:16000*5], config)  # First 5 seconds
            
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
            
        except Exception as e:
            logger.error("Language detection failed", error=str(e))
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
    # TODO: Check Riva connection status
    return {
        "status": "healthy",
        "service": "riva-asr-proxy",
        "version": "1.0.0",
        "riva_connected": True  # Mock for now
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


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting Riva ASR Proxy", 
                riva_server=RIVA_SERVER, 
                riva_port=RIVA_PORT)
    # TODO: Verify Riva connection
    

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down Riva ASR Proxy")
    # TODO: Close Riva connection
    

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
