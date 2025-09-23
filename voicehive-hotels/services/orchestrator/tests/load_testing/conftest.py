"""
Load testing configuration and fixtures
"""

import pytest
import asyncio
import os
import psutil
import time
from typing import Dict, Any, List
from unittest.mock import AsyncMock, MagicMock
import httpx
from memory_profiler import profile
import threading
import queue
from dataclasses import dataclass
from datetime import datetime, timedelta

# Import test utilities
from ..integration.conftest import (
    mock_redis, mock_vault_client, jwt_service, 
    test_user_context, test_service_context,
    mock_pms_server, mock_tts_service, mock_livekit_service
)


@dataclass
class LoadTestMetrics:
    """Metrics collected during load testing"""
    start_time: datetime
    end_time: datetime
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_response_time: float
    max_response_time: float
    min_response_time: float
    requests_per_second: float
    memory_usage_mb: float
    cpu_usage_percent: float
    error_rate: float


@dataclass
class MemorySnapshot:
    """Memory usage snapshot"""
    timestamp: datetime
    rss_mb: float  # Resident Set Size
    vms_mb: float  # Virtual Memory Size
    percent: float
    available_mb: float


class PerformanceMonitor:
    """Monitor system performance during load tests"""
    
    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self.monitoring = False
        self.metrics_queue = queue.Queue()
        self.monitor_thread = None
        
    def start_monitoring(self):
        """Start performance monitoring"""
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.start()
        
    def stop_monitoring(self) -> List[MemorySnapshot]:
        """Stop monitoring and return collected metrics"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join()
            
        snapshots = []
        while not self.metrics_queue.empty():
            snapshots.append(self.metrics_queue.get())
        return snapshots
        
    def _monitor_loop(self):
        """Monitor loop running in separate thread"""
        process = psutil.Process()
        
        while self.monitoring:
            try:
                memory_info = process.memory_info()
                memory_percent = process.memory_percent()
                virtual_memory = psutil.virtual_memory()
                
                snapshot = MemorySnapshot(
                    timestamp=datetime.now(),
                    rss_mb=memory_info.rss / 1024 / 1024,
                    vms_mb=memory_info.vms / 1024 / 1024,
                    percent=memory_percent,
                    available_mb=virtual_memory.available / 1024 / 1024
                )
                
                self.metrics_queue.put(snapshot)
                time.sleep(self.interval)
                
            except Exception as e:
                print(f"Error in performance monitoring: {e}")
                break


class LoadTestRunner:
    """Utility class for running load tests"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = None
        
    async def __aenter__(self):
        self.session = httpx.AsyncClient(base_url=self.base_url)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.aclose()
            
    async def run_concurrent_requests(
        self, 
        endpoint: str, 
        method: str = "GET",
        payload: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        concurrent_users: int = 10,
        requests_per_user: int = 10,
        delay_between_requests: float = 0.1
    ) -> LoadTestMetrics:
        """Run concurrent requests and collect metrics"""
        
        start_time = datetime.now()
        results = []
        
        async def user_simulation(user_id: int):
            """Simulate a single user making requests"""
            user_results = []
            
            for i in range(requests_per_user):
                request_start = time.time()
                
                try:
                    if method.upper() == "GET":
                        response = await self.session.get(endpoint, headers=headers)
                    elif method.upper() == "POST":
                        response = await self.session.post(endpoint, json=payload, headers=headers)
                    elif method.upper() == "PUT":
                        response = await self.session.put(endpoint, json=payload, headers=headers)
                    else:
                        raise ValueError(f"Unsupported method: {method}")
                        
                    request_time = time.time() - request_start
                    
                    user_results.append({
                        'user_id': user_id,
                        'request_id': i,
                        'status_code': response.status_code,
                        'response_time': request_time,
                        'success': 200 <= response.status_code < 400
                    })
                    
                except Exception as e:
                    request_time = time.time() - request_start
                    user_results.append({
                        'user_id': user_id,
                        'request_id': i,
                        'status_code': 0,
                        'response_time': request_time,
                        'success': False,
                        'error': str(e)
                    })
                
                if delay_between_requests > 0:
                    await asyncio.sleep(delay_between_requests)
                    
            return user_results
        
        # Run concurrent user simulations
        tasks = [user_simulation(i) for i in range(concurrent_users)]
        user_results = await asyncio.gather(*tasks)
        
        # Flatten results
        for user_result in user_results:
            results.extend(user_result)
            
        end_time = datetime.now()
        
        # Calculate metrics
        total_requests = len(results)
        successful_requests = sum(1 for r in results if r['success'])
        failed_requests = total_requests - successful_requests
        
        response_times = [r['response_time'] for r in results]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        max_response_time = max(response_times) if response_times else 0
        min_response_time = min(response_times) if response_times else 0
        
        duration = (end_time - start_time).total_seconds()
        requests_per_second = total_requests / duration if duration > 0 else 0
        error_rate = failed_requests / total_requests if total_requests > 0 else 0
        
        # Get current memory usage
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_usage_mb = memory_info.rss / 1024 / 1024
        cpu_usage_percent = process.cpu_percent()
        
        return LoadTestMetrics(
            start_time=start_time,
            end_time=end_time,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            avg_response_time=avg_response_time,
            max_response_time=max_response_time,
            min_response_time=min_response_time,
            requests_per_second=requests_per_second,
            memory_usage_mb=memory_usage_mb,
            cpu_usage_percent=cpu_usage_percent,
            error_rate=error_rate
        )


