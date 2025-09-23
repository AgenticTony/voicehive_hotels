"""
Performance Tester - Performance regression testing with baseline comparisons

This module implements comprehensive performance testing to detect regressions
and ensure system meets performance requirements under various conditions.
"""

import asyncio
import json
import logging
import psutil
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import memory_profiler

logger = logging.getLogger(__name__)


@dataclass
class PerformanceBaseline:
    """Performance baseline metrics"""
    endpoint: str
    method: str
    avg_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    throughput_rps: float
    memory_usage_mb: float
    cpu_usage_percent: float
    error_rate_percent: float
    timestamp: str


@dataclass
class PerformanceTest:
    """Defines a performance test scenario"""
    name: str
    description: str
    endpoint: str
    method: str = "GET"
    payload: Optional[Dict] = None
    headers: Optional[Dict] = None
    concurrent_users: int = 10
    requests_per_user: int = 10
    duration_seconds: Optional[int] = None
    baseline: Optional[PerformanceBaseline] = None
    regression_threshold: float = 0.2  # 20% degradation threshold


@dataclass
class PerformanceResult:
    """Results from a performance test"""
    test_name: str
    endpoint: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_response_time_ms: float
    median_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    throughput_rps: float
    memory_usage_mb: float
    peak_memory_usage_mb: float
    cpu_usage_percent: float
    error_rate_percent: float
    regression_detected: bool
    performance_score: float
    duration_seconds: float


