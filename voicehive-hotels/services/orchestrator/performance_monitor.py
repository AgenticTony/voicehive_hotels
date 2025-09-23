"""
Performance Monitor for VoiceHive Hotels Orchestrator
Comprehensive performance monitoring and metrics collection system
"""

import asyncio
import time
import gc
from typing import Dict, List, Optional, Any, Callable, Union
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import json
import weakref
from contextlib import asynccontextmanager

try:
    import psutil
except ImportError:
    psutil = None

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
    from prometheus_client import (
        Counter, Gauge, Histogram, Summary, Info,
        CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
    )
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
    
    Counter = Gauge = Histogram = Summary = Info = MockMetric
    
    def generate_latest():
        return "# Mock Prometheus metrics\n"
    
    CONTENT_TYPE_LATEST = "text/plain"

logger = get_safe_logger("orchestrator.performance")

# Custom Prometheus metrics
performance_request_duration = Histogram(
    'voicehive_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint', 'status_code'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0)
)

performance_request_count = Counter(
    'voicehive_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status_code']
)

performance_active_requests = Gauge(
    'voicehive_active_requests',
    'Number of active requests',
    ['endpoint']
)

performance_memory_usage = Gauge(
    'voicehive_memory_usage_bytes',
    'Memory usage in bytes',
    ['type']
)

performance_cpu_usage = Gauge(
    'voicehive_cpu_usage_percent',
    'CPU usage percentage'
)

performance_gc_collections = Counter(
    'voicehive_gc_collections_total',
    'Garbage collection count',
    ['generation']
)

performance_gc_duration = Histogram(
    'voicehive_gc_duration_seconds',
    'Garbage collection duration',
    ['generation']
)

