#!/usr/bin/env python3
"""
TTS Router Service for VoiceHive Hotels
Routes TTS requests to appropriate engines (ElevenLabs, Azure, etc.)
"""

import asyncio
import os
import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
import base64
import hashlib

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
import structlog
import httpx
import redis.asyncio as redis
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
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

# Environment configuration
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "westeurope")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))  # 1 hour

# Prometheus metrics
tts_requests_total = Counter(
    'voicehive_tts_requests_total',
    'Total TTS requests',
    ['engine', 'language', 'status']
)
tts_request_duration = Histogram(
    'voicehive_tts_request_duration_seconds',
    'TTS request duration',
    ['engine', 'language']
)
tts_cache_hits = Counter(
    'voicehive_tts_cache_hits_total',
    'TTS cache hits'
)
tts_cache_misses = Counter(
    'voicehive_tts_cache_misses_total',
    'TTS cache misses'
)

# FastAPI app
app = FastAPI(
    title="VoiceHive TTS Router",
    description="TTS routing service with multi-engine support",
    version="1.0.0"
)


class TTSRequest(BaseModel):
    """TTS synthesis request"""
    text: str = Field(..., description="Text to synthesize")
    language: str = Field("en-US", description="Language code")
    voice_id: Optional[str] = Field(None, description="Specific voice ID")
    voice_name: Optional[str] = Field(None, description="Voice name")
    engine: Optional[str] = Field(None, description="Force specific engine")
    speed: float = Field(1.0, description="Speech speed (0.5-2.0)")
    pitch: Optional[float] = Field(None, description="Voice pitch adjustment")
    emotion: Optional[str] = Field(None, description="Emotional tone")
    format: str = Field("mp3", description="Audio format (mp3, wav, pcm)")
    sample_rate: int = Field(24000, description="Sample rate in Hz")


class TTSResponse(BaseModel):
    """TTS synthesis response"""
    audio_data: str  # Base64 encoded audio
    duration_ms: float
    engine_used: str
    voice_used: str
    cached: bool = False
    processing_time_ms: float


class VoiceInfo(BaseModel):
    """Voice information"""
    voice_id: str
    name: str
    language: str
    gender: Optional[str]
    preview_url: Optional[str]
    engine: str


