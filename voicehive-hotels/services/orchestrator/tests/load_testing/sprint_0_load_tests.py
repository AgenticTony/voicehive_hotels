"""
Sprint 0 Load Testing Scenarios for VoiceHive Hotels
Complete implementation of Task 6: Load Testing Implementation

Implements the specific scenarios required by Sprint 0:
- Normal load: 50 concurrent users
- Peak load: 200 concurrent users
- Stress load: 500 concurrent users
- Spike load: 0-300-0 users in 5 minutes
- Database stress testing
- Circuit breaker load testing under stress
- Partner API (Apaleo) load testing
- Performance regression testing
"""

import os
import json
import time
import random
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import asyncpg
from locust import HttpUser, TaskSet, task, between, LoadTestShape, events
from locust.env import Environment
from locust.runners import LocalRunner
import gevent

logger = logging.getLogger(__name__)


@dataclass
class LoadTestScenario:
    """Configuration for a specific load test scenario"""
    name: str
    description: str
    users: int
    spawn_rate: int
    duration: int
    expected_rps: float
    max_failure_rate: float
    max_p95_response_time: int
    test_type: str  # normal, peak, stress, spike


class DatabaseStressUser(HttpUser):
    """
    User class specifically designed to stress test database operations
    """
    wait_time = between(0.5, 2)

    def on_start(self):
        """Initialize database stress testing user"""
        self.user_id = f"db_stress_{random.randint(1000, 9999)}"
        self.guest_id = f"guest_{random.randint(100000, 999999)}"

        # Authenticate
        with self.client.post("/auth/guest/login", json={
            "guest_id": self.guest_id,
            "room_number": f"{random.randint(101, 999)}",
            "last_name": "LoadTestGuest"
        }, catch_response=True) as response:
            if response.status_code == 200:
                self.auth_token = response.json().get("token", "mock_token")
                self.client.headers.update({"Authorization": f"Bearer {self.auth_token}"})

    @task(20)
    def intensive_database_queries(self):
        """Perform intensive database queries to stress the connection pool"""
        # Multiple concurrent database operations
        operations = [
            ("/api/guests/search", {"query": "test"}),
            ("/api/reservations/search", {"guest_id": self.guest_id}),
            ("/api/calls/history", {"guest_id": self.guest_id, "limit": 100}),
            ("/api/analytics/guest-stats", {"guest_id": self.guest_id}),
            ("/api/billing/transactions", {"guest_id": self.guest_id})
        ]

        for endpoint, params in operations:
            with self.client.get(endpoint, params=params, name=f"DB Query {endpoint}"):
                pass

    @task(15)
    def concurrent_writes(self):
        """Perform concurrent database writes to test transaction handling"""
        # Create call record
        call_data = {
            "guest_id": self.guest_id,
            "call_type": "information",
            "language": "en-US",
            "session_id": f"stress_session_{time.time()}"
        }

        with self.client.post("/calls/start", json=call_data, name="DB Write - Start Call") as response:
            if response.status_code == 200:
                call_id = response.json().get("call_id")

                # Add multiple events rapidly
                for i in range(5):
                    event_data = {
                        "call_id": call_id,
                        "event_type": f"stress_event_{i}",
                        "text": f"Database stress test event {i}",
                        "timestamp": datetime.utcnow().isoformat()
                    }

                    with self.client.post("/calls/events", json=event_data, name="DB Write - Add Event"):
                        pass

                # End call
                with self.client.post(f"/calls/{call_id}/end", name="DB Write - End Call"):
                    pass

    @task(10)
    def mfa_database_operations(self):
        """Stress test MFA-related database operations"""
        # Simulate MFA enrollment
        mfa_data = {
            "user_id": self.user_id,
            "secret": "test_secret_for_load_testing",
            "backup_codes": [f"backup_{i:06d}" for i in range(10)]
        }

        with self.client.post("/auth/mfa/enroll", json=mfa_data, name="DB Write - MFA Enroll"):
            pass

        # Verify MFA
        with self.client.post("/auth/mfa/verify", json={
            "user_id": self.user_id,
            "token": "123456"
        }, name="DB Query - MFA Verify"):
            pass

        # Check MFA status
        with self.client.get(f"/auth/mfa/status/{self.user_id}", name="DB Query - MFA Status"):
            pass

    @task(8)
    def analytics_heavy_queries(self):
        """Perform heavy analytics queries that stress the database"""
        # Complex analytics queries
        analytics_endpoints = [
            "/api/analytics/call-volume",
            "/api/analytics/performance-metrics",
            "/api/analytics/guest-satisfaction",
            "/api/analytics/system-health"
        ]

        for endpoint in analytics_endpoints:
            with self.client.get(endpoint, params={
                "start_date": (datetime.utcnow() - timedelta(days=30)).isoformat(),
                "end_date": datetime.utcnow().isoformat(),
                "granularity": "hour"
            }, name=f"Heavy Analytics {endpoint}"):
                pass