class PerformanceTester:
    """
    Comprehensive performance testing framework with regression detection
    """
    
    def __init__(self, config):
        self.config = config
        self.base_url = "http://localhost:8000"
        self.session = None
        self.baselines_file = Path("test_reports/performance_baselines.json")
        self.baselines = self._load_baselines()
        self.performance_tests = self._define_performance_tests()
        
        # Performance monitoring
        self.memory_samples = []
        self.cpu_samples = []
        self.monitoring_active = False
    
    def _define_performance_tests(self) -> List[PerformanceTest]:
        """Define performance test scenarios"""
        
        return [
            # Authentication performance
            PerformanceTest(
                name="authentication_performance",
                description="JWT authentication and validation performance",
                endpoint="/auth/login",
                method="POST",
                payload={"email": "test@example.com", "password": "testpass123"},
                concurrent_users=20,
                requests_per_user=50,
                regression_threshold=0.15  # 15% threshold for auth
            ),
            
            PerformanceTest(
                name="jwt_validation_performance",
                description="JWT token validation performance under load",
                endpoint="/auth/validate",
                method="GET",
                headers={"Authorization": "Bearer test_token"},
                concurrent_users=50,
                requests_per_user=100,
                regression_threshold=0.1  # 10% threshold for validation
            ),
            
            # API endpoint performance
            PerformanceTest(
                name="health_check_performance",
                description="Health check endpoint performance",
                endpoint="/health",
                method="GET",
                concurrent_users=100,
                requests_per_user=20,
                regression_threshold=0.05  # 5% threshold for health checks
            ),
            
            PerformanceTest(
                name="call_creation_performance",
                description="Call creation endpoint performance",
                endpoint="/calls",
                method="POST",
                payload={
                    "hotel_id": "test_hotel",
                    "room_number": "101",
                    "guest_phone": "+1234567890"
                },
                concurrent_users=25,
                requests_per_user=20,
                regression_threshold=0.2
            ),
            
            PerformanceTest(
                name="call_events_performance",
                description="Call events processing performance",
                endpoint="/calls/events",
                method="POST",
                payload={
                    "call_id": "test_call",
                    "event_type": "call_started",
                    "timestamp": datetime.utcnow().isoformat()
                },
                concurrent_users=50,
                requests_per_user=30,
                regression_threshold=0.15
            ),
            
            # PMS integration performance
            PerformanceTest(
                name="pms_reservation_lookup_performance",
                description="PMS reservation lookup performance",
                endpoint="/pms/reservations/lookup",
                method="GET",
                concurrent_users=15,
                requests_per_user=25,
                regression_threshold=0.25  # Higher threshold for external dependency
            ),
            
            PerformanceTest(
                name="pms_guest_profile_performance",
                description="PMS guest profile operations performance",
                endpoint="/pms/guests/profile",
                method="POST",
                payload={"guest_id": "test_guest", "profile_data": {}},
                concurrent_users=10,
                requests_per_user=20,
                regression_threshold=0.3
            ),
            
            # TTS performance
            PerformanceTest(
                name="tts_synthesis_performance",
                description="TTS synthesis performance under load",
                endpoint="/tts/synthesize",
                method="POST",
                payload={
                    "text": "Welcome to our hotel. How may I assist you?",
                    "voice": "en-US-Standard-A"
                },
                concurrent_users=5,
                requests_per_user=10,
                regression_threshold=0.3  # Higher threshold for TTS
            ),
            
            # Database performance
            PerformanceTest(
                name="database_query_performance",
                description="Database query performance testing",
                endpoint="/api/data/query",
                method="POST",
                payload={"query": "SELECT * FROM test_table LIMIT 100"},
                concurrent_users=20,
                requests_per_user=15,
                regression_threshold=0.2
            ),
            
            # Cache performance
            PerformanceTest(
                name="cache_performance",
                description="Redis cache performance testing",
                endpoint="/api/cache/test",
                method="GET",
                concurrent_users=30,
                requests_per_user=25,
                regression_threshold=0.15
            ),
            
            # Memory-intensive operations
            PerformanceTest(
                name="memory_intensive_performance",
                description="Memory-intensive operations performance",
                endpoint="/api/process/large-data",
                method="POST",
                payload={"data_size": "1MB"},
                concurrent_users=10,
                requests_per_user=5,
                regression_threshold=0.25
            ),
            
            # Sustained load test
            PerformanceTest(
                name="sustained_load_performance",
                description="Sustained load performance over time",
                endpoint="/api/mixed-operations",
                method="GET",
                concurrent_users=self.config.concurrent_users,
                duration_seconds=300,  # 5 minutes
                regression_threshold=0.2
            )
        ]
    
    def _load_baselines(self) -> Dict[str, PerformanceBaseline]:
        """Load performance baselines from file"""
        
        baselines = {}
        
        try:
            if self.baselines_file.exists():
                with open(self.baselines_file, 'r') as f:
                    baseline_data = json.load(f)
                    
                    for test_name, data in baseline_data.items():
                        baselines[test_name] = PerformanceBaseline(**data)
            else:
                logger.info("No baseline file found, will create new baselines")
        
        except Exception as e:
            logger.warning(f"Could not load baselines: {e}")
        
        return baselines
    
    def _save_baselines(self):
        """Save performance baselines to file"""
        
        try:
            # Ensure directory exists
            self.baselines_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert baselines to dict
            baseline_data = {}
            for test_name, baseline in self.baselines.items():
                baseline_data[test_name] = {
                    'endpoint': baseline.endpoint,
                    'method': baseline.method,
                    'avg_response_time_ms': baseline.avg_response_time_ms,
                    'p95_response_time_ms': baseline.p95_response_time_ms,
                    'p99_response_time_ms': baseline.p99_response_time_ms,
                    'throughput_rps': baseline.throughput_rps,
                    'memory_usage_mb': baseline.memory_usage_mb,
                    'cpu_usage_percent': baseline.cpu_usage_percent,
                    'error_rate_percent': baseline.error_rate_percent,
                    'timestamp': baseline.timestamp
                }
            
            with open(self.baselines_file, 'w') as f:
                json.dump(baseline_data, f, indent=2)
            
            logger.info(f"Saved baselines to {self.baselines_file}")
        
        except Exception as e:
            logger.error(f"Could not save baselines: {e}")
    
    async def run_regression_tests(self) -> Dict[str, Any]:
        """
        Run performance regression tests with baseline comparisons
        
        Returns:
            Dict containing performance test results and regression analysis
        """
        logger.info("Starting performance regression testing")
        
        try:
            # Initialize HTTP session
            await self._initialize_session()
            
            # Start system monitoring
            await self._start_monitoring()
            
            # Run performance tests
            results = []
            for test in self.performance_tests:
                logger.info(f"Running performance test: {test.name}")
                result = await self._run_performance_test(test)
                results.append(result)
                
                # Update baseline if this is a new test or better performance
                await self._update_baseline(test, result)
                
                # Brief pause between tests
                await asyncio.sleep(5)
            
            # Stop monitoring
            await self._stop_monitoring()
            
            # Generate comprehensive report
            report = self._generate_performance_report(results)
            
            # Save updated baselines
            self._save_baselines()
            
            logger.info("Performance regression testing completed")
            return report
            
        except Exception as e:
            logger.error(f"Error during performance testing: {e}")
            raise
        finally:
            await self._cleanup_session()
            await self._stop_monitoring()
    
    async def _initialize_session(self):
        """Initialize HTTP session for performance testing"""
        connector = aiohttp.TCPConnector(
            limit=200,
            limit_per_host=50,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        timeout = aiohttp.ClientTimeout(total=60, connect=10)
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "VoiceHive-PerformanceTester/1.0"}
        )
    
    async def _cleanup_session(self):
        """Cleanup HTTP session"""
        if self.session:
            await self.session.close()
    
    async def _start_monitoring(self):
        """Start system resource monitoring"""
        self.monitoring_active = True
        self.memory_samples = []
        self.cpu_samples = []
        
        # Start monitoring task
        asyncio.create_task(self._monitor_resources())
    
    async def _stop_monitoring(self):
        """Stop system resource monitoring"""
        self.monitoring_active = False
    
    async def _monitor_resources(self):
        """Monitor system resources during testing"""
        
        while self.monitoring_active:
            try:
                # Sample CPU and memory usage
                cpu_percent = psutil.cpu_percent(interval=None)
                memory_info = psutil.virtual_memory()
                
                self.cpu_samples.append(cpu_percent)
                self.memory_samples.append(memory_info.used / 1024 / 1024)  # MB
                
                await asyncio.sleep(1)  # Sample every second
            
            except Exception as e:
                logger.warning(f"Error monitoring resources: {e}")
                await asyncio.sleep(1)
    
    async def _run_performance_test(self, test: PerformanceTest) -> PerformanceResult:
        """Run a single performance test"""
        
        start_time = time.time()
        
        # Clear monitoring samples for this test
        self.memory_samples = []
        self.cpu_samples = []
        
        # Prepare authentication if needed
        headers = test.headers or {}
        if test.endpoint.startswith('/auth') or 'auth' in test.endpoint.lower():
            # Add mock auth headers for protected endpoints
            headers.update({"Authorization": "Bearer mock_performance_test_token"})
        
        # Create tasks for concurrent execution
        tasks = []
        
        if test.duration_seconds:
            # Duration-based testing
            tasks = await self._create_duration_tasks(test, headers)
        else:
            # Request count-based testing
            tasks = await self._create_count_tasks(test, headers)
        
        # Execute all tasks and collect metrics
        response_times = []
        errors = []
        successful_requests = 0
        
        try:
            # Execute tasks with progress tracking
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    errors.append(str(result))
                elif isinstance(result, dict) and 'response_time' in result:
                    response_times.append(result['response_time'])
                    if result.get('success', False):
                        successful_requests += 1
                    else:
                        errors.append(result.get('error', 'Unknown error'))
        
        except Exception as e:
            logger.error(f"Error executing performance test {test.name}: {e}")
            errors.append(str(e))
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Calculate performance metrics
        total_requests = len(tasks)
        failed_requests = total_requests - successful_requests
        error_rate = (failed_requests / total_requests * 100) if total_requests > 0 else 0
        
        # Response time statistics
        if response_times:
            avg_response_time = statistics.mean(response_times)
            median_response_time = statistics.median(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            
            # Calculate percentiles
            sorted_times = sorted(response_times)
            p95_index = int(0.95 * len(sorted_times))
            p99_index = int(0.99 * len(sorted_times))
            p95_response_time = sorted_times[p95_index] if p95_index < len(sorted_times) else max_response_time
            p99_response_time = sorted_times[p99_index] if p99_index < len(sorted_times) else max_response_time
        else:
            avg_response_time = median_response_time = min_response_time = max_response_time = 0
            p95_response_time = p99_response_time = 0
        
        # System resource metrics
        avg_memory_usage = statistics.mean(self.memory_samples) if self.memory_samples else 0
        peak_memory_usage = max(self.memory_samples) if self.memory_samples else 0
        avg_cpu_usage = statistics.mean(self.cpu_samples) if self.cpu_samples else 0
        
        # Throughput calculation
        throughput_rps = successful_requests / duration if duration > 0 else 0
        
        # Regression detection
        regression_detected = await self._detect_regression(test, avg_response_time, throughput_rps, error_rate)
        
        # Performance score calculation (0-100)
        performance_score = self._calculate_performance_score(
            avg_response_time, throughput_rps, error_rate, avg_memory_usage, avg_cpu_usage
        )
        
        return PerformanceResult(
            test_name=test.name,
            endpoint=test.endpoint,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            avg_response_time_ms=avg_response_time,
            median_response_time_ms=median_response_time,
            p95_response_time_ms=p95_response_time,
            p99_response_time_ms=p99_response_time,
            min_response_time_ms=min_response_time,
            max_response_time_ms=max_response_time,
            throughput_rps=throughput_rps,
            memory_usage_mb=avg_memory_usage,
            peak_memory_usage_mb=peak_memory_usage,
            cpu_usage_percent=avg_cpu_usage,
            error_rate_percent=error_rate,
            regression_detected=regression_detected,
            performance_score=performance_score,
            duration_seconds=duration
        )
    
    async def _create_count_tasks(self, test: PerformanceTest, headers: Dict) -> List:
        """Create tasks for count-based performance testing"""
        tasks = []
        
        for user_id in range(test.concurrent_users):
            for request_id in range(test.requests_per_user):
                task = self._make_performance_request(
                    test=test,
                    headers=headers,
                    user_id=user_id,
                    request_id=request_id
                )
                tasks.append(task)
        
        return tasks
    
    async def _create_duration_tasks(self, test: PerformanceTest, headers: Dict) -> List:
        """Create tasks for duration-based performance testing"""
        tasks = []
        
        # Calculate how many requests to make over the duration
        total_requests = test.concurrent_users * 20  # 20 requests per user for duration tests
        request_interval = test.duration_seconds / total_requests
        
        for user_id in range(test.concurrent_users):
            for request_id in range(20):  # 20 requests per user
                delay = request_id * request_interval
                
                task = self._make_delayed_performance_request(
                    test=test,
                    headers=headers,
                    user_id=user_id,
                    request_id=request_id,
                    delay=delay
                )
                tasks.append(task)
        
        return tasks
    
    async def _make_performance_request(self, test: PerformanceTest, headers: Dict,
                                      user_id: int, request_id: int) -> Dict:
        """Make a single performance request"""
        
        start_time = time.time()
        
        try:
            # Prepare request
            url = f"{self.base_url}{test.endpoint}"
            
            # Add user-specific variations to payload
            payload = test.payload.copy() if test.payload else None
            if payload:
                payload['user_id'] = f"perf_test_user_{user_id}"
                payload['request_id'] = request_id
            
            # Make the request
            async with self.session.request(
                method=test.method,
                url=url,
                json=payload,
                headers=headers
            ) as response:
                
                # Read response content (but limit size for performance)
                if response.content_length and response.content_length < 10240:  # 10KB limit
                    await response.text()
                else:
                    # Just read headers for large responses
                    pass
                
                end_time = time.time()
                response_time = (end_time - start_time) * 1000  # Convert to milliseconds
                
                success = 200 <= response.status < 400
                
                return {
                    'response_time': response_time,
                    'status_code': response.status,
                    'success': success,
                    'error': None if success else f"HTTP {response.status}"
                }
        
        except Exception as e:
            end_time = time.time()
            response_time = (end_time - start_time) * 1000
            
            return {
                'response_time': response_time,
                'status_code': 0,
                'success': False,
                'error': str(e)
            }
    
    async def _make_delayed_performance_request(self, test: PerformanceTest, headers: Dict,
                                              user_id: int, request_id: int, delay: float) -> Dict:
        """Make a performance request with initial delay"""
        await asyncio.sleep(delay)
        return await self._make_performance_request(test, headers, user_id, request_id)
    
    async def _detect_regression(self, test: PerformanceTest, avg_response_time: float,
                               throughput_rps: float, error_rate: float) -> bool:
        """Detect performance regression compared to baseline"""
        
        baseline = self.baselines.get(test.name)
        if not baseline:
            logger.info(f"No baseline found for {test.name}, will create new baseline")
            return False
        
        # Check response time regression
        response_time_increase = (avg_response_time - baseline.avg_response_time_ms) / baseline.avg_response_time_ms
        if response_time_increase > test.regression_threshold:
            logger.warning(f"Response time regression detected for {test.name}: {response_time_increase:.2%}")
            return True
        
        # Check throughput regression
        throughput_decrease = (baseline.throughput_rps - throughput_rps) / baseline.throughput_rps
        if throughput_decrease > test.regression_threshold:
            logger.warning(f"Throughput regression detected for {test.name}: {throughput_decrease:.2%}")
            return True
        
        # Check error rate increase
        error_rate_increase = error_rate - baseline.error_rate_percent
        if error_rate_increase > 5.0:  # 5% absolute increase in error rate
            logger.warning(f"Error rate regression detected for {test.name}: {error_rate_increase:.2%}")
            return True
        
        return False
    
    async def _update_baseline(self, test: PerformanceTest, result: PerformanceResult):
        """Update baseline if performance is better or no baseline exists"""
        
        current_baseline = self.baselines.get(test.name)
        
        # Create new baseline if none exists
        if not current_baseline:
            self.baselines[test.name] = PerformanceBaseline(
                endpoint=test.endpoint,
                method=test.method,
                avg_response_time_ms=result.avg_response_time_ms,
                p95_response_time_ms=result.p95_response_time_ms,
                p99_response_time_ms=result.p99_response_time_ms,
                throughput_rps=result.throughput_rps,
                memory_usage_mb=result.memory_usage_mb,
                cpu_usage_percent=result.cpu_usage_percent,
                error_rate_percent=result.error_rate_percent,
                timestamp=datetime.utcnow().isoformat()
            )
            logger.info(f"Created new baseline for {test.name}")
            return
        
        # Update baseline if performance is significantly better
        response_time_improvement = (current_baseline.avg_response_time_ms - result.avg_response_time_ms) / current_baseline.avg_response_time_ms
        throughput_improvement = (result.throughput_rps - current_baseline.throughput_rps) / current_baseline.throughput_rps
        
        if (response_time_improvement > 0.1 or throughput_improvement > 0.1) and result.error_rate_percent <= current_baseline.error_rate_percent:
            self.baselines[test.name] = PerformanceBaseline(
                endpoint=test.endpoint,
                method=test.method,
                avg_response_time_ms=result.avg_response_time_ms,
                p95_response_time_ms=result.p95_response_time_ms,
                p99_response_time_ms=result.p99_response_time_ms,
                throughput_rps=result.throughput_rps,
                memory_usage_mb=result.memory_usage_mb,
                cpu_usage_percent=result.cpu_usage_percent,
                error_rate_percent=result.error_rate_percent,
                timestamp=datetime.utcnow().isoformat()
            )
            logger.info(f"Updated baseline for {test.name} due to performance improvement")
    
    def _calculate_performance_score(self, avg_response_time: float, throughput_rps: float,
                                   error_rate: float, memory_usage: float, cpu_usage: float) -> float:
        """Calculate overall performance score (0-100)"""
        
        score = 100.0
        
        # Response time penalty (0-30 points)
        if avg_response_time > 2000:  # > 2 seconds
            score -= 30
        elif avg_response_time > 1000:  # > 1 second
            score -= 20
        elif avg_response_time > 500:  # > 500ms
            score -= 10
        
        # Throughput bonus/penalty (0-20 points)
        if throughput_rps > 100:
            score += min(10, throughput_rps / 20)  # Bonus for high throughput
        elif throughput_rps < 10:
            score -= 20  # Penalty for low throughput
        
        # Error rate penalty (0-25 points)
        score -= min(25, error_rate * 5)  # 5 points per 1% error rate
        
        # Memory usage penalty (0-15 points)
        if memory_usage > 1000:  # > 1GB
            score -= 15
        elif memory_usage > 500:  # > 500MB
            score -= 10
        
        # CPU usage penalty (0-10 points)
        if cpu_usage > 80:  # > 80%
            score -= 10
        elif cpu_usage > 60:  # > 60%
            score -= 5
        
        return max(0, min(100, score))
    
    def _generate_performance_report(self, results: List[PerformanceResult]) -> Dict[str, Any]:
        """Generate comprehensive performance report"""
        
        total_tests = len(results)
        passed_tests = sum(1 for r in results if not r.regression_detected and r.error_rate_percent < 5.0)
        overall_success = passed_tests == total_tests
        
        # Calculate aggregate metrics
        total_requests = sum(r.total_requests for r in results)
        total_successful = sum(r.successful_requests for r in results)
        
        # Performance statistics
        avg_response_times = [r.avg_response_time_ms for r in results if r.avg_response_time_ms > 0]
        overall_avg_response_time = statistics.mean(avg_response_times) if avg_response_times else 0
        
        throughputs = [r.throughput_rps for r in results if r.throughput_rps > 0]
        overall_throughput = sum(throughputs) if throughputs else 0
        
        memory_usages = [r.peak_memory_usage_mb for r in results if r.peak_memory_usage_mb > 0]
        peak_memory_usage = max(memory_usages) if memory_usages else 0
        
        # Regression analysis
        regressions = [r for r in results if r.regression_detected]
        regression_count = len(regressions)
        
        # Performance bottlenecks
        bottlenecks = []
        for result in results:
            if result.avg_response_time_ms > 2000:
                bottlenecks.append(f"{result.test_name}: High response time ({result.avg_response_time_ms:.0f}ms)")
            if result.throughput_rps < 10:
                bottlenecks.append(f"{result.test_name}: Low throughput ({result.throughput_rps:.1f} RPS)")
            if result.error_rate_percent > 5:
                bottlenecks.append(f"{result.test_name}: High error rate ({result.error_rate_percent:.1f}%)")
            if result.peak_memory_usage_mb > self.config.memory_threshold_mb:
                bottlenecks.append(f"{result.test_name}: High memory usage ({result.peak_memory_usage_mb:.0f}MB)")
        
        # Overall performance score
        performance_scores = [r.performance_score for r in results]
        overall_performance_score = statistics.mean(performance_scores) if performance_scores else 0
        
        return {
            'overall_success': overall_success,
            'tests_run': total_tests,
            'tests_passed': passed_tests,
            'tests_failed': total_tests - passed_tests,
            'regression_detected': regression_count > 0,
            'regressions_count': regression_count,
            'average_response_time_ms': overall_avg_response_time,
            'total_throughput_rps': overall_throughput,
            'peak_memory_usage_mb': peak_memory_usage,
            'memory_threshold_exceeded': peak_memory_usage > self.config.memory_threshold_mb,
            'overall_performance_score': overall_performance_score,
            'performance_grade': self._get_performance_grade(overall_performance_score),
            'test_results': [
                {
                    'name': r.test_name,
                    'endpoint': r.endpoint,
                    'avg_response_time_ms': r.avg_response_time_ms,
                    'p95_response_time_ms': r.p95_response_time_ms,
                    'throughput_rps': r.throughput_rps,
                    'error_rate_percent': r.error_rate_percent,
                    'memory_usage_mb': r.memory_usage_mb,
                    'regression_detected': r.regression_detected,
                    'performance_score': r.performance_score
                }
                for r in results
            ],
            'regressions': [
                {
                    'test_name': r.test_name,
                    'endpoint': r.endpoint,
                    'avg_response_time_ms': r.avg_response_time_ms,
                    'throughput_rps': r.throughput_rps,
                    'error_rate_percent': r.error_rate_percent
                }
                for r in regressions
            ],
            'performance_bottlenecks': bottlenecks,
            'recommendations': self._generate_performance_recommendations(results, regressions)
        }
    
    def _get_performance_grade(self, score: float) -> str:
        """Get performance grade based on score"""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"
    
    def _generate_performance_recommendations(self, results: List[PerformanceResult],
                                           regressions: List[PerformanceResult]) -> List[str]:
        """Generate performance recommendations"""
        recommendations = []
        
        # Regression recommendations
        if regressions:
            recommendations.append(
                f"Address {len(regressions)} performance regressions detected in: "
                f"{', '.join(r.test_name for r in regressions[:3])}"
            )
        
        # Response time recommendations
        slow_tests = [r for r in results if r.avg_response_time_ms > 1000]
        if slow_tests:
            recommendations.append(
                f"Optimize response times for {len(slow_tests)} slow endpoints (>1s response time)"
            )
        
        # Throughput recommendations
        low_throughput = [r for r in results if r.throughput_rps < 20]
        if low_throughput:
            recommendations.append(
                f"Improve throughput for {len(low_throughput)} endpoints with low RPS"
            )
        
        # Memory recommendations
        high_memory = [r for r in results if r.peak_memory_usage_mb > self.config.memory_threshold_mb]
        if high_memory:
            recommendations.append(
                f"Optimize memory usage for {len(high_memory)} memory-intensive operations"
            )
        
        # Error rate recommendations
        high_errors = [r for r in results if r.error_rate_percent > 1.0]
        if high_errors:
            recommendations.append(
                f"Reduce error rates for {len(high_errors)} endpoints with high failure rates"
            )
        
        # General recommendations
        if not recommendations:
            recommendations.append("Performance testing passed all benchmarks. System is optimized for production.")
        else:
            recommendations.append("Consider implementing performance monitoring and alerting in production")
            recommendations.append("Run performance tests regularly to catch regressions early")
        
        return recommendations