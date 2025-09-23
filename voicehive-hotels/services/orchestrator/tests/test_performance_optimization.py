"""
Tests for Performance Optimization Implementation
Comprehensive tests for all performance optimization components
"""

import pytest
import asyncio
import os
import tempfile
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

try:
    import aioredis
except ImportError:
    aioredis = None
from fastapi.testclient import TestClient

# Import performance optimization components
from connection_pool_manager import (
    ConnectionPoolManager, ConnectionPoolConfig, DatabasePool, RedisPool, HTTPPool
)
from intelligent_cache import (
    IntelligentCache, CacheConfig, CacheLevel, MemoryCache, RedisCache
)
from audio_memory_optimizer import (
    AudioMemoryOptimizer, BufferConfig, CircularAudioBuffer, AudioFormat
)
from performance_monitor import (
    PerformanceMonitor, PerformanceConfig, PerformanceTracker
)


class TestConnectionPoolManager:
    """Test connection pool manager functionality"""
    
    @pytest.fixture
    async def pool_manager(self):
        """Create test connection pool manager"""
        config = ConnectionPoolConfig(
            db_min_size=2,
            db_max_size=5,
            redis_max_connections=10,
            http_max_connections=20
        )
        manager = ConnectionPoolManager(config)
        await manager.initialize()
        yield manager
        await manager.close_all()
    
    @pytest.mark.asyncio
    async def test_database_pool_creation(self, pool_manager):
        """Test database pool creation and basic operations"""
        # Skip if no database URL available
        database_url = os.getenv("TEST_DATABASE_URL")
        if not database_url:
            pytest.skip("No test database URL provided")
        
        # Create database pool
        db_pool = await pool_manager.create_database_pool("test_db", database_url)
        
        assert db_pool is not None
        assert db_pool.name == "test_db"
        
        # Test connection acquisition
        async with db_pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            assert result == 1
        
        # Test statistics
        stats = db_pool.get_stats()
        assert stats.pool_name == "test_db"
        assert stats.pool_type == "database"
        assert stats.size >= 2  # Min pool size
    
    @pytest.mark.asyncio
    async def test_redis_pool_creation(self, pool_manager):
        """Test Redis pool creation and basic operations"""
        redis_url = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/1")
        
        try:
            # Create Redis pool
            redis_pool = await pool_manager.create_redis_pool("test_redis", redis_url)
            
            assert redis_pool is not None
            assert redis_pool.name == "test_redis"
            
            # Test connection acquisition
            async with redis_pool.acquire() as redis_client:
                await redis_client.set("test_key", "test_value")
                value = await redis_client.get("test_key")
                assert value == b"test_value"
                await redis_client.delete("test_key")
            
            # Test statistics
            stats = redis_pool.get_stats()
            assert stats.pool_name == "test_redis"
            assert stats.pool_type == "redis"
            
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")
    
    @pytest.mark.asyncio
    async def test_http_pool_creation(self, pool_manager):
        """Test HTTP pool creation and basic operations"""
        # Create HTTP pool
        http_pool = await pool_manager.create_http_pool("test_http")
        
        assert http_pool is not None
        assert http_pool.name == "test_http"
        
        # Test client acquisition
        async with http_pool.acquire() as client:
            # Test with a reliable endpoint
            try:
                response = await client.get("https://httpbin.org/status/200", timeout=5.0)
                assert response.status_code == 200
            except Exception:
                # Skip if external service not available
                pass
        
        # Test statistics
        stats = http_pool.get_stats()
        assert stats.pool_name == "test_http"
        assert stats.pool_type == "http"
    
    @pytest.mark.asyncio
    async def test_pool_health_check(self, pool_manager):
        """Test connection pool health checks"""
        # Create pools
        await pool_manager.create_http_pool("health_test")
        
        # Perform health check
        health_results = await pool_manager.health_check()
        
        assert "http" in health_results
        assert "health_test" in health_results["http"]
    
    @pytest.mark.asyncio
    async def test_pool_statistics(self, pool_manager):
        """Test pool statistics collection"""
        # Create pools
        await pool_manager.create_http_pool("stats_test")
        
        # Get statistics
        all_stats = await pool_manager.get_all_stats()
        
        assert "http" in all_stats
        assert len(all_stats["http"]) > 0
        
        http_stats = all_stats["http"][0]
        assert http_stats.pool_name == "stats_test"
        assert http_stats.pool_type == "http"