class TTSRouter:
    """Routes TTS requests to appropriate engines"""
    
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.redis_client = None
        self.voice_mapping = self._initialize_voice_mapping()
        self.voice_name_lookup = self._initialize_voice_name_lookup()
        
    async def initialize(self):
        """Initialize Redis connection"""
        if CACHE_ENABLED:
            try:
                self.redis_client = await redis.from_url(REDIS_URL)
                logger.info("TTS cache initialized")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                
    def _initialize_voice_mapping(self) -> Dict[str, Dict[str, str]]:
        """Initialize language to voice mapping"""
        return {
            "en-US": {
                "elevenlabs": "21m00Tcm4TlvDq8ikWAM",  # Rachel
                "azure": "en-US-AriaNeural",
                "default_engine": "elevenlabs"
            },
            "en-GB": {
                "elevenlabs": "21m00Tcm4TlvDq8ikWAM",  # Rachel
                "azure": "en-GB-SoniaNeural",
                "default_engine": "elevenlabs"
            },
            "de-DE": {
                "elevenlabs": "pFZP5JQG7iQjIQuC4Gr",  # Antoni
                "azure": "de-DE-KatjaNeural",
                "default_engine": "azure"  # Better German support
            },
            "es-ES": {
                "elevenlabs": "zrHiDhphv9ZnVXBqCLjz",  # Matilda
                "azure": "es-ES-ElviraNeural",
                "default_engine": "elevenlabs"
            },
            "fr-FR": {
                "elevenlabs": "pFZP5JQG7iQjIQuC4Gr",  # Antoni
                "azure": "fr-FR-DeniseNeural",
                "default_engine": "azure"  # Better French support
            },
            "it-IT": {
                "elevenlabs": "zrHiDhphv9ZnVXBqCLjz",  # Matilda
                "azure": "it-IT-ElsaNeural",
                "default_engine": "azure"
            }
        }

    def _initialize_voice_name_lookup(self) -> Dict[str, Dict[str, str]]:
        """Initialize voice name to ID lookup table"""
        return {
            # ElevenLabs voices
            "rachel": {"voice_id": "21m00Tcm4TlvDq8ikWAM", "engine": "elevenlabs", "language": "en-US", "gender": "female"},
            "antoni": {"voice_id": "pFZP5JQG7iQjIQuC4Gr", "engine": "elevenlabs", "language": "en-US", "gender": "male"},
            "matilda": {"voice_id": "zrHiDhphv9ZnVXBqCLjz", "engine": "elevenlabs", "language": "en-US", "gender": "female"},
            "james": {"voice_id": "ZQe5CZNOzWyzPSCn5a3c", "engine": "elevenlabs", "language": "en-US", "gender": "male"},
            "sarah": {"voice_id": "EXAVITQu4vr4xnSDxMaL", "engine": "elevenlabs", "language": "en-US", "gender": "female"},
            "bella": {"voice_id": "EXAVITQu4vr4xnSDxMaL", "engine": "elevenlabs", "language": "en-US", "gender": "female"},
            "adam": {"voice_id": "pNInz6obpgDQGcFmaJgB", "engine": "elevenlabs", "language": "en-US", "gender": "male"},
            "eve": {"voice_id": "MF3mGyEYCl7XYWbV9V6O", "engine": "elevenlabs", "language": "en-US", "gender": "female"},

            # Azure Speech Service voices - English
            "aria": {"voice_id": "en-US-AriaNeural", "engine": "azure", "language": "en-US", "gender": "female"},
            "jenny": {"voice_id": "en-US-JennyNeural", "engine": "azure", "language": "en-US", "gender": "female"},
            "guy": {"voice_id": "en-US-GuyNeural", "engine": "azure", "language": "en-US", "gender": "male"},
            "davis": {"voice_id": "en-US-DavisNeural", "engine": "azure", "language": "en-US", "gender": "male"},
            "sonia": {"voice_id": "en-GB-SoniaNeural", "engine": "azure", "language": "en-GB", "gender": "female"},
            "ryan": {"voice_id": "en-GB-RyanNeural", "engine": "azure", "language": "en-GB", "gender": "male"},

            # Azure Speech Service voices - German
            "katja": {"voice_id": "de-DE-KatjaNeural", "engine": "azure", "language": "de-DE", "gender": "female"},
            "conrad": {"voice_id": "de-DE-ConradNeural", "engine": "azure", "language": "de-DE", "gender": "male"},
            "amala": {"voice_id": "de-DE-AmalaNeural", "engine": "azure", "language": "de-DE", "gender": "female"},

            # Azure Speech Service voices - Spanish
            "elvira": {"voice_id": "es-ES-ElviraNeural", "engine": "azure", "language": "es-ES", "gender": "female"},
            "alvaro": {"voice_id": "es-ES-AlvaroNeural", "engine": "azure", "language": "es-ES", "gender": "male"},
            "dalia": {"voice_id": "es-MX-DaliaNeural", "engine": "azure", "language": "es-MX", "gender": "female"},

            # Azure Speech Service voices - French
            "denise": {"voice_id": "fr-FR-DeniseNeural", "engine": "azure", "language": "fr-FR", "gender": "female"},
            "henri": {"voice_id": "fr-FR-HenriNeural", "engine": "azure", "language": "fr-FR", "gender": "male"},
            "brigitte": {"voice_id": "fr-FR-BrigitteNeural", "engine": "azure", "language": "fr-FR", "gender": "female"},

            # Azure Speech Service voices - Italian
            "elsa": {"voice_id": "it-IT-ElsaNeural", "engine": "azure", "language": "it-IT", "gender": "female"},
            "isabella": {"voice_id": "it-IT-IsabellaNeural", "engine": "azure", "language": "it-IT", "gender": "female"},
            "diego": {"voice_id": "it-IT-DiegoNeural", "engine": "azure", "language": "it-IT", "gender": "male"},
        }

    def _lookup_voice_by_name(self, voice_name: str, preferred_language: str = None, preferred_engine: str = None) -> tuple[str, str]:
        """
        Look up voice ID by name with optional language and engine preferences

        Args:
            voice_name: Name of the voice to look up
            preferred_language: Preferred language code (e.g., 'en-US')
            preferred_engine: Preferred engine ('elevenlabs' or 'azure')

        Returns:
            tuple: (voice_id, engine) or (voice_name, 'unknown') if not found
        """
        voice_name_lower = voice_name.lower().strip()

        # Direct lookup
        if voice_name_lower in self.voice_name_lookup:
            voice_info = self.voice_name_lookup[voice_name_lower]
            return voice_info["voice_id"], voice_info["engine"]

        # Fuzzy matching - look for partial matches
        matching_voices = []
        for name, info in self.voice_name_lookup.items():
            if voice_name_lower in name or name in voice_name_lower:
                matching_voices.append((name, info))

        if matching_voices:
            # Apply preferences to select best match
            best_match = None

            # First preference: exact engine match
            if preferred_engine:
                for name, info in matching_voices:
                    if info["engine"] == preferred_engine:
                        best_match = info
                        break

            # Second preference: language match
            if not best_match and preferred_language:
                for name, info in matching_voices:
                    if info["language"] == preferred_language:
                        best_match = info
                        break

            # Fallback: first match
            if not best_match:
                best_match = matching_voices[0][1]

            logger.info(f"Voice lookup: '{voice_name}' -> '{best_match['voice_id']}' ({best_match['engine']})")
            return best_match["voice_id"], best_match["engine"]

        # If no match found, log and return original name
        logger.warning(f"Voice lookup failed for: '{voice_name}'. Using as-is.")
        return voice_name, "unknown"

    def _get_cache_key(self, request: TTSRequest) -> str:
        """Generate cache key for TTS request"""
        key_parts = [
            request.text,
            request.language,
            request.voice_id or request.voice_name or "",
            request.engine or "",
            str(request.speed),
            str(request.pitch or ""),
            request.emotion or "",
            request.format,
            str(request.sample_rate)
        ]
        key_string = "|".join(key_parts)
        return f"tts:cache:{hashlib.sha256(key_string.encode()).hexdigest()}"
        
    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """Route TTS request to appropriate engine"""
        start_time = datetime.utcnow()
        
        # Check cache first
        if CACHE_ENABLED and self.redis_client:
            cache_key = self._get_cache_key(request)
            cached = await self._get_cached_audio(cache_key)
            if cached:
                tts_cache_hits.inc()
                return cached
            else:
                tts_cache_misses.inc()
                
        # Determine engine and voice
        engine, voice_id = self._select_engine_and_voice(request)
        
        try:
            # Route to appropriate engine
            if engine == "elevenlabs":
                audio_data, duration_ms = await self._synthesize_elevenlabs(
                    request, voice_id
                )
            elif engine == "azure":
                audio_data, duration_ms = await self._synthesize_azure(
                    request, voice_id
                )
            else:
                # Fallback to mock TTS
                audio_data, duration_ms = await self._synthesize_mock(request)
                
            # Calculate processing time
            processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            # Create response
            response = TTSResponse(
                audio_data=audio_data,
                duration_ms=duration_ms,
                engine_used=engine,
                voice_used=voice_id,
                cached=False,
                processing_time_ms=processing_time
            )
            
            # Cache the result
            if CACHE_ENABLED and self.redis_client:
                await self._cache_audio(cache_key, response)
                
            # Record metrics
            tts_requests_total.labels(
                engine=engine,
                language=request.language,
                status="success"
            ).inc()
            tts_request_duration.labels(
                engine=engine,
                language=request.language
            ).observe(processing_time / 1000)
            
            return response
            
        except Exception as e:
            tts_requests_total.labels(
                engine=engine,
                language=request.language,
                status="error"
            ).inc()
            logger.error(f"TTS synthesis failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))
            
    def _select_engine_and_voice(self, request: TTSRequest) -> tuple[str, str]:
        """Select appropriate engine and voice for request"""
        # Force engine if specified
        if request.engine:
            engine = request.engine
        else:
            # Use default engine for language
            lang_config = self.voice_mapping.get(request.language, self.voice_mapping["en-US"])
            engine = lang_config.get("default_engine", "elevenlabs")
            
        # Get voice ID
        if request.voice_id:
            voice_id = request.voice_id
        elif request.voice_name:
            # Look up voice ID by name with preferences
            voice_id, lookup_engine = self._lookup_voice_by_name(
                request.voice_name,
                preferred_language=request.language,
                preferred_engine=engine
            )

            # If a specific engine was found during lookup and no engine was forced,
            # use the engine that matches the voice
            if not request.engine and lookup_engine != "unknown":
                engine = lookup_engine

        else:
            # Use default voice for language
            lang_config = self.voice_mapping.get(request.language, self.voice_mapping["en-US"])
            voice_id = lang_config.get(engine, lang_config.get("elevenlabs"))

        return engine, voice_id
        
    async def _synthesize_elevenlabs(self, request: TTSRequest, voice_id: str) -> tuple[str, float]:
        """Synthesize using ElevenLabs API"""
        if not ELEVENLABS_API_KEY:
            raise HTTPException(status_code=500, detail="ElevenLabs API key not configured")
            
        url = f"{ELEVENLABS_API_URL}/text-to-speech/{voice_id}"
        
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "text": request.text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True
            }
        }
        
        # Adjust voice settings for emotion
        if request.emotion == "happy":
            payload["voice_settings"]["style"] = 0.5
        elif request.emotion == "sad":
            payload["voice_settings"]["stability"] = 0.3
            
        response = await self.http_client.post(
            url,
            json=payload,
            headers=headers
        )
        
        if response.status_code != 200:
            raise Exception(f"ElevenLabs API error: {response.text}")
            
        # Get audio data
        audio_bytes = response.content
        audio_base64 = base64.b64encode(audio_bytes).decode()
        
        # Estimate duration (rough calculation)
        duration_ms = len(audio_bytes) / 24  # Approximate for 24kHz
        
        return audio_base64, duration_ms
        
    async def _synthesize_azure(self, request: TTSRequest, voice_name: str) -> tuple[str, float]:
        """Synthesize using Azure Speech Service"""
        if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
            raise HTTPException(status_code=500, detail="Azure Speech Service not configured")
        
        try:
            # Construct Azure Speech Service URL
            azure_url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
            
            # Create SSML for Azure Speech Service
            ssml = f"""
            <speak version='1.0' xml:lang='{request.language}'>
                <voice xml:lang='{request.language}' name='{voice_name}'>
                    <prosody rate='{request.speed}' pitch='{request.pitch or "+0%"}'>
                        {request.text}
                    </prosody>
                </voice>
            </speak>
            """.strip()
            
            # Prepare headers
            headers = {
                "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3" if request.format == "mp3" else "riff-24khz-16bit-mono-pcm",
                "User-Agent": "VoiceHive-TTS-Router"
            }
            
            # Make request to Azure Speech Service
            response = await self.http_client.post(
                azure_url,
                content=ssml,
                headers=headers
            )
            
            if response.status_code != 200:
                error_text = response.text
                logger.error(f"Azure Speech Service error: {response.status_code} - {error_text}")
                
                # Handle specific Azure error codes according to documentation
                if response.status_code == 401:
                    raise Exception("Azure Speech Service authentication failed - check API key and region")
                elif response.status_code == 429:
                    raise Exception("Azure Speech Service rate limit exceeded - too many requests")
                elif response.status_code == 415:
                    raise Exception("Azure Speech Service unsupported media type - check Content-Type header")
                elif response.status_code == 502:
                    raise Exception("Azure Speech Service bad gateway - network or server issue")
                elif response.status_code == 503:
                    raise Exception("Azure Speech Service temporarily unavailable")
                else:
                    raise Exception(f"Azure Speech Service error: {response.status_code} - {error_text}")
            
            # Get audio data
            audio_bytes = response.content
            audio_base64 = base64.b64encode(audio_bytes).decode()
            
            # Estimate duration based on text length and speech rate
            # Rough calculation: average speaking rate is ~150 words per minute
            words = len(request.text.split())
            base_duration_seconds = (words / 150) * 60  # Base duration in seconds
            adjusted_duration = base_duration_seconds / request.speed  # Adjust for speed
            duration_ms = adjusted_duration * 1000
            
            logger.info(f"Azure TTS synthesis successful: {len(audio_bytes)} bytes, ~{duration_ms:.0f}ms")
            
            return audio_base64, duration_ms
            
        except Exception as e:
            logger.error(f"Azure Speech Service synthesis failed: {e}")
            # Fallback to mock if Azure fails
            logger.warning("Falling back to mock TTS due to Azure failure")
            return await self._synthesize_mock(request)
        
    async def _synthesize_mock(self, request: TTSRequest) -> tuple[str, float]:
        """Mock TTS synthesis for development"""
        # Generate silent audio
        sample_rate = request.sample_rate
        duration_seconds = len(request.text) * 0.06  # ~60ms per character
        num_samples = int(sample_rate * duration_seconds)
        
        # Generate silent PCM data
        pcm_data = b'\x00' * (num_samples * 2)  # 16-bit samples
        
        # Convert to base64
        audio_base64 = base64.b64encode(pcm_data).decode()
        
        # Add small delay to simulate processing
        await asyncio.sleep(0.1)
        
        return audio_base64, duration_seconds * 1000
        
    async def _get_cached_audio(self, cache_key: str) -> Optional[TTSResponse]:
        """Retrieve cached audio if available"""
        try:
            cached_json = await self.redis_client.get(cache_key)
            if cached_json:
                data = json.loads(cached_json)
                response = TTSResponse(**data)
                response.cached = True
                return response
        except Exception as e:
            logger.error(f"Cache retrieval error: {e}")
        return None
        
    async def _cache_audio(self, cache_key: str, response: TTSResponse):
        """Cache audio response"""
        try:
            await self.redis_client.setex(
                cache_key,
                CACHE_TTL_SECONDS,
                response.model_dump_json()
            )
        except Exception as e:
            logger.error(f"Cache storage error: {e}")


