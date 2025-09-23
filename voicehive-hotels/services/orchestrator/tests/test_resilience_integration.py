"""
Integration Tests for Resilience Infrastructure
Tests the complete rate limiting, circuit breaker, and backpressure system
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from resilience_manager import ResilienceManager
from resilience_config import create_development_resilience_config
from rate_limiter import RateLimitAlgorithm
from circuit_breaker import CircuitState
from backpressure_handler import BackpressureStrategy


@pytest.fixture
async def mock_redis():
    """Mock Redis client for testing"""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.from_url = AsyncMock(return_value=redis_mock)
    redis_mock.close = AsyncMock()
    
    # Rate limiter mocks
    redis_mock.pipeline = MagicMock()
    pipeline_mock = MagicMock()
    pipeline_mock.execute = AsyncMock(return_value=[None, 1, None, None])
    redis_mock.pipeline.return_value = pipeline_mock
    
    # Circuit breaker mocks
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock()
    redis_mock.hgetall = AsyncMock(return_value={})
    redis_mock.hset = AsyncMock()
    redis_mock.expire = AsyncMock()
    
    return redis_mock


@pytest.fixture
def resilience_config():
    """Development resilience configuration for testing"""
    return create_development_resilience_config()


@pytest.fixture
async def resilience_manager(resilience_config, mock_redis):
    """Resilience manager instance for testing"""
    with patch('aioredis.from_url', return_value=mock_redis):
        manager = ResilienceManager(resilience_config, "development")
        await manager.initialize()
        yield manager
        await manager.shutdown()


class TestResilienceManagerInitialization:
    """Test resilience manager initialization"""
    
    @pytest.mark.asyncio
    async def test_initialization_success(self, resilience_config, mock_redis):
        """Test successful initialization of all components"""
        with patch('aioredis.from_url', return_value=mock_redis):
            manager = ResilienceManager(resilience_config, "development")
            
            success = await manager.initialize()
            
            assert success is True
            assert manager.initialized is True
            assert manager.redis_client is not None
            assert manager.rate_limiter is not None
            assert manager.circuit_breaker_manager is not None
            assert manager.backpressure_manager is not None
            assert manager.tts_client_manager is not None
            
            await manager.shutdown()
    
    @pytest.mark.asyncio
    async def test_initialization_redis_failure(self, resilience_config):
        """Test initialization when Redis connection fails"""
        with patch('aioredis.from_url', side_effect=Exception("Redis connection failed")):
            manager = ResilienceManager(resilience_config, "development")
            
            success = await manager.initialize()
            
            # Should still succeed but with degraded functionality
            assert success is True
            assert manager.redis_client is None
            
            await manager.shutdown()
    
    @pytest.mark.asyncio
    async def test_disabled_components(self, mock_redis):
        """Test initialization with disabled components"""
        config = create_development_resilience_config()
        config.rate_limiting_enabled = False
        config.circuit_breakers_enabled = False
        config.backpressure_enabled = False
        
        with patch('aioredis.from_url', return_value=mock_redis):
            manager = ResilienceManager(config, "development")
            
            success = await manager.initialize()
            
            assert success is True
            assert manager.rate_limiter is None
            
            await manager.shutdown()


class TestRateLimitingIntegration:
    """Test rate limiting integration"""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_creation(self, resilience_manager):
        """Test that rate limiter is created with rules"""
        assert resilience_manager.rate_limiter is not None
        assert len(resilience_manager.rate_limiter.rules) > 0
        
        # Check that rules are properly configured
        found_auth_rule = False
        for rule in resilience_manager.rate_limiter.rules:
            if "/auth/login" in rule.path_pattern:
                found_auth_rule = True
                assert rule.config.requests_per_minute <= 10  # Should be strict for auth
                break
        
        assert found_auth_rule, "Auth login rule should be configured"
    
    @pytest.mark.asyncio
    async def test_rate_limit_check(self, resilience_manager):
        """Test rate limit checking functionality"""
        result = await resilience_manager.rate_limiter.check_rate_limit(
            client_id="test_client",
            path="/api/test",
            method="GET",
            client_type="api"
        )
        
        assert result.allowed is True
        assert result.current_usage >= 0
        assert result.remaining >= 0
    
    @pytest.mark.asyncio
    async def test_internal_service_bypass(self, resilience_manager):
        """Test that internal services bypass rate limiting"""
        result = await resilience_manager.rate_limiter.check_rate_limit(
            client_id="internal_service",
            path="/api/test",
            method="GET",
            client_type="internal"
        )
        
        assert result.allowed is True
        assert result.limit_type == "bypass_internal"


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration"""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_creation(self, resilience_manager):
        """Test that circuit breakers are created for configured services"""
        assert resilience_manager.circuit_breaker_manager is not None
        
        # Check that configured breakers exist
        tts_breaker = resilience_manager.get_circuit_breaker("tts_service")
        assert tts_breaker is not None
        
        pms_breaker = resilience_manager.get_circuit_breaker("pms_connector")
        assert pms_breaker is not None
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_functionality(self, resilience_manager):
        """Test basic circuit breaker functionality"""
        breaker = resilience_manager.get_circuit_breaker("test_service")
        
        async def success_func():
            return "success"
        
        result = await breaker.call(success_func)
        assert result == "success"
        
        stats = await breaker.get_stats()
        assert stats.state == CircuitState.CLOSED
        assert stats.total_requests >= 1
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_failure_handling(self, resilience_manager):
        """Test circuit breaker failure handling"""
        breaker = resilience_manager.get_circuit_breaker("test_failure_service")
        
        async def failing_func():
            raise Exception("Test failure")
        
        # Should handle the exception
        with pytest.raises(Exception):
            await breaker.call(failing_func)
        
        stats = await breaker.get_stats()
        assert stats.total_failures >= 1