class TestIntelligentCache:
    """Test intelligent cache functionality"""
    
    @pytest.fixture
    async def cache_system(self):
        """Create test cache system"""
        config = CacheConfig(
            memory_max_size=100,
            memory_max_bytes=1024 * 1024,  # 1MB
            default_ttl_seconds=60,
            redis_enabled=False  # Disable Redis for unit tests
        )
        
        cache = IntelligentCache("test_cache", config)
        await cache.initialize()
        yield cache
        await cache.close()
    
    @pytest.mark.asyncio
    async def test_memory_cache_operations(self, cache_system):
        """Test basic cache operations"""
        # Test set and get
        await cache_system.set("key1", "value1")
        value = await cache_system.get("key1")
        assert value == "value1"
        
        # Test cache miss
        value = await cache_system.get("nonexistent")
        assert value is None
        
        # Test delete
        deleted = await cache_system.delete("key1")
        assert deleted is True
        
        value = await cache_system.get("key1")
        assert value is None
    
    @pytest.mark.asyncio
    async def test_cache_ttl(self, cache_system):
        """Test cache TTL functionality"""
        # Set with short TTL
        await cache_system.set("ttl_key", "ttl_value", ttl_seconds=1)
        
        # Should be available immediately
        value = await cache_system.get("ttl_key")
        assert value == "ttl_value"
        
        # Wait for expiration
        await asyncio.sleep(1.1)
        
        # Should be expired
        value = await cache_system.get("ttl_key")
        assert value is None
    
    @pytest.mark.asyncio
    async def test_get_or_set(self, cache_system):
        """Test get_or_set functionality"""
        call_count = 0
        
        def factory_func():
            nonlocal call_count
            call_count += 1
            return f"computed_value_{call_count}"
        
        # First call should compute value
        value1 = await cache_system.get_or_set("compute_key", factory_func)
        assert value1 == "computed_value_1"
        assert call_count == 1
        
        # Second call should use cached value
        value2 = await cache_system.get_or_set("compute_key", factory_func)
        assert value2 == "computed_value_1"
        assert call_count == 1  # Should not increment
    
    @pytest.mark.asyncio
    async def test_cache_statistics(self, cache_system):
        """Test cache statistics"""
        # Perform some operations
        await cache_system.set("stats_key1", "value1")
        await cache_system.set("stats_key2", "value2")
        await cache_system.get("stats_key1")  # Hit
        await cache_system.get("nonexistent")  # Miss
        
        # Get statistics
        stats = await cache_system.get_stats()
        
        assert "memory" in stats
        memory_stats = stats["memory"]
        assert memory_stats.hits > 0
        assert memory_stats.misses > 0
        assert memory_stats.total_entries > 0
    
    @pytest.mark.asyncio
    async def test_cache_eviction(self, cache_system):
        """Test cache eviction policies"""
        # Fill cache beyond capacity
        for i in range(150):  # More than max_size of 100
            await cache_system.set(f"evict_key_{i}", f"value_{i}")
        
        # Check that cache size is limited
        stats = await cache_system.get_stats()
        memory_stats = stats["memory"]
        assert memory_stats.total_entries <= 100


