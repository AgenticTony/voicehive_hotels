"""
Error alerting system with severity-based routing
"""

import asyncio
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from enum import Enum
import httpx

from error_models import ErrorSeverity
from correlation_middleware import CorrelationIDLogger

logger = CorrelationIDLogger("alerting_system")


class AlertChannel(str, Enum):
    """Available alert channels"""
    LOGS = "logs"
    METRICS = "metrics"
    SLACK = "slack"
    PAGERDUTY = "pagerduty"
    EMAIL = "email"
    WEBHOOK = "webhook"


class AlertingConfig:
    """Configuration for alerting system"""
    
    def __init__(
        self,
        slack_webhook_url: Optional[str] = None,
        pagerduty_integration_key: Optional[str] = None,
        email_smtp_config: Optional[Dict[str, Any]] = None,
        webhook_urls: Optional[Dict[str, str]] = None,
        rate_limit_window: int = 300,  # 5 minutes
        max_alerts_per_window: int = 10
    ):
        self.slack_webhook_url = slack_webhook_url
        self.pagerduty_integration_key = pagerduty_integration_key
        self.email_smtp_config = email_smtp_config or {}
        self.webhook_urls = webhook_urls or {}
        self.rate_limit_window = rate_limit_window
        self.max_alerts_per_window = max_alerts_per_window