@pytest.fixture
def performance_monitor():
    """Performance monitoring fixture"""
    return PerformanceMonitor()


@pytest.fixture
async def load_test_runner():
    """Load test runner fixture"""
    async with LoadTestRunner() as runner:
        yield runner


@pytest.fixture
def load_test_config():
    """Load test configuration"""
    return {
        "concurrent_users": int(os.getenv("LOAD_TEST_USERS", "10")),
        "requests_per_user": int(os.getenv("LOAD_TEST_REQUESTS", "10")),
        "test_duration": int(os.getenv("LOAD_TEST_DURATION", "60")),
        "ramp_up_time": int(os.getenv("LOAD_TEST_RAMP_UP", "10")),
        "max_response_time": float(os.getenv("LOAD_TEST_MAX_RESPONSE", "2.0")),
        "max_error_rate": float(os.getenv("LOAD_TEST_MAX_ERROR_RATE", "0.05")),
        "memory_threshold_mb": int(os.getenv("LOAD_TEST_MEMORY_THRESHOLD", "500"))
    }


@pytest.fixture
def memory_leak_detector():
    """Memory leak detection utilities"""
    class MemoryLeakDetector:
        def __init__(self):
            self.baseline_memory = None
            self.snapshots = []
            
        def set_baseline(self):
            """Set baseline memory usage"""
            process = psutil.Process()
            self.baseline_memory = process.memory_info().rss / 1024 / 1024
            
        def take_snapshot(self, label: str = ""):
            """Take a memory snapshot"""
            process = psutil.Process()
            current_memory = process.memory_info().rss / 1024 / 1024
            
            snapshot = {
                'label': label,
                'timestamp': datetime.now(),
                'memory_mb': current_memory,
                'delta_from_baseline': current_memory - (self.baseline_memory or 0)
            }
            
            self.snapshots.append(snapshot)
            return snapshot
            
        def detect_leak(self, threshold_mb: float = 50.0) -> bool:
            """Detect if there's a memory leak based on snapshots"""
            if len(self.snapshots) < 2:
                return False
                
            # Check if memory consistently increases
            increasing_count = 0
            for i in range(1, len(self.snapshots)):
                if self.snapshots[i]['memory_mb'] > self.snapshots[i-1]['memory_mb']:
                    increasing_count += 1
                    
            # If memory increases in more than 70% of snapshots and exceeds threshold
            leak_ratio = increasing_count / (len(self.snapshots) - 1)
            final_increase = self.snapshots[-1]['delta_from_baseline']
            
            return leak_ratio > 0.7 and final_increase > threshold_mb
            
        def get_report(self) -> Dict[str, Any]:
            """Get memory usage report"""
            if not self.snapshots:
                return {"error": "No snapshots taken"}
                
            return {
                "baseline_memory_mb": self.baseline_memory,
                "final_memory_mb": self.snapshots[-1]['memory_mb'],
                "max_memory_mb": max(s['memory_mb'] for s in self.snapshots),
                "min_memory_mb": min(s['memory_mb'] for s in self.snapshots),
                "total_increase_mb": self.snapshots[-1]['delta_from_baseline'],
                "snapshots_count": len(self.snapshots),
                "potential_leak": self.detect_leak()
            }
    
    return MemoryLeakDetector()


