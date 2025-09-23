"""
Tests for Monitoring and Observability Enhancement
Comprehensive test suite for business metrics, alerting, and tracing
"""

import pytest
import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from business_metrics import (
    BusinessMetricsCollector, 
    business_metrics,
    call_success_rate,
    pms_response_time
)
from enhanced_alerting import (
    EnhancedAlertingSystem,
    AlertRule,
    AlertSeverity,
    SLATarget,
    SlackNotificationChannel,
    PagerDutyNotificationChannel
)
from distributed_tracing import (
    EnhancedTracer,
    SpanType,
    BusinessContext,
    trace_function
)
from dashboard_config import DashboardGenerator
from routers.monitoring import router
from app import app


class TestBusinessMetrics:
    """Test business metrics collection"""
    
    def setup_method(self):
        """Setup test environment"""
        self.metrics_collector = BusinessMetricsCollector()
    
    def test_call_lifecycle_tracking(self):
        """Test complete call lifecycle tracking"""
        call_id = "test-call-123"
        hotel_id = "hotel-456"
        language = "en"
        call_type = "inbound"
        
        # Start call
        self.metrics_collector.record_call_start(call_id, hotel_id, language, call_type)
        assert call_id in self.metrics_collector.active_calls
        
        # Complete call successfully
        self.metrics_collector.record_call_success(call_id, hotel_id, language, call_type, "booking_completed")
        assert call_id not in self.metrics_collector.active_calls
    
    def test_call_failure_tracking(self):
        """Test call failure tracking"""
        call_id = "test-call-456"
        hotel_id = "hotel-789"
        language = "es"
        call_type = "inbound"
        
        self.metrics_collector.record_call_start(call_id, hotel_id, language, call_type)
        self.metrics_collector.record_call_failure(call_id, hotel_id, language, call_type, "pms_timeout")
        
        assert call_id not in self.metrics_collector.active_calls
    
    def test_pms_operation_measurement(self):
        """Test PMS operation duration measurement"""
        hotel_id = "hotel-123"
        pms_type = "apaleo"
        operation = "get_availability"
        
        # Test successful operation
        with self.metrics_collector.measure_pms_operation(hotel_id, pms_type, operation):
            time.sleep(0.1)  # Simulate operation time
        
        # Test failed operation
        with pytest.raises(Exception):
            with self.metrics_collector.measure_pms_operation(hotel_id, pms_type, operation):
                raise Exception("PMS connection failed")
    
    def test_pms_availability_tracking(self):
        """Test PMS availability status tracking"""
        hotel_id = "hotel-123"
        pms_type = "apaleo"
        
        # Set available
        self.metrics_collector.update_pms_availability(hotel_id, pms_type, True)
        key = f"{hotel_id}:{pms_type}"
        assert self.metrics_collector.pms_health_status[key] is True
        
        # Set unavailable
        self.metrics_collector.update_pms_availability(hotel_id, pms_type, False)
        assert self.metrics_collector.pms_health_status[key] is False
    
    def test_guest_satisfaction_recording(self):
        """Test guest satisfaction score recording"""
        hotel_id = "hotel-123"
        language = "en"
        score = 4.5
        
        self.metrics_collector.record_guest_satisfaction(hotel_id, language, score)
        # In a real test, you'd verify the metric was recorded
    
    def test_revenue_impact_tracking(self):
        """Test revenue impact tracking"""
        hotel_id = "hotel-123"
        currency = "EUR"
        impact_type = "booking_upsell"
        amount = 150.0
        
        self.metrics_collector.record_revenue_impact(hotel_id, currency, impact_type, amount)
        # In a real test, you'd verify the metric was recorded
    
    def test_resource_usage_monitoring(self):
        """Test resource usage monitoring"""
        component = "orchestrator"
        memory_bytes = 256 * 1024 * 1024  # 256MB
        cpu_percent = 15.5
        
        self.metrics_collector.update_resource_usage(component, memory_bytes, cpu_percent)
        # In a real test, you'd verify the metrics were updated


