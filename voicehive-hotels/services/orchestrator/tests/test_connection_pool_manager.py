"""
Comprehensive unit tests for Connection Pool Manager
Tests database, Redis, and HTTP connection pool management with metrics integration
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from typing import Optional, Dict, Any
import weakref

from connection_pool_manager import (
    ConnectionPoolManager, ConnectionPoolConfig, ConnectionPoolStats,
    DatabasePool, RedisPool, HTTPPool,
    get_connection_pool_manager, initialize_default_pools
)


@pytest.fixture
def pool_config():
    """Standard connection pool configuration for testing"""
    return ConnectionPoolConfig(
        db_min_size=2,
        db_max_size=10,
        db_command_timeout=15.0,
        redis_min_connections=5,
        redis_max_connections=50,
        redis_retry_on_timeout=True,
        redis_health_check_interval=30,
        http_max_keepalive=10,
        http_max_connections=50,
        http_keepalive_expiry=20.0,
        http_timeout=15.0,
        max_memory_mb=256,
        memory_check_interval=30,
        connection_test_interval=120
    )


@pytest.fixture
def mock_asyncpg_pool():
    """Mock asyncpg Pool for testing"""
    pool_mock = AsyncMock()
    pool_mock._holders = [Mock() for _ in range(5)]  # 5 total connections
    pool_mock._queue = Mock()
    pool_mock._queue._queue = [Mock() for _ in range(2)]  # 2 idle connections
    pool_mock.acquire = AsyncMock()
    pool_mock.close = AsyncMock()
    return pool_mock


@pytest.fixture
def mock_redis_pool():
    """Mock Redis ConnectionPool for testing"""
    pool_mock = AsyncMock()
    pool_mock.created_connections = 8
    pool_mock.disconnect = AsyncMock()
    return pool_mock


@pytest.fixture
def mock_redis_client():
    """Mock Redis client for testing"""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock()
    redis_mock.close = AsyncMock()
    return redis_mock


@pytest.fixture
def mock_httpx_client():
    """Mock httpx AsyncClient for testing"""
    client_mock = AsyncMock()
    client_mock.aclose = AsyncMock()
    return client_mock


class TestConnectionPoolConfig:
    """Test connection pool configuration model"""

    def test_config_defaults(self):
        """Test default configuration values"""
        config = ConnectionPoolConfig()

        # Database defaults
        assert config.db_min_size == 5
        assert config.db_max_size == 20
        assert config.db_command_timeout == 30.0
        assert config.db_server_settings == {}

        # Redis defaults
        assert config.redis_min_connections == 10
        assert config.redis_max_connections == 100
        assert config.redis_retry_on_timeout is True
        assert config.redis_health_check_interval == 30
        assert config.redis_socket_keepalive is True
        assert config.redis_socket_connect_timeout == 5.0
        assert config.redis_socket_timeout == 5.0

        # HTTP defaults
        assert config.http_max_keepalive == 20
        assert config.http_max_connections == 100
        assert config.http_keepalive_expiry == 30.0
        assert config.http_timeout == 30.0

        # Memory and performance defaults
        assert config.max_memory_mb == 512
        assert config.memory_check_interval == 60
        assert config.enable_connection_warming is True
        assert config.connection_test_interval == 300

    def test_config_custom_values(self):
        """Test custom configuration values"""
        config = ConnectionPoolConfig(
            db_min_size=3,
            db_max_size=15,
            redis_max_connections=200,
            http_timeout=45.0,
            max_memory_mb=1024
        )

        assert config.db_min_size == 3
        assert config.db_max_size == 15
        assert config.redis_max_connections == 200
        assert config.http_timeout == 45.0
        assert config.max_memory_mb == 1024

    def test_config_validation(self):
        """Test configuration validation"""
        # Valid configuration should work
        config = ConnectionPoolConfig(
            db_min_size=1,
            db_max_size=5,
            redis_min_connections=1,
            redis_max_connections=10
        )
        assert config.db_min_size == 1
        assert config.db_max_size == 5


class TestDatabasePool:
    """Test database connection pool functionality"""

    @pytest.mark.asyncio
    async def test_database_pool_initialization(self, pool_config, mock_asyncpg_pool):
        """Test database pool initialization"""
        with patch('connection_pool_manager.asyncpg') as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_asyncpg_pool)

            db_pool = DatabasePool("test_db", pool_config)
            await db_pool.initialize("postgresql://test:test@localhost/test")

            assert db_pool.pool == mock_asyncpg_pool
            assert db_pool._stats['created_total'] == pool_config.db_min_size

            # Verify asyncpg.create_pool was called with correct parameters
            mock_asyncpg.create_pool.assert_called_once_with(
                "postgresql://test:test@localhost/test",
                min_size=pool_config.db_min_size,
                max_size=pool_config.db_max_size,
                command_timeout=pool_config.db_command_timeout,
                server_settings=pool_config.db_server_settings,
                init=db_pool._init_connection
            )

    @pytest.mark.asyncio
    async def test_database_pool_initialization_without_asyncpg(self, pool_config):
        """Test database pool initialization when asyncpg is not available"""
        with patch('connection_pool_manager.asyncpg', None):
            db_pool = DatabasePool("test_db", pool_config)

            with pytest.raises(ImportError, match="asyncpg is required"):
                await db_pool.initialize("postgresql://test:test@localhost/test")

    @pytest.mark.asyncio
    async def test_database_pool_acquire_connection(self, pool_config, mock_asyncpg_pool):
        """Test acquiring database connection"""
        with patch('connection_pool_manager.asyncpg') as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_asyncpg_pool)

            # Mock connection
            mock_conn = AsyncMock()
            mock_asyncpg_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_asyncpg_pool.acquire.return_value.__aexit__.return_value = False

            db_pool = DatabasePool("test_db", pool_config)
            await db_pool.initialize("postgresql://test:test@localhost/test")

            # Test connection acquisition
            async with db_pool.acquire() as conn:
                assert conn == mock_conn

            mock_asyncpg_pool.acquire.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_pool_acquire_without_initialization(self, pool_config):
        """Test acquiring connection before pool initialization"""
        db_pool = DatabasePool("test_db", pool_config)

        with pytest.raises(RuntimeError, match="Database pool test_db not initialized"):
            async with db_pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_database_pool_acquire_error_handling(self, pool_config, mock_asyncpg_pool):
        """Test error handling during connection acquisition"""
        with patch('connection_pool_manager.asyncpg') as mock_asyncpg, \
             patch('connection_pool_manager.connection_pool_errors') as mock_counter:

            mock_asyncpg.create_pool = AsyncMock(return_value=mock_asyncpg_pool)
            mock_asyncpg_pool.acquire.side_effect = Exception("Connection failed")
            mock_counter.labels.return_value.inc = MagicMock()

            db_pool = DatabasePool("test_db", pool_config)
            await db_pool.initialize("postgresql://test:test@localhost/test")

            with pytest.raises(Exception, match="Connection failed"):
                async with db_pool.acquire():
                    pass

            # Verify error was recorded
            assert db_pool._stats['errors_total'] == 1
            assert db_pool._stats['last_error'] == "Connection failed"
            mock_counter.labels.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_pool_init_connection(self, pool_config):
        """Test database connection initialization"""
        db_pool = DatabasePool("test_db", pool_config)
        mock_conn = AsyncMock()

        await db_pool._init_connection(mock_conn)

        # Verify connection setup queries
        mock_conn.execute.assert_any_call("SET timezone = 'UTC'")
        mock_conn.execute.assert_any_call("SET statement_timeout = '30s'")

    def test_database_pool_get_stats(self, pool_config, mock_asyncpg_pool):
        """Test getting database pool statistics"""
        db_pool = DatabasePool("test_db", pool_config)
        db_pool.pool = mock_asyncpg_pool
        db_pool._stats.update({
            'created_total': 10,
            'closed_total': 2,
            'errors_total': 1,
            'last_error': "Test error",
            'last_error_time': datetime.now(timezone.utc)
        })

        stats = db_pool.get_stats()

        assert isinstance(stats, ConnectionPoolStats)
        assert stats.pool_name == "test_db"
        assert stats.pool_type == "database"
        assert stats.size == 5  # len(mock_asyncpg_pool._holders)
        assert stats.active == 3  # size - idle
        assert stats.idle == 2  # len(mock_asyncpg_pool._queue._queue)
        assert stats.created_total == 10
        assert stats.closed_total == 2
        assert stats.errors_total == 1

    @pytest.mark.asyncio
    async def test_database_pool_close(self, pool_config, mock_asyncpg_pool):
        """Test closing database pool"""
        with patch('connection_pool_manager.asyncpg') as mock_asyncpg:
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_asyncpg_pool)

            db_pool = DatabasePool("test_db", pool_config)
            await db_pool.initialize("postgresql://test:test@localhost/test")

            await db_pool.close()

            mock_asyncpg_pool.close.assert_called_once()
            assert db_pool._stats['closed_total'] == len(mock_asyncpg_pool._holders)


class TestRedisPool:
    """Test Redis connection pool functionality"""

    @pytest.mark.asyncio
    async def test_redis_pool_initialization(self, pool_config, mock_redis_pool, mock_redis_client):
        """Test Redis pool initialization"""
        with patch('connection_pool_manager.aioredis') as mock_aioredis:
            mock_aioredis.ConnectionPool.from_url = MagicMock(return_value=mock_redis_pool)
            mock_aioredis.Redis = MagicMock(return_value=mock_redis_client)

            redis_pool = RedisPool("test_redis", pool_config)
            await redis_pool.initialize("redis://localhost:6379")

            assert redis_pool.pool == mock_redis_pool
            assert redis_pool.redis == mock_redis_client
            assert redis_pool._stats['created_total'] == pool_config.redis_min_connections

            # Verify Redis pool configuration
            mock_aioredis.ConnectionPool.from_url.assert_called_once()
            call_kwargs = mock_aioredis.ConnectionPool.from_url.call_args[1]
            assert call_kwargs['max_connections'] == pool_config.redis_max_connections
            assert call_kwargs['retry_on_timeout'] == pool_config.redis_retry_on_timeout
            assert call_kwargs['health_check_interval'] == pool_config.redis_health_check_interval
            assert call_kwargs['socket_keepalive'] == pool_config.redis_socket_keepalive

            # Verify ping was called
            mock_redis_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_pool_initialization_without_aioredis(self, pool_config):
        """Test Redis pool initialization when aioredis is not available"""
        with patch('connection_pool_manager.aioredis', None):
            redis_pool = RedisPool("test_redis", pool_config)

            with pytest.raises(ImportError, match="aioredis is required"):
                await redis_pool.initialize("redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_redis_pool_acquire_connection(self, pool_config, mock_redis_pool, mock_redis_client):
        """Test acquiring Redis connection"""
        with patch('connection_pool_manager.aioredis') as mock_aioredis:
            mock_aioredis.ConnectionPool.from_url = MagicMock(return_value=mock_redis_pool)
            mock_aioredis.Redis = MagicMock(return_value=mock_redis_client)

            redis_pool = RedisPool("test_redis", pool_config)
            await redis_pool.initialize("redis://localhost:6379")

            # Test connection acquisition
            async with redis_pool.acquire() as redis_client:
                assert redis_client == mock_redis_client

    @pytest.mark.asyncio
    async def test_redis_pool_acquire_without_initialization(self, pool_config):
        """Test acquiring connection before pool initialization"""
        redis_pool = RedisPool("test_redis", pool_config)

        with pytest.raises(RuntimeError, match="Redis pool test_redis not initialized"):
            async with redis_pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_redis_pool_get_redis_direct(self, pool_config, mock_redis_pool, mock_redis_client):
        """Test getting Redis client directly"""
        with patch('connection_pool_manager.aioredis') as mock_aioredis:
            mock_aioredis.ConnectionPool.from_url = MagicMock(return_value=mock_redis_pool)
            mock_aioredis.Redis = MagicMock(return_value=mock_redis_client)

            redis_pool = RedisPool("test_redis", pool_config)
            await redis_pool.initialize("redis://localhost:6379")

            client = redis_pool.get_redis()
            assert client == mock_redis_client

    @pytest.mark.asyncio
    async def test_redis_pool_get_redis_without_initialization(self, pool_config):
        """Test getting Redis client before initialization"""
        redis_pool = RedisPool("test_redis", pool_config)

        with pytest.raises(RuntimeError, match="Redis pool test_redis not initialized"):
            redis_pool.get_redis()

    def test_redis_pool_get_stats(self, pool_config, mock_redis_pool):
        """Test getting Redis pool statistics"""
        redis_pool = RedisPool("test_redis", pool_config)
        redis_pool.pool = mock_redis_pool
        redis_pool._stats.update({
            'created_total': 15,
            'closed_total': 3,
            'errors_total': 2,
            'last_error': "Redis timeout",
            'last_error_time': datetime.now(timezone.utc)
        })

        stats = redis_pool.get_stats()

        assert isinstance(stats, ConnectionPoolStats)
        assert stats.pool_name == "test_redis"
        assert stats.pool_type == "redis"
        assert stats.size == 8  # mock_redis_pool.created_connections
        assert stats.active == 8
        assert stats.idle == max(0, pool_config.redis_max_connections - 8)
        assert stats.created_total == 15
        assert stats.errors_total == 2

    @pytest.mark.asyncio
    async def test_redis_pool_close(self, pool_config, mock_redis_pool, mock_redis_client):
        """Test closing Redis pool"""
        with patch('connection_pool_manager.aioredis') as mock_aioredis:
            mock_aioredis.ConnectionPool.from_url = MagicMock(return_value=mock_redis_pool)
            mock_aioredis.Redis = MagicMock(return_value=mock_redis_client)

            redis_pool = RedisPool("test_redis", pool_config)
            await redis_pool.initialize("redis://localhost:6379")

            await redis_pool.close()

            mock_redis_client.close.assert_called_once()
            mock_redis_pool.disconnect.assert_called_once()


class TestHTTPPool:
    """Test HTTP connection pool functionality"""

    @pytest.mark.asyncio
    async def test_http_pool_initialization(self, pool_config, mock_httpx_client):
        """Test HTTP pool initialization"""
        with patch('connection_pool_manager.httpx.AsyncClient', return_value=mock_httpx_client):
            http_pool = HTTPPool("test_http", pool_config)
            await http_pool.initialize()

            assert http_pool.client == mock_httpx_client
            assert http_pool._stats['created_total'] == 1

    @pytest.mark.asyncio
    async def test_http_pool_initialization_with_custom_kwargs(self, pool_config, mock_httpx_client):
        """Test HTTP pool initialization with custom client kwargs"""
        with patch('connection_pool_manager.httpx.AsyncClient', return_value=mock_httpx_client) as mock_client_class:
            http_pool = HTTPPool("test_http", pool_config)

            custom_headers = {"Authorization": "Bearer test-token"}
            await http_pool.initialize(headers=custom_headers, http2=True)

            # Verify AsyncClient was called with merged kwargs
            mock_client_class.assert_called_once()
            call_kwargs = mock_client_class.call_args[1]

            # Check limits configuration
            assert call_kwargs['limits'].max_keepalive_connections == pool_config.http_max_keepalive
            assert call_kwargs['limits'].max_connections == pool_config.http_max_connections
            assert call_kwargs['limits'].keepalive_expiry == pool_config.http_keepalive_expiry

            # Check timeout configuration
            assert call_kwargs['timeout'].timeout == pool_config.http_timeout

            # Check custom headers were merged
            assert "Authorization" in call_kwargs['headers']
            assert call_kwargs['headers']["Authorization"] == "Bearer test-token"

            # Check custom kwargs were passed through
            assert call_kwargs['http2'] is True

    @pytest.mark.asyncio
    async def test_http_pool_acquire_connection(self, pool_config, mock_httpx_client):
        """Test acquiring HTTP client"""
        with patch('connection_pool_manager.httpx.AsyncClient', return_value=mock_httpx_client):
            http_pool = HTTPPool("test_http", pool_config)
            await http_pool.initialize()

            # Test client acquisition
            async with http_pool.acquire() as client:
                assert client == mock_httpx_client

    @pytest.mark.asyncio
    async def test_http_pool_acquire_without_initialization(self, pool_config):
        """Test acquiring client before pool initialization"""
        http_pool = HTTPPool("test_http", pool_config)

        with pytest.raises(RuntimeError, match="HTTP pool test_http not initialized"):
            async with http_pool.acquire():
                pass

    @pytest.mark.asyncio
    async def test_http_pool_get_client_direct(self, pool_config, mock_httpx_client):
        """Test getting HTTP client directly"""
        with patch('connection_pool_manager.httpx.AsyncClient', return_value=mock_httpx_client):
            http_pool = HTTPPool("test_http", pool_config)
            await http_pool.initialize()

            client = http_pool.get_client()
            assert client == mock_httpx_client

    @pytest.mark.asyncio
    async def test_http_pool_get_client_without_initialization(self, pool_config):
        """Test getting HTTP client before initialization"""
        http_pool = HTTPPool("test_http", pool_config)

        with pytest.raises(RuntimeError, match="HTTP pool test_http not initialized"):
            http_pool.get_client()

    def test_http_pool_get_stats(self, pool_config):
        """Test getting HTTP pool statistics"""
        http_pool = HTTPPool("test_http", pool_config)
        http_pool._stats.update({
            'created_total': 5,
            'closed_total': 1,
            'errors_total': 0,
            'last_error': None,
            'last_error_time': None
        })

        stats = http_pool.get_stats()

        assert isinstance(stats, ConnectionPoolStats)
        assert stats.pool_name == "test_http"
        assert stats.pool_type == "http"
        assert stats.size == pool_config.http_max_connections
        assert stats.active == pool_config.http_max_keepalive // 2  # Estimate
        assert stats.idle == pool_config.http_max_keepalive // 2    # Estimate
        assert stats.created_total == 5
        assert stats.errors_total == 0

    @pytest.mark.asyncio
    async def test_http_pool_close(self, pool_config, mock_httpx_client):
        """Test closing HTTP pool"""
        with patch('connection_pool_manager.httpx.AsyncClient', return_value=mock_httpx_client):
            http_pool = HTTPPool("test_http", pool_config)
            await http_pool.initialize()

            await http_pool.close()

            mock_httpx_client.aclose.assert_called_once()
            assert http_pool._stats['closed_total'] == 1


class TestConnectionPoolManager:
    """Test connection pool manager functionality"""

    @pytest.mark.asyncio
    async def test_connection_pool_manager_initialization(self, pool_config):
        """Test connection pool manager initialization"""
        manager = ConnectionPoolManager(pool_config)

        assert manager.config == pool_config
        assert len(manager.db_pools) == 0
        assert len(manager.redis_pools) == 0
        assert len(manager.http_pools) == 0
        assert manager._memory_monitor_task is None
        assert manager._connection_test_task is None

        await manager.initialize()

        # Background tasks should be created if intervals > 0
        if pool_config.memory_check_interval > 0:
            assert manager._memory_monitor_task is not None
            assert not manager._memory_monitor_task.done()

        if pool_config.connection_test_interval > 0:
            assert manager._connection_test_task is not None
            assert not manager._connection_test_task.done()

        # Clean up
        await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_database_pool(self, pool_config):
        """Test creating database pool"""
        manager = ConnectionPoolManager(pool_config)

        with patch('connection_pool_manager.asyncpg') as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

            db_pool = await manager.create_database_pool(
                "test_db",
                "postgresql://test:test@localhost/test"
            )

            assert isinstance(db_pool, DatabasePool)
            assert db_pool.name == "test_db"
            assert manager.db_pools["test_db"] == db_pool

        await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_database_pool_already_exists(self, pool_config):
        """Test creating database pool when it already exists"""
        manager = ConnectionPoolManager(pool_config)

        with patch('connection_pool_manager.asyncpg') as mock_asyncpg:
            mock_pool = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)

            # Create first pool
            db_pool1 = await manager.create_database_pool(
                "test_db",
                "postgresql://test:test@localhost/test"
            )

            # Try to create same pool again
            db_pool2 = await manager.create_database_pool(
                "test_db",
                "postgresql://test:test@localhost/test"
            )

            # Should return the same instance
            assert db_pool1 == db_pool2
            assert len(manager.db_pools) == 1

        await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_redis_pool(self, pool_config):
        """Test creating Redis pool"""
        manager = ConnectionPoolManager(pool_config)

        with patch('connection_pool_manager.aioredis') as mock_aioredis:
            mock_pool = AsyncMock()
            mock_redis = AsyncMock()
            mock_aioredis.ConnectionPool.from_url = MagicMock(return_value=mock_pool)
            mock_aioredis.Redis = MagicMock(return_value=mock_redis)

            redis_pool = await manager.create_redis_pool(
                "test_redis",
                "redis://localhost:6379"
            )

            assert isinstance(redis_pool, RedisPool)
            assert redis_pool.name == "test_redis"
            assert manager.redis_pools["test_redis"] == redis_pool

        await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_http_pool(self, pool_config):
        """Test creating HTTP pool"""
        manager = ConnectionPoolManager(pool_config)

        with patch('connection_pool_manager.httpx.AsyncClient') as mock_client:
            mock_client.return_value = AsyncMock()

            http_pool = await manager.create_http_pool("test_http")

            assert isinstance(http_pool, HTTPPool)
            assert http_pool.name == "test_http"
            assert manager.http_pools["test_http"] == http_pool

        await manager.close_all()

    def test_get_pools(self, pool_config):
        """Test getting pools by name"""
        manager = ConnectionPoolManager(pool_config)

        # Initially, no pools should exist
        assert manager.get_database_pool("nonexistent") is None
        assert manager.get_redis_pool("nonexistent") is None
        assert manager.get_http_pool("nonexistent") is None

        # Add mock pools
        mock_db_pool = Mock()
        mock_redis_pool = Mock()
        mock_http_pool = Mock()

        manager.db_pools["test_db"] = mock_db_pool
        manager.redis_pools["test_redis"] = mock_redis_pool
        manager.http_pools["test_http"] = mock_http_pool

        # Test getting existing pools
        assert manager.get_database_pool("test_db") == mock_db_pool
        assert manager.get_redis_pool("test_redis") == mock_redis_pool
        assert manager.get_http_pool("test_http") == mock_http_pool

    @pytest.mark.asyncio
    async def test_get_all_stats(self, pool_config):
        """Test getting statistics for all pools"""
        manager = ConnectionPoolManager(pool_config)

        # Add mock pools with stats
        mock_db_pool = Mock()
        mock_db_stats = ConnectionPoolStats(
            pool_name="test_db", pool_type="database",
            size=10, active=5, idle=5,
            created_total=10, closed_total=0, errors_total=0
        )
        mock_db_pool.get_stats.return_value = mock_db_stats

        mock_redis_pool = Mock()
        mock_redis_stats = ConnectionPoolStats(
            pool_name="test_redis", pool_type="redis",
            size=8, active=6, idle=2,
            created_total=8, closed_total=0, errors_total=1
        )
        mock_redis_pool.get_stats.return_value = mock_redis_stats

        manager.db_pools["test_db"] = mock_db_pool
        manager.redis_pools["test_redis"] = mock_redis_pool

        stats = await manager.get_all_stats()

        assert "database" in stats
        assert "redis" in stats
        assert "http" in stats
        assert len(stats["database"]) == 1
        assert len(stats["redis"]) == 1
        assert len(stats["http"]) == 0
        assert stats["database"][0] == mock_db_stats
        assert stats["redis"][0] == mock_redis_stats

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self, pool_config):
        """Test health check when all pools are healthy"""
        manager = ConnectionPoolManager(pool_config)

        # Mock database pool
        mock_db_pool = AsyncMock()
        mock_db_pool.pool = True  # Pool exists
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_db_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_db_pool.acquire.return_value.__aexit__.return_value = False
        manager.db_pools["test_db"] = mock_db_pool

        # Mock Redis pool
        mock_redis_pool = AsyncMock()
        mock_redis_pool.redis = AsyncMock()
        mock_redis_pool.redis.ping = AsyncMock()
        manager.redis_pools["test_redis"] = mock_redis_pool

        # Mock HTTP pool
        mock_http_pool = Mock()
        mock_http_pool.client = True  # Client exists
        manager.http_pools["test_http"] = mock_http_pool

        health_results = await manager.health_check()

        assert health_results["database"]["test_db"] is True
        assert health_results["redis"]["test_redis"] is True
        assert health_results["http"]["test_http"] is True

    @pytest.mark.asyncio
    async def test_health_check_with_failures(self, pool_config):
        """Test health check when pools have failures"""
        manager = ConnectionPoolManager(pool_config)

        # Mock failing database pool
        mock_db_pool = AsyncMock()
        mock_db_pool.pool = True
        mock_db_pool.acquire.side_effect = Exception("DB connection failed")
        manager.db_pools["test_db"] = mock_db_pool

        # Mock failing Redis pool
        mock_redis_pool = AsyncMock()
        mock_redis_pool.redis = AsyncMock()
        mock_redis_pool.redis.ping.side_effect = Exception("Redis ping failed")
        manager.redis_pools["test_redis"] = mock_redis_pool

        # Mock uninitialized HTTP pool
        mock_http_pool = Mock()
        mock_http_pool.client = None  # Not initialized
        manager.http_pools["test_http"] = mock_http_pool

        health_results = await manager.health_check()

        assert health_results["database"]["test_db"] is False
        assert health_results["redis"]["test_redis"] is False
        assert health_results["http"]["test_http"] is False

    @pytest.mark.asyncio
    async def test_memory_monitoring(self, pool_config):
        """Test memory monitoring functionality"""
        # Configure shorter intervals for testing
        pool_config.memory_check_interval = 0.1
        pool_config.max_memory_mb = 100

        manager = ConnectionPoolManager(pool_config)

        with patch('connection_pool_manager.psutil') as mock_psutil:
            # Mock process memory usage above limit
            mock_process = Mock()
            mock_process.memory_info.return_value.rss = 150 * 1024 * 1024  # 150MB
            mock_psutil.Process.return_value = mock_process

            await manager.initialize()

            # Let monitor run briefly
            await asyncio.sleep(0.2)

            # Verify process was called
            mock_psutil.Process.assert_called()

        await manager.close_all()

    @pytest.mark.asyncio
    async def test_memory_monitoring_without_psutil(self, pool_config):
        """Test memory monitoring when psutil is not available"""
        pool_config.memory_check_interval = 0.1
        manager = ConnectionPoolManager(pool_config)

        with patch('connection_pool_manager.psutil', None):
            await manager.initialize()

            # Should not raise exception
            await asyncio.sleep(0.1)

        await manager.close_all()

    @pytest.mark.asyncio
    async def test_connection_testing(self, pool_config):
        """Test periodic connection testing"""
        # Configure shorter interval for testing
        pool_config.connection_test_interval = 0.1
        manager = ConnectionPoolManager(pool_config)

        with patch.object(manager, 'health_check') as mock_health_check:
            mock_health_check.return_value = {
                "database": {"test_db": True},
                "redis": {"test_redis": False},  # Unhealthy
                "http": {"test_http": True}
            }

            await manager.initialize()

            # Let connection test run briefly
            await asyncio.sleep(0.2)

            # Verify health check was called
            mock_health_check.assert_called()

        await manager.close_all()

    @pytest.mark.asyncio
    async def test_close_all_pools(self, pool_config):
        """Test closing all connection pools"""
        manager = ConnectionPoolManager(pool_config)

        # Add mock pools
        mock_db_pool = AsyncMock()
        mock_redis_pool = AsyncMock()
        mock_http_pool = AsyncMock()

        manager.db_pools["test_db"] = mock_db_pool
        manager.redis_pools["test_redis"] = mock_redis_pool
        manager.http_pools["test_http"] = mock_http_pool

        # Start background tasks
        await manager.initialize()

        # Close all pools
        await manager.close_all()

        # Verify all pools were closed
        mock_db_pool.close.assert_called_once()
        mock_redis_pool.close.assert_called_once()
        mock_http_pool.close.assert_called_once()

        # Verify pools were cleared
        assert len(manager.db_pools) == 0
        assert len(manager.redis_pools) == 0
        assert len(manager.http_pools) == 0

        # Verify background tasks were cancelled
        if manager._memory_monitor_task:
            assert manager._memory_monitor_task.cancelled()
        if manager._connection_test_task:
            assert manager._connection_test_task.cancelled()

    @pytest.mark.asyncio
    async def test_close_all_with_errors(self, pool_config):
        """Test closing all pools when some pools raise errors"""
        manager = ConnectionPoolManager(pool_config)

        # Add mock pools that will raise errors
        mock_db_pool = AsyncMock()
        mock_db_pool.close.side_effect = Exception("DB close error")
        mock_redis_pool = AsyncMock()
        mock_redis_pool.close.side_effect = Exception("Redis close error")
        mock_http_pool = AsyncMock()
        mock_http_pool.close.side_effect = Exception("HTTP close error")

        manager.db_pools["test_db"] = mock_db_pool
        manager.redis_pools["test_redis"] = mock_redis_pool
        manager.http_pools["test_http"] = mock_http_pool

        # Should not raise exception despite individual close errors
        await manager.close_all()

        # Verify all close methods were called
        mock_db_pool.close.assert_called_once()
        mock_redis_pool.close.assert_called_once()
        mock_http_pool.close.assert_called_once()

        # Pools should still be cleared
        assert len(manager.db_pools) == 0
        assert len(manager.redis_pools) == 0
        assert len(manager.http_pools) == 0


class TestGlobalPoolManager:
    """Test global pool manager functionality"""

    def test_get_connection_pool_manager_singleton(self):
        """Test global connection pool manager singleton behavior"""
        # Clear any existing global manager
        import connection_pool_manager
        connection_pool_manager._pool_manager = None

        # Get manager instances
        manager1 = get_connection_pool_manager()
        manager2 = get_connection_pool_manager()

        # Should be the same instance
        assert manager1 is manager2
        assert isinstance(manager1, ConnectionPoolManager)

        # Clear for other tests
        connection_pool_manager._pool_manager = None

    def test_get_connection_pool_manager_with_config(self, pool_config):
        """Test global connection pool manager with custom config"""
        # Clear any existing global manager
        import connection_pool_manager
        connection_pool_manager._pool_manager = None

        manager = get_connection_pool_manager(pool_config)

        assert manager.config == pool_config

        # Clear for other tests
        connection_pool_manager._pool_manager = None

    @pytest.mark.asyncio
    async def test_initialize_default_pools(self, pool_config):
        """Test initializing default connection pools"""
        # Clear any existing global manager
        import connection_pool_manager
        connection_pool_manager._pool_manager = None

        with patch('connection_pool_manager.asyncpg') as mock_asyncpg, \
             patch('connection_pool_manager.aioredis') as mock_aioredis, \
             patch('connection_pool_manager.httpx.AsyncClient') as mock_httpx:

            mock_asyncpg.create_pool = AsyncMock()
            mock_aioredis.ConnectionPool.from_url = MagicMock()
            mock_aioredis.Redis = MagicMock()
            mock_httpx.return_value = AsyncMock()

            manager = await initialize_default_pools(
                database_url="postgresql://test:test@localhost/test",
                redis_url="redis://localhost:6379",
                config=pool_config
            )

            assert isinstance(manager, ConnectionPoolManager)

            # Verify default pools were created
            assert "default" in manager.db_pools
            assert "default" in manager.redis_pools
            assert "tts_service" in manager.http_pools
            assert "asr_service" in manager.http_pools
            assert "pms_connector" in manager.http_pools
            assert "external_api" in manager.http_pools

            await manager.close_all()

        # Clear for other tests
        connection_pool_manager._pool_manager = None

    @pytest.mark.asyncio
    async def test_initialize_default_pools_no_urls(self, pool_config):
        """Test initializing default pools without database/Redis URLs"""
        # Clear any existing global manager
        import connection_pool_manager
        connection_pool_manager._pool_manager = None

        with patch('connection_pool_manager.httpx.AsyncClient') as mock_httpx:
            mock_httpx.return_value = AsyncMock()

            manager = await initialize_default_pools(config=pool_config)

            assert isinstance(manager, ConnectionPoolManager)

            # Only HTTP pools should be created
            assert len(manager.db_pools) == 0
            assert len(manager.redis_pools) == 0
            assert len(manager.http_pools) == 4  # 4 HTTP pools

            await manager.close_all()

        # Clear for other tests
        connection_pool_manager._pool_manager = None


class TestMetricsIntegration:
    """Test Prometheus metrics integration"""

    @pytest.mark.asyncio
    async def test_database_pool_metrics(self, pool_config):
        """Test database pool metrics integration"""
        with patch('connection_pool_manager.asyncpg') as mock_asyncpg, \
             patch('connection_pool_manager.connection_pool_size') as mock_size_metric, \
             patch('connection_pool_manager.connection_acquisition_duration') as mock_duration_metric:

            mock_pool = AsyncMock()
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            mock_size_metric.labels.return_value.set = MagicMock()
            mock_duration_metric.labels.return_value.observe = MagicMock()

            db_pool = DatabasePool("test_db", pool_config)
            await db_pool.initialize("postgresql://test:test@localhost/test")

            # Verify size metric was set
            mock_size_metric.labels.assert_called_with(
                pool_type='database',
                pool_name='test_db'
            )
            mock_size_metric.labels.return_value.set.assert_called_with(pool_config.db_max_size)

    @pytest.mark.asyncio
    async def test_redis_pool_metrics(self, pool_config):
        """Test Redis pool metrics integration"""
        with patch('connection_pool_manager.aioredis') as mock_aioredis, \
             patch('connection_pool_manager.connection_pool_size') as mock_size_metric:

            mock_pool = AsyncMock()
            mock_redis = AsyncMock()
            mock_aioredis.ConnectionPool.from_url = MagicMock(return_value=mock_pool)
            mock_aioredis.Redis = MagicMock(return_value=mock_redis)
            mock_size_metric.labels.return_value.set = MagicMock()

            redis_pool = RedisPool("test_redis", pool_config)
            await redis_pool.initialize("redis://localhost:6379")

            # Verify size metric was set
            mock_size_metric.labels.assert_called_with(
                pool_type='redis',
                pool_name='test_redis'
            )
            mock_size_metric.labels.return_value.set.assert_called_with(pool_config.redis_max_connections)

    @pytest.mark.asyncio
    async def test_http_pool_metrics(self, pool_config):
        """Test HTTP pool metrics integration"""
        with patch('connection_pool_manager.httpx.AsyncClient') as mock_httpx, \
             patch('connection_pool_manager.connection_pool_size') as mock_size_metric:

            mock_httpx.return_value = AsyncMock()
            mock_size_metric.labels.return_value.set = MagicMock()

            http_pool = HTTPPool("test_http", pool_config)
            await http_pool.initialize()

            # Verify size metric was set
            mock_size_metric.labels.assert_called_with(
                pool_type='http',
                pool_name='test_http'
            )
            mock_size_metric.labels.return_value.set.assert_called_with(pool_config.http_max_connections)

    @pytest.mark.asyncio
    async def test_error_metrics_recording(self, pool_config):
        """Test error metrics are recorded properly"""
        with patch('connection_pool_manager.asyncpg') as mock_asyncpg, \
             patch('connection_pool_manager.connection_pool_errors') as mock_error_metric:

            mock_asyncpg.create_pool.side_effect = Exception("Connection failed")
            mock_error_metric.labels.return_value.inc = MagicMock()

            db_pool = DatabasePool("test_db", pool_config)

            with pytest.raises(Exception, match="Connection failed"):
                await db_pool.initialize("postgresql://test:test@localhost/test")

            # Verify error metric was incremented
            mock_error_metric.labels.assert_called_with(
                pool_type='database',
                pool_name='test_db',
                error_type='Exception'
            )
            mock_error_metric.labels.return_value.inc.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])