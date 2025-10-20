"""
Email Alerting Service for VoiceHive Hotels
Provides email notifications for alerts and SLA violations using aiosmtplib
"""

import asyncio
import ssl
import aiosmtplib
from datetime import datetime
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import jinja2
import os
from pathlib import Path

from ..enhanced_alerting import NotificationChannel, Alert, AlertSeverity
from ..logging_adapter import get_safe_logger

logger = get_safe_logger("email_service")


@dataclass
class EmailConfig:
    """Email configuration settings"""
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    from_email: str
    from_name: str = "VoiceHive Hotels Alerts"
    use_tls: bool = True
    start_tls: bool = True
    timeout: float = 30.0

    # Recipient lists for different alert types
    critical_recipients: List[str] = None
    high_recipients: List[str] = None
    medium_recipients: List[str] = None
    low_recipients: List[str] = None
    info_recipients: List[str] = None
    sla_recipients: List[str] = None

    def __post_init__(self):
        """Initialize default recipient lists if not provided"""
        if self.critical_recipients is None:
            self.critical_recipients = []
        if self.high_recipients is None:
            self.high_recipients = []
        if self.medium_recipients is None:
            self.medium_recipients = []
        if self.low_recipients is None:
            self.low_recipients = []
        if self.info_recipients is None:
            self.info_recipients = []
        if self.sla_recipients is None:
            self.sla_recipients = []


