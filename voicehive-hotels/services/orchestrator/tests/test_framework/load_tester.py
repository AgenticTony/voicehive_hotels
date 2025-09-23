"""
Load Tester - Comprehensive load testing for critical user journeys

This module implements load testing scenarios for all critical user journeys
to validate system performance under production load conditions.
"""

import asyncio
import json
import logging
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import aiohttp
import pytest
from httpx import AsyncClient

logger = logging.getLogger(__name__)


@dataclass
class LoadTestScenario:
    """Defines a load testing scenario"""
    name: str
    description: str
    endpoint: str
    method: str = "GET"
    payload: Optional[Dict] = None
    headers: Optional[Dict] = None
    concurrent_users: int = 10
    requests_per_user: int = 10
    duration_seconds: Optional[int] = None
    expected_response_time_ms: int = 1000
    expected_success_rate: float = 0.99
    auth_required: bool = False


@dataclass
class LoadTestResult:
    """Results from a load test execution"""
    scenario_name: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    success_rate: float
    average_response_time_ms: float
    median_response_time_ms: float
    p95_response_time_ms: float
    p99_response_time_ms: float
    min_response_time_ms: float
    max_response_time_ms: float
    requests_per_second: float
    errors: List[str]
    duration_seconds: float
    passed: bool


class LoadTester:
    """
    Comprehensive load testing framework for critical user journeys
    """
    
    def __init__(self, config):
        self.config = config
        self.base_url = "http://localhost:8000"  # Default test URL
        self.scenarios = self._define_critical_scenarios()
        self.session = None
        
    def _define_critical_scenarios(self) -> List[LoadTestScenario]:
        """Define critical user journey scenarios for load testing"""
        
        return [
            # Authentication scenarios
            LoadTestScenario(
                name="user_authentication_flow",
                description="Complete user authentication flow including login and token validation",
                endpoint="/auth/login",
                method="POST",
                payload={"email": "test@example.com", "password": "testpass123"},
                concurrent_users=self.config.concurrent_users,
                requests_per_user=20,
                expected_response_time_ms=500,
                expected_success_rate=0.99
            ),
            
            LoadTestScenario(
                name="jwt_token_validation",
                description="JWT token validation under load",
                endpoint="/auth/validate",
                method="GET",
                headers={"Authorization": "Bearer test_token"},
                concurrent_users=self.config.concurrent_users * 2,
                requests_per_user=50,
                expected_response_time_ms=100,
                expected_success_rate=0.995,
                auth_required=True
            ),
            
            # Call management scenarios
            LoadTestScenario(
                name="call_creation_flow",
                description="Voice call creation and initialization",
                endpoint="/calls",
                method="POST",
                payload={
                    "hotel_id": "test_hotel_123",
                    "room_number": "101",
                    "guest_phone": "+1234567890"
                },
                concurrent_users=25,
                requests_per_user=10,
                expected_response_time_ms=800,
                expected_success_rate=0.98,
                auth_required=True
            ),
            
            LoadTestScenario(
                name="call_events_processing",
                description="Processing of call events (started, answered, ended)",
                endpoint="/calls/events",
                method="POST",
                payload={
                    "call_id": "test_call_123",
                    "event_type": "call_started",
                    "timestamp": datetime.utcnow().isoformat()
                },
                concurrent_users=50,
                requests_per_user=30,
                expected_response_time_ms=200,
                expected_success_rate=0.999,
                auth_required=True
            ),
            
            # PMS integration scenarios
            LoadTestScenario(
                name="pms_reservation_lookup",
                description="PMS reservation data retrieval",
                endpoint="/pms/reservations/lookup",
                method="GET",
                concurrent_users=20,
                requests_per_user=25,
                expected_response_time_ms=1500,
                expected_success_rate=0.95,  # Lower due to external dependency
                auth_required=True
            ),
            
            LoadTestScenario(
                name="pms_guest_profile_operations",
                description="Guest profile read/write operations",
                endpoint="/pms/guests/profile",
                method="POST",
                payload={
                    "guest_id": "guest_123",
                    "profile_data": {"preferences": {"language": "en"}}
                },
                concurrent_users=15,
                requests_per_user=15,
                expected_response_time_ms=1000,
                expected_success_rate=0.97,
                auth_required=True
            ),
            
            # TTS and audio scenarios
            LoadTestScenario(
                name="tts_synthesis_requests",
                description="Text-to-speech synthesis under load",
                endpoint="/tts/synthesize",
                method="POST",
                payload={
                    "text": "Welcome to our hotel. How may I assist you today?",
                    "voice": "en-US-Standard-A",
                    "format": "mp3"
                },
                concurrent_users=10,
                requests_per_user=5,
                expected_response_time_ms=3000,
                expected_success_rate=0.95,
                auth_required=True
            ),
            
            # Health and monitoring scenarios
            LoadTestScenario(
                name="health_check_endpoints",
                description="Health check endpoint performance",
                endpoint="/health",
                method="GET",
                concurrent_users=100,
                requests_per_user=20,
                expected_response_time_ms=50,
                expected_success_rate=0.999
            ),
            
            LoadTestScenario(
                name="metrics_collection",
                description="Metrics endpoint performance under load",
                endpoint="/metrics",
                method="GET",
                concurrent_users=20,
                requests_per_user=10,
                expected_response_time_ms=200,
                expected_success_rate=0.99
            ),
            
            # Mixed workload scenario
            LoadTestScenario(
                name="mixed_production_workload",
                description="Realistic mixed workload simulating production traffic",
                endpoint="/mixed",  # Special endpoint for mixed testing
                method="GET",
                concurrent_users=self.config.concurrent_users,
                requests_per_user=self.config.requests_per_user,
                duration_seconds=self.config.test_duration_seconds,
                expected_response_time_ms=self.config.max_response_time_ms,
                expected_success_rate=1.0 - (self.config.max_error_rate_percent / 100),
                auth_required=True
            )
        ]
    
    async def run_critical_journey_tests(self) -> Dict[str, Any]:
        """
        Run load tests for all critical user journeys
        
        Returns:
            Dict containing comprehensive load test results
        """
        logger.info("Starting critical user journey load tests")
        
        try:
            # Initialize HTTP session
            await self._initialize_session()
            
            # Run all load test scenarios
            results = []
            for scenario in self.scenarios:
                logger.info(f"Running load test scenario: {scenario.name}")
                result = await self._run_scenario(scenario)
                results.append(result)
                
                # Brief pause between scenarios to avoid overwhelming the system
                await asyncio.sleep(2)
            
            # Generate comprehensive report
            report = self._generate_load_test_report(results)
            
            logger.info("Critical user journey load tests completed")
            return report
            
        except Exception as e:
            logger.error(f"Error during load testing: {e}")
            raise
        finally:
            await self._cleanup_session()
    
    async def _initialize_session(self):
        """Initialize HTTP session for load testing"""
        connector = aiohttp.TCPConnector(
            limit=200,  # Total connection pool size
            limit_per_host=50,  # Per-host connection limit
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "VoiceHive-LoadTester/1.0"}
        )
    
    async def _cleanup_session(self):
        """Cleanup HTTP session"""
        if self.session:
            await self.session.close()
    
    async def _run_scenario(self, scenario: LoadTestScenario) -> LoadTestResult:
        """Run a single load test scenario"""
        
        start_time = time.time()
        
        # Prepare authentication if required
        auth_headers = {}
        if scenario.auth_required:
            auth_headers = await self._get_auth_headers()
        
        # Combine headers
        headers = {**(scenario.headers or {}), **auth_headers}
        
        # Create tasks for concurrent execution
        tasks = []
        
        if scenario.duration_seconds:
            # Duration-based testing
            tasks = await self._create_duration_based_tasks(scenario, headers)
        else:
            # Request count-based testing
            tasks = await self._create_count_based_tasks(scenario, headers)
        
        # Execute all tasks concurrently
        response_times = []
        errors = []
        successful_requests = 0
        
        try:
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
            logger.error(f"Error executing scenario {scenario.name}: {e}")
            errors.append(str(e))
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Calculate statistics
        total_requests = len(tasks)
        failed_requests = total_requests - successful_requests
        success_rate = successful_requests / total_requests if total_requests > 0 else 0
        
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
        
        requests_per_second = total_requests / duration if duration > 0 else 0
        
        # Determine if scenario passed
        passed = (
            success_rate >= scenario.expected_success_rate and
            avg_response_time <= scenario.expected_response_time_ms
        )
        
        return LoadTestResult(
            scenario_name=scenario.name,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            success_rate=success_rate,
            average_response_time_ms=avg_response_time,
            median_response_time_ms=median_response_time,
            p95_response_time_ms=p95_response_time,
            p99_response_time_ms=p99_response_time,
            min_response_time_ms=min_response_time,
            max_response_time_ms=max_response_time,
            requests_per_second=requests_per_second,
            errors=errors[:10],  # Limit error list
            duration_seconds=duration,
            passed=passed
        )
    
    async def _create_count_based_tasks(self, scenario: LoadTestScenario, headers: Dict) -> List:
        """Create tasks for count-based load testing"""
        tasks = []
        
        for user_id in range(scenario.concurrent_users):
            for request_id in range(scenario.requests_per_user):
                task = self._make_request(
                    scenario=scenario,
                    headers=headers,
                    user_id=user_id,
                    request_id=request_id
                )
                tasks.append(task)
        
        return tasks
    
    async def _create_duration_based_tasks(self, scenario: LoadTestScenario, headers: Dict) -> List:
        """Create tasks for duration-based load testing"""
        tasks = []
        
        # Calculate request rate
        total_requests = scenario.concurrent_users * scenario.requests_per_user
        request_interval = scenario.duration_seconds / total_requests
        
        for user_id in range(scenario.concurrent_users):
            for request_id in range(scenario.requests_per_user):
                # Add delay to spread requests over duration
                delay = request_id * request_interval
                
                task = self._make_delayed_request(
                    scenario=scenario,
                    headers=headers,
                    user_id=user_id,
                    request_id=request_id,
                    delay=delay
                )
                tasks.append(task)
        
        return tasks
    
    async def _make_request(self, scenario: LoadTestScenario, headers: Dict, 
                          user_id: int, request_id: int) -> Dict:
        """Make a single HTTP request"""
        
        start_time = time.time()
        
        try:
            # Handle special mixed workload scenario
            if scenario.name == "mixed_production_workload":
                return await self._make_mixed_workload_request(headers, user_id, request_id)
            
            # Prepare request parameters
            url = f"{self.base_url}{scenario.endpoint}"
            
            # Add user-specific variations to payload
            payload = scenario.payload.copy() if scenario.payload else None
            if payload and 'user_id' not in payload:
                payload['user_id'] = f"load_test_user_{user_id}"
            
            # Make the request
            async with self.session.request(
                method=scenario.method,
                url=url,
                json=payload,
                headers=headers
            ) as response:
                
                # Read response (but don't store large responses)
                if response.content_length and response.content_length < 1024:
                    await response.text()
                else:
                    # Just read a small portion for large responses
                    await response.content.read(1024)
                
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
    
    async def _make_delayed_request(self, scenario: LoadTestScenario, headers: Dict,
                                  user_id: int, request_id: int, delay: float) -> Dict:
        """Make a request with initial delay"""
        await asyncio.sleep(delay)
        return await self._make_request(scenario, headers, user_id, request_id)
    
    async def _make_mixed_workload_request(self, headers: Dict, user_id: int, request_id: int) -> Dict:
        """Make a request simulating mixed production workload"""
        
        # Randomly select an endpoint to simulate realistic traffic distribution
        endpoints = [
            ("/health", "GET", None, 0.3),  # 30% health checks
            ("/auth/validate", "GET", None, 0.25),  # 25% auth validation
            ("/calls/events", "POST", {"event": "test"}, 0.2),  # 20% call events
            ("/pms/reservations/lookup", "GET", None, 0.15),  # 15% PMS lookups
            ("/tts/synthesize", "POST", {"text": "test"}, 0.1)  # 10% TTS requests
        ]
        
        # Select endpoint based on probability distribution
        rand = random.random()
        cumulative_prob = 0
        
        for endpoint, method, payload, prob in endpoints:
            cumulative_prob += prob
            if rand <= cumulative_prob:
                # Create a temporary scenario for this request
                temp_scenario = LoadTestScenario(
                    name="mixed_request",
                    description="Mixed workload request",
                    endpoint=endpoint,
                    method=method,
                    payload=payload
                )
                return await self._make_request(temp_scenario, headers, user_id, request_id)
        
        # Fallback to health check
        temp_scenario = LoadTestScenario(
            name="mixed_request",
            description="Mixed workload request",
            endpoint="/health",
            method="GET"
        )
        return await self._make_request(temp_scenario, headers, user_id, request_id)
    
    async def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for requests"""
        # In a real implementation, this would authenticate and get a real token
        # For testing, we'll use a mock token
        return {
            "Authorization": "Bearer mock_jwt_token_for_load_testing",
            "X-API-Key": "mock_api_key_for_load_testing"
        }
    
    def _generate_load_test_report(self, results: List[LoadTestResult]) -> Dict[str, Any]:
        """Generate comprehensive load test report"""
        
        total_tests = len(results)
        passed_tests = sum(1 for r in results if r.passed)
        overall_success = passed_tests == total_tests
        
        # Calculate aggregate statistics
        total_requests = sum(r.total_requests for r in results)
        total_successful = sum(r.successful_requests for r in results)
        total_failed = sum(r.failed_requests for r in results)
        
        overall_success_rate = total_successful / total_requests if total_requests > 0 else 0
        
        # Calculate average response times
        all_avg_times = [r.average_response_time_ms for r in results if r.average_response_time_ms > 0]
        overall_avg_response_time = statistics.mean(all_avg_times) if all_avg_times else 0
        
        # Find performance bottlenecks
        bottlenecks = []
        for result in results:
            if not result.passed:
                if result.success_rate < result.scenario_name:  # This should reference scenario expected success rate
                    bottlenecks.append(f"{result.scenario_name}: Low success rate ({result.success_rate:.2%})")
                if result.average_response_time_ms > 2000:  # Arbitrary threshold
                    bottlenecks.append(f"{result.scenario_name}: High response time ({result.average_response_time_ms:.0f}ms)")
        
        # Collect all errors
        all_errors = []
        for result in results:
            all_errors.extend(result.errors)
        
        # Get unique errors with counts
        error_counts = {}
        for error in all_errors:
            error_counts[error] = error_counts.get(error, 0) + 1
        
        return {
            'overall_success': overall_success,
            'tests_run': total_tests,
            'tests_passed': passed_tests,
            'tests_failed': total_tests - passed_tests,
            'total_requests': total_requests,
            'successful_requests': total_successful,
            'failed_requests': total_failed,
            'overall_success_rate': overall_success_rate,
            'average_response_time_ms': overall_avg_response_time,
            'max_concurrent_users_supported': max(s.concurrent_users for s in self.scenarios),
            'scenario_results': [
                {
                    'name': r.scenario_name,
                    'passed': r.passed,
                    'success_rate': r.success_rate,
                    'avg_response_time_ms': r.average_response_time_ms,
                    'requests_per_second': r.requests_per_second,
                    'total_requests': r.total_requests
                }
                for r in results
            ],
            'performance_bottlenecks': bottlenecks,
            'error_summary': dict(list(error_counts.items())[:10]),  # Top 10 errors
            'recommendations': self._generate_load_test_recommendations(results)
        }
    
    def _generate_load_test_recommendations(self, results: List[LoadTestResult]) -> List[str]:
        """Generate recommendations based on load test results"""
        recommendations = []
        
        # Check for high response times
        slow_scenarios = [r for r in results if r.average_response_time_ms > 1000]
        if slow_scenarios:
            recommendations.append(
                f"Optimize performance for {len(slow_scenarios)} slow scenarios: "
                f"{', '.join(r.scenario_name for r in slow_scenarios[:3])}"
            )
        
        # Check for low success rates
        unreliable_scenarios = [r for r in results if r.success_rate < 0.95]
        if unreliable_scenarios:
            recommendations.append(
                f"Improve reliability for {len(unreliable_scenarios)} scenarios with low success rates"
            )
        
        # Check for low throughput
        low_throughput = [r for r in results if r.requests_per_second < 10]
        if low_throughput:
            recommendations.append(
                "Consider scaling infrastructure to improve throughput for low-performing endpoints"
            )
        
        # General recommendations
        if not recommendations:
            recommendations.append("Load testing passed all scenarios. System is ready for production load.")
        
        return recommendations