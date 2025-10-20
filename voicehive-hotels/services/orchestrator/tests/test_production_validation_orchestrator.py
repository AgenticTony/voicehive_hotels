"""
Comprehensive unit tests for Production Validation Orchestrator
Tests orchestration logic, validation phases, and report generation
"""

import pytest
import asyncio
import json
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from pathlib import Path
from typing import Dict, Any, List

from production_validation_orchestrator import (
    ProductionValidationOrchestrator, ValidationPhase, ValidationPhaseResult,
    OrchestrationReport
)


@pytest.fixture
def mock_validator_modules():
    """Mock all validator module imports"""
    with patch('production_validation_orchestrator.ProductionReadinessValidator') as mock_prod_validator, \
         patch('production_validation_orchestrator.FunctionalProductionValidator') as mock_func_validator, \
         patch('production_validation_orchestrator.SecurityPenetrationTester') as mock_security_tester, \
         patch('production_validation_orchestrator.LoadTestingValidator') as mock_load_validator, \
         patch('production_validation_orchestrator.ProductionCertificationGenerator') as mock_cert_generator:

        yield {
            'prod_validator': mock_prod_validator,
            'func_validator': mock_func_validator,
            'security_tester': mock_security_tester,
            'load_validator': mock_load_validator,
            'cert_generator': mock_cert_generator
        }


@pytest.fixture
def orchestrator():
    """Production validation orchestrator for testing"""
    return ProductionValidationOrchestrator(
        base_url="http://test-system:8000",
        skip_phases=[]
    )