performance_database_operations = Histogram(
    'voicehive_database_operation_duration_seconds',
    'Database operation duration',
    ['operation', 'table', 'result'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

performance_redis_operations = Histogram(
    'voicehive_redis_operation_duration_seconds',
    'Redis operation duration',
    ['operation', 'result'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

performance_external_api_calls = Histogram(
    'voicehive_external_api_duration_seconds',
    'External API call duration',
    ['service', 'endpoint', 'status_code'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
)

performance_queue_size = Gauge(
    'voicehive_queue_size',
    'Queue size',
    ['queue_name']
)

performance_error_rate = Gauge(
    'voicehive_error_rate',
    'Error rate percentage',
    ['component']
)

performance_throughput = Gauge(
    'voicehive_throughput_per_second',
    'Operations per second',
    ['component', 'operation']
)


class MetricType(str, Enum):
    """Types of performance metrics"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class AlertSeverity(str, Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class PerformanceThreshold:
    """Performance threshold configuration"""
    metric_name: str
    threshold_value: float
    comparison: str = ">"  # >, <, >=, <=, ==, !=
    severity: AlertSeverity = AlertSeverity.WARNING
    duration_seconds: int = 60  # How long threshold must be exceeded
    description: str = ""


@dataclass
class PerformanceAlert:
    """Performance alert"""
    metric_name: str
    current_value: float
    threshold_value: float
    severity: AlertSeverity
    description: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: int = 0


class PerformanceConfig(BaseModel):
    """Configuration for performance monitoring"""
    # Collection intervals
    system_metrics_interval: int = Field(30, description="System metrics collection interval")
    application_metrics_interval: int = Field(60, description="Application metrics collection interval")
    gc_metrics_interval: int = Field(120, description="GC metrics collection interval")
    
    # Retention settings
    metrics_retention_hours: int = Field(24, description="Metrics retention in hours")
    detailed_metrics_retention_hours: int = Field(6, description="Detailed metrics retention")
    
    # Performance thresholds
    memory_threshold_mb: int = Field(512, description="Memory usage threshold in MB")
    cpu_threshold_percent: float = Field(80.0, description="CPU usage threshold percentage")
    response_time_threshold_ms: float = Field(1000.0, description="Response time threshold in ms")
    error_rate_threshold_percent: float = Field(5.0, description="Error rate threshold percentage")
    
    # Alerting
    enable_alerting: bool = Field(True, description="Enable performance alerting")
    alert_cooldown_seconds: int = Field(300, description="Alert cooldown period")
    
    # Storage
    enable_redis_storage: bool = Field(True, description="Store metrics in Redis")
    redis_key_prefix: str = Field("voicehive:metrics:", description="Redis key prefix for metrics")
    
    # Sampling
    enable_sampling: bool = Field(True, description="Enable metric sampling for high-volume metrics")
    sampling_rate: float = Field(0.1, description="Sampling rate (0.0-1.0)")


class SystemMetrics(BaseModel):
    """System-level performance metrics"""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # CPU metrics
    cpu_percent: float = 0.0
    cpu_count: int = 0
    load_average: List[float] = Field(default_factory=list)
    
    # Memory metrics
    memory_total: int = 0
    memory_available: int = 0
    memory_used: int = 0
    memory_percent: float = 0.0
    
    # Disk metrics
    disk_total: int = 0
    disk_used: int = 0
    disk_free: int = 0
    disk_percent: float = 0.0
    
    # Network metrics
    network_bytes_sent: int = 0
    network_bytes_recv: int = 0
    network_packets_sent: int = 0
    network_packets_recv: int = 0
    
    # Process metrics
    process_memory_rss: int = 0
    process_memory_vms: int = 0
    process_cpu_percent: float = 0.0
    process_num_threads: int = 0
    process_num_fds: int = 0


class ApplicationMetrics(BaseModel):
    """Application-level performance metrics"""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Request metrics
    total_requests: int = 0
    active_requests: int = 0
    requests_per_second: float = 0.0
    avg_response_time_ms: float = 0.0
    
    # Error metrics
    total_errors: int = 0
    error_rate_percent: float = 0.0
    
    # Database metrics
    db_connections_active: int = 0
    db_connections_idle: int = 0
    db_query_count: int = 0
    avg_db_query_time_ms: float = 0.0
    
    # Redis metrics
    redis_connections: int = 0
    redis_operations: int = 0
    avg_redis_time_ms: float = 0.0
    
    # Cache metrics
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_ratio: float = 0.0
    
    # Queue metrics
    queue_sizes: Dict[str, int] = Field(default_factory=dict)
    
    # Custom metrics
    custom_metrics: Dict[str, float] = Field(default_factory=dict)


class GCMetrics(BaseModel):
    """Garbage collection metrics"""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # GC counts by generation
    gc_count_gen0: int = 0
    gc_count_gen1: int = 0
    gc_count_gen2: int = 0
    
    # GC thresholds
    gc_threshold_gen0: int = 0
    gc_threshold_gen1: int = 0
    gc_threshold_gen2: int = 0
    
    # Memory before/after GC
    memory_before_gc: int = 0
    memory_after_gc: int = 0
    memory_freed: int = 0
    
    # GC duration
    gc_duration_ms: float = 0.0


class PerformanceTracker:
    """Tracks performance metrics for specific operations"""
    
    def __init__(self, name: str, labels: Optional[Dict[str, str]] = None):
        self.name = name
        self.labels = labels or {}
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        
        if self.start_time:
            duration = self.end_time - self.start_time
            
            # Record to appropriate metric based on name
            if "request" in self.name.lower():
                performance_request_duration.labels(**self.labels).observe(duration)
            elif "database" in self.name.lower():
                performance_database_operations.labels(**self.labels).observe(duration)
            elif "redis" in self.name.lower():
                performance_redis_operations.labels(**self.labels).observe(duration)
            elif "external" in self.name.lower():
                performance_external_api_calls.labels(**self.labels).observe(duration)
    
    async def __aenter__(self):
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        
        if self.start_time:
            duration = self.end_time - self.start_time
            
            # Record to appropriate metric
            if "request" in self.name.lower():
                performance_request_duration.labels(**self.labels).observe(duration)
            elif "database" in self.name.lower():
                performance_database_operations.labels(**self.labels).observe(duration)
            elif "redis" in self.name.lower():
                performance_redis_operations.labels(**self.labels).observe(duration)
            elif "external" in self.name.lower():
                performance_external_api_calls.labels(**self.labels).observe(duration)
    
    def get_duration(self) -> Optional[float]:
        """Get operation duration"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


class PerformanceCollector:
    """Collects system and application performance metrics"""
    
    def __init__(self, config: PerformanceConfig):
        self.config = config
        self._process = psutil.Process()
        self._last_network_stats = None
        self._last_collection_time = None
        
        # Metric history for calculations
        self._request_history: List[tuple] = []  # (timestamp, count)
        self._error_history: List[tuple] = []    # (timestamp, count)
        
    async def collect_system_metrics(self) -> SystemMetrics:
        """Collect system-level performance metrics"""
        if psutil is None:
            return SystemMetrics()
        
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            
            try:
                load_avg = list(psutil.getloadavg())
            except AttributeError:
                # Windows doesn't have getloadavg
                load_avg = [0.0, 0.0, 0.0]
            
            # Memory metrics
            memory = psutil.virtual_memory()
            
            # Disk metrics
            disk = psutil.disk_usage('/')
            
            # Network metrics
            network = psutil.net_io_counters()
            
            # Process metrics
            process_memory = self._process.memory_info()
            process_cpu = self._process.cpu_percent()
            
            try:
                process_threads = self._process.num_threads()
                process_fds = self._process.num_fds()
            except (AttributeError, psutil.AccessDenied):
                process_threads = 0
                process_fds = 0
            
            metrics = SystemMetrics(
                cpu_percent=cpu_percent,
                cpu_count=cpu_count,
                load_average=load_avg,
                memory_total=memory.total,
                memory_available=memory.available,
                memory_used=memory.used,
                memory_percent=memory.percent,
                disk_total=disk.total,
                disk_used=disk.used,
                disk_free=disk.free,
                disk_percent=(disk.used / disk.total) * 100,
                network_bytes_sent=network.bytes_sent,
                network_bytes_recv=network.bytes_recv,
                network_packets_sent=network.packets_sent,
                network_packets_recv=network.packets_recv,
                process_memory_rss=process_memory.rss,
                process_memory_vms=process_memory.vms,
                process_cpu_percent=process_cpu,
                process_num_threads=process_threads,
                process_num_fds=process_fds
            )
            
            # Update Prometheus metrics
            performance_memory_usage.labels(type="rss").set(process_memory.rss)
            performance_memory_usage.labels(type="vms").set(process_memory.vms)
            performance_memory_usage.labels(type="system_used").set(memory.used)
            performance_memory_usage.labels(type="system_available").set(memory.available)
            performance_cpu_usage.set(cpu_percent)
            
            return metrics
            
        except Exception as e:
            logger.error("system_metrics_collection_error", error=str(e))
            return SystemMetrics()
    
    async def collect_gc_metrics(self) -> GCMetrics:
        """Collect garbage collection metrics"""
        try:
            gc_stats = gc.get_stats()
            gc_counts = gc.get_count()
            
            # Get memory before GC
            memory_before = self._process.memory_info().rss
            
            # Trigger GC and measure
            start_time = time.time()
            collected = gc.collect()
            gc_duration = (time.time() - start_time) * 1000  # Convert to ms
            
            # Get memory after GC
            memory_after = self._process.memory_info().rss
            memory_freed = max(0, memory_before - memory_after)
            
            metrics = GCMetrics(
                gc_count_gen0=gc_counts[0] if len(gc_counts) > 0 else 0,
                gc_count_gen1=gc_counts[1] if len(gc_counts) > 1 else 0,
                gc_count_gen2=gc_counts[2] if len(gc_counts) > 2 else 0,
                memory_before_gc=memory_before,
                memory_after_gc=memory_after,
                memory_freed=memory_freed,
                gc_duration_ms=gc_duration
            )
            
            # Update Prometheus metrics
            for i, count in enumerate(gc_counts):
                performance_gc_collections.labels(generation=str(i)).inc(count)
            
            performance_gc_duration.labels(generation="all").observe(gc_duration / 1000)
            
            return metrics
            
        except Exception as e:
            logger.error("gc_metrics_collection_error", error=str(e))
            return GCMetrics()
    
    def calculate_rates(self, current_time: float, current_requests: int, current_errors: int):
        """Calculate request and error rates"""
        # Clean old history (keep last 5 minutes)
        cutoff_time = current_time - 300
        self._request_history = [(t, c) for t, c in self._request_history if t > cutoff_time]
        self._error_history = [(t, c) for t, c in self._error_history if t > cutoff_time]
        
        # Add current values
        self._request_history.append((current_time, current_requests))
        self._error_history.append((current_time, current_errors))
        
        # Calculate rates
        requests_per_second = 0.0
        error_rate_percent = 0.0
        
        if len(self._request_history) >= 2:
            time_diff = self._request_history[-1][0] - self._request_history[0][0]
            request_diff = self._request_history[-1][1] - self._request_history[0][1]
            
            if time_diff > 0:
                requests_per_second = request_diff / time_diff
        
        if current_requests > 0:
            error_rate_percent = (current_errors / current_requests) * 100
        
        return requests_per_second, error_rate_percent


class PerformanceMonitor:
    """Main performance monitoring system"""
    
    def __init__(
        self,
        config: Optional[PerformanceConfig] = None,
        redis_client: Optional[aioredis.Redis] = None
    ):
        self.config = config or PerformanceConfig()
        self.redis_client = redis_client
        self.collector = PerformanceCollector(self.config)
        
        # Monitoring state
        self._monitoring_tasks: List[asyncio.Task] = []
        self._active_requests: Dict[str, int] = {}
        self._performance_thresholds: List[PerformanceThreshold] = []
        self._active_alerts: Dict[str, PerformanceAlert] = {}
        
        # Metrics storage
        self._metrics_history: Dict[str, List[Any]] = {
            'system': [],
            'application': [],
            'gc': []
        }
        
        # Request tracking
        self._request_counters: Dict[str, int] = {}
        self._error_counters: Dict[str, int] = {}
        
        self._initialize_default_thresholds()
    
    def _initialize_default_thresholds(self):
        """Initialize default performance thresholds"""
        self._performance_thresholds = [
            PerformanceThreshold(
                metric_name="memory_usage_mb",
                threshold_value=self.config.memory_threshold_mb,
                comparison=">",
                severity=AlertSeverity.WARNING,
                description="High memory usage detected"
            ),
            PerformanceThreshold(
                metric_name="cpu_usage_percent",
                threshold_value=self.config.cpu_threshold_percent,
                comparison=">",
                severity=AlertSeverity.WARNING,
                description="High CPU usage detected"
            ),
            PerformanceThreshold(
                metric_name="response_time_ms",
                threshold_value=self.config.response_time_threshold_ms,
                comparison=">",
                severity=AlertSeverity.WARNING,
                description="High response time detected"
            ),
            PerformanceThreshold(
                metric_name="error_rate_percent",
                threshold_value=self.config.error_rate_threshold_percent,
                comparison=">",
                severity=AlertSeverity.CRITICAL,
                description="High error rate detected"
            )
        ]
    
    async def start_monitoring(self):
        """Start performance monitoring tasks"""
        logger.info("starting_performance_monitoring")
        
        # System metrics collection
        self._monitoring_tasks.append(
            asyncio.create_task(self._system_metrics_loop())
        )
        
        # Application metrics collection
        self._monitoring_tasks.append(
            asyncio.create_task(self._application_metrics_loop())
        )
        
        # GC metrics collection
        self._monitoring_tasks.append(
            asyncio.create_task(self._gc_metrics_loop())
        )
        
        # Alert checking
        if self.config.enable_alerting:
            self._monitoring_tasks.append(
                asyncio.create_task(self._alert_checking_loop())
            )
        
        # Metrics cleanup
        self._monitoring_tasks.append(
            asyncio.create_task(self._cleanup_loop())
        )
        
        logger.info("performance_monitoring_started", tasks=len(self._monitoring_tasks))
    
    async def stop_monitoring(self):
        """Stop performance monitoring tasks"""
        logger.info("stopping_performance_monitoring")
        
        for task in self._monitoring_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self._monitoring_tasks:
            await asyncio.gather(*self._monitoring_tasks, return_exceptions=True)
        
        self._monitoring_tasks.clear()
        logger.info("performance_monitoring_stopped")
    
    @asynccontextmanager
    async def track_request(self, endpoint: str, method: str = "GET"):
        """Context manager to track request performance"""
        start_time = time.time()
        
        # Increment active requests
        key = f"{method}:{endpoint}"
        self._active_requests[key] = self._active_requests.get(key, 0) + 1
        performance_active_requests.labels(endpoint=endpoint).inc()
        
        status_code = "200"  # Default
        
        try:
            yield
        except Exception as e:
            status_code = "500"
            self._error_counters[key] = self._error_counters.get(key, 0) + 1
            raise
        finally:
            # Record metrics
            duration = time.time() - start_time
            
            performance_request_duration.labels(
                method=method,
                endpoint=endpoint,
                status_code=status_code
            ).observe(duration)
            
            performance_request_count.labels(
                method=method,
                endpoint=endpoint,
                status_code=status_code
            ).inc()
            
            # Decrement active requests
            self._active_requests[key] = max(0, self._active_requests.get(key, 1) - 1)
            performance_active_requests.labels(endpoint=endpoint).dec()
            
            # Update request counter
            self._request_counters[key] = self._request_counters.get(key, 0) + 1
    
    def track_database_operation(self, operation: str, table: str = "unknown"):
        """Track database operation performance"""
        return PerformanceTracker(
            "database_operation",
            {"operation": operation, "table": table, "result": "success"}
        )
    
    def track_redis_operation(self, operation: str):
        """Track Redis operation performance"""
        return PerformanceTracker(
            "redis_operation",
            {"operation": operation, "result": "success"}
        )
    
    def track_external_api_call(self, service: str, endpoint: str):
        """Track external API call performance"""
        return PerformanceTracker(
            "external_api_call",
            {"service": service, "endpoint": endpoint, "status_code": "200"}
        )
    
    def update_queue_size(self, queue_name: str, size: int):
        """Update queue size metric"""
        performance_queue_size.labels(queue_name=queue_name).set(size)
    
    def update_error_rate(self, component: str, error_rate: float):
        """Update error rate metric"""
        performance_error_rate.labels(component=component).set(error_rate)
    
    def update_throughput(self, component: str, operation: str, ops_per_second: float):
        """Update throughput metric"""
        performance_throughput.labels(
            component=component,
            operation=operation
        ).set(ops_per_second)
    
    async def get_current_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics"""
        system_metrics = await self.collector.collect_system_metrics()
        
        # Calculate application metrics
        total_requests = sum(self._request_counters.values())
        total_errors = sum(self._error_counters.values())
        active_requests = sum(self._active_requests.values())
        
        current_time = time.time()
        requests_per_second, error_rate = self.collector.calculate_rates(
            current_time, total_requests, total_errors
        )
        
        application_metrics = ApplicationMetrics(
            total_requests=total_requests,
            active_requests=active_requests,
            requests_per_second=requests_per_second,
            total_errors=total_errors,
            error_rate_percent=error_rate
        )
        
        return {
            'system': system_metrics.dict(),
            'application': application_metrics.dict(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    async def get_metrics_history(
        self,
        metric_type: str,
        hours: int = 1
    ) -> List[Dict[str, Any]]:
        """Get metrics history"""
        if metric_type not in self._metrics_history:
            return []
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        return [
            metric for metric in self._metrics_history[metric_type]
            if metric.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)) > cutoff_time
        ]
    
    async def _system_metrics_loop(self):
        """System metrics collection loop"""
        while True:
            try:
                await asyncio.sleep(self.config.system_metrics_interval)
                
                metrics = await self.collector.collect_system_metrics()
                
                # Store in history
                self._metrics_history['system'].append(metrics.dict())
                
                # Store in Redis if enabled
                if self.config.enable_redis_storage and self.redis_client:
                    key = f"{self.config.redis_key_prefix}system:{int(time.time())}"
                    await self.redis_client.setex(
                        key,
                        self.config.metrics_retention_hours * 3600,
                        json.dumps(metrics.dict(), default=str)
                    )
                
            except Exception as e:
                logger.error("system_metrics_loop_error", error=str(e))
    
    async def _application_metrics_loop(self):
        """Application metrics collection loop"""
        while True:
            try:
                await asyncio.sleep(self.config.application_metrics_interval)
                
                # Calculate current application metrics
                total_requests = sum(self._request_counters.values())
                total_errors = sum(self._error_counters.values())
                active_requests = sum(self._active_requests.values())
                
                current_time = time.time()
                requests_per_second, error_rate = self.collector.calculate_rates(
                    current_time, total_requests, total_errors
                )
                
                metrics = ApplicationMetrics(
                    total_requests=total_requests,
                    active_requests=active_requests,
                    requests_per_second=requests_per_second,
                    total_errors=total_errors,
                    error_rate_percent=error_rate
                )
                
                # Store in history
                self._metrics_history['application'].append(metrics.dict())
                
                # Store in Redis if enabled
                if self.config.enable_redis_storage and self.redis_client:
                    key = f"{self.config.redis_key_prefix}application:{int(time.time())}"
                    await self.redis_client.setex(
                        key,
                        self.config.metrics_retention_hours * 3600,
                        json.dumps(metrics.dict(), default=str)
                    )
                
            except Exception as e:
                logger.error("application_metrics_loop_error", error=str(e))
    
    async def _gc_metrics_loop(self):
        """GC metrics collection loop"""
        while True:
            try:
                await asyncio.sleep(self.config.gc_metrics_interval)
                
                metrics = await self.collector.collect_gc_metrics()
                
                # Store in history
                self._metrics_history['gc'].append(metrics.dict())
                
            except Exception as e:
                logger.error("gc_metrics_loop_error", error=str(e))
    
    async def _alert_checking_loop(self):
        """Alert checking loop"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                current_metrics = await self.get_current_metrics()
                await self._check_thresholds(current_metrics)
                
            except Exception as e:
                logger.error("alert_checking_loop_error", error=str(e))
    
    async def _cleanup_loop(self):
        """Cleanup old metrics loop"""
        while True:
            try:
                await asyncio.sleep(3600)  # Cleanup every hour
                
                cutoff_time = datetime.now(timezone.utc) - timedelta(
                    hours=self.config.metrics_retention_hours
                )
                
                # Clean up in-memory history
                for metric_type in self._metrics_history:
                    self._metrics_history[metric_type] = [
                        metric for metric in self._metrics_history[metric_type]
                        if metric.get('timestamp', datetime.min.replace(tzinfo=timezone.utc)) > cutoff_time
                    ]
                
                logger.debug("metrics_cleanup_completed")
                
            except Exception as e:
                logger.error("cleanup_loop_error", error=str(e))
    
    async def _check_thresholds(self, metrics: Dict[str, Any]):
        """Check performance thresholds and generate alerts"""
        for threshold in self._performance_thresholds:
            try:
                # Extract metric value
                metric_value = self._extract_metric_value(metrics, threshold.metric_name)
                if metric_value is None:
                    continue
                
                # Check threshold
                threshold_exceeded = self._evaluate_threshold(
                    metric_value, threshold.threshold_value, threshold.comparison
                )
                
                if threshold_exceeded:
                    # Create or update alert
                    alert_key = f"{threshold.metric_name}_{threshold.severity.value}"
                    
                    if alert_key in self._active_alerts:
                        # Update existing alert
                        self._active_alerts[alert_key].duration_seconds += 60
                    else:
                        # Create new alert
                        alert = PerformanceAlert(
                            metric_name=threshold.metric_name,
                            current_value=metric_value,
                            threshold_value=threshold.threshold_value,
                            severity=threshold.severity,
                            description=threshold.description
                        )
                        self._active_alerts[alert_key] = alert
                        
                        logger.warning(
                            "performance_alert_triggered",
                            metric=threshold.metric_name,
                            current_value=metric_value,
                            threshold=threshold.threshold_value,
                            severity=threshold.severity.value
                        )
                else:
                    # Remove alert if it exists
                    alert_key = f"{threshold.metric_name}_{threshold.severity.value}"
                    if alert_key in self._active_alerts:
                        del self._active_alerts[alert_key]
                        
                        logger.info(
                            "performance_alert_resolved",
                            metric=threshold.metric_name,
                            current_value=metric_value
                        )
                
            except Exception as e:
                logger.error("threshold_check_error", threshold=threshold.metric_name, error=str(e))
    
    def _extract_metric_value(self, metrics: Dict[str, Any], metric_name: str) -> Optional[float]:
        """Extract metric value from metrics dict"""
        # Handle nested metric names like "system.memory_percent"
        parts = metric_name.split('.')
        current = metrics
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        try:
            return float(current)
        except (ValueError, TypeError):
            return None
    
    def _evaluate_threshold(self, value: float, threshold: float, comparison: str) -> bool:
        """Evaluate threshold condition"""
        if comparison == ">":
            return value > threshold
        elif comparison == "<":
            return value < threshold
        elif comparison == ">=":
            return value >= threshold
        elif comparison == "<=":
            return value <= threshold
        elif comparison == "==":
            return value == threshold
        elif comparison == "!=":
            return value != threshold
        else:
            return False
    
    async def get_prometheus_metrics(self) -> str:
        """Get Prometheus metrics in text format"""
        return generate_latest()
    
    async def get_active_alerts(self) -> List[PerformanceAlert]:
        """Get currently active performance alerts"""
        return list(self._active_alerts.values())


# Global performance monitor instance
_performance_monitor: Optional[PerformanceMonitor] = None


def get_performance_monitor(
    config: Optional[PerformanceConfig] = None,
    redis_client: Optional[aioredis.Redis] = None
) -> PerformanceMonitor:
    """Get or create global performance monitor"""
    global _performance_monitor
    
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor(config, redis_client)
        logger.info("global_performance_monitor_created")
    
    return _performance_monitor


# Convenience decorators and functions
def track_performance(endpoint: str, method: str = "GET"):
    """Decorator to track function performance"""
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                monitor = get_performance_monitor()
                async with monitor.track_request(endpoint, method):
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                monitor = get_performance_monitor()
                with monitor.track_request(endpoint, method):
                    return func(*args, **kwargs)
            return sync_wrapper
    return decorator


async def initialize_performance_monitoring(
    config: Optional[PerformanceConfig] = None,
    redis_client: Optional[aioredis.Redis] = None
) -> PerformanceMonitor:
    """Initialize and start performance monitoring"""
    monitor = get_performance_monitor(config, redis_client)
    await monitor.start_monitoring()
    
    logger.info("performance_monitoring_initialized")
    return monitor