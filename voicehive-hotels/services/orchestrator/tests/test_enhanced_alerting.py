"""
Comprehensive unit tests for Enhanced Alerting System
Tests alert rules, SLA monitoring, notification channels, and alert evaluation
"""

import pytest
import asyncio
import time
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from typing import Dict, Any

from enhanced_alerting import (
    EnhancedAlertingSystem, AlertRule, Alert, SLATarget,
    AlertSeverity, AlertStatus, NotificationChannel,
    SlackNotificationChannel, PagerDutyNotificationChannel,
    setup_default_alert_rules, setup_default_sla_targets,
    enhanced_alerting
)


@pytest.fixture
def alert_rule():
    """Sample alert rule for testing"""
    return AlertRule(
        name="test_alert_rule",
        description="Test alert rule for unit testing",
        severity=AlertSeverity.HIGH,
        metric_name="test_metric",
        threshold=100.0,
        comparison="gt",
        duration=60,
        labels={"service": "test", "environment": "test"},
        runbook_url="https://docs.example.com/runbook",
        escalation_policy="test-policy"
    )


@pytest.fixture
def alert_instance():
    """Sample alert instance for testing"""
    return Alert(
        id="test-alert-123",
        rule_name="test_alert_rule",
        severity=AlertSeverity.HIGH,
        status=AlertStatus.ACTIVE,
        title="Test Alert - Threshold Breached",
        description="Test alert description",
        metric_value=150.0,
        threshold=100.0,
        labels={"service": "test", "environment": "test"},
        started_at=datetime.utcnow(),
        runbook_url="https://docs.example.com/runbook",
        escalation_policy="test-policy"
    )