class CircuitBreakerStressUser(HttpUser):
    """
    User class designed to test circuit breaker behavior under high load
    """
    wait_time = between(0.1, 1)  # Aggressive timing to trigger circuit breakers

    def on_start(self):
        self.user_id = f"cb_stress_{random.randint(1000, 9999)}"
        self.failure_count = 0

    @task(25)
    def stress_apaleo_connector(self):
        """Aggressively test Apaleo connector to trigger circuit breakers"""
        # Rapid-fire requests to Apaleo endpoints
        apaleo_operations = [
            ("/pms/apaleo/reservations", {"action": "search"}),
            ("/pms/apaleo/rooms", {"action": "availability"}),
            ("/pms/apaleo/guests", {"action": "lookup"}),
            ("/pms/apaleo/billing", {"action": "charges"}),
            ("/pms/apaleo/services", {"action": "request"})
        ]

        for endpoint, data in apaleo_operations:
            with self.client.post(endpoint, json=data, name=f"CB Stress - {endpoint}") as response:
                if response.status_code >= 500:
                    self.failure_count += 1

    @task(20)
    def stress_tts_service(self):
        """Stress test TTS service to trigger circuit breakers"""
        # Rapid TTS requests
        tts_requests = [
            {"text": "This is a circuit breaker stress test for TTS service", "language": "en-US"},
            {"text": "Prueba de estrés del disyuntor para el servicio TTS", "language": "es-ES"},
            {"text": "Test de stress du disjoncteur pour le service TTS", "language": "fr-FR"},
            {"text": "Circuit Breaker Stresstest für TTS-Service", "language": "de-DE"},
            {"text": "TTS服务的断路器压力测试", "language": "zh-CN"}
        ]

        for tts_data in tts_requests:
            with self.client.post("/tts/synthesize", json=tts_data, name="CB Stress - TTS") as response:
                if response.status_code >= 500:
                    self.failure_count += 1

    @task(15)
    def stress_asr_service(self):
        """Stress test ASR service to trigger circuit breakers"""
        # Rapid ASR requests with mock audio data
        audio_data = {
            "audio": "mock_audio_data_" + "x" * 1024,
            "language": random.choice(["en-US", "es-ES", "fr-FR", "de-DE"]),
            "format": "wav"
        }

        with self.client.post("/asr/transcribe", json=audio_data, name="CB Stress - ASR") as response:
            if response.status_code >= 500:
                self.failure_count += 1

    @task(10)
    def check_circuit_breaker_status(self):
        """Monitor circuit breaker states during stress testing"""
        with self.client.get("/monitoring/circuit-breakers", name="CB Status Check") as response:
            if response.status_code == 200:
                cb_data = response.json()
                services = cb_data.get("services", {})

                # Log circuit breaker states
                for service, status in services.items():
                    open_breakers = status.get("open_breakers", 0)
                    if open_breakers > 0:
                        logger.warning(f"Service {service} has {open_breakers} open circuit breakers")

    @task(5)
    def trigger_failure_scenarios(self):
        """Intentionally trigger failure scenarios to test circuit breaker response"""
        # Send requests to non-existent endpoints to trigger failures
        failure_endpoints = [
            "/pms/apaleo/invalid-endpoint",
            "/tts/invalid-operation",
            "/asr/non-existent-method",
            "/invalid/service/endpoint"
        ]

        for endpoint in failure_endpoints:
            with self.client.get(endpoint, name="CB Trigger Failure", catch_response=True) as response:
                # We expect these to fail - mark as success if they fail properly
                if response.status_code >= 400:
                    response.success()


