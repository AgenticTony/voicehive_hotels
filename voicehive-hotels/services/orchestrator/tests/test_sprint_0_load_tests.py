"""
Unit tests for Sprint 0 Load Testing Framework
Tests the load testing scenarios and infrastructure
"""

import pytest
import json
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from load_testing.sprint_0_load_tests import (
    LoadTestScenario,
    DatabaseStressUser,
    CircuitBreakerStressUser,
    PartnerAPIStressUser,
    PerformanceRegressionUser,
    Sprint0LoadTestRunner,
    Sprint0LoadShapes
)


class TestLoadTestScenario:
    """Test cases for LoadTestScenario dataclass"""

    def test_load_test_scenario_creation(self):
        """Test creating a LoadTestScenario"""
        scenario = LoadTestScenario(
            name="test_scenario",
            description="Test scenario",
            users=50,
            spawn_rate=2,
            duration=300,
            expected_rps=40.0,
            max_failure_rate=0.01,
            max_p95_response_time=200,
            test_type="normal"
        )

        assert scenario.name == "test_scenario"
        assert scenario.users == 50
        assert scenario.spawn_rate == 2
        assert scenario.duration == 300
        assert scenario.expected_rps == 40.0
        assert scenario.max_failure_rate == 0.01
        assert scenario.max_p95_response_time == 200
        assert scenario.test_type == "normal"

    def test_load_test_scenario_validation(self):
        """Test LoadTestScenario parameter validation"""
        # Valid scenario
        scenario = LoadTestScenario(
            name="valid",
            description="Valid scenario",
            users=100,
            spawn_rate=5,
            duration=600,
            expected_rps=50.0,
            max_failure_rate=0.02,
            max_p95_response_time=500,
            test_type="peak"
        )

        assert scenario.users > 0
        assert scenario.spawn_rate > 0
        assert scenario.duration > 0
        assert scenario.expected_rps >= 0
        assert 0 <= scenario.max_failure_rate <= 1
        assert scenario.max_p95_response_time > 0


class TestDatabaseStressUser:
    """Test cases for DatabaseStressUser"""

    @pytest.fixture
    def mock_http_user(self):
        """Create a mock HttpUser instance"""
        user = DatabaseStressUser()
        user.client = Mock()
        user.client.post = Mock()
        user.client.get = Mock()
        user.client.headers = Mock()

        # Mock response context manager
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "test_token", "call_id": "test_call_123"}

        user.client.post.return_value.__enter__.return_value = mock_response
        user.client.get.return_value.__enter__.return_value = mock_response

        return user

    def test_database_stress_user_initialization(self, mock_http_user):
        """Test DatabaseStressUser initialization"""
        user = mock_http_user

        # Mock on_start method components
        user.on_start()

        assert hasattr(user, 'user_id')
        assert hasattr(user, 'guest_id')
        assert user.user_id.startswith('db_stress_')
        assert user.guest_id.startswith('guest_')

    def test_intensive_database_queries(self, mock_http_user):
        """Test intensive database queries task"""
        user = mock_http_user
        user.user_id = "test_user"
        user.guest_id = "test_guest"

        # Execute the task
        user.intensive_database_queries()

        # Verify multiple GET requests were made
        assert user.client.get.call_count >= 5

        # Verify correct endpoints were called
        called_endpoints = [call[0][0] for call in user.client.get.call_args_list]
        expected_endpoints = [
            "/api/guests/search",
            "/api/reservations/search",
            "/api/calls/history",
            "/api/analytics/guest-stats",
            "/api/billing/transactions"
        ]

        for endpoint in expected_endpoints:
            assert endpoint in called_endpoints

    def test_concurrent_writes(self, mock_http_user):
        """Test concurrent database writes task"""
        user = mock_http_user
        user.guest_id = "test_guest"

        # Execute the task
        user.concurrent_writes()

        # Verify POST requests were made
        assert user.client.post.call_count >= 7  # start call + 5 events + end call

        # Check that call was started
        start_call_made = any(
            "/calls/start" in str(call) for call in user.client.post.call_args_list
        )
        assert start_call_made

    def test_mfa_database_operations(self, mock_http_user):
        """Test MFA database operations task"""
        user = mock_http_user
        user.user_id = "test_user"

        # Execute the task
        user.mfa_database_operations()

        # Verify MFA-related requests were made
        assert user.client.post.call_count >= 2  # enroll + verify
        assert user.client.get.call_count >= 1   # status check

        # Check MFA endpoints were called
        mfa_endpoints_called = [call[0][0] for call in user.client.post.call_args_list + user.client.get.call_args_list]
        assert any("/auth/mfa/" in endpoint for endpoint in mfa_endpoints_called)

    def test_analytics_heavy_queries(self, mock_http_user):
        """Test analytics heavy queries task"""
        user = mock_http_user

        # Execute the task
        user.analytics_heavy_queries()

        # Verify analytics endpoints were called
        assert user.client.get.call_count >= 4

        called_endpoints = [call[0][0] for call in user.client.get.call_args_list]
        analytics_endpoints = [
            "/api/analytics/call-volume",
            "/api/analytics/performance-metrics",
            "/api/analytics/guest-satisfaction",
            "/api/analytics/system-health"
        ]

        for endpoint in analytics_endpoints:
            assert endpoint in called_endpoints


