"""
Tenant-Aware Caching Service for VoiceHive Hotels
Provides tenant-specific caching strategies with isolation and quota enforcement.
"""

import asyncio
import hashlib
import json
import time
import zlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from enum import Enum

import redis.asyncio as redis
from pydantic import BaseModel

from services.orchestrator.tenant_management import TenantManager, TenantMetadata
from services.orchestrator.logging_adapter import get_safe_logger

logger = get_safe_logger(__name__)


class CacheStrategy(str, Enum):
    """Cache strategies for different tenant tiers"""
    BASIC = "basic"           # Simple key-value caching
    ADVANCED = "advanced"     # LRU eviction, compression
    PREMIUM = "premium"       # Multi-level caching, predictive caching
    CUSTOM = "custom"         # Custom tenant-specific strategy


class CacheNamespace(str, Enum):
    """Cache namespaces for different data types"""
    USER_SESSIONS = "sessions"
    PMS_DATA = "pms_data"
    AI_RESPONSES = "ai_responses"
    CALL_CONTEXT = "call_context"
    HOTEL_CONFIG = "hotel_config"
    RATE_LIMITS = "rate_limits"
    ANALYTICS = "analytics"
    WEBHOOKS = "webhooks"
    TRANSLATIONS = "translations"
    TEMPORARY = "temp"


class CacheEntry(BaseModel):
    """Cache entry with metadata"""
    key: str
    value: Any
    tenant_id: str
    namespace: CacheNamespace
    created_at: datetime
    expires_at: Optional[datetime] = None
    access_count: int = 0
    last_accessed: datetime
    size_bytes: int = 0
    compressed: bool = False
    tags: List[str] = []


class TenantCacheConfig(BaseModel):
    """Tenant-specific cache configuration"""
    tenant_id: str
    strategy: CacheStrategy = CacheStrategy.BASIC

    # Storage quotas
    max_memory_mb: int = 100
    max_entries: int = 10000
    max_entry_size_kb: int = 1024

    # TTL settings
    default_ttl_seconds: int = 3600
    max_ttl_seconds: int = 86400

    # Performance settings
    compression_enabled: bool = False
    compression_threshold_bytes: int = 1024
    prefetch_enabled: bool = False
    write_through_enabled: bool = False

    # Eviction policy
    eviction_policy: str = "lru"  # lru, lfu, ttl, random
    eviction_batch_size: int = 100

    # Monitoring
    metrics_enabled: bool = True
    alert_on_quota_usage: float = 0.8  # Alert at 80% usage


class TenantCacheMetrics(BaseModel):
    """Cache metrics for a tenant"""
    tenant_id: str
    period_start: datetime
    period_end: datetime

    # Usage statistics
    total_entries: int = 0
    memory_used_mb: float = 0.0
    memory_quota_mb: int = 0

    # Performance metrics
    hit_count: int = 0
    miss_count: int = 0
    eviction_count: int = 0
    compression_savings_mb: float = 0.0

    # Access patterns
    most_accessed_keys: List[str] = []
    cache_hit_rate: float = 0.0
    average_entry_size_kb: float = 0.0

    @property
    def quota_usage_percentage(self) -> float:
        """Calculate quota usage percentage"""
        if self.memory_quota_mb == 0:
            return 0.0
        return (self.memory_used_mb / self.memory_quota_mb) * 100


