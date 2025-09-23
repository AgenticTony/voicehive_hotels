#!/usr/bin/env python3
"""
Load Testing Validation Framework

Comprehensive load testing validation for production readiness.
Validates system performance under production traffic patterns.
"""

import asyncio
import json
import logging
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import aiohttp
import psutil
import concurrent.futures

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LoadTestStatus(Enum):
    """Load test status enumeration"""
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


@dataclass
class LoadTestMetrics:
    """Load test performance metrics"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    average_response_time: float
    median_response_time: float
    p95_response_time: float
    p99_response_time: float
    min_response_time: float
    max_response_time: float
    requests_per_second: float
    error_rate: float
    throughput_mb_per_sec: float


@dataclass
class LoadTestResult:
    """Individual load test result"""
    test_name: str
    category: str
    status: LoadTestStatus
    message: str
    metrics: Optional[LoadTestMetrics] = None
    details: Optional[Dict[str, Any]] = None
    duration: Optional[float] = None
    timestamp: Optional[str] = None


@dataclass
class LoadTestReport:
    """Complete load testing report"""
    overall_status: LoadTestStatus
    total_tests: int
    passed_tests: int
    failed_tests: int
    warning_tests: int
    skipped_tests: int
    execution_time: float
    timestamp: str
    results: List[LoadTestResult]
    system_metrics: Dict[str, Any]
    recommendations: List[str]


class LoadTestingValidator:
    """
    Comprehensive load testing validation framework
    
    Tests include:
    - Baseline performance testing
    - Concurrent user simulation
    - Stress testing under high load
    - Spike testing for traffic bursts
    - Endurance testing for sustained load
    - Resource utilization monitoring
    - Database performance under load
    - API endpoint performance
    - Authentication system load testing
    - Rate limiting effectiveness
    """
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[LoadTestResult] = []
        self.start_time = datetime.utcnow()
        self.system_metrics = {}
        
    async def run_comprehensive_load_tests(self) -> LoadTestReport:
        """Run complete load testing validation suite"""
        logger.info("Starting comprehensive load testing validation")
        
        # Start system monitoring
        monitor_task = asyncio.create_task(self._monitor_system_resources())
        
        try:
            # Run all load test categories
            await asyncio.gather(
                self._test_baseline_performance(),
                self._test_concurrent_users(),
                self._test_stress_limits(),
                self._test_spike_handling(),
                self._test_endurance_performance(),
                self._test_database_load(),
                self._test_api_performance(),
                self._test_authentication_load(),
                self._test_rate_limiting_load(),
                return_exceptions=True
            )
            
        finally:
            # Stop system monitoring
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        
        # Generate comprehensive report
        return self._generate_load_test_report()
    
    async def _monitor_system_resources(self) -> None:
        """Monitor system resources during load testing"""
        cpu_samples = []
        memory_samples = []
        disk_samples = []
        network_samples = []
        
        try:
            while True:
                # Collect system metrics
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage('/')
                network = psutil.net_io_counters()
                
                cpu_samples.append(cpu_percent)
                memory_samples.append(memory.percent)
                disk_samples.append(disk.percent)
                network_samples.append({
                    'bytes_sent': network.bytes_sent,
                    'bytes_recv': network.bytes_recv
                })
                
                await asyncio.sleep(5)  # Sample every 5 seconds
                
        except asyncio.CancelledError:
            # Calculate final metrics
            self.system_metrics = {
                'cpu': {
                    'average': statistics.mean(cpu_samples) if cpu_samples else 0,
                    'max': max(cpu_samples) if cpu_samples else 0,
                    'samples': len(cpu_samples)
                },
                'memory': {
                    'average': statistics.mean(memory_samples) if memory_samples else 0,
                    'max': max(memory_samples) if memory_samples else 0,
                    'samples': len(memory_samples)
                },
                'disk': {
                    'average': statistics.mean(disk_samples) if disk_samples else 0,
                    'max': max(disk_samples) if disk_samples else 0,
                    'samples': len(disk_samples)
                },
                'network': {
                    'total_samples': len(network_samples)
                }
            }
    
    async def _test_baseline_performance(self) -> None:
        """Test baseline performance with single user"""
        logger.info("Testing baseline performance")
        
        test_start = time.time()
        response_times = []
        successful_requests = 0
        failed_requests = 0
        
        # Test basic endpoints
        endpoints = [
            "/health",
            "/api/health",
            "/api/hotels",
            "/api/calls/status"
        ]
        
        async with aiohttp.ClientSession() as session:
            for endpoint in endpoints:
                for _ in range(10):  # 10 requests per endpoint
                    start_time = time.time()
                    try:
                        async with session.get(
                            f"{self.base_url}{endpoint}",
                            timeout=30
                        ) as response:
                            end_time = time.time()
                            response_time = (end_time - start_time) * 1000  # ms
                            response_times.append(response_time)
                            
                            if response.status < 400:
                                successful_requests += 1
                            else:
                                failed_requests += 1
                                
                    except Exception as e:
                        failed_requests += 1
                        logger.warning(f"Request failed: {str(e)}")
        
        test_duration = time.time() - test_start
        
        if response_times:
            metrics = LoadTestMetrics(
                total_requests=len(response_times) + failed_requests,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                average_response_time=statistics.mean(response_times),
                median_response_time=statistics.median(response_times),
                p95_response_time=self._percentile(response_times, 95),
                p99_response_time=self._percentile(response_times, 99),
                min_response_time=min(response_times),
                max_response_time=max(response_times),
                requests_per_second=(successful_requests + failed_requests) / test_duration,
                error_rate=(failed_requests / (successful_requests + failed_requests)) * 100,
                throughput_mb_per_sec=0  # Would need response size calculation
            )
            
            # Determine status based on performance
            if metrics.average_response_time > 1000:  # > 1 second
                status = LoadTestStatus.FAILED
                message = f"Baseline performance poor: {metrics.average_response_time:.2f}ms average"
            elif metrics.average_response_time > 500:  # > 500ms
                status = LoadTestStatus.WARNING
                message = f"Baseline performance acceptable: {metrics.average_response_time:.2f}ms average"
            else:
                status = LoadTestStatus.PASSED
                message = f"Baseline performance good: {metrics.average_response_time:.2f}ms average"
            
            self.results.append(LoadTestResult(
                test_name="Baseline Performance",
                category="Performance",
                status=status,
                message=message,
                metrics=metrics,
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(LoadTestResult(
                test_name="Baseline Performance",
                category="Performance",
                status=LoadTestStatus.FAILED,
                message="No successful requests completed",
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_concurrent_users(self) -> None:
        """Test performance with concurrent users"""
        logger.info("Testing concurrent user performance")
        
        concurrent_levels = [10, 25, 50, 100]
        
        for concurrent_users in concurrent_levels:
            await self._run_concurrent_test(
                f"Concurrent Users ({concurrent_users})",
                concurrent_users,
                duration=30,  # 30 seconds
                endpoint="/api/health"
            )
    
    async def _run_concurrent_test(
        self, 
        test_name: str, 
        concurrent_users: int, 
        duration: int, 
        endpoint: str
    ) -> None:
        """Run a concurrent user test"""
        test_start = time.time()
        response_times = []
        successful_requests = 0
        failed_requests = 0
        
        async def user_session():
            """Simulate a single user session"""
            nonlocal successful_requests, failed_requests, response_times
            
            async with aiohttp.ClientSession() as session:
                end_time = test_start + duration
                
                while time.time() < end_time:
                    start_time = time.time()
                    try:
                        async with session.get(
                            f"{self.base_url}{endpoint}",
                            timeout=10
                        ) as response:
                            request_end = time.time()
                            response_time = (request_end - start_time) * 1000  # ms
                            response_times.append(response_time)
                            
                            if response.status < 400:
                                successful_requests += 1
                            else:
                                failed_requests += 1
                                
                    except Exception:
                        failed_requests += 1
                    
                    # Small delay between requests
                    await asyncio.sleep(0.1)
        
        # Run concurrent user sessions
        tasks = [user_session() for _ in range(concurrent_users)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        test_duration = time.time() - test_start
        
        if response_times:
            metrics = LoadTestMetrics(
                total_requests=len(response_times) + failed_requests,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                average_response_time=statistics.mean(response_times),
                median_response_time=statistics.median(response_times),
                p95_response_time=self._percentile(response_times, 95),
                p99_response_time=self._percentile(response_times, 99),
                min_response_time=min(response_times),
                max_response_time=max(response_times),
                requests_per_second=(successful_requests + failed_requests) / test_duration,
                error_rate=(failed_requests / (successful_requests + failed_requests)) * 100,
                throughput_mb_per_sec=0
            )
            
            # Determine status based on performance degradation
            if metrics.error_rate > 5:  # > 5% error rate
                status = LoadTestStatus.FAILED
                message = f"High error rate: {metrics.error_rate:.2f}%"
            elif metrics.average_response_time > 2000:  # > 2 seconds
                status = LoadTestStatus.FAILED
                message = f"Poor response time: {metrics.average_response_time:.2f}ms"
            elif metrics.average_response_time > 1000:  # > 1 second
                status = LoadTestStatus.WARNING
                message = f"Acceptable performance: {metrics.average_response_time:.2f}ms avg, {metrics.error_rate:.2f}% errors"
            else:
                status = LoadTestStatus.PASSED
                message = f"Good performance: {metrics.average_response_time:.2f}ms avg, {metrics.requests_per_second:.2f} RPS"
            
            self.results.append(LoadTestResult(
                test_name=test_name,
                category="Concurrency",
                status=status,
                message=message,
                metrics=metrics,
                details={"concurrent_users": concurrent_users},
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(LoadTestResult(
                test_name=test_name,
                category="Concurrency",
                status=LoadTestStatus.FAILED,
                message="No successful requests completed",
                details={"concurrent_users": concurrent_users},
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_stress_limits(self) -> None:
        """Test system stress limits"""
        logger.info("Testing stress limits")
        
        # Gradually increase load until system breaks
        stress_levels = [100, 200, 500, 1000]
        
        for stress_level in stress_levels:
            await self._run_stress_test(stress_level)
    
    async def _run_stress_test(self, concurrent_requests: int) -> None:
        """Run a stress test with specified concurrent requests"""
        test_start = time.time()
        response_times = []
        successful_requests = 0
        failed_requests = 0
        
        async def make_request():
            """Make a single request"""
            nonlocal successful_requests, failed_requests, response_times
            
            start_time = time.time()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self.base_url}/api/health",
                        timeout=5
                    ) as response:
                        end_time = time.time()
                        response_time = (end_time - start_time) * 1000  # ms
                        response_times.append(response_time)
                        
                        if response.status < 400:
                            successful_requests += 1
                        else:
                            failed_requests += 1
                            
            except Exception:
                failed_requests += 1
        
        # Create and run concurrent requests
        tasks = [make_request() for _ in range(concurrent_requests)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        test_duration = time.time() - test_start
        
        if response_times:
            metrics = LoadTestMetrics(
                total_requests=concurrent_requests,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                average_response_time=statistics.mean(response_times),
                median_response_time=statistics.median(response_times),
                p95_response_time=self._percentile(response_times, 95),
                p99_response_time=self._percentile(response_times, 99),
                min_response_time=min(response_times),
                max_response_time=max(response_times),
                requests_per_second=concurrent_requests / test_duration,
                error_rate=(failed_requests / concurrent_requests) * 100,
                throughput_mb_per_sec=0
            )
            
            # Determine status based on stress handling
            if metrics.error_rate > 10:  # > 10% error rate
                status = LoadTestStatus.FAILED
                message = f"System failed under stress: {metrics.error_rate:.2f}% error rate"
            elif metrics.error_rate > 5:  # > 5% error rate
                status = LoadTestStatus.WARNING
                message = f"System stressed: {metrics.error_rate:.2f}% error rate"
            else:
                status = LoadTestStatus.PASSED
                message = f"System handled stress well: {metrics.error_rate:.2f}% error rate"
            
            self.results.append(LoadTestResult(
                test_name=f"Stress Test ({concurrent_requests} requests)",
                category="Stress",
                status=status,
                message=message,
                metrics=metrics,
                details={"concurrent_requests": concurrent_requests},
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(LoadTestResult(
                test_name=f"Stress Test ({concurrent_requests} requests)",
                category="Stress",
                status=LoadTestStatus.FAILED,
                message="System completely failed under stress",
                details={"concurrent_requests": concurrent_requests},
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_spike_handling(self) -> None:
        """Test spike handling capabilities"""
        logger.info("Testing spike handling")
        
        # Simulate traffic spikes
        await self._run_spike_test("Traffic Spike", base_load=10, spike_load=100, spike_duration=10)
    
    async def _run_spike_test(
        self, 
        test_name: str, 
        base_load: int, 
        spike_load: int, 
        spike_duration: int
    ) -> None:
        """Run a traffic spike test"""
        test_start = time.time()
        response_times = []
        successful_requests = 0
        failed_requests = 0
        
        async def sustained_load():
            """Generate sustained base load"""
            nonlocal successful_requests, failed_requests, response_times
            
            async with aiohttp.ClientSession() as session:
                while time.time() - test_start < 60:  # Run for 1 minute
                    start_time = time.time()
                    try:
                        async with session.get(
                            f"{self.base_url}/api/health",
                            timeout=10
                        ) as response:
                            end_time = time.time()
                            response_time = (end_time - start_time) * 1000
                            response_times.append(response_time)
                            
                            if response.status < 400:
                                successful_requests += 1
                            else:
                                failed_requests += 1
                                
                    except Exception:
                        failed_requests += 1
                    
                    await asyncio.sleep(1)  # 1 request per second per base user
        
        async def spike_load_generator():
            """Generate spike load"""
            nonlocal successful_requests, failed_requests, response_times
            
            # Wait for spike time (30 seconds into test)
            await asyncio.sleep(30)
            
            async def spike_request():
                start_time = time.time()
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{self.base_url}/api/health",
                            timeout=5
                        ) as response:
                            end_time = time.time()
                            response_time = (end_time - start_time) * 1000
                            response_times.append(response_time)
                            
                            if response.status < 400:
                                successful_requests += 1
                            else:
                                failed_requests += 1
                                
                except Exception:
                    failed_requests += 1
            
            # Generate spike
            spike_tasks = [spike_request() for _ in range(spike_load)]
            await asyncio.gather(*spike_tasks, return_exceptions=True)
        
        # Run base load and spike concurrently
        base_tasks = [sustained_load() for _ in range(base_load)]
        spike_task = spike_load_generator()
        
        await asyncio.gather(*base_tasks, spike_task, return_exceptions=True)
        
        test_duration = time.time() - test_start
        
        if response_times:
            metrics = LoadTestMetrics(
                total_requests=len(response_times) + failed_requests,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                average_response_time=statistics.mean(response_times),
                median_response_time=statistics.median(response_times),
                p95_response_time=self._percentile(response_times, 95),
                p99_response_time=self._percentile(response_times, 99),
                min_response_time=min(response_times),
                max_response_time=max(response_times),
                requests_per_second=(successful_requests + failed_requests) / test_duration,
                error_rate=(failed_requests / (successful_requests + failed_requests)) * 100,
                throughput_mb_per_sec=0
            )
            
            # Determine status based on spike handling
            if metrics.error_rate > 15:  # > 15% error rate during spike
                status = LoadTestStatus.FAILED
                message = f"Poor spike handling: {metrics.error_rate:.2f}% error rate"
            elif metrics.error_rate > 8:  # > 8% error rate
                status = LoadTestStatus.WARNING
                message = f"Acceptable spike handling: {metrics.error_rate:.2f}% error rate"
            else:
                status = LoadTestStatus.PASSED
                message = f"Good spike handling: {metrics.error_rate:.2f}% error rate"
            
            self.results.append(LoadTestResult(
                test_name=test_name,
                category="Spike",
                status=status,
                message=message,
                metrics=metrics,
                details={
                    "base_load": base_load,
                    "spike_load": spike_load,
                    "spike_duration": spike_duration
                },
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(LoadTestResult(
                test_name=test_name,
                category="Spike",
                status=LoadTestStatus.FAILED,
                message="System failed during spike test",
                details={
                    "base_load": base_load,
                    "spike_load": spike_load,
                    "spike_duration": spike_duration
                },
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_endurance_performance(self) -> None:
        """Test endurance performance over extended period"""
        logger.info("Testing endurance performance")
        
        # Run sustained load for extended period
        await self._run_endurance_test("Endurance Test", concurrent_users=20, duration=300)  # 5 minutes
    
    async def _run_endurance_test(self, test_name: str, concurrent_users: int, duration: int) -> None:
        """Run an endurance test"""
        test_start = time.time()
        response_times = []
        successful_requests = 0
        failed_requests = 0
        
        async def endurance_user():
            """Simulate a user for endurance testing"""
            nonlocal successful_requests, failed_requests, response_times
            
            async with aiohttp.ClientSession() as session:
                end_time = test_start + duration
                
                while time.time() < end_time:
                    start_time = time.time()
                    try:
                        async with session.get(
                            f"{self.base_url}/api/health",
                            timeout=10
                        ) as response:
                            request_end = time.time()
                            response_time = (request_end - start_time) * 1000
                            response_times.append(response_time)
                            
                            if response.status < 400:
                                successful_requests += 1
                            else:
                                failed_requests += 1
                                
                    except Exception:
                        failed_requests += 1
                    
                    await asyncio.sleep(2)  # Request every 2 seconds
        
        # Run endurance users
        tasks = [endurance_user() for _ in range(concurrent_users)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        test_duration = time.time() - test_start
        
        if response_times:
            # Check for performance degradation over time
            first_half = response_times[:len(response_times)//2]
            second_half = response_times[len(response_times)//2:]
            
            first_half_avg = statistics.mean(first_half) if first_half else 0
            second_half_avg = statistics.mean(second_half) if second_half else 0
            
            degradation = ((second_half_avg - first_half_avg) / first_half_avg * 100) if first_half_avg > 0 else 0
            
            metrics = LoadTestMetrics(
                total_requests=len(response_times) + failed_requests,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                average_response_time=statistics.mean(response_times),
                median_response_time=statistics.median(response_times),
                p95_response_time=self._percentile(response_times, 95),
                p99_response_time=self._percentile(response_times, 99),
                min_response_time=min(response_times),
                max_response_time=max(response_times),
                requests_per_second=(successful_requests + failed_requests) / test_duration,
                error_rate=(failed_requests / (successful_requests + failed_requests)) * 100,
                throughput_mb_per_sec=0
            )
            
            # Determine status based on endurance performance
            if degradation > 50:  # > 50% performance degradation
                status = LoadTestStatus.FAILED
                message = f"Significant performance degradation: {degradation:.2f}%"
            elif degradation > 25:  # > 25% degradation
                status = LoadTestStatus.WARNING
                message = f"Some performance degradation: {degradation:.2f}%"
            elif metrics.error_rate > 5:  # > 5% error rate
                status = LoadTestStatus.WARNING
                message = f"Acceptable endurance with errors: {metrics.error_rate:.2f}% error rate"
            else:
                status = LoadTestStatus.PASSED
                message = f"Good endurance performance: {degradation:.2f}% degradation"
            
            self.results.append(LoadTestResult(
                test_name=test_name,
                category="Endurance",
                status=status,
                message=message,
                metrics=metrics,
                details={
                    "concurrent_users": concurrent_users,
                    "duration_minutes": duration / 60,
                    "performance_degradation_percent": degradation
                },
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(LoadTestResult(
                test_name=test_name,
                category="Endurance",
                status=LoadTestStatus.FAILED,
                message="System failed during endurance test",
                details={
                    "concurrent_users": concurrent_users,
                    "duration_minutes": duration / 60
                },
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_database_load(self) -> None:
        """Test database performance under load"""
        logger.info("Testing database load performance")
        
        # This would require database-specific endpoints
        self.results.append(LoadTestResult(
            test_name="Database Load Test",
            category="Database",
            status=LoadTestStatus.SKIPPED,
            message="Database load testing requires specific database endpoints",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_api_performance(self) -> None:
        """Test API endpoint performance"""
        logger.info("Testing API endpoint performance")
        
        # Test different API endpoints
        endpoints = [
            "/api/health",
            "/api/hotels",
            "/api/calls/status",
            "/health"
        ]
        
        for endpoint in endpoints:
            await self._test_endpoint_performance(endpoint)
    
    async def _test_endpoint_performance(self, endpoint: str) -> None:
        """Test performance of a specific endpoint"""
        test_start = time.time()
        response_times = []
        successful_requests = 0
        failed_requests = 0
        
        async with aiohttp.ClientSession() as session:
            # Test with moderate concurrent load
            async def test_request():
                nonlocal successful_requests, failed_requests, response_times
                
                start_time = time.time()
                try:
                    async with session.get(
                        f"{self.base_url}{endpoint}",
                        timeout=10
                    ) as response:
                        end_time = time.time()
                        response_time = (end_time - start_time) * 1000
                        response_times.append(response_time)
                        
                        if response.status < 400:
                            successful_requests += 1
                        else:
                            failed_requests += 1
                            
                except Exception:
                    failed_requests += 1
            
            # Run 50 concurrent requests
            tasks = [test_request() for _ in range(50)]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        test_duration = time.time() - test_start
        
        if response_times:
            metrics = LoadTestMetrics(
                total_requests=50,
                successful_requests=successful_requests,
                failed_requests=failed_requests,
                average_response_time=statistics.mean(response_times),
                median_response_time=statistics.median(response_times),
                p95_response_time=self._percentile(response_times, 95),
                p99_response_time=self._percentile(response_times, 99),
                min_response_time=min(response_times),
                max_response_time=max(response_times),
                requests_per_second=50 / test_duration,
                error_rate=(failed_requests / 50) * 100,
                throughput_mb_per_sec=0
            )
            
            # Determine status based on endpoint performance
            if metrics.error_rate > 5:  # > 5% error rate
                status = LoadTestStatus.FAILED
                message = f"High error rate: {metrics.error_rate:.2f}%"
            elif metrics.average_response_time > 1000:  # > 1 second
                status = LoadTestStatus.WARNING
                message = f"Slow response time: {metrics.average_response_time:.2f}ms"
            else:
                status = LoadTestStatus.PASSED
                message = f"Good performance: {metrics.average_response_time:.2f}ms avg"
            
            self.results.append(LoadTestResult(
                test_name=f"API Endpoint Performance ({endpoint})",
                category="API",
                status=status,
                message=message,
                metrics=metrics,
                details={"endpoint": endpoint},
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(LoadTestResult(
                test_name=f"API Endpoint Performance ({endpoint})",
                category="API",
                status=LoadTestStatus.FAILED,
                message="Endpoint completely failed",
                details={"endpoint": endpoint},
                duration=test_duration,
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_authentication_load(self) -> None:
        """Test authentication system under load"""
        logger.info("Testing authentication load")
        
        # This would require authentication endpoints
        self.results.append(LoadTestResult(
            test_name="Authentication Load Test",
            category="Authentication",
            status=LoadTestStatus.SKIPPED,
            message="Authentication load testing requires auth endpoints",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_rate_limiting_load(self) -> None:
        """Test rate limiting under load"""
        logger.info("Testing rate limiting load")
        
        # Test rate limiting effectiveness
        test_start = time.time()
        rate_limited_requests = 0
        successful_requests = 0
        
        async with aiohttp.ClientSession() as session:
            # Make rapid requests to trigger rate limiting
            for i in range(100):
                try:
                    async with session.get(
                        f"{self.base_url}/api/health",
                        timeout=5
                    ) as response:
                        if response.status == 429:  # Rate limited
                            rate_limited_requests += 1
                        elif response.status < 400:
                            successful_requests += 1
                except Exception:
                    pass
        
        test_duration = time.time() - test_start
        
        if rate_limited_requests > 0:
            status = LoadTestStatus.PASSED
            message = f"Rate limiting working: {rate_limited_requests} requests rate limited"
        else:
            status = LoadTestStatus.WARNING
            message = "No rate limiting detected"
        
        self.results.append(LoadTestResult(
            test_name="Rate Limiting Load Test",
            category="Rate Limiting",
            status=status,
            message=message,
            details={
                "rate_limited_requests": rate_limited_requests,
                "successful_requests": successful_requests,
                "total_requests": 100
            },
            duration=test_duration,
            timestamp=datetime.utcnow().isoformat()
        ))
    
    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile of data"""
        if not data:
            return 0.0
        
        sorted_data = sorted(data)
        index = (percentile / 100) * (len(sorted_data) - 1)
        
        if index.is_integer():
            return sorted_data[int(index)]
        else:
            lower = sorted_data[int(index)]
            upper = sorted_data[int(index) + 1]
            return lower + (upper - lower) * (index - int(index))
    
    def _generate_load_test_report(self) -> LoadTestReport:
        """Generate comprehensive load test report"""
        end_time = datetime.utcnow()
        execution_time = (end_time - self.start_time).total_seconds()
        
        # Count results by status
        status_counts = {
            LoadTestStatus.PASSED: 0,
            LoadTestStatus.FAILED: 0,
            LoadTestStatus.WARNING: 0,
            LoadTestStatus.SKIPPED: 0
        }
        
        for result in self.results:
            status_counts[result.status] += 1
        
        # Determine overall status
        if status_counts[LoadTestStatus.FAILED] > 0:
            overall_status = LoadTestStatus.FAILED
        elif status_counts[LoadTestStatus.WARNING] > 0:
            overall_status = LoadTestStatus.WARNING
        else:
            overall_status = LoadTestStatus.PASSED
        
        # Generate recommendations
        recommendations = self._generate_load_test_recommendations()
        
        return LoadTestReport(
            overall_status=overall_status,
            total_tests=len(self.results),
            passed_tests=status_counts[LoadTestStatus.PASSED],
            failed_tests=status_counts[LoadTestStatus.FAILED],
            warning_tests=status_counts[LoadTestStatus.WARNING],
            skipped_tests=status_counts[LoadTestStatus.SKIPPED],
            execution_time=execution_time,
            timestamp=end_time.isoformat(),
            results=self.results,
            system_metrics=self.system_metrics,
            recommendations=recommendations
        )
    
    def _generate_load_test_recommendations(self) -> List[str]:
        """Generate load test recommendations"""
        recommendations = []
        
        failed_tests = [r for r in self.results if r.status == LoadTestStatus.FAILED]
        warning_tests = [r for r in self.results if r.status == LoadTestStatus.WARNING]
        
        if failed_tests:
            recommendations.append(
                f"🚨 CRITICAL: {len(failed_tests)} load tests failed. "
                "System is not ready for production traffic."
            )
        
        if warning_tests:
            recommendations.append(
                f"⚠️ WARNING: {len(warning_tests)} load tests showed performance concerns. "
                "Consider optimization before production deployment."
            )
        
        # System resource recommendations
        if self.system_metrics.get('cpu', {}).get('max', 0) > 80:
            recommendations.append(
                "High CPU usage detected during testing. Consider scaling or optimization."
            )
        
        if self.system_metrics.get('memory', {}).get('max', 0) > 80:
            recommendations.append(
                "High memory usage detected during testing. Check for memory leaks."
            )
        
        # Performance-specific recommendations
        slow_tests = [r for r in self.results if r.metrics and r.metrics.average_response_time > 1000]
        if slow_tests:
            recommendations.append(
                f"Slow response times detected in {len(slow_tests)} tests. "
                "Consider performance optimization."
            )
        
        high_error_tests = [r for r in self.results if r.metrics and r.metrics.error_rate > 5]
        if high_error_tests:
            recommendations.append(
                f"High error rates detected in {len(high_error_tests)} tests. "
                "Investigate error handling and system stability."
            )
        
        if not failed_tests and not warning_tests:
            recommendations.append(
                "✅ All load tests passed! System appears ready for production traffic."
            )
        
        return recommendations


