"""
Connection Pool Manager for VoiceHive Hotels Orchestrator
Centralized management of database, Redis, and HTTP connection pools
"""

import asyncio
import os
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import weakref
from contextlib import asynccontextmanager

try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    import redis.asyncio as aioredis
except ImportError:
    try:
        import aioredis
    except ImportError:
        aioredis = None

import httpx
from pydantic import BaseModel, Field

try:
    import psutil
except ImportError:
    psutil = None

from logging_adapter import get_safe_logger

try:
    from prometheus_client import Gauge, Counter, Histogram
except ImportError:
    # Mock Prometheus metrics if not available
    class MockMetric:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, **kwargs):
            return self
        def set(self, value):
            pass
        def inc(self, value=1):
            pass
        def dec(self, value=1):
            pass
        def observe(self, value):
            pass
    
    Gauge = Counter = Histogram = MockMetric

logger = get_safe_logger("orchestrator.connection_pool")

# Prometheus metrics for connection pool monitoring
connection_pool_size = Gauge(
    'voicehive_connection_pool_size',
    'Current connection pool size',
    ['pool_type', 'pool_name']
)

connection_pool_active = Gauge(
    'voicehive_connection_pool_active',
    'Active connections in pool',
    ['pool_type', 'pool_name']
)

connection_pool_idle = Gauge(
    'voicehive_connection_pool_idle',
    'Idle connections in pool',
    ['pool_type', 'pool_name']
)

connection_pool_errors = Counter(
    'voicehive_connection_pool_errors_total',
    'Connection pool errors',
    ['pool_type', 'pool_name', 'error_type']
)

