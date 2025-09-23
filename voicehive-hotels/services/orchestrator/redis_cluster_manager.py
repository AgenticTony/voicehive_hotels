"""
Redis Cluster Manager for VoiceHive Hotels Orchestrator
Production-grade Redis Cluster configuration and management
"""

import asyncio
import json
import hashlib
import time
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import weakref

try:
    import redis.asyncio as aioredis
    from redis.asyncio.cluster import RedisCluster
    from redis.exceptions import RedisClusterException, ConnectionError, TimeoutError
except ImportError:
    aioredis = None
    RedisCluster = None
    RedisClusterException = ConnectionError = TimeoutError = Exception

from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger

try:
    from prometheus_client import Counter, Histogram, Gauge
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
        def observe(self, value):
            pass
    
    Counter = Histogram = Gauge = MockMetric

logger = get_safe_logger("orchestrator.redis_cluster")

# Prometheus metrics for Redis Cluster monitoring
redis_cluster_operations_total = Counter(
    'voicehive_redis_cluster_operations_total',
    'Total Redis cluster operations',
    ['operation', 'node', 'result']
)

redis_cluster_operation_duration = Histogram(
    'voicehive_redis_cluster_operation_duration_seconds',
    'Redis cluster operation duration',
    ['operation', 'node'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

redis_cluster_connections = Gauge(
    'voicehive_redis_cluster_connections',
    'Redis cluster connections',
    ['node', 'status']
)

redis_cluster_memory_usage = Gauge(
    'voicehive_redis_cluster_memory_usage_bytes',
    'Redis cluster memory usage',
    ['node', 'type']
)

redis_cluster_keyspace_hits = Counter(
    'voicehive_redis_cluster_keyspace_hits_total',
    'Redis cluster keyspace hits',
    ['node']
)

redis_cluster_keyspace_misses = Counter(
    'voicehive_redis_cluster_keyspace_misses_total',
    'Redis cluster keyspace misses',
    ['node']
)

redis_cluster_evicted_keys = Counter(
    'voicehive_redis_cluster_evicted_keys_total',
    'Redis cluster evicted keys',
    ['node']
)


class ClusterNodeRole(str, Enum):
    """Redis cluster node roles"""
    MASTER = "master"
    SLAVE = "slave"
    UNKNOWN = "unknown"


class CacheInvalidationStrategy(str, Enum):
    """Cache invalidation strategies"""
    TTL_BASED = "ttl_based"
    TAG_BASED = "tag_based"
    PATTERN_BASED = "pattern_based"
    EVENT_DRIVEN = "event_driven"
    WRITE_THROUGH = "write_through"


@dataclass
class ClusterNode:
    """Redis cluster node information"""
    node_id: str
    host: str
    port: int
    role: ClusterNodeRole
    slots: List[Tuple[int, int]] = field(default_factory=list)
    flags: Set[str] = field(default_factory=set)
    master_id: Optional[str] = None
    ping_sent: int = 0
    pong_recv: int = 0
    config_epoch: int = 0
    link_state: str = "connected"
    
    @property
    def is_master(self) -> bool:
        return self.role == ClusterNodeRole.MASTER
    
    @property
    def is_slave(self) -> bool:
        return self.role == ClusterNodeRole.SLAVE
    
    @property
    def slot_count(self) -> int:
        return sum(end - start + 1 for start, end in self.slots)


class RedisClusterConfig(BaseModel):
    """Configuration for Redis Cluster"""
    # Cluster connection settings
    startup_nodes: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {"host": "redis-cluster-0", "port": 6379},
            {"host": "redis-cluster-1", "port": 6379},
            {"host": "redis-cluster-2", "port": 6379}
        ]
    )
    
    # Connection pool settings
    max_connections: int = Field(32, description="Maximum connections per node")
    max_connections_per_node: int = Field(16, description="Max connections per individual node")
    
    # Timeout settings
    socket_timeout: float = Field(5.0, description="Socket timeout in seconds")
    socket_connect_timeout: float = Field(5.0, description="Socket connect timeout")
    socket_keepalive: bool = Field(True, description="Enable socket keepalive")
    socket_keepalive_options: Dict[str, int] = Field(
        default_factory=lambda: {
            "TCP_KEEPIDLE": 1,
            "TCP_KEEPINTVL": 3,
            "TCP_KEEPCNT": 5
        }
    )
    
    # Retry settings
    retry_on_timeout: bool = Field(True, description="Retry on timeout")
    retry_on_cluster_down: bool = Field(True, description="Retry when cluster is down")
    max_retries: int = Field(3, description="Maximum retry attempts")
    retry_delay: float = Field(0.1, description="Delay between retries")
    
    # Cluster settings
    skip_full_coverage_check: bool = Field(False, description="Skip full coverage check")
    readonly_mode: bool = Field(False, description="Enable readonly mode")
    decode_responses: bool = Field(False, description="Decode responses to strings")
    
    # Health check settings
    health_check_interval: int = Field(30, description="Health check interval in seconds")
    node_failure_threshold: int = Field(3, description="Node failure threshold")
    
    # Performance settings
    pipeline_size: int = Field(100, description="Pipeline batch size")
    enable_compression: bool = Field(True, description="Enable data compression")
    compression_threshold: int = Field(1024, description="Compression threshold in bytes")
    
    # Monitoring settings
    enable_metrics: bool = Field(True, description="Enable Prometheus metrics")
    metrics_collection_interval: int = Field(60, description="Metrics collection interval")