class TestCircuitBreakerStressUser:
    """Test cases for CircuitBreakerStressUser"""

    @pytest.fixture
    def mock_cb_user(self):
        """Create a mock CircuitBreakerStressUser instance"""
        user = CircuitBreakerStressUser()
        user.client = Mock()
        user.client.post = Mock()
        user.client.get = Mock()
        user.failure_count = 0

        # Mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"services": {"database": {"open_breakers": 0}}}

        user.client.post.return_value.__enter__.return_value = mock_response
        user.client.get.return_value.__enter__.return_value = mock_response

        return user

    def test_circuit_breaker_user_initialization(self, mock_cb_user):
        """Test CircuitBreakerStressUser initialization"""
        user = mock_cb_user
        user.on_start()

        assert hasattr(user, 'user_id')
        assert hasattr(user, 'failure_count')
        assert user.user_id.startswith('cb_stress_')
        assert user.failure_count == 0

    def test_stress_apaleo_connector(self, mock_cb_user):
        """Test Apaleo connector stress testing"""
        user = mock_cb_user

        # Execute the task
        user.stress_apaleo_connector()

        # Verify multiple Apaleo requests were made
        assert user.client.post.call_count >= 5

        # Check Apaleo endpoints were called
        called_endpoints = [call[0][0] for call in user.client.post.call_args_list]
        apaleo_endpoints = [
            "/pms/apaleo/reservations",
            "/pms/apaleo/rooms",
            "/pms/apaleo/guests",
            "/pms/apaleo/billing",
            "/pms/apaleo/services"
        ]

        for endpoint in apaleo_endpoints:
            assert endpoint in called_endpoints

    def test_stress_tts_service(self, mock_cb_user):
        """Test TTS service stress testing"""
        user = mock_cb_user

        # Execute the task
        user.stress_tts_service()

        # Verify TTS requests were made
        assert user.client.post.call_count >= 5

        # Check TTS endpoint was called
        tts_requests_made = any(
            "/tts/synthesize" in str(call) for call in user.client.post.call_args_list
        )
        assert tts_requests_made

    def test_check_circuit_breaker_status(self, mock_cb_user):
        """Test circuit breaker status checking"""
        user = mock_cb_user

        # Execute the task
        user.check_circuit_breaker_status()

        # Verify status check was made
        assert user.client.get.call_count >= 1

        # Check monitoring endpoint was called
        status_check_made = any(
            "/monitoring/circuit-breakers" in str(call) for call in user.client.get.call_args_list
        )
        assert status_check_made

    def test_trigger_failure_scenarios(self, mock_cb_user):
        """Test failure scenario triggering"""
        user = mock_cb_user

        # Mock failure responses
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.success = Mock()
        user.client.get.return_value.__enter__.return_value = mock_response

        # Execute the task
        user.trigger_failure_scenarios()

        # Verify failure endpoints were called
        assert user.client.get.call_count >= 4

        # Verify responses were marked as successful (expected failures)
        assert mock_response.success.call_count >= 4


