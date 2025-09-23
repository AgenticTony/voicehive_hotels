"""
Enhanced Alerting System for VoiceHive Hotels
Comprehensive alerting with actionable notifications and SLA monitoring
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import aiohttp
from logging_adapter import get_safe_logger

logger = get_safe_logger("enhanced_alerting")


class AlertSeverity(Enum):
    """Alert severity levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(Enum):
    """Alert status"""
    ACTIVE = "active"
    RESOLVED = "resolved"
    ACKNOWLEDGED = "acknowledged"
    SUPPRESSED = "suppressed"


@dataclass
class AlertRule:
    """Alert rule definition"""
    name: str
    description: str
    severity: AlertSeverity
    metric_name: str
    threshold: float
    comparison: str  # "gt", "lt", "eq", "gte", "lte"
    duration: int  # seconds
    labels: Dict[str, str]
    runbook_url: Optional[str] = None
    escalation_policy: Optional[str] = None
    suppression_rules: Optional[List[str]] = None


@dataclass
class Alert:
    """Alert instance"""
    id: str
    rule_name: str
    severity: AlertSeverity
    status: AlertStatus
    title: str
    description: str
    metric_value: float
    threshold: float
    labels: Dict[str, str]
    started_at: datetime
    resolved_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    runbook_url: Optional[str] = None
    escalation_policy: Optional[str] = None


@dataclass
class SLATarget:
    """SLA target definition"""
    name: str
    description: str
    target_percentage: float
    measurement_window: int  # seconds
    metric_query: str
    labels: Dict[str, str]
    alert_threshold: float  # percentage below target to alert


