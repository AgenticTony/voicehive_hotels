"""
Enhanced TTS Client with Circuit Breaker and Backpressure Handling
Extends the original TTS client with production-ready resilience features
"""

import os
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis
from pydantic import BaseModel

from tts_client import TTSClient, TTSSynthesisRequest, TTSSynthesisResponse
from circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerManager
from backpressure_handler import BackpressureHandler, BackpressureConfig, BackpressureStrategy
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.enhanced_tts")


class EnhancedTTSClient(TTSClient):
    """
    Enhanced TTS Client with circuit breaker and backpressure handling
    """
    
    def __init__(
        self,
        tts_url: str = None,
        timeout: float = 30.0,
        redis_client: Optional[aioredis.Redis] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        backpressure_config: Optional[BackpressureConfig] = None
    ):
        super().__init__(tts_url, timeout)
        
        self.redis_client = redis_client
        
        # Initialize circuit breaker
        if circuit_breaker_config is None:
            circuit_breaker_config = CircuitBreakerConfig(
                name="tts_synthesis",
                failure_threshold=5,
                recovery_timeout=60,
                expected_exception=(httpx.HTTPError, asyncio.TimeoutError),
                timeout=timeout,
                fallback_function=self._synthesis_fallback
            )
        
        self.circuit_breaker = CircuitBreaker(circuit_breaker_config, redis_client)
        
        # Initialize backpressure handler
        if backpressure_config is None:
            backpressure_config = BackpressureConfig(
                max_queue_size=100,
                max_memory_mb=50,
                strategy=BackpressureStrategy.ADAPTIVE,
                timeout_seconds=30.0
            )
        
        self.backpressure_handler = BackpressureHandler(
            "tts_synthesis",
            backpressure_config,
            redis_client
        )
        
        # Cache for voices to reduce external calls
        self._voices_cache: Optional[Dict[str, List[Dict[str, Any]]]] = {}
        self._voices_cache_expiry: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minutes
        
        logger.info("enhanced_tts_client_initialized", tts_url=self.tts_url)
    
    async def synthesize(
        self,
        text: str,
        language: str = "en-US",
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        emotion: Optional[str] = None,
        format: str = "mp3",
        sample_rate: int = 24000,
        priority: str = "normal"
    ) -> TTSSynthesisResponse:
        """
        Enhanced synthesize method with circuit breaker and backpressure handling
        """
        # Generate unique task ID for tracking
        task_id = f"tts_{int(datetime.now().timestamp() * 1000)}_{hash(text) % 10000}"
        
        # Submit to backpressure handler for queue management
        task = await self.backpressure_handler.submit_task(
            task_id,
            self._synthesize_with_circuit_breaker,
            text, language, voice_id, speed, emotion, format, sample_rate
        )
        
        if task is None:
            # Task was dropped due to backpressure
            logger.warning("tts_synthesis_dropped", task_id=task_id, text_length=len(text))
            return await self._synthesis_fallback(text, language)
        
        try:
            return await task
        except Exception as e:
            logger.error("tts_synthesis_task_failed", task_id=task_id, error=str(e))
            return await self._synthesis_fallback(text, language)
    
    async def _synthesize_with_circuit_breaker(
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
        Internal synthesis method that uses circuit breaker
        """
        return await self.circuit_breaker.call(
            super().synthesize,
            text, language, voice_id, speed, emotion, format, sample_rate
        )
    
    async def _synthesis_fallback(
        self,
        text: str,
        language: str = "en-US",
        **kwargs
    ) -> TTSSynthesisResponse:
        """
        Fallback method when TTS service is unavailable
        Returns a minimal response indicating service unavailability
        """
        logger.info("tts_synthesis_fallback_used", text_length=len(text), language=language)
        
        # Return a placeholder response
        return TTSSynthesisResponse(
            audio_data="",  # Empty audio data
            duration_ms=len(text) * 50,  # Estimate based on text length
            engine_used="fallback",
            voice_used="system",
            cached=False,
            processing_time_ms=1.0
        )
    
    async def get_voices(
        self, 
        language: Optional[str] = None,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Enhanced get_voices with caching and circuit breaker protection
        """
        # Check cache first
        if use_cache and self._is_cache_valid():
            cache_key = language or "all"
            if cache_key in self._voices_cache:
                logger.debug("voices_cache_hit", language=language)
                return self._voices_cache[cache_key]
        
        # Use circuit breaker for external call
        try:
            voices = await self.circuit_breaker.call(super().get_voices, language)
            
            # Update cache
            if use_cache:
                self._update_voices_cache(language, voices)
            
            return voices
            
        except Exception as e:
            logger.warning("get_voices_failed_using_cache", error=str(e), language=language)
            
            # Return cached data if available
            cache_key = language or "all"
            if cache_key in self._voices_cache:
                return self._voices_cache[cache_key]
            
            # Return empty list as fallback
            return []
    
    def _is_cache_valid(self) -> bool:
        """Check if voices cache is still valid"""
        if self._voices_cache_expiry is None:
            return False
        return datetime.now() < self._voices_cache_expiry
    
    def _update_voices_cache(self, language: Optional[str], voices: List[Dict[str, Any]]):
        """Update voices cache"""
        cache_key = language or "all"
        self._voices_cache[cache_key] = voices
        self._voices_cache_expiry = datetime.now() + \
            datetime.timedelta(seconds=self._cache_ttl_seconds)
        
        logger.debug("voices_cache_updated", language=language, count=len(voices))
    
    async def health_check(self) -> bool:
        """Enhanced health check with circuit breaker awareness"""
        try:
            # Check circuit breaker state first
            stats = await self.circuit_breaker.get_stats()
            if stats.state.value == "open":
                logger.warning("tts_health_check_circuit_open")
                return False
            
            # Use circuit breaker for health check
            return await self.circuit_breaker.call(super().health_check)
            
        except Exception as e:
            logger.warning("tts_health_check_error", error=str(e))
            return False
    
    async def get_circuit_breaker_stats(self):
        """Get circuit breaker statistics"""
        return await self.circuit_breaker.get_stats()
    
    async def get_backpressure_stats(self):
        """Get backpressure handler statistics"""
        return await self.backpressure_handler.get_stats()
    
    async def reset_circuit_breaker(self):
        """Reset circuit breaker (admin function)"""
        await self.circuit_breaker.reset()
        logger.info("tts_circuit_breaker_reset")
    
    async def close(self):
        """Enhanced close method that cleans up all resources"""
        try:
            # Shutdown backpressure handler
            await self.backpressure_handler.shutdown()
            
            # Close parent HTTP client
            await super().close()
            
            logger.info("enhanced_tts_client_closed")
            
        except Exception as e:
            logger.error("enhanced_tts_client_close_error", error=str(e))


class TTSClientManager:
    """
    Manager for TTS clients with shared circuit breakers and backpressure handling
    """
    
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self.redis_client = redis_client
        self.clients: Dict[str, EnhancedTTSClient] = {}
        self.circuit_breaker_manager = CircuitBreakerManager(redis_client)
        
    def create_client(
        self,
        name: str,
        tts_url: str = None,
        timeout: float = 30.0,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        backpressure_config: Optional[BackpressureConfig] = None
    ) -> EnhancedTTSClient:
        """Create a new enhanced TTS client"""
        
        if name in self.clients:
            logger.warning("tts_client_already_exists", name=name)
            return self.clients[name]
        
        client = EnhancedTTSClient(
            tts_url=tts_url,
            timeout=timeout,
            redis_client=self.redis_client,
            circuit_breaker_config=circuit_breaker_config,
            backpressure_config=backpressure_config
        )
        
        self.clients[name] = client
        logger.info("tts_client_created", name=name, tts_url=tts_url)
        
        return client
    
    def get_client(self, name: str) -> Optional[EnhancedTTSClient]:
        """Get existing TTS client"""
        return self.clients.get(name)
    
    async def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all TTS clients"""
        stats = {}
        
        for name, client in self.clients.items():
            try:
                circuit_stats = await client.get_circuit_breaker_stats()
                backpressure_stats = await client.get_backpressure_stats()
                
                stats[name] = {
                    "circuit_breaker": circuit_stats.dict(),
                    "backpressure": backpressure_stats.dict()
                }
            except Exception as e:
                logger.error("failed_to_get_client_stats", name=name, error=str(e))
                stats[name] = {"error": str(e)}
        
        return stats
    
    async def health_check_all(self) -> Dict[str, bool]:
        """Health check all TTS clients"""
        results = {}
        
        for name, client in self.clients.items():
            try:
                results[name] = await client.health_check()
            except Exception as e:
                logger.error("tts_client_health_check_failed", name=name, error=str(e))
                results[name] = False
        
        return results
    
    async def reset_all_circuit_breakers(self):
        """Reset all circuit breakers (admin function)"""
        for client in self.clients.values():
            try:
                await client.reset_circuit_breaker()
            except Exception as e:
                logger.error("failed_to_reset_circuit_breaker", error=str(e))
        
        logger.info("all_tts_circuit_breakers_reset")
    
    async def close_all(self):
        """Close all TTS clients"""
        for name, client in self.clients.items():
            try:
                await client.close()
                logger.debug("tts_client_closed", name=name)
            except Exception as e:
                logger.error("tts_client_close_failed", name=name, error=str(e))
        
        self.clients.clear()
        logger.info("all_tts_clients_closed")


# Global TTS client manager instance
_tts_manager: Optional[TTSClientManager] = None


def get_tts_manager(redis_client: Optional[aioredis.Redis] = None) -> TTSClientManager:
    """Get or create global TTS client manager"""
    global _tts_manager
    
    if _tts_manager is None:
        _tts_manager = TTSClientManager(redis_client)
        logger.info("global_tts_manager_created")
    
    return _tts_manager


async def create_default_tts_client(
    redis_client: Optional[aioredis.Redis] = None
) -> EnhancedTTSClient:
    """Create default TTS client with standard configuration"""
    
    manager = get_tts_manager(redis_client)
    
    # Default circuit breaker config for TTS
    circuit_config = CircuitBreakerConfig(
        name="default_tts",
        failure_threshold=3,
        recovery_timeout=30,
        expected_exception=(httpx.HTTPError, asyncio.TimeoutError),
        timeout=25.0
    )
    
    # Default backpressure config for TTS
    backpressure_config = BackpressureConfig(
        max_queue_size=50,
        max_memory_mb=25,
        strategy=BackpressureStrategy.ADAPTIVE,
        timeout_seconds=20.0
    )
    
    return manager.create_client(
        "default",
        circuit_breaker_config=circuit_config,
        backpressure_config=backpressure_config
    )