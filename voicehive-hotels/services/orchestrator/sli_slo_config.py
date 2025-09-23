"""
Service Level Indicators (SLI) and Service Level Objectives (SLO) Configuration
Production-grade SLI/SLO implementation with error budgets and burn rate monitoring
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
import yaml
from pathlib import Path

class SLIType(str, Enum):
    """Types of Service Level Indicators"""
    AVAILABILITY = "availability"
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"
    CUSTOM = "custom"

class SLOCompliance(str, Enum):
    """SLO compliance status"""
    COMPLIANT = "compliant"
    AT_RISK = "at_risk"
    VIOLATED = "violated"
    UNKNOWN = "unknown"

class BurnRateWindow(str, Enum):
    """Burn rate monitoring windows"""
    FAST = "1h"      # 1 hour - for immediate alerts
    MEDIUM = "6h"    # 6 hours - for early warning
    SLOW = "24h"     # 24 hours - for trend monitoring
    VERY_SLOW = "72h" # 72 hours - for capacity planning

@dataclass
class SLIDefinition:
    """Service Level Indicator definition"""
    name: str
    description: str
    sli_type: SLIType
    query: str  # Prometheus query
    unit: str
    good_total_ratio: bool = True  # True for good/total, False for bad/total
    labels: Dict[str, str] = field(default_factory=dict)

@dataclass
class SLOTarget:
    """Service Level Objective target definition"""
    target_percentage: float  # e.g., 99.9 for 99.9%
    compliance_period: str    # e.g., "30d", "7d", "1h"
    description: str

@dataclass
class ErrorBudgetPolicy:
    """Error budget policy configuration"""
    burn_rate_thresholds: Dict[BurnRateWindow, float] = field(default_factory=lambda: {
        BurnRateWindow.FAST: 14.4,     # 1% budget in 1 hour (for 99.9% SLO)
        BurnRateWindow.MEDIUM: 6.0,    # 5% budget in 6 hours
        BurnRateWindow.SLOW: 3.0,      # 10% budget in 24 hours
        BurnRateWindow.VERY_SLOW: 1.0  # 25% budget in 72 hours
    })
    alert_on_exhaustion_percentage: float = 90.0  # Alert when 90% of budget consumed
    freeze_deployments_percentage: float = 95.0   # Freeze deployments at 95%

@dataclass
class SLODefinition:
    """Complete SLO definition with SLI, targets, and policies"""
    name: str
    service: str
    sli: SLIDefinition
    targets: List[SLOTarget]
    error_budget_policy: ErrorBudgetPolicy
    enabled: bool = True
    tags: Dict[str, str] = field(default_factory=dict)

class VoiceHiveSLOConfig:
    """VoiceHive Hotels SLI/SLO Configuration"""
    
    @staticmethod
    def get_core_slos() -> List[SLODefinition]:
        """Get core SLO definitions for VoiceHive services"""
        
        return [
            # API Availability SLO
            SLODefinition(
                name="api_availability",
                service="orchestrator",
                sli=SLIDefinition(
                    name="api_availability",
                    description="Percentage of successful API requests",
                    sli_type=SLIType.AVAILABILITY,
                    query="""
                    sum(rate(voicehive_requests_total{status!~"5.."}[5m])) /
                    sum(rate(voicehive_requests_total[5m]))
                    """,
                    unit="percentage",
                    good_total_ratio=True,
                    labels={"service": "orchestrator", "type": "availability"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=99.9,
                        compliance_period="30d",
                        description="99.9% availability over 30 days"
                    ),
                    SLOTarget(
                        target_percentage=99.5,
                        compliance_period="7d",
                        description="99.5% availability over 7 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(),
                tags={"criticality": "high", "team": "platform"}
            ),
            
            # API Latency SLO
            SLODefinition(
                name="api_latency_p95",
                service="orchestrator",
                sli=SLIDefinition(
                    name="api_latency_p95",
                    description="95th percentile API response latency under 2 seconds",
                    sli_type=SLIType.LATENCY,
                    query="""
                    sum(rate(voicehive_request_duration_seconds_bucket{le="2.0"}[5m])) /
                    sum(rate(voicehive_request_duration_seconds_count[5m]))
                    """,
                    unit="percentage",
                    good_total_ratio=True,
                    labels={"service": "orchestrator", "type": "latency", "percentile": "95"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=95.0,
                        compliance_period="30d",
                        description="95% of requests under 2s over 30 days"
                    ),
                    SLOTarget(
                        target_percentage=90.0,
                        compliance_period="7d",
                        description="90% of requests under 2s over 7 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(
                    burn_rate_thresholds={
                        BurnRateWindow.FAST: 7.2,     # Adjusted for 95% SLO
                        BurnRateWindow.MEDIUM: 3.0,
                        BurnRateWindow.SLOW: 1.5,
                        BurnRateWindow.VERY_SLOW: 0.5
                    }
                ),
                tags={"criticality": "high", "team": "platform"}
            ),
            
            # Call Success Rate SLO
            SLODefinition(
                name="call_success_rate",
                service="call-manager",
                sli=SLIDefinition(
                    name="call_success_rate",
                    description="Percentage of successful voice calls",
                    sli_type=SLIType.AVAILABILITY,
                    query="""
                    sum(rate(voicehive_call_success_total[5m])) /
                    (sum(rate(voicehive_call_success_total[5m])) + sum(rate(voicehive_call_failures_total[5m])))
                    """,
                    unit="percentage",
                    good_total_ratio=True,
                    labels={"service": "call-manager", "type": "business"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=99.0,
                        compliance_period="30d",
                        description="99% call success rate over 30 days"
                    ),
                    SLOTarget(
                        target_percentage=98.0,
                        compliance_period="7d",
                        description="98% call success rate over 7 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(),
                tags={"criticality": "critical", "team": "voice", "business_impact": "high"}
            ),
            
            # PMS Connector Availability SLO
            SLODefinition(
                name="pms_connector_availability",
                service="pms-connector",
                sli=SLIDefinition(
                    name="pms_connector_availability",
                    description="PMS connector operation success rate",
                    sli_type=SLIType.AVAILABILITY,
                    query="""
                    sum(rate(voicehive_pms_operations_total{status="success"}[5m])) /
                    sum(rate(voicehive_pms_operations_total[5m]))
                    """,
                    unit="percentage",
                    good_total_ratio=True,
                    labels={"service": "pms-connector", "type": "integration"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=98.0,
                        compliance_period="30d",
                        description="98% PMS operation success over 30 days"
                    ),
                    SLOTarget(
                        target_percentage=95.0,
                        compliance_period="7d",
                        description="95% PMS operation success over 7 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(
                    burn_rate_thresholds={
                        BurnRateWindow.FAST: 3.6,     # Adjusted for 98% SLO
                        BurnRateWindow.MEDIUM: 1.5,
                        BurnRateWindow.SLOW: 0.75,
                        BurnRateWindow.VERY_SLOW: 0.25
                    }
                ),
                tags={"criticality": "high", "team": "integrations"}
            ),
            
            # PMS Response Time SLO
            SLODefinition(
                name="pms_response_time",
                service="pms-connector",
                sli=SLIDefinition(
                    name="pms_response_time",
                    description="PMS response time under 5 seconds",
                    sli_type=SLIType.LATENCY,
                    query="""
                    sum(rate(voicehive_pms_response_seconds_bucket{le="5.0"}[5m])) /
                    sum(rate(voicehive_pms_response_seconds_count[5m]))
                    """,
                    unit="percentage",
                    good_total_ratio=True,
                    labels={"service": "pms-connector", "type": "latency"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=90.0,
                        compliance_period="30d",
                        description="90% of PMS requests under 5s over 30 days"
                    ),
                    SLOTarget(
                        target_percentage=85.0,
                        compliance_period="7d",
                        description="85% of PMS requests under 5s over 7 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(
                    burn_rate_thresholds={
                        BurnRateWindow.FAST: 1.8,     # Adjusted for 90% SLO
                        BurnRateWindow.MEDIUM: 0.75,
                        BurnRateWindow.SLOW: 0.375,
                        BurnRateWindow.VERY_SLOW: 0.125
                    }
                ),
                tags={"criticality": "medium", "team": "integrations"}
            ),
            
            # Authentication Success Rate SLO
            SLODefinition(
                name="auth_success_rate",
                service="auth",
                sli=SLIDefinition(
                    name="auth_success_rate",
                    description="Authentication success rate",
                    sli_type=SLIType.AVAILABILITY,
                    query="""
                    (sum(rate(voicehive_auth_requests_total[5m])) - sum(rate(voicehive_auth_failures_total[5m]))) /
                    sum(rate(voicehive_auth_requests_total[5m]))
                    """,
                    unit="percentage",
                    good_total_ratio=True,
                    labels={"service": "auth", "type": "security"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=99.5,
                        compliance_period="30d",
                        description="99.5% authentication success over 30 days"
                    ),
                    SLOTarget(
                        target_percentage=99.0,
                        compliance_period="7d",
                        description="99% authentication success over 7 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(),
                tags={"criticality": "critical", "team": "security"}
            ),
            
            # Database Connection Pool SLO
            SLODefinition(
                name="database_connection_availability",
                service="database",
                sli=SLIDefinition(
                    name="database_connection_availability",
                    description="Database connection pool availability",
                    sli_type=SLIType.AVAILABILITY,
                    query="""
                    min(voicehive_connection_pool_active / voicehive_connection_pool_max < 0.95)
                    """,
                    unit="percentage",
                    good_total_ratio=True,
                    labels={"service": "database", "type": "infrastructure"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=99.0,
                        compliance_period="30d",
                        description="99% database connection availability over 30 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(),
                tags={"criticality": "critical", "team": "platform"}
            )
        ]
    
    @staticmethod
    def get_business_slos() -> List[SLODefinition]:
        """Get business-focused SLO definitions"""
        
        return [
            # Guest Satisfaction SLO
            SLODefinition(
                name="guest_satisfaction",
                service="call-manager",
                sli=SLIDefinition(
                    name="guest_satisfaction",
                    description="Average guest satisfaction score above 4.0",
                    sli_type=SLIType.CUSTOM,
                    query="""
                    sum(rate(voicehive_guest_satisfaction_sum[24h])) /
                    sum(rate(voicehive_guest_satisfaction_count[24h])) >= 4.0
                    """,
                    unit="score",
                    good_total_ratio=True,
                    labels={"service": "call-manager", "type": "business", "metric": "satisfaction"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=90.0,
                        compliance_period="30d",
                        description="90% of time satisfaction score above 4.0 over 30 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(
                    burn_rate_thresholds={
                        BurnRateWindow.FAST: 1.8,
                        BurnRateWindow.MEDIUM: 0.75,
                        BurnRateWindow.SLOW: 0.375,
                        BurnRateWindow.VERY_SLOW: 0.125
                    }
                ),
                tags={"criticality": "high", "team": "product", "business_impact": "critical"}
            ),
            
            # Booking Conversion Rate SLO
            SLODefinition(
                name="booking_conversion_rate",
                service="call-manager",
                sli=SLIDefinition(
                    name="booking_conversion_rate",
                    description="Booking conversion rate from voice interactions",
                    sli_type=SLIType.CUSTOM,
                    query="""
                    sum(rate(voicehive_booking_conversions_total{outcome="success"}[1h])) /
                    sum(rate(voicehive_booking_conversions_total[1h]))
                    """,
                    unit="percentage",
                    good_total_ratio=True,
                    labels={"service": "call-manager", "type": "business", "metric": "conversion"}
                ),
                targets=[
                    SLOTarget(
                        target_percentage=15.0,  # 15% conversion rate target
                        compliance_period="30d",
                        description="15% booking conversion rate over 30 days"
                    )
                ],
                error_budget_policy=ErrorBudgetPolicy(
                    burn_rate_thresholds={
                        BurnRateWindow.FAST: 1.0,
                        BurnRateWindow.MEDIUM: 0.5,
                        BurnRateWindow.SLOW: 0.25,
                        BurnRateWindow.VERY_SLOW: 0.1
                    },
                    alert_on_exhaustion_percentage=80.0  # More sensitive for business metrics
                ),
                tags={"criticality": "high", "team": "product", "business_impact": "revenue"}
            )
        ]
    
    @staticmethod
    def load_from_file(file_path: str) -> List[SLODefinition]:
        """Load SLO definitions from YAML file"""
        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)
            
            slos = []
            for slo_data in data.get('slos', []):
                slo = SLODefinition(**slo_data)
                slos.append(slo)
            
            return slos
        except Exception as e:
            raise ValueError(f"Failed to load SLO configuration from {file_path}: {e}")
    
    @staticmethod
    def save_to_file(slos: List[SLODefinition], file_path: str):
        """Save SLO definitions to YAML file"""
        try:
            data = {
                'slos': [
                    {
                        'name': slo.name,
                        'service': slo.service,
                        'sli': {
                            'name': slo.sli.name,
                            'description': slo.sli.description,
                            'sli_type': slo.sli.sli_type.value,
                            'query': slo.sli.query.strip(),
                            'unit': slo.sli.unit,
                            'good_total_ratio': slo.sli.good_total_ratio,
                            'labels': slo.sli.labels
                        },
                        'targets': [
                            {
                                'target_percentage': target.target_percentage,
                                'compliance_period': target.compliance_period,
                                'description': target.description
                            }
                            for target in slo.targets
                        ],
                        'error_budget_policy': {
                            'burn_rate_thresholds': {
                                window.value: threshold
                                for window, threshold in slo.error_budget_policy.burn_rate_thresholds.items()
                            },
                            'alert_on_exhaustion_percentage': slo.error_budget_policy.alert_on_exhaustion_percentage,
                            'freeze_deployments_percentage': slo.error_budget_policy.freeze_deployments_percentage
                        },
                        'enabled': slo.enabled,
                        'tags': slo.tags
                    }
                    for slo in slos
                ]
            }
            
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w') as f:
                yaml.dump(data, f, default_flow_style=False, indent=2)
                
        except Exception as e:
            raise ValueError(f"Failed to save SLO configuration to {file_path}: {e}")

# Global SLO registry
SLO_REGISTRY = VoiceHiveSLOConfig.get_core_slos() + VoiceHiveSLOConfig.get_business_slos()