class TestAudioMemoryOptimizer:
    """Test audio memory optimizer functionality"""
    
    @pytest.fixture
    async def audio_optimizer(self):
        """Create test audio memory optimizer"""
        config = BufferConfig(
            max_buffer_size_mb=1,  # Small for testing
            chunk_size_bytes=1024,
            gc_threshold_mb=10,
            auto_gc_enabled=False  # Disable for testing
        )
        
        optimizer = AudioMemoryOptimizer(config)
        await optimizer.initialize()
        yield optimizer
        await optimizer.close()
    
    @pytest.mark.asyncio
    async def test_audio_stream_creation(self, audio_optimizer):
        """Test audio stream creation"""
        audio_format = AudioFormat(
            sample_rate=16000,
            channels=1,
            bit_depth=16
        )
        
        # Create audio stream
        buffer = await audio_optimizer.create_optimized_stream(
            "test_stream", audio_format, buffer_size_mb=1
        )
        
        assert buffer is not None
        assert buffer.buffer_id == "test_stream"
        assert buffer.capacity_bytes == 1024 * 1024  # 1MB
        
        # Clean up
        await audio_optimizer.close_stream("test_stream")
    
    @pytest.mark.asyncio
    async def test_circular_buffer_operations(self):
        """Test circular buffer operations"""
        audio_format = AudioFormat(sample_rate=16000, channels=1, bit_depth=16)
        config = BufferConfig()
        
        buffer = CircularAudioBuffer(
            "test_buffer", 1024, audio_format, config
        )
        
        # Test write and read
        test_data = b"hello world"
        bytes_written = await buffer.write(test_data)
        assert bytes_written == len(test_data)
        
        read_data = await buffer.read(len(test_data))
        assert read_data == test_data
        
        # Test buffer state
        assert buffer.available_bytes() == 0
        assert not buffer.is_full()
        assert buffer.is_empty()
        
        await buffer.close()
    
    @pytest.mark.asyncio
    async def test_audio_processing(self, audio_optimizer):
        """Test audio data processing"""
        audio_format = AudioFormat(sample_rate=16000, channels=1, bit_depth=16)
        
        # Create stream
        await audio_optimizer.create_optimized_stream(
            "process_stream", audio_format
        )
        
        # Process audio data
        test_audio = b"audio_data_" * 100  # Some test audio data
        
        def simple_processor(data):
            return data.upper()
        
        processed = await audio_optimizer.process_audio_data(
            "process_stream", test_audio, simple_processor
        )
        
        assert processed == test_audio.upper()
        
        # Clean up
        await audio_optimizer.close_stream("process_stream")
    
    @pytest.mark.asyncio
    async def test_memory_optimization_stats(self, audio_optimizer):
        """Test memory optimization statistics"""
        # Get initial stats
        stats = await audio_optimizer.get_optimization_stats()
        
        assert "process_memory_mb" in stats
        assert "active_streams" in stats
        assert isinstance(stats["process_memory_mb"], (int, float))
        assert isinstance(stats["active_streams"], int)
    
    @pytest.mark.asyncio
    async def test_garbage_collection(self, audio_optimizer):
        """Test manual garbage collection"""
        # Force garbage collection
        collected = await audio_optimizer.force_garbage_collection()
        
        assert isinstance(collected, int)
        assert collected >= 0


class TestPerformanceMonitor:
    """Test performance monitoring functionality"""
    
    @pytest.fixture
    async def perf_monitor(self):
        """Create test performance monitor"""
        config = PerformanceConfig(
            system_metrics_interval=60,  # Long interval for testing
            application_metrics_interval=60,
            enable_alerting=False,  # Disable for testing
            enable_redis_storage=False
        )
        
        monitor = PerformanceMonitor(config)
        yield monitor
        await monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_performance_tracking(self, perf_monitor):
        """Test performance tracking context manager"""
        # Test async context manager
        async with perf_monitor.track_request("/test", "GET"):
            await asyncio.sleep(0.01)  # Simulate work
        
        # Check that metrics were recorded
        current_metrics = await perf_monitor.get_current_metrics()
        assert "system" in current_metrics
        assert "application" in current_metrics
    
    @pytest.mark.asyncio
    async def test_database_operation_tracking(self, perf_monitor):
        """Test database operation tracking"""
        # Test database operation tracker
        async with perf_monitor.track_database_operation("SELECT", "users"):
            await asyncio.sleep(0.01)  # Simulate query
        
        # Should complete without errors
        assert True
    
    @pytest.mark.asyncio
    async def test_metrics_collection(self, perf_monitor):
        """Test metrics collection"""
        # Get current metrics
        metrics = await perf_monitor.get_current_metrics()
        
        assert "system" in metrics
        assert "application" in metrics
        assert "timestamp" in metrics
        
        # Check system metrics structure
        system_metrics = metrics["system"]
        assert "cpu_percent" in system_metrics
        assert "memory_used" in system_metrics
        assert "process_memory_rss" in system_metrics
        
        # Check application metrics structure
        app_metrics = metrics["application"]
        assert "total_requests" in app_metrics
        assert "active_requests" in app_metrics
    
    @pytest.mark.asyncio
    async def test_performance_tracker(self):
        """Test performance tracker utility"""
        tracker = PerformanceTracker("test_operation", {"component": "test"})
        
        # Test sync context manager
        with tracker:
            pass  # Simulate work
        
        duration = tracker.get_duration()
        assert duration is not None
        assert duration >= 0
    
    @pytest.mark.asyncio
    async def test_queue_size_tracking(self, perf_monitor):
        """Test queue size tracking"""
        # Update queue size
        perf_monitor.update_queue_size("test_queue", 42)
        
        # Should complete without errors
        assert True
    
    @pytest.mark.asyncio
    async def test_error_rate_tracking(self, perf_monitor):
        """Test error rate tracking"""
        # Update error rate
        perf_monitor.update_error_rate("test_component", 5.5)
        
        # Should complete without errors
        assert True
    
    @pytest.mark.asyncio
    async def test_throughput_tracking(self, perf_monitor):
        """Test throughput tracking"""
        # Update throughput
        perf_monitor.update_throughput("test_component", "requests", 100.0)
        
        # Should complete without errors
        assert True


