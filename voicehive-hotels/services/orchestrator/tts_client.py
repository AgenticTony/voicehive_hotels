"""
TTS Client for orchestrator service.
Handles communication with the TTS Router service.
"""

import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_random_exponential
import redis.asyncio as aioredis

try:
    # Try absolute import first (for when module is imported from outside)
    from services.orchestrator.logging_adapter import get_safe_logger
except ImportError:
    # Fall back to relative import (for when running tests)
    from logging_adapter import get_safe_logger
from prometheus_client import Histogram, Counter

# Import circuit breaker from resilience infrastructure
try:
    from resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitBreakerTimeoutError
    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError as e:
    # Fallback - circuit breaker not available
    logger.warning(f"Circuit breaker not available for TTS client: {e}")
    CircuitBreaker = None
    CircuitBreakerConfig = None
    CircuitBreakerOpenError = Exception
    CircuitBreakerTimeoutError = Exception
    CIRCUIT_BREAKER_AVAILABLE = False

# Use safe logger adapter
logger = get_safe_logger(__name__)

# Prometheus metrics for TTS performance monitoring
tts_synthesis_duration_seconds = Histogram(
    'voicehive_tts_synthesis_duration_seconds',
    'TTS synthesis duration in seconds',
    ['language', 'engine', 'cached'],
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)
)

tts_synthesis_total = Counter(
    'voicehive_tts_synthesis_total',
    'Total TTS synthesis requests',
    ['language', 'engine', 'status']
)