class TestEnhancedAlerting:
    """Test enhanced alerting system"""
    
    def setup_method(self):
        """Setup test environment"""
        self.alerting_system = EnhancedAlertingSystem()
    
    def test_alert_rule_creation(self):
        """Test alert rule creation and storage"""
        rule = AlertRule(
            name="test_high_error_rate",
            description="Test alert for high error rate",
            severity=AlertSeverity.HIGH,
            metric_name="error_rate",
            threshold=0.05,
            comparison="gt",
            duration=60,
            labels={"service": "orchestrator"}
        )
        
        self.alerting_system.add_alert_rule(rule)
        assert "test_high_error_rate" in self.alerting_system.alert_rules
        assert self.alerting_system.alert_rules["test_high_error_rate"] == rule
    
    def test_sla_target_creation(self):
        """Test SLA target creation"""
        target = SLATarget(
            name="test_call_success_sla",
            description="Test SLA for call success rate",
            target_percentage=99.0,
            measurement_window=3600,
            metric_query="call_success_rate",
            labels={},
            alert_threshold=1.0
        )
        
        self.alerting_system.add_sla_target(target)
        assert "test_call_success_sla" in self.alerting_system.sla_targets
    
    def test_metric_value_recording(self):
        """Test metric value recording for alerting"""
        metric_name = "error_rate"
        value = 0.02
        labels = {"service": "orchestrator"}
        
        self.alerting_system.record_metric_value(metric_name, value, labels)
        assert metric_name in self.alerting_system.metric_values
        assert len(self.alerting_system.metric_values[metric_name]) == 1
    
    @pytest.mark.asyncio
    async def test_alert_rule_evaluation(self):
        """Test alert rule evaluation"""
        # Create a rule that should trigger
        rule = AlertRule(
            name="test_threshold_breach",
            description="Test threshold breach",
            severity=AlertSeverity.CRITICAL,
            metric_name="test_metric",
            threshold=0.05,
            comparison="gt",
            duration=1,  # 1 second
            labels={}
        )
        
        self.alerting_system.add_alert_rule(rule)
        
        # Record a value that breaches the threshold
        self.alerting_system.record_metric_value("test_metric", 0.10)
        
        # Wait for duration
        await asyncio.sleep(1.1)
        
        # Evaluate rules
        await self.alerting_system.evaluate_alert_rules()
        
        # Check if alert was created
        assert len(self.alerting_system.active_alerts) > 0
    
    @pytest.mark.asyncio
    async def test_slack_notification(self):
        """Test Slack notification channel"""
        webhook_url = "https://hooks.slack.com/test"
        channel = SlackNotificationChannel(webhook_url)
        
        # Mock the HTTP request
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = Mock()
            mock_response.status = 200
            mock_post.return_value.__aenter__.return_value = mock_response
            
            from enhanced_alerting import Alert, AlertStatus
            alert = Alert(
                id="test-alert-123",
                rule_name="test_rule",
                severity=AlertSeverity.HIGH,
                status=AlertStatus.ACTIVE,
                title="Test Alert",
                description="This is a test alert",
                metric_value=0.10,
                threshold=0.05,
                labels={"service": "test"},
                started_at=datetime.utcnow()
            )
            
            result = await channel.send_alert(alert)
            assert result is True
            mock_post.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_pagerduty_notification(self):
        """Test PagerDuty notification channel"""
        integration_key = "test-integration-key"
        channel = PagerDutyNotificationChannel(integration_key)
        
        # Mock the HTTP request
        with patch('aiohttp.ClientSession.post') as mock_post:
            mock_response = Mock()
            mock_response.status = 202
            mock_post.return_value.__aenter__.return_value = mock_response
            
            from enhanced_alerting import Alert, AlertStatus
            alert = Alert(
                id="test-alert-456",
                rule_name="test_rule",
                severity=AlertSeverity.CRITICAL,
                status=AlertStatus.ACTIVE,
                title="Critical Test Alert",
                description="This is a critical test alert",
                metric_value=0.15,
                threshold=0.05,
                labels={"service": "test"},
                started_at=datetime.utcnow()
            )
            
            result = await channel.send_alert(alert)
            assert result is True
            mock_post.assert_called_once()