# Initialize router
tts_router = TTSRouter()


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    await tts_router.initialize()
    logger.info("TTS Router started")


@app.on_event("shutdown") 
async def shutdown_event():
    """Cleanup on shutdown"""
    if tts_router.http_client:
        await tts_router.http_client.aclose()
    if tts_router.redis_client:
        await tts_router.redis_client.close()
    logger.info("TTS Router shutdown")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "tts-router",
        "engines": ["elevenlabs", "azure", "mock"],
        "cache_enabled": CACHE_ENABLED
    }


@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/synthesize", response_model=TTSResponse)
async def synthesize_speech(request: TTSRequest):
    """Synthesize speech from text"""
    logger.info("TTS synthesis request", language=request.language, engine=request.engine)
    return await tts_router.synthesize(request)


@app.get("/voices", response_model=List[VoiceInfo])
async def list_voices(language: Optional[str] = None, engine: Optional[str] = None):
    """List available voices with names"""
    voices = []

    # Add voices from the name lookup table (more comprehensive)
    for voice_name, voice_info in tts_router.voice_name_lookup.items():
        # Filter by language if specified
        if language and voice_info["language"] != language:
            continue

        # Filter by engine if specified
        if engine and voice_info["engine"] != engine:
            continue

        voices.append(VoiceInfo(
            voice_id=voice_info["voice_id"],
            name=voice_name.title(),  # Capitalize name for display
            language=voice_info["language"],
            gender=voice_info.get("gender", "neutral"),
            preview_url=None,
            engine=voice_info["engine"]
        ))

    # Sort by engine, then language, then name for consistent ordering
    voices.sort(key=lambda v: (v.engine, v.language, v.name))

    return voices


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
