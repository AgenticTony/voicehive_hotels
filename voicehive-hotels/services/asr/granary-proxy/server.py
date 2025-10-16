#!/usr/bin/env python3
"""
NVIDIA Granary ASR Proxy Service
Provides HTTP API wrapper around NeMo Parakeet-tdt ASR models for 25 EU languages
Replaces Riva with state-of-the-art multilingual ASR capability
"""

import asyncio
import os
import logging
import uuid
import base64
import torch
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
asr_requests_total = Counter(
    'granary_asr_requests_total',
    'Total Granary ASR requests',
    ['language', 'type', 'status', 'model'],
)
asr_request_duration = Histogram(
    'granary_asr_request_duration_seconds',
    'Granary ASR request duration',
    ['language', 'type', 'model'],
)
active_streams = Gauge(
    'granary_asr_active_streams',
    'Number of active Granary ASR streams',
)
model_load_time = Histogram(
    'granary_model_load_duration_seconds',
    'Time to load Granary models',
    ['model_name'],
)

# Create FastAPI app
app = FastAPI(
    title="VoiceHive Granary ASR Proxy",
    version="1.0.0",
    description="HTTP/WebSocket proxy for NVIDIA Granary (Parakeet-tdt) ASR service with 25 EU languages"
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
GRANARY_MODEL_NAME = os.getenv("GRANARY_MODEL_NAME", "nvidia/parakeet-tdt-0.6b-v3")
GRANARY_CACHE_DIR = os.getenv("GRANARY_CACHE_DIR", "/tmp/granary_models")
DEVICE = os.getenv("GRANARY_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
BATCH_SIZE = int(os.getenv("GRANARY_BATCH_SIZE", "1"))

# 25 EU Languages supported by Granary
GRANARY_LANGUAGES = {
    "en-US": "en",  # English
    "en-GB": "en",  # English (UK)
    "de-DE": "de",  # German
    "fr-FR": "fr",  # French
    "es-ES": "es",  # Spanish
    "it-IT": "it",  # Italian
    "nl-NL": "nl",  # Dutch
    "sv-SE": "sv",  # Swedish
    "da-DK": "da",  # Danish
    "no-NO": "no",  # Norwegian
    "pt-PT": "pt",  # Portuguese
    "ro-RO": "ro",  # Romanian
    "ca-ES": "ca",  # Catalan
    "pl-PL": "pl",  # Polish
    "cs-CZ": "cs",  # Czech
    "sk-SK": "sk",  # Slovak
    "hr-HR": "hr",  # Croatian
    "sl-SI": "sl",  # Slovenian
    "bg-BG": "bg",  # Bulgarian
    "fi-FI": "fi",  # Finnish
    "hu-HU": "hu",  # Hungarian
    "et-EE": "et",  # Estonian
    "lv-LV": "lv",  # Latvian
    "lt-LT": "lt",  # Lithuanian
    "el-GR": "el",  # Greek
    "mt-MT": "mt",  # Maltese
}

# Request/Response models
class TranscribeRequest(BaseModel):
    """Request model for offline transcription"""
    audio_data: str  # Base64 encoded audio
    language: str = Field(default="en-US", pattern="^[a-z]{2}-[A-Z]{2}$")
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    encoding: str = Field(default="LINEAR16", regex="^(LINEAR16|FLAC|MULAW)$")
    enable_word_time_offsets: bool = True
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
    model_used: str = "granary"


class LanguageDetectionRequest(BaseModel):
    """Request model for language detection"""
    audio_data: str  # Base64 encoded audio
    sample_rate: int = Field(default=16000, ge=8000, le=48000)


class LanguageDetectionResult(BaseModel):
    """Response model for language detection"""
    detected_language: str
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: List[Dict[str, float]] = []


class GranaryASRService:
    """Service wrapper for NVIDIA Granary (Parakeet-tdt) ASR operations"""

    def __init__(self):
        """Initialize Granary ASR models"""
        self.model = None
        self.device = DEVICE
        self.model_loaded = False
        self.supported_languages = set(GRANARY_LANGUAGES.keys())
        self._load_model()

    def _load_model(self):
        """Load the Granary Parakeet-tdt model"""
        start_time = datetime.now(timezone.utc)

        try:
            import nemo.collections.asr as nemo_asr

            logger.info("Loading Granary Parakeet-tdt model",
                       model_name=GRANARY_MODEL_NAME,
                       device=self.device)

            # Load the pretrained Parakeet-tdt model
            self.model = nemo_asr.models.ASRModel.from_pretrained(
                model_name=GRANARY_MODEL_NAME,
                map_location=self.device
            )

            # Move model to appropriate device
            if torch.cuda.is_available() and self.device == "cuda":
                self.model = self.model.cuda()

            # Set model to evaluation mode
            self.model.eval()

            self.model_loaded = True

            load_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            model_load_time.labels(model_name=GRANARY_MODEL_NAME).observe(load_time)

            logger.info("Granary model loaded successfully",
                       model_name=GRANARY_MODEL_NAME,
                       device=self.device,
                       load_time_seconds=load_time,
                       supported_languages=len(self.supported_languages))

        except Exception as e:
            self.model_loaded = False
            logger.error("Failed to load Granary model",
                        error=str(e),
                        model_name=GRANARY_MODEL_NAME)
            # Don't raise here - let individual methods handle the error

    def _ensure_model_loaded(self):
        """Ensure model is loaded, reload if needed"""
        if not self.model_loaded or not self.model:
            logger.info("Attempting to reload Granary model")
            self._load_model()

        if not self.model_loaded:
            raise HTTPException(
                status_code=503,
                detail="Granary ASR model is not available. Please try again later."
            )

    def _is_language_supported(self, language_code: str) -> bool:
        """Check if language is supported by Granary"""
        return language_code in GRANARY_LANGUAGES

    def _prepare_audio(self, audio_data: str, sample_rate: int = 16000) -> str:
        """Prepare audio data for Granary processing"""
        try:
            # Decode base64 audio
            audio_bytes = base64.b64decode(audio_data)

            # Write to temporary file for NeMo processing
            import tempfile
            import soundfile as sf
            import numpy as np

            # Convert audio bytes to numpy array (assuming 16-bit PCM)
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            audio_array = audio_array.astype(np.float32) / 32768.0  # Normalize to [-1, 1]

            # Create temporary file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                sf.write(temp_file.name, audio_array, sample_rate)
                return temp_file.name

        except Exception as e:
            logger.error("Failed to prepare audio", error=str(e))
            raise HTTPException(status_code=400, detail=f"Invalid audio data: {str(e)}")

    async def transcribe_offline(self, request: TranscribeRequest) -> TranscriptionResult:
        """Perform offline transcription using Granary"""
        start_time = datetime.now(timezone.utc)

        try:
            # Ensure model is loaded
            self._ensure_model_loaded()

            # Check language support
            if not self._is_language_supported(request.language):
                raise HTTPException(
                    status_code=400,
                    detail=f"Language {request.language} not supported by Granary. "
                           f"Supported languages: {list(self.supported_languages)}"
                )

            # Prepare audio file
            audio_file_path = self._prepare_audio(request.audio_data, request.sample_rate)

            try:
                # Perform transcription with timestamps if requested
                if request.enable_word_time_offsets:
                    hypotheses = self.model.transcribe(
                        [audio_file_path],
                        batch_size=BATCH_SIZE,
                        return_hypotheses=True,
                        timestamps=True
                    )

                    if hypotheses and len(hypotheses) > 0:
                        hypothesis = hypotheses[0]
                        transcript = hypothesis.text
                        confidence = getattr(hypothesis, 'score', 0.95)  # Default confidence

                        # Extract word timestamps if available
                        words = []
                        if hasattr(hypothesis, 'timestamp') and 'word' in hypothesis.timestamp:
                            for word_info in hypothesis.timestamp['word']:
                                words.append({
                                    'word': word_info.get('word', ''),
                                    'start_time': word_info.get('start_offset', 0) * 0.08,  # Convert to seconds
                                    'end_time': word_info.get('end_offset', 0) * 0.08,
                                    'confidence': confidence
                                })
                    else:
                        transcript = ""
                        confidence = 0.0
                        words = []
                else:
                    # Simple transcription without timestamps
                    transcripts = self.model.transcribe(
                        [audio_file_path],
                        batch_size=BATCH_SIZE
                    )

                    if transcripts and len(transcripts) > 0:
                        transcript = transcripts[0]
                        confidence = 0.95  # Default confidence for simple transcription
                        words = None
                    else:
                        transcript = ""
                        confidence = 0.0
                        words = None

            finally:
                # Clean up temporary audio file
                import os
                if os.path.exists(audio_file_path):
                    os.unlink(audio_file_path)

            # Record metrics
            processing_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            asr_requests_total.labels(
                language=request.language,
                type="offline",
                status="success",
                model="granary"
            ).inc()
            asr_request_duration.labels(
                language=request.language,
                type="offline",
                model="granary"
            ).observe(processing_time / 1000)

            return TranscriptionResult(
                transcript=transcript,
                confidence=confidence,
                words=words,
                language=request.language,
                processing_time_ms=processing_time,
                model_used="granary"
            )

        except HTTPException:
            raise
        except Exception as e:
            asr_requests_total.labels(
                language=request.language,
                type="offline",
                status="error",
                model="granary"
            ).inc()
            logger.error("Granary transcription failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

    async def detect_language(self, request: LanguageDetectionRequest) -> LanguageDetectionResult:
        """Detect language from audio using Granary transcription analysis"""
        try:
            # Ensure model is loaded
            self._ensure_model_loaded()

            # Prepare audio file (shorter sample for language detection)
            audio_file_path = self._prepare_audio(request.audio_data, request.sample_rate)

            try:
                # Quick transcription for language detection
                transcripts = self.model.transcribe(
                    [audio_file_path],
                    batch_size=1
                )

                if not transcripts or len(transcripts) == 0 or not transcripts[0].strip():
                    # Fallback if no transcription
                    return LanguageDetectionResult(
                        detected_language="en-US",
                        confidence=0.5,
                        alternatives=[]
                    )

                # Use simple heuristic language detection on transcribed text
                transcript = transcripts[0]
                detected_lang, confidence = self._detect_language_from_text(transcript)

                # Generate alternatives
                alternatives = []
                for lang_code in list(self.supported_languages)[:3]:
                    if lang_code != detected_lang:
                        alternatives.append({
                            "language": lang_code,
                            "confidence": max(0.1, confidence - 0.3)
                        })

                return LanguageDetectionResult(
                    detected_language=detected_lang,
                    confidence=confidence,
                    alternatives=alternatives[:2]
                )

            finally:
                # Clean up temporary audio file
                import os
                if os.path.exists(audio_file_path):
                    os.unlink(audio_file_path)

        except Exception as e:
            logger.error("Granary language detection failed", error=str(e))
            # Fallback to English
            return LanguageDetectionResult(
                detected_language="en-US",
                confidence=0.5,
                alternatives=[]
            )

    def _detect_language_from_text(self, text: str) -> tuple[str, float]:
        """Simple heuristic language detection from transcribed text"""
        # Language-specific common words and patterns
        language_indicators = {
            "de-DE": ["ich", "ist", "das", "der", "die", "und", "oder", "haben", "sein", "können", "mit", "von"],
            "es-ES": ["el", "la", "es", "de", "que", "en", "un", "se", "con", "para", "por", "son"],
            "fr-FR": ["le", "de", "et", "un", "il", "être", "avoir", "que", "pour", "dans", "ce", "son"],
            "it-IT": ["il", "di", "che", "è", "per", "un", "in", "con", "del", "la", "da", "sono"],
            "nl-NL": ["de", "het", "van", "een", "en", "in", "is", "dat", "te", "voor", "op", "zijn"],
            "pt-PT": ["de", "o", "a", "e", "do", "da", "em", "um", "para", "com", "não", "uma"],
            "sv-SE": ["är", "och", "i", "att", "det", "som", "på", "för", "av", "med", "den", "till"],
            "da-DK": ["og", "i", "at", "det", "er", "en", "til", "på", "med", "for", "af", "den"],
            "no-NO": ["og", "i", "det", "er", "til", "en", "på", "med", "for", "av", "som", "at"],
            "pl-PL": ["i", "w", "na", "z", "że", "do", "o", "się", "nie", "od", "po", "te"],
            "cs-CZ": ["a", "v", "na", "se", "o", "do", "s", "je", "že", "z", "to", "pro"],
            "fi-FI": ["ja", "on", "että", "ei", "ole", "se", "hän", "kun", "niin", "kuin", "vain", "jos"],
        }

        words = text.lower().split()
        if not words:
            return "en-US", 0.5

        # Score each language
        language_scores = {"en-US": 1.0}  # Default to English

        for lang_code, indicators in language_indicators.items():
            score = sum(1 for word in words if word in indicators)
            if score > 0:
                language_scores[lang_code] = score / len(words)

        # Get best match
        best_lang = max(language_scores, key=language_scores.get)
        confidence = min(0.95, language_scores[best_lang] * 2 + 0.5)

        return best_lang, confidence


# Initialize Granary ASR service
granary_service = GranaryASRService()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        model_status = "loaded" if granary_service.model_loaded else "not_loaded"

        return {
            "status": "healthy" if granary_service.model_loaded else "degraded",
            "service": "granary-asr-proxy",
            "version": "1.0.0",
            "model_loaded": granary_service.model_loaded,
            "model_name": GRANARY_MODEL_NAME,
            "device": DEVICE,
            "supported_languages": len(granary_service.supported_languages),
            "model_status": model_status
        }
    except Exception as e:
        logger.error("Granary health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "service": "granary-asr-proxy",
            "version": "1.0.0",
            "model_loaded": False,
            "error": str(e)
        }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/transcribe", response_model=TranscriptionResult)
async def transcribe_offline(request: TranscribeRequest):
    """Transcribe audio file using Granary (non-streaming)"""
    logger.info("Granary offline transcription request", language=request.language)
    return await granary_service.transcribe_offline(request)


@app.post("/detect-language", response_model=LanguageDetectionResult)
async def detect_language(request: LanguageDetectionRequest):
    """Detect language from audio using Granary"""
    logger.info("Granary language detection request")
    return await granary_service.detect_language(request)


@app.get("/supported-languages")
async def get_supported_languages():
    """Get list of 25 EU languages supported by Granary"""
    languages = []
    for lang_code in sorted(GRANARY_LANGUAGES.keys()):
        # Map language codes to display names
        lang_names = {
            "en-US": "English (US)", "en-GB": "English (UK)",
            "de-DE": "German", "fr-FR": "French", "es-ES": "Spanish",
            "it-IT": "Italian", "nl-NL": "Dutch", "sv-SE": "Swedish",
            "da-DK": "Danish", "no-NO": "Norwegian", "pt-PT": "Portuguese",
            "ro-RO": "Romanian", "ca-ES": "Catalan", "pl-PL": "Polish",
            "cs-CZ": "Czech", "sk-SK": "Slovak", "hr-HR": "Croatian",
            "sl-SI": "Slovenian", "bg-BG": "Bulgarian", "fi-FI": "Finnish",
            "hu-HU": "Hungarian", "et-EE": "Estonian", "lv-LV": "Latvian",
            "lt-LT": "Lithuanian", "el-GR": "Greek", "mt-MT": "Maltese"
        }

        languages.append({
            "code": lang_code,
            "name": lang_names.get(lang_code, lang_code)
        })

    return {
        "languages": languages,
        "total_count": len(languages),
        "model": "granary",
        "notes": "25 EU languages supported by NVIDIA Parakeet-tdt"
    }


@app.websocket("/transcribe-stream")
async def transcribe_stream(websocket: WebSocket):
    """WebSocket endpoint for streaming transcription (future implementation)"""
    await websocket.accept()
    stream_id = str(uuid.uuid4())
    logger.info("Granary streaming transcription started", stream_id=stream_id)

    active_streams.inc()

    try:
        # Send initial message about streaming capabilities
        await websocket.send_json({
            "type": "info",
            "message": "Granary streaming mode - currently processes in chunks",
            "supported_languages": list(GRANARY_LANGUAGES.keys())[:5]  # Show first 5
        })

        # For now, implement chunk-based processing
        # Future enhancement: implement true streaming with NeMo
        audio_chunks = []

        while True:
            data = await websocket.receive_json()

            if data.get("type") == "config":
                language = data.get("language", "en-US")
                await websocket.send_json({
                    "type": "config_ack",
                    "language": language,
                    "model": "granary"
                })

            elif data.get("type") == "audio":
                audio_chunks.append(data.get("audio", ""))

                # Process chunks when we have enough data (e.g., every 3 seconds)
                if len(audio_chunks) >= 3:
                    combined_audio = "".join(audio_chunks)
                    audio_chunks = []

                    # Process the chunk
                    try:
                        request = TranscribeRequest(
                            audio_data=combined_audio,
                            language=language,
                            enable_word_time_offsets=True
                        )
                        result = await granary_service.transcribe_offline(request)

                        await websocket.send_json({
                            "type": "partial",
                            "transcript": result.transcript,
                            "confidence": result.confidence,
                            "is_final": False,
                            "language": result.language,
                            "model": "granary"
                        })

                    except Exception as e:
                        logger.error("Streaming chunk processing failed", error=str(e))

            elif data.get("type") == "end_of_stream":
                # Process any remaining chunks
                if audio_chunks:
                    combined_audio = "".join(audio_chunks)
                    try:
                        request = TranscribeRequest(
                            audio_data=combined_audio,
                            language=language,
                            enable_word_time_offsets=True
                        )
                        result = await granary_service.transcribe_offline(request)

                        await websocket.send_json({
                            "type": "final",
                            "transcript": result.transcript,
                            "confidence": result.confidence,
                            "is_final": True,
                            "language": result.language,
                            "model": "granary"
                        })

                    except Exception as e:
                        logger.error("Final chunk processing failed", error=str(e))

                break

    except WebSocketDisconnect:
        logger.info("Client disconnected", stream_id=stream_id)
    except Exception as e:
        logger.error("Streaming error", error=str(e), stream_id=stream_id)
        await websocket.close(code=1000)
    finally:
        active_streams.dec()


@app.on_event("startup")
async def startup_event():
    """Initialize Granary service on startup"""
    logger.info("Starting Granary ASR Proxy",
                model_name=GRANARY_MODEL_NAME,
                device=DEVICE,
                supported_languages=len(GRANARY_LANGUAGES))

    # Verify model loading
    if granary_service.model_loaded:
        logger.info("Granary model loaded successfully at startup")
    else:
        logger.warning("Granary model failed to load at startup - will retry on first request")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down Granary ASR Proxy")

    # Clean up model resources
    if granary_service.model:
        try:
            # Clear CUDA cache if using GPU
            if hasattr(granary_service.model, 'cuda') and torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("Granary model resources cleaned up")
        except Exception as e:
            logger.error("Error cleaning up Granary model", error=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=51052,  # Different port from Riva
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