class AlertRateLimiter:
    """Rate limiter for alerts to prevent spam"""
    
    def __init__(self, window_seconds: int = 300, max_alerts: int = 10):
        self.window_seconds = window_seconds
        self.max_alerts = max_alerts
        self.alert_history: Dict[str, List[datetime]] = {}
    
    def should_send_alert(self, alert_key: str) -> bool:
        """
        Check if alert should be sent based on rate limiting
        
        Args:
            alert_key: Unique key for the alert type
        
        Returns:
            True if alert should be sent, False if rate limited
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self.window_seconds)
        
        # Clean old entries
        if alert_key in self.alert_history:
            self.alert_history[alert_key] = [
                timestamp for timestamp in self.alert_history[alert_key]
                if timestamp > cutoff
            ]
        else:
            self.alert_history[alert_key] = []
        
        # Check if under limit
        if len(self.alert_history[alert_key]) < self.max_alerts:
            self.alert_history[alert_key].append(now)
            return True
        
        return False


class SlackAlerter:
    """Slack alerting implementation"""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.http_client = httpx.AsyncClient(timeout=10.0)
    
    async def send_alert(
        self,
        title: str,
        message: str,
        severity: ErrorSeverity,
        context: Dict[str, Any]
    ) -> bool:
        """Send alert to Slack"""
        try:
            # Determine color based on severity
            color_map = {
                ErrorSeverity.LOW: "#36a64f",      # Green
                ErrorSeverity.MEDIUM: "#ff9500",   # Orange
                ErrorSeverity.HIGH: "#ff0000",     # Red
                ErrorSeverity.CRITICAL: "#8B0000"  # Dark Red
            }
            
            color = color_map.get(severity, "#ff0000")
            
            # Build Slack message
            slack_message = {
                "text": f"🚨 {title}",
                "attachments": [
                    {
                        "color": color,
                        "title": title,
                        "text": message,
                        "fields": [
                            {
                                "title": "Severity",
                                "value": severity.value.upper(),
                                "short": True
                            },
                            {
                                "title": "Service",
                                "value": context.get("service", "unknown"),
                                "short": True
                            },
                            {
                                "title": "Correlation ID",
                                "value": context.get("correlation_id", "N/A"),
                                "short": True
                            },
                            {
                                "title": "Path",
                                "value": f"{context.get('method', 'N/A')} {context.get('path', 'N/A')}",
                                "short": True
                            }
                        ],
                        "footer": "VoiceHive Hotels",
                        "ts": int(datetime.now(timezone.utc).timestamp())
                    }
                ]
            }
            
            # Add additional context if available
            if context.get("details"):
                slack_message["attachments"][0]["fields"].append({
                    "title": "Details",
                    "value": json.dumps(context["details"], indent=2)[:500],
                    "short": False
                })
            
            response = await self.http_client.post(
                self.webhook_url,
                json=slack_message
            )
            
            if response.status_code == 200:
                logger.info("slack_alert_sent", title=title, severity=severity)
                return True
            else:
                logger.error(
                    "slack_alert_failed",
                    title=title,
                    status_code=response.status_code,
                    response=response.text
                )
                return False
                
        except Exception as e:
            logger.error("slack_alert_error", title=title, error=str(e))
            return False
    
    async def close(self):
        """Close HTTP client"""
        await self.http_client.aclose()


class PagerDutyAlerter:
    """PagerDuty alerting implementation"""
    
    def __init__(self, integration_key: str):
        self.integration_key = integration_key
        self.http_client = httpx.AsyncClient(timeout=10.0)
        self.api_url = "https://events.pagerduty.com/v2/enqueue"
    
    async def send_alert(
        self,
        title: str,
        message: str,
        severity: ErrorSeverity,
        context: Dict[str, Any]
    ) -> bool:
        """Send alert to PagerDuty"""
        try:
            # Only send critical and high severity alerts to PagerDuty
            if severity not in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]:
                return True
            
            # Build PagerDuty event
            event = {
                "routing_key": self.integration_key,
                "event_action": "trigger",
                "dedup_key": f"voicehive-{context.get('error_code', 'unknown')}-{context.get('correlation_id', '')}",
                "payload": {
                    "summary": title,
                    "source": "voicehive-orchestrator",
                    "severity": "critical" if severity == ErrorSeverity.CRITICAL else "error",
                    "component": context.get("service", "orchestrator"),
                    "group": "voicehive-hotels",
                    "class": context.get("error_category", "system"),
                    "custom_details": {
                        "message": message,
                        "correlation_id": context.get("correlation_id"),
                        "path": context.get("path"),
                        "method": context.get("method"),
                        "details": context.get("details", {})
                    }
                }
            }
            
            response = await self.http_client.post(
                self.api_url,
                json=event
            )
            
            if response.status_code == 202:
                logger.info("pagerduty_alert_sent", title=title, severity=severity)
                return True
            else:
                logger.error(
                    "pagerduty_alert_failed",
                    title=title,
                    status_code=response.status_code,
                    response=response.text
                )
                return False
                
        except Exception as e:
            logger.error("pagerduty_alert_error", title=title, error=str(e))
            return False
    
    async def close(self):
        """Close HTTP client"""
        await self.http_client.aclose()


class WebhookAlerter:
    """Generic webhook alerting implementation"""
    
    def __init__(self, webhook_urls: Dict[str, str]):
        self.webhook_urls = webhook_urls
        self.http_client = httpx.AsyncClient(timeout=10.0)
    
    async def send_alert(
        self,
        title: str,
        message: str,
        severity: ErrorSeverity,
        context: Dict[str, Any]
    ) -> bool:
        """Send alert to configured webhooks"""
        success = True
        
        for name, url in self.webhook_urls.items():
            try:
                payload = {
                    "title": title,
                    "message": message,
                    "severity": severity.value,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "service": "voicehive-orchestrator",
                    "context": context
                }
                
                response = await self.http_client.post(url, json=payload)
                
                if response.status_code in [200, 201, 202]:
                    logger.info("webhook_alert_sent", webhook=name, title=title)
                else:
                    logger.error(
                        "webhook_alert_failed",
                        webhook=name,
                        title=title,
                        status_code=response.status_code
                    )
                    success = False
                    
            except Exception as e:
                logger.error("webhook_alert_error", webhook=name, title=title, error=str(e))
                success = False
        
        return success
    
    async def close(self):
        """Close HTTP client"""
        await self.http_client.aclose()


class AlertingSystem:
    """
    Main alerting system that coordinates different alert channels
    """
    
    def __init__(self, config: AlertingConfig):
        self.config = config
        self.rate_limiter = AlertRateLimiter(
            window_seconds=config.rate_limit_window,
            max_alerts=config.max_alerts_per_window
        )
        
        # Initialize alerters
        self.alerters = {}
        
        if config.slack_webhook_url:
            self.alerters[AlertChannel.SLACK] = SlackAlerter(config.slack_webhook_url)
        
        if config.pagerduty_integration_key:
            self.alerters[AlertChannel.PAGERDUTY] = PagerDutyAlerter(config.pagerduty_integration_key)
        
        if config.webhook_urls:
            self.alerters[AlertChannel.WEBHOOK] = WebhookAlerter(config.webhook_urls)
    
    async def send_alert(
        self,
        title: str,
        message: str,
        severity: ErrorSeverity,
        context: Dict[str, Any],
        channels: List[str]
    ) -> bool:
        """
        Send alert through specified channels
        
        Args:
            title: Alert title
            message: Alert message
            severity: Alert severity
            context: Additional context
            channels: List of channels to send to
        
        Returns:
            True if at least one alert was sent successfully
        """
        # Create rate limiting key
        alert_key = f"{context.get('error_code', 'unknown')}:{severity.value}"
        
        # Check rate limiting
        if not self.rate_limiter.should_send_alert(alert_key):
            logger.warning(
                "alert_rate_limited",
                title=title,
                severity=severity,
                alert_key=alert_key
            )
            return False
        
        success = False
        
        # Send to each requested channel
        for channel in channels:
            try:
                if channel == AlertChannel.LOGS:
                    # Always log the alert
                    logger.error(
                        "alert_generated",
                        title=title,
                        message=message,
                        severity=severity,
                        **context
                    )
                    success = True
                
                elif channel == AlertChannel.METRICS:
                    # Update metrics (implement based on your metrics system)
                    await self._update_metrics(title, severity, context)
                    success = True
                
                elif channel in self.alerters:
                    alerter = self.alerters[channel]
                    result = await alerter.send_alert(title, message, severity, context)
                    if result:
                        success = True
                
            except Exception as e:
                logger.error(
                    "alert_channel_error",
                    channel=channel,
                    title=title,
                    error=str(e)
                )
        
        return success
    
    async def _update_metrics(self, title: str, severity: ErrorSeverity, context: Dict[str, Any]):
        """Update metrics for the alert"""
        # This would integrate with your metrics system (Prometheus, etc.)
        # For now, just log the metric
        logger.info(
            "alert_metric",
            metric_name="voicehive_alerts_total",
            severity=severity.value,
            error_code=context.get("error_code"),
            service=context.get("service")
        )
    
    async def close(self):
        """Close all alerters"""
        for alerter in self.alerters.values():
            if hasattr(alerter, 'close'):
                await alerter.close()


# Factory function to create alerting system from environment
def create_alerting_system_from_env() -> Optional[AlertingSystem]:
    """Create alerting system from environment variables"""
    import os
    
    config = AlertingConfig(
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
        pagerduty_integration_key=os.getenv("PAGERDUTY_INTEGRATION_KEY"),
        webhook_urls={
            "monitoring": os.getenv("MONITORING_WEBHOOK_URL")
        } if os.getenv("MONITORING_WEBHOOK_URL") else {}
    )
    
    # Only create if at least one alerter is configured
    if any([config.slack_webhook_url, config.pagerduty_integration_key, config.webhook_urls]):
        return AlertingSystem(config)
    
    return None