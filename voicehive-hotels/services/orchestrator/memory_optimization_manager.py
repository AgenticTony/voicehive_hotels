"""
Advanced Memory Optimization and Leak Detection Manager for VoiceHive Hotels
Real-time memory monitoring, optimization, and leak detection system
"""

import asyncio
import gc
import time
import tracemalloc
import weakref
from typing import Dict, List, Optional, Any, Set, Tuple, Callable
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import threading
import sys
import os

try:
    import psutil
except ImportError:
    psutil = None

try:
    import objgraph
except ImportError:
    objgraph = None

from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger

try:
    from prometheus_client import Counter, Histogram, Gauge, Summary
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
    
    Counter = Histogram = Gauge = Summary = MockMetric

logger = get_safe_logger("orchestrator.memory_optimization")

# Prometheus metrics for memory monitoring
memory_usage_bytes = Gauge(
    'voicehive_memory_usage_bytes',
    'Memory usage in bytes',
    ['memory_type', 'component']
)

memory_leak_detections = Counter(
    'voicehive_memory_leak_detections_total',
    'Memory leak detections',
    ['leak_type', 'component']
)

memory_optimization_actions = Counter(
    'voicehive_memory_optimization_actions_total',
    'Memory optimization actions taken',
    ['action_type', 'trigger']
)