class TestDistributedTracing:
    """Test distributed tracing functionality"""
    
    def setup_method(self):
        """Setup test environment"""
        self.tracer = EnhancedTracer("test-service")
    
    def test_business_context_creation(self):
        """Test business context creation"""
        context = self.tracer.create_business_context(
            hotel_id="hotel-123",
            call_id="call-456",
            language="en"
        )
        
        assert context.hotel_id == "hotel-123"
        assert context.call_id == "call-456"
        assert context.language == "en"
    
    @pytest.mark.asyncio
    async def test_async_operation_tracing(self):
        """Test async operation tracing"""
        business_context = BusinessContext(
            hotel_id="hotel-123",
            call_id="call-456"
        )
        
        async with self.tracer.trace_operation(
            "test_operation",
            SpanType.CALL_HANDLING,
            business_context=business_context
        ) as span:
            # Simulate some work
            await asyncio.sleep(0.01)
            
            # The span should be active
            if span:  # Only if OpenTelemetry is available
                assert span is not None
    
    def test_sync_operation_tracing(self):
        """Test synchronous operation tracing"""
        business_context = BusinessContext(
            hotel_id="hotel-123",
            pms_type="apaleo"
        )
        
        with self.tracer.trace_sync_operation(
            "test_sync_operation",
            SpanType.PMS_OPERATION,
            business_context=business_context
        ) as span:
            # Simulate some work
            time.sleep(0.01)
            
            # The span should be active (if OpenTelemetry is available)
            pass
    
    def test_trace_function_decorator(self):
        """Test trace function decorator"""
        
        @trace_function("test_decorated_function", SpanType.AI_PROCESSING)
        def test_function(x, y):
            return x + y
        
        result = test_function(2, 3)
        assert result == 5
    
    @pytest.mark.asyncio
    async def test_async_trace_function_decorator(self):
        """Test async trace function decorator"""
        
        @trace_function("test_async_decorated_function", SpanType.AUDIO_PROCESSING)
        async def test_async_function(x, y):
            await asyncio.sleep(0.01)
            return x * y
        
        result = await test_async_function(3, 4)
        assert result == 12
    
    def test_trace_context_propagation(self):
        """Test trace context header propagation"""
        headers = self.tracer.get_trace_context_headers()
        
        # Headers should be a dictionary (empty if OpenTelemetry not available)
        assert isinstance(headers, dict)
        
        # Test extraction (should not raise errors)
        self.tracer.extract_trace_context(headers)


class TestDashboardConfiguration:
    """Test dashboard configuration generation"""
    
    def setup_method(self):
        """Setup test environment"""
        self.dashboard_generator = DashboardGenerator()
    
    def test_business_metrics_dashboard_creation(self):
        """Test business metrics dashboard creation"""
        dashboard = self.dashboard_generator.create_business_metrics_dashboard()
        
        assert "title" in dashboard
        assert dashboard["title"] == "VoiceHive Hotels - Business Metrics"
        assert "panels" in dashboard
        assert len(dashboard["panels"]) > 0
        
        # Check for key panels
        panel_titles = [panel["title"] for panel in dashboard["panels"]]
        assert "Call Success Rate" in panel_titles
        assert "Active Calls" in panel_titles
        assert "PMS Response Time" in panel_titles
    
    def test_system_health_dashboard_creation(self):
        """Test system health dashboard creation"""
        dashboard = self.dashboard_generator.create_system_health_dashboard()
        
        assert "title" in dashboard
        assert dashboard["title"] == "VoiceHive Hotels - System Health"
        assert "panels" in dashboard
        
        # Check for system health panels
        panel_titles = [panel["title"] for panel in dashboard["panels"]]
        assert "CPU Usage" in panel_titles
        assert "Memory Usage" in panel_titles
    
    def test_sla_monitoring_dashboard_creation(self):
        """Test SLA monitoring dashboard creation"""
        dashboard = self.dashboard_generator.create_sla_monitoring_dashboard()
        
        assert "title" in dashboard
        assert dashboard["title"] == "VoiceHive Hotels - SLA Monitoring"
        assert "panels" in dashboard
        
        # Check for SLA panels
        panel_titles = [panel["title"] for panel in dashboard["panels"]]
        assert "SLA Compliance Overview" in panel_titles
        assert "Call Success Rate SLA (99%)" in panel_titles


