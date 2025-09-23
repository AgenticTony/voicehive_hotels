"""
Performance Benchmarking and Capacity Planning System for VoiceHive Hotels
Automated performance testing, benchmarking, and capacity planning
"""

import asyncio
import time
import json
import statistics
from typing import Dict, List, Optional, Any, Callable, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import concurrent.futures
import threading
import math

try:
    import numpy as np
except ImportError:
    np = None

try:
    import psutil
except ImportError:
    psutil = None

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

logger = get_safe_logger("orchestrator.performance_benchmarking")

# Prometheus metrics for benchmarking
benchmark_execution_duration = Histogram(
    'voicehive_benchmark_execution_duration_seconds',
    'Benchmark execution duration',
    ['benchmark_type', 'scenario'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0)
)

benchmark_throughput = Gauge(
    'voicehive_benchmark_throughput_ops_per_second',
    'Benchmark throughput in operations per second',
    ['benchmark_type', 'scenario']
)

benchmark_latency_percentiles = Gauge(
    'voicehive_benchmark_latency_percentile_seconds',
    'Benchmark latency percentiles',
    ['benchmark_type', 'scenario', 'percentile']
)

capacity_prediction = Gauge(
    'voicehive_capacity_prediction',
    'Capacity predictions',
    ['metric_type', 'time_horizon']
)

performance_regression_detected = Counter(
    'voicehive_performance_regression_detected_total',
    'Performance regressions detected',
    ['benchmark_type', 'severity']
)


class BenchmarkType(str, Enum):
    """Types of performance benchmarks"""
    LOAD_TEST = "load_test"
    STRESS_TEST = "stress_test"
    ENDURANCE_TEST = "endurance_test"
    SPIKE_TEST = "spike_test"
    VOLUME_TEST = "volume_test"
    BASELINE_TEST = "baseline_test"
    REGRESSION_TEST = "regression_test"


class LoadPattern(str, Enum):
    """Load patterns for testing"""
    CONSTANT = "constant"
    RAMP_UP = "ramp_up"
    RAMP_DOWN = "ramp_down"
    SPIKE = "spike"
    STEP = "step"
    SINE_WAVE = "sine_wave"
    RANDOM = "random"


class PerformanceMetric(str, Enum):
    """Performance metrics to track"""
    RESPONSE_TIME = "response_time"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    DISK_IO = "disk_io"
    NETWORK_IO = "network_io"
    CONCURRENT_USERS = "concurrent_users"


@dataclass
class BenchmarkScenario:
    """Benchmark scenario configuration"""
    name: str
    benchmark_type: BenchmarkType
    load_pattern: LoadPattern
    duration_seconds: int
    max_concurrent_users: int
    ramp_up_duration_seconds: int = 0
    ramp_down_duration_seconds: int = 0
    target_operations_per_second: Optional[int] = None
    
    # Test parameters
    test_endpoints: List[str] = field(default_factory=list)
    test_data: Dict[str, Any] = field(default_factory=dict)
    
    # Success criteria
    max_response_time_ms: float = 5000.0
    max_error_rate_percent: float = 1.0
    min_throughput_ops_per_second: float = 10.0
    
    # Resource limits
    max_cpu_percent: float = 80.0
    max_memory_mb: int = 1024


@dataclass
class BenchmarkResult:
    """Benchmark execution result"""
    scenario_name: str
    benchmark_type: BenchmarkType
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    
    # Performance metrics
    total_operations: int
    successful_operations: int
    failed_operations: int
    throughput_ops_per_second: float
    error_rate_percent: float
    
    # Latency statistics
    response_times_ms: List[float]
    avg_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    p50_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    
    # Resource usage
    avg_cpu_percent: float
    max_cpu_percent: float
    avg_memory_mb: float
    max_memory_mb: float
    
    # Success criteria evaluation
    passed: bool
    failure_reasons: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "benchmark_type": self.benchmark_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration_seconds,
            "total_operations": self.total_operations,
            "successful_operations": self.successful_operations,
            "failed_operations": self.failed_operations,
            "throughput_ops_per_second": self.throughput_ops_per_second,
            "error_rate_percent": self.error_rate_percent,
            "latency_stats": {
                "avg_ms": self.avg_response_time_ms,
                "min_ms": self.min_response_time_ms,
                "max_ms": self.max_response_time_ms,
                "p50_ms": self.p50_response_time_ms,
                "p95_ms": self.p95_response_time_ms,
                "p99_ms": self.p99_response_time_ms
            },
            "resource_usage": {
                "avg_cpu_percent": self.avg_cpu_percent,
                "max_cpu_percent": self.max_cpu_percent,
                "avg_memory_mb": self.avg_memory_mb,
                "max_memory_mb": self.max_memory_mb
            },
            "passed": self.passed,
            "failure_reasons": self.failure_reasons
        }