class NotificationChannel:
    """Base notification channel"""
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert notification"""
        raise NotImplementedError
    
    async def send_sla_violation(self, sla_name: str, current_value: float, 
                               target_value: float, details: Dict[str, Any]) -> bool:
        """Send SLA violation notification"""
        raise NotImplementedError


class SlackNotificationChannel(NotificationChannel):
    """Slack notification channel"""
    
    def __init__(self, webhook_url: str, channel: str = "#alerts"):
        self.webhook_url = webhook_url
        self.channel = channel
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert to Slack"""
        try:
            color_map = {
                AlertSeverity.CRITICAL: "#FF0000",
                AlertSeverity.HIGH: "#FF8C00",
                AlertSeverity.MEDIUM: "#FFD700",
                AlertSeverity.LOW: "#32CD32",
                AlertSeverity.INFO: "#87CEEB"
            }
            
            emoji_map = {
                AlertSeverity.CRITICAL: "🚨",
                AlertSeverity.HIGH: "⚠️",
                AlertSeverity.MEDIUM: "⚡",
                AlertSeverity.LOW: "ℹ️",
                AlertSeverity.INFO: "📊"
            }
            
            fields = [
                {
                    "title": "Metric Value",
                    "value": f"{alert.metric_value:.2f}",
                    "short": True
                },
                {
                    "title": "Threshold",
                    "value": f"{alert.threshold:.2f}",
                    "short": True
                },
                {
                    "title": "Started At",
                    "value": alert.started_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "short": True
                }
            ]
            
            if alert.runbook_url:
                fields.append({
                    "title": "Runbook",
                    "value": f"<{alert.runbook_url}|View Runbook>",
                    "short": True
                })
            
            # Add label information
            if alert.labels:
                label_text = ", ".join([f"{k}={v}" for k, v in alert.labels.items()])
                fields.append({
                    "title": "Labels",
                    "value": label_text,
                    "short": False
                })
            
            # Following Slack webhook best practices with proper formatting
            payload = {
                "channel": self.channel,
                "username": "VoiceHive Alerts",
                "icon_emoji": ":warning:",
                "text": f"{emoji_map[alert.severity]} {alert.title}",  # Fallback text
                "attachments": [
                    {
                        "color": color_map[alert.severity],
                        "title": f"{emoji_map[alert.severity]} {alert.title}",
                        "text": alert.description,
                        "fields": fields,
                        "footer": f"Alert ID: {alert.id}",
                        "ts": int(alert.started_at.timestamp()),
                        "mrkdwn_in": ["text", "fields"]  # Enable markdown formatting
                    }
                ]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status == 200:
                        logger.info("slack_alert_sent", alert_id=alert.id)
                        return True
                    else:
                        logger.error("slack_alert_failed", 
                                   alert_id=alert.id, 
                                   status=response.status)
                        return False
        
        except Exception as e:
            logger.error("slack_notification_error", alert_id=alert.id, error=str(e))
            return False
    
    async def send_sla_violation(self, sla_name: str, current_value: float,
                               target_value: float, details: Dict[str, Any]) -> bool:
        """Send SLA violation to Slack"""
        try:
            payload = {
                "channel": self.channel,
                "username": "VoiceHive SLA Monitor",
                "icon_emoji": ":chart_with_downwards_trend:",
                "attachments": [
                    {
                        "color": "#FF0000",
                        "title": f"🚨 SLA Violation: {sla_name}",
                        "text": f"SLA target not met. Current: {current_value:.2f}%, Target: {target_value:.2f}%",
                        "fields": [
                            {
                                "title": "Current Value",
                                "value": f"{current_value:.2f}%",
                                "short": True
                            },
                            {
                                "title": "Target Value",
                                "value": f"{target_value:.2f}%",
                                "short": True
                            },
                            {
                                "title": "Violation Time",
                                "value": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                                "short": True
                            }
                        ],
                        "footer": f"SLA: {sla_name}"
                    }
                ]
            }
            
            # Add details if provided
            if details:
                detail_text = "\n".join([f"• {k}: {v}" for k, v in details.items()])
                payload["attachments"][0]["fields"].append({
                    "title": "Additional Details",
                    "value": detail_text,
                    "short": False
                })
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status == 200:
                        logger.info("slack_sla_violation_sent", sla_name=sla_name)
                        return True
                    else:
                        logger.error("slack_sla_violation_failed",
                                   sla_name=sla_name,
                                   status=response.status)
                        return False
        
        except Exception as e:
            logger.error("slack_sla_notification_error", sla_name=sla_name, error=str(e))
            return False


class PagerDutyNotificationChannel(NotificationChannel):
    """PagerDuty notification channel"""
    
    def __init__(self, integration_key: str):
        self.integration_key = integration_key
        self.api_url = "https://events.pagerduty.com/v2/enqueue"
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert to PagerDuty"""
        try:
            # Only send critical and high severity alerts to PagerDuty
            if alert.severity not in [AlertSeverity.CRITICAL, AlertSeverity.HIGH]:
                return True
            
            payload = {
                "routing_key": self.integration_key,
                "event_action": "trigger",
                "dedup_key": alert.id,
                "payload": {
                    "summary": alert.title,
                    "source": "voicehive-hotels",
                    "severity": alert.severity.value,
                    "component": "orchestrator",
                    "group": "voicehive",
                    "class": "alert",
                    "custom_details": {
                        "description": alert.description,
                        "metric_value": alert.metric_value,
                        "threshold": alert.threshold,
                        "labels": alert.labels,
                        "runbook_url": alert.runbook_url
                    }
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload) as response:
                    if response.status == 202:
                        logger.info("pagerduty_alert_sent", alert_id=alert.id)
                        return True
                    else:
                        logger.error("pagerduty_alert_failed",
                                   alert_id=alert.id,
                                   status=response.status)
                        return False
        
        except Exception as e:
            logger.error("pagerduty_notification_error", alert_id=alert.id, error=str(e))
            return False
    
    async def send_sla_violation(self, sla_name: str, current_value: float,
                               target_value: float, details: Dict[str, Any]) -> bool:
        """Send SLA violation to PagerDuty"""
        try:
            payload = {
                "routing_key": self.integration_key,
                "event_action": "trigger",
                "dedup_key": f"sla-violation-{sla_name}",
                "payload": {
                    "summary": f"SLA Violation: {sla_name}",
                    "source": "voicehive-hotels",
                    "severity": "critical",
                    "component": "sla-monitor",
                    "group": "voicehive",
                    "class": "sla_violation",
                    "custom_details": {
                        "sla_name": sla_name,
                        "current_value": current_value,
                        "target_value": target_value,
                        "details": details
                    }
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload) as response:
                    if response.status == 202:
                        logger.info("pagerduty_sla_violation_sent", sla_name=sla_name)
                        return True
                    else:
                        logger.error("pagerduty_sla_violation_failed",
                                   sla_name=sla_name,
                                   status=response.status)
                        return False
        
        except Exception as e:
            logger.error("pagerduty_sla_notification_error", sla_name=sla_name, error=str(e))
            return False


class EnhancedAlertingSystem:
    """Enhanced alerting system with SLA monitoring"""
    
    def __init__(self):
        self.alert_rules: Dict[str, AlertRule] = {}
        self.active_alerts: Dict[str, Alert] = {}
        self.sla_targets: Dict[str, SLATarget] = {}
        self.notification_channels: List[NotificationChannel] = []
        self.metric_values: Dict[str, List[tuple]] = {}  # metric_name -> [(timestamp, value)]
        self.sla_violations: Dict[str, datetime] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    def add_notification_channel(self, channel: NotificationChannel):
        """Add a notification channel"""
        self.notification_channels.append(channel)
    
    def add_alert_rule(self, rule: AlertRule):
        """Add an alert rule"""
        self.alert_rules[rule.name] = rule
        logger.info("alert_rule_added", rule_name=rule.name, severity=rule.severity.value)
    
    def add_sla_target(self, target: SLATarget):
        """Add an SLA target"""
        self.sla_targets[target.name] = target
        logger.info("sla_target_added", sla_name=target.name, target=target.target_percentage)
    
    def record_metric_value(self, metric_name: str, value: float, labels: Dict[str, str] = None):
        """Record a metric value for alerting evaluation"""
        timestamp = time.time()
        
        if metric_name not in self.metric_values:
            self.metric_values[metric_name] = []
        
        self.metric_values[metric_name].append((timestamp, value, labels or {}))
        
        # Keep only last 1 hour of data
        cutoff = timestamp - 3600
        self.metric_values[metric_name] = [
            (ts, val, lbl) for ts, val, lbl in self.metric_values[metric_name]
            if ts > cutoff
        ]
    
    async def evaluate_alert_rules(self):
        """Evaluate all alert rules"""
        for rule_name, rule in self.alert_rules.items():
            try:
                await self._evaluate_single_rule(rule)
            except Exception as e:
                logger.error("alert_rule_evaluation_failed", 
                           rule_name=rule_name, error=str(e))
    
    async def _evaluate_single_rule(self, rule: AlertRule):
        """Evaluate a single alert rule"""
        if rule.metric_name not in self.metric_values:
            return
        
        current_time = time.time()
        cutoff_time = current_time - rule.duration
        
        # Get recent values for this metric
        recent_values = [
            (ts, val, lbl) for ts, val, lbl in self.metric_values[rule.metric_name]
            if ts > cutoff_time and self._labels_match(lbl, rule.labels)
        ]
        
        if not recent_values:
            return
        
        # Get the latest value
        latest_timestamp, latest_value, latest_labels = recent_values[-1]
        
        # Check if threshold is breached
        threshold_breached = self._check_threshold(latest_value, rule.threshold, rule.comparison)
        
        alert_id = f"{rule.name}-{hash(str(sorted(latest_labels.items())))}"
        
        if threshold_breached:
            if alert_id not in self.active_alerts:
                # Create new alert
                alert = Alert(
                    id=alert_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    status=AlertStatus.ACTIVE,
                    title=f"{rule.name} - Threshold Breached",
                    description=rule.description,
                    metric_value=latest_value,
                    threshold=rule.threshold,
                    labels=latest_labels,
                    started_at=datetime.fromtimestamp(latest_timestamp),
                    runbook_url=rule.runbook_url,
                    escalation_policy=rule.escalation_policy
                )
                
                self.active_alerts[alert_id] = alert
                await self._send_alert_notifications(alert)
                
                logger.warning("alert_triggered",
                             alert_id=alert_id,
                             rule_name=rule.name,
                             metric_value=latest_value,
                             threshold=rule.threshold)
        else:
            # Check if we should resolve an existing alert
            if alert_id in self.active_alerts:
                alert = self.active_alerts[alert_id]
                if alert.status == AlertStatus.ACTIVE:
                    alert.status = AlertStatus.RESOLVED
                    alert.resolved_at = datetime.fromtimestamp(current_time)
                    
                    await self._send_resolution_notifications(alert)
                    
                    logger.info("alert_resolved",
                              alert_id=alert_id,
                              rule_name=rule.name,
                              duration=(alert.resolved_at - alert.started_at).total_seconds())
    
    def _labels_match(self, metric_labels: Dict[str, str], rule_labels: Dict[str, str]) -> bool:
        """Check if metric labels match rule labels"""
        for key, value in rule_labels.items():
            if key not in metric_labels or metric_labels[key] != value:
                return False
        return True
    
    def _check_threshold(self, value: float, threshold: float, comparison: str) -> bool:
        """Check if value breaches threshold"""
        if comparison == "gt":
            return value > threshold
        elif comparison == "gte":
            return value >= threshold
        elif comparison == "lt":
            return value < threshold
        elif comparison == "lte":
            return value <= threshold
        elif comparison == "eq":
            return value == threshold
        else:
            return False
    
    async def _send_alert_notifications(self, alert: Alert):
        """Send alert notifications to all channels"""
        for channel in self.notification_channels:
            try:
                await channel.send_alert(alert)
            except Exception as e:
                logger.error("notification_send_failed",
                           alert_id=alert.id,
                           channel=type(channel).__name__,
                           error=str(e))
    
    async def _send_resolution_notifications(self, alert: Alert):
        """Send alert resolution notifications"""
        # For now, just log resolution. Could extend to send resolution notifications
        logger.info("alert_resolution_logged", alert_id=alert.id)
    
    async def evaluate_sla_targets(self):
        """Evaluate all SLA targets"""
        for sla_name, target in self.sla_targets.items():
            try:
                await self._evaluate_single_sla(target)
            except Exception as e:
                logger.error("sla_evaluation_failed", sla_name=sla_name, error=str(e))
    
    async def _evaluate_single_sla(self, target: SLATarget):
        """Evaluate a single SLA target"""
        # This is a simplified implementation
        # In a real system, you'd query your metrics backend (Prometheus, etc.)
        
        current_time = time.time()
        window_start = current_time - target.measurement_window
        
        # Calculate SLA based on available metrics
        # This is a placeholder - implement actual SLA calculation logic
        current_sla_value = await self._calculate_sla_value(target, window_start, current_time)
        
        if current_sla_value is not None:
            violation_threshold = target.target_percentage - target.alert_threshold
            
            if current_sla_value < violation_threshold:
                # SLA violation detected
                if target.name not in self.sla_violations:
                    self.sla_violations[target.name] = datetime.utcnow()
                    
                    details = {
                        "measurement_window": f"{target.measurement_window}s",
                        "violation_detected_at": datetime.utcnow().isoformat(),
                        "labels": str(target.labels)
                    }
                    
                    await self._send_sla_violation_notifications(
                        target.name, current_sla_value, target.target_percentage, details
                    )
                    
                    logger.critical("sla_violation_detected",
                                  sla_name=target.name,
                                  current_value=current_sla_value,
                                  target_value=target.target_percentage)
            else:
                # SLA is healthy, remove from violations if it was there
                if target.name in self.sla_violations:
                    violation_duration = datetime.utcnow() - self.sla_violations[target.name]
                    del self.sla_violations[target.name]
                    
                    logger.info("sla_violation_resolved",
                              sla_name=target.name,
                              violation_duration=violation_duration.total_seconds())
    
    async def _calculate_sla_value(self, target: SLATarget, window_start: float, window_end: float) -> Optional[float]:
        """Calculate SLA value for the given time window"""
        # Placeholder implementation
        # In a real system, this would query your metrics backend
        # For now, return a mock value based on available data
        
        # Example: Calculate success rate from call metrics
        if "call_success_rate" in target.metric_query:
            success_count = 0
            total_count = 0
            
            # This is simplified - you'd implement proper metric querying
            for metric_name, values in self.metric_values.items():
                if "call_success" in metric_name or "call_failure" in metric_name:
                    for timestamp, value, labels in values:
                        if window_start <= timestamp <= window_end:
                            if self._labels_match(labels, target.labels):
                                total_count += value
                                if "success" in metric_name:
                                    success_count += value
            
            if total_count > 0:
                return (success_count / total_count) * 100
        
        return None
    
    async def _send_sla_violation_notifications(self, sla_name: str, current_value: float,
                                              target_value: float, details: Dict[str, Any]):
        """Send SLA violation notifications"""
        for channel in self.notification_channels:
            try:
                await channel.send_sla_violation(sla_name, current_value, target_value, details)
            except Exception as e:
                logger.error("sla_notification_send_failed",
                           sla_name=sla_name,
                           channel=type(channel).__name__,
                           error=str(e))
    
    async def start(self):
        """Start the alerting system"""
        if self._running:
            return
        
        self._running = True
        
        # Start evaluation tasks
        self._tasks.append(asyncio.create_task(self._alert_evaluation_loop()))
        self._tasks.append(asyncio.create_task(self._sla_evaluation_loop()))
        
        logger.info("enhanced_alerting_system_started")
    
    async def stop(self):
        """Stop the alerting system"""
        self._running = False
        
        for task in self._tasks:
            task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        
        logger.info("enhanced_alerting_system_stopped")
    
    async def _alert_evaluation_loop(self):
        """Main alert evaluation loop"""
        while self._running:
            try:
                await self.evaluate_alert_rules()
                await asyncio.sleep(30)  # Evaluate every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("alert_evaluation_loop_error", error=str(e))
                await asyncio.sleep(30)
    
    async def _sla_evaluation_loop(self):
        """Main SLA evaluation loop"""
        while self._running:
            try:
                await self.evaluate_sla_targets()
                await asyncio.sleep(60)  # Evaluate every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("sla_evaluation_loop_error", error=str(e))
                await asyncio.sleep(60)


# Global instance
enhanced_alerting = EnhancedAlertingSystem()


# Predefined alert rules for VoiceHive Hotels
def setup_default_alert_rules():
    """Setup default alert rules for VoiceHive Hotels"""
    
    # Call failure rate alerts
    enhanced_alerting.add_alert_rule(AlertRule(
        name="high_call_failure_rate",
        description="Call failure rate is above 5% for more than 2 minutes",
        severity=AlertSeverity.HIGH,
        metric_name="voicehive_call_failures_total",
        threshold=0.05,
        comparison="gt",
        duration=120,
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/call-failures"
    ))
    
    # PMS response time alerts
    enhanced_alerting.add_alert_rule(AlertRule(
        name="slow_pms_response",
        description="PMS response time is above 5 seconds",
        severity=AlertSeverity.MEDIUM,
        metric_name="voicehive_pms_response_seconds",
        threshold=5.0,
        comparison="gt",
        duration=60,
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/pms-performance"
    ))
    
    # Memory usage alerts
    enhanced_alerting.add_alert_rule(AlertRule(
        name="high_memory_usage",
        description="Memory usage is above 80%",
        severity=AlertSeverity.HIGH,
        metric_name="voicehive_memory_usage_percent",
        threshold=80.0,
        comparison="gt",
        duration=300,
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/memory-usage"
    ))


def setup_default_sla_targets():
    """Setup default SLA targets for VoiceHive Hotels"""
    
    # Call success rate SLA
    enhanced_alerting.add_sla_target(SLATarget(
        name="call_success_rate_sla",
        description="Call success rate should be above 99%",
        target_percentage=99.0,
        measurement_window=3600,  # 1 hour
        metric_query="call_success_rate",
        labels={},
        alert_threshold=1.0  # Alert if below 98%
    ))
    
    # PMS availability SLA
    enhanced_alerting.add_sla_target(SLATarget(
        name="pms_availability_sla",
        description="PMS systems should be available 99.5% of the time",
        target_percentage=99.5,
        measurement_window=3600,
        metric_query="pms_availability",
        labels={},
        alert_threshold=0.5  # Alert if below 99%
    ))