connection_acquisition_duration = Histogram(
    'voicehive_connection_acquisition_duration_seconds',
    'Time to acquire connection from pool',
    ['pool_type', 'pool_name'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)


class ConnectionPoolConfig(BaseModel):
    """Configuration for connection pools"""
    # Database pool config
    db_min_size: int = Field(5, description="Minimum database connections")
    db_max_size: int = Field(20, description="Maximum database connections")
    db_command_timeout: float = Field(30.0, description="Database command timeout")
    db_server_settings: Dict[str, str] = Field(default_factory=dict)
    
    # Redis pool config - optimized for production based on official Redis documentation
    redis_min_connections: int = Field(10, description="Minimum Redis connections (warm pool)")
    redis_max_connections: int = Field(100, description="Maximum Redis connections (production optimized)")
    redis_retry_on_timeout: bool = Field(True, description="Retry on Redis timeout")
    redis_health_check_interval: int = Field(30, description="Redis health check interval")

    # Additional Redis production settings following official best practices
    redis_socket_keepalive: bool = Field(True, description="Enable TCP keepalive for connection stability")
    redis_socket_connect_timeout: float = Field(5.0, description="Connection establishment timeout")
    redis_socket_timeout: float = Field(5.0, description="Socket operation timeout")
    
    # HTTP pool config
    http_max_keepalive: int = Field(20, description="Max HTTP keepalive connections")
    http_max_connections: int = Field(100, description="Max total HTTP connections")
    http_keepalive_expiry: float = Field(30.0, description="HTTP keepalive expiry seconds")
    http_timeout: float = Field(30.0, description="HTTP request timeout")
    
    # Memory management
    max_memory_mb: int = Field(512, description="Maximum memory usage in MB")
    memory_check_interval: int = Field(60, description="Memory check interval in seconds")
    
    # Performance tuning
    enable_connection_warming: bool = Field(True, description="Pre-warm connections on startup")
    connection_test_interval: int = Field(300, description="Connection test interval in seconds")


class ConnectionPoolStats(BaseModel):
    """Statistics for connection pools"""
    pool_name: str
    pool_type: str
    size: int
    active: int
    idle: int
    created_total: int
    closed_total: int
    errors_total: int
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    memory_usage_mb: float = 0.0


class DatabasePool:
    """Asyncpg database connection pool wrapper"""
    
    def __init__(self, name: str, config: ConnectionPoolConfig):
        self.name = name
        self.config = config
        self.pool: Optional[asyncpg.Pool] = None
        self._stats = {
            'created_total': 0,
            'closed_total': 0,
            'errors_total': 0,
            'last_error': None,
            'last_error_time': None
        }
        
    async def initialize(self, database_url: str):
        """Initialize database connection pool"""
        if asyncpg is None:
            raise ImportError("asyncpg is required for database connection pooling")
        
        try:
            self.pool = await asyncpg.create_pool(
                database_url,
                min_size=self.config.db_min_size,
                max_size=self.config.db_max_size,
                command_timeout=self.config.db_command_timeout,
                server_settings=self.config.db_server_settings,
                init=self._init_connection
            )
            
            self._stats['created_total'] += self.config.db_min_size
            
            # Update metrics
            connection_pool_size.labels(
                pool_type='database',
                pool_name=self.name
            ).set(self.config.db_max_size)
            
            logger.info(
                "database_pool_initialized",
                name=self.name,
                min_size=self.config.db_min_size,
                max_size=self.config.db_max_size
            )
            
        except Exception as e:
            self._record_error(e)
            logger.error("database_pool_init_failed", name=self.name, error=str(e))
            raise
    
    async def _init_connection(self, conn):
        """Initialize individual database connection"""
        # Set connection-specific settings
        await conn.execute("SET timezone = 'UTC'")
        await conn.execute("SET statement_timeout = '30s'")
        
    @asynccontextmanager
    async def acquire(self):
        """Acquire database connection with metrics"""
        if not self.pool:
            raise RuntimeError(f"Database pool {self.name} not initialized")
        
        start_time = datetime.now(timezone.utc)
        
        try:
            async with self.pool.acquire() as conn:
                # Record acquisition time
                acquisition_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                connection_acquisition_duration.labels(
                    pool_type='database',
                    pool_name=self.name
                ).observe(acquisition_time)
                
                # Update active connections metric
                self._update_metrics()
                
                yield conn
                
        except Exception as e:
            self._record_error(e)
            raise
    
    def _record_error(self, error: Exception):
        """Record error in stats and metrics"""
        self._stats['errors_total'] += 1
        self._stats['last_error'] = str(error)
        self._stats['last_error_time'] = datetime.now(timezone.utc)
        
        connection_pool_errors.labels(
            pool_type='database',
            pool_name=self.name,
            error_type=type(error).__name__
        ).inc()
    
    def _update_metrics(self):
        """Update Prometheus metrics"""
        if self.pool:
            connection_pool_active.labels(
                pool_type='database',
                pool_name=self.name
            ).set(len(self.pool._holders) - len(self.pool._queue._queue))
            
            connection_pool_idle.labels(
                pool_type='database',
                pool_name=self.name
            ).set(len(self.pool._queue._queue))
    
    def get_stats(self) -> ConnectionPoolStats:
        """Get connection pool statistics"""
        active = 0
        idle = 0
        size = 0
        
        if self.pool:
            size = len(self.pool._holders)
            idle = len(self.pool._queue._queue)
            active = size - idle
        
        return ConnectionPoolStats(
            pool_name=self.name,
            pool_type='database',
            size=size,
            active=active,
            idle=idle,
            created_total=self._stats['created_total'],
            closed_total=self._stats['closed_total'],
            errors_total=self._stats['errors_total'],
            last_error=self._stats['last_error'],
            last_error_time=self._stats['last_error_time']
        )
    
    async def close(self):
        """Close database pool"""
        if self.pool:
            await self.pool.close()
            self._stats['closed_total'] += len(self.pool._holders)
            logger.info("database_pool_closed", name=self.name)


class RedisPool:
    """Redis connection pool wrapper"""
    
    def __init__(self, name: str, config: ConnectionPoolConfig):
        self.name = name
        self.config = config
        self.pool: Optional[aioredis.ConnectionPool] = None
        self.redis: Optional[aioredis.Redis] = None
        self._stats = {
            'created_total': 0,
            'closed_total': 0,
            'errors_total': 0,
            'last_error': None,
            'last_error_time': None
        }
        
    async def initialize(self, redis_url: str):
        """Initialize Redis connection pool"""
        if aioredis is None:
            raise ImportError("aioredis is required for Redis connection pooling")
        
        try:
            # Enhanced Redis connection pool configuration based on official documentation
            # Following https://redis.io/docs/latest/develop/clients/redis-py/connect/#connect-with-a-connection-pool
            self.pool = aioredis.ConnectionPool.from_url(
                redis_url,
                # Core pool settings from official Redis documentation
                max_connections=self.config.redis_max_connections,
                retry_on_timeout=self.config.redis_retry_on_timeout,
                health_check_interval=self.config.redis_health_check_interval,
                decode_responses=False,

                # Production optimizations based on official Redis best practices
                socket_keepalive=self.config.redis_socket_keepalive,          # Enable TCP keepalive for connection stability
                socket_keepalive_options={},                                  # Use system defaults for keepalive options
                socket_connect_timeout=self.config.redis_socket_connect_timeout,  # Connection establishment timeout
                socket_timeout=self.config.redis_socket_timeout,             # Socket operation timeout

                # Connection lifecycle management
                retry_on_error=[ConnectionError, TimeoutError],  # Retry on connection issues

                # Performance optimizations
                connection_class=aioredis.Connection,  # Use efficient async connection class
            )
            
            self.redis = aioredis.Redis(connection_pool=self.pool)
            
            # Test connection
            await self.redis.ping()
            
            self._stats['created_total'] += self.config.redis_min_connections
            
            # Update metrics
            connection_pool_size.labels(
                pool_type='redis',
                pool_name=self.name
            ).set(self.config.redis_max_connections)
            
            logger.info(
                "redis_pool_initialized",
                name=self.name,
                max_connections=self.config.redis_max_connections
            )
            
        except Exception as e:
            self._record_error(e)
            logger.error("redis_pool_init_failed", name=self.name, error=str(e))
            raise
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire Redis connection with metrics"""
        if not self.redis:
            raise RuntimeError(f"Redis pool {self.name} not initialized")
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Redis client handles connection pooling internally
            yield self.redis
            
            # Record acquisition time
            acquisition_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            connection_acquisition_duration.labels(
                pool_type='redis',
                pool_name=self.name
            ).observe(acquisition_time)
            
            self._update_metrics()
            
        except Exception as e:
            self._record_error(e)
            raise
    
    def get_redis(self) -> aioredis.Redis:
        """Get Redis client directly (for compatibility)"""
        if not self.redis:
            raise RuntimeError(f"Redis pool {self.name} not initialized")
        return self.redis
    
    def _record_error(self, error: Exception):
        """Record error in stats and metrics"""
        self._stats['errors_total'] += 1
        self._stats['last_error'] = str(error)
        self._stats['last_error_time'] = datetime.now(timezone.utc)
        
        connection_pool_errors.labels(
            pool_type='redis',
            pool_name=self.name,
            error_type=type(error).__name__
        ).inc()
    
    def _update_metrics(self):
        """Update Prometheus metrics"""
        if self.pool:
            # Redis pool metrics are harder to get, use approximations
            connection_pool_active.labels(
                pool_type='redis',
                pool_name=self.name
            ).set(self.pool.created_connections)
            
            connection_pool_idle.labels(
                pool_type='redis',
                pool_name=self.name
            ).set(max(0, self.config.redis_max_connections - self.pool.created_connections))
    
    def get_stats(self) -> ConnectionPoolStats:
        """Get connection pool statistics"""
        active = 0
        idle = 0
        size = 0
        
        if self.pool:
            size = self.pool.created_connections
            active = size  # Redis doesn't expose idle connections easily
            idle = max(0, self.config.redis_max_connections - active)
        
        return ConnectionPoolStats(
            pool_name=self.name,
            pool_type='redis',
            size=size,
            active=active,
            idle=idle,
            created_total=self._stats['created_total'],
            closed_total=self._stats['closed_total'],
            errors_total=self._stats['errors_total'],
            last_error=self._stats['last_error'],
            last_error_time=self._stats['last_error_time']
        )
    
    async def close(self):
        """Close Redis pool"""
        if self.redis:
            await self.redis.close()
        if self.pool:
            await self.pool.disconnect()
        logger.info("redis_pool_closed", name=self.name)


class HTTPPool:
    """HTTP client connection pool wrapper"""
    
    def __init__(self, name: str, config: ConnectionPoolConfig):
        self.name = name
        self.config = config
        self.client: Optional[httpx.AsyncClient] = None
        self._stats = {
            'created_total': 0,
            'closed_total': 0,
            'errors_total': 0,
            'last_error': None,
            'last_error_time': None
        }
        
    async def initialize(self, **client_kwargs):
        """Initialize HTTP client with connection pooling"""
        try:
            # Configure connection limits
            limits = httpx.Limits(
                max_keepalive_connections=self.config.http_max_keepalive,
                max_connections=self.config.http_max_connections,
                keepalive_expiry=self.config.http_keepalive_expiry
            )
            
            # Configure timeout
            timeout = httpx.Timeout(self.config.http_timeout)
            
            # Default headers
            headers = {
                "User-Agent": f"VoiceHive-Orchestrator/{self.name}/1.0",
                "Accept": "application/json",
                "Connection": "keep-alive"
            }
            
            # Merge with provided kwargs
            client_kwargs.setdefault('limits', limits)
            client_kwargs.setdefault('timeout', timeout)
            client_kwargs.setdefault('headers', headers)
            
            self.client = httpx.AsyncClient(**client_kwargs)
            
            self._stats['created_total'] += 1
            
            # Update metrics
            connection_pool_size.labels(
                pool_type='http',
                pool_name=self.name
            ).set(self.config.http_max_connections)
            
            logger.info(
                "http_pool_initialized",
                name=self.name,
                max_connections=self.config.http_max_connections,
                max_keepalive=self.config.http_max_keepalive
            )
            
        except Exception as e:
            self._record_error(e)
            logger.error("http_pool_init_failed", name=self.name, error=str(e))
            raise
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire HTTP client with metrics"""
        if not self.client:
            raise RuntimeError(f"HTTP pool {self.name} not initialized")
        
        start_time = datetime.now(timezone.utc)
        
        try:
            yield self.client
            
            # Record acquisition time
            acquisition_time = (datetime.now(timezone.utc) - start_time).total_seconds()
            connection_acquisition_duration.labels(
                pool_type='http',
                pool_name=self.name
            ).observe(acquisition_time)
            
            self._update_metrics()
            
        except Exception as e:
            self._record_error(e)
            raise
    
    def get_client(self) -> httpx.AsyncClient:
        """Get HTTP client directly (for compatibility)"""
        if not self.client:
            raise RuntimeError(f"HTTP pool {self.name} not initialized")
        return self.client
    
    def _record_error(self, error: Exception):
        """Record error in stats and metrics"""
        self._stats['errors_total'] += 1
        self._stats['last_error'] = str(error)
        self._stats['last_error_time'] = datetime.now(timezone.utc)
        
        connection_pool_errors.labels(
            pool_type='http',
            pool_name=self.name,
            error_type=type(error).__name__
        ).inc()
    
    def _update_metrics(self):
        """Update Prometheus metrics"""
        # HTTP client doesn't expose detailed connection stats
        # Use approximations based on configuration
        connection_pool_active.labels(
            pool_type='http',
            pool_name=self.name
        ).set(self.config.http_max_keepalive // 2)  # Estimate
        
        connection_pool_idle.labels(
            pool_type='http',
            pool_name=self.name
        ).set(self.config.http_max_keepalive // 2)  # Estimate
    
    def get_stats(self) -> ConnectionPoolStats:
        """Get connection pool statistics"""
        return ConnectionPoolStats(
            pool_name=self.name,
            pool_type='http',
            size=self.config.http_max_connections,
            active=self.config.http_max_keepalive // 2,  # Estimate
            idle=self.config.http_max_keepalive // 2,    # Estimate
            created_total=self._stats['created_total'],
            closed_total=self._stats['closed_total'],
            errors_total=self._stats['errors_total'],
            last_error=self._stats['last_error'],
            last_error_time=self._stats['last_error_time']
        )
    
    async def close(self):
        """Close HTTP client"""
        if self.client:
            await self.client.aclose()
            self._stats['closed_total'] += 1
        logger.info("http_pool_closed", name=self.name)


class ConnectionPoolManager:
    """Centralized connection pool manager"""
    
    def __init__(self, config: Optional[ConnectionPoolConfig] = None):
        self.config = config or ConnectionPoolConfig()
        self.db_pools: Dict[str, DatabasePool] = {}
        self.redis_pools: Dict[str, RedisPool] = {}
        self.http_pools: Dict[str, HTTPPool] = {}
        self._memory_monitor_task: Optional[asyncio.Task] = None
        self._connection_test_task: Optional[asyncio.Task] = None
        
    async def initialize(self):
        """Initialize connection pool manager"""
        logger.info("connection_pool_manager_initializing")
        
        # Start background tasks
        if self.config.memory_check_interval > 0:
            self._memory_monitor_task = asyncio.create_task(self._monitor_memory())
        
        if self.config.connection_test_interval > 0:
            self._connection_test_task = asyncio.create_task(self._test_connections())
        
        logger.info("connection_pool_manager_initialized")
    
    async def create_database_pool(
        self,
        name: str,
        database_url: str,
        config: Optional[ConnectionPoolConfig] = None
    ) -> DatabasePool:
        """Create and initialize database connection pool"""
        if name in self.db_pools:
            logger.warning("database_pool_already_exists", name=name)
            return self.db_pools[name]
        
        pool_config = config or self.config
        pool = DatabasePool(name, pool_config)
        await pool.initialize(database_url)
        
        self.db_pools[name] = pool
        logger.info("database_pool_created", name=name)
        
        return pool
    
    async def create_redis_pool(
        self,
        name: str,
        redis_url: str,
        config: Optional[ConnectionPoolConfig] = None
    ) -> RedisPool:
        """Create and initialize Redis connection pool"""
        if name in self.redis_pools:
            logger.warning("redis_pool_already_exists", name=name)
            return self.redis_pools[name]
        
        pool_config = config or self.config
        pool = RedisPool(name, pool_config)
        await pool.initialize(redis_url)
        
        self.redis_pools[name] = pool
        logger.info("redis_pool_created", name=name)
        
        return pool
    
    async def create_http_pool(
        self,
        name: str,
        config: Optional[ConnectionPoolConfig] = None,
        **client_kwargs
    ) -> HTTPPool:
        """Create and initialize HTTP connection pool"""
        if name in self.http_pools:
            logger.warning("http_pool_already_exists", name=name)
            return self.http_pools[name]
        
        pool_config = config or self.config
        pool = HTTPPool(name, pool_config)
        await pool.initialize(**client_kwargs)
        
        self.http_pools[name] = pool
        logger.info("http_pool_created", name=name)
        
        return pool
    
    def get_database_pool(self, name: str) -> Optional[DatabasePool]:
        """Get database pool by name"""
        return self.db_pools.get(name)
    
    def get_redis_pool(self, name: str) -> Optional[RedisPool]:
        """Get Redis pool by name"""
        return self.redis_pools.get(name)
    
    def get_http_pool(self, name: str) -> Optional[HTTPPool]:
        """Get HTTP pool by name"""
        return self.http_pools.get(name)
    
    async def get_all_stats(self) -> Dict[str, List[ConnectionPoolStats]]:
        """Get statistics for all connection pools"""
        stats = {
            'database': [pool.get_stats() for pool in self.db_pools.values()],
            'redis': [pool.get_stats() for pool in self.redis_pools.values()],
            'http': [pool.get_stats() for pool in self.http_pools.values()]
        }
        
        return stats
    
    async def health_check(self) -> Dict[str, Dict[str, bool]]:
        """Health check all connection pools"""
        results = {
            'database': {},
            'redis': {},
            'http': {}
        }
        
        # Test database pools
        for name, pool in self.db_pools.items():
            try:
                if pool.pool:
                    async with pool.acquire() as conn:
                        await conn.fetchval("SELECT 1")
                    results['database'][name] = True
                else:
                    results['database'][name] = False
            except Exception as e:
                logger.error("database_pool_health_check_failed", name=name, error=str(e))
                results['database'][name] = False
        
        # Test Redis pools
        for name, pool in self.redis_pools.items():
            try:
                if pool.redis:
                    await pool.redis.ping()
                    results['redis'][name] = True
                else:
                    results['redis'][name] = False
            except Exception as e:
                logger.error("redis_pool_health_check_failed", name=name, error=str(e))
                results['redis'][name] = False
        
        # Test HTTP pools
        for name, pool in self.http_pools.items():
            try:
                if pool.client:
                    # HTTP pools are considered healthy if client exists
                    results['http'][name] = True
                else:
                    results['http'][name] = False
            except Exception as e:
                logger.error("http_pool_health_check_failed", name=name, error=str(e))
                results['http'][name] = False
        
        return results
    
    async def _monitor_memory(self):
        """Monitor memory usage and log warnings"""
        if psutil is None:
            logger.warning("psutil not available, memory monitoring disabled")
            return
        
        while True:
            try:
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                
                if memory_mb > self.config.max_memory_mb:
                    logger.warning(
                        "high_memory_usage",
                        current_mb=memory_mb,
                        limit_mb=self.config.max_memory_mb
                    )
                
                # Update memory stats for all pools
                for pool in self.db_pools.values():
                    stats = pool.get_stats()
                    stats.memory_usage_mb = memory_mb / len(self.db_pools) if self.db_pools else 0
                
                await asyncio.sleep(self.config.memory_check_interval)
                
            except Exception as e:
                logger.error("memory_monitor_error", error=str(e))
                await asyncio.sleep(60)  # Fallback interval
    
    async def _test_connections(self):
        """Periodically test all connections"""
        while True:
            try:
                await asyncio.sleep(self.config.connection_test_interval)
                
                # Test all pools
                health_results = await self.health_check()
                
                # Log any unhealthy pools
                for pool_type, pools in health_results.items():
                    for pool_name, is_healthy in pools.items():
                        if not is_healthy:
                            logger.warning(
                                "connection_pool_unhealthy",
                                pool_type=pool_type,
                                pool_name=pool_name
                            )
                
            except Exception as e:
                logger.error("connection_test_error", error=str(e))
    
    async def close_all(self):
        """Close all connection pools"""
        logger.info("closing_all_connection_pools")
        
        # Cancel background tasks
        if self._memory_monitor_task:
            self._memory_monitor_task.cancel()
        if self._connection_test_task:
            self._connection_test_task.cancel()
        
        # Close all pools
        for pool in self.db_pools.values():
            try:
                await pool.close()
            except Exception as e:
                logger.error("database_pool_close_error", error=str(e))
        
        for pool in self.redis_pools.values():
            try:
                await pool.close()
            except Exception as e:
                logger.error("redis_pool_close_error", error=str(e))
        
        for pool in self.http_pools.values():
            try:
                await pool.close()
            except Exception as e:
                logger.error("http_pool_close_error", error=str(e))
        
        # Clear pools
        self.db_pools.clear()
        self.redis_pools.clear()
        self.http_pools.clear()
        
        logger.info("all_connection_pools_closed")


# Global connection pool manager instance
_pool_manager: Optional[ConnectionPoolManager] = None


def get_connection_pool_manager(
    config: Optional[ConnectionPoolConfig] = None
) -> ConnectionPoolManager:
    """Get or create global connection pool manager"""
    global _pool_manager
    
    if _pool_manager is None:
        _pool_manager = ConnectionPoolManager(config)
        logger.info("global_connection_pool_manager_created")
    
    return _pool_manager


async def initialize_default_pools(
    database_url: Optional[str] = None,
    redis_url: Optional[str] = None,
    config: Optional[ConnectionPoolConfig] = None
) -> ConnectionPoolManager:
    """Initialize default connection pools"""
    manager = get_connection_pool_manager(config)
    await manager.initialize()
    
    # Create default database pool if URL provided
    if database_url:
        await manager.create_database_pool("default", database_url)
    
    # Create default Redis pool if URL provided
    if redis_url:
        await manager.create_redis_pool("default", redis_url)
    
    # Create default HTTP pools for common services
    await manager.create_http_pool("tts_service")
    await manager.create_http_pool("asr_service")
    await manager.create_http_pool("pms_connector")
    await manager.create_http_pool("external_api")
    
    logger.info("default_connection_pools_initialized")
    return manager