memory_gc_duration = Histogram(
    'voicehive_memory_gc_duration_seconds',
    'Garbage collection duration',
    ['generation'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

memory_object_count = Gauge(
    'voicehive_memory_object_count',
    'Number of objects in memory',
    ['object_type']
)

memory_fragmentation_ratio = Gauge(
    'voicehive_memory_fragmentation_ratio',
    'Memory fragmentation ratio'
)


class MemoryLeakType(str, Enum):
    """Types of memory leaks"""
    GROWING_OBJECTS = "growing_objects"
    CIRCULAR_REFERENCES = "circular_references"
    UNCLOSED_RESOURCES = "unclosed_resources"
    CACHE_OVERFLOW = "cache_overflow"
    EVENT_LISTENERS = "event_listeners"
    THREAD_LOCALS = "thread_locals"


class OptimizationAction(str, Enum):
    """Memory optimization actions"""
    GARBAGE_COLLECT = "garbage_collect"
    CLEAR_CACHE = "clear_cache"
    CLOSE_RESOURCES = "close_resources"
    COMPACT_MEMORY = "compact_memory"
    RESTART_COMPONENT = "restart_component"
    REDUCE_BUFFER_SIZE = "reduce_buffer_size"


class MemoryAlert(str, Enum):
    """Memory alert levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class MemorySnapshot:
    """Memory usage snapshot"""
    timestamp: datetime
    rss_bytes: int
    vms_bytes: int
    heap_bytes: int
    available_bytes: int
    gc_stats: Dict[str, int]
    object_counts: Dict[str, int]
    top_objects: List[Tuple[str, int]]
    
    @property
    def memory_usage_mb(self) -> float:
        return self.rss_bytes / (1024 * 1024)
    
    @property
    def fragmentation_ratio(self) -> float:
        if self.heap_bytes > 0:
            return (self.vms_bytes - self.heap_bytes) / self.heap_bytes
        return 0.0


@dataclass
class MemoryLeak:
    """Memory leak detection result"""
    leak_type: MemoryLeakType
    component: str
    description: str
    growth_rate_mb_per_hour: float
    confidence: float
    first_detected: datetime
    last_detected: datetime
    snapshots: List[MemorySnapshot] = field(default_factory=list)
    
    @property
    def is_confirmed(self) -> bool:
        return self.confidence > 0.8 and len(self.snapshots) >= 3
    
    @property
    def severity(self) -> MemoryAlert:
        if self.growth_rate_mb_per_hour > 100:
            return MemoryAlert.CRITICAL
        elif self.growth_rate_mb_per_hour > 50:
            return MemoryAlert.WARNING
        else:
            return MemoryAlert.INFO


class MemoryOptimizationConfig(BaseModel):
    """Configuration for memory optimization manager"""
    # Monitoring settings
    enable_monitoring: bool = Field(True, description="Enable memory monitoring")
    monitoring_interval_seconds: int = Field(30, description="Memory monitoring interval")
    snapshot_retention_hours: int = Field(24, description="Snapshot retention period")
    
    # Leak detection settings
    enable_leak_detection: bool = Field(True, description="Enable memory leak detection")
    leak_detection_window_hours: int = Field(2, description="Leak detection analysis window")
    leak_confidence_threshold: float = Field(0.7, description="Leak detection confidence threshold")
    min_growth_rate_mb_per_hour: float = Field(10.0, description="Minimum growth rate for leak detection")
    
    # Optimization settings
    enable_automatic_optimization: bool = Field(True, description="Enable automatic optimization")
    memory_threshold_mb: int = Field(512, description="Memory usage threshold for optimization")
    critical_memory_threshold_mb: int = Field(1024, description="Critical memory threshold")
    gc_threshold_ratio: float = Field(0.8, description="GC trigger threshold ratio")
    
    # Object tracking
    enable_object_tracking: bool = Field(True, description="Enable object count tracking")
    track_object_types: List[str] = Field(
        default_factory=lambda: [
            'dict', 'list', 'tuple', 'set', 'str', 'bytes',
            'function', 'method', 'coroutine', 'asyncio.Task'
        ]
    )
    
    # Cache management
    enable_cache_management: bool = Field(True, description="Enable automatic cache management")
    cache_size_threshold_mb: int = Field(100, description="Cache size threshold for cleanup")
    
    # Resource monitoring
    enable_resource_monitoring: bool = Field(True, description="Enable resource leak monitoring")
    track_file_descriptors: bool = Field(True, description="Track file descriptor leaks")
    track_thread_count: bool = Field(True, description="Track thread count growth")
    
    # Alert settings
    enable_alerts: bool = Field(True, description="Enable memory alerts")
    alert_cooldown_seconds: int = Field(300, description="Alert cooldown period")


class MemoryTracker:
    """Advanced memory usage tracking and analysis"""
    
    def __init__(self):
        self.snapshots: List[MemorySnapshot] = []
        self.baseline_snapshot: Optional[MemorySnapshot] = None
        self.process = psutil.Process() if psutil else None
        
        # Object tracking
        self.object_trackers: Dict[str, weakref.WeakSet] = {}
        self.reference_cycles: Set[int] = set()
        
        # Resource tracking
        self.tracked_resources: Dict[str, Set[Any]] = {
            'files': set(),
            'sockets': set(),
            'threads': set(),
            'tasks': set()
        }
    
    def take_snapshot(self) -> MemorySnapshot:
        """Take a comprehensive memory snapshot"""
        try:
            # System memory info
            if self.process:
                memory_info = self.process.memory_info()
                rss_bytes = memory_info.rss
                vms_bytes = memory_info.vms
            else:
                rss_bytes = vms_bytes = 0
            
            # Heap memory estimation
            heap_bytes = self._estimate_heap_size()
            
            # Available memory
            if psutil:
                available_bytes = psutil.virtual_memory().available
            else:
                available_bytes = 0
            
            # GC statistics
            gc_stats = {
                f'gen_{i}': gc.get_count()[i] if i < len(gc.get_count()) else 0
                for i in range(3)
            }
            gc_stats.update({
                'collected': sum(gc.get_stats()[i]['collected'] for i in range(len(gc.get_stats()))),
                'collections': sum(gc.get_stats()[i]['collections'] for i in range(len(gc.get_stats())))
            })
            
            # Object counts
            object_counts = self._get_object_counts()
            
            # Top objects by count
            top_objects = self._get_top_objects()
            
            snapshot = MemorySnapshot(
                timestamp=datetime.now(timezone.utc),
                rss_bytes=rss_bytes,
                vms_bytes=vms_bytes,
                heap_bytes=heap_bytes,
                available_bytes=available_bytes,
                gc_stats=gc_stats,
                object_counts=object_counts,
                top_objects=top_objects
            )
            
            self.snapshots.append(snapshot)
            
            # Set baseline if first snapshot
            if not self.baseline_snapshot:
                self.baseline_snapshot = snapshot
            
            return snapshot
            
        except Exception as e:
            logger.error("memory_snapshot_failed", error=str(e))
            raise
    
    def _estimate_heap_size(self) -> int:
        """Estimate heap size using tracemalloc if available"""
        try:
            if tracemalloc.is_tracing():
                current, peak = tracemalloc.get_traced_memory()
                return current
            else:
                # Fallback estimation
                return sum(sys.getsizeof(obj) for obj in gc.get_objects()[:1000])  # Sample
        except Exception:
            return 0
    
    def _get_object_counts(self) -> Dict[str, int]:
        """Get counts of different object types"""
        counts = {}
        
        try:
            if objgraph:
                # Use objgraph for detailed object counting
                for obj_type in ['dict', 'list', 'tuple', 'set', 'str', 'bytes', 'function']:
                    counts[obj_type] = len(objgraph.by_type(obj_type))
            else:
                # Fallback manual counting
                type_counts = {}
                for obj in gc.get_objects()[:10000]:  # Sample to avoid performance issues
                    obj_type = type(obj).__name__
                    type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
                
                # Get top 10 types
                sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
                counts = dict(sorted_types[:10])
        
        except Exception as e:
            logger.warning("object_counting_failed", error=str(e))
        
        return counts
    
    def _get_top_objects(self) -> List[Tuple[str, int]]:
        """Get top objects by memory usage"""
        top_objects = []
        
        try:
            if objgraph:
                # Get most common types
                most_common = objgraph.most_common_types(limit=10)
                top_objects = [(name, count) for name, count in most_common]
            else:
                # Fallback - use object counts
                object_counts = self._get_object_counts()
                top_objects = list(object_counts.items())
        
        except Exception as e:
            logger.warning("top_objects_analysis_failed", error=str(e))
        
        return top_objects
    
    def detect_leaks(self, window_hours: int = 2) -> List[MemoryLeak]:
        """Detect memory leaks using trend analysis"""
        leaks = []
        
        if len(self.snapshots) < 3:
            return leaks
        
        try:
            # Filter snapshots within the window
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=window_hours)
            recent_snapshots = [
                s for s in self.snapshots 
                if s.timestamp > cutoff_time
            ]
            
            if len(recent_snapshots) < 3:
                return leaks
            
            # Analyze memory growth trends
            leaks.extend(self._detect_memory_growth_leaks(recent_snapshots))
            
            # Analyze object count growth
            leaks.extend(self._detect_object_growth_leaks(recent_snapshots))
            
            # Detect circular references
            leaks.extend(self._detect_circular_reference_leaks())
            
            # Detect resource leaks
            leaks.extend(self._detect_resource_leaks())
        
        except Exception as e:
            logger.error("leak_detection_failed", error=str(e))
        
        return leaks
    
    def _detect_memory_growth_leaks(self, snapshots: List[MemorySnapshot]) -> List[MemoryLeak]:
        """Detect leaks based on memory growth patterns"""
        leaks = []
        
        if len(snapshots) < 3:
            return leaks
        
        try:
            # Calculate memory growth rate
            first_snapshot = snapshots[0]
            last_snapshot = snapshots[-1]
            
            time_diff_hours = (last_snapshot.timestamp - first_snapshot.timestamp).total_seconds() / 3600
            if time_diff_hours <= 0:
                return leaks
            
            memory_growth_mb = (last_snapshot.rss_bytes - first_snapshot.rss_bytes) / (1024 * 1024)
            growth_rate = memory_growth_mb / time_diff_hours
            
            # Check if growth rate indicates a leak
            if growth_rate > 10.0:  # More than 10MB/hour growth
                # Calculate confidence based on consistency of growth
                growth_points = []
                for i in range(1, len(snapshots)):
                    prev_snapshot = snapshots[i-1]
                    curr_snapshot = snapshots[i]
                    
                    time_diff = (curr_snapshot.timestamp - prev_snapshot.timestamp).total_seconds() / 3600
                    if time_diff > 0:
                        point_growth = (curr_snapshot.rss_bytes - prev_snapshot.rss_bytes) / (1024 * 1024) / time_diff
                        growth_points.append(point_growth)
                
                # Calculate confidence based on consistency
                if growth_points:
                    avg_growth = sum(growth_points) / len(growth_points)
                    variance = sum((x - avg_growth) ** 2 for x in growth_points) / len(growth_points)
                    confidence = max(0.0, min(1.0, 1.0 - (variance / (avg_growth ** 2 + 1))))
                    
                    if confidence > 0.5:
                        leak = MemoryLeak(
                            leak_type=MemoryLeakType.GROWING_OBJECTS,
                            component="system",
                            description=f"Consistent memory growth detected: {growth_rate:.2f} MB/hour",
                            growth_rate_mb_per_hour=growth_rate,
                            confidence=confidence,
                            first_detected=first_snapshot.timestamp,
                            last_detected=last_snapshot.timestamp,
                            snapshots=snapshots
                        )
                        leaks.append(leak)
        
        except Exception as e:
            logger.error("memory_growth_leak_detection_failed", error=str(e))
        
        return leaks
    
    def _detect_object_growth_leaks(self, snapshots: List[MemorySnapshot]) -> List[MemoryLeak]:
        """Detect leaks based on object count growth"""
        leaks = []
        
        if len(snapshots) < 3:
            return leaks
        
        try:
            # Analyze growth for each object type
            for obj_type in ['dict', 'list', 'tuple', 'str']:
                first_count = snapshots[0].object_counts.get(obj_type, 0)
                last_count = snapshots[-1].object_counts.get(obj_type, 0)
                
                if first_count > 0 and last_count > first_count * 2:  # Doubled
                    time_diff_hours = (snapshots[-1].timestamp - snapshots[0].timestamp).total_seconds() / 3600
                    
                    if time_diff_hours > 0:
                        growth_rate = (last_count - first_count) / time_diff_hours
                        
                        # Estimate memory impact (rough)
                        estimated_mb_per_hour = growth_rate * 100 / (1024 * 1024)  # Rough estimate
                        
                        if estimated_mb_per_hour > 5.0:  # Significant growth
                            leak = MemoryLeak(
                                leak_type=MemoryLeakType.GROWING_OBJECTS,
                                component=f"objects_{obj_type}",
                                description=f"Rapid growth in {obj_type} objects: {growth_rate:.0f}/hour",
                                growth_rate_mb_per_hour=estimated_mb_per_hour,
                                confidence=0.7,
                                first_detected=snapshots[0].timestamp,
                                last_detected=snapshots[-1].timestamp,
                                snapshots=snapshots
                            )
                            leaks.append(leak)
        
        except Exception as e:
            logger.error("object_growth_leak_detection_failed", error=str(e))
        
        return leaks
    
    def _detect_circular_reference_leaks(self) -> List[MemoryLeak]:
        """Detect circular reference leaks"""
        leaks = []
        
        try:
            # Force garbage collection to identify uncollectable objects
            before_gc = len(gc.garbage)
            collected = gc.collect()
            after_gc = len(gc.garbage)
            
            if after_gc > before_gc:
                # New uncollectable objects found
                leak = MemoryLeak(
                    leak_type=MemoryLeakType.CIRCULAR_REFERENCES,
                    component="gc_uncollectable",
                    description=f"Circular references detected: {after_gc - before_gc} uncollectable objects",
                    growth_rate_mb_per_hour=0.0,  # Hard to estimate
                    confidence=0.8,
                    first_detected=datetime.now(timezone.utc),
                    last_detected=datetime.now(timezone.utc)
                )
                leaks.append(leak)
        
        except Exception as e:
            logger.error("circular_reference_detection_failed", error=str(e))
        
        return leaks
    
    def _detect_resource_leaks(self) -> List[MemoryLeak]:
        """Detect resource leaks (file descriptors, threads, etc.)"""
        leaks = []
        
        try:
            if not self.process:
                return leaks
            
            # Check file descriptor count
            try:
                fd_count = self.process.num_fds()
                if fd_count > 1000:  # High FD count
                    leak = MemoryLeak(
                        leak_type=MemoryLeakType.UNCLOSED_RESOURCES,
                        component="file_descriptors",
                        description=f"High file descriptor count: {fd_count}",
                        growth_rate_mb_per_hour=0.0,
                        confidence=0.6,
                        first_detected=datetime.now(timezone.utc),
                        last_detected=datetime.now(timezone.utc)
                    )
                    leaks.append(leak)
            except (AttributeError, psutil.AccessDenied):
                pass
            
            # Check thread count
            try:
                thread_count = self.process.num_threads()
                if thread_count > 100:  # High thread count
                    leak = MemoryLeak(
                        leak_type=MemoryLeakType.THREAD_LOCALS,
                        component="threads",
                        description=f"High thread count: {thread_count}",
                        growth_rate_mb_per_hour=0.0,
                        confidence=0.6,
                        first_detected=datetime.now(timezone.utc),
                        last_detected=datetime.now(timezone.utc)
                    )
                    leaks.append(leak)
            except (AttributeError, psutil.AccessDenied):
                pass
        
        except Exception as e:
            logger.error("resource_leak_detection_failed", error=str(e))
        
        return leaks
    
    def cleanup_snapshots(self, retention_hours: int):
        """Clean up old snapshots"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
        self.snapshots = [s for s in self.snapshots if s.timestamp > cutoff_time]


class MemoryOptimizer:
    """Memory optimization and cleanup manager"""
    
    def __init__(self, config: MemoryOptimizationConfig):
        self.config = config
        self.optimization_history: List[Dict[str, Any]] = []
        self.cache_managers: List[Callable] = []
        
    def register_cache_manager(self, manager: Callable):
        """Register a cache manager for automatic cleanup"""
        self.cache_managers.append(manager)
    
    async def optimize_memory(
        self,
        trigger: str = "manual",
        force: bool = False
    ) -> Dict[str, Any]:
        """Perform memory optimization"""
        start_time = time.time()
        actions_taken = []
        
        try:
            # Get current memory usage
            if psutil:
                process = psutil.Process()
                current_memory_mb = process.memory_info().rss / (1024 * 1024)
            else:
                current_memory_mb = 0
            
            logger.info("starting_memory_optimization",
                       current_memory_mb=current_memory_mb,
                       trigger=trigger)
            
            # Force garbage collection
            if force or current_memory_mb > self.config.memory_threshold_mb:
                gc_start = time.time()
                collected = gc.collect()
                gc_duration = time.time() - gc_start
                
                actions_taken.append({
                    "action": OptimizationAction.GARBAGE_COLLECT,
                    "objects_collected": collected,
                    "duration_seconds": gc_duration
                })
                
                memory_gc_duration.labels(generation="all").observe(gc_duration)
                memory_optimization_actions.labels(
                    action_type=OptimizationAction.GARBAGE_COLLECT,
                    trigger=trigger
                ).inc()
            
            # Clear caches if memory usage is high
            if current_memory_mb > self.config.cache_size_threshold_mb:
                cache_actions = await self._clear_caches()
                actions_taken.extend(cache_actions)
            
            # Compact memory if critically high
            if current_memory_mb > self.config.critical_memory_threshold_mb:
                compact_actions = await self._compact_memory()
                actions_taken.extend(compact_actions)
            
            # Get final memory usage
            if psutil:
                final_memory_mb = process.memory_info().rss / (1024 * 1024)
                memory_saved_mb = current_memory_mb - final_memory_mb
            else:
                final_memory_mb = 0
                memory_saved_mb = 0
            
            optimization_result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "trigger": trigger,
                "initial_memory_mb": current_memory_mb,
                "final_memory_mb": final_memory_mb,
                "memory_saved_mb": memory_saved_mb,
                "actions_taken": actions_taken,
                "duration_seconds": time.time() - start_time
            }
            
            self.optimization_history.append(optimization_result)
            
            logger.info("memory_optimization_completed",
                       memory_saved_mb=memory_saved_mb,
                       actions_count=len(actions_taken))
            
            return optimization_result
        
        except Exception as e:
            logger.error("memory_optimization_failed", error=str(e))
            return {"error": str(e)}
    
    async def _clear_caches(self) -> List[Dict[str, Any]]:
        """Clear registered caches"""
        actions = []
        
        for cache_manager in self.cache_managers:
            try:
                if asyncio.iscoroutinefunction(cache_manager):
                    result = await cache_manager()
                else:
                    result = cache_manager()
                
                actions.append({
                    "action": OptimizationAction.CLEAR_CACHE,
                    "manager": cache_manager.__name__,
                    "result": result
                })
                
                memory_optimization_actions.labels(
                    action_type=OptimizationAction.CLEAR_CACHE,
                    trigger="high_memory"
                ).inc()
            
            except Exception as e:
                logger.error("cache_clear_failed", 
                           manager=cache_manager.__name__, error=str(e))
        
        return actions
    
    async def _compact_memory(self) -> List[Dict[str, Any]]:
        """Perform memory compaction"""
        actions = []
        
        try:
            # Force multiple GC cycles for better cleanup
            for generation in range(3):
                collected = gc.collect(generation)
                if collected > 0:
                    actions.append({
                        "action": OptimizationAction.GARBAGE_COLLECT,
                        "generation": generation,
                        "objects_collected": collected
                    })
            
            # Clear weak references
            weakref_count = len(gc.get_referrers())
            actions.append({
                "action": OptimizationAction.COMPACT_MEMORY,
                "weak_references_cleared": weakref_count
            })
            
            memory_optimization_actions.labels(
                action_type=OptimizationAction.COMPACT_MEMORY,
                trigger="critical_memory"
            ).inc()
        
        except Exception as e:
            logger.error("memory_compaction_failed", error=str(e))
        
        return actions


class MemoryOptimizationManager:
    """Main memory optimization and leak detection manager"""
    
    def __init__(self, config: Optional[MemoryOptimizationConfig] = None):
        self.config = config or MemoryOptimizationConfig()
        self.tracker = MemoryTracker()
        self.optimizer = MemoryOptimizer(self.config)
        
        # Monitoring tasks
        self.monitoring_tasks: List[asyncio.Task] = []
        
        # Leak detection
        self.detected_leaks: List[MemoryLeak] = []
        self.last_alert_time: Dict[str, datetime] = {}
        
        # Statistics
        self.stats = {
            'snapshots_taken': 0,
            'leaks_detected': 0,
            'optimizations_performed': 0,
            'memory_saved_mb': 0.0
        }
        
        # Initialize tracemalloc if available
        if not tracemalloc.is_tracing():
            try:
                tracemalloc.start()
                logger.info("tracemalloc_started")
            except Exception as e:
                logger.warning("tracemalloc_start_failed", error=str(e))
    
    async def start(self):
        """Start memory optimization manager"""
        logger.info("starting_memory_optimization_manager")
        
        # Start monitoring task
        if self.config.enable_monitoring:
            task = asyncio.create_task(self._monitoring_loop())
            self.monitoring_tasks.append(task)
        
        # Start leak detection task
        if self.config.enable_leak_detection:
            task = asyncio.create_task(self._leak_detection_loop())
            self.monitoring_tasks.append(task)
        
        # Start optimization task
        if self.config.enable_automatic_optimization:
            task = asyncio.create_task(self._optimization_loop())
            self.monitoring_tasks.append(task)
        
        # Start cleanup task
        task = asyncio.create_task(self._cleanup_loop())
        self.monitoring_tasks.append(task)
        
        logger.info("memory_optimization_manager_started",
                   tasks=len(self.monitoring_tasks))
    
    async def stop(self):
        """Stop memory optimization manager"""
        logger.info("stopping_memory_optimization_manager")
        
        for task in self.monitoring_tasks:
            task.cancel()
        
        if self.monitoring_tasks:
            await asyncio.gather(*self.monitoring_tasks, return_exceptions=True)
        
        self.monitoring_tasks.clear()
        logger.info("memory_optimization_manager_stopped")
    
    async def _monitoring_loop(self):
        """Memory monitoring loop"""
        while True:
            try:
                await asyncio.sleep(self.config.monitoring_interval_seconds)
                
                # Take memory snapshot
                snapshot = self.tracker.take_snapshot()
                self.stats['snapshots_taken'] += 1
                
                # Update metrics
                memory_usage_bytes.labels(
                    memory_type="rss",
                    component="system"
                ).set(snapshot.rss_bytes)
                
                memory_usage_bytes.labels(
                    memory_type="vms",
                    component="system"
                ).set(snapshot.vms_bytes)
                
                memory_usage_bytes.labels(
                    memory_type="heap",
                    component="system"
                ).set(snapshot.heap_bytes)
                
                memory_fragmentation_ratio.set(snapshot.fragmentation_ratio)
                
                # Update object count metrics
                for obj_type, count in snapshot.object_counts.items():
                    memory_object_count.labels(object_type=obj_type).set(count)
                
                # Check for immediate optimization needs
                if snapshot.memory_usage_mb > self.config.critical_memory_threshold_mb:
                    logger.warning("critical_memory_usage_detected",
                                 memory_mb=snapshot.memory_usage_mb)
                    
                    if self.config.enable_automatic_optimization:
                        await self.optimizer.optimize_memory(trigger="critical_memory")
                
            except Exception as e:
                logger.error("monitoring_loop_error", error=str(e))
    
    async def _leak_detection_loop(self):
        """Memory leak detection loop"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                # Detect leaks
                leaks = self.tracker.detect_leaks(self.config.leak_detection_window_hours)
                
                for leak in leaks:
                    if leak.confidence >= self.config.leak_confidence_threshold:
                        # Check if this is a new leak or update existing
                        existing_leak = self._find_existing_leak(leak)
                        
                        if existing_leak:
                            existing_leak.last_detected = leak.last_detected
                            existing_leak.confidence = max(existing_leak.confidence, leak.confidence)
                        else:
                            self.detected_leaks.append(leak)
                            self.stats['leaks_detected'] += 1
                            
                            # Update metrics
                            memory_leak_detections.labels(
                                leak_type=leak.leak_type,
                                component=leak.component
                            ).inc()
                            
                            # Send alert
                            await self._send_leak_alert(leak)
                
            except Exception as e:
                logger.error("leak_detection_loop_error", error=str(e))
    
    async def _optimization_loop(self):
        """Automatic optimization loop"""
        while True:
            try:
                await asyncio.sleep(600)  # Check every 10 minutes
                
                # Get current memory usage
                if self.tracker.snapshots:
                    latest_snapshot = self.tracker.snapshots[-1]
                    
                    # Check if optimization is needed
                    if latest_snapshot.memory_usage_mb > self.config.memory_threshold_mb:
                        result = await self.optimizer.optimize_memory(trigger="scheduled")
                        
                        if 'memory_saved_mb' in result:
                            self.stats['memory_saved_mb'] += result['memory_saved_mb']
                            self.stats['optimizations_performed'] += 1
                
            except Exception as e:
                logger.error("optimization_loop_error", error=str(e))
    
    async def _cleanup_loop(self):
        """Cleanup old data loop"""
        while True:
            try:
                await asyncio.sleep(3600)  # Clean up every hour
                
                # Clean up old snapshots
                self.tracker.cleanup_snapshots(self.config.snapshot_retention_hours)
                
                # Clean up old leaks
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                self.detected_leaks = [
                    leak for leak in self.detected_leaks
                    if leak.last_detected > cutoff_time
                ]
                
                # Clean up optimization history
                self.optimizer.optimization_history = self.optimizer.optimization_history[-100:]
                
            except Exception as e:
                logger.error("cleanup_loop_error", error=str(e))
    
    def _find_existing_leak(self, new_leak: MemoryLeak) -> Optional[MemoryLeak]:
        """Find existing leak of the same type and component"""
        for existing_leak in self.detected_leaks:
            if (existing_leak.leak_type == new_leak.leak_type and
                existing_leak.component == new_leak.component):
                return existing_leak
        return None
    
    async def _send_leak_alert(self, leak: MemoryLeak):
        """Send memory leak alert"""
        alert_key = f"{leak.leak_type}_{leak.component}"
        
        # Check alert cooldown
        if alert_key in self.last_alert_time:
            time_since_last = datetime.now(timezone.utc) - self.last_alert_time[alert_key]
            if time_since_last.total_seconds() < self.config.alert_cooldown_seconds:
                return
        
        self.last_alert_time[alert_key] = datetime.now(timezone.utc)
        
        logger.warning("memory_leak_detected",
                      leak_type=leak.leak_type,
                      component=leak.component,
                      growth_rate=leak.growth_rate_mb_per_hour,
                      confidence=leak.confidence,
                      description=leak.description)
    
    def register_cache_manager(self, manager: Callable):
        """Register a cache manager for automatic cleanup"""
        self.optimizer.register_cache_manager(manager)
    
    async def force_optimization(self) -> Dict[str, Any]:
        """Force immediate memory optimization"""
        return await self.optimizer.optimize_memory(trigger="manual", force=True)
    
    def get_memory_report(self) -> Dict[str, Any]:
        """Generate comprehensive memory report"""
        latest_snapshot = self.tracker.snapshots[-1] if self.tracker.snapshots else None
        
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "current_memory": {
                "rss_mb": latest_snapshot.memory_usage_mb if latest_snapshot else 0,
                "vms_mb": latest_snapshot.vms_bytes / (1024 * 1024) if latest_snapshot else 0,
                "heap_mb": latest_snapshot.heap_bytes / (1024 * 1024) if latest_snapshot else 0,
                "fragmentation_ratio": latest_snapshot.fragmentation_ratio if latest_snapshot else 0
            },
            "statistics": self.stats,
            "detected_leaks": [
                {
                    "type": leak.leak_type,
                    "component": leak.component,
                    "description": leak.description,
                    "growth_rate_mb_per_hour": leak.growth_rate_mb_per_hour,
                    "confidence": leak.confidence,
                    "severity": leak.severity,
                    "first_detected": leak.first_detected.isoformat(),
                    "last_detected": leak.last_detected.isoformat()
                }
                for leak in self.detected_leaks
            ],
            "optimization_history": self.optimizer.optimization_history[-10:],  # Last 10
            "object_counts": latest_snapshot.object_counts if latest_snapshot else {},
            "gc_stats": latest_snapshot.gc_stats if latest_snapshot else {}
        }
        
        return report
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get memory health status"""
        latest_snapshot = self.tracker.snapshots[-1] if self.tracker.snapshots else None
        
        if not latest_snapshot:
            return {"status": "unknown", "reason": "No snapshots available"}
        
        memory_mb = latest_snapshot.memory_usage_mb
        
        # Determine health status
        if memory_mb > self.config.critical_memory_threshold_mb:
            status = "critical"
            reason = f"Memory usage ({memory_mb:.1f}MB) exceeds critical threshold"
        elif memory_mb > self.config.memory_threshold_mb:
            status = "warning"
            reason = f"Memory usage ({memory_mb:.1f}MB) exceeds warning threshold"
        elif len([l for l in self.detected_leaks if l.severity == MemoryAlert.CRITICAL]) > 0:
            status = "warning"
            reason = "Critical memory leaks detected"
        else:
            status = "healthy"
            reason = "Memory usage within normal limits"
        
        return {
            "status": status,
            "reason": reason,
            "memory_mb": memory_mb,
            "active_leaks": len(self.detected_leaks),
            "fragmentation_ratio": latest_snapshot.fragmentation_ratio
        }