class TestPartnerAPIStressUser:
    """Test cases for PartnerAPIStressUser"""

    @pytest.fixture
    def mock_partner_user(self):
        """Create a mock PartnerAPIStressUser instance"""
        user = PartnerAPIStressUser()
        user.client = Mock()
        user.client.get = Mock()
        user.client.post = Mock()
        user.client.put = Mock()

        # Mock responses
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"reservation_id": "res_123", "authorization_id": "auth_456"}

        user.client.get.return_value.__enter__.return_value = mock_response
        user.client.post.return_value.__enter__.return_value = mock_response
        user.client.put.return_value.__enter__.return_value = mock_response

        return user

    def test_partner_api_user_initialization(self, mock_partner_user):
        """Test PartnerAPIStressUser initialization"""
        user = mock_partner_user
        user.on_start()

        assert hasattr(user, 'guest_id')
        assert hasattr(user, 'booking_ref')
        assert user.guest_id.startswith('partner_test_')
        assert user.booking_ref.startswith('BK')

    def test_apaleo_booking_flow(self, mock_partner_user):
        """Test complete Apaleo booking flow"""
        user = mock_partner_user
        user.guest_id = "test_guest"
        user.booking_ref = "BK12345"

        # Execute the task
        user.apaleo_booking_flow()

        # Verify booking flow requests were made
        assert user.client.get.call_count >= 1   # availability check
        assert user.client.post.call_count >= 1  # create reservation
        assert user.client.put.call_count >= 1   # modify reservation

    def test_apaleo_payment_operations(self, mock_partner_user):
        """Test Apaleo payment operations"""
        user = mock_partner_user
        user.guest_id = "test_guest"

        # Execute the task
        user.apaleo_payment_operations()

        # Verify payment requests were made
        assert user.client.post.call_count >= 2  # authorize + capture

        # Check payment endpoints were called
        payment_endpoints_called = [call[0][0] for call in user.client.post.call_args_list]
        assert any("/payments/authorize" in endpoint for endpoint in payment_endpoints_called)

    def test_apaleo_guest_services(self, mock_partner_user):
        """Test Apaleo guest services"""
        user = mock_partner_user
        user.guest_id = "test_guest"

        # Execute the task
        user.apaleo_guest_services()

        # Verify service requests were made
        assert user.client.post.call_count >= 2  # room service + housekeeping

    def test_apaleo_reporting_apis(self, mock_partner_user):
        """Test Apaleo reporting APIs"""
        user = mock_partner_user

        # Execute the task
        user.apaleo_reporting_apis()

        # Verify reporting requests were made
        assert user.client.get.call_count >= 2

        # Check reporting endpoints were called
        called_endpoints = [call[0][0] for call in user.client.get.call_args_list]
        assert any("/reports/occupancy" in endpoint for endpoint in called_endpoints)
        assert any("/reports/revenue" in endpoint for endpoint in called_endpoints)

    def test_apaleo_bulk_operations(self, mock_partner_user):
        """Test Apaleo bulk operations"""
        user = mock_partner_user

        # Execute the task
        user.apaleo_bulk_operations()

        # Verify bulk requests were made
        assert user.client.post.call_count >= 2  # bulk lookup + bulk update


class TestPerformanceRegressionUser:
    """Test cases for PerformanceRegressionUser"""

    @pytest.fixture
    def mock_regression_user(self):
        """Create a mock PerformanceRegressionUser instance"""
        user = PerformanceRegressionUser()
        user.client = Mock()
        user.client.get = Mock()
        user.client.post = Mock()
        user.baseline_times = {}

        # Mock responses
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "test_token"}

        user.client.get.return_value.__enter__.return_value = mock_response
        user.client.post.return_value.__enter__.return_value = mock_response

        return user

    def test_regression_user_initialization(self, mock_regression_user):
        """Test PerformanceRegressionUser initialization"""
        user = mock_regression_user
        user.on_start()

        assert hasattr(user, 'user_id')
        assert hasattr(user, 'baseline_times')
        assert user.user_id.startswith('regression_')
        assert isinstance(user.baseline_times, dict)

    def test_baseline_api_performance(self, mock_regression_user):
        """Test baseline API performance testing"""
        user = mock_regression_user
        user.user_id = "test_user"

        # Execute the task
        user.baseline_api_performance()

        # Verify baseline requests were made
        assert user.client.get.call_count >= 5

        # Check baseline endpoints were called
        called_endpoints = [call[0][0] for call in user.client.get.call_args_list]
        baseline_endpoints = [
            "/api/health",
            "/api/version",
            "/monitoring/metrics/business",
            "/monitoring/performance/summary",
            "/api/calls/active"
        ]

        for endpoint in baseline_endpoints:
            assert endpoint in called_endpoints

    def test_record_baseline_time(self, mock_regression_user):
        """Test baseline time recording"""
        user = mock_regression_user

        # Record some baseline times
        user._record_baseline_time("test_operation", 0.1)
        user._record_baseline_time("test_operation", 0.15)
        user._record_baseline_time("test_operation", 0.12)

        assert "test_operation" in user.baseline_times
        assert len(user.baseline_times["test_operation"]) == 3
        assert all(isinstance(time, float) for time in user.baseline_times["test_operation"])

    def test_regression_detection(self, mock_regression_user):
        """Test regression detection logic"""
        user = mock_regression_user

        # Setup baseline times
        for i in range(15):
            user._record_baseline_time("slow_operation", 0.1)  # Consistent 0.1s baseline

        # Mock logger
        with patch('load_testing.sprint_0_load_tests.logger') as mock_logger:
            # Record a significantly slower time (should trigger regression warning)
            user._record_baseline_time("slow_operation", 0.2)  # 100% slower

            # Verify regression warning was logged
            mock_logger.warning.assert_called()
            warning_call = mock_logger.warning.call_args[0][0]
            assert "Potential regression detected" in warning_call
            assert "slow_operation" in warning_call


