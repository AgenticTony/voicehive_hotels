"""
Memory Usage and Leak Detection Testing

Tests system memory usage patterns, detects memory leaks, and validates
memory performance under various load conditions.
"""

import pytest
import asyncio
import time
import gc
import sys
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import psutil
import tracemalloc
from memory_profiler import profile
import threading
import queue

from .conftest import LoadTestRunner, LoadTestMetrics, PerformanceMonitor, MemorySnapshot


class MemoryProfiler:
    """Advanced memory profiling utilities"""
    
    def __init__(self):
        self.tracemalloc_started = False
        self.baseline_snapshot = None
        self.snapshots = []
        
    def start_tracing(self):
        """Start memory tracing"""
        if not self.tracemalloc_started:
            tracemalloc.start()
            self.tracemalloc_started = True
            
    def stop_tracing(self):
        """Stop memory tracing"""
        if self.tracemalloc_started:
            tracemalloc.stop()
            self.tracemalloc_started = False
            
    def take_snapshot(self, label: str = "") -> Dict[str, Any]:
        """Take a detailed memory snapshot"""
        if not self.tracemalloc_started:
            self.start_tracing()
            
        # Get tracemalloc snapshot
        snapshot = tracemalloc.take_snapshot()
        
        # Get process memory info
        process = psutil.Process()
        memory_info = process.memory_info()
        
        # Get Python memory info
        memory_usage = {
            'label': label,
            'timestamp': datetime.now(),
            'rss_mb': memory_info.rss / 1024 / 1024,
            'vms_mb': memory_info.vms / 1024 / 1024,
            'percent': process.memory_percent(),
            'python_objects': len(gc.get_objects()),
            'tracemalloc_snapshot': snapshot
        }
        
        self.snapshots.append(memory_usage)
        return memory_usage
        
    def set_baseline(self):
        """Set baseline memory snapshot"""
        self.baseline_snapshot = self.take_snapshot("baseline")
        
    def compare_with_baseline(self, current_snapshot: Optional[Dict] = None) -> Dict[str, Any]:
        """Compare current memory usage with baseline"""
        if not self.baseline_snapshot:
            raise ValueError("No baseline snapshot set")
            
        if current_snapshot is None:
            current_snapshot = self.take_snapshot("current")
            
        comparison = {
            'baseline_rss_mb': self.baseline_snapshot['rss_mb'],
            'current_rss_mb': current_snapshot['rss_mb'],
            'rss_increase_mb': current_snapshot['rss_mb'] - self.baseline_snapshot['rss_mb'],
            'rss_increase_percent': ((current_snapshot['rss_mb'] - self.baseline_snapshot['rss_mb']) / self.baseline_snapshot['rss_mb']) * 100,
            'baseline_objects': self.baseline_snapshot['python_objects'],
            'current_objects': current_snapshot['python_objects'],
            'objects_increase': current_snapshot['python_objects'] - self.baseline_snapshot['python_objects']
        }
        
        return comparison
        
    def detect_memory_leak(self, threshold_mb: float = 50.0, threshold_objects: int = 10000) -> Dict[str, Any]:
        """Detect potential memory leaks"""
        if len(self.snapshots) < 3:
            return {"error": "Need at least 3 snapshots for leak detection"}
            
        # Analyze memory growth trend
        memory_values = [s['rss_mb'] for s in self.snapshots]
        object_counts = [s['python_objects'] for s in self.snapshots]
        
        # Calculate linear regression to detect consistent growth
        n = len(memory_values)
        x_values = list(range(n))
        
        # Memory growth rate
        memory_slope = self._calculate_slope(x_values, memory_values)
        object_slope = self._calculate_slope(x_values, object_counts)
        
        # Total increase from first to last snapshot
        total_memory_increase = memory_values[-1] - memory_values[0]
        total_object_increase = object_counts[-1] - object_counts[0]
        
        leak_detected = (
            memory_slope > 1.0 and total_memory_increase > threshold_mb
        ) or (
            object_slope > 100 and total_object_increase > threshold_objects
        )
        
        return {
            'leak_detected': leak_detected,
            'memory_slope_mb_per_snapshot': memory_slope,
            'object_slope_per_snapshot': object_slope,
            'total_memory_increase_mb': total_memory_increase,
            'total_object_increase': total_object_increase,
            'snapshots_analyzed': n,
            'threshold_mb': threshold_mb,
            'threshold_objects': threshold_objects
        }
        
    def _calculate_slope(self, x_values: List[float], y_values: List[float]) -> float:
        """Calculate linear regression slope"""
        n = len(x_values)
        if n < 2:
            return 0.0
            
        x_mean = sum(x_values) / n
        y_mean = sum(y_values) / n
        
        numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(n))
        denominator = sum((x_values[i] - x_mean) ** 2 for i in range(n))
        
        return numerator / denominator if denominator != 0 else 0.0
        
    def get_top_memory_consumers(self, snapshot_index: int = -1, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top memory consuming code locations"""
        if not self.snapshots or snapshot_index >= len(self.snapshots):
            return []
            
        snapshot = self.snapshots[snapshot_index]['tracemalloc_snapshot']
        top_stats = snapshot.statistics('lineno')
        
        consumers = []
        for stat in top_stats[:limit]:
            consumers.append({
                'filename': stat.traceback.format()[0] if stat.traceback.format() else 'unknown',
                'size_mb': stat.size / 1024 / 1024,
                'count': stat.count
            })
            
        return consumers


class TestMemoryPerformance:
    """Test memory usage and leak detection"""
    
    @pytest.mark.asyncio
    async def test_memory_usage_under_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test memory usage patterns under normal load"""
        
        memory_profiler = MemoryProfiler()
        memory_profiler.start_tracing()
        memory_profiler.set_baseline()
        
        performance_monitor.start_monitoring()
        
        try:
            # Test different types of operations and their memory impact
            test_scenarios = [
                {
                    "name": "lightweight_requests",
                    "endpoint": "/healthz",
                    "method": "GET",
                    "concurrent_users": load_test_config["concurrent_users"],
                    "requests_per_user": load_test_config["requests_per_user"] * 2
                },
                {
                    "name": "data_processing",
                    "endpoint": "/api/v1/reservations/search",
                    "method": "POST",
                    "payload": {
                        "hotel_id": "hotel_123",
                        "date_range": {"start": "2024-02-01", "end": "2024-02-07"},
                        "guest_count": 2
                    },
                    "concurrent_users": load_test_config["concurrent_users"] // 2,
                    "requests_per_user": load_test_config["requests_per_user"]
                },
                {
                    "name": "audio_processing",
                    "endpoint": "/api/v1/tts/synthesize",
                    "method": "POST",
                    "payload": {
                        "text": "This is a test message for memory usage analysis during TTS processing.",
                        "voice": "en-US-Standard-A"
                    },
                    "concurrent_users": load_test_config["concurrent_users"] // 4,
                    "requests_per_user": load_test_config["requests_per_user"] // 2
                }
            ]
            
            scenario_results = []
            
            for scenario in test_scenarios:
                print(f"\nTesting memory usage for: {scenario['name']}")
                
                # Take snapshot before scenario
                memory_profiler.take_snapshot(f"before_{scenario['name']}")
                
                # Run the load test
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint=scenario["endpoint"],
                    method=scenario["method"],
                    payload=scenario.get("payload"),
                    concurrent_users=scenario["concurrent_users"],
                    requests_per_user=scenario["requests_per_user"],
                    delay_between_requests=0.1
                )
                
                # Take snapshot after scenario
                after_snapshot = memory_profiler.take_snapshot(f"after_{scenario['name']}")
                
                # Force garbage collection
                gc.collect()
                
                # Take snapshot after GC
                gc_snapshot = memory_profiler.take_snapshot(f"after_gc_{scenario['name']}")
                
                scenario_results.append({
                    'scenario': scenario['name'],
                    'metrics': metrics,
                    'memory_after': after_snapshot,
                    'memory_after_gc': gc_snapshot
                })
                
                # Validate memory usage
                assert metrics.memory_usage_mb <= load_test_config["memory_threshold_mb"], \
                    f"Memory usage for {scenario['name']} ({metrics.memory_usage_mb:.1f}MB) exceeds threshold"
                
                # Wait a bit between scenarios
                await asyncio.sleep(2)
            
            # Analyze memory usage patterns
            baseline_comparison = memory_profiler.compare_with_baseline()
            
            print(f"\n=== Memory Usage Under Load Test Results ===")
            print(f"Baseline Memory: {baseline_comparison['baseline_rss_mb']:.1f}MB")
            print(f"Final Memory: {baseline_comparison['current_rss_mb']:.1f}MB")
            print(f"Memory Increase: {baseline_comparison['rss_increase_mb']:.1f}MB ({baseline_comparison['rss_increase_percent']:.1f}%)")
            print(f"Object Increase: {baseline_comparison['objects_increase']}")
            
            for result in scenario_results:
                scenario = result['scenario']
                memory_after = result['memory_after']
                memory_after_gc = result['memory_after_gc']
                
                memory_recovered = memory_after['rss_mb'] - memory_after_gc['rss_mb']
                
                print(f"\n{scenario}:")
                print(f"  Peak Memory: {memory_after['rss_mb']:.1f}MB")
                print(f"  After GC: {memory_after_gc['rss_mb']:.1f}MB")
                print(f"  Memory Recovered: {memory_recovered:.1f}MB")
                print(f"  RPS: {result['metrics'].requests_per_second:.1f}")
            
            # Check for excessive memory growth
            assert baseline_comparison['rss_increase_percent'] <= 200, \
                f"Memory increase ({baseline_comparison['rss_increase_percent']:.1f}%) too high"
                
        finally:
            memory_profiler.stop_tracing()
            performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_memory_leak_detection(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test for memory leaks during sustained operations"""
        
        memory_profiler = MemoryProfiler()
        memory_profiler.start_tracing()
        memory_profiler.set_baseline()
        
        performance_monitor.start_monitoring()
        
        try:
            # Run sustained load to detect memory leaks
            leak_test_duration = 60  # 1 minute of sustained load
            snapshot_interval = 10   # Take snapshot every 10 seconds
            
            start_time = time.time()
            snapshot_count = 0
            
            # Continuous load test with periodic snapshots
            while time.time() - start_time < leak_test_duration:
                # Run a batch of requests
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/api/v1/calls",
                    method="POST",
                    payload={
                        "hotel_id": "hotel_123",
                        "room_number": f"10{snapshot_count % 10}",
                        "call_type": "room_service"
                    },
                    concurrent_users=load_test_config["concurrent_users"] // 4,
                    requests_per_user=5,
                    delay_between_requests=0.1
                )
                
                # Take memory snapshot
                snapshot_count += 1
                memory_profiler.take_snapshot(f"leak_test_{snapshot_count}")
                
                # Force garbage collection periodically
                if snapshot_count % 3 == 0:
                    gc.collect()
                
                # Wait for next interval
                await asyncio.sleep(snapshot_interval)
            
            # Analyze for memory leaks
            leak_analysis = memory_profiler.detect_memory_leak(
                threshold_mb=30.0,  # 30MB increase considered a leak
                threshold_objects=5000  # 5000 objects increase considered a leak
            )
            
            # Get top memory consumers
            top_consumers = memory_profiler.get_top_memory_consumers(limit=5)
            
            print(f"\n=== Memory Leak Detection Test Results ===")
            print(f"Test Duration: {leak_test_duration}s")
            print(f"Snapshots Taken: {snapshot_count}")
            print(f"Leak Detected: {leak_analysis['leak_detected']}")
            print(f"Memory Growth Rate: {leak_analysis['memory_slope_mb_per_snapshot']:.2f}MB per snapshot")
            print(f"Object Growth Rate: {leak_analysis['object_slope_per_snapshot']:.0f} objects per snapshot")
            print(f"Total Memory Increase: {leak_analysis['total_memory_increase_mb']:.1f}MB")
            print(f"Total Object Increase: {leak_analysis['total_object_increase']}")
            
            print(f"\nTop Memory Consumers:")
            for i, consumer in enumerate(top_consumers, 1):
                print(f"  {i}. {consumer['filename']}: {consumer['size_mb']:.2f}MB ({consumer['count']} allocations)")
            
            # Assert no significant memory leak
            assert not leak_analysis['leak_detected'], \
                f"Memory leak detected: {leak_analysis}"
                
        finally:
            memory_profiler.stop_tracing()
            performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_connection_pool_memory_usage(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        database_load_tester,
        redis_load_tester,
        load_test_config: Dict[str, Any]
    ):
        """Test memory usage of connection pools under load"""
        
        memory_profiler = MemoryProfiler()
        memory_profiler.start_tracing()
        memory_profiler.set_baseline()
        
        performance_monitor.start_monitoring()
        
        try:
            # Test database connection pool memory usage
            print("Testing database connection pool memory usage...")
            
            memory_profiler.take_snapshot("before_db_pool_test")
            
            # Simulate heavy database usage
            db_results = await database_load_tester.test_connection_pool_performance(
                pool_size=20,
                concurrent_queries=100,
                query_complexity="complex"
            )
            
            memory_profiler.take_snapshot("after_db_pool_test")
            
            # Test Redis connection pool memory usage
            print("Testing Redis connection pool memory usage...")
            
            redis_results = await redis_load_tester.test_redis_performance(
                concurrent_operations=200,
                operation_types=["get", "set", "hget", "hset", "incr", "zadd", "zrange"]
            )
            
            memory_profiler.take_snapshot("after_redis_pool_test")
            
            # Test HTTP connection pool memory usage
            print("Testing HTTP connection pool memory usage...")
            
            http_metrics = await load_test_runner.run_concurrent_requests(
                endpoint="/api/v1/pms/reservation",
                method="POST",
                payload={"reservation_id": "RES123456"},
                concurrent_users=load_test_config["concurrent_users"],
                requests_per_user=load_test_config["requests_per_user"],
                delay_between_requests=0.05
            )
            
            memory_profiler.take_snapshot("after_http_pool_test")
            
            # Force garbage collection
            gc.collect()
            memory_profiler.take_snapshot("after_gc")
            
            # Analyze connection pool memory usage
            baseline_comparison = memory_profiler.compare_with_baseline()
            
            print(f"\n=== Connection Pool Memory Usage Test Results ===")
            print(f"Database Pool Test:")
            print(f"  Queries: {db_results['total_queries']}")
            print(f"  QPS: {db_results['queries_per_second']:.1f}")
            print(f"  Error Rate: {db_results['error_rate']:.2%}")
            
            print(f"Redis Pool Test:")
            print(f"  Operations: {redis_results['total_operations']}")
            print(f"  OPS: {redis_results['operations_per_second']:.1f}")
            print(f"  Error Rate: {redis_results['error_rate']:.2%}")
            
            print(f"HTTP Pool Test:")
            print(f"  Requests: {http_metrics.total_requests}")
            print(f"  RPS: {http_metrics.requests_per_second:.1f}")
            print(f"  Error Rate: {http_metrics.error_rate:.2%}")
            
            print(f"\nMemory Usage:")
            print(f"  Baseline: {baseline_comparison['baseline_rss_mb']:.1f}MB")
            print(f"  Peak: {baseline_comparison['current_rss_mb']:.1f}MB")
            print(f"  Increase: {baseline_comparison['rss_increase_mb']:.1f}MB ({baseline_comparison['rss_increase_percent']:.1f}%)")
            
            # Connection pools should not cause excessive memory usage
            assert baseline_comparison['rss_increase_percent'] <= 150, \
                f"Connection pool memory increase ({baseline_comparison['rss_increase_percent']:.1f}%) too high"
                
        finally:
            memory_profiler.stop_tracing()
            performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_audio_processing_memory_usage(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test memory usage during audio processing operations"""
        
        memory_profiler = MemoryProfiler()
        memory_profiler.start_tracing()
        memory_profiler.set_baseline()
        
        performance_monitor.start_monitoring()
        
        try:
            # Audio processing scenarios with different memory profiles
            audio_scenarios = [
                {
                    "name": "short_tts",
                    "endpoint": "/api/v1/tts/synthesize",
                    "payload": {
                        "text": "Hello, this is a short message.",
                        "voice": "en-US-Standard-A"
                    },
                    "expected_memory_mb": 10
                },
                {
                    "name": "long_tts",
                    "endpoint": "/api/v1/tts/synthesize",
                    "payload": {
                        "text": " ".join(["This is a very long text message for TTS synthesis."] * 20),
                        "voice": "en-US-Standard-A"
                    },
                    "expected_memory_mb": 50
                },
                {
                    "name": "audio_upload",
                    "endpoint": "/api/v1/audio/upload",
                    "payload": {
                        "call_id": "audio_test_001",
                        "audio_format": "wav",
                        "sample_rate": 16000,
                        "duration_ms": 10000  # 10 seconds
                    },
                    "expected_memory_mb": 30
                }
            ]
            
            scenario_results = []
            
            for scenario in audio_scenarios:
                print(f"\nTesting audio memory usage: {scenario['name']}")
                
                # Take snapshot before audio processing
                before_snapshot = memory_profiler.take_snapshot(f"before_{scenario['name']}")
                
                # Run audio processing load test
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint=scenario["endpoint"],
                    method="POST",
                    payload=scenario["payload"],
                    concurrent_users=load_test_config["concurrent_users"] // 4,  # Audio is memory intensive
                    requests_per_user=3,  # Fewer requests for audio
                    delay_between_requests=0.3
                )
                
                # Take snapshot after audio processing
                after_snapshot = memory_profiler.take_snapshot(f"after_{scenario['name']}")
                
                # Force garbage collection to see if memory is properly released
                gc.collect()
                gc_snapshot = memory_profiler.take_snapshot(f"gc_{scenario['name']}")
                
                # Calculate memory usage for this scenario
                memory_increase = after_snapshot['rss_mb'] - before_snapshot['rss_mb']
                memory_recovered = after_snapshot['rss_mb'] - gc_snapshot['rss_mb']
                
                scenario_results.append({
                    'scenario': scenario['name'],
                    'metrics': metrics,
                    'memory_increase_mb': memory_increase,
                    'memory_recovered_mb': memory_recovered,
                    'expected_memory_mb': scenario['expected_memory_mb']
                })
                
                # Validate audio processing doesn't use excessive memory
                assert memory_increase <= scenario['expected_memory_mb'] * 2, \
                    f"Audio processing memory usage for {scenario['name']} ({memory_increase:.1f}MB) exceeds expected ({scenario['expected_memory_mb']}MB)"
                
                # Validate memory is properly released after GC
                memory_retention_rate = (after_snapshot['rss_mb'] - gc_snapshot['rss_mb']) / memory_increase if memory_increase > 0 else 0
                assert memory_retention_rate <= 0.3, \
                    f"Too much memory retained after GC for {scenario['name']}: {memory_retention_rate:.1%}"
                
                # Wait between scenarios
                await asyncio.sleep(2)
            
            # Overall memory analysis
            final_comparison = memory_profiler.compare_with_baseline()
            
            print(f"\n=== Audio Processing Memory Usage Test Results ===")
            for result in scenario_results:
                print(f"{result['scenario']}:")
                print(f"  Memory Increase: {result['memory_increase_mb']:.1f}MB")
                print(f"  Memory Recovered: {result['memory_recovered_mb']:.1f}MB")
                print(f"  Expected: {result['expected_memory_mb']}MB")
                print(f"  RPS: {result['metrics'].requests_per_second:.1f}")
                print(f"  Error Rate: {result['metrics'].error_rate:.2%}")
            
            print(f"\nOverall Memory Impact:")
            print(f"  Final Increase: {final_comparison['rss_increase_mb']:.1f}MB")
            print(f"  Object Increase: {final_comparison['objects_increase']}")
            
            # Audio processing should not cause permanent memory increase
            assert final_comparison['rss_increase_mb'] <= 100, \
                f"Permanent memory increase from audio processing too high: {final_comparison['rss_increase_mb']:.1f}MB"
                
        finally:
            memory_profiler.stop_tracing()
            performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_garbage_collection_performance(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test garbage collection performance under load"""
        
        memory_profiler = MemoryProfiler()
        memory_profiler.start_tracing()
        memory_profiler.set_baseline()
        
        performance_monitor.start_monitoring()
        
        # Track GC statistics
        gc_stats_before = gc.get_stats()
        gc_counts_before = gc.get_count()
        
        try:
            # Run load test that generates many objects
            print("Running object-intensive load test...")
            
            # Create many temporary objects
            object_creation_metrics = await load_test_runner.run_concurrent_requests(
                endpoint="/api/v1/reservations/search",
                method="POST",
                payload={
                    "hotel_id": "hotel_123",
                    "filters": {
                        "date_range": {"start": "2024-01-01", "end": "2024-12-31"},
                        "guest_count": [1, 2, 3, 4],
                        "room_types": ["standard", "deluxe", "suite"],
                        "amenities": ["wifi", "parking", "pool", "gym"]
                    }
                },
                concurrent_users=load_test_config["concurrent_users"],
                requests_per_user=load_test_config["requests_per_user"] * 2,
                delay_between_requests=0.05
            )
            
            memory_profiler.take_snapshot("before_gc")
            
            # Measure GC performance
            gc_start_time = time.time()
            collected = gc.collect()
            gc_duration = time.time() - gc_start_time
            
            memory_profiler.take_snapshot("after_gc")
            
            # Get GC statistics after load test
            gc_stats_after = gc.get_stats()
            gc_counts_after = gc.get_count()
            
            # Calculate GC metrics
            gc_collections = []
            for i in range(len(gc_stats_before)):
                before = gc_stats_before[i]
                after = gc_stats_after[i]
                
                gc_collections.append({
                    'generation': i,
                    'collections_before': before['collections'],
                    'collections_after': after['collections'],
                    'collections_during_test': after['collections'] - before['collections'],
                    'collected_before': before['collected'],
                    'collected_after': after['collected'],
                    'collected_during_test': after['collected'] - before['collected']
                })
            
            # Analyze memory recovery
            snapshots = memory_profiler.snapshots
            before_gc_snapshot = next((s for s in snapshots if s['label'] == 'before_gc'), None)
            after_gc_snapshot = next((s for s in snapshots if s['label'] == 'after_gc'), None)
            
            if before_gc_snapshot and after_gc_snapshot:
                memory_recovered = before_gc_snapshot['rss_mb'] - after_gc_snapshot['rss_mb']
                objects_recovered = before_gc_snapshot['python_objects'] - after_gc_snapshot['python_objects']
            else:
                memory_recovered = 0
                objects_recovered = 0
            
            print(f"\n=== Garbage Collection Performance Test Results ===")
            print(f"Load Test Performance:")
            print(f"  Requests: {object_creation_metrics.total_requests}")
            print(f"  RPS: {object_creation_metrics.requests_per_second:.1f}")
            print(f"  Error Rate: {object_creation_metrics.error_rate:.2%}")
            
            print(f"\nGarbage Collection Performance:")
            print(f"  Manual GC Duration: {gc_duration:.3f}s")
            print(f"  Objects Collected: {collected}")
            print(f"  Memory Recovered: {memory_recovered:.1f}MB")
            print(f"  Python Objects Recovered: {objects_recovered}")
            
            print(f"\nGC Statistics by Generation:")
            for gc_info in gc_collections:
                print(f"  Generation {gc_info['generation']}:")
                print(f"    Collections: {gc_info['collections_during_test']}")
                print(f"    Objects Collected: {gc_info['collected_during_test']}")
            
            # Validate GC performance
            assert gc_duration <= 1.0, \
                f"Manual garbage collection took too long: {gc_duration:.3f}s"
            
            # GC should recover significant memory if objects were created
            if object_creation_metrics.total_requests > 100:
                assert memory_recovered >= 0, \
                    f"Garbage collection should recover some memory"
                    
        finally:
            memory_profiler.stop_tracing()
            performance_monitor.stop_monitoring()