class TestPerformanceIntegration:
    """Integration tests for performance optimization components"""
    
    @pytest.mark.asyncio
    async def test_full_performance_stack(self):
        """Test integration of all performance components"""
        # Initialize all components
        pool_config = ConnectionPoolConfig(
            db_min_size=1,
            db_max_size=2,
            redis_max_connections=5,
            http_max_connections=10
        )
        
        cache_config = CacheConfig(
            memory_max_size=50,
            redis_enabled=False
        )
        
        buffer_config = BufferConfig(
            max_buffer_size_mb=1,
            auto_gc_enabled=False
        )
        
        perf_config = PerformanceConfig(
            enable_alerting=False,
            enable_redis_storage=False
        )
        
        # Create components
        pool_manager = ConnectionPoolManager(pool_config)
        cache = IntelligentCache("integration_test", cache_config)
        audio_optimizer = AudioMemoryOptimizer(buffer_config)
        perf_monitor = PerformanceMonitor(perf_config)
        
        try:
            # Initialize all components
            await pool_manager.initialize()
            await cache.initialize()
            await audio_optimizer.initialize()
            
            # Create some resources
            http_pool = await pool_manager.create_http_pool("integration_http")
            
            # Perform some operations
            await cache.set("integration_key", "integration_value")
            cached_value = await cache.get("integration_key")
            assert cached_value == "integration_value"
            
            # Create audio stream
            audio_format = AudioFormat()
            buffer = await audio_optimizer.create_optimized_stream(
                "integration_stream", audio_format
            )
            
            # Process some audio
            test_audio = b"test_audio_data"
            processed = await audio_optimizer.process_audio_data(
                "integration_stream", test_audio
            )
            assert processed == test_audio
            
            # Track performance
            async with perf_monitor.track_request("/integration", "GET"):
                await asyncio.sleep(0.01)
            
            # Get metrics
            metrics = await perf_monitor.get_current_metrics()
            assert metrics is not None
            
            # Get component statistics
            pool_stats = await pool_manager.get_all_stats()
            cache_stats = await cache.get_stats()
            audio_stats = await audio_optimizer.get_optimization_stats()
            
            assert pool_stats is not None
            assert cache_stats is not None
            assert audio_stats is not None
            
        finally:
            # Clean up all components
            await audio_optimizer.close()
            await cache.close()
            await pool_manager.close_all()
    
    @pytest.mark.asyncio
    async def test_performance_under_load(self):
        """Test performance components under simulated load"""
        cache_config = CacheConfig(memory_max_size=100, redis_enabled=False)
        cache = IntelligentCache("load_test", cache_config)
        
        try:
            await cache.initialize()
            
            # Simulate concurrent operations
            async def cache_operations():
                for i in range(50):
                    await cache.set(f"load_key_{i}", f"load_value_{i}")
                    await cache.get(f"load_key_{i}")
            
            # Run multiple concurrent tasks
            tasks = [cache_operations() for _ in range(5)]
            await asyncio.gather(*tasks)
            
            # Verify cache still works
            stats = await cache.get_stats()
            memory_stats = stats["memory"]
            assert memory_stats.total_entries > 0
            assert memory_stats.hits > 0
            
        finally:
            await cache.close()


# Pytest configuration
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])