class TestMonitoringRouter:
    """Test monitoring router endpoints"""
    
    def setup_method(self):
        """Setup test client"""
        self.client = TestClient(app)
    
    def test_prometheus_metrics_endpoint(self):
        """Test Prometheus metrics endpoint"""
        response = self.client.get("/monitoring/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
    
    @patch('routers.monitoring.require_auth')
    def test_business_metrics_endpoint(self, mock_auth):
        """Test business metrics endpoint"""
        mock_auth.return_value = {"user_id": "test-user"}
        
        response = self.client.get("/monitoring/metrics/business")
        assert response.status_code == 200
        
        data = response.json()
        assert "metrics" in data
        assert "call_success_rate" in data["metrics"]
        assert "active_calls" in data["metrics"]
    
    def test_detailed_health_check_endpoint(self):
        """Test detailed health check endpoint"""
        response = self.client.get("/monitoring/health/detailed")
        assert response.status_code == 200
        
        data = response.json()
        assert "overall_status" in data
        assert "components" in data
        assert "database" in data["components"]
        assert "redis" in data["components"]
    
    @patch('routers.monitoring.require_role')
    def test_alerts_endpoint(self, mock_auth):
        """Test alerts endpoint"""
        mock_auth.return_value = {"user_id": "test-operator", "roles": ["operator"]}
        
        response = self.client.get("/monitoring/alerts")
        assert response.status_code == 200
        
        data = response.json()
        assert "alerts" in data
        assert "total_alerts" in data
    
    @patch('routers.monitoring.require_auth')
    def test_sla_status_endpoint(self, mock_auth):
        """Test SLA status endpoint"""
        mock_auth.return_value = {"user_id": "test-user"}
        
        response = self.client.get("/monitoring/sla/status")
        assert response.status_code == 200
        
        data = response.json()
        assert "sla_targets" in data
    
    @patch('routers.monitoring.require_auth')
    def test_dashboards_list_endpoint(self, mock_auth):
        """Test dashboards list endpoint"""
        mock_auth.return_value = {"user_id": "test-user"}
        
        response = self.client.get("/monitoring/dashboards")
        assert response.status_code == 200
        
        data = response.json()
        assert "dashboards" in data
        assert len(data["dashboards"]) >= 3
    
    @patch('routers.monitoring.require_auth')
    def test_dashboard_config_endpoint(self, mock_auth):
        """Test dashboard config endpoint"""
        mock_auth.return_value = {"user_id": "test-user"}
        
        response = self.client.get("/monitoring/dashboards/business-metrics")
        assert response.status_code == 200
        
        data = response.json()
        assert "title" in data
        assert "panels" in data
    
    def test_operational_status_endpoint(self):
        """Test operational status endpoint"""
        response = self.client.get("/monitoring/operational/status")
        assert response.status_code in [200, 503]  # Healthy or degraded
        
        data = response.json()
        assert "status" in data
        assert "systems" in data
        assert data["status"] in ["operational", "degraded", "outage", "unknown"]


class TestIntegrationScenarios:
    """Test integration scenarios across monitoring components"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_call_monitoring(self):
        """Test end-to-end call monitoring scenario"""
        # Setup
        metrics_collector = BusinessMetricsCollector()
        alerting_system = EnhancedAlertingSystem()
        tracer = EnhancedTracer("integration-test")
        
        # Simulate a call with monitoring
        call_id = "integration-test-call"
        hotel_id = "hotel-integration"
        language = "en"
        
        # Start tracing
        business_context = BusinessContext(
            call_id=call_id,
            hotel_id=hotel_id,
            language=language
        )
        
        async with tracer.trace_operation(
            "integration_call_handling",
            SpanType.CALL_HANDLING,
            business_context=business_context
        ):
            # Record call start
            metrics_collector.record_call_start(call_id, hotel_id, language, "inbound")
            
            # Simulate PMS operation
            with metrics_collector.measure_pms_operation(hotel_id, "apaleo", "get_availability"):
                await asyncio.sleep(0.01)  # Simulate PMS call
            
            # Record successful completion
            metrics_collector.record_call_success(call_id, hotel_id, language, "inbound", "booking_completed")
        
        # Verify call was tracked
        assert call_id not in metrics_collector.active_calls
    
    @pytest.mark.asyncio
    async def test_alert_triggering_scenario(self):
        """Test alert triggering and notification scenario"""
        alerting_system = EnhancedAlertingSystem()
        
        # Add a test notification channel
        mock_channel = Mock()
        mock_channel.send_alert = AsyncMock(return_value=True)
        alerting_system.add_notification_channel(mock_channel)
        
        # Create an alert rule
        rule = AlertRule(
            name="integration_test_alert",
            description="Integration test alert",
            severity=AlertSeverity.HIGH,
            metric_name="test_error_rate",
            threshold=0.05,
            comparison="gt",
            duration=1,
            labels={}
        )
        alerting_system.add_alert_rule(rule)
        
        # Record metric values that should trigger alert
        alerting_system.record_metric_value("test_error_rate", 0.10)
        
        # Wait and evaluate
        await asyncio.sleep(1.1)
        await alerting_system.evaluate_alert_rules()
        
        # Verify alert was created and notification sent
        assert len(alerting_system.active_alerts) > 0
        mock_channel.send_alert.assert_called()
    
    def test_dashboard_metrics_alignment(self):
        """Test that dashboard configurations align with available metrics"""
        dashboard_generator = DashboardGenerator()
        
        # Get business metrics dashboard
        dashboard = dashboard_generator.create_business_metrics_dashboard()
        
        # Extract metric queries from panels
        metric_queries = []
        for panel in dashboard["panels"]:
            if "targets" in panel:
                for target in panel["targets"]:
                    if "expr" in target:
                        metric_queries.append(target["expr"])
        
        # Verify that queries reference expected metrics
        expected_metrics = [
            "voicehive_call_success_total",
            "voicehive_call_failures_total",
            "voicehive_concurrent_calls",
            "voicehive_pms_response_seconds"
        ]
        
        query_text = " ".join(metric_queries)
        for metric in expected_metrics:
            assert metric in query_text, f"Metric {metric} not found in dashboard queries"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])