@dataclass
class CapacityPrediction:
    """Capacity planning prediction"""
    metric_name: str
    current_value: float
    predicted_values: Dict[str, float]  # time_horizon -> predicted_value
    confidence_intervals: Dict[str, Tuple[float, float]]  # time_horizon -> (lower, upper)
    growth_rate_per_day: float
    saturation_point: Optional[float]
    days_to_saturation: Optional[int]
    recommendations: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "current_value": self.current_value,
            "predicted_values": self.predicted_values,
            "confidence_intervals": {
                k: {"lower": v[0], "upper": v[1]} 
                for k, v in self.confidence_intervals.items()
            },
            "growth_rate_per_day": self.growth_rate_per_day,
            "saturation_point": self.saturation_point,
            "days_to_saturation": self.days_to_saturation,
            "recommendations": self.recommendations
        }


class BenchmarkConfig(BaseModel):
    """Configuration for performance benchmarking system"""
    # Execution settings
    enable_benchmarking: bool = Field(True, description="Enable performance benchmarking")
    benchmark_interval_hours: int = Field(24, description="Benchmark execution interval")
    parallel_scenarios: int = Field(3, description="Maximum parallel benchmark scenarios")
    
    # Data retention
    result_retention_days: int = Field(30, description="Benchmark result retention period")
    detailed_metrics_retention_days: int = Field(7, description="Detailed metrics retention")
    
    # Regression detection
    enable_regression_detection: bool = Field(True, description="Enable regression detection")
    regression_threshold_percent: float = Field(20.0, description="Regression detection threshold")
    baseline_comparison_days: int = Field(7, description="Days to look back for baseline")
    
    # Capacity planning
    enable_capacity_planning: bool = Field(True, description="Enable capacity planning")
    capacity_prediction_horizons: List[str] = Field(
        default_factory=lambda: ["7d", "30d", "90d", "365d"]
    )
    capacity_growth_analysis_days: int = Field(30, description="Days of data for growth analysis")
    
    # Alert settings
    enable_performance_alerts: bool = Field(True, description="Enable performance alerts")
    alert_on_regression: bool = Field(True, description="Alert on performance regression")
    alert_on_capacity_threshold: bool = Field(True, description="Alert on capacity thresholds")
    
    # Resource monitoring
    monitor_system_resources: bool = Field(True, description="Monitor system resources during tests")
    resource_sampling_interval_seconds: float = Field(1.0, description="Resource sampling interval")


