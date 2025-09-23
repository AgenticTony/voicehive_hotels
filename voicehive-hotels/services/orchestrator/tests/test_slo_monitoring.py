"""
Comprehensive Tests for SLO Monitoring System
Tests for SLI/SLO configuration, monitoring, error budgets, and runbook automation
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch
import json

from sli_slo_config import (
    SLIDefinition, SLODefinition, SLOTarget, ErrorBudgetPolicy,
    SLIType, BurnRateWindow, VoiceHiveSLOConfig
)
from slo_monitor import (
    SLOMonitor, SLOStatus, SLOCompliance, ErrorBudgetAlert,
    PrometheusClient
)
from runbook_automation import (
    RunbookAutomationEngine, RunbookDefinition, RunbookStep,
    RunbookSeverity, RunbookStatus, RunbookActionExecutor
)

class TestSLIConfiguration:
    """Test SLI/SLO configuration and definitions"""
    
    def test_sli_definition_creation(self):
        """Test SLI definition creation"""
        sli = SLIDefinition(
            name="test_availability",
            description="Test availability SLI",
            sli_type=SLIType.AVAILABILITY,
            query="sum(rate(requests_total{status!~\"5..\"}[5m])) / sum(rate(requests_total[5m]))",
            unit="percentage",
            good_total_ratio=True,
            labels={"service": "test"}
        )
        
        assert sli.name == "test_availability"
        assert sli.sli_type == SLIType.AVAILABILITY
        assert sli.good_total_ratio is True
        assert sli.labels["service"] == "test"
    
    def test_slo_definition_creation(self):
        """Test SLO definition creation with targets and error budget policy"""
        sli = SLIDefinition(
            name="test_sli",
            description="Test SLI",
            sli_type=SLIType.AVAILABILITY,
            query="test_query",
            unit="percentage"
        )
        
        targets = [
            SLOTarget(
                target_percentage=99.9,
                compliance_period="30d",
                description="99.9% availability over 30 days"
            )
        ]
        
        error_budget_policy = ErrorBudgetPolicy(
            burn_rate_thresholds={
                BurnRateWindow.FAST: 14.4,
                BurnRateWindow.MEDIUM: 6.0
            },
            alert_on_exhaustion_percentage=90.0
        )
        
        slo = SLODefinition(
            name="test_slo",
            service="test_service",
            sli=sli,
            targets=targets,
            error_budget_policy=error_budget_policy,
            tags={"criticality": "high"}
        )
        
        assert slo.name == "test_slo"
        assert slo.service == "test_service"
        assert len(slo.targets) == 1
        assert slo.targets[0].target_percentage == 99.9
        assert slo.error_budget_policy.alert_on_exhaustion_percentage == 90.0
        assert slo.tags["criticality"] == "high"
    
    def test_voicehive_slo_config_core_slos(self):
        """Test VoiceHive core SLO configuration"""
        core_slos = VoiceHiveSLOConfig.get_core_slos()
        
        assert len(core_slos) > 0
        
        # Check API availability SLO
        api_availability_slo = next(
            (slo for slo in core_slos if slo.name == "api_availability"), 
            None
        )
        assert api_availability_slo is not None
        assert api_availability_slo.service == "orchestrator"
        assert api_availability_slo.sli.sli_type == SLIType.AVAILABILITY
        assert len(api_availability_slo.targets) >= 1
        assert api_availability_slo.targets[0].target_percentage == 99.9
    
    def test_voicehive_slo_config_business_slos(self):
        """Test VoiceHive business SLO configuration"""
        business_slos = VoiceHiveSLOConfig.get_business_slos()
        
        assert len(business_slos) > 0
        
        # Check guest satisfaction SLO
        satisfaction_slo = next(
            (slo for slo in business_slos if slo.name == "guest_satisfaction"),
            None
        )
        assert satisfaction_slo is not None
        assert satisfaction_slo.sli.sli_type == SLIType.CUSTOM
        assert "business_impact" in satisfaction_slo.tags

class TestPrometheusClient:
    """Test Prometheus client functionality"""
    
    @pytest.mark.asyncio
    async def test_prometheus_client_query(self):
        """Test Prometheus query execution"""
        mock_response_data = {
            "status": "success",
            "data": {
                "result": [
                    {
                        "value": [1640995200, "0.995"]
                    }
                ]
            }
        }
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)
            mock_response.raise_for_status = Mock()
            
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response
            
            async with PrometheusClient("http://prometheus:9090") as client:
                result = await client.query("up")
                
                assert result["result"][0]["value"][1] == "0.995"
    
    @pytest.mark.asyncio
    async def test_prometheus_client_query_error(self):
        """Test Prometheus query error handling"""
        mock_response_data = {
            "status": "error",
            "error": "invalid query"
        }
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_response_data)
            mock_response.raise_for_status = Mock()
            
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response
            
            async with PrometheusClient("http://prometheus:9090") as client:
                with pytest.raises(ValueError, match="Prometheus query failed"):
                    await client.query("invalid_query")

class TestSLOMonitor:
    """Test SLO monitoring functionality"""
    
    @pytest.fixture
    def sample_slo(self):
        """Create sample SLO for testing"""
        sli = SLIDefinition(
            name="test_availability",
            description="Test availability SLI",
            sli_type=SLIType.AVAILABILITY,
            query="sum(rate(requests_total{status!~\"5..\"}[5m])) / sum(rate(requests_total[5m]))",
            unit="percentage",
            good_total_ratio=True
        )
        
        targets = [
            SLOTarget(
                target_percentage=99.9,
                compliance_period="30d",
                description="99.9% availability"
            )
        ]
        
        return SLODefinition(
            name="test_slo",
            service="test_service",
            sli=sli,
            targets=targets,
            error_budget_policy=ErrorBudgetPolicy()
        )
    
    @pytest.mark.asyncio
    async def test_slo_evaluation_compliant(self, sample_slo):
        """Test SLO evaluation when SLO is compliant"""
        monitor = SLOMonitor("http://prometheus:9090")
        
        # Mock Prometheus responses
        with patch.object(monitor, '_calculate_burn_rates', return_value={
            BurnRateWindow.FAST: 0.5,
            BurnRateWindow.MEDIUM: 0.3,
            BurnRateWindow.SLOW: 0.2,
            BurnRateWindow.VERY_SLOW: 0.1
        }):
            with patch('slo_monitor.PrometheusClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.query = AsyncMock(return_value={
                    "result": [{"value": [1640995200, "0.999"]}]  # 99.9% availability
                })
                mock_client_class.return_value.__aenter__.return_value = mock_client
                
                status = await monitor.evaluate_slo(sample_slo)
                
                assert status.slo_name == "test_slo"
                assert status.current_sli_value == 99.9
                assert status.compliance_status == SLOCompliance.COMPLIANT
                assert status.error_budget_remaining > 0
                assert status.burn_rate_1h == 0.5
    
    @pytest.mark.asyncio
    async def test_slo_evaluation_violated(self, sample_slo):
        """Test SLO evaluation when SLO is violated"""
        monitor = SLOMonitor("http://prometheus:9090")
        
        with patch.object(monitor, '_calculate_burn_rates', return_value={
            BurnRateWindow.FAST: 15.0,  # High burn rate
            BurnRateWindow.MEDIUM: 8.0,
            BurnRateWindow.SLOW: 4.0,
            BurnRateWindow.VERY_SLOW: 2.0
        }):
            with patch('slo_monitor.PrometheusClient') as mock_client_class:
                mock_client = AsyncMock()
                mock_client.query = AsyncMock(return_value={
                    "result": [{"value": [1640995200, "0.985"]}]  # 98.5% availability (below 99.9% target)
                })
                mock_client_class.return_value.__aenter__.return_value = mock_client
                
                with patch.object(monitor, '_send_alert', new_callable=AsyncMock) as mock_send_alert:
                    status = await monitor.evaluate_slo(sample_slo)
                    
                    assert status.compliance_status == SLOCompliance.VIOLATED
                    assert status.error_budget_consumed == 100.0
                    assert len(status.alerts_active) > 0
                    
                    # Verify alerts were sent
                    assert mock_send_alert.call_count > 0
    
    @pytest.mark.asyncio
    async def test_burn_rate_calculation(self, sample_slo):
        """Test burn rate calculation for different windows"""
        monitor = SLOMonitor("http://prometheus:9090")
        
        with patch('slo_monitor.PrometheusClient') as mock_client_class:
            mock_client = AsyncMock()
            
            # Mock different error rates for different windows
            def mock_query_side_effect(query):
                if "[1h]" in query:
                    return {"result": [{"value": [1640995200, "0.002"]}]}  # 0.2% error rate
                elif "[6h]" in query:
                    return {"result": [{"value": [1640995200, "0.001"]}]}  # 0.1% error rate
                else:
                    return {"result": [{"value": [1640995200, "0.0005"]}]}  # 0.05% error rate
            
            mock_client.query = AsyncMock(side_effect=mock_query_side_effect)
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            burn_rates = await monitor._calculate_burn_rates(mock_client, sample_slo)
            
            # For 99.9% SLO, error budget rate is 0.1%
            # Burn rate = error_rate / error_budget_rate
            assert burn_rates[BurnRateWindow.FAST] == 2.0  # 0.2% / 0.1%
            assert burn_rates[BurnRateWindow.MEDIUM] == 1.0  # 0.1% / 0.1%
    
    def test_error_budget_calculation(self):
        """Test error budget calculation logic"""
        monitor = SLOMonitor("http://prometheus:9090")
        
        # Mock target
        target = Mock()
        target.target_percentage = 99.9
        
        # Test compliant case
        compliance, remaining, consumed = monitor._calculate_error_budget(99.95, target)
        assert compliance == SLOCompliance.COMPLIANT
        assert remaining > 0
        assert consumed < 100
        
        # Test violated case
        compliance, remaining, consumed = monitor._calculate_error_budget(99.8, target)
        assert compliance == SLOCompliance.VIOLATED
        assert consumed == 100.0
        assert remaining == 0.0
    
    @pytest.mark.asyncio
    async def test_dashboard_data_generation(self):
        """Test SLO dashboard data generation"""
        monitor = SLOMonitor("http://prometheus:9090")
        
        # Mock evaluate_all_slos
        mock_status = SLOStatus(
            slo_name="test_slo",
            service="test_service",
            current_sli_value=99.9,
            target_percentage=99.9,
            compliance_period="30d",
            compliance_status=SLOCompliance.COMPLIANT,
            error_budget_remaining=80.0,
            error_budget_consumed=20.0,
            burn_rate_1h=0.5,
            burn_rate_6h=0.3,
            burn_rate_24h=0.2,
            burn_rate_72h=0.1,
            last_updated=datetime.utcnow(),
            alerts_active=[],
            metadata={}
        )
        
        with patch.object(monitor, 'evaluate_all_slos', return_value={"test_slo": mock_status}):
            dashboard_data = await monitor.get_slo_dashboard_data()
            
            assert "summary" in dashboard_data
            assert "slos" in dashboard_data
            assert dashboard_data["summary"]["total_slos"] == 1
            assert dashboard_data["summary"]["compliant"] == 1
            assert "test_slo" in dashboard_data["slos"]

class TestRunbookAutomation:
    """Test runbook automation system"""
    
    @pytest.fixture
    def sample_runbook(self):
        """Create sample runbook for testing"""
        steps = [
            RunbookStep(
                name="check_health",
                description="Check service health",
                action_type="check",
                action_config={
                    "type": "http",
                    "url": "http://service:8000/health",
                    "expected_status": 200
                }
            ),
            RunbookStep(
                name="send_notification",
                description="Send alert notification",
                action_type="notification",
                action_config={
                    "type": "slack",
                    "message": "Service issue detected: {slo_name}"
                }
            )
        ]
        
        return RunbookDefinition(
            name="test_runbook",
            description="Test runbook for SLO violations",
            trigger_conditions=["test_alert"],
            severity=RunbookSeverity.HIGH,
            steps=steps,
            cooldown_minutes=10,
            max_executions_per_hour=5
        )
    
    @pytest.mark.asyncio
    async def test_runbook_step_execution_success(self):
        """Test successful runbook step execution"""
        executor = RunbookActionExecutor()
        
        step = RunbookStep(
            name="test_check",
            description="Test health check",
            action_type="check",
            action_config={
                "type": "http",
                "url": "http://test:8000/health",
                "expected_status": 200
            }
        )
        
        context = {"test_key": "test_value"}
        
        with patch.object(executor, '_execute_check', return_value={"success": True}):
            result = await executor.execute_step(step, context)
            
            assert result["step_name"] == "test_check"
            assert result["status"] == "success"
            assert "duration_seconds" in result
    
    @pytest.mark.asyncio
    async def test_runbook_step_execution_failure(self):
        """Test runbook step execution failure"""
        executor = RunbookActionExecutor()
        
        step = RunbookStep(
            name="failing_step",
            description="Step that fails",
            action_type="command",
            action_config={"command": "false"}  # Command that always fails
        )
        
        context = {}
        
        with patch.object(executor, '_execute_command', side_effect=Exception("Command failed")):
            result = await executor.execute_step(step, context)
            
            assert result["step_name"] == "failing_step"
            assert result["status"] == "failed"
            assert "error" in result
    
    @pytest.mark.asyncio
    async def test_runbook_step_condition_evaluation(self):
        """Test runbook step condition evaluation"""
        executor = RunbookActionExecutor()
        
        step = RunbookStep(
            name="conditional_step",
            description="Step with condition",
            action_type="notification",
            action_config={"type": "slack", "message": "test"},
            condition="error_budget_remaining < 10"
        )
        
        # Test condition not met
        context = {"error_budget_remaining": 50}
        result = await executor.execute_step(step, context)
        assert result["status"] == "skipped"
        
        # Test condition met
        context = {"error_budget_remaining": 5}
        with patch.object(executor, '_send_notification', return_value="sent"):
            result = await executor.execute_step(step, context)
            assert result["status"] == "success"
    
    @pytest.mark.asyncio
    async def test_runbook_engine_trigger_matching(self, sample_runbook):
        """Test runbook triggering based on alert conditions"""
        engine = RunbookAutomationEngine()
        engine.add_runbook(sample_runbook)
        
        # Create mock alert and SLO status
        alert = ErrorBudgetAlert(
            slo_name="test_slo",
            alert_type="test_alert",
            severity="high",
            message="Test alert",
            current_value=10.0,
            threshold=5.0,
            window="1h",
            timestamp=datetime.utcnow(),
            runbook_url=""
        )
        
        slo_status = SLOStatus(
            slo_name="test_slo",
            service="test_service",
            current_sli_value=99.0,
            target_percentage=99.9,
            compliance_period="30d",
            compliance_status=SLOCompliance.VIOLATED,
            error_budget_remaining=10.0,
            error_budget_consumed=90.0,
            burn_rate_1h=5.0,
            burn_rate_6h=3.0,
            burn_rate_24h=2.0,
            burn_rate_72h=1.0,
            last_updated=datetime.utcnow(),
            alerts_active=["test_alert"],
            metadata={}
        )
        
        with patch.object(engine, '_execute_runbook') as mock_execute:
            mock_execute.return_value = Mock(execution_id="test_exec_123")
            
            execution = await engine.trigger_runbook(alert, slo_status)
            
            assert execution is not None
            mock_execute.assert_called_once()
    
    def test_runbook_cooldown_and_rate_limiting(self, sample_runbook):
        """Test runbook cooldown and rate limiting"""
        engine = RunbookAutomationEngine()
        engine.add_runbook(sample_runbook)
        
        # Test initial execution allowed
        assert engine._can_execute_runbook(sample_runbook) is True
        
        # Simulate recent execution
        engine._update_execution_tracking(sample_runbook.name)
        
        # Test cooldown prevents execution
        assert engine._can_execute_runbook(sample_runbook) is False
        
        # Test rate limiting
        engine.cooldown_tracker[sample_runbook.name] = datetime.utcnow() - timedelta(minutes=15)
        
        # Add many recent executions to test rate limit
        now = datetime.utcnow()
        engine.execution_counter[sample_runbook.name] = [
            now - timedelta(minutes=i) for i in range(sample_runbook.max_executions_per_hour)
        ]
        
        assert engine._can_execute_runbook(sample_runbook) is False
    
    @pytest.mark.asyncio
    async def test_runbook_execution_with_required_step_failure(self, sample_runbook):
        """Test runbook execution stops when required step fails"""
        engine = RunbookAutomationEngine()
        
        # Make first step required and failing
        sample_runbook.steps[0].required = True
        
        alert = ErrorBudgetAlert(
            slo_name="test_slo",
            alert_type="test_alert",
            severity="high",
            message="Test alert",
            current_value=10.0,
            threshold=5.0,
            window="1h",
            timestamp=datetime.utcnow(),
            runbook_url=""
        )
        
        slo_status = Mock()
        slo_status.current_sli_value = 99.0
        slo_status.error_budget_remaining = 10.0
        
        with patch.object(engine.executor, 'execute_step') as mock_execute_step:
            # First step fails
            mock_execute_step.side_effect = [
                {"step_name": "check_health", "status": "failed", "error": "Health check failed"},
                {"step_name": "send_notification", "status": "success"}
            ]
            
            execution = await engine._execute_runbook(sample_runbook, alert, slo_status)
            
            assert execution.status == RunbookStatus.FAILED
            assert "Health check failed" in execution.error_message
            # Should only execute first step since it's required and failed
            assert len(execution.steps_executed) == 1

class TestSLOIntegration:
    """Integration tests for complete SLO monitoring workflow"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_slo_violation_workflow(self):
        """Test complete workflow from SLO violation to runbook execution"""
        # Setup SLO monitor
        monitor = SLOMonitor("http://prometheus:9090")
        
        # Setup runbook engine
        engine = RunbookAutomationEngine()
        
        # Create test SLO
        sli = SLIDefinition(
            name="integration_test_sli",
            description="Integration test SLI",
            sli_type=SLIType.AVAILABILITY,
            query="test_query",
            unit="percentage"
        )
        
        slo = SLODefinition(
            name="integration_test_slo",
            service="test_service",
            sli=sli,
            targets=[SLOTarget(99.9, "30d", "Test target")],
            error_budget_policy=ErrorBudgetPolicy()
        )
        
        # Mock SLO evaluation to return violation
        mock_status = SLOStatus(
            slo_name="integration_test_slo",
            service="test_service",
            current_sli_value=98.0,  # Below target
            target_percentage=99.9,
            compliance_period="30d",
            compliance_status=SLOCompliance.VIOLATED,
            error_budget_remaining=0.0,
            error_budget_consumed=100.0,
            burn_rate_1h=20.0,  # High burn rate
            burn_rate_6h=15.0,
            burn_rate_24h=10.0,
            burn_rate_72h=5.0,
            last_updated=datetime.utcnow(),
            alerts_active=["slo_violation", "burn_rate_1h_exceeded"],
            metadata={}
        )
        
        with patch.object(monitor, 'evaluate_slo', return_value=mock_status):
            with patch.object(monitor, '_send_alert') as mock_send_alert:
                # Evaluate SLO
                status = await monitor.evaluate_slo(slo)
                
                # Verify SLO violation detected
                assert status.compliance_status == SLOCompliance.VIOLATED
                assert len(status.alerts_active) > 0
                
                # Verify alerts were sent
                assert mock_send_alert.call_count > 0
                
                # Get the alert that would trigger runbook
                alert_call = mock_send_alert.call_args_list[0]
                alert = alert_call[0][0]  # First argument of first call
                
                # Trigger runbook
                with patch.object(engine, '_execute_runbook') as mock_execute_runbook:
                    mock_execution = Mock()
                    mock_execution.execution_id = "test_execution_123"
                    mock_execution.status = RunbookStatus.SUCCESS
                    mock_execute_runbook.return_value = mock_execution
                    
                    execution = await engine.trigger_runbook(alert, status)
                    
                    # Verify runbook was executed
                    assert execution is not None
                    assert execution.execution_id == "test_execution_123"
                    mock_execute_runbook.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_multiple_slo_evaluation_performance(self):
        """Test performance of evaluating multiple SLOs"""
        monitor = SLOMonitor("http://prometheus:9090")
        
        # Mock Prometheus client to return quick responses
        with patch('slo_monitor.PrometheusClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.query = AsyncMock(return_value={
                "result": [{"value": [1640995200, "0.999"]}]
            })
            mock_client_class.return_value.__aenter__.return_value = mock_client
            
            with patch.object(monitor, '_calculate_burn_rates', return_value={
                BurnRateWindow.FAST: 0.5,
                BurnRateWindow.MEDIUM: 0.3,
                BurnRateWindow.SLOW: 0.2,
                BurnRateWindow.VERY_SLOW: 0.1
            }):
                start_time = datetime.utcnow()
                
                # Evaluate all SLOs
                results = await monitor.evaluate_all_slos()
                
                end_time = datetime.utcnow()
                duration = (end_time - start_time).total_seconds()
                
                # Should complete within reasonable time (adjust based on SLO count)
                assert duration < 10.0  # 10 seconds max for all SLOs
                assert len(results) > 0
                
                # Verify all results are valid
                for slo_name, status in results.items():
                    assert isinstance(status, SLOStatus)
                    assert status.slo_name == slo_name
                    assert status.last_updated is not None

if __name__ == "__main__":
    pytest.main([__file__, "-v"])