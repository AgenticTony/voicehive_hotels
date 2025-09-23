"""
Monitoring Configuration for VoiceHive Hotels
Centralized configuration for monitoring, alerting, and observability
"""

import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from enhanced_alerting import AlertRule, AlertSeverity, SLATarget


@dataclass
class MonitoringConfig:
    """Monitoring system configuration"""
    
    # Metrics collection
    metrics_enabled: bool = True
    metrics_port: int = 8000
    metrics_path: str = "/monitoring/metrics"
    
    # Alerting configuration
    alerting_enabled: bool = True
    alert_evaluation_interval: int = 30  # seconds
    sla_evaluation_interval: int = 60    # seconds
    
    # Notification channels
    slack_webhook_url: Optional[str] = None
    slack_channel: str = "#alerts"
    pagerduty_integration_key: Optional[str] = None
    
    # Tracing configuration
    tracing_enabled: bool = True
    jaeger_endpoint: str = "http://jaeger:14268/api/traces"
    otlp_endpoint: str = "http://tempo:4317"
    trace_sample_rate: float = 1.0
    
    # Dashboard configuration
    grafana_url: Optional[str] = None
    grafana_api_key: Optional[str] = None
    
    # Business metrics thresholds
    call_success_rate_threshold: float = 99.0
    pms_response_time_threshold: float = 2.0  # seconds
    guest_satisfaction_threshold: float = 4.0
    
    # System health thresholds
    cpu_usage_threshold: float = 80.0  # percent
    memory_usage_threshold: float = 80.0  # percent
    error_rate_threshold: float = 5.0  # percent


def get_monitoring_config() -> MonitoringConfig:
    """Get monitoring configuration from environment variables"""
    return MonitoringConfig(
        # Metrics
        metrics_enabled=os.getenv("METRICS_ENABLED", "true").lower() == "true",
        metrics_port=int(os.getenv("METRICS_PORT", "8000")),
        metrics_path=os.getenv("METRICS_PATH", "/monitoring/metrics"),
        
        # Alerting
        alerting_enabled=os.getenv("ALERTING_ENABLED", "true").lower() == "true",
        alert_evaluation_interval=int(os.getenv("ALERT_EVALUATION_INTERVAL", "30")),
        sla_evaluation_interval=int(os.getenv("SLA_EVALUATION_INTERVAL", "60")),
        
        # Notifications
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
        slack_channel=os.getenv("SLACK_CHANNEL", "#alerts"),
        pagerduty_integration_key=os.getenv("PAGERDUTY_INTEGRATION_KEY"),
        
        # Tracing
        tracing_enabled=os.getenv("TRACING_ENABLED", "true").lower() == "true",
        jaeger_endpoint=os.getenv("JAEGER_ENDPOINT", "http://jaeger:14268/api/traces"),
        otlp_endpoint=os.getenv("OTLP_ENDPOINT", "http://tempo:4317"),
        trace_sample_rate=float(os.getenv("TRACE_SAMPLE_RATE", "1.0")),
        
        # Dashboard
        grafana_url=os.getenv("GRAFANA_URL"),
        grafana_api_key=os.getenv("GRAFANA_API_KEY"),
        
        # Business thresholds
        call_success_rate_threshold=float(os.getenv("CALL_SUCCESS_RATE_THRESHOLD", "99.0")),
        pms_response_time_threshold=float(os.getenv("PMS_RESPONSE_TIME_THRESHOLD", "2.0")),
        guest_satisfaction_threshold=float(os.getenv("GUEST_SATISFACTION_THRESHOLD", "4.0")),
        
        # System thresholds
        cpu_usage_threshold=float(os.getenv("CPU_USAGE_THRESHOLD", "80.0")),
        memory_usage_threshold=float(os.getenv("MEMORY_USAGE_THRESHOLD", "80.0")),
        error_rate_threshold=float(os.getenv("ERROR_RATE_THRESHOLD", "5.0"))
    )


