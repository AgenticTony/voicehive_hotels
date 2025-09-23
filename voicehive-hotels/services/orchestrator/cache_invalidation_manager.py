"""
Advanced Cache Invalidation Manager for VoiceHive Hotels
Intelligent cache invalidation strategies with event-driven updates
"""

import asyncio
import json
import time
from typing import Dict, List, Optional, Any, Set, Callable, Union
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import weakref
import hashlib
import re

from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger
from redis_cluster_manager import RedisClusterManager

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

logger = get_safe_logger("orchestrator.cache_invalidation")

# Prometheus metrics for cache invalidation monitoring
cache_invalidations_total = Counter(
    'voicehive_cache_invalidations_total',
    'Total cache invalidations',
    ['strategy', 'reason', 'result']
)

cache_invalidation_duration = Histogram(
    'voicehive_cache_invalidation_duration_seconds',
    'Cache invalidation operation duration',
    ['strategy', 'scope'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

cache_invalidation_keys_affected = Histogram(
    'voicehive_cache_invalidation_keys_affected',
    'Number of keys affected by invalidation',
    ['strategy'],
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)
)

cache_warming_operations_total = Counter(
    'voicehive_cache_warming_operations_total',
    'Total cache warming operations',
    ['operation', 'result']
)

cache_warming_duration = Histogram(
    'voicehive_cache_warming_duration_seconds',
    'Cache warming operation duration',
    ['operation'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
)


class InvalidationTrigger(str, Enum):
    """Cache invalidation triggers"""
    DATA_CHANGE = "data_change"
    TIME_BASED = "time_based"
    MANUAL = "manual"
    DEPENDENCY = "dependency"
    PATTERN_MATCH = "pattern_match"
    EVENT_DRIVEN = "event_driven"
    CAPACITY_LIMIT = "capacity_limit"


class InvalidationScope(str, Enum):
    """Cache invalidation scope"""
    SINGLE_KEY = "single_key"
    KEY_PATTERN = "key_pattern"
    TAG_BASED = "tag_based"
    DEPENDENCY_TREE = "dependency_tree"
    NAMESPACE = "namespace"
    GLOBAL = "global"


class WarmingPriority(str, Enum):
    """Cache warming priority levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    BACKGROUND = "background"


@dataclass
class InvalidationRule:
    """Cache invalidation rule definition"""
    name: str
    trigger: InvalidationTrigger
    scope: InvalidationScope
    pattern: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)
    delay_seconds: int = 0
    batch_size: int = 100
    enabled: bool = True
    
    def matches_key(self, key: str, tags: List[str] = None) -> bool:
        """Check if rule matches a given key"""
        if self.scope == InvalidationScope.SINGLE_KEY:
            return key == self.pattern
        
        elif self.scope == InvalidationScope.KEY_PATTERN:
            if self.pattern:
                return re.match(self.pattern, key) is not None
        
        elif self.scope == InvalidationScope.TAG_BASED:
            if tags and self.tags:
                return any(tag in self.tags for tag in tags)
        
        return False


@dataclass
class WarmingTask:
    """Cache warming task definition"""
    key_pattern: str
    warming_function: str
    priority: WarmingPriority
    ttl_seconds: Optional[int] = None
    dependencies: List[str] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 3
    retry_delay: float = 1.0
    enabled: bool = True
    
    def __post_init__(self):
        self.created_at = datetime.now(timezone.utc)
        self.attempts = 0
        self.last_attempt = None
        self.last_success = None


class CacheInvalidationConfig(BaseModel):
    """Configuration for cache invalidation manager"""
    # Invalidation settings
    enable_automatic_invalidation: bool = Field(True, description="Enable automatic invalidation")
    enable_dependency_tracking: bool = Field(True, description="Enable dependency tracking")
    enable_tag_based_invalidation: bool = Field(True, description="Enable tag-based invalidation")
    
    # Performance settings
    max_concurrent_invalidations: int = Field(10, description="Max concurrent invalidations")
    invalidation_batch_size: int = Field(100, description="Batch size for bulk invalidations")
    invalidation_timeout_seconds: int = Field(30, description="Timeout for invalidation operations")
    
    # Warming settings
    enable_proactive_warming: bool = Field(True, description="Enable proactive cache warming")
    warming_threshold_percent: int = Field(75, description="TTL percentage to trigger warming")
    max_concurrent_warming: int = Field(5, description="Max concurrent warming operations")
    
    # Event processing
    enable_event_processing: bool = Field(True, description="Enable event-driven invalidation")
    event_queue_size: int = Field(1000, description="Event queue size")
    event_processing_interval: float = Field(0.1, description="Event processing interval")
    
    # Monitoring
    enable_metrics: bool = Field(True, description="Enable Prometheus metrics")
    log_invalidations: bool = Field(True, description="Log invalidation operations")
    
    # Default rules
    default_invalidation_rules: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "name": "hotel_config_changes",
                "trigger": "data_change",
                "scope": "key_pattern",
                "pattern": r"hotel:\d+:config.*",
                "delay_seconds": 0
            },
            {
                "name": "user_profile_updates",
                "trigger": "data_change",
                "scope": "key_pattern",
                "pattern": r"user:\d+:profile.*",
                "delay_seconds": 5
            },
            {
                "name": "pms_credential_rotation",
                "trigger": "event_driven",
                "scope": "tag_based",
                "tags": ["pms", "credentials"],
                "delay_seconds": 0
            }
        ]
    )


class CacheEvent:
    """Cache invalidation/warming event"""
    
    def __init__(
        self,
        event_type: str,
        key: Optional[str] = None,
        pattern: Optional[str] = None,
        tags: List[str] = None,
        data: Dict[str, Any] = None,
        priority: int = 1
    ):
        self.event_type = event_type
        self.key = key
        self.pattern = pattern
        self.tags = tags or []
        self.data = data or {}
        self.priority = priority
        self.timestamp = datetime.now(timezone.utc)
        self.processed = False
        self.attempts = 0


class CacheInvalidationManager:
    """Advanced cache invalidation and warming manager"""
    
    def __init__(
        self,
        cluster_manager: RedisClusterManager,
        config: Optional[CacheInvalidationConfig] = None
    ):
        self.cluster = cluster_manager
        self.config = config or CacheInvalidationConfig()
        
        # Invalidation rules and warming tasks
        self.invalidation_rules: Dict[str, InvalidationRule] = {}
        self.warming_tasks: Dict[str, WarmingTask] = {}
        self.warming_functions: Dict[str, Callable] = {}
        
        # Event processing
        self.event_queue: asyncio.Queue = asyncio.Queue(
            maxsize=self.config.event_queue_size
        )
        self.processing_tasks: List[asyncio.Task] = []
        
        # Dependency tracking
        self.key_dependencies: Dict[str, Set[str]] = {}
        self.tag_dependencies: Dict[str, Set[str]] = {}
        
        # Concurrency control
        self.invalidation_semaphore = asyncio.Semaphore(
            self.config.max_concurrent_invalidations
        )
        self.warming_semaphore = asyncio.Semaphore(
            self.config.max_concurrent_warming
        )
        
        # Statistics
        self.stats = {
            'invalidations_processed': 0,
            'warming_operations': 0,
            'events_processed': 0,
            'errors': 0
        }
        
        self._initialize_default_rules()
    
    def _initialize_default_rules(self):
        """Initialize default invalidation rules"""
        for rule_config in self.config.default_invalidation_rules:
            rule = InvalidationRule(
                name=rule_config['name'],
                trigger=InvalidationTrigger(rule_config['trigger']),
                scope=InvalidationScope(rule_config['scope']),
                pattern=rule_config.get('pattern'),
                tags=rule_config.get('tags', []),
                delay_seconds=rule_config.get('delay_seconds', 0)
            )
            self.invalidation_rules[rule.name] = rule
    
    async def start(self):
        """Start the cache invalidation manager"""
        logger.info("starting_cache_invalidation_manager")
        
        # Start event processing tasks
        for i in range(3):  # Multiple processors for better throughput
            task = asyncio.create_task(self._event_processing_loop())
            self.processing_tasks.append(task)
        
        # Start proactive warming task
        if self.config.enable_proactive_warming:
            task = asyncio.create_task(self._proactive_warming_loop())
            self.processing_tasks.append(task)
        
        # Start dependency cleanup task
        task = asyncio.create_task(self._dependency_cleanup_loop())
        self.processing_tasks.append(task)
        
        logger.info("cache_invalidation_manager_started", 
                   tasks=len(self.processing_tasks))
    
    async def stop(self):
        """Stop the cache invalidation manager"""
        logger.info("stopping_cache_invalidation_manager")
        
        # Cancel all processing tasks
        for task in self.processing_tasks:
            task.cancel()
        
        if self.processing_tasks:
            await asyncio.gather(*self.processing_tasks, return_exceptions=True)
        
        self.processing_tasks.clear()
        logger.info("cache_invalidation_manager_stopped")
    
    def add_invalidation_rule(self, rule: InvalidationRule):
        """Add a new invalidation rule"""
        self.invalidation_rules[rule.name] = rule
        logger.info("invalidation_rule_added", name=rule.name)
    
    def remove_invalidation_rule(self, name: str):
        """Remove an invalidation rule"""
        if name in self.invalidation_rules:
            del self.invalidation_rules[name]
            logger.info("invalidation_rule_removed", name=name)
    
    def register_warming_function(self, name: str, func: Callable):
        """Register a cache warming function"""
        self.warming_functions[name] = func
        logger.info("warming_function_registered", name=name)
    
    def add_warming_task(self, task: WarmingTask):
        """Add a cache warming task"""
        self.warming_tasks[task.key_pattern] = task
        logger.info("warming_task_added", pattern=task.key_pattern)
    
    async def invalidate_key(
        self,
        key: str,
        reason: str = "manual",
        cascade: bool = True
    ) -> bool:
        """Invalidate a specific cache key"""
        start_time = time.time()
        
        try:
            async with self.invalidation_semaphore:
                # Delete the key
                deleted = await self.cluster.delete(key)
                
                # Handle cascading invalidation
                if cascade and deleted > 0:
                    await self._cascade_invalidation(key)
                
                # Update metrics
                cache_invalidations_total.labels(
                    strategy="single_key",
                    reason=reason,
                    result="success"
                ).inc()
                
                cache_invalidation_duration.labels(
                    strategy="single_key",
                    scope="single"
                ).observe(time.time() - start_time)
                
                cache_invalidation_keys_affected.labels(
                    strategy="single_key"
                ).observe(deleted)
                
                self.stats['invalidations_processed'] += 1
                
                if self.config.log_invalidations:
                    logger.info("cache_key_invalidated", 
                               key=key, reason=reason, deleted=deleted)
                
                return deleted > 0
        
        except Exception as e:
            cache_invalidations_total.labels(
                strategy="single_key",
                reason=reason,
                result="error"
            ).inc()
            
            self.stats['errors'] += 1
            logger.error("cache_key_invalidation_failed", 
                        key=key, error=str(e))
            return False
    
    async def invalidate_pattern(
        self,
        pattern: str,
        reason: str = "manual",
        batch_size: int = None
    ) -> int:
        """Invalidate cache keys matching a pattern"""
        start_time = time.time()
        batch_size = batch_size or self.config.invalidation_batch_size
        
        try:
            async with self.invalidation_semaphore:
                deleted_count = await self.cluster.invalidate_by_pattern(pattern)
                
                # Update metrics
                cache_invalidations_total.labels(
                    strategy="pattern",
                    reason=reason,
                    result="success"
                ).inc()
                
                cache_invalidation_duration.labels(
                    strategy="pattern",
                    scope="multiple"
                ).observe(time.time() - start_time)
                
                cache_invalidation_keys_affected.labels(
                    strategy="pattern"
                ).observe(deleted_count)
                
                self.stats['invalidations_processed'] += 1
                
                if self.config.log_invalidations:
                    logger.info("cache_pattern_invalidated",
                               pattern=pattern, reason=reason, 
                               deleted=deleted_count)
                
                return deleted_count
        
        except Exception as e:
            cache_invalidations_total.labels(
                strategy="pattern",
                reason=reason,
                result="error"
            ).inc()
            
            self.stats['errors'] += 1
            logger.error("cache_pattern_invalidation_failed",
                        pattern=pattern, error=str(e))
            return 0
    
    async def invalidate_by_tags(
        self,
        tags: List[str],
        reason: str = "manual"
    ) -> int:
        """Invalidate cache keys by tags"""
        if not self.config.enable_tag_based_invalidation:
            logger.warning("tag_based_invalidation_disabled")
            return 0
        
        start_time = time.time()
        total_deleted = 0
        
        try:
            async with self.invalidation_semaphore:
                # Find keys with matching tags
                # This would require a tag index in a real implementation
                for tag in tags:
                    if tag in self.tag_dependencies:
                        keys_to_delete = list(self.tag_dependencies[tag])
                        
                        for key in keys_to_delete:
                            try:
                                deleted = await self.cluster.delete(key)
                                total_deleted += deleted
                            except Exception as e:
                                logger.warning("tag_key_deletion_failed",
                                             key=key, tag=tag, error=str(e))
                
                # Update metrics
                cache_invalidations_total.labels(
                    strategy="tags",
                    reason=reason,
                    result="success"
                ).inc()
                
                cache_invalidation_duration.labels(
                    strategy="tags",
                    scope="multiple"
                ).observe(time.time() - start_time)
                
                cache_invalidation_keys_affected.labels(
                    strategy="tags"
                ).observe(total_deleted)
                
                self.stats['invalidations_processed'] += 1
                
                if self.config.log_invalidations:
                    logger.info("cache_tags_invalidated",
                               tags=tags, reason=reason, 
                               deleted=total_deleted)
                
                return total_deleted
        
        except Exception as e:
            cache_invalidations_total.labels(
                strategy="tags",
                reason=reason,
                result="error"
            ).inc()
            
            self.stats['errors'] += 1
            logger.error("cache_tags_invalidation_failed",
                        tags=tags, error=str(e))
            return 0
    
    async def _cascade_invalidation(self, key: str):
        """Handle cascading invalidation for dependent keys"""
        if not self.config.enable_dependency_tracking:
            return
        
        try:
            # Find dependent keys
            dependent_keys = self.key_dependencies.get(key, set())
            
            for dependent_key in dependent_keys:
                try:
                    await self.cluster.delete(dependent_key)
                    logger.debug("dependent_key_invalidated",
                               parent=key, dependent=dependent_key)
                except Exception as e:
                    logger.warning("dependent_key_invalidation_failed",
                                 parent=key, dependent=dependent_key, 
                                 error=str(e))
        
        except Exception as e:
            logger.error("cascade_invalidation_failed", key=key, error=str(e))
    
    async def emit_event(self, event: CacheEvent):
        """Emit a cache invalidation/warming event"""
        try:
            await self.event_queue.put(event)
            logger.debug("cache_event_emitted", type=event.event_type)
        except asyncio.QueueFull:
            logger.warning("cache_event_queue_full", type=event.event_type)
    
    async def _event_processing_loop(self):
        """Process cache events from the queue"""
        while True:
            try:
                # Get event from queue with timeout
                try:
                    event = await asyncio.wait_for(
                        self.event_queue.get(),
                        timeout=self.config.event_processing_interval
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process the event
                await self._process_event(event)
                self.stats['events_processed'] += 1
                
            except Exception as e:
                logger.error("event_processing_loop_error", error=str(e))
                await asyncio.sleep(1)
    
    async def _process_event(self, event: CacheEvent):
        """Process a single cache event"""
        try:
            event.attempts += 1
            
            # Find matching invalidation rules
            matching_rules = self._find_matching_rules(event)
            
            for rule in matching_rules:
                if not rule.enabled:
                    continue
                
                # Apply delay if specified
                if rule.delay_seconds > 0:
                    await asyncio.sleep(rule.delay_seconds)
                
                # Execute invalidation based on rule scope
                if rule.scope == InvalidationScope.SINGLE_KEY and event.key:
                    await self.invalidate_key(event.key, reason=event.event_type)
                
                elif rule.scope == InvalidationScope.KEY_PATTERN and rule.pattern:
                    await self.invalidate_pattern(rule.pattern, reason=event.event_type)
                
                elif rule.scope == InvalidationScope.TAG_BASED and rule.tags:
                    await self.invalidate_by_tags(rule.tags, reason=event.event_type)
            
            # Check for warming opportunities
            await self._check_warming_opportunities(event)
            
            event.processed = True
            
        except Exception as e:
            logger.error("event_processing_failed", 
                        event_type=event.event_type, error=str(e))
            self.stats['errors'] += 1
    
    def _find_matching_rules(self, event: CacheEvent) -> List[InvalidationRule]:
        """Find invalidation rules that match the event"""
        matching_rules = []
        
        for rule in self.invalidation_rules.values():
            if not rule.enabled:
                continue
            
            # Check trigger type
            if rule.trigger == InvalidationTrigger.EVENT_DRIVEN:
                if event.key and rule.matches_key(event.key, event.tags):
                    matching_rules.append(rule)
                elif rule.scope == InvalidationScope.TAG_BASED:
                    if any(tag in rule.tags for tag in event.tags):
                        matching_rules.append(rule)
        
        return matching_rules
    
    async def _check_warming_opportunities(self, event: CacheEvent):
        """Check if event creates warming opportunities"""
        if not self.config.enable_proactive_warming:
            return
        
        try:
            # Find warming tasks that might be triggered by this event
            for pattern, task in self.warming_tasks.items():
                if not task.enabled:
                    continue
                
                # Check if event matches warming task pattern
                if event.key and re.match(pattern, event.key):
                    await self._execute_warming_task(task, event.key)
        
        except Exception as e:
            logger.error("warming_opportunity_check_failed", error=str(e))
    
    async def _execute_warming_task(self, task: WarmingTask, key: str):
        """Execute a cache warming task"""
        if task.warming_function not in self.warming_functions:
            logger.warning("warming_function_not_found", 
                          function=task.warming_function)
            return
        
        start_time = time.time()
        
        try:
            async with self.warming_semaphore:
                func = self.warming_functions[task.warming_function]
                
                # Execute warming function
                if asyncio.iscoroutinefunction(func):
                    await func(key)
                else:
                    func(key)
                
                task.last_success = datetime.now(timezone.utc)
                
                # Update metrics
                cache_warming_operations_total.labels(
                    operation=task.warming_function,
                    result="success"
                ).inc()
                
                cache_warming_duration.labels(
                    operation=task.warming_function
                ).observe(time.time() - start_time)
                
                self.stats['warming_operations'] += 1
                
                logger.debug("warming_task_executed",
                           function=task.warming_function, key=key)
        
        except Exception as e:
            task.last_attempt = datetime.now(timezone.utc)
            
            cache_warming_operations_total.labels(
                operation=task.warming_function,
                result="error"
            ).inc()
            
            self.stats['errors'] += 1
            logger.error("warming_task_failed",
                        function=task.warming_function, 
                        key=key, error=str(e))
    
    async def _proactive_warming_loop(self):
        """Proactive cache warming based on TTL thresholds"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                # Find keys that are close to expiring
                await self._warm_expiring_keys()
                
            except Exception as e:
                logger.error("proactive_warming_loop_error", error=str(e))
    
    async def _warm_expiring_keys(self):
        """Warm keys that are close to expiring"""
        try:
            # This would scan for keys with low TTL and trigger warming
            # Implementation would depend on specific warming strategies
            
            for pattern, task in self.warming_tasks.items():
                if not task.enabled:
                    continue
                
                # Find keys matching pattern with low TTL
                # This is a simplified implementation
                await self._check_pattern_for_warming(pattern, task)
        
        except Exception as e:
            logger.error("expiring_keys_warming_failed", error=str(e))
    
    async def _check_pattern_for_warming(self, pattern: str, task: WarmingTask):
        """Check a pattern for keys that need warming"""
        try:
            # This would scan Redis for keys matching the pattern
            # and check their TTL values
            
            # Simplified implementation - would need actual Redis scanning
            logger.debug("checking_pattern_for_warming", pattern=pattern)
            
        except Exception as e:
            logger.warning("pattern_warming_check_failed", 
                          pattern=pattern, error=str(e))
    
    async def _dependency_cleanup_loop(self):
        """Clean up stale dependency tracking data"""
        while True:
            try:
                await asyncio.sleep(3600)  # Clean up every hour
                
                # Remove stale dependencies
                await self._cleanup_stale_dependencies()
                
            except Exception as e:
                logger.error("dependency_cleanup_loop_error", error=str(e))
    
    async def _cleanup_stale_dependencies(self):
        """Clean up stale dependency tracking data"""
        try:
            # Remove dependencies for keys that no longer exist
            # This would require checking key existence in Redis
            
            stale_keys = []
            for key in self.key_dependencies.keys():
                # Check if key still exists (simplified)
                try:
                    exists = await self.cluster.cluster.exists(key)
                    if not exists:
                        stale_keys.append(key)
                except Exception:
                    stale_keys.append(key)
            
            # Remove stale dependencies
            for key in stale_keys:
                if key in self.key_dependencies:
                    del self.key_dependencies[key]
            
            if stale_keys:
                logger.info("stale_dependencies_cleaned", count=len(stale_keys))
        
        except Exception as e:
            logger.error("dependency_cleanup_failed", error=str(e))
    
    def add_key_dependency(self, parent_key: str, dependent_key: str):
        """Add a key dependency relationship"""
        if parent_key not in self.key_dependencies:
            self.key_dependencies[parent_key] = set()
        self.key_dependencies[parent_key].add(dependent_key)
    
    def add_tag_dependency(self, tag: str, key: str):
        """Add a tag dependency relationship"""
        if tag not in self.tag_dependencies:
            self.tag_dependencies[tag] = set()
        self.tag_dependencies[tag].add(key)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get invalidation manager statistics"""
        return {
            **self.stats,
            "invalidation_rules": len(self.invalidation_rules),
            "warming_tasks": len(self.warming_tasks),
            "warming_functions": len(self.warming_functions),
            "key_dependencies": len(self.key_dependencies),
            "tag_dependencies": len(self.tag_dependencies),
            "event_queue_size": self.event_queue.qsize(),
            "processing_tasks": len(self.processing_tasks)
        }


# Convenience functions for common invalidation patterns

async def invalidate_hotel_cache(
    manager: CacheInvalidationManager,
    hotel_id: str,
    reason: str = "hotel_update"
):
    """Invalidate all cache entries for a specific hotel"""
    pattern = f"hotel:{hotel_id}:*"
    return await manager.invalidate_pattern(pattern, reason)


async def invalidate_user_cache(
    manager: CacheInvalidationManager,
    user_id: str,
    reason: str = "user_update"
):
    """Invalidate all cache entries for a specific user"""
    pattern = f"user:{user_id}:*"
    return await manager.invalidate_pattern(pattern, reason)


async def invalidate_pms_cache(
    manager: CacheInvalidationManager,
    reason: str = "pms_update"
):
    """Invalidate all PMS-related cache entries"""
    tags = ["pms", "credentials", "configuration"]
    return await manager.invalidate_by_tags(tags, reason)


async def warm_critical_data(
    manager: CacheInvalidationManager,
    hotel_id: Optional[str] = None
):
    """Warm critical data for a hotel or all hotels"""
    if hotel_id:
        event = CacheEvent(
            event_type="warm_critical_data",
            pattern=f"hotel:{hotel_id}:*",
            tags=["critical", "hotel"],
            priority=1
        )
    else:
        event = CacheEvent(
            event_type="warm_critical_data",
            pattern="hotel:*:config",
            tags=["critical", "global"],
            priority=1
        )
    
    await manager.emit_event(event)