class CacheWarmingConfig(BaseModel):
    """Configuration for cache warming strategies"""
    enabled: bool = Field(True, description="Enable cache warming")
    
    # Warming strategies
    preload_critical_data: bool = Field(True, description="Preload critical data on startup")
    background_refresh: bool = Field(True, description="Background refresh of expiring data")
    predictive_loading: bool = Field(False, description="Predictive cache loading")
    
    # Timing settings
    warmup_delay_seconds: int = Field(30, description="Delay before starting warmup")
    refresh_threshold_percent: int = Field(80, description="Refresh when TTL reaches this %")
    max_concurrent_warmups: int = Field(10, description="Max concurrent warming operations")
    
    # Data patterns
    critical_key_patterns: List[str] = Field(
        default_factory=lambda: [
            "hotel:*:config",
            "user:*:profile",
            "pms:*:credentials",
            "tts:*:settings"
        ]
    )
    
    # Warming functions
    warming_functions: Dict[str, str] = Field(
        default_factory=lambda: {
            "hotel_configs": "warm_hotel_configurations",
            "user_profiles": "warm_user_profiles",
            "pms_credentials": "warm_pms_credentials",
            "tts_settings": "warm_tts_settings"
        }
    )


class RedisClusterManager:
    """Production-grade Redis Cluster manager with advanced features"""
    
    def __init__(self, config: Optional[RedisClusterConfig] = None):
        self.config = config or RedisClusterConfig()
        self.cluster: Optional[RedisCluster] = None
        self.nodes: Dict[str, ClusterNode] = {}
        self.is_initialized = False
        
        # Monitoring and health
        self._health_check_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._node_failures: Dict[str, int] = {}
        
        # Performance tracking
        self._operation_stats: Dict[str, Dict[str, int]] = {}
        self._last_metrics_collection = time.time()
        
    async def initialize(self) -> bool:
        """Initialize Redis Cluster connection"""
        if RedisCluster is None:
            logger.error("redis_cluster_not_available", 
                        error="redis-py-cluster not installed")
            return False
        
        try:
            logger.info("initializing_redis_cluster", 
                       nodes=self.config.startup_nodes)
            
            # Create cluster connection
            self.cluster = RedisCluster(
                startup_nodes=self.config.startup_nodes,
                max_connections=self.config.max_connections,
                max_connections_per_node=self.config.max_connections_per_node,
                socket_timeout=self.config.socket_timeout,
                socket_connect_timeout=self.config.socket_connect_timeout,
                socket_keepalive=self.config.socket_keepalive,
                socket_keepalive_options=self.config.socket_keepalive_options,
                retry_on_timeout=self.config.retry_on_timeout,
                retry_on_cluster_down=self.config.retry_on_cluster_down,
                skip_full_coverage_check=self.config.skip_full_coverage_check,
                readonly_mode=self.config.readonly_mode,
                decode_responses=self.config.decode_responses
            )
            
            # Test connection
            await self.cluster.ping()
            
            # Discover cluster topology
            await self._discover_cluster_topology()
            
            # Start background tasks
            await self._start_background_tasks()
            
            self.is_initialized = True
            logger.info("redis_cluster_initialized", 
                       node_count=len(self.nodes))
            
            return True
            
        except Exception as e:
            logger.error("redis_cluster_initialization_failed", error=str(e))
            return False
    
    async def _discover_cluster_topology(self):
        """Discover and map cluster topology"""
        try:
            # Get cluster nodes information
            cluster_info = await self.cluster.cluster_nodes()
            
            self.nodes.clear()
            
            for node_info in cluster_info.values():
                node = ClusterNode(
                    node_id=node_info.get('id', ''),
                    host=node_info.get('host', ''),
                    port=node_info.get('port', 6379),
                    role=ClusterNodeRole.MASTER if 'master' in node_info.get('flags', []) else ClusterNodeRole.SLAVE,
                    flags=set(node_info.get('flags', [])),
                    master_id=node_info.get('master_id'),
                    config_epoch=node_info.get('config_epoch', 0)
                )
                
                # Parse slot ranges
                if 'slots' in node_info:
                    for slot_range in node_info['slots']:
                        if isinstance(slot_range, list) and len(slot_range) == 2:
                            node.slots.append((slot_range[0], slot_range[1]))
                
                self.nodes[node.node_id] = node
            
            logger.info("cluster_topology_discovered", 
                       masters=len([n for n in self.nodes.values() if n.is_master]),
                       slaves=len([n for n in self.nodes.values() if n.is_slave]))
            
        except Exception as e:
            logger.error("cluster_topology_discovery_failed", error=str(e))
    
    async def _start_background_tasks(self):
        """Start background monitoring and maintenance tasks"""
        if self.config.health_check_interval > 0:
            self._health_check_task = asyncio.create_task(
                self._health_check_loop()
            )
        
        if self.config.enable_metrics and self.config.metrics_collection_interval > 0:
            self._metrics_task = asyncio.create_task(
                self._metrics_collection_loop()
            )
    
    async def _health_check_loop(self):
        """Continuous health checking of cluster nodes"""
        while self.is_initialized:
            try:
                await asyncio.sleep(self.config.health_check_interval)
                await self._check_cluster_health()
                
            except Exception as e:
                logger.error("health_check_loop_error", error=str(e))
    
    async def _check_cluster_health(self):
        """Check health of all cluster nodes"""
        healthy_nodes = 0
        
        for node_id, node in self.nodes.items():
            try:
                # Try to ping the specific node
                node_client = self.cluster.get_node(host=node.host, port=node.port)
                if node_client:
                    await node_client.ping()
                    
                    # Reset failure count on success
                    self._node_failures[node_id] = 0
                    healthy_nodes += 1
                    
                    # Update connection metrics
                    redis_cluster_connections.labels(
                        node=f"{node.host}:{node.port}",
                        status="healthy"
                    ).set(1)
                
            except Exception as e:
                # Increment failure count
                self._node_failures[node_id] = self._node_failures.get(node_id, 0) + 1
                
                logger.warning("cluster_node_health_check_failed",
                             node_id=node_id,
                             host=node.host,
                             port=node.port,
                             failures=self._node_failures[node_id],
                             error=str(e))
                
                # Update connection metrics
                redis_cluster_connections.labels(
                    node=f"{node.host}:{node.port}",
                    status="unhealthy"
                ).set(0)
                
                # Check if node should be marked as failed
                if self._node_failures[node_id] >= self.config.node_failure_threshold:
                    logger.error("cluster_node_marked_failed",
                               node_id=node_id,
                               failures=self._node_failures[node_id])
        
        logger.debug("cluster_health_check_completed",
                    healthy_nodes=healthy_nodes,
                    total_nodes=len(self.nodes))
    
    async def _metrics_collection_loop(self):
        """Collect and update cluster metrics"""
        while self.is_initialized:
            try:
                await asyncio.sleep(self.config.metrics_collection_interval)
                await self._collect_cluster_metrics()
                
            except Exception as e:
                logger.error("metrics_collection_loop_error", error=str(e))
    
    async def _collect_cluster_metrics(self):
        """Collect comprehensive cluster metrics"""
        try:
            # Get cluster info
            cluster_info = await self.cluster.cluster_info()
            
            # Collect per-node metrics
            for node_id, node in self.nodes.items():
                try:
                    node_client = self.cluster.get_node(host=node.host, port=node.port)
                    if not node_client:
                        continue
                    
                    # Get node info
                    info = await node_client.info()
                    
                    node_label = f"{node.host}:{node.port}"
                    
                    # Memory metrics
                    if 'used_memory' in info:
                        redis_cluster_memory_usage.labels(
                            node=node_label,
                            type="used"
                        ).set(info['used_memory'])
                    
                    if 'used_memory_rss' in info:
                        redis_cluster_memory_usage.labels(
                            node=node_label,
                            type="rss"
                        ).set(info['used_memory_rss'])
                    
                    # Keyspace metrics
                    if 'keyspace_hits' in info:
                        redis_cluster_keyspace_hits.labels(
                            node=node_label
                        ).inc(info['keyspace_hits'])
                    
                    if 'keyspace_misses' in info:
                        redis_cluster_keyspace_misses.labels(
                            node=node_label
                        ).inc(info['keyspace_misses'])
                    
                    if 'evicted_keys' in info:
                        redis_cluster_evicted_keys.labels(
                            node=node_label
                        ).inc(info['evicted_keys'])
                    
                except Exception as e:
                    logger.warning("node_metrics_collection_failed",
                                 node_id=node_id,
                                 error=str(e))
            
            self._last_metrics_collection = time.time()
            
        except Exception as e:
            logger.error("cluster_metrics_collection_failed", error=str(e))
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cluster with metrics tracking"""
        if not self.is_initialized:
            raise RuntimeError("Redis cluster not initialized")
        
        start_time = time.time()
        node_info = "unknown"
        
        try:
            # Get the value
            value = await self.cluster.get(key)
            
            # Track successful operation
            duration = time.time() - start_time
            redis_cluster_operation_duration.labels(
                operation="get",
                node=node_info
            ).observe(duration)
            
            redis_cluster_operations_total.labels(
                operation="get",
                node=node_info,
                result="success"
            ).inc()
            
            return value
            
        except Exception as e:
            # Track failed operation
            redis_cluster_operations_total.labels(
                operation="get",
                node=node_info,
                result="error"
            ).inc()
            
            logger.error("cluster_get_failed", key=key, error=str(e))
            raise
    
    async def set(
        self,
        key: str,
        value: Any,
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False
    ) -> bool:
        """Set value in cluster with metrics tracking"""
        if not self.is_initialized:
            raise RuntimeError("Redis cluster not initialized")
        
        start_time = time.time()
        node_info = "unknown"
        
        try:
            # Compress large values if enabled
            if (self.config.enable_compression and 
                isinstance(value, (str, bytes)) and 
                len(value) > self.config.compression_threshold):
                
                import gzip
                if isinstance(value, str):
                    value = value.encode('utf-8')
                value = gzip.compress(value)
                key = f"compressed:{key}"
            
            # Set the value
            result = await self.cluster.set(key, value, ex=ex, px=px, nx=nx, xx=xx)
            
            # Track successful operation
            duration = time.time() - start_time
            redis_cluster_operation_duration.labels(
                operation="set",
                node=node_info
            ).observe(duration)
            
            redis_cluster_operations_total.labels(
                operation="set",
                node=node_info,
                result="success"
            ).inc()
            
            return result
            
        except Exception as e:
            # Track failed operation
            redis_cluster_operations_total.labels(
                operation="set",
                node=node_info,
                result="error"
            ).inc()
            
            logger.error("cluster_set_failed", key=key, error=str(e))
            raise
    
    async def delete(self, *keys: str) -> int:
        """Delete keys from cluster with metrics tracking"""
        if not self.is_initialized:
            raise RuntimeError("Redis cluster not initialized")
        
        start_time = time.time()
        node_info = "unknown"
        
        try:
            # Delete the keys
            result = await self.cluster.delete(*keys)
            
            # Track successful operation
            duration = time.time() - start_time
            redis_cluster_operation_duration.labels(
                operation="delete",
                node=node_info
            ).observe(duration)
            
            redis_cluster_operations_total.labels(
                operation="delete",
                node=node_info,
                result="success"
            ).inc()
            
            return result
            
        except Exception as e:
            # Track failed operation
            redis_cluster_operations_total.labels(
                operation="delete",
                node=node_info,
                result="error"
            ).inc()
            
            logger.error("cluster_delete_failed", keys=keys, error=str(e))
            raise
    
    async def pipeline(self) -> Any:
        """Create cluster pipeline for batch operations"""
        if not self.is_initialized:
            raise RuntimeError("Redis cluster not initialized")
        
        return self.cluster.pipeline()
    
    async def invalidate_by_pattern(self, pattern: str) -> int:
        """Invalidate cache entries matching pattern"""
        if not self.is_initialized:
            raise RuntimeError("Redis cluster not initialized")
        
        try:
            deleted_count = 0
            
            # Use SCAN to find matching keys across all nodes
            for node_id, node in self.nodes.items():
                if not node.is_master:
                    continue  # Only scan master nodes
                
                try:
                    node_client = self.cluster.get_node(host=node.host, port=node.port)
                    if not node_client:
                        continue
                    
                    # Scan for matching keys on this node
                    async for key in node_client.scan_iter(match=pattern, count=100):
                        try:
                            await self.cluster.delete(key)
                            deleted_count += 1
                        except Exception as e:
                            logger.warning("failed_to_delete_key", 
                                         key=key, error=str(e))
                
                except Exception as e:
                    logger.warning("pattern_invalidation_node_failed",
                                 node_id=node_id, error=str(e))
            
            logger.info("pattern_invalidation_completed",
                       pattern=pattern,
                       deleted_count=deleted_count)
            
            return deleted_count
            
        except Exception as e:
            logger.error("pattern_invalidation_failed", 
                        pattern=pattern, error=str(e))
            return 0
    
    async def get_cluster_stats(self) -> Dict[str, Any]:
        """Get comprehensive cluster statistics"""
        if not self.is_initialized:
            return {"error": "Cluster not initialized"}
        
        try:
            stats = {
                "cluster_state": "unknown",
                "cluster_slots_assigned": 0,
                "cluster_slots_ok": 0,
                "cluster_slots_pfail": 0,
                "cluster_slots_fail": 0,
                "cluster_known_nodes": len(self.nodes),
                "cluster_size": len([n for n in self.nodes.values() if n.is_master]),
                "nodes": {},
                "total_memory_used": 0,
                "total_keys": 0,
                "last_metrics_collection": self._last_metrics_collection
            }
            
            # Get cluster info
            cluster_info = await self.cluster.cluster_info()
            stats.update(cluster_info)
            
            # Get per-node stats
            for node_id, node in self.nodes.items():
                try:
                    node_client = self.cluster.get_node(host=node.host, port=node.port)
                    if not node_client:
                        continue
                    
                    info = await node_client.info()
                    
                    node_stats = {
                        "role": node.role,
                        "host": node.host,
                        "port": node.port,
                        "slot_count": node.slot_count,
                        "memory_used": info.get('used_memory', 0),
                        "keys": sum(info.get(f'db{i}', {}).get('keys', 0) for i in range(16)),
                        "connected_clients": info.get('connected_clients', 0),
                        "keyspace_hits": info.get('keyspace_hits', 0),
                        "keyspace_misses": info.get('keyspace_misses', 0),
                        "evicted_keys": info.get('evicted_keys', 0),
                        "failures": self._node_failures.get(node_id, 0)
                    }
                    
                    stats["nodes"][node_id] = node_stats
                    stats["total_memory_used"] += node_stats["memory_used"]
                    stats["total_keys"] += node_stats["keys"]
                    
                except Exception as e:
                    logger.warning("node_stats_collection_failed",
                                 node_id=node_id, error=str(e))
            
            return stats
            
        except Exception as e:
            logger.error("cluster_stats_collection_failed", error=str(e))
            return {"error": str(e)}
    
    async def close(self):
        """Close cluster connection and cleanup"""
        logger.info("closing_redis_cluster")
        
        self.is_initialized = False
        
        # Cancel background tasks
        if self._health_check_task:
            self._health_check_task.cancel()
        if self._metrics_task:
            self._metrics_task.cancel()
        
        # Close cluster connection
        if self.cluster:
            await self.cluster.close()
        
        logger.info("redis_cluster_closed")


class CacheWarmingManager:
    """Advanced cache warming and preloading manager"""
    
    def __init__(
        self,
        cluster_manager: RedisClusterManager,
        config: Optional[CacheWarmingConfig] = None
    ):
        self.cluster = cluster_manager
        self.config = config or CacheWarmingConfig()
        self.warming_functions: Dict[str, callable] = {}
        self._warming_tasks: List[asyncio.Task] = []
        self._warming_semaphore = asyncio.Semaphore(self.config.max_concurrent_warmups)
        
    def register_warming_function(self, name: str, func: callable):
        """Register a cache warming function"""
        self.warming_functions[name] = func
        logger.info("cache_warming_function_registered", name=name)
    
    async def start_warming(self):
        """Start cache warming process"""
        if not self.config.enabled:
            logger.info("cache_warming_disabled")
            return
        
        logger.info("starting_cache_warming", delay=self.config.warmup_delay_seconds)
        
        # Wait for initial delay
        await asyncio.sleep(self.config.warmup_delay_seconds)
        
        # Start warming tasks
        if self.config.preload_critical_data:
            task = asyncio.create_task(self._preload_critical_data())
            self._warming_tasks.append(task)
        
        if self.config.background_refresh:
            task = asyncio.create_task(self._background_refresh_loop())
            self._warming_tasks.append(task)
        
        if self.config.predictive_loading:
            task = asyncio.create_task(self._predictive_loading_loop())
            self._warming_tasks.append(task)
        
        logger.info("cache_warming_started", tasks=len(self._warming_tasks))
    
    async def _preload_critical_data(self):
        """Preload critical data patterns"""
        try:
            logger.info("preloading_critical_data", 
                       patterns=self.config.critical_key_patterns)
            
            # Execute registered warming functions
            for func_name, func in self.warming_functions.items():
                try:
                    async with self._warming_semaphore:
                        if asyncio.iscoroutinefunction(func):
                            await func()
                        else:
                            func()
                    
                    logger.info("warming_function_completed", function=func_name)
                    
                except Exception as e:
                    logger.error("warming_function_failed", 
                               function=func_name, error=str(e))
            
            logger.info("critical_data_preloading_completed")
            
        except Exception as e:
            logger.error("critical_data_preloading_failed", error=str(e))
    
    async def _background_refresh_loop(self):
        """Background refresh of expiring cache entries"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Find keys that are close to expiring
                await self._refresh_expiring_keys()
                
            except Exception as e:
                logger.error("background_refresh_loop_error", error=str(e))
    
    async def _refresh_expiring_keys(self):
        """Refresh keys that are close to expiring"""
        try:
            # This would require tracking TTLs and refresh functions
            # For now, implement basic pattern-based refresh
            
            for pattern in self.config.critical_key_patterns:
                try:
                    # Find keys matching pattern with low TTL
                    # This is a simplified implementation
                    keys_to_refresh = await self._find_expiring_keys(pattern)
                    
                    for key in keys_to_refresh:
                        async with self._warming_semaphore:
                            await self._refresh_key(key)
                    
                except Exception as e:
                    logger.warning("pattern_refresh_failed", 
                                 pattern=pattern, error=str(e))
            
        except Exception as e:
            logger.error("expiring_keys_refresh_failed", error=str(e))
    
    async def _find_expiring_keys(self, pattern: str) -> List[str]:
        """Find keys matching pattern that are close to expiring"""
        expiring_keys = []
        
        try:
            # Scan for keys matching pattern
            for node_id, node in self.cluster.nodes.items():
                if not node.is_master:
                    continue
                
                node_client = self.cluster.cluster.get_node(host=node.host, port=node.port)
                if not node_client:
                    continue
                
                async for key in node_client.scan_iter(match=pattern, count=50):
                    try:
                        # Check TTL
                        ttl = await node_client.ttl(key)
                        if ttl > 0:
                            # Calculate percentage of TTL remaining
                            # This is simplified - would need original TTL
                            if ttl < 300:  # Less than 5 minutes remaining
                                expiring_keys.append(key)
                    
                    except Exception:
                        continue
        
        except Exception as e:
            logger.warning("expiring_keys_scan_failed", 
                         pattern=pattern, error=str(e))
        
        return expiring_keys
    
    async def _refresh_key(self, key: str):
        """Refresh a specific cache key"""
        try:
            # This would call the appropriate refresh function
            # For now, just log the refresh attempt
            logger.debug("refreshing_cache_key", key=key)
            
            # In a real implementation, this would:
            # 1. Identify the data source for the key
            # 2. Fetch fresh data
            # 3. Update the cache with new TTL
            
        except Exception as e:
            logger.warning("cache_key_refresh_failed", key=key, error=str(e))
    
    async def _predictive_loading_loop(self):
        """Predictive cache loading based on access patterns"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                # Analyze access patterns and predict needed data
                await self._predictive_load()
                
            except Exception as e:
                logger.error("predictive_loading_loop_error", error=str(e))
    
    async def _predictive_load(self):
        """Predictive loading based on access patterns"""
        try:
            # This would analyze access logs and patterns
            # to predict what data might be needed soon
            
            logger.debug("running_predictive_cache_loading")
            
            # Simplified implementation - would use ML or statistical analysis
            # to predict cache needs based on historical patterns
            
        except Exception as e:
            logger.error("predictive_loading_failed", error=str(e))
    
    async def stop_warming(self):
        """Stop all cache warming tasks"""
        logger.info("stopping_cache_warming")
        
        for task in self._warming_tasks:
            task.cancel()
        
        if self._warming_tasks:
            await asyncio.gather(*self._warming_tasks, return_exceptions=True)
        
        self._warming_tasks.clear()
        logger.info("cache_warming_stopped")


# Global cluster manager instance
_cluster_manager: Optional[RedisClusterManager] = None


def get_redis_cluster_manager(
    config: Optional[RedisClusterConfig] = None
) -> RedisClusterManager:
    """Get or create global Redis cluster manager"""
    global _cluster_manager
    
    if _cluster_manager is None:
        _cluster_manager = RedisClusterManager(config)
        logger.info("global_redis_cluster_manager_created")
    
    return _cluster_manager


async def initialize_redis_cluster(
    config: Optional[RedisClusterConfig] = None
) -> RedisClusterManager:
    """Initialize Redis cluster with default configuration"""
    manager = get_redis_cluster_manager(config)
    
    if await manager.initialize():
        logger.info("redis_cluster_initialized_successfully")
        return manager
    else:
        raise RuntimeError("Failed to initialize Redis cluster")