class PartnerAPIStressUser(HttpUser):
    """
    User class focused on testing partner API integrations (primarily Apaleo)
    """
    wait_time = between(1, 3)

    def on_start(self):
        self.guest_id = f"partner_test_{random.randint(100000, 999999)}"
        self.booking_ref = f"BK{random.randint(10000, 99999)}"

    @task(20)
    def apaleo_booking_flow(self):
        """Complete Apaleo booking flow testing"""
        # Check availability
        with self.client.get("/pms/apaleo/availability", params={
            "checkin": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "checkout": (datetime.utcnow() + timedelta(days=3)).isoformat(),
            "guests": 2
        }, name="Apaleo - Check Availability"):
            pass

        # Create reservation
        reservation_data = {
            "guest_id": self.guest_id,
            "checkin": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "checkout": (datetime.utcnow() + timedelta(days=3)).isoformat(),
            "room_type": "standard",
            "guests": 2,
            "booking_reference": self.booking_ref
        }

        with self.client.post("/pms/apaleo/reservations", json=reservation_data,
                            name="Apaleo - Create Reservation") as response:
            if response.status_code == 200:
                reservation_id = response.json().get("reservation_id")

                # Modify reservation
                with self.client.put(f"/pms/apaleo/reservations/{reservation_id}", json={
                    "special_requests": "Late checkout, quiet room"
                }, name="Apaleo - Modify Reservation"):
                    pass

    @task(15)
    def apaleo_payment_operations(self):
        """Test Apaleo payment processing under load"""
        payment_data = {
            "guest_id": self.guest_id,
            "amount": random.uniform(100, 500),
            "currency": "EUR",
            "payment_method": "credit_card",
            "card_token": f"token_{random.randint(1000, 9999)}"
        }

        # Authorize payment
        with self.client.post("/pms/apaleo/payments/authorize", json=payment_data,
                            name="Apaleo - Authorize Payment") as response:
            if response.status_code == 200:
                auth_id = response.json().get("authorization_id")

                # Capture payment
                with self.client.post(f"/pms/apaleo/payments/{auth_id}/capture",
                                    name="Apaleo - Capture Payment"):
                    pass

    @task(10)
    def apaleo_guest_services(self):
        """Test Apaleo guest service operations"""
        # Room service
        with self.client.post("/pms/apaleo/room-service", json={
            "guest_id": self.guest_id,
            "items": [{"name": "Club Sandwich", "quantity": 1}],
            "delivery_time": "ASAP"
        }, name="Apaleo - Room Service"):
            pass

        # Housekeeping request
        with self.client.post("/pms/apaleo/housekeeping", json={
            "guest_id": self.guest_id,
            "request_type": "extra_towels",
            "priority": "normal"
        }, name="Apaleo - Housekeeping"):
            pass

    @task(8)
    def apaleo_reporting_apis(self):
        """Test Apaleo reporting and analytics APIs"""
        # Occupancy report
        with self.client.get("/pms/apaleo/reports/occupancy", params={
            "date": datetime.utcnow().date().isoformat()
        }, name="Apaleo - Occupancy Report"):
            pass

        # Revenue report
        with self.client.get("/pms/apaleo/reports/revenue", params={
            "start_date": (datetime.utcnow() - timedelta(days=7)).date().isoformat(),
            "end_date": datetime.utcnow().date().isoformat()
        }, name="Apaleo - Revenue Report"):
            pass

    @task(5)
    def apaleo_bulk_operations(self):
        """Test Apaleo bulk operations that may stress the API"""
        # Bulk guest lookup
        guest_ids = [f"guest_{i}" for i in range(10)]
        with self.client.post("/pms/apaleo/guests/bulk-lookup", json={
            "guest_ids": guest_ids
        }, name="Apaleo - Bulk Guest Lookup"):
            pass

        # Bulk room status update
        room_updates = [
            {"room_number": f"{100 + i}", "status": "clean"}
            for i in range(20)
        ]
        with self.client.post("/pms/apaleo/rooms/bulk-update", json={
            "updates": room_updates
        }, name="Apaleo - Bulk Room Update"):
            pass