def create_production_alert_rules(config: MonitoringConfig) -> List[AlertRule]:
    """Create production-ready alert rules based on configuration"""
    
    rules = []
    
    # Call success rate alerts
    rules.append(AlertRule(
        name="call_success_rate_critical",
        description=f"Call success rate below {config.call_success_rate_threshold - 2}% for more than 5 minutes",
        severity=AlertSeverity.CRITICAL,
        metric_name="voicehive_call_success_rate",
        threshold=config.call_success_rate_threshold - 2,
        comparison="lt",
        duration=300,  # 5 minutes
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/call-failures",
        escalation_policy="critical"
    ))
    
    rules.append(AlertRule(
        name="call_success_rate_warning",
        description=f"Call success rate below {config.call_success_rate_threshold}% for more than 2 minutes",
        severity=AlertSeverity.HIGH,
        metric_name="voicehive_call_success_rate",
        threshold=config.call_success_rate_threshold,
        comparison="lt",
        duration=120,  # 2 minutes
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/call-failures"
    ))
    
    # PMS response time alerts
    rules.append(AlertRule(
        name="pms_response_time_critical",
        description=f"PMS response time above {config.pms_response_time_threshold * 2}s for more than 3 minutes",
        severity=AlertSeverity.CRITICAL,
        metric_name="voicehive_pms_response_seconds",
        threshold=config.pms_response_time_threshold * 2,
        comparison="gt",
        duration=180,  # 3 minutes
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/pms-performance"
    ))
    
    rules.append(AlertRule(
        name="pms_response_time_warning",
        description=f"PMS response time above {config.pms_response_time_threshold}s",
        severity=AlertSeverity.MEDIUM,
        metric_name="voicehive_pms_response_seconds",
        threshold=config.pms_response_time_threshold,
        comparison="gt",
        duration=60,
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/pms-performance"
    ))
    
    # System resource alerts
    rules.append(AlertRule(
        name="high_cpu_usage",
        description=f"CPU usage above {config.cpu_usage_threshold}% for more than 5 minutes",
        severity=AlertSeverity.HIGH,
        metric_name="voicehive_cpu_usage_percent",
        threshold=config.cpu_usage_threshold,
        comparison="gt",
        duration=300,
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/high-cpu"
    ))
    
    rules.append(AlertRule(
        name="high_memory_usage",
        description=f"Memory usage above {config.memory_usage_threshold}% for more than 5 minutes",
        severity=AlertSeverity.HIGH,
        metric_name="voicehive_memory_usage_percent",
        threshold=config.memory_usage_threshold,
        comparison="gt",
        duration=300,
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/high-memory"
    ))
    
    # Error rate alerts
    rules.append(AlertRule(
        name="high_error_rate",
        description=f"Error rate above {config.error_rate_threshold}% for more than 2 minutes",
        severity=AlertSeverity.HIGH,
        metric_name="voicehive_error_rate_percent",
        threshold=config.error_rate_threshold,
        comparison="gt",
        duration=120,
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/high-errors"
    ))
    
    # PMS availability alerts
    rules.append(AlertRule(
        name="pms_unavailable",
        description="PMS system unavailable",
        severity=AlertSeverity.CRITICAL,
        metric_name="voicehive_pms_availability",
        threshold=0.5,
        comparison="lt",
        duration=60,
        labels={},
        runbook_url="https://docs.voicehive.com/runbooks/pms-unavailable",
        escalation_policy="critical"
    ))
    
    return rules


