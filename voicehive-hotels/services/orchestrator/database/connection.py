"""
Database connection and session management for VoiceHive Hotels
Enhanced with circuit breaker protection for resilient database operations
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Dict, Any, Union
from urllib.parse import quote_plus
import time

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.engine.events import event
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, OperationalError, TimeoutError as SQLTimeoutError

# Direct asyncpg import for high-performance connection pooling
try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None

from config import get_config
from logging_adapter import get_safe_logger

# Import circuit breaker from resilience infrastructure with fallback
try:
    from resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerOpenError, CircuitBreakerTimeoutError
    import redis.asyncio as aioredis
    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError as e:
    # Fallback - circuit breaker not available
    logger = get_safe_logger("orchestrator.database.connection")
    logger.warning(f"Circuit breaker not available for database operations: {e}")
    CircuitBreaker = None
    CircuitBreakerConfig = None
    CircuitBreakerOpenError = Exception
    CircuitBreakerTimeoutError = Exception
    CIRCUIT_BREAKER_AVAILABLE = False

# Prometheus metrics for database performance monitoring
try:
    from prometheus_client import Counter, Histogram, Gauge

    database_operations_total = Counter(
        'voicehive_database_operations_total',
        'Total database operations',
        ['operation', 'status']
    )

    database_operation_duration_seconds = Histogram(
        'voicehive_database_operation_duration_seconds',
        'Database operation duration in seconds',
        ['operation'],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)
    )

    database_circuit_breaker_state = Gauge(
        'voicehive_database_circuit_breaker_state',
        'Database circuit breaker state (0=closed, 1=open, 2=half-open)',
        ['breaker_name']
    )

    # Enhanced connection pool metrics
    database_connection_pool_size = Gauge(
        'voicehive_database_connection_pool_size',
        'Current database connection pool size',
        ['pool_type']  # 'sqlalchemy' or 'asyncpg'
    )

    database_connection_pool_checked_in = Gauge(
        'voicehive_database_connection_pool_checked_in',
        'Number of connections currently checked in to the pool',
        ['pool_type']
    )

    database_connection_pool_checked_out = Gauge(
        'voicehive_database_connection_pool_checked_out',
        'Number of connections currently checked out from the pool',
        ['pool_type']
    )

    database_connection_pool_overflow = Gauge(
        'voicehive_database_connection_pool_overflow',
        'Number of overflow connections in the pool',
        ['pool_type']
    )

    database_connection_pool_invalid = Gauge(
        'voicehive_database_connection_pool_invalid',
        'Number of invalid connections in the pool',
        ['pool_type']
    )

    database_connection_acquire_duration_seconds = Histogram(
        'voicehive_database_connection_acquire_duration_seconds',
        'Time taken to acquire a connection from the pool',
        ['pool_type'],
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
    )

    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False

logger = get_safe_logger("orchestrator.database.connection")

class DatabaseManager:
    """Manages database connections and sessions with circuit breaker protection"""

    def __init__(self):
        self.engine = None
        self.async_session_factory = None
        self._config = get_config()
        self._circuit_breakers = {}

        # Direct asyncpg connection pool for high-performance operations
        self._asyncpg_pool: Optional[asyncpg.Pool] = None
        self._asyncpg_dsn: Optional[str] = None

        # Initialize circuit breakers if available
        if CIRCUIT_BREAKER_AVAILABLE and CircuitBreaker is not None:
            self._initialize_circuit_breakers()
        else:
            logger.warning("Circuit breakers not available for database operations")

    def _initialize_circuit_breakers(self) -> None:
        """Initialize circuit breakers for database operations"""
        try:
            # Get Redis client for circuit breaker state sharing
            redis_client = None
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                try:
                    redis_client = aioredis.from_url(redis_url)
                except Exception as e:
                    logger.warning(f"Failed to connect to Redis for database circuit breaker: {e}")

            # Circuit breaker for connection operations
            connection_config = CircuitBreakerConfig(
                name="database_connection",
                failure_threshold=3,  # Fail after 3 connection failures
                recovery_timeout=120,  # 2 minute recovery for connection issues
                timeout=30.0,  # Connection timeout
                expected_exception=(OperationalError, SQLTimeoutError, SQLAlchemyError)
            )
            self._circuit_breakers["connection"] = CircuitBreaker(connection_config, redis_client)

            # Circuit breaker for query operations
            query_config = CircuitBreakerConfig(
                name="database_query",
                failure_threshold=5,  # More tolerant for query operations
                recovery_timeout=60,  # 1 minute recovery for queries
                timeout=15.0,  # Query timeout
                expected_exception=(OperationalError, SQLTimeoutError, SQLAlchemyError)
            )
            self._circuit_breakers["query"] = CircuitBreaker(query_config, redis_client)

            # Circuit breaker for transaction operations
            transaction_config = CircuitBreakerConfig(
                name="database_transaction",
                failure_threshold=4,  # Moderate tolerance for transactions
                recovery_timeout=90,  # 1.5 minute recovery for transactions
                timeout=30.0,  # Transaction timeout
                expected_exception=(OperationalError, SQLTimeoutError, SQLAlchemyError)
            )
            self._circuit_breakers["transaction"] = CircuitBreaker(transaction_config, redis_client)

            logger.info(
                "database_circuit_breakers_initialized",
                connection_threshold=connection_config.failure_threshold,
                query_threshold=query_config.failure_threshold,
                transaction_threshold=transaction_config.failure_threshold
            )

        except Exception as e:
            logger.error(f"Failed to initialize database circuit breakers: {e}")
            self._circuit_breakers = {}  # Clear any partial initialization

    async def _initialize_asyncpg_pool(self, db_config) -> None:
        """Initialize direct asyncpg connection pool for high-performance operations"""
        try:
            # Build asyncpg DSN
            self._asyncpg_dsn = (
                f"postgresql://"
                f"{db_config.username}:{db_config.password}@"
                f"{db_config.host}:{db_config.port}/"
                f"{db_config.database}"
            )

            # Add SSL mode if specified
            ssl_context = None
            if db_config.ssl_mode != "disable":
                import ssl
                ssl_context = ssl.create_default_context()
                if db_config.ssl_mode == "require":
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

            # Create asyncpg connection pool with optimized settings
            # Based on official asyncpg documentation best practices
            self._asyncpg_pool = await asyncpg.create_pool(
                self._asyncpg_dsn,
                # Pool sizing - following asyncpg best practices
                min_size=max(db_config.pool_size // 2, 5),  # Minimum 5 connections
                max_size=max(db_config.pool_size + db_config.max_overflow, 30),  # Allow more for high performance

                # Connection management
                max_queries=50000,  # Rotate connections after 50k queries
                max_inactive_connection_lifetime=300.0,  # 5 minutes idle timeout

                # Performance settings
                command_timeout=30.0,  # 30 second command timeout
                server_settings={
                    'application_name': 'voicehive_orchestrator_asyncpg',
                    'timezone': 'UTC',
                    'statement_timeout': '30000',  # 30 seconds
                    'lock_timeout': '10000',       # 10 seconds
                    'idle_in_transaction_session_timeout': '300000',  # 5 minutes
                },

                # SSL configuration
                ssl=ssl_context,

                # Connection initialization
                init=self._init_asyncpg_connection,
            )

            logger.info(
                "asyncpg_pool_initialized",
                min_size=self._asyncpg_pool._minsize,
                max_size=self._asyncpg_pool._maxsize,
                max_queries=50000,
                ssl_enabled=ssl_context is not None
            )

        except Exception as e:
            logger.error(f"Failed to initialize asyncpg connection pool: {e}")
            self._asyncpg_pool = None

    async def _init_asyncpg_connection(self, connection):
        """Initialize each asyncpg connection with custom settings"""
        try:
            # Set up any connection-level configuration
            await connection.execute("SET timezone = 'UTC'")
            await connection.execute("SET statement_timeout = '30000'")
            await connection.execute("SET lock_timeout = '10000'")

            # Register custom types if needed
            # await connection.set_type_codec('uuid', encoder=str, decoder=uuid.UUID, schema='pg_catalog')

        except Exception as e:
            logger.warning(f"Failed to initialize asyncpg connection: {e}")

    async def initialize(self) -> None:
        """Initialize database engine and session factory with circuit breaker protection"""
        if self.engine is not None:
            logger.warning("Database already initialized")
            return

        async def _do_initialization():
            """Inner initialization function for circuit breaker"""
            # Build connection URL
            db_config = self._config.database

            # URL encode password to handle special characters
            encoded_password = quote_plus(db_config.password)

            database_url = (
                f"postgresql+asyncpg://"
                f"{db_config.username}:{encoded_password}@"
                f"{db_config.host}:{db_config.port}/"
                f"{db_config.database}"
            )

            # Add SSL mode if specified
            if db_config.ssl_mode != "disable":
                database_url += f"?sslmode={db_config.ssl_mode}"

            # Create async engine with optimized settings
            self.engine = create_async_engine(
                database_url,
                # Connection pool settings - optimized for high performance
                poolclass=QueuePool,
                pool_size=max(db_config.pool_size, 10),  # Minimum 10 connections
                max_overflow=max(db_config.max_overflow, 20),  # Allow more overflow
                pool_timeout=30,  # seconds
                pool_recycle=3600,  # 1 hour
                pool_pre_ping=True,  # Validate connections before use

                # Performance settings
                echo=False,  # Set to True for SQL debugging
                future=True,

                # Async settings
                connect_args={
                    "server_settings": {
                        "application_name": "voicehive_orchestrator",
                        "statement_timeout": "30000",  # 30 seconds
                        "lock_timeout": "10000",       # 10 seconds
                        "idle_in_transaction_session_timeout": "300000",  # 5 minutes
                    },
                    "command_timeout": 30,
                }
            )

            # Initialize direct asyncpg connection pool for high-performance operations
            if ASYNCPG_AVAILABLE:
                await self._initialize_asyncpg_pool(db_config)

            # Create session factory
            self.async_session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,  # Keep objects accessible after commit
                autoflush=True,
                autocommit=False,
            )

            # Register event listeners
            self._register_event_listeners()

            # Test connection
            await self._test_connection()

            # Record success metrics
            if METRICS_AVAILABLE:
                database_operations_total.labels(operation="initialize", status="success").inc()

            logger.info(
                "database_initialized",
                host=db_config.host,
                port=db_config.port,
                database=db_config.database,
                pool_size=db_config.pool_size,
                ssl_mode=db_config.ssl_mode
            )

        try:
            # Use circuit breaker if available
            if "connection" in self._circuit_breakers:
                await self._circuit_breakers["connection"].call(_do_initialization)
            else:
                await _do_initialization()

        except CircuitBreakerOpenError as e:
            # Record circuit breaker metrics
            if METRICS_AVAILABLE:
                database_operations_total.labels(operation="initialize", status="circuit_breaker_open").inc()

            logger.error(
                "database_initialization_circuit_breaker_open",
                circuit_name=e.circuit_name,
                next_attempt=e.next_attempt_time,
                host=getattr(self._config.database, 'host', 'unknown')
            )
            raise Exception(f"Database initialization temporarily unavailable: {e}")

        except CircuitBreakerTimeoutError as e:
            # Record timeout metrics
            if METRICS_AVAILABLE:
                database_operations_total.labels(operation="initialize", status="timeout").inc()

            logger.error(
                "database_initialization_timeout",
                error=str(e),
                host=getattr(self._config.database, 'host', 'unknown')
            )
            raise Exception(f"Database initialization timeout: {e}")

        except Exception as e:
            # Record error metrics
            if METRICS_AVAILABLE:
                database_operations_total.labels(operation="initialize", status="error").inc()

            logger.error(
                "database_initialization_failed",
                error=str(e),
                host=getattr(self._config.database, 'host', 'unknown'),
                port=getattr(self._config.database, 'port', 'unknown')
            )
            raise

    async def _test_connection(self) -> None:
        """Test database connection with circuit breaker protection"""

        async def _do_connection_test():
            """Inner connection test function for circuit breaker"""
            async with self.get_session() as session:
                result = await session.execute(text("SELECT 1 as test"))
                test_value = result.scalar()
                if test_value != 1:
                    raise Exception("Database connection test failed")

                # Test database version
                result = await session.execute(text("SELECT version()"))
                version = result.scalar()
                logger.info("database_connection_test_passed", version=version[:100])

        try:
            # Use circuit breaker if available
            if "query" in self._circuit_breakers:
                await self._circuit_breakers["query"].call(_do_connection_test)
            else:
                await _do_connection_test()

        except CircuitBreakerOpenError as e:
            logger.error(
                "database_connection_test_circuit_breaker_open",
                circuit_name=e.circuit_name,
                next_attempt=e.next_attempt_time
            )
            raise Exception(f"Database connection test temporarily unavailable: {e}")

        except CircuitBreakerTimeoutError as e:
            logger.error(
                "database_connection_test_timeout",
                error=str(e)
            )
            raise Exception(f"Database connection test timeout: {e}")

        except Exception as e:
            logger.error("database_connection_test_failed", error=str(e))
            raise

    def _register_event_listeners(self) -> None:
        """Register SQLAlchemy event listeners for monitoring"""

        @event.listens_for(self.engine.sync_engine, "connect")
        def receive_connect(dbapi_connection, connection_record):
            """Log new database connections"""
            logger.debug("database_connection_created")

        @event.listens_for(self.engine.sync_engine, "checkout")
        def receive_checkout(dbapi_connection, connection_record, connection_proxy):
            """Log connection checkout from pool"""
            logger.debug("database_connection_checkout")

        @event.listens_for(self.engine.sync_engine, "checkin")
        def receive_checkin(dbapi_connection, connection_record):
            """Log connection checkin to pool"""
            logger.debug("database_connection_checkin")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session with automatic cleanup and circuit breaker protection"""
        if self.async_session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        # For session creation, we use a lighter approach since the session factory
        # itself doesn't perform database operations until queries are executed
        async with self.async_session_factory() as session:
            try:
                yield session
                # Record successful session operation
                if METRICS_AVAILABLE:
                    database_operations_total.labels(operation="session", status="success").inc()
            except (OperationalError, SQLTimeoutError, SQLAlchemyError) as e:
                logger.error("database_session_error", error=str(e))
                await session.rollback()
                # Record database error
                if METRICS_AVAILABLE:
                    database_operations_total.labels(operation="session", status="error").inc()
                raise
            except Exception as e:
                logger.error("database_session_error", error=str(e))
                await session.rollback()
                raise
            finally:
                await session.close()

    async def health_check(self) -> dict:
        """Perform database health check with circuit breaker information"""
        if self.engine is None:
            return {
                "status": "unhealthy",
                "error": "Database not initialized",
                "circuit_breakers": {},
                "circuit_breaker_enabled": False
            }

        # Get circuit breaker statistics
        circuit_breaker_stats = await self.get_circuit_breaker_stats()

        async def _do_health_check():
            """Inner health check function for circuit breaker"""
            async with self.get_session() as session:
                # Test basic query
                result = await session.execute(text("SELECT 1"))
                test_value = result.scalar()

                # Get comprehensive connection pool stats
                connection_pool_stats = await self.get_connection_pool_stats()

                return {
                    "status": "healthy",
                    "test_query_result": test_value,
                    "connection_pools": connection_pool_stats["pools"],
                    "ssl_mode": self._config.database.ssl_mode,
                    "asyncpg_pool_available": self._asyncpg_pool is not None,
                    "circuit_breakers": circuit_breaker_stats,
                    "circuit_breaker_enabled": len(self._circuit_breakers) > 0
                }

        try:
            # Use circuit breaker if available
            if "query" in self._circuit_breakers:
                return await self._circuit_breakers["query"].call(_do_health_check)
            else:
                return await _do_health_check()

        except CircuitBreakerOpenError as e:
            return {
                "status": "degraded",
                "error": f"Circuit breaker open: {e}",
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0
            }

        except CircuitBreakerTimeoutError as e:
            return {
                "status": "degraded",
                "error": f"Database health check timeout: {e}",
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0
            }

        except Exception as e:
            logger.error("database_health_check_failed", error=str(e))
            return {
                "status": "unhealthy",
                "error": str(e),
                "circuit_breakers": circuit_breaker_stats,
                "circuit_breaker_enabled": len(self._circuit_breakers) > 0
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

                    # Update Prometheus metrics for circuit breaker state
                    if METRICS_AVAILABLE:
                        state_value = 0 if breaker_stats.state.value == "closed" else (1 if breaker_stats.state.value == "open" else 2)
                        database_circuit_breaker_state.labels(breaker_name=name).set(state_value)

                except Exception as e:
                    stats[name] = {"error": f"Failed to get stats: {e}"}
        return stats

    async def execute_with_circuit_breaker(
        self,
        operation_name: str,
        operation_func,
        circuit_breaker_type: str = "query"
    ):
        """
        Execute a database operation with circuit breaker protection.

        Args:
            operation_name: Name of the operation for metrics
            operation_func: Async function to execute
            circuit_breaker_type: Type of circuit breaker to use (query, transaction, connection)
        """
        import time
        start_time = time.time()

        try:
            # Use circuit breaker if available
            if circuit_breaker_type in self._circuit_breakers:
                result = await self._circuit_breakers[circuit_breaker_type].call(operation_func)
            else:
                result = await operation_func()

            # Record success metrics
            if METRICS_AVAILABLE:
                duration = time.time() - start_time
                database_operation_duration_seconds.labels(operation=operation_name).observe(duration)
                database_operations_total.labels(operation=operation_name, status="success").inc()

            return result

        except CircuitBreakerOpenError as e:
            # Record circuit breaker metrics
            if METRICS_AVAILABLE:
                database_operations_total.labels(operation=operation_name, status="circuit_breaker_open").inc()

            logger.error(
                f"database_{operation_name}_circuit_breaker_open",
                circuit_name=e.circuit_name,
                next_attempt=e.next_attempt_time
            )
            raise Exception(f"Database {operation_name} temporarily unavailable: {e}")

        except CircuitBreakerTimeoutError as e:
            # Record timeout metrics
            if METRICS_AVAILABLE:
                database_operations_total.labels(operation=operation_name, status="timeout").inc()

            logger.error(
                f"database_{operation_name}_timeout",
                error=str(e)
            )
            raise Exception(f"Database {operation_name} timeout: {e}")

        except Exception as e:
            # Record error metrics
            if METRICS_AVAILABLE:
                database_operations_total.labels(operation=operation_name, status="error").inc()

            logger.error(f"database_{operation_name}_failed", error=str(e))
            raise

    @asynccontextmanager
    async def get_asyncpg_connection(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """
        Get a direct asyncpg connection for high-performance operations.

        Use this for operations that don't need the SQLAlchemy ORM overhead,
        such as bulk inserts, simple queries, or custom SQL operations.
        """
        if not ASYNCPG_AVAILABLE or self._asyncpg_pool is None:
            raise RuntimeError("Asyncpg connection pool not available. Use get_session() instead.")

        start_time = time.time()

        try:
            async with self._asyncpg_pool.acquire() as connection:
                # Record connection acquisition metrics
                if METRICS_AVAILABLE:
                    duration = time.time() - start_time
                    database_connection_acquire_duration_seconds.labels(pool_type="asyncpg").observe(duration)

                yield connection

        except Exception as e:
            logger.error("asyncpg_connection_error", error=str(e))
            raise

    async def execute_raw_query(
        self,
        query: str,
        *args,
        fetch: str = "all",
        circuit_breaker_type: str = "query"
    ) -> Union[list, dict, None]:
        """
        Execute a raw SQL query using the asyncpg connection pool.

        Args:
            query: SQL query string
            *args: Query parameters
            fetch: 'all', 'one', 'val', or 'none'
            circuit_breaker_type: Circuit breaker type to use

        Returns:
            Query results based on fetch type
        """
        if not ASYNCPG_AVAILABLE or self._asyncpg_pool is None:
            raise RuntimeError("Asyncpg connection pool not available")

        async def _execute_query():
            async with self.get_asyncpg_connection() as conn:
                if fetch == "all":
                    return await conn.fetch(query, *args)
                elif fetch == "one":
                    return await conn.fetchrow(query, *args)
                elif fetch == "val":
                    return await conn.fetchval(query, *args)
                elif fetch == "none":
                    await conn.execute(query, *args)
                    return None
                else:
                    raise ValueError(f"Invalid fetch type: {fetch}")

        return await self.execute_with_circuit_breaker(
            operation_name=f"raw_query_{fetch}",
            operation_func=_execute_query,
            circuit_breaker_type=circuit_breaker_type
        )

    async def get_connection_pool_stats(self) -> Dict[str, Any]:
        """Get detailed connection pool statistics for both SQLAlchemy and asyncpg pools"""
        stats = {"pools": {}}

        # SQLAlchemy pool stats
        if self.engine is not None:
            pool = self.engine.pool
            sqlalchemy_stats = {
                "type": "SQLAlchemy",
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "invalid": pool.invalid(),
                "total_connections": pool.size() + pool.overflow(),
                "utilization_percent": round((pool.checkedout() / max(pool.size(), 1)) * 100, 2)
            }
            stats["pools"]["sqlalchemy"] = sqlalchemy_stats

            # Update Prometheus metrics for SQLAlchemy pool
            if METRICS_AVAILABLE:
                database_connection_pool_size.labels(pool_type="sqlalchemy").set(pool.size())
                database_connection_pool_checked_in.labels(pool_type="sqlalchemy").set(pool.checkedin())
                database_connection_pool_checked_out.labels(pool_type="sqlalchemy").set(pool.checkedout())
                database_connection_pool_overflow.labels(pool_type="sqlalchemy").set(pool.overflow())
                database_connection_pool_invalid.labels(pool_type="sqlalchemy").set(pool.invalid())

        # Asyncpg pool stats
        if self._asyncpg_pool is not None:
            try:
                asyncpg_stats = {
                    "type": "asyncpg",
                    "min_size": self._asyncpg_pool._minsize,
                    "max_size": self._asyncpg_pool._maxsize,
                    "current_size": self._asyncpg_pool.get_size(),
                    "idle_connections": self._asyncpg_pool.get_idle_size(),
                    "active_connections": self._asyncpg_pool.get_size() - self._asyncpg_pool.get_idle_size(),
                    "utilization_percent": round(((self._asyncpg_pool.get_size() - self._asyncpg_pool.get_idle_size()) / max(self._asyncpg_pool._maxsize, 1)) * 100, 2),
                    "max_queries": 50000,
                    "max_inactive_lifetime": 300.0
                }
                stats["pools"]["asyncpg"] = asyncpg_stats

                # Update Prometheus metrics for asyncpg pool
                if METRICS_AVAILABLE:
                    database_connection_pool_size.labels(pool_type="asyncpg").set(self._asyncpg_pool.get_size())
                    database_connection_pool_checked_in.labels(pool_type="asyncpg").set(self._asyncpg_pool.get_idle_size())
                    database_connection_pool_checked_out.labels(pool_type="asyncpg").set(self._asyncpg_pool.get_size() - self._asyncpg_pool.get_idle_size())

            except Exception as e:
                stats["pools"]["asyncpg"] = {"error": f"Failed to get asyncpg pool stats: {e}"}

        return stats

    async def close(self) -> None:
        """Close database connections"""
        # Close SQLAlchemy engine
        if self.engine is not None:
            await self.engine.dispose()
            logger.info("sqlalchemy_engine_closed")
            self.engine = None
            self.async_session_factory = None

        # Close asyncpg pool
        if self._asyncpg_pool is not None:
            await self._asyncpg_pool.close()
            logger.info("asyncpg_pool_closed")
            self._asyncpg_pool = None

        logger.info("all_database_connections_closed")


# Global database manager instance
db_manager = DatabaseManager()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection for FastAPI to get database session"""
    async with db_manager.get_session() as session:
        yield session


async def initialize_database() -> None:
    """Initialize database connection (call during app startup)"""
    await db_manager.initialize()


async def close_database() -> None:
    """Close database connections (call during app shutdown)"""
    await db_manager.close()


async def get_database_health() -> dict:
    """Get database health status"""
    return await db_manager.health_check()