class PerformanceRegressionUser(HttpUser):
    """
    User class for performance regression testing
    Runs baseline performance tests to detect regressions
    """
    wait_time = between(1, 2)

    def on_start(self):
        self.user_id = f"regression_{random.randint(1000, 9999)}"
        self.baseline_times = {}

    @task(15)
    def baseline_api_performance(self):
        """Test baseline API performance for regression detection"""
        baseline_endpoints = [
            ("/api/health", "GET", None),
            ("/api/version", "GET", None),
            ("/monitoring/metrics/business", "GET", None),
            ("/monitoring/performance/summary", "GET", None),
            ("/api/calls/active", "GET", None)
        ]

        for endpoint, method, data in baseline_endpoints:
            start_time = time.time()

            if method == "GET":
                with self.client.get(endpoint, name=f"Baseline - {endpoint}") as response:
                    response_time = time.time() - start_time
                    self._record_baseline_time(endpoint, response_time)
            elif method == "POST":
                with self.client.post(endpoint, json=data, name=f"Baseline - {endpoint}") as response:
                    response_time = time.time() - start_time
                    self._record_baseline_time(endpoint, response_time)

    @task(10)
    def auth_flow_performance(self):
        """Test authentication flow performance"""
        start_time = time.time()

        # Login
        with self.client.post("/auth/guest/login", json={
            "guest_id": f"perf_test_{self.user_id}",
            "room_number": "101",
            "last_name": "RegressionTest"
        }, name="Baseline - Auth Login"):
            pass

        # MFA enrollment (if applicable)
        with self.client.post("/auth/mfa/enroll", json={
            "user_id": self.user_id
        }, name="Baseline - MFA Enroll"):
            pass

        total_time = time.time() - start_time
        self._record_baseline_time("auth_flow", total_time)

    @task(8)
    def database_query_performance(self):
        """Test database query performance for regression"""
        db_operations = [
            ("/api/guests/search", {"query": "test"}),
            ("/api/calls/history", {"limit": 50}),
            ("/api/analytics/call-volume", {"hours": 24})
        ]

        for endpoint, params in db_operations:
            start_time = time.time()
            with self.client.get(endpoint, params=params, name=f"DB Baseline - {endpoint}"):
                pass
            response_time = time.time() - start_time
            self._record_baseline_time(f"db_{endpoint}", response_time)

    def _record_baseline_time(self, operation: str, response_time: float):
        """Record baseline response time for regression comparison"""
        if operation not in self.baseline_times:
            self.baseline_times[operation] = []

        self.baseline_times[operation].append(response_time)

        # Log potential regression if response time is significantly higher
        if len(self.baseline_times[operation]) > 10:
            avg_time = sum(self.baseline_times[operation]) / len(self.baseline_times[operation])
            if response_time > avg_time * 1.5:  # 50% slower than average
                logger.warning(f"Potential regression detected in {operation}: "
                             f"{response_time:.3f}s vs avg {avg_time:.3f}s")