@pytest.fixture
def orchestrator_with_skipped_phases():
    """Orchestrator with some phases skipped"""
    return ProductionValidationOrchestrator(
        base_url="http://test-system:8000",
        skip_phases=["load_testing", "disaster_recovery"]
    )


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession for HTTP requests"""
    session_mock = AsyncMock()
    response_mock = AsyncMock()
    response_mock.status = 200
    response_mock.text = AsyncMock(return_value="OK")
    session_mock.get.return_value.__aenter__.return_value = response_mock
    session_mock.get.return_value.__aexit__.return_value = False
    return session_mock


class TestValidationDataModels:
    """Test validation data models and enums"""

    def test_validation_phase_enum(self):
        """Test ValidationPhase enum values"""
        assert ValidationPhase.INFRASTRUCTURE_CHECK.value == "infrastructure_check"
        assert ValidationPhase.PRODUCTION_READINESS.value == "production_readiness"
        assert ValidationPhase.SECURITY_TESTING.value == "security_testing"
        assert ValidationPhase.LOAD_TESTING.value == "load_testing"
        assert ValidationPhase.DISASTER_RECOVERY.value == "disaster_recovery"
        assert ValidationPhase.COMPLIANCE_VERIFICATION.value == "compliance_verification"
        assert ValidationPhase.CERTIFICATION_GENERATION.value == "certification_generation"

    def test_validation_phase_result_creation(self):
        """Test ValidationPhaseResult dataclass creation"""
        result = ValidationPhaseResult(
            phase=ValidationPhase.INFRASTRUCTURE_CHECK,
            status="PASSED",
            message="Infrastructure check completed successfully",
            duration=15.5,
            details={"checks": 5, "passed": 5},
            timestamp="2024-01-01T10:00:00Z"
        )

        assert result.phase == ValidationPhase.INFRASTRUCTURE_CHECK
        assert result.status == "PASSED"
        assert result.message == "Infrastructure check completed successfully"
        assert result.duration == 15.5
        assert result.details["checks"] == 5
        assert result.timestamp == "2024-01-01T10:00:00Z"

    def test_orchestration_report_creation(self):
        """Test OrchestrationReport dataclass creation"""
        phase_results = [
            ValidationPhaseResult(
                phase=ValidationPhase.INFRASTRUCTURE_CHECK,
                status="PASSED",
                message="Infrastructure check passed",
                duration=10.0,
                timestamp="2024-01-01T10:00:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.PRODUCTION_READINESS,
                status="FAILED",
                message="Production readiness failed",
                duration=25.0,
                timestamp="2024-01-01T10:00:30Z"
            )
        ]

        report = OrchestrationReport(
            overall_status="FAILED",
            total_phases=2,
            successful_phases=1,
            failed_phases=1,
            total_duration=35.0,
            timestamp="2024-01-01T10:01:00Z",
            phase_results=phase_results,
            recommendations=["Fix production readiness issues"]
        )

        assert report.overall_status == "FAILED"
        assert report.total_phases == 2
        assert report.successful_phases == 1
        assert report.failed_phases == 1
        assert report.total_duration == 35.0
        assert len(report.phase_results) == 2
        assert len(report.recommendations) == 1


class TestOrchestratorInitialization:
    """Test orchestrator initialization"""

    def test_init_with_defaults(self):
        """Test initialization with default parameters"""
        orchestrator = ProductionValidationOrchestrator()

        assert orchestrator.base_url == "http://localhost:8000"
        assert orchestrator.skip_phases == []
        assert len(orchestrator.phase_results) == 0
        assert isinstance(orchestrator.start_time, datetime)

    def test_init_with_custom_parameters(self):
        """Test initialization with custom parameters"""
        skip_phases = ["load_testing", "compliance_verification"]
        orchestrator = ProductionValidationOrchestrator(
            base_url="https://prod-system.example.com",
            skip_phases=skip_phases
        )

        assert orchestrator.base_url == "https://prod-system.example.com"
        assert orchestrator.skip_phases == skip_phases
        assert len(orchestrator.phase_results) == 0

    def test_init_with_none_skip_phases(self):
        """Test initialization with None skip_phases"""
        orchestrator = ProductionValidationOrchestrator(skip_phases=None)

        assert orchestrator.skip_phases == []


class TestInfrastructureCheck:
    """Test infrastructure check functionality"""

    @pytest.mark.asyncio
    async def test_infrastructure_check_all_passed(self, orchestrator, mock_aiohttp_session):
        """Test infrastructure check when all checks pass"""
        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.__import__') as mock_import:

            # Mock successful imports
            mock_import.return_value = Mock()

            result = await orchestrator._run_infrastructure_check()

            assert result["status"] == "PASSED"
            assert "infrastructure checks passed" in result["message"]
            assert "checks" in result["details"]
            assert len(result["details"]["checks"]) > 0

    @pytest.mark.asyncio
    async def test_infrastructure_check_system_health_failed(self, orchestrator):
        """Test infrastructure check when system health fails"""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session
            mock_session.get.side_effect = Exception("Connection refused")

            with patch('pathlib.Path.exists', return_value=True), \
                 patch('builtins.__import__'):

                result = await orchestrator._run_infrastructure_check()

                assert result["status"] == "FAILED"
                assert "infrastructure checks failed" in result["message"]
                assert "failed_checks" in result["details"]

                # Check that system health failure is recorded
                system_health_check = next(
                    (check for check in result["details"]["checks"]
                     if check["check"] == "System Health"), None
                )
                assert system_health_check is not None
                assert system_health_check["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_infrastructure_check_missing_directories(self, orchestrator, mock_aiohttp_session):
        """Test infrastructure check with missing directories"""
        def mock_path_exists(path_str):
            # Only first directory exists
            return "voicehive-hotels/services/orchestrator" in str(path_str)

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session), \
             patch('pathlib.Path.exists', side_effect=mock_path_exists), \
             patch('builtins.__import__'):

            result = await orchestrator._run_infrastructure_check()

            assert result["status"] == "FAILED"
            assert "failed_checks" in result["details"]

            # Check for missing directory failures
            failed_checks = result["details"]["failed_checks"]
            directory_failures = [check for check in failed_checks if "Directory" in check["check"]]
            assert len(directory_failures) > 0

    @pytest.mark.asyncio
    async def test_infrastructure_check_missing_dependencies(self, orchestrator, mock_aiohttp_session):
        """Test infrastructure check with missing Python dependencies"""
        def mock_import(name, *args, **kwargs):
            if name in ["aiohttp", "asyncpg", "redis", "psutil"]:
                raise ImportError(f"Module {name} not found")
            return Mock()

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.__import__', side_effect=mock_import):

            result = await orchestrator._run_infrastructure_check()

            assert result["status"] == "FAILED"

            # Check for dependency failure
            dependency_check = next(
                (check for check in result["details"]["checks"]
                 if check["check"] == "Python Dependencies"), None
            )
            assert dependency_check is not None
            assert dependency_check["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_infrastructure_check_http_status_error(self, orchestrator):
        """Test infrastructure check when HTTP returns non-200 status"""
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 503
        mock_session.get.return_value.__aenter__.return_value = mock_response
        mock_session.get.return_value.__aexit__.return_value = False

        with patch('aiohttp.ClientSession', return_value=mock_session), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.__import__'):

            result = await orchestrator._run_infrastructure_check()

            assert result["status"] == "FAILED"

            # Check that system health failure is recorded with correct status
            system_health_check = next(
                (check for check in result["details"]["checks"]
                 if check["check"] == "System Health"), None
            )
            assert system_health_check is not None
            assert system_health_check["status"] == "FAILED"
            assert "503" in system_health_check["message"]


class TestProductionReadinessValidation:
    """Test production readiness validation functionality"""

    @pytest.mark.asyncio
    async def test_production_readiness_validation_success(self, orchestrator, mock_validator_modules):
        """Test successful production readiness validation"""
        # Mock functional validator
        mock_func_report = Mock()
        mock_func_report.total_tests = 50
        mock_func_report.passed_tests = 48
        mock_func_report.failed_tests = 0
        mock_func_report.warning_tests = 2
        mock_func_report.total_duration = 120.5
        mock_func_report.summary = {"recommendations": ["Minor improvement needed"]}

        mock_func_instance = mock_validator_modules['func_validator'].return_value
        mock_func_instance.run_all_functional_tests.return_value = mock_func_report

        # Mock legacy validator
        mock_legacy_report = Mock()
        mock_legacy_report.total_tests = 25
        mock_legacy_report.passed_tests = 24
        mock_legacy_report.failed_tests = 0
        mock_legacy_report.warning_tests = 1
        mock_legacy_report.overall_status.value = "PASSED"
        mock_legacy_report.execution_time = 60.0
        mock_legacy_report.recommendations = ["Consider optimization"]

        mock_legacy_instance = mock_validator_modules['prod_validator'].return_value
        mock_legacy_instance.run_comprehensive_validation.return_value = mock_legacy_report

        result = await orchestrator._run_production_readiness_validation()

        assert result["status"] == "WARNING"  # Has warnings
        assert "72/75 tests passed" in result["message"]
        assert result["details"]["total_tests"] == 75
        assert result["details"]["passed_tests"] == 72
        assert result["details"]["failed_tests"] == 0
        assert result["details"]["warning_tests"] == 3

    @pytest.mark.asyncio
    async def test_production_readiness_validation_with_failures(self, orchestrator, mock_validator_modules):
        """Test production readiness validation with failures"""
        # Mock functional validator with failures
        mock_func_report = Mock()
        mock_func_report.total_tests = 50
        mock_func_report.passed_tests = 40
        mock_func_report.failed_tests = 8
        mock_func_report.warning_tests = 2
        mock_func_report.total_duration = 120.5
        mock_func_report.summary = {"recommendations": ["Fix critical issues"]}

        mock_func_instance = mock_validator_modules['func_validator'].return_value
        mock_func_instance.run_all_functional_tests.return_value = mock_func_report

        # Mock legacy validator
        mock_legacy_report = Mock()
        mock_legacy_report.total_tests = 25
        mock_legacy_report.passed_tests = 20
        mock_legacy_report.failed_tests = 3
        mock_legacy_report.warning_tests = 2
        mock_legacy_report.overall_status.value = "FAILED"
        mock_legacy_report.execution_time = 60.0
        mock_legacy_report.recommendations = ["Address failures"]

        mock_legacy_instance = mock_validator_modules['prod_validator'].return_value
        mock_legacy_instance.run_comprehensive_validation.return_value = mock_legacy_report

        result = await orchestrator._run_production_readiness_validation()

        assert result["status"] == "FAILED"  # Functional tests failed
        assert result["details"]["failed_tests"] == 11
        assert "60/75 tests passed" in result["message"]

    @pytest.mark.asyncio
    async def test_production_readiness_validation_exception(self, orchestrator, mock_validator_modules):
        """Test production readiness validation with exception"""
        mock_func_instance = mock_validator_modules['func_validator'].return_value
        mock_func_instance.run_all_functional_tests.side_effect = Exception("Validation failed")

        result = await orchestrator._run_production_readiness_validation()

        assert result["status"] == "ERROR"
        assert "Production readiness validation failed" in result["message"]
        assert "Validation failed" in result["details"]["error"]


class TestSecurityTesting:
    """Test security testing functionality"""

    @pytest.mark.asyncio
    async def test_security_testing_success(self, orchestrator, mock_validator_modules):
        """Test successful security testing"""
        mock_report = Mock()
        mock_report.critical_vulnerabilities = 0
        mock_report.high_vulnerabilities = 1
        mock_report.total_tests = 20
        mock_report.passed_tests = 18
        mock_report.vulnerable_tests = 2
        mock_report.execution_time = 300.0
        mock_report.recommendations = ["Fix high severity vulnerability"]

        mock_tester_instance = mock_validator_modules['security_tester'].return_value
        mock_tester_instance.run_comprehensive_security_tests.return_value = mock_report

        result = await orchestrator._run_security_testing()

        assert result["status"] == "PASSED"  # No critical vulnerabilities
        assert "0 critical vulnerabilities found" in result["message"]
        assert result["details"]["total_tests"] == 20
        assert result["details"]["critical_vulnerabilities"] == 0
        assert result["details"]["high_vulnerabilities"] == 1

    @pytest.mark.asyncio
    async def test_security_testing_with_critical_vulnerabilities(self, orchestrator, mock_validator_modules):
        """Test security testing with critical vulnerabilities"""
        mock_report = Mock()
        mock_report.critical_vulnerabilities = 3
        mock_report.high_vulnerabilities = 5
        mock_report.total_tests = 20
        mock_report.passed_tests = 10
        mock_report.vulnerable_tests = 10
        mock_report.execution_time = 300.0
        mock_report.recommendations = ["Fix critical vulnerabilities immediately"]

        mock_tester_instance = mock_validator_modules['security_tester'].return_value
        mock_tester_instance.run_comprehensive_security_tests.return_value = mock_report

        result = await orchestrator._run_security_testing()

        assert result["status"] == "FAILED"  # Critical vulnerabilities found
        assert "3 critical vulnerabilities found" in result["message"]
        assert result["details"]["critical_vulnerabilities"] == 3

    @pytest.mark.asyncio
    async def test_security_testing_exception(self, orchestrator, mock_validator_modules):
        """Test security testing with exception"""
        mock_tester_instance = mock_validator_modules['security_tester'].return_value
        mock_tester_instance.run_comprehensive_security_tests.side_effect = Exception("Security test failed")

        result = await orchestrator._run_security_testing()

        assert result["status"] == "ERROR"
        assert "Security testing failed" in result["message"]
        assert "Security test failed" in result["details"]["error"]


class TestLoadTesting:
    """Test load testing functionality"""

    @pytest.mark.asyncio
    async def test_load_testing_success(self, orchestrator, mock_validator_modules):
        """Test successful load testing"""
        mock_report = Mock()
        mock_report.overall_status.value = "PASSED"
        mock_report.total_tests = 15
        mock_report.passed_tests = 14
        mock_report.failed_tests = 0
        mock_report.warning_tests = 1
        mock_report.execution_time = 600.0
        mock_report.system_metrics = {"cpu_usage": 65.5, "memory_usage": 70.2}
        mock_report.recommendations = ["Optimize memory usage"]

        mock_validator_instance = mock_validator_modules['load_validator'].return_value
        mock_validator_instance.run_comprehensive_load_tests.return_value = mock_report

        result = await orchestrator._run_load_testing()

        assert result["status"] == "PASSED"
        assert "14/15 tests passed" in result["message"]
        assert result["details"]["total_tests"] == 15
        assert result["details"]["system_metrics"]["cpu_usage"] == 65.5

    @pytest.mark.asyncio
    async def test_load_testing_failed(self, orchestrator, mock_validator_modules):
        """Test failed load testing"""
        mock_report = Mock()
        mock_report.overall_status.value = "FAILED"
        mock_report.total_tests = 15
        mock_report.passed_tests = 10
        mock_report.failed_tests = 4
        mock_report.warning_tests = 1
        mock_report.execution_time = 600.0
        mock_report.system_metrics = {"cpu_usage": 95.0, "memory_usage": 90.0}
        mock_report.recommendations = ["Reduce load or scale up resources"]

        mock_validator_instance = mock_validator_modules['load_validator'].return_value
        mock_validator_instance.run_comprehensive_load_tests.return_value = mock_report

        result = await orchestrator._run_load_testing()

        assert result["status"] == "FAILED"
        assert "10/15 tests passed" in result["message"]
        assert result["details"]["failed_tests"] == 4

    @pytest.mark.asyncio
    async def test_load_testing_exception(self, orchestrator, mock_validator_modules):
        """Test load testing with exception"""
        mock_validator_instance = mock_validator_modules['load_validator'].return_value
        mock_validator_instance.run_comprehensive_load_tests.side_effect = Exception("Load test failed")

        result = await orchestrator._run_load_testing()

        assert result["status"] == "ERROR"
        assert "Load testing failed" in result["message"]


class TestDisasterRecoveryTesting:
    """Test disaster recovery testing functionality"""

    @pytest.mark.asyncio
    async def test_disaster_recovery_all_components_present(self, orchestrator):
        """Test disaster recovery when all components are present"""
        with patch('pathlib.Path.exists', return_value=True):
            result = await orchestrator._run_disaster_recovery_testing()

            assert result["status"] == "PASSED"
            assert "All disaster recovery components implemented" in result["message"]
            assert len(result["details"]["implemented_components"]) == 4
            assert len(result["details"]["missing_components"]) == 0

    @pytest.mark.asyncio
    async def test_disaster_recovery_some_components_missing(self, orchestrator):
        """Test disaster recovery with some components missing"""
        def mock_path_exists(path_str):
            # Only 2 out of 4 components exist
            return "disaster_recovery_manager.py" in str(path_str) or "velero-backup-schedule.yaml" in str(path_str)

        with patch('pathlib.Path.exists', side_effect=mock_path_exists):
            result = await orchestrator._run_disaster_recovery_testing()

            assert result["status"] == "WARNING"
            assert "2 DR components missing" in result["message"]
            assert len(result["details"]["implemented_components"]) == 2
            assert len(result["details"]["missing_components"]) == 2

    @pytest.mark.asyncio
    async def test_disaster_recovery_many_components_missing(self, orchestrator):
        """Test disaster recovery with many components missing"""
        def mock_path_exists(path_str):
            # Only 1 out of 4 components exists
            return "disaster_recovery_manager.py" in str(path_str)

        with patch('pathlib.Path.exists', side_effect=mock_path_exists):
            result = await orchestrator._run_disaster_recovery_testing()

            assert result["status"] == "FAILED"
            assert "3 DR components missing" in result["message"]
            assert len(result["details"]["implemented_components"]) == 1
            assert len(result["details"]["missing_components"]) == 3

    @pytest.mark.asyncio
    async def test_disaster_recovery_with_test_script(self, orchestrator):
        """Test disaster recovery with test script available"""
        def mock_path_exists(path_str):
            return "automated-dr-tests.sh" in str(path_str) or "disaster_recovery_manager.py" in str(path_str)

        with patch('pathlib.Path.exists', side_effect=mock_path_exists):
            result = await orchestrator._run_disaster_recovery_testing()

            assert "dr_test_results" in result["details"]
            assert result["details"]["dr_test_results"]["backup_test"] == "PASSED"
            assert result["details"]["dr_test_results"]["restore_test"] == "SIMULATED"

    @pytest.mark.asyncio
    async def test_disaster_recovery_exception(self, orchestrator):
        """Test disaster recovery with exception"""
        with patch('pathlib.Path.exists', side_effect=Exception("File system error")):
            result = await orchestrator._run_disaster_recovery_testing()

            assert result["status"] == "ERROR"
            assert "Disaster recovery testing failed" in result["message"]


class TestComplianceVerification:
    """Test compliance verification functionality"""

    @pytest.mark.asyncio
    async def test_compliance_verification_all_implemented(self, orchestrator):
        """Test compliance verification when all components are implemented"""
        with patch('pathlib.Path.exists', return_value=True):
            result = await orchestrator._run_compliance_verification()

            assert result["status"] == "PASSED"
            assert "All compliance components implemented" in result["message"]
            assert "100.0%" in result["details"]["compliance_coverage"]

    @pytest.mark.asyncio
    async def test_compliance_verification_some_missing(self, orchestrator):
        """Test compliance verification with some components missing"""
        def mock_path_exists(path_str):
            # Missing some components and configs
            return (
                "gdpr_compliance_manager.py" in str(path_str) or
                "compliance_monitoring_system.py" in str(path_str) or
                "gdpr-config.yaml" in str(path_str)
            )

        with patch('pathlib.Path.exists', side_effect=mock_path_exists):
            result = await orchestrator._run_compliance_verification()

            assert result["status"] == "WARNING" or result["status"] == "FAILED"
            assert "compliance items missing" in result["message"]
            assert len(result["details"]["missing_components"]) > 0

    @pytest.mark.asyncio
    async def test_compliance_verification_many_missing(self, orchestrator):
        """Test compliance verification with many components missing"""
        def mock_path_exists(path_str):
            # Only one component exists
            return "gdpr_compliance_manager.py" in str(path_str)

        with patch('pathlib.Path.exists', side_effect=mock_path_exists):
            result = await orchestrator._run_compliance_verification()

            assert result["status"] == "FAILED"
            assert len(result["details"]["missing_components"]) >= 5

    @pytest.mark.asyncio
    async def test_compliance_verification_exception(self, orchestrator):
        """Test compliance verification with exception"""
        with patch('pathlib.Path.exists', side_effect=Exception("Access denied")):
            result = await orchestrator._run_compliance_verification()

            assert result["status"] == "ERROR"
            assert "Compliance verification failed" in result["message"]


class TestCertificationGeneration:
    """Test certification generation functionality"""

    @pytest.mark.asyncio
    async def test_certification_generation_success(self, orchestrator, mock_validator_modules):
        """Test successful certification generation"""
        mock_report = Mock()
        mock_report.overall_status.value = "PASSED"
        mock_report.criteria = [
            Mock(status="PASSED"),
            Mock(status="PASSED"),
            Mock(status="FAILED"),
            Mock(status="PENDING")
        ]
        mock_report.recommendations = ["Address failed criteria"]

        mock_generator_instance = mock_validator_modules['cert_generator'].return_value
        mock_generator_instance.generate_certification_report.return_value = mock_report

        result = await orchestrator._run_certification_generation()

        assert result["status"] == "COMPLETED"
        assert "Certification report generated: PASSED" in result["message"]
        assert result["details"]["total_criteria"] == 4
        assert result["details"]["passed_criteria"] == 2
        assert result["details"]["failed_criteria"] == 1
        assert result["details"]["pending_criteria"] == 1

    @pytest.mark.asyncio
    async def test_certification_generation_exception(self, orchestrator, mock_validator_modules):
        """Test certification generation with exception"""
        mock_generator_instance = mock_validator_modules['cert_generator'].return_value
        mock_generator_instance.generate_certification_report.side_effect = Exception("Cert generation failed")

        result = await orchestrator._run_certification_generation()

        assert result["status"] == "ERROR"
        assert "Certification generation failed" in result["message"]


class TestFlowControlLogic:
    """Test orchestration flow control logic"""

    def test_should_continue_after_failure_infrastructure(self, orchestrator):
        """Test continuation after infrastructure check failure"""
        should_continue = orchestrator._should_continue_after_failure(ValidationPhase.INFRASTRUCTURE_CHECK)
        assert should_continue is True

    def test_should_continue_after_failure_production_readiness(self, orchestrator):
        """Test stopping after production readiness failure"""
        should_continue = orchestrator._should_continue_after_failure(ValidationPhase.PRODUCTION_READINESS)
        assert should_continue is False

    def test_should_continue_after_failure_security(self, orchestrator):
        """Test stopping after security testing failure"""
        should_continue = orchestrator._should_continue_after_failure(ValidationPhase.SECURITY_TESTING)
        assert should_continue is False

    def test_should_continue_after_failure_load_testing(self, orchestrator):
        """Test continuation after load testing failure"""
        should_continue = orchestrator._should_continue_after_failure(ValidationPhase.LOAD_TESTING)
        assert should_continue is True

    def test_should_continue_after_failure_compliance(self, orchestrator):
        """Test continuation after compliance failure"""
        should_continue = orchestrator._should_continue_after_failure(ValidationPhase.COMPLIANCE_VERIFICATION)
        assert should_continue is True

    def test_should_continue_after_failure_disaster_recovery(self, orchestrator):
        """Test continuation after disaster recovery failure"""
        should_continue = orchestrator._should_continue_after_failure(ValidationPhase.DISASTER_RECOVERY)
        assert should_continue is True


class TestReportGeneration:
    """Test orchestration report generation"""

    def test_generate_orchestration_report_all_passed(self, orchestrator):
        """Test report generation when all phases passed"""
        orchestrator.phase_results = [
            ValidationPhaseResult(
                phase=ValidationPhase.INFRASTRUCTURE_CHECK,
                status="PASSED",
                message="Infrastructure check passed",
                duration=10.0,
                timestamp="2024-01-01T10:00:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.PRODUCTION_READINESS,
                status="PASSED",
                message="Production readiness passed",
                duration=60.0,
                timestamp="2024-01-01T10:01:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.CERTIFICATION_GENERATION,
                status="COMPLETED",
                message="Certification completed",
                duration=15.0,
                timestamp="2024-01-01T10:02:00Z"
            )
        ]

        report = orchestrator._generate_orchestration_report()

        assert report.overall_status == "PASSED"
        assert report.total_phases == 3
        assert report.successful_phases == 3
        assert report.failed_phases == 0
        assert len(report.phase_results) == 3

    def test_generate_orchestration_report_with_failures(self, orchestrator):
        """Test report generation with phase failures"""
        orchestrator.phase_results = [
            ValidationPhaseResult(
                phase=ValidationPhase.INFRASTRUCTURE_CHECK,
                status="PASSED",
                message="Infrastructure check passed",
                duration=10.0,
                timestamp="2024-01-01T10:00:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.PRODUCTION_READINESS,
                status="FAILED",
                message="Production readiness failed",
                duration=60.0,
                timestamp="2024-01-01T10:01:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.LOAD_TESTING,
                status="ERROR",
                message="Load testing crashed",
                duration=30.0,
                timestamp="2024-01-01T10:02:00Z"
            )
        ]

        report = orchestrator._generate_orchestration_report()

        assert report.overall_status == "FAILED"  # Critical failure (production readiness)
        assert report.total_phases == 3
        assert report.successful_phases == 1
        assert report.failed_phases == 2

    def test_generate_orchestration_report_with_warnings(self, orchestrator):
        """Test report generation with non-critical failures"""
        orchestrator.phase_results = [
            ValidationPhaseResult(
                phase=ValidationPhase.INFRASTRUCTURE_CHECK,
                status="PASSED",
                message="Infrastructure check passed",
                duration=10.0,
                timestamp="2024-01-01T10:00:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.PRODUCTION_READINESS,
                status="PASSED",
                message="Production readiness passed",
                duration=60.0,
                timestamp="2024-01-01T10:01:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.COMPLIANCE_VERIFICATION,
                status="FAILED",
                message="Compliance verification failed",
                duration=30.0,
                timestamp="2024-01-01T10:02:00Z"
            )
        ]

        report = orchestrator._generate_orchestration_report()

        assert report.overall_status == "WARNING"  # Non-critical failure
        assert report.successful_phases == 2
        assert report.failed_phases == 1

    def test_generate_orchestration_recommendations_no_failures(self, orchestrator):
        """Test recommendation generation with no failures"""
        orchestrator.phase_results = [
            ValidationPhaseResult(
                phase=ValidationPhase.INFRASTRUCTURE_CHECK,
                status="PASSED",
                message="All good",
                duration=10.0,
                timestamp="2024-01-01T10:00:00Z"
            )
        ]

        recommendations = orchestrator._generate_orchestration_recommendations()

        assert len(recommendations) == 1
        assert "All validation phases completed successfully" in recommendations[0]

    def test_generate_orchestration_recommendations_with_failures(self, orchestrator):
        """Test recommendation generation with failures"""
        orchestrator.phase_results = [
            ValidationPhaseResult(
                phase=ValidationPhase.PRODUCTION_READINESS,
                status="FAILED",
                message="Production readiness failed",
                duration=60.0,
                timestamp="2024-01-01T10:00:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.SECURITY_TESTING,
                status="FAILED",
                message="Security issues found",
                duration=30.0,
                timestamp="2024-01-01T10:01:00Z"
            ),
            ValidationPhaseResult(
                phase=ValidationPhase.LOAD_TESTING,
                status="WARNING",
                message="Performance concerns",
                duration=45.0,
                timestamp="2024-01-01T10:02:00Z"
            )
        ]

        recommendations = orchestrator._generate_orchestration_recommendations()

        # Should have general critical recommendation
        critical_rec = next((r for r in recommendations if "CRITICAL" in r), None)
        assert critical_rec is not None
        assert "2 validation phases failed" in critical_rec

        # Should have warning recommendation
        warning_rec = next((r for r in recommendations if "WARNING" in r), None)
        assert warning_rec is not None

        # Should have specific phase recommendations
        prod_rec = next((r for r in recommendations if "production readiness" in r), None)
        assert prod_rec is not None

        security_rec = next((r for r in recommendations if "security vulnerabilities" in r), None)
        assert security_rec is not None


class TestCompleteValidationOrchestration:
    """Test complete validation orchestration"""

    @pytest.mark.asyncio
    async def test_run_complete_validation_with_skipped_phases(self, orchestrator_with_skipped_phases, mock_validator_modules):
        """Test complete validation with skipped phases"""
        # Mock all validation methods to return success
        with patch.object(orchestrator_with_skipped_phases, '_run_infrastructure_check') as mock_infra, \
             patch.object(orchestrator_with_skipped_phases, '_run_production_readiness_validation') as mock_prod, \
             patch.object(orchestrator_with_skipped_phases, '_run_security_testing') as mock_security, \
             patch.object(orchestrator_with_skipped_phases, '_run_compliance_verification') as mock_compliance, \
             patch.object(orchestrator_with_skipped_phases, '_run_certification_generation') as mock_cert:

            mock_infra.return_value = {"status": "PASSED", "message": "Infrastructure OK"}
            mock_prod.return_value = {"status": "PASSED", "message": "Production readiness OK"}
            mock_security.return_value = {"status": "PASSED", "message": "Security OK"}
            mock_compliance.return_value = {"status": "PASSED", "message": "Compliance OK"}
            mock_cert.return_value = {"status": "COMPLETED", "message": "Certification OK"}

            report = await orchestrator_with_skipped_phases.run_complete_validation()

            # Should have results for all phases (including skipped ones)
            assert report.total_phases == 7

            # Check that load_testing and disaster_recovery phases were skipped
            skipped_phases = [r for r in report.phase_results if r.status == "SKIPPED"]
            assert len(skipped_phases) == 2

            skipped_phase_names = [r.phase.value for r in skipped_phases]
            assert "load_testing" in skipped_phase_names
            assert "disaster_recovery" in skipped_phase_names

    @pytest.mark.asyncio
    async def test_run_complete_validation_stop_on_critical_failure(self, orchestrator, mock_validator_modules):
        """Test that orchestration stops on critical failures"""
        with patch.object(orchestrator, '_run_infrastructure_check') as mock_infra, \
             patch.object(orchestrator, '_run_production_readiness_validation') as mock_prod, \
             patch.object(orchestrator, '_run_security_testing') as mock_security:

            mock_infra.return_value = {"status": "PASSED", "message": "Infrastructure OK"}
            mock_prod.return_value = {"status": "FAILED", "message": "Production readiness failed"}

            # Security testing should not be called due to critical failure
            mock_security.return_value = {"status": "PASSED", "message": "Security OK"}

            report = await orchestrator.run_complete_validation()

            # Should stop after production readiness failure
            mock_infra.assert_called_once()
            mock_prod.assert_called_once()
            mock_security.assert_not_called()  # Should not reach security testing

            assert report.overall_status == "FAILED"

    @pytest.mark.asyncio
    async def test_run_complete_validation_continue_on_non_critical_failure(self, orchestrator, mock_validator_modules):
        """Test that orchestration continues on non-critical failures"""
        with patch.object(orchestrator, '_run_infrastructure_check') as mock_infra, \
             patch.object(orchestrator, '_run_production_readiness_validation') as mock_prod, \
             patch.object(orchestrator, '_run_security_testing') as mock_security, \
             patch.object(orchestrator, '_run_load_testing') as mock_load, \
             patch.object(orchestrator, '_run_disaster_recovery_testing') as mock_dr, \
             patch.object(orchestrator, '_run_compliance_verification') as mock_compliance, \
             patch.object(orchestrator, '_run_certification_generation') as mock_cert:

            mock_infra.return_value = {"status": "FAILED", "message": "Infrastructure issues"}  # Non-critical
            mock_prod.return_value = {"status": "PASSED", "message": "Production readiness OK"}
            mock_security.return_value = {"status": "PASSED", "message": "Security OK"}
            mock_load.return_value = {"status": "PASSED", "message": "Load testing OK"}
            mock_dr.return_value = {"status": "FAILED", "message": "DR not implemented"}  # Non-critical
            mock_compliance.return_value = {"status": "PASSED", "message": "Compliance OK"}
            mock_cert.return_value = {"status": "COMPLETED", "message": "Certification OK"}

            report = await orchestrator.run_complete_validation()

            # All phases should be called despite infrastructure and DR failures
            mock_infra.assert_called_once()
            mock_prod.assert_called_once()
            mock_security.assert_called_once()
            mock_load.assert_called_once()
            mock_dr.assert_called_once()
            mock_compliance.assert_called_once()
            mock_cert.assert_called_once()

            assert report.overall_status == "WARNING"  # Non-critical failures

    @pytest.mark.asyncio
    async def test_run_complete_validation_with_exceptions(self, orchestrator, mock_validator_modules):
        """Test handling of exceptions during validation phases"""
        with patch.object(orchestrator, '_run_infrastructure_check') as mock_infra, \
             patch.object(orchestrator, '_run_production_readiness_validation') as mock_prod, \
             patch.object(orchestrator, '_run_security_testing') as mock_security:

            mock_infra.return_value = {"status": "PASSED", "message": "Infrastructure OK"}
            mock_prod.side_effect = Exception("Production validation crashed")

            # Should not reach security testing due to exception in critical phase
            mock_security.return_value = {"status": "PASSED", "message": "Security OK"}

            report = await orchestrator.run_complete_validation()

            # Check that exception was recorded properly
            prod_result = next((r for r in report.phase_results if r.phase == ValidationPhase.PRODUCTION_READINESS), None)
            assert prod_result is not None
            assert prod_result.status == "ERROR"
            assert "Production validation crashed" in prod_result.message

            # Should have stopped due to exception in critical phase
            mock_security.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])