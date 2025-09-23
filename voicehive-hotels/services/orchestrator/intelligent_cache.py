"""
Intelligent Caching System for VoiceHive Hotels Orchestrator
Multi-level caching with configurable TTL policies and performance optimization
"""

import asyncio
import json
import hashlib
import pickle
from typing import Any, Optional, Dict, List, Union, Callable, TypeVar, Generic
from datetime import datetime, timezone, timedelta
from enum import Enum
import weakref
from dataclasses import dataclass, field

try:
    import redis.asyncio as aioredis
except ImportError:
    try:
        import aioredis
    except ImportError:
        aioredis = None

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

logger = get_safe_logger("orchestrator.cache")

T = TypeVar('T')

# Prometheus metrics for cache monitoring
cache_operations_total = Counter(
    'voicehive_cache_operations_total',
    'Total cache operations',
    ['cache_name', 'operation', 'result']
)

cache_hit_ratio = Gauge(
    'voicehive_cache_hit_ratio',
    'Cache hit ratio',
    ['cache_name']
)

cache_operation_duration = Histogram(
    'voicehive_cache_operation_duration_seconds',
    'Cache operation duration',
    ['cache_name', 'operation'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

cache_memory_usage = Gauge(
    'voicehive_cache_memory_usage_bytes',
    'Cache memory usage in bytes',
    ['cache_name', 'level']
)

cache_evictions_total = Counter(
    'voicehive_cache_evictions_total',
    'Total cache evictions',
    ['cache_name', 'level', 'reason']
)


class CacheLevel(str, Enum):
    """Cache levels in order of speed"""
    MEMORY = "memory"      # Fastest, limited size
    REDIS = "redis"        # Fast, shared across instances
    PERSISTENT = "persistent"  # Slowest, long-term storage


class EvictionPolicy(str, Enum):
    """Cache eviction policies"""
    LRU = "lru"           # Least Recently Used
    LFU = "lfu"           # Least Frequently Used
    TTL = "ttl"           # Time To Live based
    FIFO = "fifo"         # First In, First Out
    ADAPTIVE = "adaptive"  # Adaptive based on access patterns


class CacheStrategy(str, Enum):
    """Cache strategies"""
    WRITE_THROUGH = "write_through"    # Write to cache and storage simultaneously
    WRITE_BACK = "write_back"          # Write to cache first, storage later
    WRITE_AROUND = "write_around"      # Write to storage, bypass cache
    READ_THROUGH = "read_through"      # Read from cache, load from storage if miss
    CACHE_ASIDE = "cache_aside"        # Application manages cache explicitly


@dataclass
class CacheEntry:
    """Cache entry with metadata"""
    key: str
    value: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0
    ttl_seconds: Optional[int] = None
    size_bytes: int = 0
    tags: List[str] = field(default_factory=list)
    
    def is_expired(self) -> bool:
        """Check if entry is expired"""
        if self.ttl_seconds is None:
            return False
        
        expiry_time = self.created_at + timedelta(seconds=self.ttl_seconds)
        return datetime.now(timezone.utc) > expiry_time
    
    def touch(self):
        """Update access metadata"""
        self.accessed_at = datetime.now(timezone.utc)
        self.access_count += 1
    
    def calculate_size(self):
        """Calculate approximate size in bytes"""
        try:
            self.size_bytes = len(pickle.dumps(self.value))
        except Exception:
            # Fallback estimation
            self.size_bytes = len(str(self.value).encode('utf-8'))


class CacheConfig(BaseModel):
    """Configuration for cache behavior"""
    # Memory cache settings
    memory_max_size: int = Field(1000, description="Maximum memory cache entries")
    memory_max_bytes: int = Field(50 * 1024 * 1024, description="Maximum memory cache size in bytes")
    memory_eviction_policy: EvictionPolicy = Field(EvictionPolicy.LRU, description="Memory eviction policy")
    
    # Redis cache settings
    redis_enabled: bool = Field(True, description="Enable Redis caching")
    redis_max_bytes: int = Field(100 * 1024 * 1024, description="Maximum Redis cache size in bytes")
    redis_key_prefix: str = Field("voicehive:cache:", description="Redis key prefix")
    
    # TTL settings
    default_ttl_seconds: int = Field(300, description="Default TTL in seconds")
    max_ttl_seconds: int = Field(86400, description="Maximum TTL in seconds")
    
    # Performance settings
    cache_strategy: CacheStrategy = Field(CacheStrategy.READ_THROUGH, description="Cache strategy")
    compression_enabled: bool = Field(True, description="Enable value compression")
    serialization_format: str = Field("pickle", description="Serialization format (pickle, json)")
    
    # Monitoring settings
    enable_metrics: bool = Field(True, description="Enable Prometheus metrics")
    stats_interval_seconds: int = Field(60, description="Statistics update interval")
    
    # Cleanup settings
    cleanup_interval_seconds: int = Field(300, description="Cleanup interval for expired entries")
    cleanup_batch_size: int = Field(100, description="Cleanup batch size")


class CacheStats(BaseModel):
    """Cache statistics"""
    name: str
    level: CacheLevel
    
    # Counts
    total_entries: int = 0
    total_size_bytes: int = 0
    
    # Hit/miss statistics
    hits: int = 0
    misses: int = 0
    hit_ratio: float = 0.0
    
    # Operations
    gets: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    
    # Performance
    avg_get_time_ms: float = 0.0
    avg_set_time_ms: float = 0.0
    
    # Memory usage
    memory_usage_bytes: int = 0
    memory_usage_percent: float = 0.0
    
    # Last updated
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemoryCache:
    """In-memory cache with configurable eviction policies"""
    
    def __init__(self, name: str, config: CacheConfig):
        self.name = name
        self.config = config
        self.entries: Dict[str, CacheEntry] = {}
        self.access_order: List[str] = []  # For LRU
        self.stats = CacheStats(name=name, level=CacheLevel.MEMORY)
        self._lock = asyncio.Lock()
        
    async def get(self, key: str) -> Optional[Any]:
        """Get value from memory cache"""
        start_time = datetime.now(timezone.utc)
        
        async with self._lock:
            entry = self.entries.get(key)
            
            if entry is None:
                self.stats.misses += 1
                self.stats.gets += 1
                self._record_operation('get', 'miss', start_time)
                return None
            
            if entry.is_expired():
                # Remove expired entry
                await self._remove_entry(key)
                self.stats.misses += 1
                self.stats.gets += 1
                self._record_operation('get', 'miss', start_time)
                return None
            
            # Update access metadata
            entry.touch()
            self._update_access_order(key)
            
            self.stats.hits += 1
            self.stats.gets += 1
            self._record_operation('get', 'hit', start_time)
            
            return entry.value
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """Set value in memory cache"""
        start_time = datetime.now(timezone.utc)
        
        async with self._lock:
            # Create cache entry
            entry = CacheEntry(
                key=key,
                value=value,
                ttl_seconds=ttl_seconds or self.config.default_ttl_seconds
            )
            entry.calculate_size()
            
            # Check if we need to evict entries
            await self._ensure_capacity(entry.size_bytes)
            
            # Store entry
            self.entries[key] = entry
            self._update_access_order(key)
            
            self.stats.sets += 1
            self.stats.total_entries = len(self.entries)
            self.stats.total_size_bytes += entry.size_bytes
            
            self._record_operation('set', 'success', start_time)
            return True
    
    async def delete(self, key: str) -> bool:
        """Delete value from memory cache"""
        start_time = datetime.now(timezone.utc)
        
        async with self._lock:
            if key in self.entries:
                await self._remove_entry(key)
                self.stats.deletes += 1
                self._record_operation('delete', 'success', start_time)
                return True
            
            self._record_operation('delete', 'miss', start_time)
            return False
    
    async def clear(self):
        """Clear all entries from memory cache"""
        async with self._lock:
            self.entries.clear()
            self.access_order.clear()
            self.stats.total_entries = 0
            self.stats.total_size_bytes = 0
    
    async def cleanup_expired(self) -> int:
        """Remove expired entries"""
        removed_count = 0
        
        async with self._lock:
            expired_keys = [
                key for key, entry in self.entries.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                await self._remove_entry(key)
                removed_count += 1
        
        if removed_count > 0:
            logger.debug("memory_cache_cleanup", name=self.name, removed=removed_count)
        
        return removed_count
    
    async def _ensure_capacity(self, new_entry_size: int):
        """Ensure cache has capacity for new entry"""
        # Check entry count limit
        while len(self.entries) >= self.config.memory_max_size:
            await self._evict_entry("max_entries")
        
        # Check size limit
        while (self.stats.total_size_bytes + new_entry_size) > self.config.memory_max_bytes:
            await self._evict_entry("max_size")
    
    async def _evict_entry(self, reason: str):
        """Evict entry based on eviction policy"""
        if not self.entries:
            return
        
        key_to_evict = None
        
        if self.config.memory_eviction_policy == EvictionPolicy.LRU:
            # Least recently used
            key_to_evict = self.access_order[0] if self.access_order else None
        
        elif self.config.memory_eviction_policy == EvictionPolicy.LFU:
            # Least frequently used
            min_access_count = min(entry.access_count for entry in self.entries.values())
            for key, entry in self.entries.items():
                if entry.access_count == min_access_count:
                    key_to_evict = key
                    break
        
        elif self.config.memory_eviction_policy == EvictionPolicy.TTL:
            # Shortest TTL remaining
            now = datetime.now(timezone.utc)
            min_remaining_ttl = float('inf')
            for key, entry in self.entries.items():
                if entry.ttl_seconds:
                    remaining = entry.ttl_seconds - (now - entry.created_at).total_seconds()
                    if remaining < min_remaining_ttl:
                        min_remaining_ttl = remaining
                        key_to_evict = key
        
        elif self.config.memory_eviction_policy == EvictionPolicy.FIFO:
            # First in, first out (oldest created)
            oldest_time = min(entry.created_at for entry in self.entries.values())
            for key, entry in self.entries.items():
                if entry.created_at == oldest_time:
                    key_to_evict = key
                    break
        
        if key_to_evict:
            await self._remove_entry(key_to_evict)
            self.stats.evictions += 1
            
            cache_evictions_total.labels(
                cache_name=self.name,
                level=CacheLevel.MEMORY.value,
                reason=reason
            ).inc()
    
    async def _remove_entry(self, key: str):
        """Remove entry and update metadata"""
        if key in self.entries:
            entry = self.entries.pop(key)
            self.stats.total_size_bytes -= entry.size_bytes
            self.stats.total_entries = len(self.entries)
            
            if key in self.access_order:
                self.access_order.remove(key)
    
    def _update_access_order(self, key: str):
        """Update access order for LRU"""
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
    
    def _record_operation(self, operation: str, result: str, start_time: datetime):
        """Record operation metrics"""
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        if self.config.enable_metrics:
            cache_operations_total.labels(
                cache_name=self.name,
                operation=operation,
                result=result
            ).inc()
            
            cache_operation_duration.labels(
                cache_name=self.name,
                operation=operation
            ).observe(duration)
        
        # Update stats
        if operation == 'get':
            if result == 'hit':
                self.stats.avg_get_time_ms = (
                    (self.stats.avg_get_time_ms * (self.stats.hits - 1) + duration * 1000) / 
                    self.stats.hits if self.stats.hits > 0 else duration * 1000
                )
        elif operation == 'set':
            self.stats.avg_set_time_ms = (
                (self.stats.avg_set_time_ms * (self.stats.sets - 1) + duration * 1000) / 
                self.stats.sets if self.stats.sets > 0 else duration * 1000
            )
        
        # Update hit ratio
        total_gets = self.stats.hits + self.stats.misses
        self.stats.hit_ratio = self.stats.hits / total_gets if total_gets > 0 else 0.0
        
        if self.config.enable_metrics:
            cache_hit_ratio.labels(cache_name=self.name).set(self.stats.hit_ratio)
    
    def get_stats(self) -> CacheStats:
        """Get current cache statistics"""
        self.stats.memory_usage_bytes = self.stats.total_size_bytes
        self.stats.memory_usage_percent = (
            (self.stats.total_size_bytes / self.config.memory_max_bytes) * 100
            if self.config.memory_max_bytes > 0 else 0.0
        )
        self.stats.last_updated = datetime.now(timezone.utc)
        
        return self.stats


class RedisCache:
    """Redis-based distributed cache"""
    
    def __init__(self, name: str, config: CacheConfig, redis_client):
        self.name = name
        self.config = config
        self.redis = redis_client
        self.stats = CacheStats(name=name, level=CacheLevel.REDIS)
        
    def _make_key(self, key: str) -> str:
        """Create Redis key with prefix"""
        return f"{self.config.redis_key_prefix}{self.name}:{key}"
    
    def _make_meta_key(self, key: str) -> str:
        """Create Redis metadata key"""
        return f"{self.config.redis_key_prefix}{self.name}:meta:{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from Redis cache"""
        if not self.config.redis_enabled:
            return None
        
        start_time = datetime.now(timezone.utc)
        
        try:
            redis_key = self._make_key(key)
            meta_key = self._make_meta_key(key)
            
            # Get value and metadata
            pipe = self.redis.pipeline()
            pipe.get(redis_key)
            pipe.hgetall(meta_key)
            results = await pipe.execute()
            
            value_data = results[0]
            meta_data = results[1]
            
            if value_data is None:
                self.stats.misses += 1
                self.stats.gets += 1
                self._record_operation('get', 'miss', start_time)
                return None
            
            # Check TTL
            if meta_data:
                created_at_str = meta_data.get(b'created_at', b'').decode('utf-8')
                ttl_str = meta_data.get(b'ttl_seconds', b'').decode('utf-8')
                
                if created_at_str and ttl_str:
                    created_at = datetime.fromisoformat(created_at_str)
                    ttl_seconds = int(ttl_str)
                    
                    if ttl_seconds > 0:
                        expiry_time = created_at + timedelta(seconds=ttl_seconds)
                        if datetime.now(timezone.utc) > expiry_time:
                            # Expired, remove it
                            await self.delete(key)
                            self.stats.misses += 1
                            self.stats.gets += 1
                            self._record_operation('get', 'miss', start_time)
                            return None
            
            # Deserialize value
            value = self._deserialize(value_data)
            
            # Update access metadata
            await self.redis.hset(
                meta_key,
                mapping={
                    'accessed_at': datetime.now(timezone.utc).isoformat(),
                    'access_count': int(meta_data.get(b'access_count', b'0')) + 1
                }
            )
            
            self.stats.hits += 1
            self.stats.gets += 1
            self._record_operation('get', 'hit', start_time)
            
            return value
            
        except Exception as e:
            logger.error("redis_cache_get_error", name=self.name, key=key, error=str(e))
            self.stats.misses += 1
            self.stats.gets += 1
            self._record_operation('get', 'error', start_time)
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """Set value in Redis cache"""
        if not self.config.redis_enabled:
            return False
        
        start_time = datetime.now(timezone.utc)
        
        try:
            redis_key = self._make_key(key)
            meta_key = self._make_meta_key(key)
            
            # Serialize value
            serialized_value = self._serialize(value)
            
            # Calculate TTL
            ttl = ttl_seconds or self.config.default_ttl_seconds
            
            # Store value and metadata
            pipe = self.redis.pipeline()
            
            if ttl > 0:
                pipe.setex(redis_key, ttl, serialized_value)
                pipe.expire(meta_key, ttl)
            else:
                pipe.set(redis_key, serialized_value)
            
            pipe.hset(
                meta_key,
                mapping={
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'accessed_at': datetime.now(timezone.utc).isoformat(),
                    'ttl_seconds': str(ttl),
                    'access_count': '1',
                    'size_bytes': str(len(serialized_value))
                }
            )
            
            await pipe.execute()
            
            self.stats.sets += 1
            self.stats.total_entries += 1
            self.stats.total_size_bytes += len(serialized_value)
            
            self._record_operation('set', 'success', start_time)
            return True
            
        except Exception as e:
            logger.error("redis_cache_set_error", name=self.name, key=key, error=str(e))
            self._record_operation('set', 'error', start_time)
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from Redis cache"""
        if not self.config.redis_enabled:
            return False
        
        start_time = datetime.now(timezone.utc)
        
        try:
            redis_key = self._make_key(key)
            meta_key = self._make_meta_key(key)
            
            # Delete both value and metadata
            pipe = self.redis.pipeline()
            pipe.delete(redis_key)
            pipe.delete(meta_key)
            results = await pipe.execute()
            
            deleted = results[0] > 0
            
            if deleted:
                self.stats.deletes += 1
                self.stats.total_entries = max(0, self.stats.total_entries - 1)
            
            self._record_operation('delete', 'success' if deleted else 'miss', start_time)
            return deleted
            
        except Exception as e:
            logger.error("redis_cache_delete_error", name=self.name, key=key, error=str(e))
            self._record_operation('delete', 'error', start_time)
            return False
    
    async def clear(self):
        """Clear all entries from Redis cache"""
        if not self.config.redis_enabled:
            return
        
        try:
            pattern = f"{self.config.redis_key_prefix}{self.name}:*"
            
            # Use scan to find all keys
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                await self.redis.delete(*keys)
            
            self.stats.total_entries = 0
            self.stats.total_size_bytes = 0
            
        except Exception as e:
            logger.error("redis_cache_clear_error", name=self.name, error=str(e))
    
    def _serialize(self, value: Any) -> bytes:
        """Serialize value for Redis storage"""
        if self.config.serialization_format == "json":
            return json.dumps(value, default=str).encode('utf-8')
        else:  # pickle
            return pickle.dumps(value)
    
    def _deserialize(self, data: bytes) -> Any:
        """Deserialize value from Redis storage"""
        if self.config.serialization_format == "json":
            return json.loads(data.decode('utf-8'))
        else:  # pickle
            return pickle.loads(data)
    
    def _record_operation(self, operation: str, result: str, start_time: datetime):
        """Record operation metrics"""
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        if self.config.enable_metrics:
            cache_operations_total.labels(
                cache_name=self.name,
                operation=operation,
                result=result
            ).inc()
            
            cache_operation_duration.labels(
                cache_name=self.name,
                operation=operation
            ).observe(duration)
        
        # Update hit ratio
        total_gets = self.stats.hits + self.stats.misses
        self.stats.hit_ratio = self.stats.hits / total_gets if total_gets > 0 else 0.0
        
        if self.config.enable_metrics:
            cache_hit_ratio.labels(cache_name=self.name).set(self.stats.hit_ratio)
    
    def get_stats(self) -> CacheStats:
        """Get current cache statistics"""
        self.stats.last_updated = datetime.now(timezone.utc)
        return self.stats


class IntelligentCache(Generic[T]):
    """Multi-level intelligent cache with automatic optimization"""
    
    def __init__(
        self,
        name: str,
        config: Optional[CacheConfig] = None,
        redis_client: Optional[Any] = None
    ):
        self.name = name
        self.config = config or CacheConfig()
        
        # Initialize cache levels
        self.memory_cache = MemoryCache(name, self.config)
        self.redis_cache = RedisCache(name, self.config, redis_client) if redis_client else None
        
        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None
        
        # Cache warming
        self._warm_cache_functions: Dict[str, Callable] = {}
        
        logger.info("intelligent_cache_initialized", name=name)
    
    async def initialize(self):
        """Initialize cache and start background tasks"""
        # Start cleanup task
        if self.config.cleanup_interval_seconds > 0:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        # Start stats task
        if self.config.stats_interval_seconds > 0:
            self._stats_task = asyncio.create_task(self._stats_loop())
        
        logger.info("intelligent_cache_started", name=self.name)
    
    async def get(self, key: str) -> Optional[T]:
        """Get value from cache (multi-level lookup)"""
        # Try memory cache first
        value = await self.memory_cache.get(key)
        if value is not None:
            return value
        
        # Try Redis cache
        if self.redis_cache:
            value = await self.redis_cache.get(key)
            if value is not None:
                # Promote to memory cache
                await self.memory_cache.set(key, value)
                return value
        
        return None
    
    async def set(
        self,
        key: str,
        value: T,
        ttl_seconds: Optional[int] = None,
        levels: Optional[List[CacheLevel]] = None
    ) -> bool:
        """Set value in cache (multi-level storage)"""
        levels = levels or [CacheLevel.MEMORY, CacheLevel.REDIS]
        success = True
        
        # Store in memory cache
        if CacheLevel.MEMORY in levels:
            memory_success = await self.memory_cache.set(key, value, ttl_seconds)
            success = success and memory_success
        
        # Store in Redis cache
        if CacheLevel.REDIS in levels and self.redis_cache:
            redis_success = await self.redis_cache.set(key, value, ttl_seconds)
            success = success and redis_success
        
        return success
    
    async def delete(self, key: str) -> bool:
        """Delete value from all cache levels"""
        memory_deleted = await self.memory_cache.delete(key)
        redis_deleted = await self.redis_cache.delete(key) if self.redis_cache else False
        
        return memory_deleted or redis_deleted
    
    async def clear(self):
        """Clear all cache levels"""
        await self.memory_cache.clear()
        if self.redis_cache:
            await self.redis_cache.clear()
    
    async def get_or_set(
        self,
        key: str,
        factory_func: Callable[[], T],
        ttl_seconds: Optional[int] = None
    ) -> T:
        """Get value from cache or compute and store it"""
        # Try to get from cache first
        value = await self.get(key)
        if value is not None:
            return value
        
        # Compute value
        if asyncio.iscoroutinefunction(factory_func):
            value = await factory_func()
        else:
            value = factory_func()
        
        # Store in cache
        await self.set(key, value, ttl_seconds)
        
        return value
    
    async def invalidate_by_tags(self, tags: List[str]):
        """Invalidate cache entries by tags (memory cache only for now)"""
        keys_to_delete = []
        
        for key, entry in self.memory_cache.entries.items():
            if any(tag in entry.tags for tag in tags):
                keys_to_delete.append(key)
        
        for key in keys_to_delete:
            await self.delete(key)
        
        logger.info("cache_invalidated_by_tags", name=self.name, tags=tags, count=len(keys_to_delete))
    
    def register_warm_function(self, key_pattern: str, func: Callable):
        """Register function to warm cache for specific key patterns"""
        self._warm_cache_functions[key_pattern] = func
    
    async def warm_cache(self, key_patterns: Optional[List[str]] = None):
        """Warm cache using registered functions"""
        patterns = key_patterns or list(self._warm_cache_functions.keys())
        
        for pattern in patterns:
            if pattern in self._warm_cache_functions:
                try:
                    func = self._warm_cache_functions[pattern]
                    if asyncio.iscoroutinefunction(func):
                        await func()
                    else:
                        func()
                    
                    logger.info("cache_warmed", name=self.name, pattern=pattern)
                    
                except Exception as e:
                    logger.error("cache_warm_error", name=self.name, pattern=pattern, error=str(e))
    
    async def get_stats(self) -> Dict[str, CacheStats]:
        """Get statistics for all cache levels"""
        stats = {
            'memory': self.memory_cache.get_stats()
        }
        
        if self.redis_cache:
            stats['redis'] = self.redis_cache.get_stats()
        
        return stats
    
    async def health_check(self) -> Dict[str, bool]:
        """Health check for all cache levels"""
        results = {
            'memory': True  # Memory cache is always healthy if initialized
        }
        
        if self.redis_cache:
            try:
                await self.redis_cache.redis.ping()
                results['redis'] = True
            except Exception:
                results['redis'] = False
        
        return results
    
    async def _cleanup_loop(self):
        """Background cleanup of expired entries"""
        while True:
            try:
                await asyncio.sleep(self.config.cleanup_interval_seconds)
                
                # Clean up memory cache
                removed_count = await self.memory_cache.cleanup_expired()
                
                if removed_count > 0:
                    logger.debug("cache_cleanup_completed", name=self.name, removed=removed_count)
                
            except Exception as e:
                logger.error("cache_cleanup_error", name=self.name, error=str(e))
    
    async def _stats_loop(self):
        """Background statistics update"""
        while True:
            try:
                await asyncio.sleep(self.config.stats_interval_seconds)
                
                # Update Prometheus metrics
                if self.config.enable_metrics:
                    stats = await self.get_stats()
                    
                    for level, level_stats in stats.items():
                        cache_memory_usage.labels(
                            cache_name=self.name,
                            level=level
                        ).set(level_stats.memory_usage_bytes)
                
            except Exception as e:
                logger.error("cache_stats_error", name=self.name, error=str(e))
    
    async def close(self):
        """Close cache and cleanup resources"""
        # Cancel background tasks
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._stats_task:
            self._stats_task.cancel()
        
        # Clear caches
        await self.clear()
        
        logger.info("intelligent_cache_closed", name=self.name)


class CacheManager:
    """Manager for multiple intelligent caches"""
    
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self.redis_client = redis_client
        self.caches: Dict[str, IntelligentCache] = {}
        
    def create_cache(
        self,
        name: str,
        config: Optional[CacheConfig] = None
    ) -> IntelligentCache:
        """Create a new intelligent cache"""
        if name in self.caches:
            logger.warning("cache_already_exists", name=name)
            return self.caches[name]
        
        cache = IntelligentCache(name, config, self.redis_client)
        self.caches[name] = cache
        
        logger.info("cache_created", name=name)
        return cache
    
    def get_cache(self, name: str) -> Optional[IntelligentCache]:
        """Get existing cache by name"""
        return self.caches.get(name)
    
    async def initialize_all(self):
        """Initialize all caches"""
        for cache in self.caches.values():
            await cache.initialize()
    
    async def get_all_stats(self) -> Dict[str, Dict[str, CacheStats]]:
        """Get statistics for all caches"""
        all_stats = {}
        
        for name, cache in self.caches.items():
            all_stats[name] = await cache.get_stats()
        
        return all_stats
    
    async def health_check_all(self) -> Dict[str, Dict[str, bool]]:
        """Health check all caches"""
        results = {}
        
        for name, cache in self.caches.items():
            results[name] = await cache.health_check()
        
        return results
    
    async def close_all(self):
        """Close all caches"""
        for cache in self.caches.values():
            await cache.close()
        
        self.caches.clear()
        logger.info("all_caches_closed")


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager(redis_client: Optional[aioredis.Redis] = None) -> CacheManager:
    """Get or create global cache manager"""
    global _cache_manager
    
    if _cache_manager is None:
        _cache_manager = CacheManager(redis_client)
        logger.info("global_cache_manager_created")
    
    return _cache_manager


# Convenience functions for common cache operations
async def cached(
    cache_name: str,
    key: str,
    factory_func: Callable[[], T],
    ttl_seconds: Optional[int] = None,
    redis_client: Optional[aioredis.Redis] = None
) -> T:
    """Decorator-like function for caching"""
    manager = get_cache_manager(redis_client)
    cache = manager.get_cache(cache_name)
    
    if cache is None:
        cache = manager.create_cache(cache_name)
        await cache.initialize()
    
    return await cache.get_or_set(key, factory_func, ttl_seconds)


def cache_key(*args, **kwargs) -> str:
    """Generate cache key from arguments"""
    key_parts = []
    
    # Add positional arguments
    for arg in args:
        key_parts.append(str(arg))
    
    # Add keyword arguments (sorted for consistency)
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={v}")
    
    # Create hash for long keys
    key_str = ":".join(key_parts)
    if len(key_str) > 200:  # Redis key length limit consideration
        key_hash = hashlib.md5(key_str.encode()).hexdigest()
        return f"hash:{key_hash}"
    
    return key_str