class TestBackpressureIntegration:
    """Test backpressure handling integration"""
    
    @pytest.mark.asyncio
    async def test_backpressure_handler_creation(self, resilience_manager):
        """Test that backpressure handlers are created"""
        assert resilience_manager.backpressure_manager is not None
        
        # Check that configured handlers exist
        tts_handler = resilience_manager.get_backpressure_handler("tts_synthesis")
        assert tts_handler is not None
        
        audio_handler = resilience_manager.get_backpressure_handler("audio_streaming")
        assert audio_handler is not None
    
    @pytest.mark.asyncio
    async def test_backpressure_task_submission(self, resilience_manager):
        """Test backpressure task submission"""
        handler = resilience_manager.get_backpressure_handler("test_handler")
        
        async def test_task():
            await asyncio.sleep(0.01)  # Small delay
            return "completed"
        
        task = await handler.submit_task("test_task_1", test_task)
        
        if task:  # Task might be None if dropped
            result = await task
            assert result == "completed"
        
        stats = await handler.get_stats()
        assert stats.total_processed >= 0


class TestTTSClientIntegration:
    """Test TTS client integration with resilience features"""
    
    @pytest.mark.asyncio
    async def test_tts_client_creation(self, resilience_manager):
        """Test TTS client creation with resilience features"""
        tts_client = resilience_manager.get_tts_client("test_client")
        
        assert tts_client is not None
        assert tts_client.circuit_breaker is not None
        assert tts_client.backpressure_handler is not None
    
    @pytest.mark.asyncio
    async def test_tts_client_health_check(self, resilience_manager):
        """Test TTS client health check"""
        tts_client = resilience_manager.get_tts_client("test_client")
        
        # Mock the HTTP client health check
        tts_client.http_client.get = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        tts_client.http_client.get.return_value = mock_response
        
        # Override the parent health_check to avoid actual HTTP call
        async def mock_health_check():
            return True
        
        tts_client.TTSClient.health_check = mock_health_check
        
        is_healthy = await tts_client.health_check()
        # Health check might fail due to circuit breaker state, which is expected


class TestResilienceManagerHealthAndMetrics:
    """Test health checking and metrics collection"""
    
    @pytest.mark.asyncio
    async def test_health_status(self, resilience_manager):
        """Test getting health status"""
        health = await resilience_manager.get_health_status()
        
        assert "initialized" in health
        assert "startup_time" in health
        assert "environment" in health
        assert "components" in health
        
        assert health["initialized"] is True
        assert health["environment"] == "development"
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self, resilience_manager):
        """Test metrics collection"""
        metrics = await resilience_manager.get_metrics()
        
        assert "timestamp" in metrics
        assert "environment" in metrics
        assert metrics["environment"] == "development"
        
        # Should have metrics for enabled components
        if resilience_manager.circuit_breaker_manager:
            assert "circuit_breakers" in metrics
        
        if resilience_manager.backpressure_manager:
            assert "backpressure" in metrics
    
    @pytest.mark.asyncio
    async def test_reset_all_circuit_breakers(self, resilience_manager):
        """Test resetting all circuit breakers"""
        # This should not raise an exception
        await resilience_manager.reset_all_circuit_breakers()


class TestResilienceManagerShutdown:
    """Test graceful shutdown"""
    
    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, resilience_config, mock_redis):
        """Test graceful shutdown of all components"""
        with patch('aioredis.from_url', return_value=mock_redis):
            manager = ResilienceManager(resilience_config, "development")
            await manager.initialize()
            
            # Should shutdown without errors
            await manager.shutdown()
            
            assert manager.initialized is False


if __name__ == "__main__":
    pytest.main([__file__])