class Sprint0LoadShapes:
    """Load shapes for Sprint 0 specific scenarios"""

    class NormalLoadShape(LoadTestShape):
        """Normal load: 50 concurrent users"""

        def tick(self):
            run_time = self.get_run_time()

            if run_time < 60:  # Ramp up over 1 minute
                users = int(50 * (run_time / 60))
                return (users, 2)
            elif run_time < 300:  # Hold at 50 users for 4 minutes
                return (50, 2)
            else:
                return None

    class PeakLoadShape(LoadTestShape):
        """Peak load: 200 concurrent users"""

        def tick(self):
            run_time = self.get_run_time()

            if run_time < 120:  # Ramp up over 2 minutes
                users = int(200 * (run_time / 120))
                return (users, 5)
            elif run_time < 600:  # Hold at 200 users for 8 minutes
                return (200, 5)
            else:
                return None

    class StressLoadShape(LoadTestShape):
        """Stress load: 500 concurrent users"""

        def tick(self):
            run_time = self.get_run_time()

            if run_time < 180:  # Ramp up over 3 minutes
                users = int(500 * (run_time / 180))
                return (users, 10)
            elif run_time < 900:  # Hold at 500 users for 12 minutes
                return (500, 10)
            else:
                return None

    class SpikeLoadShape(LoadTestShape):
        """Spike load: 0-300-0 users in 5 minutes"""

        def tick(self):
            run_time = self.get_run_time()

            if run_time < 60:  # Ramp up to 300 in 1 minute
                users = int(300 * (run_time / 60))
                return (users, 15)
            elif run_time < 240:  # Hold at 300 for 3 minutes
                return (300, 15)
            elif run_time < 300:  # Ramp down to 0 in 1 minute
                users = int(300 * (1 - (run_time - 240) / 60))
                return (users, 15)
            else:
                return None


