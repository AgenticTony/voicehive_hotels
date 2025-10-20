"""
Comprehensive unit tests for email alerting service
Tests EmailConfig validation, EmailTemplate rendering, and EmailNotificationChannel functionality
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from pathlib import Path
import tempfile
import os
from email.mime.multipart import MIMEMultipart

# Import the modules under test
from services.orchestrator.alerting.email_service import (
    EmailConfig,
    EmailTemplate,
    EmailNotificationChannel,
    create_email_notification_channel
)
from services.orchestrator.enhanced_alerting import (
    Alert,
    AlertSeverity,
    AlertStatus
)


class TestEmailConfig:
    """Test EmailConfig validation and configuration"""

    def test_valid_email_config(self):
        """Test creating a valid email configuration"""
        config = EmailConfig(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            username="alerts@company.com",
            password="securepass123",
            from_email="alerts@company.com",
            from_name="Company Alerts",
            critical_recipients=["admin@company.com"],
            high_recipients=["devops@company.com"],
            sla_recipients=["sre@company.com"]
        )

        assert config.smtp_host == "smtp.gmail.com"
        assert config.smtp_port == 587
        assert config.username == "alerts@company.com"
        assert config.from_email == "alerts@company.com"
        assert "admin@company.com" in config.critical_recipients
        assert "devops@company.com" in config.high_recipients
        assert "sre@company.com" in config.sla_recipients

    def test_email_address_validation(self):
        """Test email address validation"""
        # Valid email addresses should pass
        valid_config = EmailConfig(
            smtp_host="smtp.company.com",
            smtp_port=587,
            username="alerts@company.com",
            password="securepass123",
            from_email="alerts@company.com",
            critical_recipients=["admin@company.com", "user+tag@domain.co.uk"]
        )
        assert len(valid_config.critical_recipients) == 2

        # Invalid email addresses should fail
        with pytest.raises(ValueError, match="Invalid email address"):
            EmailConfig(
                smtp_host="smtp.company.com",
                smtp_port=587,
                username="alerts@company.com",
                password="securepass123",
                from_email="invalid-email",  # Invalid email
                critical_recipients=["admin@company.com"]
            )

        with pytest.raises(ValueError, match="Invalid email address"):
            EmailConfig(
                smtp_host="smtp.company.com",
                smtp_port=587,
                username="alerts@company.com",
                password="securepass123",
                from_email="alerts@company.com",
                critical_recipients=["invalid-email-format"]  # Invalid recipient
            )

    def test_smtp_host_validation(self):
        """Test SMTP host validation"""
        # Localhost should be rejected
        with pytest.raises(ValueError, match="Localhost SMTP not allowed"):
            EmailConfig(
                smtp_host="localhost",
                smtp_port=587,
                username="test",
                password="securepass123",
                from_email="test@company.com"
            )

        with pytest.raises(ValueError, match="Localhost SMTP not allowed"):
            EmailConfig(
                smtp_host="127.0.0.1",
                smtp_port=587,
                username="test",
                password="securepass123",
                from_email="test@company.com"
            )

    def test_password_validation(self):
        """Test SMTP password validation"""
        # Short password should fail
        with pytest.raises(ValueError, match="SMTP password must be at least 8 characters"):
            EmailConfig(
                smtp_host="smtp.company.com",
                smtp_port=587,
                username="test",
                password="short",  # Too short
                from_email="test@company.com"
            )

        # Weak password should fail
        with pytest.raises(ValueError, match="Weak SMTP password detected"):
            EmailConfig(
                smtp_host="smtp.company.com",
                smtp_port=587,
                username="test",
                password="password",  # Weak password
                from_email="test@company.com"
            )

    def test_smtp_port_validation(self):
        """Test SMTP port validation"""
        # Standard ports should work
        for port in [25, 465, 587, 2525]:
            config = EmailConfig(
                smtp_host="smtp.company.com",
                smtp_port=port,
                username="test",
                password="securepass123",
                from_email="test@company.com"
            )
            assert config.smtp_port == port

        # Non-standard port should work but may log warning
        config = EmailConfig(
            smtp_host="smtp.company.com",
            smtp_port=1025,  # Non-standard port
            username="test",
            password="securepass123",
            from_email="test@company.com"
        )
        assert config.smtp_port == 1025


class TestEmailTemplate:
    """Test EmailTemplate rendering functionality"""

    def setup_method(self):
        """Set up test fixtures"""
        # Create a temporary directory for templates
        self.temp_dir = tempfile.mkdtemp()
        self.template_manager = EmailTemplate(self.temp_dir)

        # Create a sample alert for testing
        self.sample_alert = Alert(
            id="test-alert-123",
            rule_name="test_rule",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.ACTIVE,
            title="Test Alert",
            description="This is a test alert",
            metric_value=95.5,
            threshold=90.0,
            labels={"service": "api", "environment": "production"},
            started_at=datetime(2025, 10, 20, 12, 0, 0),
            runbook_url="https://docs.company.com/runbooks/test"
        )

    def teardown_method(self):
        """Clean up test fixtures"""
        # Clean up temporary directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_severity_emoji_mapping(self):
        """Test severity emoji mapping"""
        assert self.template_manager._get_severity_emoji(AlertSeverity.CRITICAL) == "🚨"
        assert self.template_manager._get_severity_emoji(AlertSeverity.HIGH) == "⚠️"
        assert self.template_manager._get_severity_emoji(AlertSeverity.MEDIUM) == "⚡"
        assert self.template_manager._get_severity_emoji(AlertSeverity.LOW) == "ℹ️"
        assert self.template_manager._get_severity_emoji(AlertSeverity.INFO) == "📊"

    def test_severity_color_mapping(self):
        """Test severity color mapping"""
        assert self.template_manager._get_severity_color(AlertSeverity.CRITICAL) == "#FF0000"
        assert self.template_manager._get_severity_color(AlertSeverity.HIGH) == "#FF8C00"
        assert self.template_manager._get_severity_color(AlertSeverity.MEDIUM) == "#FFD700"
        assert self.template_manager._get_severity_color(AlertSeverity.LOW) == "#32CD32"
        assert self.template_manager._get_severity_color(AlertSeverity.INFO) == "#87CEEB"

    def test_duration_formatting(self):
        """Test alert duration formatting"""
        # Test ongoing alert (no resolution time)
        ongoing_alert = Alert(
            id="test-alert",
            rule_name="test_rule",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.ACTIVE,
            title="Test Alert",
            description="Test",
            metric_value=95.5,
            threshold=90.0,
            labels={},
            started_at=datetime(2025, 10, 20, 12, 0, 0)
        )
        assert self.template_manager._format_duration(ongoing_alert) == "Ongoing"

        # Test resolved alert with various durations
        resolved_alert = Alert(
            id="test-alert",
            rule_name="test_rule",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.RESOLVED,
            title="Test Alert",
            description="Test",
            metric_value=95.5,
            threshold=90.0,
            labels={},
            started_at=datetime(2025, 10, 20, 12, 0, 0),
            resolved_at=datetime(2025, 10, 20, 13, 30, 45)  # 1h 30m 45s later
        )
        assert self.template_manager._format_duration(resolved_alert) == "1h 30m 45s"

        # Test short duration
        short_duration_alert = Alert(
            id="test-alert",
            rule_name="test_rule",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.RESOLVED,
            title="Test Alert",
            description="Test",
            metric_value=95.5,
            threshold=90.0,
            labels={},
            started_at=datetime(2025, 10, 20, 12, 0, 0),
            resolved_at=datetime(2025, 10, 20, 12, 0, 30)  # 30s later
        )
        assert self.template_manager._format_duration(short_duration_alert) == "30s"

    def test_fallback_alert_email_generation(self):
        """Test fallback email generation when templates are missing"""
        html_content, text_content = self.template_manager._generate_fallback_alert_email(
            self.sample_alert, "alert"
        )

        # Check HTML content
        assert "Test Alert" in html_content
        assert "This is a test alert" in html_content
        assert "95.50" in html_content  # metric value
        assert "90.00" in html_content  # threshold
        assert "HIGH" in html_content   # severity
        assert "test-alert-123" in html_content  # alert ID
        assert self.sample_alert.runbook_url in html_content

        # Check text content
        assert "Test Alert" in text_content
        assert "This is a test alert" in text_content
        assert "95.50" in text_content
        assert "90.00" in text_content
        assert "HIGH" in text_content
        assert "test-alert-123" in text_content
        assert self.sample_alert.runbook_url in text_content

    def test_fallback_sla_email_generation(self):
        """Test fallback SLA violation email generation"""
        sla_name = "API Response Time SLA"
        current_value = 95.5
        target_value = 99.0
        details = {"window": "1h", "requests": 1000}

        html_content, text_content = self.template_manager._generate_fallback_sla_email(
            sla_name, current_value, target_value, details
        )

        # Check HTML content
        assert sla_name in html_content
        assert "95.50%" in html_content
        assert "99.00%" in html_content
        assert "3.50%" in html_content  # violation percentage
        assert "window: 1h" in html_content
        assert "requests: 1000" in html_content

        # Check text content
        assert sla_name in text_content
        assert "95.50%" in text_content
        assert "99.00%" in text_content
        assert "3.50%" in text_content
        assert "window: 1h" in text_content
        assert "requests: 1000" in text_content

    def test_template_rendering_with_missing_templates(self):
        """Test template rendering falls back to simple templates when Jinja templates are missing"""
        # This should fall back to simple template generation
        html_content, text_content = self.template_manager.render_alert_email(self.sample_alert)

        assert html_content is not None
        assert text_content is not None
        assert "Test Alert" in html_content
        assert "Test Alert" in text_content


class TestEmailNotificationChannel:
    """Test EmailNotificationChannel functionality"""

    def setup_method(self):
        """Set up test fixtures"""
        self.config = EmailConfig(
            smtp_host="smtp.test.com",
            smtp_port=587,
            username="test@company.com",
            password="securepass123",
            from_email="alerts@company.com",
            from_name="Test Alerts",
            critical_recipients=["admin@company.com"],
            high_recipients=["devops@company.com"],
            medium_recipients=["team@company.com"],
            sla_recipients=["sre@company.com"]
        )

        self.temp_dir = tempfile.mkdtemp()
        self.email_channel = EmailNotificationChannel(self.config, self.temp_dir)

        self.sample_alert = Alert(
            id="test-alert-456",
            rule_name="cpu_usage_high",
            severity=AlertSeverity.HIGH,
            status=AlertStatus.ACTIVE,
            title="High CPU Usage",
            description="CPU usage is above 80%",
            metric_value=85.0,
            threshold=80.0,
            labels={"host": "web-01"},
            started_at=datetime(2025, 10, 20, 14, 0, 0)
        )

    def teardown_method(self):
        """Clean up test fixtures"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_recipients_for_severity(self):
        """Test recipient selection based on alert severity"""
        assert self.email_channel._get_recipients_for_severity(AlertSeverity.CRITICAL) == ["admin@company.com"]
        assert self.email_channel._get_recipients_for_severity(AlertSeverity.HIGH) == ["devops@company.com"]
        assert self.email_channel._get_recipients_for_severity(AlertSeverity.MEDIUM) == ["team@company.com"]
        assert self.email_channel._get_recipients_for_severity(AlertSeverity.LOW) == []  # No low recipients configured
        assert self.email_channel._get_recipients_for_severity(AlertSeverity.INFO) == []  # No info recipients configured

    def test_create_multipart_message(self):
        """Test multipart email message creation"""
        html_content = "<html><body><h1>Test Alert</h1></body></html>"
        text_content = "Test Alert\n\nThis is a test alert."
        recipients = ["test@company.com", "admin@company.com"]
        subject = "[HIGH] Test Alert"

        message = self.email_channel._create_multipart_message(
            subject, html_content, text_content, recipients
        )

        assert isinstance(message, MIMEMultipart)
        assert message["Subject"] == subject
        assert message["To"] == "test@company.com, admin@company.com"
        assert message["From"] == "Test Alerts <alerts@company.com>"
        assert message["X-Priority"] == "1"  # High priority

        # Check that both text and HTML parts are included
        parts = message.get_payload()
        assert len(parts) == 2
        assert parts[0].get_content_type() == "text/plain"
        assert parts[1].get_content_type() == "text/html"

    @pytest.mark.asyncio
    async def test_send_email_success(self):
        """Test successful email sending"""
        with patch('services.orchestrator.alerting.email_service.aiosmtplib.SMTP') as mock_smtp_class:
            # Mock SMTP client
            mock_smtp = AsyncMock()
            mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
            mock_smtp.__aexit__ = AsyncMock(return_value=None)
            mock_smtp.login = AsyncMock()
            mock_smtp.send_message = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            # Create a test message
            html_content = "<html><body>Test</body></html>"
            text_content = "Test"
            recipients = ["test@company.com"]
            subject = "Test Subject"

            message = self.email_channel._create_multipart_message(
                subject, html_content, text_content, recipients
            )

            # Test sending
            result = await self.email_channel._send_email(message)

            assert result is True
            mock_smtp_class.assert_called_once()
            mock_smtp.login.assert_called_once_with(self.config.username, self.config.password)
            mock_smtp.send_message.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_email_smtp_error(self):
        """Test email sending with SMTP error"""
        with patch('services.orchestrator.alerting.email_service.aiosmtplib.SMTP') as mock_smtp_class:
            # Mock SMTP client to raise an exception
            mock_smtp = AsyncMock()
            mock_smtp.__aenter__ = AsyncMock(side_effect=Exception("SMTP connection failed"))
            mock_smtp_class.return_value = mock_smtp

            # Create a test message
            html_content = "<html><body>Test</body></html>"
            text_content = "Test"
            recipients = ["test@company.com"]
            subject = "Test Subject"

            message = self.email_channel._create_multipart_message(
                subject, html_content, text_content, recipients
            )

            # Test sending with error
            result = await self.email_channel._send_email(message)

            assert result is False
            mock_smtp_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_alert_success(self):
        """Test successful alert notification sending"""
        with patch.object(self.email_channel, '_send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await self.email_channel.send_alert(self.sample_alert)

            assert result is True
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_alert_no_recipients(self):
        """Test alert sending with no configured recipients"""
        # Create alert with severity that has no recipients
        low_alert = Alert(
            id="test-alert",
            rule_name="test_rule",
            severity=AlertSeverity.LOW,  # No recipients configured for LOW
            status=AlertStatus.ACTIVE,
            title="Low Priority Alert",
            description="This is a low priority alert",
            metric_value=10.0,
            threshold=5.0,
            labels={},
            started_at=datetime.now()
        )

        result = await self.email_channel.send_alert(low_alert)

        # Should return True (no failure) even when no recipients are configured
        assert result is True

    @pytest.mark.asyncio
    async def test_send_sla_violation_success(self):
        """Test successful SLA violation notification sending"""
        with patch.object(self.email_channel, '_send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            result = await self.email_channel.send_sla_violation(
                "API Response Time SLA",
                95.5,
                99.0,
                {"window": "1h", "requests": 1000}
            )

            assert result is True
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_sla_violation_no_recipients(self):
        """Test SLA violation sending with no configured recipients"""
        # Temporarily clear SLA recipients
        original_recipients = self.config.sla_recipients
        self.config.sla_recipients = []

        result = await self.email_channel.send_sla_violation(
            "API Response Time SLA",
            95.5,
            99.0,
            {"window": "1h"}
        )

        # Should return True even when no recipients are configured
        assert result is True

        # Restore original recipients
        self.config.sla_recipients = original_recipients

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test successful health check"""
        with patch('services.orchestrator.alerting.email_service.aiosmtplib.SMTP') as mock_smtp_class:
            # Mock successful SMTP connection
            mock_smtp = AsyncMock()
            mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
            mock_smtp.__aexit__ = AsyncMock(return_value=None)
            mock_smtp.login = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            result = await self.email_channel.health_check()

            assert result["status"] == "healthy"
            assert result["service"] == "smtp"
            assert result["smtp_host"] == self.config.smtp_host
            assert result["smtp_port"] == self.config.smtp_port
            assert "response_time_ms" in result
            assert result["connection_successful"] is True
            assert result["authentication_successful"] is True

    @pytest.mark.asyncio
    async def test_health_check_auth_failure(self):
        """Test health check with authentication failure"""
        with patch('services.orchestrator.alerting.email_service.aiosmtplib.SMTP') as mock_smtp_class:
            from services.orchestrator.alerting.email_service import aiosmtplib

            # Mock SMTP authentication error
            mock_smtp = AsyncMock()
            mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
            mock_smtp.__aexit__ = AsyncMock(return_value=None)
            mock_smtp.login = AsyncMock(side_effect=aiosmtplib.SMTPAuthenticationError("Authentication failed"))
            mock_smtp_class.return_value = mock_smtp

            result = await self.email_channel.health_check()

            assert result["status"] == "auth_failed"
            assert result["service"] == "smtp"
            assert "Authentication failed" in result["error"]

    @pytest.mark.asyncio
    async def test_health_check_connection_failure(self):
        """Test health check with connection failure"""
        with patch('services.orchestrator.alerting.email_service.aiosmtplib.SMTP') as mock_smtp_class:
            from services.orchestrator.alerting.email_service import aiosmtplib

            # Mock SMTP connection error
            mock_smtp = AsyncMock()
            mock_smtp.__aenter__ = AsyncMock(side_effect=aiosmtplib.SMTPException("Connection failed"))
            mock_smtp_class.return_value = mock_smtp

            result = await self.email_channel.health_check()

            assert result["status"] == "smtp_error"
            assert result["service"] == "smtp"
            assert "SMTP error" in result["error"]

    def test_get_health_status(self):
        """Test getting current health status without performing check"""
        # Initially should be unknown
        status = self.email_channel.get_health_status()
        assert status["status"] == "unknown"
        assert status["service"] == "smtp"
        assert status["smtp_host"] == self.config.smtp_host
        assert status["last_check"] is None


class TestEmailServiceFactory:
    """Test email service factory functions"""

    def test_create_email_notification_channel(self):
        """Test factory function for creating email notification channel"""
        channel = create_email_notification_channel(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            username="test@gmail.com",
            password="securepass123",
            from_email="alerts@company.com",
            critical_recipients=["admin@company.com"],
            high_recipients=["devops@company.com"]
        )

        assert isinstance(channel, EmailNotificationChannel)
        assert channel.config.smtp_host == "smtp.gmail.com"
        assert channel.config.smtp_port == 587
        assert channel.config.username == "test@gmail.com"
        assert channel.config.from_email == "alerts@company.com"
        assert "admin@company.com" in channel.config.critical_recipients
        assert "devops@company.com" in channel.config.high_recipients

    def test_create_email_notification_channel_with_defaults(self):
        """Test factory function with default values"""
        channel = create_email_notification_channel(
            smtp_host="smtp.company.com",
            smtp_port=587,
            username="alerts@company.com",
            password="securepass123",
            from_email="alerts@company.com"
        )

        assert isinstance(channel, EmailNotificationChannel)
        assert channel.config.from_name == "VoiceHive Hotels Alerts"  # Default value
        assert channel.config.use_tls is True  # Default value
        assert channel.config.start_tls is True  # Default value
        assert len(channel.config.critical_recipients) == 0  # Empty default


class TestEmailServiceIntegration:
    """Integration tests for email service components"""

    def setup_method(self):
        """Set up integration test fixtures"""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up integration test fixtures"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_end_to_end_alert_flow(self):
        """Test complete end-to-end alert email flow"""
        # Create email channel
        config = EmailConfig(
            smtp_host="smtp.test.com",
            smtp_port=587,
            username="test@company.com",
            password="securepass123",
            from_email="alerts@company.com",
            critical_recipients=["admin@company.com"]
        )

        channel = EmailNotificationChannel(config, self.temp_dir)

        # Create test alert
        alert = Alert(
            id="integration-test-alert",
            rule_name="integration_test",
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.ACTIVE,
            title="Integration Test Alert",
            description="This is an integration test alert",
            metric_value=95.0,
            threshold=90.0,
            labels={"test": "integration"},
            started_at=datetime.now()
        )

        # Mock the SMTP sending
        with patch.object(channel, '_send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            # Send alert
            result = await channel.send_alert(alert)

            # Verify success
            assert result is True
            mock_send.assert_called_once()

            # Verify the message was properly constructed
            call_args = mock_send.call_args[0]
            message = call_args[0]

            assert isinstance(message, MIMEMultipart)
            assert "Integration Test Alert" in message["Subject"]
            assert message["To"] == "admin@company.com"
            assert message["From"] == "VoiceHive Hotels Alerts <alerts@company.com>"

    @pytest.mark.asyncio
    async def test_end_to_end_sla_violation_flow(self):
        """Test complete end-to-end SLA violation email flow"""
        # Create email channel
        config = EmailConfig(
            smtp_host="smtp.test.com",
            smtp_port=587,
            username="test@company.com",
            password="securepass123",
            from_email="alerts@company.com",
            sla_recipients=["sre@company.com"]
        )

        channel = EmailNotificationChannel(config, self.temp_dir)

        # Mock the SMTP sending
        with patch.object(channel, '_send_email', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            # Send SLA violation
            result = await channel.send_sla_violation(
                "Integration Test SLA",
                95.5,
                99.0,
                {"measurement_window": "1h", "test": "integration"}
            )

            # Verify success
            assert result is True
            mock_send.assert_called_once()

            # Verify the message was properly constructed
            call_args = mock_send.call_args[0]
            message = call_args[0]

            assert isinstance(message, MIMEMultipart)
            assert "SLA VIOLATION" in message["Subject"]
            assert "Integration Test SLA" in message["Subject"]
            assert message["To"] == "sre@company.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])