def create_production_sla_targets(config: MonitoringConfig) -> List[SLATarget]:
    """Create production SLA targets based on configuration"""
    
    targets = []
    
    # Call success rate SLA
    targets.append(SLATarget(
        name="call_success_rate_sla",
        description=f"Call success rate should be above {config.call_success_rate_threshold}%",
        target_percentage=config.call_success_rate_threshold,
        measurement_window=3600,  # 1 hour
        metric_query="call_success_rate",
        labels={},
        alert_threshold=1.0  # Alert if below 98%
    ))
    
    # PMS response time SLA
    targets.append(SLATarget(
        name="pms_response_time_sla",
        description=f"95% of PMS requests should complete within {config.pms_response_time_threshold}s",
        target_percentage=95.0,
        measurement_window=3600,
        metric_query="pms_response_time_p95",
        labels={},
        alert_threshold=5.0  # Alert if below 90%
    ))
    
    # System availability SLA
    targets.append(SLATarget(
        name="system_availability_sla",
        description="System should be available 99.9% of the time",
        target_percentage=99.9,
        measurement_window=86400,  # 24 hours
        metric_query="system_availability",
        labels={},
        alert_threshold=0.1  # Alert if below 99.8%
    ))
    
    # Guest satisfaction SLA
    targets.append(SLATarget(
        name="guest_satisfaction_sla",
        description=f"Average guest satisfaction should be above {config.guest_satisfaction_threshold}",
        target_percentage=config.guest_satisfaction_threshold * 20,  # Convert to percentage
        measurement_window=86400,
        metric_query="guest_satisfaction_average",
        labels={},
        alert_threshold=10.0  # Alert if significantly below target
    ))
    
    return targets


# Environment-specific configurations
DEVELOPMENT_CONFIG = MonitoringConfig(
    alerting_enabled=False,  # Disable alerting in development
    tracing_enabled=True,
    trace_sample_rate=1.0,   # Sample all traces in development
    alert_evaluation_interval=60,
    sla_evaluation_interval=300
)

STAGING_CONFIG = MonitoringConfig(
    alerting_enabled=True,
    tracing_enabled=True,
    trace_sample_rate=0.1,   # Sample 10% of traces in staging
    alert_evaluation_interval=30,
    sla_evaluation_interval=60
)

PRODUCTION_CONFIG = MonitoringConfig(
    alerting_enabled=True,
    tracing_enabled=True,
    trace_sample_rate=0.01,  # Sample 1% of traces in production
    alert_evaluation_interval=15,  # More frequent evaluation in production
    sla_evaluation_interval=30
)


def get_environment_config(environment: str) -> MonitoringConfig:
    """Get monitoring configuration for specific environment"""
    
    configs = {
        "development": DEVELOPMENT_CONFIG,
        "staging": STAGING_CONFIG,
        "production": PRODUCTION_CONFIG
    }
    
    base_config = configs.get(environment, DEVELOPMENT_CONFIG)
    
    # Override with environment variables
    env_config = get_monitoring_config()
    
    # Merge configurations (environment variables take precedence)
    return MonitoringConfig(
        metrics_enabled=env_config.metrics_enabled,
        metrics_port=env_config.metrics_port,
        metrics_path=env_config.metrics_path,
        alerting_enabled=env_config.alerting_enabled if env_config.alerting_enabled is not None else base_config.alerting_enabled,
        alert_evaluation_interval=env_config.alert_evaluation_interval,
        sla_evaluation_interval=env_config.sla_evaluation_interval,
        slack_webhook_url=env_config.slack_webhook_url,
        slack_channel=env_config.slack_channel,
        pagerduty_integration_key=env_config.pagerduty_integration_key,
        tracing_enabled=env_config.tracing_enabled if env_config.tracing_enabled is not None else base_config.tracing_enabled,
        jaeger_endpoint=env_config.jaeger_endpoint,
        otlp_endpoint=env_config.otlp_endpoint,
        trace_sample_rate=env_config.trace_sample_rate,
        grafana_url=env_config.grafana_url,
        grafana_api_key=env_config.grafana_api_key,
        call_success_rate_threshold=env_config.call_success_rate_threshold,
        pms_response_time_threshold=env_config.pms_response_time_threshold,
        guest_satisfaction_threshold=env_config.guest_satisfaction_threshold,
        cpu_usage_threshold=env_config.cpu_usage_threshold,
        memory_usage_threshold=env_config.memory_usage_threshold,
        error_rate_threshold=env_config.error_rate_threshold
    )