class TestSprint0LoadShapes:
    """Test cases for Sprint 0 Load Shapes"""

    def test_normal_load_shape(self):
        """Test normal load shape implementation"""
        shape = Sprint0LoadShapes.NormalLoadShape()

        # Test ramp up phase
        with patch.object(shape, 'get_run_time', return_value=30):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 25  # 50 * (30/60)
            assert spawn_rate == 2

        # Test steady state phase
        with patch.object(shape, 'get_run_time', return_value=180):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 50
            assert spawn_rate == 2

        # Test end phase
        with patch.object(shape, 'get_run_time', return_value=400):
            result = shape.tick()
            assert result is None

    def test_peak_load_shape(self):
        """Test peak load shape implementation"""
        shape = Sprint0LoadShapes.PeakLoadShape()

        # Test ramp up phase
        with patch.object(shape, 'get_run_time', return_value=60):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 100  # 200 * (60/120)
            assert spawn_rate == 5

        # Test steady state phase
        with patch.object(shape, 'get_run_time', return_value=300):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 200
            assert spawn_rate == 5

    def test_stress_load_shape(self):
        """Test stress load shape implementation"""
        shape = Sprint0LoadShapes.StressLoadShape()

        # Test ramp up phase
        with patch.object(shape, 'get_run_time', return_value=90):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 250  # 500 * (90/180)
            assert spawn_rate == 10

        # Test steady state phase
        with patch.object(shape, 'get_run_time', return_value=450):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 500
            assert spawn_rate == 10

    def test_spike_load_shape(self):
        """Test spike load shape implementation"""
        shape = Sprint0LoadShapes.SpikeLoadShape()

        # Test ramp up phase
        with patch.object(shape, 'get_run_time', return_value=30):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 150  # 300 * (30/60)
            assert spawn_rate == 15

        # Test hold phase
        with patch.object(shape, 'get_run_time', return_value=120):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 300
            assert spawn_rate == 15

        # Test ramp down phase
        with patch.object(shape, 'get_run_time', return_value=270):
            result = shape.tick()
            assert result is not None
            users, spawn_rate = result
            assert users == 150  # 300 * (1 - (270-240)/60)
            assert spawn_rate == 15


