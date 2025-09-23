"""
Regulatory Compliance Monitoring and Violation Alerting System for VoiceHive Hotels
Real-time monitoring of compliance status with automated violation detection and alerting
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set, Callable, Tuple
from enum import Enum
from dataclasses import dataclass, asdict, field
from pathlib import Path
import uuid

from pydantic import BaseModel, Field, validator
from sqlalchemy import text, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger, AuditEventType, AuditSeverity
from compliance_evidence_collector import ComplianceFramework, ComplianceRequirement, EvidenceStatus
from gdpr_compliance_manager import GDPRLawfulBasis, DataSubjectRight

logger = get_safe_logger("orchestrator.compliance_monitoring")


class ViolationType(str, Enum):
    """Types of compliance violations"""
    DATA_RETENTION_EXCEEDED = "data_retention_exceeded"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    MISSING_CONSENT = "missing_consent"
    EXPIRED_EVIDENCE = "expired_evidence"
    SECURITY_CONTROL_FAILURE = "security_control_failure"
    AUDIT_LOG_GAP = "audit_log_gap"
    ENCRYPTION_VIOLATION = "encryption_violation"
    CROSS_BORDER_TRANSFER = "cross_border_transfer"
    BREACH_NOTIFICATION_DELAY = "breach_notification_delay"
    DSAR_RESPONSE_OVERDUE = "dsar_response_overdue"
    PII_EXPOSURE = "pii_exposure"
    ACCESS_CONTROL_VIOLATION = "access_control_violation"


class ViolationSeverity(str, Enum):
    """Severity levels for compliance violations"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MonitoringStatus(str, Enum):
    """Status of compliance monitoring"""
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    ERROR = "error"


class AlertChannel(str, Enum):
    """Alert notification channels"""
    EMAIL = "email"
    SLACK = "slack"
    PAGERDUTY = "pagerduty"
    WEBHOOK = "webhook"
    SMS = "sms"
    TEAMS = "teams"


@dataclass
class ComplianceRule:
    """Individual compliance monitoring rule"""
    rule_id: str
    name: str
    description: str
    framework: ComplianceFramework
    requirement: ComplianceRequirement
    violation_type: ViolationType
    
    # Rule logic
    condition_query: str
    threshold_value: Optional[float] = None
    threshold_operator: str = ">"  # >, <, >=, <=, ==, !=
    
    # Monitoring configuration
    check_interval_minutes: int = 60
    enabled: bool = True
    
    # Severity and alerting
    severity: ViolationSeverity = ViolationSeverity.MEDIUM
    alert_channels: List[AlertChannel] = field(default_factory=list)
    alert_recipients: List[str] = field(default_factory=list)
    
    # Timing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_checked: Optional[datetime] = None
    last_violation: Optional[datetime] = None
    
    # Metadata
    tags: List[str] = field(default_factory=list)
    remediation_steps: List[str] = field(default_factory=list)
    
    def should_check(self) -> bool:
        """Check if rule should be evaluated now"""
        if not self.enabled:
            return False
        
        if not self.last_checked:
            return True
        
        next_check = self.last_checked + timedelta(minutes=self.check_interval_minutes)
        return datetime.now(timezone.utc) >= next_check


@dataclass
class ComplianceViolation:
    """Detected compliance violation"""
    violation_id: str
    rule_id: str
    violation_type: ViolationType
    framework: ComplianceFramework
    requirement: ComplianceRequirement
    
    # Violation details
    title: str
    description: str
    severity: ViolationSeverity
    
    # Detection details
    detected_at: datetime
    detection_query: str
    detection_result: Any
    threshold_exceeded: Optional[float] = None
    
    # Context
    affected_resources: List[str] = field(default_factory=list)
    data_subjects_affected: List[str] = field(default_factory=list)
    
    # Status and resolution
    status: str = "open"  # open, investigating, resolved, false_positive
    assigned_to: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    
    # Risk assessment
    risk_score: float = 0.0
    business_impact: str = "medium"
    regulatory_impact: str = "medium"
    
    # Remediation
    remediation_steps: List[str] = field(default_factory=list)
    remediation_deadline: Optional[datetime] = None
    
    # Notifications
    notifications_sent: List[Dict[str, Any]] = field(default_factory=list)
    escalation_level: int = 0
    
    def is_overdue(self) -> bool:
        """Check if violation remediation is overdue"""
        if self.remediation_deadline and self.status == "open":
            return datetime.now(timezone.utc) > self.remediation_deadline
        return False
    
    def calculate_risk_score(self) -> float:
        """Calculate risk score based on severity and impact"""
        severity_weights = {
            ViolationSeverity.LOW: 1.0,
            ViolationSeverity.MEDIUM: 2.5,
            ViolationSeverity.HIGH: 4.0,
            ViolationSeverity.CRITICAL: 5.0
        }
        
        impact_weights = {
            "low": 1.0,
            "medium": 2.0,
            "high": 3.0,
            "critical": 4.0
        }
        
        severity_score = severity_weights.get(self.severity, 2.5)
        business_score = impact_weights.get(self.business_impact, 2.0)
        regulatory_score = impact_weights.get(self.regulatory_impact, 2.0)
        
        # Calculate weighted risk score (0-10 scale)
        risk_score = (severity_score * 0.4 + business_score * 0.3 + regulatory_score * 0.3) * 2
        self.risk_score = min(10.0, risk_score)
        return self.risk_score