class LoadGenerator:
    """Load generation for performance testing"""
    
    def __init__(self):
        self.active_workers = 0
        self.stop_event = threading.Event()
        
    async def generate_load(
        self,
        scenario: BenchmarkScenario,
        test_function: Callable,
        progress_callback: Optional[Callable] = None
    ) -> List[Dict[str, Any]]:
        """Generate load according to scenario pattern"""
        results = []
        start_time = time.time()
        
        try:
            if scenario.load_pattern == LoadPattern.CONSTANT:
                results = await self._constant_load(scenario, test_function, progress_callback)
            elif scenario.load_pattern == LoadPattern.RAMP_UP:
                results = await self._ramp_up_load(scenario, test_function, progress_callback)
            elif scenario.load_pattern == LoadPattern.SPIKE:
                results = await self._spike_load(scenario, test_function, progress_callback)
            elif scenario.load_pattern == LoadPattern.STEP:
                results = await self._step_load(scenario, test_function, progress_callback)
            else:
                # Default to constant load
                results = await self._constant_load(scenario, test_function, progress_callback)
        
        except Exception as e:
            logger.error("load_generation_failed", scenario=scenario.name, error=str(e))
            raise
        
        return results
    
    async def _constant_load(
        self,
        scenario: BenchmarkScenario,
        test_function: Callable,
        progress_callback: Optional[Callable]
    ) -> List[Dict[str, Any]]:
        """Generate constant load"""
        results = []
        end_time = time.time() + scenario.duration_seconds
        
        # Create semaphore to limit concurrent operations
        semaphore = asyncio.Semaphore(scenario.max_concurrent_users)
        
        async def worker():
            async with semaphore:
                start = time.time()
                try:
                    result = await test_function()
                    duration = time.time() - start
                    
                    results.append({
                        "timestamp": start,
                        "duration_ms": duration * 1000,
                        "success": True,
                        "result": result
                    })
                except Exception as e:
                    duration = time.time() - start
                    results.append({
                        "timestamp": start,
                        "duration_ms": duration * 1000,
                        "success": False,
                        "error": str(e)
                    })
        
        # Generate load
        tasks = []
        operation_count = 0
        
        while time.time() < end_time and not self.stop_event.is_set():
            # Calculate target operations per second
            if scenario.target_operations_per_second:
                # Wait to maintain target rate
                expected_ops = operation_count + 1
                elapsed = time.time() - (end_time - scenario.duration_seconds)
                target_time = expected_ops / scenario.target_operations_per_second
                
                if elapsed < target_time:
                    await asyncio.sleep(target_time - elapsed)
            
            # Start new operation
            task = asyncio.create_task(worker())
            tasks.append(task)
            operation_count += 1
            
            # Report progress
            if progress_callback and operation_count % 100 == 0:
                progress = (time.time() - (end_time - scenario.duration_seconds)) / scenario.duration_seconds
                await progress_callback(progress, operation_count, len(results))
            
            # Limit concurrent tasks
            if len(tasks) >= scenario.max_concurrent_users * 2:
                # Wait for some tasks to complete
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                tasks = list(pending)
        
        # Wait for remaining tasks
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        return results
    
    async def _ramp_up_load(
        self,
        scenario: BenchmarkScenario,
        test_function: Callable,
        progress_callback: Optional[Callable]
    ) -> List[Dict[str, Any]]:
        """Generate ramping up load"""
        results = []
        start_time = time.time()
        ramp_duration = scenario.ramp_up_duration_seconds or scenario.duration_seconds // 3
        
        # Calculate load progression
        total_duration = scenario.duration_seconds
        steady_duration = total_duration - ramp_duration
        
        current_users = 1
        max_users = scenario.max_concurrent_users
        
        while time.time() - start_time < total_duration:
            elapsed = time.time() - start_time
            
            # Calculate current user count
            if elapsed < ramp_duration:
                # Ramp up phase
                progress = elapsed / ramp_duration
                current_users = int(1 + (max_users - 1) * progress)
            else:
                # Steady state
                current_users = max_users
            
            # Generate load with current user count
            semaphore = asyncio.Semaphore(current_users)
            
            async def worker():
                async with semaphore:
                    start = time.time()
                    try:
                        result = await test_function()
                        duration = time.time() - start
                        
                        results.append({
                            "timestamp": start,
                            "duration_ms": duration * 1000,
                            "success": True,
                            "concurrent_users": current_users,
                            "result": result
                        })
                    except Exception as e:
                        duration = time.time() - start
                        results.append({
                            "timestamp": start,
                            "duration_ms": duration * 1000,
                            "success": False,
                            "concurrent_users": current_users,
                            "error": str(e)
                        })
            
            # Start operations for current second
            tasks = [asyncio.create_task(worker()) for _ in range(current_users)]
            await asyncio.sleep(1.0)  # Wait 1 second
            
            # Report progress
            if progress_callback:
                overall_progress = elapsed / total_duration
                await progress_callback(overall_progress, len(results), current_users)
        
        return results
    
    async def _spike_load(
        self,
        scenario: BenchmarkScenario,
        test_function: Callable,
        progress_callback: Optional[Callable]
    ) -> List[Dict[str, Any]]:
        """Generate spike load pattern"""
        results = []
        
        # Normal load for 70% of time, spike for 30%
        normal_duration = int(scenario.duration_seconds * 0.7)
        spike_duration = scenario.duration_seconds - normal_duration
        
        normal_users = max(1, scenario.max_concurrent_users // 4)
        spike_users = scenario.max_concurrent_users
        
        # Normal load phase
        normal_scenario = BenchmarkScenario(
            name=f"{scenario.name}_normal",
            benchmark_type=scenario.benchmark_type,
            load_pattern=LoadPattern.CONSTANT,
            duration_seconds=normal_duration,
            max_concurrent_users=normal_users
        )
        
        normal_results = await self._constant_load(normal_scenario, test_function, progress_callback)
        results.extend(normal_results)
        
        # Spike phase
        spike_scenario = BenchmarkScenario(
            name=f"{scenario.name}_spike",
            benchmark_type=scenario.benchmark_type,
            load_pattern=LoadPattern.CONSTANT,
            duration_seconds=spike_duration,
            max_concurrent_users=spike_users
        )
        
        spike_results = await self._constant_load(spike_scenario, test_function, progress_callback)
        results.extend(spike_results)
        
        return results
    
    async def _step_load(
        self,
        scenario: BenchmarkScenario,
        test_function: Callable,
        progress_callback: Optional[Callable]
    ) -> List[Dict[str, Any]]:
        """Generate step load pattern"""
        results = []
        
        # Divide duration into 4 steps
        step_duration = scenario.duration_seconds // 4
        max_users = scenario.max_concurrent_users
        
        for step in range(4):
            step_users = int(max_users * (step + 1) / 4)
            
            step_scenario = BenchmarkScenario(
                name=f"{scenario.name}_step_{step + 1}",
                benchmark_type=scenario.benchmark_type,
                load_pattern=LoadPattern.CONSTANT,
                duration_seconds=step_duration,
                max_concurrent_users=step_users
            )
            
            step_results = await self._constant_load(step_scenario, test_function, progress_callback)
            results.extend(step_results)
        
        return results
    
    def stop(self):
        """Stop load generation"""
        self.stop_event.set()


class ResourceMonitor:
    """System resource monitoring during benchmarks"""
    
    def __init__(self):
        self.monitoring = False
        self.samples = []
        
    async def start_monitoring(self, interval_seconds: float = 1.0):
        """Start resource monitoring"""
        self.monitoring = True
        self.samples = []
        
        while self.monitoring:
            try:
                sample = await self._take_sample()
                self.samples.append(sample)
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error("resource_monitoring_error", error=str(e))
                break
    
    def stop_monitoring(self):
        """Stop resource monitoring"""
        self.monitoring = False
    
    async def _take_sample(self) -> Dict[str, Any]:
        """Take a resource usage sample"""
        sample = {
            "timestamp": time.time(),
            "cpu_percent": 0.0,
            "memory_mb": 0.0,
            "disk_io_read_mb": 0.0,
            "disk_io_write_mb": 0.0,
            "network_io_sent_mb": 0.0,
            "network_io_recv_mb": 0.0
        }
        
        if psutil:
            try:
                # CPU usage
                sample["cpu_percent"] = psutil.cpu_percent(interval=None)
                
                # Memory usage
                memory = psutil.virtual_memory()
                sample["memory_mb"] = memory.used / (1024 * 1024)
                
                # Disk I/O
                disk_io = psutil.disk_io_counters()
                if disk_io:
                    sample["disk_io_read_mb"] = disk_io.read_bytes / (1024 * 1024)
                    sample["disk_io_write_mb"] = disk_io.write_bytes / (1024 * 1024)
                
                # Network I/O
                network_io = psutil.net_io_counters()
                if network_io:
                    sample["network_io_sent_mb"] = network_io.bytes_sent / (1024 * 1024)
                    sample["network_io_recv_mb"] = network_io.bytes_recv / (1024 * 1024)
            
            except Exception as e:
                logger.warning("resource_sample_failed", error=str(e))
        
        return sample
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get resource usage statistics"""
        if not self.samples:
            return {}
        
        stats = {}
        
        for metric in ["cpu_percent", "memory_mb"]:
            values = [sample[metric] for sample in self.samples]
            if values:
                stats[metric] = {
                    "avg": statistics.mean(values),
                    "min": min(values),
                    "max": max(values),
                    "p95": np.percentile(values, 95) if np else sorted(values)[int(len(values) * 0.95)]
                }
        
        return stats


class CapacityPlanner:
    """Capacity planning and prediction system"""
    
    def __init__(self):
        self.historical_data: Dict[str, List[Tuple[datetime, float]]] = {}
        
    def add_data_point(self, metric_name: str, timestamp: datetime, value: float):
        """Add a data point for capacity planning"""
        if metric_name not in self.historical_data:
            self.historical_data[metric_name] = []
        
        self.historical_data[metric_name].append((timestamp, value))
        
        # Keep only recent data (last 90 days)
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=90)
        self.historical_data[metric_name] = [
            (ts, val) for ts, val in self.historical_data[metric_name]
            if ts > cutoff_time
        ]
    
    def predict_capacity(
        self,
        metric_name: str,
        horizons: List[str] = None,
        saturation_threshold: Optional[float] = None
    ) -> Optional[CapacityPrediction]:
        """Predict capacity requirements"""
        if metric_name not in self.historical_data:
            return None
        
        data_points = self.historical_data[metric_name]
        if len(data_points) < 7:  # Need at least a week of data
            return None
        
        horizons = horizons or ["7d", "30d", "90d", "365d"]
        
        try:
            # Extract time series data
            timestamps = [ts for ts, _ in data_points]
            values = [val for _, val in data_points]
            
            # Convert timestamps to days since first measurement
            first_time = timestamps[0]
            days = [(ts - first_time).total_seconds() / 86400 for ts in timestamps]
            
            # Calculate growth rate using linear regression
            if np:
                # Use numpy for better accuracy
                coeffs = np.polyfit(days, values, 1)
                growth_rate_per_day = coeffs[0]
                intercept = coeffs[1]
            else:
                # Simple linear regression
                n = len(days)
                sum_x = sum(days)
                sum_y = sum(values)
                sum_xy = sum(x * y for x, y in zip(days, values))
                sum_x2 = sum(x * x for x in days)
                
                growth_rate_per_day = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
                intercept = (sum_y - growth_rate_per_day * sum_x) / n
            
            current_value = values[-1]
            current_day = days[-1]
            
            # Make predictions
            predicted_values = {}
            confidence_intervals = {}
            
            for horizon in horizons:
                # Parse horizon (e.g., "30d" -> 30 days)
                if horizon.endswith('d'):
                    horizon_days = int(horizon[:-1])
                else:
                    continue
                
                future_day = current_day + horizon_days
                predicted_value = intercept + growth_rate_per_day * future_day
                
                predicted_values[horizon] = max(0, predicted_value)
                
                # Simple confidence interval (±20% for now)
                margin = predicted_value * 0.2
                confidence_intervals[horizon] = (
                    max(0, predicted_value - margin),
                    predicted_value + margin
                )
            
            # Calculate days to saturation
            days_to_saturation = None
            if saturation_threshold and growth_rate_per_day > 0:
                days_needed = (saturation_threshold - current_value) / growth_rate_per_day
                if days_needed > 0:
                    days_to_saturation = int(days_needed)
            
            # Generate recommendations
            recommendations = self._generate_capacity_recommendations(
                metric_name, growth_rate_per_day, days_to_saturation, predicted_values
            )
            
            return CapacityPrediction(
                metric_name=metric_name,
                current_value=current_value,
                predicted_values=predicted_values,
                confidence_intervals=confidence_intervals,
                growth_rate_per_day=growth_rate_per_day,
                saturation_point=saturation_threshold,
                days_to_saturation=days_to_saturation,
                recommendations=recommendations
            )
        
        except Exception as e:
            logger.error("capacity_prediction_failed", metric=metric_name, error=str(e))
            return None
    
    def _generate_capacity_recommendations(
        self,
        metric_name: str,
        growth_rate: float,
        days_to_saturation: Optional[int],
        predictions: Dict[str, float]
    ) -> List[str]:
        """Generate capacity planning recommendations"""
        recommendations = []
        
        if growth_rate > 0:
            if days_to_saturation and days_to_saturation < 30:
                recommendations.append(
                    f"URGENT: {metric_name} will reach capacity in {days_to_saturation} days"
                )
            elif days_to_saturation and days_to_saturation < 90:
                recommendations.append(
                    f"WARNING: {metric_name} will reach capacity in {days_to_saturation} days"
                )
            
            # Check 30-day prediction
            if "30d" in predictions:
                growth_30d = predictions["30d"] - predictions.get("0d", 0)
                if growth_30d > 0:
                    recommendations.append(
                        f"Expected {metric_name} growth: {growth_30d:.1f} units in 30 days"
                    )
            
            # Scaling recommendations
            if "cpu" in metric_name.lower():
                recommendations.append("Consider horizontal scaling or CPU optimization")
            elif "memory" in metric_name.lower():
                recommendations.append("Consider memory optimization or vertical scaling")
            elif "disk" in metric_name.lower():
                recommendations.append("Consider storage expansion or data archiving")
            elif "network" in metric_name.lower():
                recommendations.append("Consider network capacity expansion")
        
        return recommendations


class PerformanceBenchmarkingSystem:
    """Main performance benchmarking and capacity planning system"""
    
    def __init__(self, config: Optional[BenchmarkConfig] = None):
        self.config = config or BenchmarkConfig()
        self.load_generator = LoadGenerator()
        self.resource_monitor = ResourceMonitor()
        self.capacity_planner = CapacityPlanner()
        
        # Benchmark management
        self.scenarios: List[BenchmarkScenario] = []
        self.results: List[BenchmarkResult] = []
        self.baseline_results: Dict[str, BenchmarkResult] = {}
        
        # Background tasks
        self.benchmark_tasks: List[asyncio.Task] = []
        
        # Statistics
        self.stats = {
            'benchmarks_executed': 0,
            'regressions_detected': 0,
            'capacity_predictions_generated': 0
        }
        
        self._initialize_default_scenarios()
    
    def _initialize_default_scenarios(self):
        """Initialize default benchmark scenarios"""
        # API endpoint load test
        self.scenarios.append(BenchmarkScenario(
            name="api_load_test",
            benchmark_type=BenchmarkType.LOAD_TEST,
            load_pattern=LoadPattern.RAMP_UP,
            duration_seconds=300,  # 5 minutes
            max_concurrent_users=50,
            ramp_up_duration_seconds=60,
            test_endpoints=["/health", "/api/v1/calls", "/api/v1/hotels"],
            max_response_time_ms=2000.0,
            max_error_rate_percent=2.0,
            min_throughput_ops_per_second=20.0
        ))
        
        # Database stress test
        self.scenarios.append(BenchmarkScenario(
            name="database_stress_test",
            benchmark_type=BenchmarkType.STRESS_TEST,
            load_pattern=LoadPattern.CONSTANT,
            duration_seconds=600,  # 10 minutes
            max_concurrent_users=100,
            max_response_time_ms=5000.0,
            max_error_rate_percent=1.0
        ))
        
        # Memory endurance test
        self.scenarios.append(BenchmarkScenario(
            name="memory_endurance_test",
            benchmark_type=BenchmarkType.ENDURANCE_TEST,
            load_pattern=LoadPattern.CONSTANT,
            duration_seconds=3600,  # 1 hour
            max_concurrent_users=20,
            max_memory_mb=2048
        ))
    
    async def start(self):
        """Start the benchmarking system"""
        logger.info("starting_performance_benchmarking_system")
        
        # Start periodic benchmarking
        if self.config.enable_benchmarking:
            task = asyncio.create_task(self._benchmark_loop())
            self.benchmark_tasks.append(task)
        
        # Start capacity planning
        if self.config.enable_capacity_planning:
            task = asyncio.create_task(self._capacity_planning_loop())
            self.benchmark_tasks.append(task)
        
        logger.info("performance_benchmarking_system_started",
                   tasks=len(self.benchmark_tasks))
    
    async def stop(self):
        """Stop the benchmarking system"""
        logger.info("stopping_performance_benchmarking_system")
        
        # Stop load generation
        self.load_generator.stop()
        
        # Cancel benchmark tasks
        for task in self.benchmark_tasks:
            task.cancel()
        
        if self.benchmark_tasks:
            await asyncio.gather(*self.benchmark_tasks, return_exceptions=True)
        
        self.benchmark_tasks.clear()
        logger.info("performance_benchmarking_system_stopped")
    
    def add_scenario(self, scenario: BenchmarkScenario):
        """Add a benchmark scenario"""
        self.scenarios.append(scenario)
        logger.info("benchmark_scenario_added", name=scenario.name)
    
    async def execute_benchmark(
        self,
        scenario: BenchmarkScenario,
        test_function: Callable
    ) -> BenchmarkResult:
        """Execute a single benchmark scenario"""
        logger.info("executing_benchmark", scenario=scenario.name)
        
        start_time = datetime.now(timezone.utc)
        
        # Start resource monitoring
        monitor_task = None
        if self.config.monitor_system_resources:
            monitor_task = asyncio.create_task(
                self.resource_monitor.start_monitoring(
                    self.config.resource_sampling_interval_seconds
                )
            )
        
        try:
            # Generate load
            operation_results = await self.load_generator.generate_load(
                scenario, test_function
            )
            
            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()
            
            # Stop resource monitoring
            if monitor_task:
                self.resource_monitor.stop_monitoring()
                await monitor_task
            
            # Analyze results
            result = self._analyze_benchmark_results(
                scenario, operation_results, start_time, end_time, duration
            )
            
            # Store result
            self.results.append(result)
            self.stats['benchmarks_executed'] += 1
            
            # Update metrics
            benchmark_execution_duration.labels(
                benchmark_type=scenario.benchmark_type,
                scenario=scenario.name
            ).observe(duration)
            
            benchmark_throughput.labels(
                benchmark_type=scenario.benchmark_type,
                scenario=scenario.name
            ).set(result.throughput_ops_per_second)
            
            # Update latency percentile metrics
            for percentile, value in [
                ("50", result.p50_response_time_ms / 1000),
                ("95", result.p95_response_time_ms / 1000),
                ("99", result.p99_response_time_ms / 1000)
            ]:
                benchmark_latency_percentiles.labels(
                    benchmark_type=scenario.benchmark_type,
                    scenario=scenario.name,
                    percentile=percentile
                ).set(value)
            
            # Check for regressions
            if self.config.enable_regression_detection:
                await self._check_for_regression(result)
            
            logger.info("benchmark_completed",
                       scenario=scenario.name,
                       duration=duration,
                       throughput=result.throughput_ops_per_second,
                       passed=result.passed)
            
            return result
        
        except Exception as e:
            # Stop resource monitoring on error
            if monitor_task:
                self.resource_monitor.stop_monitoring()
                monitor_task.cancel()
            
            logger.error("benchmark_execution_failed", 
                        scenario=scenario.name, error=str(e))
            raise
    
    def _analyze_benchmark_results(
        self,
        scenario: BenchmarkScenario,
        operation_results: List[Dict[str, Any]],
        start_time: datetime,
        end_time: datetime,
        duration: float
    ) -> BenchmarkResult:
        """Analyze benchmark operation results"""
        
        # Basic statistics
        total_operations = len(operation_results)
        successful_operations = len([r for r in operation_results if r.get('success', False)])
        failed_operations = total_operations - successful_operations
        
        throughput = successful_operations / duration if duration > 0 else 0
        error_rate = (failed_operations / total_operations * 100) if total_operations > 0 else 0
        
        # Response time analysis
        response_times = [r['duration_ms'] for r in operation_results if 'duration_ms' in r]
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            
            # Calculate percentiles
            sorted_times = sorted(response_times)
            p50 = sorted_times[int(len(sorted_times) * 0.5)]
            p95 = sorted_times[int(len(sorted_times) * 0.95)]
            p99 = sorted_times[int(len(sorted_times) * 0.99)]
        else:
            avg_response_time = min_response_time = max_response_time = 0
            p50 = p95 = p99 = 0
        
        # Resource usage analysis
        resource_stats = self.resource_monitor.get_statistics()
        avg_cpu = resource_stats.get('cpu_percent', {}).get('avg', 0)
        max_cpu = resource_stats.get('cpu_percent', {}).get('max', 0)
        avg_memory = resource_stats.get('memory_mb', {}).get('avg', 0)
        max_memory = resource_stats.get('memory_mb', {}).get('max', 0)
        
        # Evaluate success criteria
        passed = True
        failure_reasons = []
        
        if avg_response_time > scenario.max_response_time_ms:
            passed = False
            failure_reasons.append(
                f"Average response time ({avg_response_time:.1f}ms) exceeds limit ({scenario.max_response_time_ms}ms)"
            )
        
        if error_rate > scenario.max_error_rate_percent:
            passed = False
            failure_reasons.append(
                f"Error rate ({error_rate:.1f}%) exceeds limit ({scenario.max_error_rate_percent}%)"
            )
        
        if throughput < scenario.min_throughput_ops_per_second:
            passed = False
            failure_reasons.append(
                f"Throughput ({throughput:.1f} ops/s) below minimum ({scenario.min_throughput_ops_per_second} ops/s)"
            )
        
        if max_cpu > scenario.max_cpu_percent:
            passed = False
            failure_reasons.append(
                f"CPU usage ({max_cpu:.1f}%) exceeds limit ({scenario.max_cpu_percent}%)"
            )
        
        if max_memory > scenario.max_memory_mb:
            passed = False
            failure_reasons.append(
                f"Memory usage ({max_memory:.1f}MB) exceeds limit ({scenario.max_memory_mb}MB)"
            )
        
        return BenchmarkResult(
            scenario_name=scenario.name,
            benchmark_type=scenario.benchmark_type,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            total_operations=total_operations,
            successful_operations=successful_operations,
            failed_operations=failed_operations,
            throughput_ops_per_second=throughput,
            error_rate_percent=error_rate,
            response_times_ms=response_times,
            avg_response_time_ms=avg_response_time,
            min_response_time_ms=min_response_time,
            max_response_time_ms=max_response_time,
            p50_response_time_ms=p50,
            p95_response_time_ms=p95,
            p99_response_time_ms=p99,
            avg_cpu_percent=avg_cpu,
            max_cpu_percent=max_cpu,
            avg_memory_mb=avg_memory,
            max_memory_mb=max_memory,
            passed=passed,
            failure_reasons=failure_reasons
        )
    
    async def _check_for_regression(self, result: BenchmarkResult):
        """Check for performance regression"""
        scenario_name = result.scenario_name
        
        # Find baseline result
        baseline = self.baseline_results.get(scenario_name)
        if not baseline:
            # Look for recent results to use as baseline
            recent_results = [
                r for r in self.results[-10:]  # Last 10 results
                if r.scenario_name == scenario_name and r.passed
            ]
            
            if recent_results:
                baseline = recent_results[0]
                self.baseline_results[scenario_name] = baseline
            else:
                # No baseline available
                return
        
        # Compare key metrics
        regression_detected = False
        regression_details = []
        
        # Response time regression
        response_time_increase = (
            (result.avg_response_time_ms - baseline.avg_response_time_ms) / 
            baseline.avg_response_time_ms * 100
        )
        
        if response_time_increase > self.config.regression_threshold_percent:
            regression_detected = True
            regression_details.append(
                f"Response time increased by {response_time_increase:.1f}%"
            )
        
        # Throughput regression
        throughput_decrease = (
            (baseline.throughput_ops_per_second - result.throughput_ops_per_second) / 
            baseline.throughput_ops_per_second * 100
        )
        
        if throughput_decrease > self.config.regression_threshold_percent:
            regression_detected = True
            regression_details.append(
                f"Throughput decreased by {throughput_decrease:.1f}%"
            )
        
        # Error rate regression
        error_rate_increase = result.error_rate_percent - baseline.error_rate_percent
        
        if error_rate_increase > 1.0:  # More than 1% increase in error rate
            regression_detected = True
            regression_details.append(
                f"Error rate increased by {error_rate_increase:.1f}%"
            )
        
        if regression_detected:
            self.stats['regressions_detected'] += 1
            
            # Update metrics
            severity = "high" if response_time_increase > 50 or throughput_decrease > 50 else "medium"
            performance_regression_detected.labels(
                benchmark_type=result.benchmark_type,
                severity=severity
            ).inc()
            
            logger.warning("performance_regression_detected",
                          scenario=scenario_name,
                          details=regression_details,
                          baseline_time=baseline.start_time.isoformat(),
                          current_time=result.start_time.isoformat())
    
    async def _benchmark_loop(self):
        """Periodic benchmark execution loop"""
        while True:
            try:
                await asyncio.sleep(self.config.benchmark_interval_hours * 3600)
                
                logger.info("starting_scheduled_benchmarks")
                
                # Execute scenarios in parallel (limited)
                semaphore = asyncio.Semaphore(self.config.parallel_scenarios)
                
                async def execute_scenario(scenario):
                    async with semaphore:
                        # Create a simple test function for the scenario
                        async def test_function():
                            # Simulate API call
                            await asyncio.sleep(0.1)  # 100ms simulated operation
                            return {"status": "success"}
                        
                        try:
                            await self.execute_benchmark(scenario, test_function)
                        except Exception as e:
                            logger.error("scheduled_benchmark_failed",
                                       scenario=scenario.name, error=str(e))
                
                # Execute all scenarios
                tasks = [execute_scenario(scenario) for scenario in self.scenarios]
                await asyncio.gather(*tasks, return_exceptions=True)
                
                logger.info("scheduled_benchmarks_completed")
                
            except Exception as e:
                logger.error("benchmark_loop_error", error=str(e))
    
    async def _capacity_planning_loop(self):
        """Capacity planning analysis loop"""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                
                # Generate capacity predictions for key metrics
                metrics_to_predict = [
                    "cpu_usage_percent",
                    "memory_usage_mb",
                    "disk_usage_gb",
                    "network_throughput_mbps",
                    "concurrent_users",
                    "requests_per_second"
                ]
                
                for metric in metrics_to_predict:
                    prediction = self.capacity_planner.predict_capacity(
                        metric,
                        self.config.capacity_prediction_horizons,
                        saturation_threshold=self._get_saturation_threshold(metric)
                    )
                    
                    if prediction:
                        self.stats['capacity_predictions_generated'] += 1
                        
                        # Update metrics
                        for horizon, value in prediction.predicted_values.items():
                            capacity_prediction.labels(
                                metric_type=metric,
                                time_horizon=horizon
                            ).set(value)
                        
                        # Log important predictions
                        if prediction.days_to_saturation and prediction.days_to_saturation < 30:
                            logger.warning("capacity_saturation_warning",
                                         metric=metric,
                                         days_to_saturation=prediction.days_to_saturation,
                                         recommendations=prediction.recommendations)
                
            except Exception as e:
                logger.error("capacity_planning_loop_error", error=str(e))
    
    def _get_saturation_threshold(self, metric: str) -> Optional[float]:
        """Get saturation threshold for a metric"""
        thresholds = {
            "cpu_usage_percent": 80.0,
            "memory_usage_mb": 8192.0,  # 8GB
            "disk_usage_gb": 100.0,     # 100GB
            "network_throughput_mbps": 1000.0,  # 1Gbps
            "concurrent_users": 1000,
            "requests_per_second": 10000
        }
        
        return thresholds.get(metric)
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report"""
        recent_results = self.results[-10:] if self.results else []
        
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_benchmarks": len(self.results),
                "recent_benchmarks": len(recent_results),
                "scenarios_configured": len(self.scenarios),
                "regressions_detected": self.stats['regressions_detected'],
                "capacity_predictions": self.stats['capacity_predictions_generated']
            },
            "recent_results": [result.to_dict() for result in recent_results],
            "baseline_performance": {
                name: result.to_dict() 
                for name, result in self.baseline_results.items()
            },
            "capacity_predictions": {},
            "performance_trends": self._analyze_performance_trends()
        }
        
        # Add capacity predictions
        for metric in ["cpu_usage_percent", "memory_usage_mb", "requests_per_second"]:
            prediction = self.capacity_planner.predict_capacity(metric)
            if prediction:
                report["capacity_predictions"][metric] = prediction.to_dict()
        
        return report
    
    def _analyze_performance_trends(self) -> Dict[str, Any]:
        """Analyze performance trends across recent benchmarks"""
        if len(self.results) < 5:
            return {"insufficient_data": True}
        
        recent_results = self.results[-20:]  # Last 20 results
        trends = {}
        
        # Group by scenario
        by_scenario = {}
        for result in recent_results:
            if result.scenario_name not in by_scenario:
                by_scenario[result.scenario_name] = []
            by_scenario[result.scenario_name].append(result)
        
        # Analyze trends for each scenario
        for scenario_name, results in by_scenario.items():
            if len(results) < 3:
                continue
            
            # Sort by time
            results.sort(key=lambda r: r.start_time)
            
            # Calculate trends
            response_times = [r.avg_response_time_ms for r in results]
            throughputs = [r.throughput_ops_per_second for r in results]
            error_rates = [r.error_rate_percent for r in results]
            
            trends[scenario_name] = {
                "response_time_trend": self._calculate_trend(response_times),
                "throughput_trend": self._calculate_trend(throughputs),
                "error_rate_trend": self._calculate_trend(error_rates),
                "recent_performance": {
                    "avg_response_time_ms": statistics.mean(response_times[-3:]),
                    "avg_throughput_ops_per_second": statistics.mean(throughputs[-3:]),
                    "avg_error_rate_percent": statistics.mean(error_rates[-3:])
                }
            }
        
        return trends
    
    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate trend direction from a list of values"""
        if len(values) < 2:
            return "stable"
        
        # Simple trend calculation
        first_half = values[:len(values)//2]
        second_half = values[len(values)//2:]
        
        first_avg = statistics.mean(first_half)
        second_avg = statistics.mean(second_half)
        
        change_percent = (second_avg - first_avg) / first_avg * 100 if first_avg > 0 else 0
        
        if change_percent > 10:
            return "increasing"
        elif change_percent < -10:
            return "decreasing"
        else:
            return "stable"