class TenantCacheService:
    """Tenant-aware caching service with isolation and quotas"""

    def __init__(
        self,
        redis_client: redis.Redis,
        tenant_manager: TenantManager,
        global_prefix: str = "voicehive_cache"
    ):
        self.redis = redis_client
        self.tenant_manager = tenant_manager
        self.global_prefix = global_prefix

        # Cache configurations per tenant
        self.tenant_configs: Dict[str, TenantCacheConfig] = {}

        # Metrics tracking
        self.metrics: Dict[str, TenantCacheMetrics] = {}

        # Performance optimization
        self.local_cache: Dict[str, Tuple[Any, float]] = {}  # Simple in-memory cache
        self.local_cache_ttl = 60  # 1 minute local cache

    # Core Cache Operations

    async def get(
        self,
        tenant_id: str,
        key: str,
        namespace: CacheNamespace = CacheNamespace.TEMPORARY,
        use_local_cache: bool = True
    ) -> Optional[Any]:
        """Get value from tenant cache"""
        cache_key = self._build_cache_key(tenant_id, namespace, key)

        # Check local cache first (for frequently accessed data)
        if use_local_cache and cache_key in self.local_cache:
            value, expire_time = self.local_cache[cache_key]
            if time.time() < expire_time:
                await self._track_cache_hit(tenant_id, namespace)
                return value
            else:
                # Remove expired entry
                del self.local_cache[cache_key]

        # Check Redis cache
        try:
            cached_data = await self.redis.get(cache_key)
            if cached_data is None:
                await self._track_cache_miss(tenant_id, namespace)
                return None

            # Deserialize and decompress if needed
            entry_data = json.loads(cached_data)
            entry = CacheEntry(**entry_data)

            # Check expiration
            if entry.expires_at and datetime.now(timezone.utc) > entry.expires_at:
                await self.delete(tenant_id, key, namespace)
                await self._track_cache_miss(tenant_id, namespace)
                return None

            # Update access tracking
            await self._update_access_tracking(cache_key, entry)

            # Decompress if needed
            value = entry.value
            if entry.compressed and isinstance(value, str):
                value = self._decompress_value(value)

            # Store in local cache
            if use_local_cache:
                self.local_cache[cache_key] = (value, time.time() + self.local_cache_ttl)

            await self._track_cache_hit(tenant_id, namespace)
            return value

        except Exception as e:
            logger.error("cache_get_error", tenant_id=tenant_id, key=key, error=str(e))
            await self._track_cache_miss(tenant_id, namespace)
            return None

    async def set(
        self,
        tenant_id: str,
        key: str,
        value: Any,
        namespace: CacheNamespace = CacheNamespace.TEMPORARY,
        ttl_seconds: Optional[int] = None,
        tags: Optional[List[str]] = None
    ) -> bool:
        """Set value in tenant cache"""
        try:
            # Get tenant cache configuration
            config = await self._get_tenant_cache_config(tenant_id)

            # Check tenant quota
            if not await self._check_quota(tenant_id, config):
                logger.warning("cache_quota_exceeded", tenant_id=tenant_id)
                return False

            # Determine TTL
            if ttl_seconds is None:
                ttl_seconds = config.default_ttl_seconds
            ttl_seconds = min(ttl_seconds, config.max_ttl_seconds)

            # Serialize value
            serialized_value = self._serialize_value(value)
            size_bytes = len(str(serialized_value).encode('utf-8'))

            # Check entry size limit
            if size_bytes > config.max_entry_size_kb * 1024:
                logger.warning("cache_entry_too_large", tenant_id=tenant_id, size_bytes=size_bytes)
                return False

            # Compress if needed
            compressed = False
            if (config.compression_enabled and
                size_bytes > config.compression_threshold_bytes):
                serialized_value = self._compress_value(serialized_value)
                compressed = True

            # Create cache entry
            now = datetime.now(timezone.utc)
            entry = CacheEntry(
                key=key,
                value=serialized_value,
                tenant_id=tenant_id,
                namespace=namespace,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                last_accessed=now,
                size_bytes=size_bytes,
                compressed=compressed,
                tags=tags or []
            )

            # Store in Redis
            cache_key = self._build_cache_key(tenant_id, namespace, key)
            await self.redis.setex(
                cache_key,
                ttl_seconds,
                entry.model_dump_json()
            )

            # Update tenant usage tracking
            await self._update_tenant_usage(tenant_id, namespace, size_bytes, "add")

            # Check for eviction if needed
            await self._check_and_evict(tenant_id, config)

            logger.debug("cache_set_success", tenant_id=tenant_id, key=key, size_bytes=size_bytes)
            return True

        except Exception as e:
            logger.error("cache_set_error", tenant_id=tenant_id, key=key, error=str(e))
            return False

    async def delete(
        self,
        tenant_id: str,
        key: str,
        namespace: CacheNamespace = CacheNamespace.TEMPORARY
    ) -> bool:
        """Delete value from tenant cache"""
        try:
            cache_key = self._build_cache_key(tenant_id, namespace, key)

            # Get entry info for usage tracking
            cached_data = await self.redis.get(cache_key)
            if cached_data:
                entry_data = json.loads(cached_data)
                entry = CacheEntry(**entry_data)
                size_bytes = entry.size_bytes
            else:
                size_bytes = 0

            # Delete from Redis
            deleted = await self.redis.delete(cache_key)

            # Remove from local cache
            if cache_key in self.local_cache:
                del self.local_cache[cache_key]

            # Update tenant usage tracking
            if deleted and size_bytes > 0:
                await self._update_tenant_usage(tenant_id, namespace, size_bytes, "remove")

            return bool(deleted)

        except Exception as e:
            logger.error("cache_delete_error", tenant_id=tenant_id, key=key, error=str(e))
            return False

    async def exists(
        self,
        tenant_id: str,
        key: str,
        namespace: CacheNamespace = CacheNamespace.TEMPORARY
    ) -> bool:
        """Check if key exists in tenant cache"""
        cache_key = self._build_cache_key(tenant_id, namespace, key)
        return bool(await self.redis.exists(cache_key))

    async def expire(
        self,
        tenant_id: str,
        key: str,
        namespace: CacheNamespace = CacheNamespace.TEMPORARY,
        ttl_seconds: int = 3600
    ) -> bool:
        """Set expiration for cache key"""
        cache_key = self._build_cache_key(tenant_id, namespace, key)
        return bool(await self.redis.expire(cache_key, ttl_seconds))

    # Batch Operations

    async def mget(
        self,
        tenant_id: str,
        keys: List[str],
        namespace: CacheNamespace = CacheNamespace.TEMPORARY
    ) -> Dict[str, Any]:
        """Get multiple values from tenant cache"""
        result = {}
        cache_keys = [self._build_cache_key(tenant_id, namespace, key) for key in keys]

        try:
            cached_values = await self.redis.mget(cache_keys)

            for i, cached_data in enumerate(cached_values):
                original_key = keys[i]
                if cached_data:
                    try:
                        entry_data = json.loads(cached_data)
                        entry = CacheEntry(**entry_data)

                        # Check expiration
                        if entry.expires_at and datetime.now(timezone.utc) > entry.expires_at:
                            await self.delete(tenant_id, original_key, namespace)
                            continue

                        # Decompress if needed
                        value = entry.value
                        if entry.compressed and isinstance(value, str):
                            value = self._decompress_value(value)

                        result[original_key] = value
                        await self._track_cache_hit(tenant_id, namespace)

                    except Exception as e:
                        logger.error("cache_mget_entry_error", key=original_key, error=str(e))
                        await self._track_cache_miss(tenant_id, namespace)
                else:
                    await self._track_cache_miss(tenant_id, namespace)

        except Exception as e:
            logger.error("cache_mget_error", tenant_id=tenant_id, error=str(e))

        return result

    async def mset(
        self,
        tenant_id: str,
        key_value_pairs: Dict[str, Any],
        namespace: CacheNamespace = CacheNamespace.TEMPORARY,
        ttl_seconds: Optional[int] = None
    ) -> int:
        """Set multiple values in tenant cache"""
        success_count = 0

        for key, value in key_value_pairs.items():
            if await self.set(tenant_id, key, value, namespace, ttl_seconds):
                success_count += 1

        return success_count

    # Advanced Operations

    async def get_by_tags(
        self,
        tenant_id: str,
        tags: List[str],
        namespace: CacheNamespace = CacheNamespace.TEMPORARY
    ) -> Dict[str, Any]:
        """Get all cache entries matching tags"""
        result = {}
        pattern = self._build_cache_key(tenant_id, namespace, "*")

        try:
            async for cache_key in self.redis.scan_iter(match=pattern):
                cached_data = await self.redis.get(cache_key)
                if cached_data:
                    try:
                        entry_data = json.loads(cached_data)
                        entry = CacheEntry(**entry_data)

                        # Check if any of the requested tags match
                        if any(tag in entry.tags for tag in tags):
                            # Decompress if needed
                            value = entry.value
                            if entry.compressed and isinstance(value, str):
                                value = self._decompress_value(value)

                            result[entry.key] = value

                    except Exception as e:
                        logger.error("cache_get_by_tags_entry_error", cache_key=cache_key, error=str(e))

        except Exception as e:
            logger.error("cache_get_by_tags_error", tenant_id=tenant_id, error=str(e))

        return result

    async def invalidate_by_tags(
        self,
        tenant_id: str,
        tags: List[str],
        namespace: CacheNamespace = CacheNamespace.TEMPORARY
    ) -> int:
        """Invalidate all cache entries matching tags"""
        deleted_count = 0
        pattern = self._build_cache_key(tenant_id, namespace, "*")

        try:
            keys_to_delete = []

            async for cache_key in self.redis.scan_iter(match=pattern):
                cached_data = await self.redis.get(cache_key)
                if cached_data:
                    try:
                        entry_data = json.loads(cached_data)
                        entry = CacheEntry(**entry_data)

                        # Check if any of the tags match
                        if any(tag in entry.tags for tag in tags):
                            keys_to_delete.append(cache_key)

                    except Exception as e:
                        logger.error("cache_invalidate_entry_error", cache_key=cache_key, error=str(e))

            # Delete in batches
            if keys_to_delete:
                for i in range(0, len(keys_to_delete), 100):
                    batch = keys_to_delete[i:i+100]
                    deleted_count += await self.redis.delete(*batch)

        except Exception as e:
            logger.error("cache_invalidate_by_tags_error", tenant_id=tenant_id, error=str(e))

        return deleted_count

    # Tenant Management

    async def configure_tenant_cache(
        self,
        tenant_id: str,
        config: TenantCacheConfig
    ) -> bool:
        """Configure cache settings for a tenant"""
        try:
            self.tenant_configs[tenant_id] = config

            # Store configuration in Redis for persistence
            config_key = f"{self.global_prefix}:config:{tenant_id}"
            await self.redis.setex(
                config_key,
                86400,  # 24 hour TTL
                config.model_dump_json()
            )

            logger.info("tenant_cache_configured", tenant_id=tenant_id, strategy=config.strategy.value)
            return True

        except Exception as e:
            logger.error("tenant_cache_config_error", tenant_id=tenant_id, error=str(e))
            return False

    async def clear_tenant_cache(
        self,
        tenant_id: str,
        namespace: Optional[CacheNamespace] = None
    ) -> int:
        """Clear all cache entries for a tenant"""
        try:
            if namespace:
                pattern = self._build_cache_key(tenant_id, namespace, "*")
            else:
                pattern = f"{self.global_prefix}:tenant:{tenant_id}:*"

            keys_to_delete = []
            async for key in self.redis.scan_iter(match=pattern):
                keys_to_delete.append(key)

            # Delete in batches
            deleted_count = 0
            if keys_to_delete:
                for i in range(0, len(keys_to_delete), 100):
                    batch = keys_to_delete[i:i+100]
                    deleted_count += await self.redis.delete(*batch)

            # Clear from local cache
            local_keys_to_remove = [key for key in self.local_cache.keys() if key.startswith(pattern.replace("*", ""))]
            for key in local_keys_to_remove:
                del self.local_cache[key]

            logger.info("tenant_cache_cleared", tenant_id=tenant_id, deleted_count=deleted_count)
            return deleted_count

        except Exception as e:
            logger.error("tenant_cache_clear_error", tenant_id=tenant_id, error=str(e))
            return 0

    async def get_tenant_cache_metrics(self, tenant_id: str) -> TenantCacheMetrics:
        """Get cache metrics for a tenant"""
        if tenant_id in self.metrics:
            return self.metrics[tenant_id]

        # Calculate metrics from Redis
        metrics = TenantCacheMetrics(
            tenant_id=tenant_id,
            period_start=datetime.now(timezone.utc) - timedelta(hours=1),
            period_end=datetime.now(timezone.utc)
        )

        try:
            pattern = f"{self.global_prefix}:tenant:{tenant_id}:*"
            total_entries = 0
            total_size = 0
            access_counts = {}

            async for cache_key in self.redis.scan_iter(match=pattern):
                cached_data = await self.redis.get(cache_key)
                if cached_data:
                    try:
                        entry_data = json.loads(cached_data)
                        entry = CacheEntry(**entry_data)

                        total_entries += 1
                        total_size += entry.size_bytes
                        access_counts[entry.key] = entry.access_count

                    except Exception:
                        continue

            metrics.total_entries = total_entries
            metrics.memory_used_mb = total_size / (1024 * 1024)

            # Get tenant configuration for quota
            config = await self._get_tenant_cache_config(tenant_id)
            metrics.memory_quota_mb = config.max_memory_mb

            # Most accessed keys
            sorted_access = sorted(access_counts.items(), key=lambda x: x[1], reverse=True)
            metrics.most_accessed_keys = [key for key, _ in sorted_access[:10]]

            # Average entry size
            if total_entries > 0:
                metrics.average_entry_size_kb = (total_size / total_entries) / 1024

            self.metrics[tenant_id] = metrics

        except Exception as e:
            logger.error("cache_metrics_error", tenant_id=tenant_id, error=str(e))

        return metrics

    # Utility Methods

    def _build_cache_key(self, tenant_id: str, namespace: CacheNamespace, key: str) -> str:
        """Build cache key with tenant isolation"""
        # Use SHA256 hash for long keys to avoid Redis key length limits
        if len(key) > 200:
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            return f"{self.global_prefix}:tenant:{tenant_id}:{namespace.value}:{key_hash}"
        else:
            return f"{self.global_prefix}:tenant:{tenant_id}:{namespace.value}:{key}"

    async def _get_tenant_cache_config(self, tenant_id: str) -> TenantCacheConfig:
        """Get cache configuration for tenant"""
        # Check memory cache first
        if tenant_id in self.tenant_configs:
            return self.tenant_configs[tenant_id]

        # Check Redis
        config_key = f"{self.global_prefix}:config:{tenant_id}"
        cached_config = await self.redis.get(config_key)

        if cached_config:
            config = TenantCacheConfig.model_validate_json(cached_config)
            self.tenant_configs[tenant_id] = config
            return config

        # Get tenant metadata to determine default configuration
        tenant = await self.tenant_manager.get_tenant(tenant_id)
        if tenant:
            config = self._get_default_cache_config(tenant)
            self.tenant_configs[tenant_id] = config
            return config

        # Final fallback
        return TenantCacheConfig(tenant_id=tenant_id)

    def _get_default_cache_config(self, tenant: TenantMetadata) -> TenantCacheConfig:
        """Get default cache configuration based on tenant tier"""
        configs = {
            "starter": TenantCacheConfig(
                tenant_id=tenant.tenant_id,
                strategy=CacheStrategy.BASIC,
                max_memory_mb=50,
                max_entries=5000,
                compression_enabled=False
            ),
            "professional": TenantCacheConfig(
                tenant_id=tenant.tenant_id,
                strategy=CacheStrategy.ADVANCED,
                max_memory_mb=200,
                max_entries=20000,
                compression_enabled=True
            ),
            "enterprise": TenantCacheConfig(
                tenant_id=tenant.tenant_id,
                strategy=CacheStrategy.PREMIUM,
                max_memory_mb=1000,
                max_entries=100000,
                compression_enabled=True,
                prefetch_enabled=True
            ),
            "custom": TenantCacheConfig(
                tenant_id=tenant.tenant_id,
                strategy=CacheStrategy.CUSTOM,
                max_memory_mb=500,
                max_entries=50000,
                compression_enabled=True
            )
        }

        return configs.get(tenant.tenant_tier.value, configs["starter"])

    def _serialize_value(self, value: Any) -> Any:
        """Serialize value for storage"""
        if isinstance(value, (dict, list, tuple)):
            return value  # JSON serializable
        elif isinstance(value, (str, int, float, bool)):
            return value
        else:
            # Convert to JSON string for complex objects
            return json.dumps(value, default=str)

    def _compress_value(self, value: Any) -> str:
        """Compress value using zlib"""
        json_str = json.dumps(value) if not isinstance(value, str) else value
        compressed = zlib.compress(json_str.encode('utf-8'))
        return compressed.hex()

    def _decompress_value(self, compressed_hex: str) -> Any:
        """Decompress value from hex string"""
        try:
            compressed_bytes = bytes.fromhex(compressed_hex)
            decompressed = zlib.decompress(compressed_bytes)
            json_str = decompressed.decode('utf-8')
            return json.loads(json_str)
        except Exception as e:
            logger.error("decompression_error", error=str(e))
            return compressed_hex  # Return as-is if decompression fails

    async def _check_quota(self, tenant_id: str, config: TenantCacheConfig) -> bool:
        """Check if tenant can store more data"""
        metrics = await self.get_tenant_cache_metrics(tenant_id)
        return (metrics.memory_used_mb < config.max_memory_mb and
                metrics.total_entries < config.max_entries)

    async def _update_access_tracking(self, cache_key: str, entry: CacheEntry):
        """Update access tracking for cache entry"""
        try:
            entry.access_count += 1
            entry.last_accessed = datetime.now(timezone.utc)

            # Update in Redis (async, don't wait)
            asyncio.create_task(self.redis.setex(
                cache_key,
                int((entry.expires_at - datetime.now(timezone.utc)).total_seconds()) if entry.expires_at else 3600,
                entry.model_dump_json()
            ))

        except Exception as e:
            logger.error("access_tracking_error", cache_key=cache_key, error=str(e))

    async def _update_tenant_usage(
        self,
        tenant_id: str,
        namespace: CacheNamespace,
        size_bytes: int,
        operation: str
    ):
        """Update tenant usage tracking"""
        try:
            # Track in tenant manager for quota enforcement
            if operation == "add":
                await self.tenant_manager.track_resource_usage(
                    tenant_id,
                    "storage",
                    size_bytes / (1024 * 1024)  # Convert to MB
                )

        except Exception as e:
            logger.error("usage_tracking_error", tenant_id=tenant_id, error=str(e))

    async def _track_cache_hit(self, tenant_id: str, namespace: CacheNamespace):
        """Track cache hit for metrics"""
        if tenant_id not in self.metrics:
            self.metrics[tenant_id] = TenantCacheMetrics(
                tenant_id=tenant_id,
                period_start=datetime.now(timezone.utc),
                period_end=datetime.now(timezone.utc) + timedelta(hours=1)
            )

        self.metrics[tenant_id].hit_count += 1
        self._update_hit_rate(tenant_id)

    async def _track_cache_miss(self, tenant_id: str, namespace: CacheNamespace):
        """Track cache miss for metrics"""
        if tenant_id not in self.metrics:
            self.metrics[tenant_id] = TenantCacheMetrics(
                tenant_id=tenant_id,
                period_start=datetime.now(timezone.utc),
                period_end=datetime.now(timezone.utc) + timedelta(hours=1)
            )

        self.metrics[tenant_id].miss_count += 1
        self._update_hit_rate(tenant_id)

    def _update_hit_rate(self, tenant_id: str):
        """Update cache hit rate"""
        metrics = self.metrics[tenant_id]
        total_requests = metrics.hit_count + metrics.miss_count
        if total_requests > 0:
            metrics.cache_hit_rate = metrics.hit_count / total_requests

    async def _check_and_evict(self, tenant_id: str, config: TenantCacheConfig):
        """Check quotas and evict entries if needed"""
        metrics = await self.get_tenant_cache_metrics(tenant_id)

        if (metrics.memory_used_mb > config.max_memory_mb or
            metrics.total_entries > config.max_entries):

            evicted_count = await self._evict_entries(tenant_id, config)
            logger.info("cache_eviction_performed", tenant_id=tenant_id, evicted_count=evicted_count)

    async def _evict_entries(self, tenant_id: str, config: TenantCacheConfig) -> int:
        """Evict cache entries based on configured policy"""
        # This is a simplified LRU eviction
        # In production, you'd implement proper LRU/LFU algorithms

        pattern = f"{self.global_prefix}:tenant:{tenant_id}:*"
        entries_to_evict = []

        try:
            async for cache_key in self.redis.scan_iter(match=pattern):
                cached_data = await self.redis.get(cache_key)
                if cached_data:
                    try:
                        entry_data = json.loads(cached_data)
                        entry = CacheEntry(**entry_data)
                        entries_to_evict.append((cache_key, entry.last_accessed))
                    except Exception:
                        continue

            # Sort by last accessed time (oldest first)
            entries_to_evict.sort(key=lambda x: x[1])

            # Evict oldest entries
            evicted_count = 0
            for cache_key, _ in entries_to_evict[:config.eviction_batch_size]:
                if await self.redis.delete(cache_key):
                    evicted_count += 1

            return evicted_count

        except Exception as e:
            logger.error("cache_eviction_error", tenant_id=tenant_id, error=str(e))
            return 0