tts_synthesis_errors = Counter(
    'voicehive_tts_synthesis_errors',
    'TTS synthesis errors',
    ['language', 'error_type']
)


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
    """Client for interacting with TTS Router service with circuit breaker protection"""

    def __init__(
        self,
        tts_url: str = None,
        timeout: float = 30.0,
        redis_url: str = None
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

        # Initialize circuit breakers if available
        self._circuit_breakers = {}
        if CIRCUIT_BREAKER_AVAILABLE and CircuitBreaker is not None:
            # Get Redis client from parameter or environment (optional)
            redis_client = None
            redis_url = redis_url or os.getenv("REDIS_URL")
            if redis_url:
                try:
                    redis_client = aioredis.from_url(redis_url)
                except Exception as e:
                    logger.warning(f"Failed to connect to Redis for TTS circuit breaker: {e}")

            # Circuit breaker for TTS synthesis (main operations)
            synthesis_config = CircuitBreakerConfig(
                name="tts_synthesis",
                failure_threshold=5,  # More tolerant for synthesis operations
                recovery_timeout=60,  # 1 minute recovery for synthesis
                timeout=45.0,  # Synthesis can take longer than default timeout
                expected_exception=(httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException)
            )
            self._circuit_breakers["synthesis"] = CircuitBreaker(synthesis_config, redis_client)

            # Circuit breaker for TTS metadata operations (voices, health)
            metadata_config = CircuitBreakerConfig(
                name="tts_metadata",
                failure_threshold=3,  # Fail faster for metadata operations
                recovery_timeout=30,  # Quicker recovery for metadata
                timeout=15.0,  # Metadata operations should be fast
                expected_exception=(httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException)
            )
            self._circuit_breakers["metadata"] = CircuitBreaker(metadata_config, redis_client)

            logger.info("TTS circuit breakers initialized",
                       synthesis_threshold=synthesis_config.failure_threshold,
                       metadata_threshold=metadata_config.failure_threshold,
                       tts_url=self.tts_url)
        else:
            logger.warning("Circuit breaker not available for TTS client")
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=10),
        reraise=True
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
        Synthesize text to speech using TTS Router with circuit breaker protection.

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

        async def _do_synthesis():
            """Inner synthesis function for circuit breaker"""
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

            response = await self.http_client.post(
                f"{self.tts_url}/synthesize",
                json=request.model_dump()
            )
            response.raise_for_status()

            data = response.json()

            # Calculate processing time
            processing_time_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            processing_time_seconds = processing_time_ms / 1000.0

            # Record Prometheus metrics
            tts_synthesis_duration_seconds.labels(
                language=language,
                engine=data.get("engine_used", "unknown"),
                cached=str(data.get("cached", False))
            ).observe(processing_time_seconds)

            tts_synthesis_total.labels(
                language=language,
                engine=data.get("engine_used", "unknown"),
                status="success"
            ).inc()

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

        try:
            # Use circuit breaker if available
            if "synthesis" in self._circuit_breakers:
                return await self._circuit_breakers["synthesis"].call(_do_synthesis)
            else:
                return await _do_synthesis()

        except CircuitBreakerOpenError as e:
            # Record circuit breaker metrics
            tts_synthesis_total.labels(
                language=language,
                engine="unknown",
                status="circuit_breaker_open"
            ).inc()

            tts_synthesis_errors.labels(
                language=language,
                error_type="circuit_breaker_open"
            ).inc()

            logger.error(
                "tts_synthesis_circuit_breaker_open",
                circuit_name=e.circuit_name,
                next_attempt=e.next_attempt_time,
                language=language,
                text_length=len(text)
            )
            raise Exception(f"TTS service temporarily unavailable: {e}")

        except CircuitBreakerTimeoutError as e:
            # Record timeout metrics
            tts_synthesis_total.labels(
                language=language,
                engine="unknown",
                status="timeout"
            ).inc()

            tts_synthesis_errors.labels(
                language=language,
                error_type="circuit_breaker_timeout"
            ).inc()

            logger.error(
                "tts_synthesis_timeout",
                error=str(e),
                language=language,
                text_length=len(text)
            )
            raise Exception(f"TTS synthesis timeout: {e}")

        except httpx.HTTPStatusError as e:
            # Record error metrics
            tts_synthesis_total.labels(
                language=language,
                engine="unknown",
                status="error"
            ).inc()

            tts_synthesis_errors.labels(
                language=language,
                error_type="http_error"
            ).inc()

            logger.error(
                "tts_synthesis_failed",
                status_code=e.response.status_code,
                error=str(e),
                language=language
            )
            raise

        except Exception as e:
            # Record error metrics
            tts_synthesis_total.labels(
                language=language,
                engine="unknown",
                status="error"
            ).inc()

            tts_synthesis_errors.labels(
                language=language,
                error_type=type(e).__name__
            ).inc()

            logger.error(
                "tts_synthesis_error",
                error=str(e),
                language=language
            )
            raise
            
    async def get_voices(self, language: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get available voices from TTS Router with circuit breaker protection.

        Args:
            language: Optional language filter

        Returns:
            List of available voices
        """

        async def _do_get_voices():
            """Inner get voices function for circuit breaker"""
            params = {}
            if language:
                params["language"] = language

            response = await self.http_client.get(
                f"{self.tts_url}/voices",
                params=params
            )
            response.raise_for_status()

            return response.json()["voices"]

        try:
            # Use circuit breaker if available
            if "metadata" in self._circuit_breakers:
                return await self._circuit_breakers["metadata"].call(_do_get_voices)
            else:
                return await _do_get_voices()

        except CircuitBreakerOpenError as e:
            logger.error(
                "tts_voices_circuit_breaker_open",
                circuit_name=e.circuit_name,
                next_attempt=e.next_attempt_time,
                language=language
            )
            return []  # Return empty list as graceful degradation

        except CircuitBreakerTimeoutError as e:
            logger.error(
                "tts_voices_timeout",
                error=str(e),
                language=language
            )
            return []  # Return empty list as graceful degradation

        except Exception as e:
            logger.error(
                "failed_to_fetch_voices",
                error=str(e),
                language=language
            )
            return []

    async def health_check(self) -> Dict[str, Any]:
        """Check if TTS Router is healthy with circuit breaker information"""

        async def _do_health_check():
            """Inner health check function for circuit breaker"""
            response = await self.http_client.get(f"{self.tts_url}/health")
            response.raise_for_status()
            return response.json() if response.content else {"status": "healthy"}

        # Get circuit breaker statistics
        circuit_breaker_stats = await self.get_circuit_breaker_stats()

        try:
            # Use circuit breaker if available
            if "metadata" in self._circuit_breakers:
                health_data = await self._circuit_breakers["metadata"].call(_do_health_check)
            else:
                health_data = await _do_health_check()

            return {
                "status": "healthy",
                "service": "tts_router",
                "url": self.tts_url,
                "tts_service_status": health_data.get("status", "healthy"),
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except CircuitBreakerOpenError as e:
            return {
                "status": "degraded",
                "service": "tts_router",
                "url": self.tts_url,
                "error": f"Circuit breaker open: {e}",
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "service": "tts_router",
                "url": self.tts_url,
                "error": str(e),
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

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