class EmailTemplate:
    """Email template manager using Jinja2"""

    def __init__(self, template_dir: str):
        self.template_dir = Path(template_dir)
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self.template_dir)),
            autoescape=jinja2.select_autoescape(['html', 'xml'])
        )

    def render_alert_email(self, alert: Alert, template_type: str = 'alert') -> tuple[str, str]:
        """
        Render alert email templates

        Args:
            alert: Alert object to render
            template_type: Template type ('alert' or 'resolution')

        Returns:
            Tuple of (html_content, text_content)
        """
        try:
            # Prepare template context
            context = {
                'alert': alert,
                'severity_emoji': self._get_severity_emoji(alert.severity),
                'severity_color': self._get_severity_color(alert.severity),
                'formatted_started_at': alert.started_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                'formatted_resolved_at': alert.resolved_at.strftime("%Y-%m-%d %H:%M:%S UTC") if alert.resolved_at else None,
                'duration': self._format_duration(alert) if alert.resolved_at else None,
                'company_name': 'VoiceHive Hotels',
                'dashboard_url': 'https://voicehive-hotels.eu/monitoring',
                'runbook_available': bool(alert.runbook_url)
            }

            # Render HTML template
            html_template = self.env.get_template(f'{template_type}_email.html')
            html_content = html_template.render(**context)

            # Render text template
            text_template = self.env.get_template(f'{template_type}_email.txt')
            text_content = text_template.render(**context)

            return html_content, text_content

        except jinja2.TemplateNotFound as e:
            logger.error("email_template_not_found", template=str(e))
            # Fallback to simple templates
            return self._generate_fallback_alert_email(alert, template_type)
        except Exception as e:
            logger.error("email_template_render_error", error=str(e))
            return self._generate_fallback_alert_email(alert, template_type)

    def render_sla_violation_email(self, sla_name: str, current_value: float,
                                  target_value: float, details: Dict[str, Any]) -> tuple[str, str]:
        """
        Render SLA violation email templates

        Returns:
            Tuple of (html_content, text_content)
        """
        try:
            context = {
                'sla_name': sla_name,
                'current_value': current_value,
                'target_value': target_value,
                'violation_percentage': target_value - current_value,
                'details': details,
                'formatted_time': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                'company_name': 'VoiceHive Hotels',
                'dashboard_url': 'https://voicehive-hotels.eu/monitoring/sla'
            }

            html_template = self.env.get_template('sla_violation_email.html')
            html_content = html_template.render(**context)

            text_template = self.env.get_template('sla_violation_email.txt')
            text_content = text_template.render(**context)

            return html_content, text_content

        except jinja2.TemplateNotFound as e:
            logger.error("sla_email_template_not_found", template=str(e))
            return self._generate_fallback_sla_email(sla_name, current_value, target_value, details)
        except Exception as e:
            logger.error("sla_email_template_render_error", error=str(e))
            return self._generate_fallback_sla_email(sla_name, current_value, target_value, details)

    def _get_severity_emoji(self, severity: AlertSeverity) -> str:
        """Get emoji for alert severity"""
        emoji_map = {
            AlertSeverity.CRITICAL: "🚨",
            AlertSeverity.HIGH: "⚠️",
            AlertSeverity.MEDIUM: "⚡",
            AlertSeverity.LOW: "ℹ️",
            AlertSeverity.INFO: "📊"
        }
        return emoji_map.get(severity, "⚠️")

    def _get_severity_color(self, severity: AlertSeverity) -> str:
        """Get color for alert severity"""
        color_map = {
            AlertSeverity.CRITICAL: "#FF0000",
            AlertSeverity.HIGH: "#FF8C00",
            AlertSeverity.MEDIUM: "#FFD700",
            AlertSeverity.LOW: "#32CD32",
            AlertSeverity.INFO: "#87CEEB"
        }
        return color_map.get(severity, "#FF8C00")

    def _format_duration(self, alert: Alert) -> str:
        """Format alert duration"""
        if not alert.resolved_at:
            return "Ongoing"

        duration = alert.resolved_at - alert.started_at
        total_seconds = int(duration.total_seconds())

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def _generate_fallback_alert_email(self, alert: Alert, template_type: str) -> tuple[str, str]:
        """Generate simple fallback email templates"""
        emoji = self._get_severity_emoji(alert.severity)

        if template_type == 'resolution':
            subject_prefix = "RESOLVED"
            status_text = "has been resolved"
        else:
            subject_prefix = "ALERT"
            status_text = "is active"

        # Simple HTML template
        html_content = f"""
        <html>
        <head><title>{subject_prefix}: {alert.title}</title></head>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
            <h2 style="color: {self._get_severity_color(alert.severity)};">
                {emoji} {subject_prefix}: {alert.title}
            </h2>
            <p><strong>Status:</strong> Alert {status_text}</p>
            <p><strong>Severity:</strong> {alert.severity.value.upper()}</p>
            <p><strong>Description:</strong> {alert.description}</p>
            <p><strong>Metric Value:</strong> {alert.metric_value:.2f}</p>
            <p><strong>Threshold:</strong> {alert.threshold:.2f}</p>
            <p><strong>Started At:</strong> {alert.started_at.strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
            {f'<p><strong>Resolved At:</strong> {alert.resolved_at.strftime("%Y-%m-%d %H:%M:%S UTC")}</p>' if alert.resolved_at else ''}
            <p><strong>Alert ID:</strong> {alert.id}</p>
            {f'<p><strong>Runbook:</strong> <a href="{alert.runbook_url}">View Runbook</a></p>' if alert.runbook_url else ''}
            <hr>
            <p style="font-size: 12px; color: #666;">
                VoiceHive Hotels Monitoring System
            </p>
        </body>
        </html>
        """

        # Simple text template
        text_content = f"""
{subject_prefix}: {alert.title}

Status: Alert {status_text}
Severity: {alert.severity.value.upper()}
Description: {alert.description}
Metric Value: {alert.metric_value:.2f}
Threshold: {alert.threshold:.2f}
Started At: {alert.started_at.strftime("%Y-%m-%d %H:%M:%S UTC")}
{f'Resolved At: {alert.resolved_at.strftime("%Y-%m-%d %H:%M:%S UTC")}' if alert.resolved_at else ''}
Alert ID: {alert.id}
{f'Runbook: {alert.runbook_url}' if alert.runbook_url else ''}

--
VoiceHive Hotels Monitoring System
        """

        return html_content.strip(), text_content.strip()

    def _generate_fallback_sla_email(self, sla_name: str, current_value: float,
                                   target_value: float, details: Dict[str, Any]) -> tuple[str, str]:
        """Generate simple fallback SLA violation email"""
        html_content = f"""
        <html>
        <head><title>SLA Violation: {sla_name}</title></head>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
            <h2 style="color: #FF0000;">🚨 SLA Violation: {sla_name}</h2>
            <p><strong>Current Value:</strong> {current_value:.2f}%</p>
            <p><strong>Target Value:</strong> {target_value:.2f}%</p>
            <p><strong>Violation:</strong> {target_value - current_value:.2f}% below target</p>
            <p><strong>Time:</strong> {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
            {f'<p><strong>Details:</strong><br>{"<br>".join([f"{k}: {v}" for k, v in details.items()])}</p>' if details else ''}
            <hr>
            <p style="font-size: 12px; color: #666;">
                VoiceHive Hotels SLA Monitoring
            </p>
        </body>
        </html>
        """

        text_content = f"""
SLA VIOLATION: {sla_name}

Current Value: {current_value:.2f}%
Target Value: {target_value:.2f}%
Violation: {target_value - current_value:.2f}% below target
Time: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}

{chr(10).join([f"{k}: {v}" for k, v in details.items()]) if details else ''}

--
VoiceHive Hotels SLA Monitoring
        """

        return html_content.strip(), text_content.strip()