@dataclass
class MonitoringDashboard:
    """Compliance monitoring dashboard data"""
    generated_at: datetime
    
    # Overall status
    total_rules: int = 0
    active_rules: int = 0
    total_violations: int = 0
    open_violations: int = 0
    
    # Violations by severity
    critical_violations: int = 0
    high_violations: int = 0
    medium_violations: int = 0
    low_violations: int = 0
    
    # Violations by framework
    violations_by_framework: Dict[str, int] = field(default_factory=dict)
    violations_by_type: Dict[str, int] = field(default_factory=dict)
    
    # Trends
    violations_last_24h: int = 0
    violations_last_7d: int = 0
    violations_last_30d: int = 0
    
    # Top violations
    top_violation_types: List[Dict[str, Any]] = field(default_factory=list)
    overdue_violations: List[str] = field(default_factory=list)
    
    # Compliance scores
    framework_scores: Dict[str, float] = field(default_factory=dict)
    overall_compliance_score: float = 0.0


class ComplianceMonitoringSystem:
    """Real-time compliance monitoring and violation alerting system"""
    
    def __init__(self, 
                 db_session: AsyncSession,
                 audit_logger: Optional[AuditLogger] = None,
                 config_path: Optional[str] = None):
        self.db = db_session
        self.audit_logger = audit_logger or AuditLogger()
        
        # Load configuration
        self.config = self._load_config(config_path)
        
        # Monitoring state
        self.monitoring_status = MonitoringStatus.ACTIVE
        self.rules: Dict[str, ComplianceRule] = {}
        self.violations: Dict[str, ComplianceViolation] = {}
        
        # Alert handlers
        self.alert_handlers: Dict[AlertChannel, Callable] = {}
        self._initialize_alert_handlers()
        
        # Statistics
        self.monitoring_stats = {
            "rules_executed": 0,
            "violations_detected": 0,
            "alerts_sent": 0,
            "false_positives": 0,
            "last_monitoring_run": None
        }
        
        # Load default rules
        self._load_default_rules()
        
        # Start monitoring loop
        self.monitoring_task = None
        if self.config.get("auto_start_monitoring", True):
            self.start_monitoring()
    
    def start_monitoring(self):
        """Start the compliance monitoring loop"""
        if self.monitoring_task is None or self.monitoring_task.done():
            self.monitoring_task = asyncio.create_task(self._monitoring_loop())
            self.monitoring_status = MonitoringStatus.ACTIVE
            logger.info("Compliance monitoring started")
    
    def stop_monitoring(self):
        """Stop the compliance monitoring loop"""
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
            self.monitoring_status = MonitoringStatus.PAUSED
            logger.info("Compliance monitoring stopped")
    
    async def add_monitoring_rule(self, rule: ComplianceRule) -> ComplianceRule:
        """Add a new compliance monitoring rule"""
        
        self.rules[rule.rule_id] = rule
        
        # Store in database
        await self._store_monitoring_rule(rule)
        
        # Audit rule creation
        self.audit_logger.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            description=f"Compliance monitoring rule added: {rule.name}",
            severity=AuditSeverity.MEDIUM,
            resource_type="monitoring_rule",
            resource_id=rule.rule_id,
            action="create",
            metadata={
                "rule_name": rule.name,
                "framework": rule.framework.value,
                "violation_type": rule.violation_type.value,
                "severity": rule.severity.value
            },
            retention_period=2555
        )
        
        logger.info(f"Monitoring rule added: {rule.rule_id} - {rule.name}")
        return rule
    
    async def update_monitoring_rule(self, rule_id: str, updates: Dict[str, Any]) -> ComplianceRule:
        """Update an existing monitoring rule"""
        
        if rule_id not in self.rules:
            raise ValueError(f"Monitoring rule not found: {rule_id}")
        
        rule = self.rules[rule_id]
        
        # Apply updates
        for key, value in updates.items():
            if hasattr(rule, key):
                setattr(rule, key, value)
        
        # Store updated rule
        await self._update_monitoring_rule(rule)
        
        # Audit rule update
        self.audit_logger.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            description=f"Compliance monitoring rule updated: {rule.name}",
            severity=AuditSeverity.MEDIUM,
            resource_type="monitoring_rule",
            resource_id=rule_id,
            action="update",
            metadata={"updates": updates},
            retention_period=2555
        )
        
        logger.info(f"Monitoring rule updated: {rule_id}")
        return rule
    
    async def execute_rule_check(self, rule_id: str) -> Optional[ComplianceViolation]:
        """Execute a specific monitoring rule check"""
        
        if rule_id not in self.rules:
            raise ValueError(f"Monitoring rule not found: {rule_id}")
        
        rule = self.rules[rule_id]
        
        if not rule.enabled:
            return None
        
        try:
            # Execute rule condition query
            result = await self.db.execute(text(rule.condition_query))
            query_result = result.fetchall()
            
            # Update last checked time
            rule.last_checked = datetime.now(timezone.utc)
            
            # Evaluate rule condition
            violation = await self._evaluate_rule_condition(rule, query_result)
            
            if violation:
                # Store violation
                self.violations[violation.violation_id] = violation
                await self._store_violation(violation)
                
                # Send alerts
                await self._send_violation_alerts(violation, rule)
                
                # Update statistics
                self.monitoring_stats["violations_detected"] += 1
                rule.last_violation = violation.detected_at
                
                # Audit violation detection
                self.audit_logger.log_event(
                    event_type=AuditEventType.SECURITY_VIOLATION,
                    description=f"Compliance violation detected: {violation.title}",
                    severity=AuditSeverity.CRITICAL if violation.severity == ViolationSeverity.CRITICAL else AuditSeverity.HIGH,
                    resource_type="compliance_violation",
                    resource_id=violation.violation_id,
                    action="detect",
                    metadata={
                        "violation_type": violation.violation_type.value,
                        "framework": violation.framework.value,
                        "severity": violation.severity.value,
                        "risk_score": violation.risk_score
                    },
                    retention_period=2555
                )
                
                logger.warning(f"Compliance violation detected: {violation.violation_id} - {violation.title}")
            
            # Update statistics
            self.monitoring_stats["rules_executed"] += 1
            
            return violation
        
        except Exception as e:
            logger.error(f"Failed to execute monitoring rule {rule_id}: {e}")
            raise
    
    async def resolve_violation(self, 
                              violation_id: str, 
                              resolution_notes: str,
                              resolved_by: str) -> ComplianceViolation:
        """Mark a violation as resolved"""
        
        if violation_id not in self.violations:
            raise ValueError(f"Violation not found: {violation_id}")
        
        violation = self.violations[violation_id]
        violation.status = "resolved"
        violation.resolved_at = datetime.now(timezone.utc)
        violation.resolution_notes = resolution_notes
        violation.assigned_to = resolved_by
        
        # Store updated violation
        await self._update_violation(violation)
        
        # Audit resolution
        self.audit_logger.log_event(
            event_type=AuditEventType.ADMIN_ACTION,
            description=f"Compliance violation resolved: {violation.title}",
            severity=AuditSeverity.MEDIUM,
            resource_type="compliance_violation",
            resource_id=violation_id,
            action="resolve",
            metadata={
                "resolved_by": resolved_by,
                "resolution_notes": resolution_notes
            },
            retention_period=2555
        )
        
        logger.info(f"Violation resolved: {violation_id} by {resolved_by}")
        return violation
    
    async def generate_monitoring_dashboard(self) -> MonitoringDashboard:
        """Generate compliance monitoring dashboard"""
        
        dashboard = MonitoringDashboard(
            generated_at=datetime.now(timezone.utc)
        )
        
        # Calculate rule statistics
        dashboard.total_rules = len(self.rules)
        dashboard.active_rules = len([r for r in self.rules.values() if r.enabled])
        
        # Calculate violation statistics
        dashboard.total_violations = len(self.violations)
        dashboard.open_violations = len([v for v in self.violations.values() if v.status == "open"])
        
        # Violations by severity
        for violation in self.violations.values():
            if violation.status == "open":
                if violation.severity == ViolationSeverity.CRITICAL:
                    dashboard.critical_violations += 1
                elif violation.severity == ViolationSeverity.HIGH:
                    dashboard.high_violations += 1
                elif violation.severity == ViolationSeverity.MEDIUM:
                    dashboard.medium_violations += 1
                elif violation.severity == ViolationSeverity.LOW:
                    dashboard.low_violations += 1
        
        # Violations by framework and type
        for violation in self.violations.values():
            framework = violation.framework.value
            violation_type = violation.violation_type.value
            
            dashboard.violations_by_framework[framework] = dashboard.violations_by_framework.get(framework, 0) + 1
            dashboard.violations_by_type[violation_type] = dashboard.violations_by_type.get(violation_type, 0) + 1
        
        # Time-based trends
        now = datetime.now(timezone.utc)
        for violation in self.violations.values():
            if violation.detected_at >= now - timedelta(hours=24):
                dashboard.violations_last_24h += 1
            if violation.detected_at >= now - timedelta(days=7):
                dashboard.violations_last_7d += 1
            if violation.detected_at >= now - timedelta(days=30):
                dashboard.violations_last_30d += 1
        
        # Top violation types
        violation_type_counts = {}
        for violation in self.violations.values():
            if violation.status == "open":
                vtype = violation.violation_type.value
                violation_type_counts[vtype] = violation_type_counts.get(vtype, 0) + 1
        
        dashboard.top_violation_types = [
            {"type": vtype, "count": count}
            for vtype, count in sorted(violation_type_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        
        # Overdue violations
        dashboard.overdue_violations = [
            v.violation_id for v in self.violations.values()
            if v.is_overdue()
        ]
        
        # Calculate compliance scores
        dashboard.framework_scores = await self._calculate_framework_scores()
        if dashboard.framework_scores:
            dashboard.overall_compliance_score = sum(dashboard.framework_scores.values()) / len(dashboard.framework_scores)
        
        return dashboard
    
    async def get_violation_report(self, 
                                 framework: Optional[ComplianceFramework] = None,
                                 severity: Optional[ViolationSeverity] = None,
                                 status: Optional[str] = None,
                                 days_back: int = 30) -> Dict[str, Any]:
        """Generate detailed violation report"""
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        
        # Filter violations
        filtered_violations = []
        for violation in self.violations.values():
            if violation.detected_at < cutoff_date:
                continue
            
            if framework and violation.framework != framework:
                continue
            
            if severity and violation.severity != severity:
                continue
            
            if status and violation.status != status:
                continue
            
            filtered_violations.append(violation)
        
        # Generate report
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "filters": {
                "framework": framework.value if framework else "all",
                "severity": severity.value if severity else "all",
                "status": status or "all",
                "days_back": days_back
            },
            "summary": {
                "total_violations": len(filtered_violations),
                "by_severity": {},
                "by_framework": {},
                "by_status": {},
                "average_risk_score": 0.0
            },
            "violations": []
        }
        
        # Calculate summary statistics
        total_risk_score = 0.0
        for violation in filtered_violations:
            # By severity
            sev = violation.severity.value
            report["summary"]["by_severity"][sev] = report["summary"]["by_severity"].get(sev, 0) + 1
            
            # By framework
            fw = violation.framework.value
            report["summary"]["by_framework"][fw] = report["summary"]["by_framework"].get(fw, 0) + 1
            
            # By status
            st = violation.status
            report["summary"]["by_status"][st] = report["summary"]["by_status"].get(st, 0) + 1
            
            # Risk score
            total_risk_score += violation.risk_score
            
            # Add to violations list
            report["violations"].append({
                "violation_id": violation.violation_id,
                "title": violation.title,
                "severity": violation.severity.value,
                "framework": violation.framework.value,
                "detected_at": violation.detected_at.isoformat(),
                "status": violation.status,
                "risk_score": violation.risk_score,
                "affected_resources": violation.affected_resources,
                "is_overdue": violation.is_overdue()
            })
        
        if filtered_violations:
            report["summary"]["average_risk_score"] = total_risk_score / len(filtered_violations)
        
        return report
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        
        logger.info("Starting compliance monitoring loop")
        
        while self.monitoring_status == MonitoringStatus.ACTIVE:
            try:
                # Check which rules need to be executed
                rules_to_check = [rule for rule in self.rules.values() if rule.should_check()]
                
                if rules_to_check:
                    logger.info(f"Executing {len(rules_to_check)} monitoring rules")
                    
                    # Execute rules
                    for rule in rules_to_check:
                        try:
                            await self.execute_rule_check(rule.rule_id)
                        except Exception as e:
                            logger.error(f"Failed to execute rule {rule.rule_id}: {e}")
                
                # Update monitoring statistics
                self.monitoring_stats["last_monitoring_run"] = datetime.now(timezone.utc)
                
                # Sleep until next check
                await asyncio.sleep(self.config.get("monitoring_interval_seconds", 300))  # 5 minutes default
            
            except asyncio.CancelledError:
                logger.info("Compliance monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in compliance monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def _evaluate_rule_condition(self, 
                                     rule: ComplianceRule, 
                                     query_result: List[Any]) -> Optional[ComplianceViolation]:
        """Evaluate rule condition and create violation if needed"""
        
        # Extract numeric value from query result if threshold-based rule
        if rule.threshold_value is not None:
            if not query_result:
                result_value = 0
            else:
                # Assume first column of first row contains the numeric value
                result_value = float(query_result[0][0]) if query_result[0] else 0
            
            # Evaluate threshold condition
            violation_detected = False
            if rule.threshold_operator == ">":
                violation_detected = result_value > rule.threshold_value
            elif rule.threshold_operator == ">=":
                violation_detected = result_value >= rule.threshold_value
            elif rule.threshold_operator == "<":
                violation_detected = result_value < rule.threshold_value
            elif rule.threshold_operator == "<=":
                violation_detected = result_value <= rule.threshold_value
            elif rule.threshold_operator == "==":
                violation_detected = result_value == rule.threshold_value
            elif rule.threshold_operator == "!=":
                violation_detected = result_value != rule.threshold_value
            
            if not violation_detected:
                return None
            
            threshold_exceeded = result_value
        else:
            # Non-threshold rule - violation if any results returned
            if not query_result:
                return None
            
            threshold_exceeded = len(query_result)
        
        # Create violation
        violation_id = str(uuid.uuid4())
        
        violation = ComplianceViolation(
            violation_id=violation_id,
            rule_id=rule.rule_id,
            violation_type=rule.violation_type,
            framework=rule.framework,
            requirement=rule.requirement,
            title=f"{rule.name} - Violation Detected",
            description=f"Rule '{rule.name}' detected a compliance violation",
            severity=rule.severity,
            detected_at=datetime.now(timezone.utc),
            detection_query=rule.condition_query,
            detection_result=query_result,
            threshold_exceeded=threshold_exceeded,
            remediation_steps=rule.remediation_steps.copy()
        )
        
        # Set remediation deadline based on severity
        deadline_hours = {
            ViolationSeverity.CRITICAL: 4,
            ViolationSeverity.HIGH: 24,
            ViolationSeverity.MEDIUM: 72,
            ViolationSeverity.LOW: 168
        }
        
        hours = deadline_hours.get(rule.severity, 72)
        violation.remediation_deadline = datetime.now(timezone.utc) + timedelta(hours=hours)
        
        # Calculate risk score
        violation.calculate_risk_score()
        
        # Extract affected resources from query result
        violation.affected_resources = self._extract_affected_resources(query_result)
        
        return violation
    
    async def _send_violation_alerts(self, violation: ComplianceViolation, rule: ComplianceRule):
        """Send alerts for detected violation"""
        
        alert_data = {
            "violation_id": violation.violation_id,
            "title": violation.title,
            "description": violation.description,
            "severity": violation.severity.value,
            "framework": violation.framework.value,
            "detected_at": violation.detected_at.isoformat(),
            "risk_score": violation.risk_score,
            "remediation_deadline": violation.remediation_deadline.isoformat() if violation.remediation_deadline else None,
            "affected_resources": violation.affected_resources
        }
        
        # Send alerts through configured channels
        for channel in rule.alert_channels:
            try:
                handler = self.alert_handlers.get(channel)
                if handler:
                    await handler(alert_data, rule.alert_recipients)
                    
                    # Record notification
                    violation.notifications_sent.append({
                        "channel": channel.value,
                        "sent_at": datetime.now(timezone.utc).isoformat(),
                        "recipients": rule.alert_recipients
                    })
                    
                    self.monitoring_stats["alerts_sent"] += 1
                else:
                    logger.warning(f"No handler configured for alert channel: {channel}")
            
            except Exception as e:
                logger.error(f"Failed to send alert via {channel}: {e}")
    
    async def _calculate_framework_scores(self) -> Dict[str, float]:
        """Calculate compliance scores for each framework"""
        
        framework_scores = {}
        
        for framework in ComplianceFramework:
            # Get violations for this framework
            framework_violations = [
                v for v in self.violations.values()
                if v.framework == framework and v.status == "open"
            ]
            
            # Get rules for this framework
            framework_rules = [
                r for r in self.rules.values()
                if r.framework == framework and r.enabled
            ]
            
            if not framework_rules:
                continue
            
            # Calculate score based on violations vs rules
            violation_penalty = 0.0
            for violation in framework_violations:
                penalty = {
                    ViolationSeverity.CRITICAL: 5.0,
                    ViolationSeverity.HIGH: 3.0,
                    ViolationSeverity.MEDIUM: 1.5,
                    ViolationSeverity.LOW: 0.5
                }.get(violation.severity, 1.0)
                
                violation_penalty += penalty
            
            # Score calculation (0-100 scale)
            max_score = 100.0
            penalty_per_rule = violation_penalty / len(framework_rules)
            score = max(0.0, max_score - (penalty_per_rule * 10))
            
            framework_scores[framework.value] = score
        
        return framework_scores
    
    def _extract_affected_resources(self, query_result: List[Any]) -> List[str]:
        """Extract affected resource identifiers from query result"""
        
        resources = []
        
        for row in query_result:
            # Try to extract resource identifiers from common column names
            row_dict = dict(row._mapping) if hasattr(row, '_mapping') else {}
            
            for key, value in row_dict.items():
                if key.lower() in ['id', 'resource_id', 'user_id', 'data_subject_id', 'record_id']:
                    if value and str(value) not in resources:
                        resources.append(str(value))
        
        return resources[:10]  # Limit to first 10 resources
    
    def _initialize_alert_handlers(self):
        """Initialize alert notification handlers"""
        
        self.alert_handlers = {
            AlertChannel.EMAIL: self._send_email_alert,
            AlertChannel.SLACK: self._send_slack_alert,
            AlertChannel.WEBHOOK: self._send_webhook_alert,
            AlertChannel.PAGERDUTY: self._send_pagerduty_alert
        }
    
    async def _send_email_alert(self, alert_data: Dict[str, Any], recipients: List[str]):
        """Send email alert"""
        
        # This would integrate with actual email service
        logger.info(f"Email alert sent to {recipients}: {alert_data['title']}")
    
    async def _send_slack_alert(self, alert_data: Dict[str, Any], recipients: List[str]):
        """Send Slack alert"""
        
        # This would integrate with Slack API
        logger.info(f"Slack alert sent to {recipients}: {alert_data['title']}")
    
    async def _send_webhook_alert(self, alert_data: Dict[str, Any], recipients: List[str]):
        """Send webhook alert"""
        
        # This would make HTTP POST to webhook URLs
        logger.info(f"Webhook alert sent to {recipients}: {alert_data['title']}")
    
    async def _send_pagerduty_alert(self, alert_data: Dict[str, Any], recipients: List[str]):
        """Send PagerDuty alert"""
        
        # This would integrate with PagerDuty API
        logger.info(f"PagerDuty alert sent to {recipients}: {alert_data['title']}")
    
    def _load_default_rules(self):
        """Load default compliance monitoring rules"""
        
        default_rules = [
            # GDPR Data Retention Rule
            ComplianceRule(
                rule_id="gdpr_data_retention_exceeded",
                name="GDPR Data Retention Period Exceeded",
                description="Detect data that has exceeded its retention period",
                framework=ComplianceFramework.GDPR,
                requirement=ComplianceRequirement.GDPR_ARTICLE_5,
                violation_type=ViolationType.DATA_RETENTION_EXCEEDED,
                condition_query="""
                    SELECT COUNT(*) FROM processing_records 
                    WHERE expires_at < NOW() AND status = 'active'
                """,
                threshold_value=0,
                threshold_operator=">",
                check_interval_minutes=60,
                severity=ViolationSeverity.HIGH,
                alert_channels=[AlertChannel.EMAIL, AlertChannel.SLACK],
                remediation_steps=[
                    "Review expired processing records",
                    "Execute data deletion or archival",
                    "Update retention policies if needed"
                ]
            ),
            
            # GDPR DSAR Response Overdue
            ComplianceRule(
                rule_id="gdpr_dsar_overdue",
                name="GDPR Data Subject Access Request Overdue",
                description="Detect overdue data subject access requests",
                framework=ComplianceFramework.GDPR,
                requirement=ComplianceRequirement.GDPR_ARTICLE_15,
                violation_type=ViolationType.DSAR_RESPONSE_OVERDUE,
                condition_query="""
                    SELECT request_id, data_subject_id, requested_at 
                    FROM erasure_requests 
                    WHERE requested_at < NOW() - INTERVAL '30 days' 
                    AND status IN ('pending', 'verified')
                """,
                threshold_value=0,
                threshold_operator=">",
                check_interval_minutes=240,  # Check every 4 hours
                severity=ViolationSeverity.CRITICAL,
                alert_channels=[AlertChannel.EMAIL, AlertChannel.PAGERDUTY],
                remediation_steps=[
                    "Review overdue DSAR requests",
                    "Process pending requests immediately",
                    "Notify data subjects of status"
                ]
            ),
            
            # Unauthorized Access Detection
            ComplianceRule(
                rule_id="unauthorized_access_detection",
                name="Unauthorized Access Attempts",
                description="Detect unauthorized access attempts to sensitive data",
                framework=ComplianceFramework.GDPR,
                requirement=ComplianceRequirement.GDPR_ARTICLE_32,
                violation_type=ViolationType.UNAUTHORIZED_ACCESS,
                condition_query="""
                    SELECT COUNT(*) FROM audit_logs 
                    WHERE event_type = 'access_denied' 
                    AND timestamp > NOW() - INTERVAL '1 hour'
                """,
                threshold_value=10,
                threshold_operator=">",
                check_interval_minutes=30,
                severity=ViolationSeverity.HIGH,
                alert_channels=[AlertChannel.EMAIL, AlertChannel.SLACK],
                remediation_steps=[
                    "Review access denied events",
                    "Check for potential security threats",
                    "Update access controls if needed"
                ]
            ),
            
            # Missing Consent Records
            ComplianceRule(
                rule_id="missing_consent_records",
                name="Missing Consent Records",
                description="Detect processing activities without proper consent records",
                framework=ComplianceFramework.GDPR,
                requirement=ComplianceRequirement.GDPR_ARTICLE_7,
                violation_type=ViolationType.MISSING_CONSENT,
                condition_query="""
                    SELECT record_id, data_subject_id FROM processing_records 
                    WHERE lawful_basis = 'consent' 
                    AND consent_id IS NULL 
                    AND status = 'active'
                """,
                threshold_value=0,
                threshold_operator=">",
                check_interval_minutes=120,
                severity=ViolationSeverity.MEDIUM,
                alert_channels=[AlertChannel.EMAIL],
                remediation_steps=[
                    "Review processing records without consent",
                    "Obtain proper consent or change lawful basis",
                    "Update processing records"
                ]
            ),
            
            # Audit Log Gaps
            ComplianceRule(
                rule_id="audit_log_gaps",
                name="Audit Log Gaps Detected",
                description="Detect gaps in audit logging",
                framework=ComplianceFramework.GDPR,
                requirement=ComplianceRequirement.GDPR_ARTICLE_30,
                violation_type=ViolationType.AUDIT_LOG_GAP,
                condition_query="""
                    SELECT DATE(timestamp) as log_date, COUNT(*) as log_count
                    FROM audit_logs 
                    WHERE timestamp >= NOW() - INTERVAL '7 days'
                    GROUP BY DATE(timestamp)
                    HAVING COUNT(*) < 100
                """,
                threshold_value=0,
                threshold_operator=">",
                check_interval_minutes=360,  # Check every 6 hours
                severity=ViolationSeverity.MEDIUM,
                alert_channels=[AlertChannel.EMAIL],
                remediation_steps=[
                    "Investigate audit logging system",
                    "Check for system outages or configuration issues",
                    "Ensure continuous audit logging"
                ]
            )
        ]
        
        for rule in default_rules:
            self.rules[rule.rule_id] = rule
    
    async def _store_monitoring_rule(self, rule: ComplianceRule):
        """Store monitoring rule in database"""
        try:
            query = text("""
                INSERT INTO compliance_monitoring_rules 
                (rule_id, name, description, framework, requirement, violation_type,
                 condition_query, threshold_value, threshold_operator, check_interval_minutes,
                 enabled, severity, alert_channels, alert_recipients, created_at,
                 tags, remediation_steps)
                VALUES (:rule_id, :name, :description, :framework, :requirement, :violation_type,
                        :condition_query, :threshold_value, :threshold_operator, :check_interval_minutes,
                        :enabled, :severity, :alert_channels, :alert_recipients, :created_at,
                        :tags, :remediation_steps)
            """)
            
            await self.db.execute(query, {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "description": rule.description,
                "framework": rule.framework.value,
                "requirement": rule.requirement.value,
                "violation_type": rule.violation_type.value,
                "condition_query": rule.condition_query,
                "threshold_value": rule.threshold_value,
                "threshold_operator": rule.threshold_operator,
                "check_interval_minutes": rule.check_interval_minutes,
                "enabled": rule.enabled,
                "severity": rule.severity.value,
                "alert_channels": json.dumps([ch.value for ch in rule.alert_channels]),
                "alert_recipients": json.dumps(rule.alert_recipients),
                "created_at": rule.created_at,
                "tags": json.dumps(rule.tags),
                "remediation_steps": json.dumps(rule.remediation_steps)
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to store monitoring rule {rule.rule_id}: {e}")
            await self.db.rollback()
            raise
    
    async def _update_monitoring_rule(self, rule: ComplianceRule):
        """Update monitoring rule in database"""
        try:
            query = text("""
                UPDATE compliance_monitoring_rules 
                SET name = :name,
                    description = :description,
                    condition_query = :condition_query,
                    threshold_value = :threshold_value,
                    threshold_operator = :threshold_operator,
                    check_interval_minutes = :check_interval_minutes,
                    enabled = :enabled,
                    severity = :severity,
                    alert_channels = :alert_channels,
                    alert_recipients = :alert_recipients,
                    tags = :tags,
                    remediation_steps = :remediation_steps,
                    last_checked = :last_checked,
                    last_violation = :last_violation,
                    updated_at = :updated_at
                WHERE rule_id = :rule_id
            """)
            
            await self.db.execute(query, {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "description": rule.description,
                "condition_query": rule.condition_query,
                "threshold_value": rule.threshold_value,
                "threshold_operator": rule.threshold_operator,
                "check_interval_minutes": rule.check_interval_minutes,
                "enabled": rule.enabled,
                "severity": rule.severity.value,
                "alert_channels": json.dumps([ch.value for ch in rule.alert_channels]),
                "alert_recipients": json.dumps(rule.alert_recipients),
                "tags": json.dumps(rule.tags),
                "remediation_steps": json.dumps(rule.remediation_steps),
                "last_checked": rule.last_checked,
                "last_violation": rule.last_violation,
                "updated_at": datetime.now(timezone.utc)
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to update monitoring rule {rule.rule_id}: {e}")
            await self.db.rollback()
            raise
    
    async def _store_violation(self, violation: ComplianceViolation):
        """Store violation in database"""
        try:
            query = text("""
                INSERT INTO compliance_violations 
                (violation_id, rule_id, violation_type, framework, requirement, title,
                 description, severity, detected_at, detection_query, detection_result,
                 threshold_exceeded, affected_resources, data_subjects_affected, status,
                 risk_score, business_impact, regulatory_impact, remediation_steps,
                 remediation_deadline, escalation_level)
                VALUES (:violation_id, :rule_id, :violation_type, :framework, :requirement, :title,
                        :description, :severity, :detected_at, :detection_query, :detection_result,
                        :threshold_exceeded, :affected_resources, :data_subjects_affected, :status,
                        :risk_score, :business_impact, :regulatory_impact, :remediation_steps,
                        :remediation_deadline, :escalation_level)
            """)
            
            await self.db.execute(query, {
                "violation_id": violation.violation_id,
                "rule_id": violation.rule_id,
                "violation_type": violation.violation_type.value,
                "framework": violation.framework.value,
                "requirement": violation.requirement.value,
                "title": violation.title,
                "description": violation.description,
                "severity": violation.severity.value,
                "detected_at": violation.detected_at,
                "detection_query": violation.detection_query,
                "detection_result": json.dumps(str(violation.detection_result)),
                "threshold_exceeded": violation.threshold_exceeded,
                "affected_resources": json.dumps(violation.affected_resources),
                "data_subjects_affected": json.dumps(violation.data_subjects_affected),
                "status": violation.status,
                "risk_score": violation.risk_score,
                "business_impact": violation.business_impact,
                "regulatory_impact": violation.regulatory_impact,
                "remediation_steps": json.dumps(violation.remediation_steps),
                "remediation_deadline": violation.remediation_deadline,
                "escalation_level": violation.escalation_level
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to store violation {violation.violation_id}: {e}")
            await self.db.rollback()
            raise
    
    async def _update_violation(self, violation: ComplianceViolation):
        """Update violation in database"""
        try:
            query = text("""
                UPDATE compliance_violations 
                SET status = :status,
                    assigned_to = :assigned_to,
                    resolved_at = :resolved_at,
                    resolution_notes = :resolution_notes,
                    escalation_level = :escalation_level,
                    notifications_sent = :notifications_sent,
                    updated_at = :updated_at
                WHERE violation_id = :violation_id
            """)
            
            await self.db.execute(query, {
                "violation_id": violation.violation_id,
                "status": violation.status,
                "assigned_to": violation.assigned_to,
                "resolved_at": violation.resolved_at,
                "resolution_notes": violation.resolution_notes,
                "escalation_level": violation.escalation_level,
                "notifications_sent": json.dumps(violation.notifications_sent),
                "updated_at": datetime.now(timezone.utc)
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to update violation {violation.violation_id}: {e}")
            await self.db.rollback()
            raise
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load compliance monitoring configuration"""
        
        default_config = {
            "monitoring_interval_seconds": 300,  # 5 minutes
            "auto_start_monitoring": True,
            "alert_settings": {
                "email_smtp_server": "localhost",
                "slack_webhook_url": "",
                "pagerduty_api_key": ""
            },
            "violation_retention_days": 2555,  # 7 years
            "escalation_enabled": True
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r') as f:
                    import yaml
                    config = yaml.safe_load(f)
                    default_config.update(config)
            except Exception as e:
                logger.error(f"Failed to load monitoring config from {config_path}: {e}")
        
        return default_config


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    from unittest.mock import AsyncMock
    
    async def test_compliance_monitoring():
        # Mock database session
        mock_db = AsyncMock()
        
        # Mock query results
        mock_db.execute.return_value.fetchall.return_value = [(5,)]  # Simulate 5 violations found
        
        # Create monitoring system
        monitor = ComplianceMonitoringSystem(mock_db)
        
        # Test rule execution
        rule_id = "gdpr_data_retention_exceeded"
        violation = await monitor.execute_rule_check(rule_id)
        
        if violation:
            print(f"Violation detected: {violation.violation_id} - {violation.title}")
            print(f"Severity: {violation.severity.value}")
            print(f"Risk Score: {violation.risk_score}")
        
        # Test violation resolution
        if violation:
            resolved_violation = await monitor.resolve_violation(
                violation.violation_id,
                "Data retention policies updated and expired data deleted",
                "admin@voicehive.com"
            )
            print(f"Violation resolved: {resolved_violation.violation_id}")
        
        # Test dashboard generation
        dashboard = await monitor.generate_monitoring_dashboard()
        print(f"Dashboard: {dashboard.total_violations} total violations")
        print(f"Overall compliance score: {dashboard.overall_compliance_score:.2f}")
        
        # Test violation report
        report = await monitor.get_violation_report(
            framework=ComplianceFramework.GDPR,
            severity=ViolationSeverity.HIGH,
            days_back=30
        )
        print(f"Violation report: {report['summary']['total_violations']} violations")
        
        # Stop monitoring
        monitor.stop_monitoring()
        
        print("Compliance monitoring test completed successfully")
    
    # Run test
    asyncio.run(test_compliance_monitoring())