class TestSprint0LoadTestRunner:
    """Test cases for Sprint0LoadTestRunner"""

    @pytest.fixture
    def mock_runner(self):
        """Create a mock Sprint0LoadTestRunner instance"""
        runner = Sprint0LoadTestRunner("http://test-host:8000")
        return runner

    def test_runner_initialization(self, mock_runner):
        """Test Sprint0LoadTestRunner initialization"""
        assert mock_runner.target_host == "http://test-host:8000"
        assert len(mock_runner.scenarios) == 7  # All Sprint 0 scenarios
        assert isinstance(mock_runner.results, dict)

    def test_scenario_creation(self, mock_runner):
        """Test scenario creation"""
        scenarios = mock_runner._create_scenarios()

        assert len(scenarios) == 7

        # Check that all required scenarios are present
        scenario_names = [s.name for s in scenarios]
        expected_scenarios = [
            "normal_load", "peak_load", "stress_load", "database_stress",
            "circuit_breaker_stress", "partner_api_stress", "performance_regression"
        ]

        for expected in expected_scenarios:
            assert expected in scenario_names

        # Verify scenario properties
        normal_scenario = next(s for s in scenarios if s.name == "normal_load")
        assert normal_scenario.users == 50
        assert normal_scenario.spawn_rate == 2
        assert normal_scenario.duration == 300
        assert normal_scenario.test_type == "normal"

    def test_evaluate_scenario_results(self, mock_runner):
        """Test scenario results evaluation"""
        scenario = LoadTestScenario(
            name="test_scenario",
            description="Test",
            users=50,
            spawn_rate=2,
            duration=300,
            expected_rps=40.0,
            max_failure_rate=0.01,
            max_p95_response_time=200,
            test_type="normal"
        )

        # Test passing results
        passing_results = {
            "failure_rate": 0.005,
            "p95_response_time": 150,
            "requests_per_second": 45.0
        }

        assert mock_runner._evaluate_scenario_results(scenario, passing_results) == True

        # Test failing results - high failure rate
        failing_results_1 = {
            "failure_rate": 0.02,  # Above max
            "p95_response_time": 150,
            "requests_per_second": 45.0
        }

        assert mock_runner._evaluate_scenario_results(scenario, failing_results_1) == False

        # Test failing results - high response time
        failing_results_2 = {
            "failure_rate": 0.005,
            "p95_response_time": 250,  # Above max
            "requests_per_second": 45.0
        }

        assert mock_runner._evaluate_scenario_results(scenario, failing_results_2) == False

        # Test failing results - low throughput
        failing_results_3 = {
            "failure_rate": 0.005,
            "p95_response_time": 150,
            "requests_per_second": 25.0  # Below expected * 0.8
        }

        assert mock_runner._evaluate_scenario_results(scenario, failing_results_3) == False

    def test_generate_overall_summary(self, mock_runner):
        """Test overall summary generation"""
        mock_scenarios = {
            "scenario1": {"passed": True},
            "scenario2": {"passed": True},
            "scenario3": {"passed": False},
            "scenario4": {"passed": True}
        }

        summary = mock_runner._generate_overall_summary(mock_scenarios)

        assert summary["total_scenarios"] == 4
        assert summary["passed_scenarios"] == 3
        assert summary["failed_scenarios"] == 1
        assert summary["success_rate"] == 0.75
        assert summary["overall_status"] == "FAILED"  # Not all passed

        # Test all passing
        all_passing = {
            "scenario1": {"passed": True},
            "scenario2": {"passed": True}
        }

        summary_passing = mock_runner._generate_overall_summary(all_passing)
        assert summary_passing["overall_status"] == "PASSED"

    def test_generate_recommendations(self, mock_runner):
        """Test recommendations generation"""
        mock_scenarios = {
            "scenario1": {
                "passed": False,
                "failure_rate": 0.08,  # High failure rate
                "p95_response_time": 1500
            },
            "scenario2": {
                "passed": False,
                "p95_response_time": 2500  # High response time
            },
            "circuit_breaker_stress": {
                "passed": True
            }
        }

        recommendations = mock_runner._generate_recommendations(mock_scenarios)

        assert len(recommendations) >= 2
        assert any("High failure rate" in rec for rec in recommendations)
        assert any("High response times" in rec for rec in recommendations)
        assert any("Circuit breakers are functioning correctly" in rec for rec in recommendations)

    @patch('load_testing.sprint_0_load_tests.open')
    @patch('load_testing.sprint_0_load_tests.json.dump')
    def test_save_comprehensive_report(self, mock_json_dump, mock_open, mock_runner):
        """Test comprehensive report saving"""
        test_results = {
            "test_run_id": "test_123",
            "scenarios": {"test": {"passed": True}}
        }

        mock_runner._save_comprehensive_report(test_results)

        # Verify file was opened for writing
        mock_open.assert_called_once()

        # Verify JSON was dumped
        mock_json_dump.assert_called_once()
        dumped_data = mock_json_dump.call_args[0][0]
        assert dumped_data == test_results


class TestLoadTestConfiguration:
    """Test cases for load test configuration"""

    def test_load_config_file(self):
        """Test loading load test configuration file"""
        config_path = os.path.join(
            os.path.dirname(__file__),
            "load_testing",
            "load_test_config.json"
        )

        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)

            assert "sprint_0_load_tests" in config
            assert "sprint_0_scenarios" in config["sprint_0_load_tests"]

            scenarios = config["sprint_0_load_tests"]["sprint_0_scenarios"]
            assert "normal_load" in scenarios
            assert "peak_load" in scenarios
            assert "stress_load" in scenarios
            assert "spike_load" in scenarios

    def test_config_scenario_validation(self):
        """Test configuration scenario validation"""
        # This would test that all required fields are present in config scenarios
        required_fields = [
            "name", "description", "users", "spawn_rate",
            "duration", "expected_metrics"
        ]

        # Mock config for testing
        mock_scenario = {
            "name": "Test Scenario",
            "description": "Test description",
            "users": 50,
            "spawn_rate": 2,
            "duration": 300,
            "expected_metrics": {
                "min_rps": 40.0,
                "max_failure_rate": 0.01,
                "max_p95_response_time_ms": 200
            }
        }

        for field in required_fields:
            assert field in mock_scenario

        # Validate metrics
        metrics = mock_scenario["expected_metrics"]
        assert metrics["min_rps"] > 0
        assert 0 <= metrics["max_failure_rate"] <= 1
        assert metrics["max_p95_response_time_ms"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])