class EmailNotificationChannel(NotificationChannel):
    """Email notification channel using aiosmtplib"""

    def __init__(self, config: EmailConfig, template_dir: Optional[str] = None):
        self.config = config
        self.template_dir = template_dir or str(Path(__file__).parent / "email_templates")
        self.template_manager = EmailTemplate(self.template_dir)
        self._health_status = "unknown"
        self._last_health_check = None

    async def send_alert(self, alert: Alert) -> bool:
        """Send alert notification via email"""
        try:
            recipients = self._get_recipients_for_severity(alert.severity)
            if not recipients:
                logger.warning("no_email_recipients_configured", severity=alert.severity.value)
                return True  # Don't fail if no recipients configured

            # Determine email type
            template_type = 'resolution' if alert.status.value == 'resolved' else 'alert'

            # Render email content
            html_content, text_content = self.template_manager.render_alert_email(alert, template_type)

            # Create email message
            message = self._create_multipart_message(
                subject=f"[{alert.severity.value.upper()}] {alert.title}",
                html_content=html_content,
                text_content=text_content,
                recipients=recipients
            )

            # Send email
            success = await self._send_email(message)

            if success:
                logger.info("email_alert_sent",
                          alert_id=alert.id,
                          severity=alert.severity.value,
                          recipients_count=len(recipients))
            else:
                logger.error("email_alert_failed", alert_id=alert.id)

            return success

        except Exception as e:
            logger.error("email_alert_error", alert_id=alert.id, error=str(e))
            return False

    async def send_sla_violation(self, sla_name: str, current_value: float,
                               target_value: float, details: Dict[str, Any]) -> bool:
        """Send SLA violation notification via email"""
        try:
            recipients = self.config.sla_recipients
            if not recipients:
                logger.warning("no_sla_email_recipients_configured")
                return True  # Don't fail if no recipients configured

            # Render email content
            html_content, text_content = self.template_manager.render_sla_violation_email(
                sla_name, current_value, target_value, details
            )

            # Create email message
            message = self._create_multipart_message(
                subject=f"[SLA VIOLATION] {sla_name} - {current_value:.2f}% (Target: {target_value:.2f}%)",
                html_content=html_content,
                text_content=text_content,
                recipients=recipients
            )

            # Send email
            success = await self._send_email(message)

            if success:
                logger.info("email_sla_violation_sent",
                          sla_name=sla_name,
                          recipients_count=len(recipients))
            else:
                logger.error("email_sla_violation_failed", sla_name=sla_name)

            return success

        except Exception as e:
            logger.error("email_sla_violation_error", sla_name=sla_name, error=str(e))
            return False

    def _get_recipients_for_severity(self, severity: AlertSeverity) -> List[str]:
        """Get email recipients based on alert severity"""
        severity_map = {
            AlertSeverity.CRITICAL: self.config.critical_recipients,
            AlertSeverity.HIGH: self.config.high_recipients,
            AlertSeverity.MEDIUM: self.config.medium_recipients,
            AlertSeverity.LOW: self.config.low_recipients,
            AlertSeverity.INFO: self.config.info_recipients
        }
        return severity_map.get(severity, [])

    def _create_multipart_message(self, subject: str, html_content: str,
                                text_content: str, recipients: List[str]) -> MIMEMultipart:
        """Create a multipart email message with HTML and text alternatives"""
        message = MIMEMultipart("alternative")
        message["From"] = f"{self.config.from_name} <{self.config.from_email}>"
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message["X-Priority"] = "1"  # High priority
        message["X-MSMail-Priority"] = "High"

        # Add text and HTML parts
        text_part = MIMEText(text_content, "plain", "utf-8")
        html_part = MIMEText(html_content, "html", "utf-8")

        # Attach parts (order matters - text first, then HTML)
        message.attach(text_part)
        message.attach(html_part)

        return message

    async def _send_email(self, message: MIMEMultipart) -> bool:
        """Send email using aiosmtplib"""
        try:
            # Create SMTP client
            smtp_client = aiosmtplib.SMTP(
                hostname=self.config.smtp_host,
                port=self.config.smtp_port,
                use_tls=self.config.use_tls,
                start_tls=self.config.start_tls,
                timeout=self.config.timeout
            )

            # Use async context manager for proper connection handling
            async with smtp_client:
                # Authenticate if credentials provided
                if self.config.username and self.config.password:
                    await smtp_client.login(self.config.username, self.config.password)

                # Send message
                await smtp_client.send_message(message)

                logger.debug("email_sent_successfully",
                           smtp_host=self.config.smtp_host,
                           recipients=message["To"])
                return True

        except aiosmtplib.SMTPException as e:
            logger.error("smtp_error", error=str(e), smtp_host=self.config.smtp_host)
            return False
        except Exception as e:
            logger.error("email_send_error", error=str(e))
            return False

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check for SMTP service connectivity

        Returns:
            Dict containing health status and details
        """
        try:
            start_time = datetime.utcnow()

            # Test SMTP connection
            smtp_client = aiosmtplib.SMTP(
                hostname=self.config.smtp_host,
                port=self.config.smtp_port,
                use_tls=self.config.use_tls,
                start_tls=self.config.start_tls,
                timeout=10.0  # Shorter timeout for health checks
            )

            async with smtp_client:
                # Test authentication if credentials provided
                if self.config.username and self.config.password:
                    await smtp_client.login(self.config.username, self.config.password)

                response_time_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

                self._health_status = "healthy"
                self._last_health_check = datetime.utcnow()

                health_data = {
                    "status": "healthy",
                    "service": "smtp",
                    "smtp_host": self.config.smtp_host,
                    "smtp_port": self.config.smtp_port,
                    "connection_successful": True,
                    "authentication_successful": bool(self.config.username),
                    "response_time_ms": response_time_ms,
                    "last_check": self._last_health_check.isoformat(),
                    "use_tls": self.config.use_tls,
                    "start_tls": self.config.start_tls
                }

                logger.info("smtp_health_check_passed",
                          smtp_host=self.config.smtp_host,
                          response_time_ms=response_time_ms)
                return health_data

        except aiosmtplib.SMTPAuthenticationError as e:
            self._health_status = "auth_failed"
            health_data = {
                "status": "auth_failed",
                "service": "smtp",
                "smtp_host": self.config.smtp_host,
                "error": f"Authentication failed: {str(e)}",
                "last_check": datetime.utcnow().isoformat()
            }
            logger.error("smtp_health_check_auth_failed", error=str(e))
            return health_data

        except aiosmtplib.SMTPException as e:
            self._health_status = "smtp_error"
            health_data = {
                "status": "smtp_error",
                "service": "smtp",
                "smtp_host": self.config.smtp_host,
                "error": f"SMTP error: {str(e)}",
                "last_check": datetime.utcnow().isoformat()
            }
            logger.error("smtp_health_check_smtp_error", error=str(e))
            return health_data

        except Exception as e:
            self._health_status = "error"
            health_data = {
                "status": "error",
                "service": "smtp",
                "smtp_host": self.config.smtp_host,
                "error": f"Unexpected error: {str(e)}",
                "last_check": datetime.utcnow().isoformat()
            }
            logger.error("smtp_health_check_error", error=str(e))
            return health_data

    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status without performing a new check"""
        return {
            "status": self._health_status,
            "service": "smtp",
            "smtp_host": self.config.smtp_host,
            "last_check": self._last_health_check.isoformat() if self._last_health_check else None
        }