@pytest.fixture
def network_simulator():
    """Network condition simulator for testing resilience"""
    class NetworkSimulator:
        def __init__(self):
            self.conditions = {
                "normal": {"latency": 0, "packet_loss": 0, "bandwidth": None},
                "slow": {"latency": 500, "packet_loss": 0, "bandwidth": "1mbps"},
                "unreliable": {"latency": 100, "packet_loss": 0.1, "bandwidth": None},
                "partition": {"latency": 0, "packet_loss": 1.0, "bandwidth": None}
            }
            
        async def apply_condition(self, condition: str):
            """Apply network condition (mock implementation)"""
            if condition not in self.conditions:
                raise ValueError(f"Unknown condition: {condition}")
                
            # In a real implementation, this would use tools like tc (traffic control)
            # or toxiproxy to simulate network conditions
            print(f"Applying network condition: {condition}")
            
        async def reset_conditions(self):
            """Reset to normal network conditions"""
            print("Resetting network conditions to normal")
    
    return NetworkSimulator()


@pytest.fixture
def database_load_tester():
    """Database load testing utilities"""
    class DatabaseLoadTester:
        def __init__(self):
            self.connection_pool = None
            
        async def test_connection_pool_performance(
            self, 
            pool_size: int = 10,
            concurrent_queries: int = 50,
            query_complexity: str = "simple"
        ):
            """Test database connection pool under load"""
            
            # Mock implementation - in real scenario would use actual DB
            queries = {
                "simple": "SELECT 1",
                "medium": "SELECT * FROM users WHERE id = $1",
                "complex": """
                    SELECT u.*, COUNT(r.*) as reservation_count 
                    FROM users u 
                    LEFT JOIN reservations r ON u.id = r.user_id 
                    GROUP BY u.id
                """
            }
            
            query = queries.get(query_complexity, queries["simple"])
            
            # Simulate concurrent database operations
            start_time = time.time()
            
            async def execute_query(query_id: int):
                # Simulate query execution time
                await asyncio.sleep(0.01 + (query_id % 3) * 0.01)
                return {"query_id": query_id, "result": "success"}
            
            tasks = [execute_query(i) for i in range(concurrent_queries)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            end_time = time.time()
            
            successful_queries = sum(1 for r in results if isinstance(r, dict))
            failed_queries = len(results) - successful_queries
            
            return {
                "total_queries": len(results),
                "successful_queries": successful_queries,
                "failed_queries": failed_queries,
                "duration": end_time - start_time,
                "queries_per_second": len(results) / (end_time - start_time),
                "error_rate": failed_queries / len(results)
            }
    
    return DatabaseLoadTester()


@pytest.fixture
def redis_load_tester():
    """Redis load testing utilities"""
    class RedisLoadTester:
        def __init__(self):
            self.redis_client = None
            
        async def test_redis_performance(
            self,
            concurrent_operations: int = 100,
            operation_types: List[str] = None
        ):
            """Test Redis performance under load"""
            
            if operation_types is None:
                operation_types = ["get", "set", "hget", "hset", "incr"]
            
            start_time = time.time()
            
            async def redis_operation(op_id: int):
                op_type = operation_types[op_id % len(operation_types)]
                
                # Simulate Redis operations
                await asyncio.sleep(0.001)  # Simulate Redis latency
                
                return {
                    "operation_id": op_id,
                    "operation_type": op_type,
                    "success": True,
                    "response_time": 0.001
                }
            
            tasks = [redis_operation(i) for i in range(concurrent_operations)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            end_time = time.time()
            
            successful_ops = sum(1 for r in results if isinstance(r, dict))
            failed_ops = len(results) - successful_ops
            
            return {
                "total_operations": len(results),
                "successful_operations": successful_ops,
                "failed_operations": failed_ops,
                "duration": end_time - start_time,
                "operations_per_second": len(results) / (end_time - start_time),
                "error_rate": failed_ops / len(results)
            }
    
    return RedisLoadTester()