async def main():
    """Main execution function for load testing validation"""
    print("⚡ Starting Load Testing Validation")
    print("=" * 60)
    
    # You can customize the base URL for testing
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    validator = LoadTestingValidator(base_url=base_url)
    
    try:
        # Run comprehensive load tests
        report = await validator.run_comprehensive_load_tests()
        
        # Print summary
        print(f"\n📊 LOAD TEST SUMMARY")
        print(f"Overall Status: {report.overall_status.value}")
        print(f"Total Tests: {report.total_tests}")
        print(f"Passed: {report.passed_tests}")
        print(f"Failed: {report.failed_tests}")
        print(f"Warnings: {report.warning_tests}")
        print(f"Skipped: {report.skipped_tests}")
        print(f"Execution Time: {report.execution_time:.2f} seconds")
        
        # Print system metrics
        if report.system_metrics:
            print(f"\n💻 SYSTEM METRICS")
            print("-" * 60)
            cpu_metrics = report.system_metrics.get('cpu', {})
            memory_metrics = report.system_metrics.get('memory', {})
            
            print(f"CPU Usage - Avg: {cpu_metrics.get('average', 0):.1f}%, Max: {cpu_metrics.get('max', 0):.1f}%")
            print(f"Memory Usage - Avg: {memory_metrics.get('average', 0):.1f}%, Max: {memory_metrics.get('max', 0):.1f}%")
        
        # Print detailed results
        print(f"\n📋 DETAILED RESULTS")
        print("-" * 60)
        
        for result in report.results:
            status_emoji = {
                LoadTestStatus.PASSED: "✅",
                LoadTestStatus.FAILED: "❌",
                LoadTestStatus.WARNING: "⚠️",
                LoadTestStatus.SKIPPED: "⏭️"
            }
            
            print(f"{status_emoji[result.status]} [{result.category}] {result.test_name}")
            print(f"   {result.message}")
            
            if result.metrics:
                print(f"   📈 Avg Response: {result.metrics.average_response_time:.2f}ms, "
                      f"RPS: {result.metrics.requests_per_second:.2f}, "
                      f"Error Rate: {result.metrics.error_rate:.2f}%")
            
            if result.duration:
                print(f"   ⏱️ Duration: {result.duration:.2f}s")
            print()
        
        # Print recommendations
        if report.recommendations:
            print(f"\n💡 RECOMMENDATIONS")
            print("-" * 60)
            for i, rec in enumerate(report.recommendations, 1):
                print(f"{i}. {rec}")
        
        # Save report to file
        report_path = Path("load_testing_report.json")
        with open(report_path, 'w') as f:
            json.dump(asdict(report), f, indent=2, default=str)
        
        print(f"\n📄 Full load test report saved to: {report_path}")
        
        # Exit with appropriate code
        if report.overall_status == LoadTestStatus.FAILED:
            print("\n❌ LOAD TESTING: FAILED")
            print("System is not ready for production traffic.")
            sys.exit(1)
        elif report.overall_status == LoadTestStatus.WARNING:
            print("\n⚠️ LOAD TESTING: WARNING")
            print("System has performance concerns that should be addressed.")
            sys.exit(0)
        else:
            print("\n✅ LOAD TESTING: PASSED")
            print("System is ready for production traffic!")
            sys.exit(0)
            
    except Exception as e:
        logger.error(f"Load testing failed with error: {str(e)}")
        print(f"\n❌ LOAD TESTING ERROR: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())