class Sprint0LoadTestRunner:
    """Coordinated runner for all Sprint 0 load test scenarios"""

    def __init__(self, target_host: str = "http://localhost:8000"):
        self.target_host = target_host
        self.scenarios = self._create_scenarios()
        self.results = {}

    def _create_scenarios(self) -> List[LoadTestScenario]:
        """Create all Sprint 0 load test scenarios"""
        return [
            LoadTestScenario(
                name="normal_load",
                description="Normal operational load - 50 concurrent users",
                users=50,
                spawn_rate=2,
                duration=300,
                expected_rps=50.0,
                max_failure_rate=0.01,
                max_p95_response_time=200,
                test_type="normal"
            ),
            LoadTestScenario(
                name="peak_load",
                description="Peak load scenario - 200 concurrent users",
                users=200,
                spawn_rate=5,
                duration=600,
                expected_rps=150.0,
                max_failure_rate=0.02,
                max_p95_response_time=500,
                test_type="peak"
            ),
            LoadTestScenario(
                name="stress_load",
                description="Stress test - 500 concurrent users",
                users=500,
                spawn_rate=10,
                duration=900,
                expected_rps=200.0,
                max_failure_rate=0.05,
                max_p95_response_time=1000,
                test_type="stress"
            ),
            LoadTestScenario(
                name="database_stress",
                description="Database stress testing with heavy queries",
                users=100,
                spawn_rate=5,
                duration=300,
                expected_rps=75.0,
                max_failure_rate=0.03,
                max_p95_response_time=800,
                test_type="database"
            ),
            LoadTestScenario(
                name="circuit_breaker_stress",
                description="Circuit breaker stress testing",
                users=150,
                spawn_rate=10,
                duration=300,
                expected_rps=100.0,
                max_failure_rate=0.1,  # Higher tolerance for circuit breaker testing
                max_p95_response_time=1500,
                test_type="circuit_breaker"
            ),
            LoadTestScenario(
                name="partner_api_stress",
                description="Partner API (Apaleo) stress testing",
                users=75,
                spawn_rate=3,
                duration=600,
                expected_rps=40.0,
                max_failure_rate=0.02,
                max_p95_response_time=2000,  # External API tolerance
                test_type="partner_api"
            ),
            LoadTestScenario(
                name="performance_regression",
                description="Performance regression baseline testing",
                users=50,
                spawn_rate=2,
                duration=300,
                expected_rps=50.0,
                max_failure_rate=0.01,
                max_p95_response_time=200,
                test_type="regression"
            )
        ]

    def run_all_scenarios(self) -> Dict[str, Any]:
        """Run all Sprint 0 load test scenarios"""
        logger.info("Starting Sprint 0 comprehensive load testing")

        overall_results = {
            "test_run_id": f"sprint0_{int(time.time())}",
            "start_time": datetime.utcnow().isoformat(),
            "target_host": self.target_host,
            "scenarios": {},
            "summary": {},
            "recommendations": []
        }

        for scenario in self.scenarios:
            logger.info(f"Running scenario: {scenario.name}")

            try:
                result = self._run_scenario(scenario)
                overall_results["scenarios"][scenario.name] = result

                # Check if scenario passed
                passed = self._evaluate_scenario_results(scenario, result)
                result["passed"] = passed

                logger.info(f"Scenario {scenario.name}: {'PASSED' if passed else 'FAILED'}")

            except Exception as e:
                logger.error(f"Scenario {scenario.name} failed with error: {e}")
                overall_results["scenarios"][scenario.name] = {
                    "error": str(e),
                    "passed": False
                }

        # Generate overall summary and recommendations
        overall_results["summary"] = self._generate_overall_summary(overall_results["scenarios"])
        overall_results["recommendations"] = self._generate_recommendations(overall_results["scenarios"])
        overall_results["end_time"] = datetime.utcnow().isoformat()

        # Save comprehensive report
        self._save_comprehensive_report(overall_results)

        return overall_results

    def _run_scenario(self, scenario: LoadTestScenario) -> Dict[str, Any]:
        """Run a specific load test scenario"""
        # Select appropriate user class based on scenario type
        user_classes = {
            "normal": [DatabaseStressUser, PartnerAPIStressUser, PerformanceRegressionUser],
            "peak": [DatabaseStressUser, PartnerAPIStressUser, PerformanceRegressionUser],
            "stress": [DatabaseStressUser, PartnerAPIStressUser, PerformanceRegressionUser],
            "database": [DatabaseStressUser],
            "circuit_breaker": [CircuitBreakerStressUser],
            "partner_api": [PartnerAPIStressUser],
            "regression": [PerformanceRegressionUser]
        }

        # Create environment
        env = Environment(
            user_classes=user_classes.get(scenario.test_type, [DatabaseStressUser]),
            host=self.target_host
        )

        # Create runner
        runner = env.create_local_runner()

        # Start test
        runner.start(scenario.users, spawn_rate=scenario.spawn_rate)

        # Run for specified duration
        gevent.sleep(scenario.duration)

        # Stop test
        runner.stop()

        # Collect results
        stats = env.stats

        return {
            "scenario": scenario.name,
            "duration": scenario.duration,
            "total_requests": stats.total.num_requests,
            "total_failures": stats.total.num_failures,
            "failure_rate": stats.total.fail_ratio,
            "requests_per_second": stats.total.total_rps,
            "average_response_time": stats.total.avg_response_time,
            "median_response_time": stats.total.median_response_time,
            "p95_response_time": stats.total.get_response_time_percentile(0.95),
            "p99_response_time": stats.total.get_response_time_percentile(0.99),
            "min_response_time": stats.total.min_response_time,
            "max_response_time": stats.total.max_response_time,
            "endpoints": {
                name: {
                    "requests": stat.num_requests,
                    "failures": stat.num_failures,
                    "avg_response_time": stat.avg_response_time,
                    "failure_rate": stat.fail_ratio
                }
                for name, stat in stats.entries.items()
                if stat.num_requests > 0
            }
        }

    def _evaluate_scenario_results(self, scenario: LoadTestScenario, results: Dict[str, Any]) -> bool:
        """Evaluate if scenario results meet expectations"""
        # Check failure rate
        if results["failure_rate"] > scenario.max_failure_rate:
            logger.warning(f"Scenario {scenario.name}: Failure rate {results['failure_rate']:.3f} "
                         f"exceeds maximum {scenario.max_failure_rate:.3f}")
            return False

        # Check P95 response time
        if results["p95_response_time"] > scenario.max_p95_response_time:
            logger.warning(f"Scenario {scenario.name}: P95 response time {results['p95_response_time']:.1f}ms "
                         f"exceeds maximum {scenario.max_p95_response_time}ms")
            return False

        # Check minimum throughput (for non-stress tests)
        if scenario.test_type != "stress" and results["requests_per_second"] < scenario.expected_rps * 0.8:
            logger.warning(f"Scenario {scenario.name}: RPS {results['requests_per_second']:.1f} "
                         f"below expected {scenario.expected_rps:.1f}")
            return False

        return True

    def _generate_overall_summary(self, scenarios: Dict[str, Any]) -> Dict[str, Any]:
        """Generate overall test summary"""
        total_scenarios = len(scenarios)
        passed_scenarios = sum(1 for result in scenarios.values() if result.get("passed", False))

        return {
            "total_scenarios": total_scenarios,
            "passed_scenarios": passed_scenarios,
            "failed_scenarios": total_scenarios - passed_scenarios,
            "success_rate": passed_scenarios / total_scenarios if total_scenarios > 0 else 0,
            "overall_status": "PASSED" if passed_scenarios == total_scenarios else "FAILED"
        }

    def _generate_recommendations(self, scenarios: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on test results"""
        recommendations = []

        # Analyze each scenario
        for scenario_name, result in scenarios.items():
            if not result.get("passed", False):
                if result.get("failure_rate", 0) > 0.05:
                    recommendations.append(f"High failure rate in {scenario_name} - investigate error handling")

                if result.get("p95_response_time", 0) > 1000:
                    recommendations.append(f"High response times in {scenario_name} - optimize performance")

        # General recommendations
        circuit_breaker_result = scenarios.get("circuit_breaker_stress")
        if circuit_breaker_result and circuit_breaker_result.get("passed", False):
            recommendations.append("Circuit breakers are functioning correctly under stress")

        database_result = scenarios.get("database_stress")
        if database_result and not database_result.get("passed", False):
            recommendations.append("Database performance issues detected - consider connection pool tuning")

        partner_api_result = scenarios.get("partner_api_stress")
        if partner_api_result and not partner_api_result.get("passed", False):
            recommendations.append("Partner API performance issues - implement caching or rate limiting")

        if not recommendations:
            recommendations.append("All load test scenarios passed - system is performing well under load")

        return recommendations

    def _save_comprehensive_report(self, results: Dict[str, Any]):
        """Save comprehensive test report"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_file = f"sprint0_load_test_report_{timestamp}.json"

        try:
            with open(report_file, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            logger.info(f"Comprehensive load test report saved to {report_file}")
        except Exception as e:
            logger.error(f"Failed to save comprehensive report: {e}")


# CLI interface for Sprint 0 load testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sprint 0 Load Testing Suite")
    parser.add_argument("--scenario", choices=[
        "all", "normal", "peak", "stress", "spike", "database",
        "circuit_breaker", "partner_api", "regression"
    ], default="all", help="Load test scenario to run")
    parser.add_argument("--host", default="http://localhost:8000", help="Target host")
    parser.add_argument("--duration", type=int, help="Override test duration")
    parser.add_argument("--users", type=int, help="Override user count")

    args = parser.parse_args()

    # Initialize runner
    runner = Sprint0LoadTestRunner(args.host)

    if args.scenario == "all":
        print("🚀 Running all Sprint 0 load test scenarios...")
        results = runner.run_all_scenarios()

        print(f"\n📊 Overall Results:")
        print(f"Scenarios: {results['summary']['passed_scenarios']}/{results['summary']['total_scenarios']} passed")
        print(f"Status: {results['summary']['overall_status']}")

        print(f"\n💡 Recommendations:")
        for rec in results['recommendations']:
            print(f"• {rec}")

    else:
        # Run single scenario
        scenario = next((s for s in runner.scenarios if s.name == args.scenario), None)
        if not scenario:
            print(f"❌ Unknown scenario: {args.scenario}")
            exit(1)

        # Apply overrides
        if args.duration:
            scenario.duration = args.duration
        if args.users:
            scenario.users = args.users

        print(f"🚀 Running {scenario.name} scenario...")
        print(f"Target: {args.host}")
        print(f"Users: {scenario.users}, Duration: {scenario.duration}s")

        result = runner._run_scenario(scenario)
        passed = runner._evaluate_scenario_results(scenario, result)

        print(f"\n📊 Results:")
        print(f"Status: {'PASSED' if passed else 'FAILED'}")
        print(f"Total Requests: {result['total_requests']}")
        print(f"Failure Rate: {result['failure_rate']:.2%}")
        print(f"Avg Response Time: {result['average_response_time']:.1f}ms")
        print(f"P95 Response Time: {result['p95_response_time']:.1f}ms")
        print(f"Requests/sec: {result['requests_per_second']:.1f}")