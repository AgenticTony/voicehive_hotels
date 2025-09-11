"""
TTS Client for orchestrator service.
Handles communication with the TTS Router service.
"""

import os
import logging
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import base64

import httpx
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

# Structured logging with graceful fallback if structlog is unavailable
try:
    import structlog  # type: ignore
    logger = structlog.get_logger(__name__)
except Exception:  # pragma: no cover - fallback for minimal test envs
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


class TTSSynthesisRequest(BaseModel):
    """Request model for TTS synthesis"""
    text: str = Field(..., description="Text to synthesize")
    language: str = Field("en-US", description="Language code")
    voice_id: Optional[str] = Field(None, description="Specific voice ID")
    voice_name: Optional[str] = Field(None, description="Voice name")
    engine: Optional[str] = Field(None, description="Force specific engine")
    speed: float = Field(1.0, description="Speech speed (0.5-2.0)")
    emotion: Optional[str] = Field(None, description="Emotional tone")
    format: str = Field("mp3", description="Audio format (mp3, wav, pcm)")
    sample_rate: int = Field(24000, description="Sample rate in Hz")


class TTSSynthesisResponse(BaseModel):
    """Response model from TTS synthesis"""
    audio_data: str  # Base64 encoded audio
    duration_ms: float
    engine_used: str
    voice_used: str
    cached: bool = False
    processing_time_ms: float


class TTSClient:
    """Client for interacting with TTS Router service"""
    
    def __init__(
        self,
        tts_url: str = None,
        timeout: float = 30.0
    ):
        self.tts_url = tts_url or os.getenv("TTS_ROUTER_URL", "http://tts-router:9000")
        # Use granular timeouts and reasonable connection limits per httpx docs
        _timeout = httpx.Timeout(timeout) if isinstance(timeout, (int, float)) else timeout
        self.http_client = httpx.AsyncClient(
            timeout=_timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            headers={
                "User-Agent": "VoiceHive-Orchestrator/1.0 (+https://voicehive-hotels.example)",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        self.default_voices = self._get_default_voices()
        
    def _get_default_voices(self) -> Dict[str, str]:
        """Get default voices per language"""
        return {
            "en-US": "en-US-AriaNeural",
            "en-GB": "en-GB-SoniaNeural",
            "de-DE": "de-DE-KatjaNeural",
            "es-ES": "es-ES-ElviraNeural",
            "fr-FR": "fr-FR-DeniseNeural",
            "it-IT": "it-IT-ElsaNeural",
            "nl-NL": "nl-NL-ColetteNeural",
            "pt-PT": "pt-PT-FernandaNeural",
            "pl-PL": "pl-PL-ZofiaNeural",
            "ru-RU": "ru-RU-SvetlanaNeural",
            "ja-JP": "ja-JP-NanamiNeural",
            "zh-CN": "zh-CN-XiaoxiaoNeural"
        }
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=5)
    )
    async def synthesize(
        self,
        text: str,
        language: str = "en-US",
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        emotion: Optional[str] = None,
        format: str = "mp3",
        sample_rate: int = 24000
    ) -> TTSSynthesisResponse:
        """
        Synthesize text to speech using TTS Router.
        
        Args:
            text: Text to synthesize
            language: Language code (e.g., en-US, de-DE)
            voice_id: Optional specific voice ID
            speed: Speech speed multiplier
            emotion: Optional emotional tone
            format: Audio format (mp3, wav, pcm)
            sample_rate: Sample rate in Hz
            
        Returns:
            TTSSynthesisResponse with audio data
        """
        start_time = datetime.now(timezone.utc)
        
        # Do not select a default voice_id here; let the TTS Router choose the best engine/voice
        request = TTSSynthesisRequest(
            text=text,
            language=language,
            voice_id=voice_id,
            speed=speed,
            emotion=emotion,
            format=format,
            sample_rate=sample_rate
        )
        
        try:
            response = await self.http_client.post(
                f"{self.tts_url}/synthesize",
                json=request.model_dump()
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Calculate processing time
            processing_time_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            
            logger.info(
                "tts_synthesis_completed",
                language=language,
                engine_used=data.get("engine_used"),
                duration_ms=data.get("duration_ms"),
                processing_time_ms=processing_time_ms,
                cached=data.get("cached", False)
            )
            
            return TTSSynthesisResponse(
                audio_data=data["audio_data"],
                duration_ms=data["duration_ms"],
                engine_used=data["engine_used"],
                voice_used=data["voice_used"],
                cached=data.get("cached", False),
                processing_time_ms=processing_time_ms
            )
            
        except httpx.HTTPStatusError as e:
            logger.error(
                "tts_synthesis_failed",
                status_code=e.response.status_code,
                error=str(e),
                language=language
            )
            raise
        except Exception as e:
            logger.error(
                "tts_synthesis_error",
                error=str(e),
                language=language
            )
            raise
            
    async def get_voices(self, language: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get available voices from TTS Router.
        
        Args:
            language: Optional language filter
            
        Returns:
            List of available voices
        """
        try:
            params = {}
            if language:
                params["language"] = language
                
            response = await self.http_client.get(
                f"{self.tts_url}/voices",
                params=params
            )
            response.raise_for_status()
            
            return response.json()["voices"]
            
        except Exception as e:
            logger.error(
                "Failed to fetch voices",
                error=str(e),
                language=language
            )
            return []
            
    async def health_check(self) -> bool:
        """Check if TTS Router is healthy"""
        try:
            response = await self.http_client.get(f"{self.tts_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.warning("tts_health_check_error", error=str(e))
            return False
            
    async def close(self):
        """Close HTTP client"""
        await self.http_client.aclose()
        
    async def __aenter__(self):
        """Async context manager entry"""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Convenience function for quick synthesis
async def synthesize_text(
    text: str,
    language: str = "en-US",
    tts_url: Optional[str] = None
) -> TTSSynthesisResponse:
    """
    Convenience function for synthesizing text.
    
    Args:
        text: Text to synthesize
        language: Language code
        tts_url: Optional TTS Router URL
        
    Returns:
        TTSSynthesisResponse
    """
    async with TTSClient(tts_url=tts_url) as client:
        return await client.synthesize(text, language)