@pytest.fixture
def sla_target():
    """Sample SLA target for testing"""
    return SLATarget(
        name="test_sla",
        description="Test SLA target",
        target_percentage=99.0,
        measurement_window=3600,
        metric_query="test_sla_query",
        labels={"service": "test"},
        alert_threshold=1.0
    )


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession for HTTP requests"""
    session_mock = AsyncMock()
    response_mock = AsyncMock()
    response_mock.status = 200
    response_mock.text = AsyncMock(return_value="OK")
    session_mock.post.return_value.__aenter__.return_value = response_mock
    session_mock.post.return_value.__aexit__.return_value = False
    return session_mock


class TestAlertDataModels:
    """Test alert data models and enums"""

    def test_alert_severity_enum(self):
        """Test AlertSeverity enum values"""
        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.HIGH.value == "high"
        assert AlertSeverity.MEDIUM.value == "medium"
        assert AlertSeverity.LOW.value == "low"
        assert AlertSeverity.INFO.value == "info"

    def test_alert_status_enum(self):
        """Test AlertStatus enum values"""
        assert AlertStatus.ACTIVE.value == "active"
        assert AlertStatus.RESOLVED.value == "resolved"
        assert AlertStatus.ACKNOWLEDGED.value == "acknowledged"
        assert AlertStatus.SUPPRESSED.value == "suppressed"

    def test_alert_rule_creation(self, alert_rule):
        """Test AlertRule dataclass creation"""
        assert alert_rule.name == "test_alert_rule"
        assert alert_rule.severity == AlertSeverity.HIGH
        assert alert_rule.metric_name == "test_metric"
        assert alert_rule.threshold == 100.0
        assert alert_rule.comparison == "gt"
        assert alert_rule.duration == 60
        assert alert_rule.labels == {"service": "test", "environment": "test"}
        assert alert_rule.runbook_url == "https://docs.example.com/runbook"

    def test_alert_instance_creation(self, alert_instance):
        """Test Alert dataclass creation"""
        assert alert_instance.id == "test-alert-123"
        assert alert_instance.rule_name == "test_alert_rule"
        assert alert_instance.severity == AlertSeverity.HIGH
        assert alert_instance.status == AlertStatus.ACTIVE
        assert alert_instance.metric_value == 150.0
        assert alert_instance.threshold == 100.0
        assert alert_instance.resolved_at is None

    def test_alert_instance_with_resolution(self):
        """Test Alert instance with resolution"""
        resolved_time = datetime.utcnow()
        alert = Alert(
            id="resolved-alert",
            rule_name="test_rule",
            severity=AlertSeverity.MEDIUM,
            status=AlertStatus.RESOLVED,
            title="Resolved Alert",
            description="Test resolved alert",
            metric_value=50.0,
            threshold=100.0,
            labels={},
            started_at=datetime.utcnow() - timedelta(minutes=10),
            resolved_at=resolved_time
        )

        assert alert.status == AlertStatus.RESOLVED
        assert alert.resolved_at == resolved_time

    def test_sla_target_creation(self, sla_target):
        """Test SLATarget dataclass creation"""
        assert sla_target.name == "test_sla"
        assert sla_target.target_percentage == 99.0
        assert sla_target.measurement_window == 3600
        assert sla_target.metric_query == "test_sla_query"
        assert sla_target.alert_threshold == 1.0


class TestSlackNotificationChannel:
    """Test Slack notification channel"""

    @pytest.fixture
    def slack_channel(self):
        """Slack notification channel for testing"""
        return SlackNotificationChannel(
            webhook_url="https://hooks.slack.com/test",
            channel="#test-alerts"
        )

    @pytest.mark.asyncio
    async def test_send_alert_success(self, slack_channel, alert_instance, mock_aiohttp_session):
        """Test successful Slack alert sending"""
        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            result = await slack_channel.send_alert(alert_instance)

            assert result is True
            mock_aiohttp_session.post.assert_called_once()

            # Verify payload structure
            call_args = mock_aiohttp_session.post.call_args
            payload = call_args[1]["json"]

            assert payload["channel"] == "#test-alerts"
            assert payload["username"] == "VoiceHive Alerts"
            assert "⚠️" in payload["text"]  # HIGH severity emoji
            assert len(payload["attachments"]) == 1

            attachment = payload["attachments"][0]
            assert attachment["color"] == "#FF8C00"  # HIGH severity color
            assert "Test Alert" in attachment["title"]
            assert "test-alert-123" in attachment["footer"]

    @pytest.mark.asyncio
    async def test_send_alert_critical_severity(self, slack_channel, mock_aiohttp_session):
        """Test Slack alert with critical severity"""
        critical_alert = Alert(
            id="critical-alert",
            rule_name="critical_rule",
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.ACTIVE,
            title="Critical Alert",
            description="Critical issue detected",
            metric_value=200.0,
            threshold=100.0,
            labels={},
            started_at=datetime.utcnow()
        )

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            result = await slack_channel.send_alert(critical_alert)

            assert result is True

            # Verify critical severity formatting
            call_args = mock_aiohttp_session.post.call_args
            payload = call_args[1]["json"]
            attachment = payload["attachments"][0]

            assert attachment["color"] == "#FF0000"  # Critical color
            assert "🚨" in attachment["title"]  # Critical emoji

    @pytest.mark.asyncio
    async def test_send_alert_with_runbook(self, slack_channel, mock_aiohttp_session):
        """Test Slack alert with runbook URL"""
        alert_with_runbook = Alert(
            id="alert-with-runbook",
            rule_name="test_rule",
            severity=AlertSeverity.MEDIUM,
            status=AlertStatus.ACTIVE,
            title="Alert with Runbook",
            description="Alert that includes runbook",
            metric_value=120.0,
            threshold=100.0,
            labels={"service": "test"},
            started_at=datetime.utcnow(),
            runbook_url="https://docs.example.com/runbook"
        )

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            await slack_channel.send_alert(alert_with_runbook)

            # Verify runbook field is included
            call_args = mock_aiohttp_session.post.call_args
            payload = call_args[1]["json"]
            fields = payload["attachments"][0]["fields"]

            runbook_field = next((f for f in fields if f["title"] == "Runbook"), None)
            assert runbook_field is not None
            assert "View Runbook" in runbook_field["value"]

    @pytest.mark.asyncio
    async def test_send_alert_http_error(self, slack_channel, alert_instance):
        """Test Slack alert sending with HTTP error"""
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.post.return_value.__aexit__.return_value = False

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await slack_channel.send_alert(alert_instance)

            assert result is False

    @pytest.mark.asyncio
    async def test_send_alert_exception(self, slack_channel, alert_instance):
        """Test Slack alert sending with exception"""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session_class.side_effect = Exception("Connection failed")

            result = await slack_channel.send_alert(alert_instance)

            assert result is False

    @pytest.mark.asyncio
    async def test_send_sla_violation_success(self, slack_channel, mock_aiohttp_session):
        """Test successful SLA violation notification to Slack"""
        details = {
            "measurement_window": "3600s",
            "affected_services": "payment,booking"
        }

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            result = await slack_channel.send_sla_violation(
                "test_sla", 97.5, 99.0, details
            )

            assert result is True

            # Verify SLA violation payload
            call_args = mock_aiohttp_session.post.call_args
            payload = call_args[1]["json"]

            assert payload["username"] == "VoiceHive SLA Monitor"
            assert "SLA Violation" in payload["attachments"][0]["title"]
            assert "97.5%" in payload["attachments"][0]["text"]
            assert "99.0%" in payload["attachments"][0]["text"]

            # Check additional details
            fields = payload["attachments"][0]["fields"]
            details_field = next((f for f in fields if f["title"] == "Additional Details"), None)
            assert details_field is not None

    @pytest.mark.asyncio
    async def test_send_sla_violation_without_details(self, slack_channel, mock_aiohttp_session):
        """Test SLA violation notification without additional details"""
        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            result = await slack_channel.send_sla_violation(
                "simple_sla", 98.0, 99.5, {}
            )

            assert result is True

            # Verify no additional details field when details are empty
            call_args = mock_aiohttp_session.post.call_args
            payload = call_args[1]["json"]
            fields = payload["attachments"][0]["fields"]

            details_field = next((f for f in fields if f["title"] == "Additional Details"), None)
            assert details_field is None


class TestPagerDutyNotificationChannel:
    """Test PagerDuty notification channel"""

    @pytest.fixture
    def pagerduty_channel(self):
        """PagerDuty notification channel for testing"""
        return PagerDutyNotificationChannel(integration_key="test-integration-key")

    @pytest.mark.asyncio
    async def test_send_alert_critical_success(self, pagerduty_channel, mock_aiohttp_session):
        """Test successful PagerDuty critical alert sending"""
        critical_alert = Alert(
            id="critical-pd-alert",
            rule_name="critical_rule",
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.ACTIVE,
            title="Critical System Failure",
            description="Critical system failure detected",
            metric_value=300.0,
            threshold=100.0,
            labels={"service": "api", "region": "eu-west-1"},
            started_at=datetime.utcnow(),
            runbook_url="https://docs.example.com/critical-runbook"
        )

        mock_aiohttp_session.post.return_value.__aenter__.return_value.status = 202

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            result = await pagerduty_channel.send_alert(critical_alert)

            assert result is True

            # Verify PagerDuty API payload
            call_args = mock_aiohttp_session.post.call_args
            assert call_args[0][0] == "https://events.pagerduty.com/v2/enqueue"

            payload = call_args[1]["json"]
            assert payload["routing_key"] == "test-integration-key"
            assert payload["event_action"] == "trigger"
            assert payload["dedup_key"] == "critical-pd-alert"

            event_payload = payload["payload"]
            assert event_payload["summary"] == "Critical System Failure"
            assert event_payload["severity"] == "critical"
            assert event_payload["source"] == "voicehive-hotels.orchestrator"
            assert "custom_details" in event_payload

            custom_details = event_payload["custom_details"]
            assert custom_details["metric_value"] == 300.0
            assert custom_details["threshold"] == 100.0
            assert custom_details["runbook_url"] == "https://docs.example.com/critical-runbook"

    @pytest.mark.asyncio
    async def test_send_alert_low_severity_skip(self, pagerduty_channel):
        """Test that low severity alerts are skipped in PagerDuty"""
        low_alert = Alert(
            id="low-alert",
            rule_name="low_rule",
            severity=AlertSeverity.LOW,
            status=AlertStatus.ACTIVE,
            title="Low Priority Alert",
            description="Low priority issue",
            metric_value=110.0,
            threshold=100.0,
            labels={},
            started_at=datetime.utcnow()
        )

        # Should return True without making HTTP call
        result = await pagerduty_channel.send_alert(low_alert)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_alert_http_error(self, pagerduty_channel):
        """Test PagerDuty alert sending with HTTP error"""
        high_alert = Alert(
            id="high-alert",
            rule_name="high_rule",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.ACTIVE,
            title="High Priority Alert",
            description="High priority issue",
            metric_value=200.0,
            threshold=100.0,
            labels={},
            started_at=datetime.utcnow()
        )

        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.post.return_value.__aexit__.return_value = False

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await pagerduty_channel.send_alert(high_alert)

            assert result is False

    @pytest.mark.asyncio
    async def test_send_sla_violation_success(self, pagerduty_channel, mock_aiohttp_session):
        """Test successful SLA violation notification to PagerDuty"""
        mock_aiohttp_session.post.return_value.__aenter__.return_value.status = 202

        details = {"affected_endpoints": "/api/v1/bookings", "error_rate": "5.2%"}

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            result = await pagerduty_channel.send_sla_violation(
                "booking_api_sla", 94.8, 99.0, details
            )

            assert result is True

            # Verify SLA violation payload
            call_args = mock_aiohttp_session.post.call_args
            payload = call_args[1]["json"]

            assert payload["event_action"] == "trigger"
            assert payload["dedup_key"] == "sla-violation-booking_api_sla"
            assert payload["payload"]["severity"] == "critical"  # SLA violations are always critical
            assert "SLA Violation" in payload["payload"]["summary"]

            custom_details = payload["payload"]["custom_details"]
            assert custom_details["sla_name"] == "booking_api_sla"
            assert custom_details["current_value"] == 94.8
            assert custom_details["target_value"] == 99.0
            assert custom_details["details"] == details

    @pytest.mark.asyncio
    async def test_health_check_success(self, pagerduty_channel):
        """Test successful PagerDuty health check"""
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 202
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.post.return_value.__aexit__.return_value = False

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await pagerduty_channel.health_check()

            assert result["status"] == "healthy"
            assert result["service"] == "pagerduty"
            assert result["integration_key_valid"] is True
            assert "response_time_ms" in result
            assert result["test_event_sent"] is True

    @pytest.mark.asyncio
    async def test_health_check_invalid_key(self, pagerduty_channel):
        """Test PagerDuty health check with invalid integration key"""
        mock_session = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Invalid routing key")
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.post.return_value.__aexit__.return_value = False

        with patch('aiohttp.ClientSession', return_value=mock_session):
            result = await pagerduty_channel.health_check()

            assert result["status"] == "unhealthy"
            assert result["integration_key_valid"] is False
            assert "Invalid routing key" in result["error"]

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self, pagerduty_channel):
        """Test PagerDuty health check with connection error"""
        with patch('aiohttp.ClientSession') as mock_session_class:
            mock_session_class.side_effect = Exception("Connection failed")

            result = await pagerduty_channel.health_check()

            assert result["status"] == "error"
            assert "Connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_resolve_alert_success(self, pagerduty_channel, mock_aiohttp_session):
        """Test successful alert resolution in PagerDuty"""
        mock_aiohttp_session.post.return_value.__aenter__.return_value.status = 202

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            result = await pagerduty_channel.resolve_alert("test-alert-123")

            assert result is True

            # Verify resolve payload
            call_args = mock_aiohttp_session.post.call_args
            payload = call_args[1]["json"]

            assert payload["event_action"] == "resolve"
            assert payload["dedup_key"] == "test-alert-123"

    @pytest.mark.asyncio
    async def test_acknowledge_alert_success(self, pagerduty_channel, mock_aiohttp_session):
        """Test successful alert acknowledgment in PagerDuty"""
        mock_aiohttp_session.post.return_value.__aenter__.return_value.status = 202

        with patch('aiohttp.ClientSession', return_value=mock_aiohttp_session):
            result = await pagerduty_channel.acknowledge_alert("test-alert-456")

            assert result is True

            # Verify acknowledge payload
            call_args = mock_aiohttp_session.post.call_args
            payload = call_args[1]["json"]

            assert payload["event_action"] == "acknowledge"
            assert payload["dedup_key"] == "test-alert-456"

    def test_get_health_status(self, pagerduty_channel):
        """Test getting current health status without new check"""
        # Initially unknown
        status = pagerduty_channel.get_health_status()
        assert status["status"] == "unknown"
        assert status["last_check"] is None

        # After setting health status
        pagerduty_channel._health_status = "healthy"
        pagerduty_channel._last_health_check = datetime.utcnow()

        status = pagerduty_channel.get_health_status()
        assert status["status"] == "healthy"
        assert status["last_check"] is not None


class TestEnhancedAlertingSystem:
    """Test main enhanced alerting system"""

    @pytest.fixture
    def alerting_system(self):
        """Enhanced alerting system for testing"""
        return EnhancedAlertingSystem()

    @pytest.fixture
    def mock_notification_channel(self):
        """Mock notification channel for testing"""
        channel = Mock(spec=NotificationChannel)
        channel.send_alert = AsyncMock(return_value=True)
        channel.send_sla_violation = AsyncMock(return_value=True)
        return channel

    def test_add_notification_channel(self, alerting_system, mock_notification_channel):
        """Test adding notification channel"""
        alerting_system.add_notification_channel(mock_notification_channel)
        assert len(alerting_system.notification_channels) == 1
        assert alerting_system.notification_channels[0] == mock_notification_channel

    def test_add_alert_rule(self, alerting_system, alert_rule):
        """Test adding alert rule"""
        alerting_system.add_alert_rule(alert_rule)
        assert "test_alert_rule" in alerting_system.alert_rules
        assert alerting_system.alert_rules["test_alert_rule"] == alert_rule

    def test_add_sla_target(self, alerting_system, sla_target):
        """Test adding SLA target"""
        alerting_system.add_sla_target(sla_target)
        assert "test_sla" in alerting_system.sla_targets
        assert alerting_system.sla_targets["test_sla"] == sla_target

    def test_record_metric_value(self, alerting_system):
        """Test recording metric values"""
        labels = {"service": "api", "region": "us-east-1"}

        alerting_system.record_metric_value("test_metric", 100.0, labels)
        alerting_system.record_metric_value("test_metric", 150.0, labels)

        assert "test_metric" in alerting_system.metric_values
        assert len(alerting_system.metric_values["test_metric"]) == 2

        # Check values are stored correctly
        values = alerting_system.metric_values["test_metric"]
        assert values[0][1] == 100.0  # First value
        assert values[1][1] == 150.0  # Second value
        assert values[0][2] == labels  # Labels

    def test_record_metric_value_cleanup_old_data(self, alerting_system):
        """Test that old metric values are cleaned up"""
        current_time = time.time()
        old_time = current_time - 7200  # 2 hours ago (outside 1 hour window)

        # Mock time.time() to return old timestamp for first entry
        with patch('time.time', return_value=old_time):
            alerting_system.record_metric_value("cleanup_metric", 50.0)

        # Record new value with current time
        with patch('time.time', return_value=current_time):
            alerting_system.record_metric_value("cleanup_metric", 100.0)

        # Should only have the recent value (within 1 hour)
        assert len(alerting_system.metric_values["cleanup_metric"]) == 1
        assert alerting_system.metric_values["cleanup_metric"][0][1] == 100.0

    def test_labels_match(self, alerting_system):
        """Test label matching logic"""
        metric_labels = {"service": "api", "region": "us-east-1", "version": "1.0"}
        rule_labels = {"service": "api", "region": "us-east-1"}

        # Should match (rule labels subset of metric labels)
        assert alerting_system._labels_match(metric_labels, rule_labels) is True

        # Should not match (missing required label)
        rule_labels_missing = {"service": "api", "environment": "prod"}
        assert alerting_system._labels_match(metric_labels, rule_labels_missing) is False

        # Should not match (different value)
        rule_labels_different = {"service": "web", "region": "us-east-1"}
        assert alerting_system._labels_match(metric_labels, rule_labels_different) is False

        # Empty rule labels should always match
        assert alerting_system._labels_match(metric_labels, {}) is True

    def test_check_threshold_operations(self, alerting_system):
        """Test threshold checking operations"""
        # Greater than
        assert alerting_system._check_threshold(150.0, 100.0, "gt") is True
        assert alerting_system._check_threshold(50.0, 100.0, "gt") is False

        # Greater than or equal
        assert alerting_system._check_threshold(100.0, 100.0, "gte") is True
        assert alerting_system._check_threshold(150.0, 100.0, "gte") is True
        assert alerting_system._check_threshold(50.0, 100.0, "gte") is False

        # Less than
        assert alerting_system._check_threshold(50.0, 100.0, "lt") is True
        assert alerting_system._check_threshold(150.0, 100.0, "lt") is False

        # Less than or equal
        assert alerting_system._check_threshold(100.0, 100.0, "lte") is True
        assert alerting_system._check_threshold(50.0, 100.0, "lte") is True
        assert alerting_system._check_threshold(150.0, 100.0, "lte") is False

        # Equal
        assert alerting_system._check_threshold(100.0, 100.0, "eq") is True
        assert alerting_system._check_threshold(150.0, 100.0, "eq") is False

        # Invalid comparison
        assert alerting_system._check_threshold(150.0, 100.0, "invalid") is False

    @pytest.mark.asyncio
    async def test_evaluate_single_rule_trigger_alert(self, alerting_system, alert_rule, mock_notification_channel):
        """Test evaluating rule that triggers new alert"""
        alerting_system.add_alert_rule(alert_rule)
        alerting_system.add_notification_channel(mock_notification_channel)

        # Record metric value that breaches threshold
        current_time = time.time()
        with patch('time.time', return_value=current_time):
            alerting_system.record_metric_value(
                "test_metric", 150.0, {"service": "test", "environment": "test"}
            )

        await alerting_system._evaluate_single_rule(alert_rule)

        # Check that alert was created
        assert len(alerting_system.active_alerts) == 1
        alert_id = list(alerting_system.active_alerts.keys())[0]
        alert = alerting_system.active_alerts[alert_id]

        assert alert.rule_name == "test_alert_rule"
        assert alert.status == AlertStatus.ACTIVE
        assert alert.metric_value == 150.0
        assert alert.threshold == 100.0

        # Check that notification was sent
        mock_notification_channel.send_alert.assert_called_once_with(alert)

    @pytest.mark.asyncio
    async def test_evaluate_single_rule_resolve_alert(self, alerting_system, alert_rule, mock_notification_channel):
        """Test evaluating rule that resolves existing alert"""
        alerting_system.add_alert_rule(alert_rule)
        alerting_system.add_notification_channel(mock_notification_channel)

        # Create existing active alert
        alert_id = "test-alert-existing"
        existing_alert = Alert(
            id=alert_id,
            rule_name="test_alert_rule",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.ACTIVE,
            title="Test Alert",
            description="Test alert",
            metric_value=150.0,
            threshold=100.0,
            labels={"service": "test", "environment": "test"},
            started_at=datetime.utcnow() - timedelta(minutes=5)
        )
        alerting_system.active_alerts[alert_id] = existing_alert

        # Record metric value that doesn't breach threshold
        current_time = time.time()
        with patch('time.time', return_value=current_time):
            alerting_system.record_metric_value(
                "test_metric", 50.0, {"service": "test", "environment": "test"}
            )

        await alerting_system._evaluate_single_rule(alert_rule)

        # Check that alert was resolved
        alert = alerting_system.active_alerts[alert_id]
        assert alert.status == AlertStatus.RESOLVED
        assert alert.resolved_at is not None

    @pytest.mark.asyncio
    async def test_evaluate_single_rule_no_data(self, alerting_system, alert_rule):
        """Test evaluating rule with no metric data"""
        alerting_system.add_alert_rule(alert_rule)

        # No metric data recorded
        await alerting_system._evaluate_single_rule(alert_rule)

        # Should not create any alerts
        assert len(alerting_system.active_alerts) == 0

    @pytest.mark.asyncio
    async def test_evaluate_single_rule_insufficient_duration(self, alerting_system, mock_notification_channel):
        """Test evaluating rule with insufficient duration"""
        # Create rule with 120 second duration
        rule = AlertRule(
            name="duration_test_rule",
            description="Test rule for duration",
            severity=AlertSeverity.MEDIUM,
            metric_name="duration_metric",
            threshold=100.0,
            comparison="gt",
            duration=120,  # 2 minutes
            labels={}
        )

        alerting_system.add_alert_rule(rule)
        alerting_system.add_notification_channel(mock_notification_channel)

        # Record value that breaches threshold but is too recent
        current_time = time.time()
        recent_time = current_time - 30  # Only 30 seconds ago

        with patch('time.time', return_value=recent_time):
            alerting_system.record_metric_value("duration_metric", 150.0, {})

        # Evaluate with current time
        with patch('time.time', return_value=current_time):
            await alerting_system._evaluate_single_rule(rule)

        # Should not create alert (insufficient duration)
        assert len(alerting_system.active_alerts) == 0

    @pytest.mark.asyncio
    async def test_evaluate_alert_rules_exception_handling(self, alerting_system):
        """Test alert rule evaluation with exceptions"""
        # Add rule that will cause evaluation to fail
        broken_rule = AlertRule(
            name="broken_rule",
            description="Rule that causes evaluation to fail",
            severity=AlertSeverity.LOW,
            metric_name="broken_metric",
            threshold=100.0,
            comparison="gt",
            duration=60,
            labels={}
        )
        alerting_system.add_alert_rule(broken_rule)

        # Mock _evaluate_single_rule to raise exception
        with patch.object(alerting_system, '_evaluate_single_rule', side_effect=Exception("Evaluation failed")):
            # Should not raise exception
            await alerting_system.evaluate_alert_rules()

    @pytest.mark.asyncio
    async def test_send_alert_notifications_exception_handling(self, alerting_system):
        """Test alert notification sending with exceptions"""
        # Add mock channel that raises exception
        failing_channel = Mock(spec=NotificationChannel)
        failing_channel.send_alert = AsyncMock(side_effect=Exception("Notification failed"))
        alerting_system.add_notification_channel(failing_channel)

        alert = Alert(
            id="test-alert",
            rule_name="test_rule",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.ACTIVE,
            title="Test Alert",
            description="Test alert",
            metric_value=150.0,
            threshold=100.0,
            labels={},
            started_at=datetime.utcnow()
        )

        # Should not raise exception
        await alerting_system._send_alert_notifications(alert)

        # Verify the failing channel was called
        failing_channel.send_alert.assert_called_once_with(alert)

    @pytest.mark.asyncio
    async def test_calculate_sla_value_call_success_rate(self, alerting_system):
        """Test SLA value calculation for call success rate"""
        target = SLATarget(
            name="call_sla",
            description="Call success rate SLA",
            target_percentage=99.0,
            measurement_window=3600,
            metric_query="call_success_rate",
            labels={},
            alert_threshold=1.0
        )

        # Record success and failure metrics
        current_time = time.time()
        window_start = current_time - 3600

        # Add some success and failure data
        for i in range(95):  # 95 successes
            alerting_system.record_metric_value("call_success", 1.0, {})

        for i in range(5):   # 5 failures
            alerting_system.record_metric_value("call_failure", 1.0, {})

        sla_value = await alerting_system._calculate_sla_value(target, window_start, current_time)

        # Should calculate 95% success rate (95 successes / 100 total)
        assert sla_value == 95.0

    @pytest.mark.asyncio
    async def test_calculate_sla_value_no_data(self, alerting_system):
        """Test SLA value calculation with no data"""
        target = SLATarget(
            name="empty_sla",
            description="SLA with no data",
            target_percentage=99.0,
            measurement_window=3600,
            metric_query="call_success_rate",
            labels={},
            alert_threshold=1.0
        )

        current_time = time.time()
        window_start = current_time - 3600

        sla_value = await alerting_system._calculate_sla_value(target, window_start, current_time)

        # Should return None when no data available
        assert sla_value is None

    @pytest.mark.asyncio
    async def test_evaluate_single_sla_violation(self, alerting_system, mock_notification_channel):
        """Test SLA evaluation that detects violation"""
        target = SLATarget(
            name="violation_sla",
            description="SLA that will be violated",
            target_percentage=99.0,
            measurement_window=3600,
            metric_query="call_success_rate",
            labels={},
            alert_threshold=1.0  # Alert if below 98%
        )

        alerting_system.add_sla_target(target)
        alerting_system.add_notification_channel(mock_notification_channel)

        # Mock SLA calculation to return violation
        with patch.object(alerting_system, '_calculate_sla_value', return_value=97.5):
            await alerting_system._evaluate_single_sla(target)

        # Check that violation was recorded
        assert "violation_sla" in alerting_system.sla_violations

        # Check that notification was sent
        mock_notification_channel.send_sla_violation.assert_called_once()
        call_args = mock_notification_channel.send_sla_violation.call_args
        assert call_args[0][0] == "violation_sla"  # sla_name
        assert call_args[0][1] == 97.5             # current_value
        assert call_args[0][2] == 99.0             # target_value

    @pytest.mark.asyncio
    async def test_evaluate_single_sla_resolution(self, alerting_system):
        """Test SLA evaluation that resolves existing violation"""
        target = SLATarget(
            name="resolving_sla",
            description="SLA that will be resolved",
            target_percentage=99.0,
            measurement_window=3600,
            metric_query="call_success_rate",
            labels={},
            alert_threshold=1.0
        )

        alerting_system.add_sla_target(target)

        # Add existing violation
        violation_time = datetime.utcnow() - timedelta(minutes=10)
        alerting_system.sla_violations["resolving_sla"] = violation_time

        # Mock SLA calculation to return healthy value
        with patch.object(alerting_system, '_calculate_sla_value', return_value=99.5):
            await alerting_system._evaluate_single_sla(target)

        # Check that violation was resolved
        assert "resolving_sla" not in alerting_system.sla_violations

    @pytest.mark.asyncio
    async def test_start_stop_alerting_system(self, alerting_system):
        """Test starting and stopping the alerting system"""
        assert alerting_system._running is False
        assert len(alerting_system._tasks) == 0

        # Start the system
        await alerting_system.start()

        assert alerting_system._running is True
        assert len(alerting_system._tasks) == 2  # Alert and SLA evaluation tasks

        # Stop the system
        await alerting_system.stop()

        assert alerting_system._running is False
        assert len(alerting_system._tasks) == 0

    @pytest.mark.asyncio
    async def test_start_already_running(self, alerting_system):
        """Test starting system when already running"""
        await alerting_system.start()
        initial_tasks = alerting_system._tasks.copy()

        # Start again
        await alerting_system.start()

        # Should not create duplicate tasks
        assert len(alerting_system._tasks) == len(initial_tasks)

        await alerting_system.stop()

    @pytest.mark.asyncio
    async def test_evaluation_loops(self, alerting_system):
        """Test that evaluation loops run without errors"""
        # Add a simple rule and target
        rule = AlertRule(
            name="loop_test_rule",
            description="Rule for loop testing",
            severity=AlertSeverity.LOW,
            metric_name="loop_metric",
            threshold=100.0,
            comparison="gt",
            duration=1,  # Very short duration for testing
            labels={}
        )
        alerting_system.add_alert_rule(rule)

        target = SLATarget(
            name="loop_test_sla",
            description="SLA for loop testing",
            target_percentage=99.0,
            measurement_window=60,
            metric_query="test_sla",
            labels={},
            alert_threshold=1.0
        )
        alerting_system.add_sla_target(target)

        # Start the system briefly
        await alerting_system.start()
        await asyncio.sleep(0.1)  # Let loops run once
        await alerting_system.stop()

        # Should complete without errors


class TestDefaultSetupFunctions:
    """Test default alert rules and SLA targets setup"""

    def test_setup_default_alert_rules(self):
        """Test setting up default alert rules"""
        # Clear any existing rules
        enhanced_alerting.alert_rules.clear()

        setup_default_alert_rules()

        # Should have created default rules
        assert len(enhanced_alerting.alert_rules) > 0
        assert "high_call_failure_rate" in enhanced_alerting.alert_rules
        assert "slow_pms_response" in enhanced_alerting.alert_rules
        assert "high_memory_usage" in enhanced_alerting.alert_rules

        # Verify rule properties
        call_failure_rule = enhanced_alerting.alert_rules["high_call_failure_rate"]
        assert call_failure_rule.severity == AlertSeverity.HIGH
        assert call_failure_rule.threshold == 0.05
        assert call_failure_rule.comparison == "gt"
        assert call_failure_rule.runbook_url is not None

    def test_setup_default_sla_targets(self):
        """Test setting up default SLA targets"""
        # Clear any existing targets
        enhanced_alerting.sla_targets.clear()

        setup_default_sla_targets()

        # Should have created default SLA targets
        assert len(enhanced_alerting.sla_targets) > 0
        assert "call_success_rate_sla" in enhanced_alerting.sla_targets
        assert "pms_availability_sla" in enhanced_alerting.sla_targets

        # Verify SLA properties
        call_sla = enhanced_alerting.sla_targets["call_success_rate_sla"]
        assert call_sla.target_percentage == 99.0
        assert call_sla.measurement_window == 3600
        assert call_sla.alert_threshold == 1.0

        pms_sla = enhanced_alerting.sla_targets["pms_availability_sla"]
        assert pms_sla.target_percentage == 99.5
        assert pms_sla.alert_threshold == 0.5


class TestGlobalAlertingInstance:
    """Test global alerting instance"""

    def test_global_instance_exists(self):
        """Test that global enhanced_alerting instance exists"""
        assert enhanced_alerting is not None
        assert isinstance(enhanced_alerting, EnhancedAlertingSystem)

    def test_global_instance_is_singleton(self):
        """Test that global instance behaves like singleton"""
        from enhanced_alerting import enhanced_alerting as imported_instance
        assert enhanced_alerting is imported_instance


if __name__ == "__main__":
    pytest.main([__file__])