# Factory function for easy configuration
def create_email_notification_channel(
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    from_email: str,
    from_name: str = "VoiceHive Hotels Alerts",
    critical_recipients: List[str] = None,
    high_recipients: List[str] = None,
    medium_recipients: List[str] = None,
    low_recipients: List[str] = None,
    info_recipients: List[str] = None,
    sla_recipients: List[str] = None,
    use_tls: bool = True,
    start_tls: bool = True,
    template_dir: Optional[str] = None
) -> EmailNotificationChannel:
    """
    Factory function to create an EmailNotificationChannel with configuration

    Args:
        smtp_host: SMTP server hostname
        smtp_port: SMTP server port (587 for STARTTLS, 465 for TLS, 25 for plain)
        username: SMTP username for authentication
        password: SMTP password for authentication
        from_email: Sender email address
        from_name: Sender display name
        critical_recipients: List of email addresses for critical alerts
        high_recipients: List of email addresses for high priority alerts
        medium_recipients: List of email addresses for medium priority alerts
        low_recipients: List of email addresses for low priority alerts
        info_recipients: List of email addresses for info alerts
        sla_recipients: List of email addresses for SLA violations
        use_tls: Use direct TLS connection (port 465)
        start_tls: Upgrade to TLS using STARTTLS (port 587)
        template_dir: Directory containing email templates

    Returns:
        Configured EmailNotificationChannel instance
    """
    config = EmailConfig(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=username,
        password=password,
        from_email=from_email,
        from_name=from_name,
        critical_recipients=critical_recipients or [],
        high_recipients=high_recipients or [],
        medium_recipients=medium_recipients or [],
        low_recipients=low_recipients or [],
        info_recipients=info_recipients or [],
        sla_recipients=sla_recipients or [],
        use_tls=use_tls,
        start_tls=start_tls
    )

    return EmailNotificationChannel(config, template_dir)