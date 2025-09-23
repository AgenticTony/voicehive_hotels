"""
Secret Lifecycle Management System
Comprehensive management of secret lifecycle from creation to retirement
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

import hvac
from prometheus_client import Counter, Histogram, Gauge, Info

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger
from secrets_manager import SecretsManager, SecretType, SecretStatus, SecretMetadata

# Configure logging
logger = get_safe_logger("orchestrator.secret_lifecycle")
audit_logger = AuditLogger("secret_lifecycle")

# Metrics
secret_lifecycle_events = Counter('voicehive_secret_lifecycle_events_total', 
                                 'Secret lifecycle events', ['event_type', 'secret_type'])
secret_expiry_notifications = Counter('voicehive_secret_expiry_notifications_total',
                                    'Secret expiry notifications sent', ['notification_type', 'days_to_expiry'])
secret_compliance_violations = Counter('voicehive_secret_compliance_violations_total',
                                     'Secret compliance violations', ['violation_type', 'secret_type'])
secret_age_histogram = Histogram('voicehive_secret_age_days', 'Age of secrets in days', ['secret_type'])
active_secrets_gauge = Gauge('voicehive_active_secrets_total', 'Total active secrets', ['secret_type'])
secret_lifecycle_info = Info('voicehive_secret_lifecycle_manager', 'Secret lifecycle manager information')


class LifecycleEvent(str, Enum):
    """Secret lifecycle events"""
    CREATED = "created"
    ACTIVATED = "activated"
    ACCESSED = "accessed"
    ROTATED = "rotated"
    DEPRECATED = "deprecated"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ARCHIVED = "archived"
    PURGED = "purged"


class ComplianceRule(str, Enum):
    """Compliance rules for secrets"""
    MAX_AGE_DAYS = "max_age_days"
    MIN_ROTATION_FREQUENCY = "min_rotation_frequency"
    REQUIRED_ENCRYPTION = "required_encryption"
    ACCESS_LOGGING = "access_logging"
    BACKUP_REQUIRED = "backup_required"
    GEOGRAPHIC_RESTRICTION = "geographic_restriction"


class NotificationType(str, Enum):
    """Types of lifecycle notifications"""
    EXPIRY_WARNING = "expiry_warning"
    ROTATION_DUE = "rotation_due"
    COMPLIANCE_VIOLATION = "compliance_violation"
    EMERGENCY_ALERT = "emergency_alert"
    LIFECYCLE_MILESTONE = "lifecycle_milestone"


@dataclass
class LifecyclePolicy:
    """Policy for secret lifecycle management"""
    secret_type: SecretType
    max_age_days: int
    rotation_warning_days: int
    auto_rotation_enabled: bool
    backup_retention_days: int
    compliance_rules: List[ComplianceRule]
    notification_recipients: List[str]
    geographic_restrictions: List[str]
    encryption_required: bool
    access_audit_required: bool


@dataclass
class LifecycleEvent:
    """Represents a lifecycle event"""
    event_id: str
    secret_id: str
    event_type: LifecycleEvent
    timestamp: datetime
    actor: str
    details: Dict[str, Any]
    compliance_impact: Optional[str]


@dataclass
class ExpiryNotification:
    """Notification for secret expiry"""
    notification_id: str
    secret_id: str
    secret_type: SecretType
    days_to_expiry: int
    notification_type: NotificationType
    recipients: List[str]
    sent_at: Optional[datetime]
    acknowledged: bool


class SecretLifecycleManager:
    """
    Comprehensive secret lifecycle management with compliance tracking
    """
    
    def __init__(self, secrets_manager: SecretsManager, vault_client: hvac.Client, config: Dict[str, Any]):
        self.secrets_manager = secrets_manager
        self.vault_client = vault_client
        self.config = config
        
        # Lifecycle policies
        self.policies: Dict[SecretType, LifecyclePolicy] = {}
        self._load_lifecycle_policies()
        
        # Event tracking
        self.lifecycle_events_path = config.get('lifecycle_events_path', 'voicehive/lifecycle/events')
        self.notifications_path = config.get('notifications_path', 'voicehive/lifecycle/notifications')
        
        # Background tasks
        self._monitoring_task: Optional[asyncio.Task] = None
        self._notification_task: Optional[asyncio.Task] = None
        self._compliance_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Notification handlers
        self._notification_handlers: Dict[NotificationType, callable] = {}
        self._register_default_notification_handlers()
    
    def _load_lifecycle_policies(self):
        """Load lifecycle policies for different secret types"""
        
        # Default policies based on security best practices
        default_policies = {
            SecretType.DATABASE_PASSWORD: LifecyclePolicy(
                secret_type=SecretType.DATABASE_PASSWORD,
                max_age_days=90,
                rotation_warning_days=7,
                auto_rotation_enabled=True,
                backup_retention_days=30,
                compliance_rules=[
                    ComplianceRule.MAX_AGE_DAYS,
                    ComplianceRule.MIN_ROTATION_FREQUENCY,
                    ComplianceRule.REQUIRED_ENCRYPTION,
                    ComplianceRule.ACCESS_LOGGING
                ],
                notification_recipients=['security@voicehive.com', 'devops@voicehive.com'],
                geographic_restrictions=['EU'],
                encryption_required=True,
                access_audit_required=True
            ),
            
            SecretType.JWT_SECRET: LifecyclePolicy(
                secret_type=SecretType.JWT_SECRET,
                max_age_days=30,
                rotation_warning_days=3,
                auto_rotation_enabled=True,
                backup_retention_days=7,
                compliance_rules=[
                    ComplianceRule.MAX_AGE_DAYS,
                    ComplianceRule.MIN_ROTATION_FREQUENCY,
                    ComplianceRule.REQUIRED_ENCRYPTION
                ],
                notification_recipients=['security@voicehive.com'],
                geographic_restrictions=['EU'],
                encryption_required=True,
                access_audit_required=True
            ),
            
            SecretType.API_KEY: LifecyclePolicy(
                secret_type=SecretType.API_KEY,
                max_age_days=180,
                rotation_warning_days=14,
                auto_rotation_enabled=False,  # Manual rotation for API keys
                backup_retention_days=90,
                compliance_rules=[
                    ComplianceRule.MAX_AGE_DAYS,
                    ComplianceRule.ACCESS_LOGGING,
                    ComplianceRule.BACKUP_REQUIRED
                ],
                notification_recipients=['api-team@voicehive.com'],
                geographic_restrictions=['EU'],
                encryption_required=True,
                access_audit_required=True
            ),
            
            SecretType.ENCRYPTION_KEY: LifecyclePolicy(
                secret_type=SecretType.ENCRYPTION_KEY,
                max_age_days=365,
                rotation_warning_days=30,
                auto_rotation_enabled=True,
                backup_retention_days=1095,  # 3 years for encryption keys
                compliance_rules=[
                    ComplianceRule.MAX_AGE_DAYS,
                    ComplianceRule.MIN_ROTATION_FREQUENCY,
                    ComplianceRule.REQUIRED_ENCRYPTION,
                    ComplianceRule.BACKUP_REQUIRED,
                    ComplianceRule.GEOGRAPHIC_RESTRICTION
                ],
                notification_recipients=['security@voicehive.com', 'compliance@voicehive.com'],
                geographic_restrictions=['EU'],
                encryption_required=True,
                access_audit_required=True
            ),
            
            SecretType.TLS_CERTIFICATE: LifecyclePolicy(
                secret_type=SecretType.TLS_CERTIFICATE,
                max_age_days=90,  # Short-lived certificates
                rotation_warning_days=14,
                auto_rotation_enabled=True,
                backup_retention_days=30,
                compliance_rules=[
                    ComplianceRule.MAX_AGE_DAYS,
                    ComplianceRule.MIN_ROTATION_FREQUENCY,
                    ComplianceRule.BACKUP_REQUIRED
                ],
                notification_recipients=['devops@voicehive.com'],
                geographic_restrictions=['EU'],
                encryption_required=False,  # Certificates are public
                access_audit_required=True
            )
        }
        
        self.policies = default_policies
    
    def _register_default_notification_handlers(self):
        """Register default notification handlers"""
        self._notification_handlers[NotificationType.EXPIRY_WARNING] = self._handle_expiry_warning
        self._notification_handlers[NotificationType.ROTATION_DUE] = self._handle_rotation_due
        self._notification_handlers[NotificationType.COMPLIANCE_VIOLATION] = self._handle_compliance_violation
        self._notification_handlers[NotificationType.EMERGENCY_ALERT] = self._handle_emergency_alert
    
    async def initialize(self) -> bool:
        """Initialize the lifecycle manager"""
        try:
            # Verify Vault connection
            if not self.vault_client.is_authenticated():
                logger.error("vault_authentication_failed")
                return False
            
            # Ensure required paths exist
            await self._ensure_vault_paths()
            
            # Start background tasks
            await self._start_background_tasks()
            
            # Set manager info
            secret_lifecycle_info.info({
                'version': '1.0.0',
                'policies_loaded': str(len(self.policies)),
                'initialized_at': datetime.now(timezone.utc).isoformat()
            })
            
            audit_logger.log_security_event(
                event_type="lifecycle_manager_initialized",
                details={"policies_count": len(self.policies)},
                severity="info"
            )
            
            logger.info("secret_lifecycle_manager_initialized")
            return True
            
        except Exception as e:
            logger.error("lifecycle_manager_initialization_failed", error=str(e))
            return False
    
    async def record_lifecycle_event(self, 
                                   secret_id: str,
                                   event_type: LifecycleEvent,
                                   actor: str,
                                   details: Optional[Dict[str, Any]] = None) -> str:
        """Record a lifecycle event"""
        
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Get secret metadata to determine type
        metadata = await self.secrets_manager._get_secret_metadata(secret_id)
        secret_type = metadata.secret_type if metadata else SecretType.GENERIC_SECRET
        
        # Check compliance impact
        compliance_impact = await self._assess_compliance_impact(secret_id, event_type, details)
        
        # Create lifecycle event
        lifecycle_event = LifecycleEvent(
            event_id=event_id,
            secret_id=secret_id,
            event_type=event_type,
            timestamp=now,
            actor=actor,
            details=details or {},
            compliance_impact=compliance_impact
        )
        
        try:
            # Store event in Vault
            event_path = f"{self.lifecycle_events_path}/{event_id}"
            event_data = asdict(lifecycle_event)
            event_data['timestamp'] = event_data['timestamp'].isoformat()
            
            self.vault_client.secrets.kv.v2.create_or_update_secret(
                path=event_path,
                secret=event_data
            )
            
            # Update metrics
            secret_lifecycle_events.labels(
                event_type=event_type.value,
                secret_type=secret_type.value
            ).inc()
            
            # Audit log
            audit_logger.log_security_event(
                event_type="lifecycle_event_recorded",
                details={
                    "event_id": event_id,
                    "secret_id": secret_id,
                    "event_type": event_type.value,
                    "actor": actor,
                    "compliance_impact": compliance_impact
                },
                severity="info"
            )
            
            logger.info("lifecycle_event_recorded", 
                       event_id=event_id, 
                       event_type=event_type.value)
            
            return event_id
            
        except Exception as e:
            logger.error("lifecycle_event_recording_failed", 
                        event_id=event_id, error=str(e))
            raise
    
    async def get_secret_lifecycle_history(self, secret_id: str) -> List[LifecycleEvent]:
        """Get complete lifecycle history for a secret"""
        
        try:
            # List all events
            events_response = self.vault_client.secrets.kv.v2.list_secrets(
                path=self.lifecycle_events_path
            )
            event_ids = events_response['data']['keys']
            
            # Filter events for this secret
            secret_events = []
            
            for event_id in event_ids:
                try:
                    event_path = f"{self.lifecycle_events_path}/{event_id}"
                    event_response = self.vault_client.secrets.kv.v2.read_secret_version(
                        path=event_path
                    )
                    event_data = event_response['data']['data']
                    
                    if event_data.get('secret_id') == secret_id:
                        # Convert timestamp back to datetime
                        event_data['timestamp'] = datetime.fromisoformat(event_data['timestamp'])
                        event_data['event_type'] = LifecycleEvent(event_data['event_type'])
                        
                        secret_events.append(LifecycleEvent(**event_data))
                        
                except Exception as e:
                    logger.warning("failed_to_read_lifecycle_event", 
                                 event_id=event_id, error=str(e))
                    continue
            
            # Sort by timestamp
            secret_events.sort(key=lambda e: e.timestamp)
            
            return secret_events
            
        except Exception as e:
            logger.error("lifecycle_history_retrieval_failed", 
                        secret_id=secret_id, error=str(e))
            return []
    
    async def check_secret_compliance(self, secret_id: str) -> Dict[str, Any]:
        """Check compliance status of a secret"""
        
        compliance_report = {
            "secret_id": secret_id,
            "compliant": True,
            "violations": [],
            "warnings": [],
            "last_checked": datetime.now(timezone.utc).isoformat()
        }
        
        try:
            # Get secret metadata
            metadata = await self.secrets_manager._get_secret_metadata(secret_id)
            if not metadata:
                compliance_report["violations"].append("Secret metadata not found")
                compliance_report["compliant"] = False
                return compliance_report
            
            # Get policy for this secret type
            policy = self.policies.get(metadata.secret_type)
            if not policy:
                compliance_report["warnings"].append("No policy defined for secret type")
                return compliance_report
            
            now = datetime.now(timezone.utc)
            
            # Check age compliance
            if ComplianceRule.MAX_AGE_DAYS in policy.compliance_rules:
                age_days = (now - metadata.created_at).days
                
                if age_days > policy.max_age_days:
                    compliance_report["violations"].append(
                        f"Secret age ({age_days} days) exceeds maximum ({policy.max_age_days} days)"
                    )
                    compliance_report["compliant"] = False
                elif age_days > (policy.max_age_days - policy.rotation_warning_days):
                    compliance_report["warnings"].append(
                        f"Secret approaching age limit ({age_days}/{policy.max_age_days} days)"
                    )
            
            # Check rotation frequency
            if ComplianceRule.MIN_ROTATION_FREQUENCY in policy.compliance_rules:
                if metadata.last_rotated:
                    days_since_rotation = (now - metadata.last_rotated).days
                    if days_since_rotation > policy.max_age_days:
                        compliance_report["violations"].append(
                            f"Secret not rotated for {days_since_rotation} days"
                        )
                        compliance_report["compliant"] = False
                else:
                    # Never rotated
                    age_days = (now - metadata.created_at).days
                    if age_days > policy.max_age_days:
                        compliance_report["violations"].append(
                            "Secret has never been rotated and exceeds age limit"
                        )
                        compliance_report["compliant"] = False
            
            # Check geographic restrictions
            if ComplianceRule.GEOGRAPHIC_RESTRICTION in policy.compliance_rules:
                # This would check where the secret is stored/accessed
                # For now, assume compliance based on Vault configuration
                pass
            
            # Check encryption requirements
            if ComplianceRule.REQUIRED_ENCRYPTION in policy.compliance_rules:
                if not policy.encryption_required:
                    compliance_report["violations"].append(
                        "Encryption required but not configured"
                    )
                    compliance_report["compliant"] = False
            
            # Update metrics
            if not compliance_report["compliant"]:
                for violation in compliance_report["violations"]:
                    secret_compliance_violations.labels(
                        violation_type="policy_violation",
                        secret_type=metadata.secret_type.value
                    ).inc()
            
            return compliance_report
            
        except Exception as e:
            logger.error("compliance_check_failed", secret_id=secret_id, error=str(e))
            compliance_report["violations"].append(f"Compliance check failed: {str(e)}")
            compliance_report["compliant"] = False
            return compliance_report
    
    async def generate_lifecycle_report(self, 
                                      secret_type: Optional[SecretType] = None,
                                      include_history: bool = False) -> Dict[str, Any]:
        """Generate comprehensive lifecycle report"""
        
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "secret_type_filter": secret_type.value if secret_type else "all",
            "summary": {
                "total_secrets": 0,
                "active_secrets": 0,
                "expired_secrets": 0,
                "compliant_secrets": 0,
                "non_compliant_secrets": 0
            },
            "secrets": [],
            "compliance_summary": {},
            "recommendations": []
        }
        
        try:
            # Get all secret metadata
            all_metadata = await self.secrets_manager._get_all_secret_metadata()
            
            # Filter by type if specified
            if secret_type:
                all_metadata = [m for m in all_metadata if m.secret_type == secret_type]
            
            report["summary"]["total_secrets"] = len(all_metadata)
            
            # Analyze each secret
            for metadata in all_metadata:
                secret_info = {
                    "secret_id": metadata.secret_id,
                    "secret_type": metadata.secret_type.value,
                    "status": metadata.status.value,
                    "created_at": metadata.created_at.isoformat(),
                    "age_days": (datetime.now(timezone.utc) - metadata.created_at).days,
                    "last_rotated": metadata.last_rotated.isoformat() if metadata.last_rotated else None,
                    "rotation_count": metadata.rotation_count,
                    "compliance": await self.check_secret_compliance(metadata.secret_id)
                }
                
                # Include history if requested
                if include_history:
                    history = await self.get_secret_lifecycle_history(metadata.secret_id)
                    secret_info["lifecycle_events"] = [
                        {
                            "event_type": event.event_type.value,
                            "timestamp": event.timestamp.isoformat(),
                            "actor": event.actor
                        }
                        for event in history
                    ]
                
                report["secrets"].append(secret_info)
                
                # Update summary counters
                if metadata.status == SecretStatus.ACTIVE:
                    report["summary"]["active_secrets"] += 1
                elif metadata.status == SecretStatus.EXPIRED:
                    report["summary"]["expired_secrets"] += 1
                
                if secret_info["compliance"]["compliant"]:
                    report["summary"]["compliant_secrets"] += 1
                else:
                    report["summary"]["non_compliant_secrets"] += 1
                
                # Update age histogram
                secret_age_histogram.labels(
                    secret_type=metadata.secret_type.value
                ).observe(secret_info["age_days"])
            
            # Generate recommendations
            report["recommendations"] = await self._generate_recommendations(report)
            
            # Update active secrets gauge
            for secret_type_enum in SecretType:
                count = len([s for s in report["secrets"] 
                           if s["secret_type"] == secret_type_enum.value and s["status"] == "active"])
                active_secrets_gauge.labels(secret_type=secret_type_enum.value).set(count)
            
            return report
            
        except Exception as e:
            logger.error("lifecycle_report_generation_failed", error=str(e))
            report["error"] = str(e)
            return report
    
    async def _assess_compliance_impact(self, 
                                      secret_id: str, 
                                      event_type: LifecycleEvent, 
                                      details: Optional[Dict[str, Any]]) -> Optional[str]:
        """Assess compliance impact of a lifecycle event"""
        
        # Get secret metadata
        metadata = await self.secrets_manager._get_secret_metadata(secret_id)
        if not metadata:
            return None
        
        # Get policy
        policy = self.policies.get(metadata.secret_type)
        if not policy:
            return None
        
        # Assess impact based on event type
        if event_type == LifecycleEvent.EXPIRED:
            return "high"  # Expired secrets are high compliance impact
        elif event_type == LifecycleEvent.ROTATED:
            return "positive"  # Rotation improves compliance
        elif event_type == LifecycleEvent.ACCESSED:
            # Check if access is from authorized location
            source_ip = details.get('source_ip') if details else None
            if source_ip and not self._is_authorized_location(source_ip):
                return "medium"  # Unauthorized location access
        
        return None
    
    def _is_authorized_location(self, source_ip: str) -> bool:
        """Check if source IP is from authorized location"""
        # This would implement geolocation checking
        # For now, assume all IPs are authorized
        return True
    
    async def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on lifecycle report"""
        
        recommendations = []
        
        # Check compliance ratio
        total = report["summary"]["total_secrets"]
        non_compliant = report["summary"]["non_compliant_secrets"]
        
        if total > 0:
            compliance_ratio = (total - non_compliant) / total
            
            if compliance_ratio < 0.8:
                recommendations.append(
                    f"Compliance ratio is {compliance_ratio:.1%}. "
                    "Consider implementing automated rotation for more secret types."
                )
        
        # Check for old secrets
        old_secrets = [s for s in report["secrets"] if s["age_days"] > 180]
        if old_secrets:
            recommendations.append(
                f"{len(old_secrets)} secrets are older than 180 days. "
                "Review and rotate these secrets."
            )
        
        # Check rotation frequency
        never_rotated = [s for s in report["secrets"] if s["last_rotated"] is None and s["age_days"] > 30]
        if never_rotated:
            recommendations.append(
                f"{len(never_rotated)} secrets have never been rotated. "
                "Implement rotation schedules for these secrets."
            )
        
        return recommendations
    
    async def _start_background_tasks(self):
        """Start background monitoring tasks"""
        self._running = True
        
        self._monitoring_task = asyncio.create_task(self._lifecycle_monitoring_worker())
        self._notification_task = asyncio.create_task(self._notification_worker())
        self._compliance_task = asyncio.create_task(self._compliance_monitoring_worker())
    
    async def _lifecycle_monitoring_worker(self):
        """Background worker to monitor secret lifecycle"""
        while self._running:
            try:
                # Check for secrets approaching expiry
                await self._check_expiring_secrets()
                
                # Check for secrets needing rotation
                await self._check_rotation_due()
                
                await asyncio.sleep(3600)  # Check every hour
                
            except Exception as e:
                logger.error("lifecycle_monitoring_error", error=str(e))
                await asyncio.sleep(300)
    
    async def _notification_worker(self):
        """Background worker to send notifications"""
        while self._running:
            try:
                # Process pending notifications
                await self._process_pending_notifications()
                
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error("notification_worker_error", error=str(e))
                await asyncio.sleep(60)
    
    async def _compliance_monitoring_worker(self):
        """Background worker to monitor compliance"""
        while self._running:
            try:
                # Run compliance checks
                await self._run_compliance_checks()
                
                await asyncio.sleep(86400)  # Check daily
                
            except Exception as e:
                logger.error("compliance_monitoring_error", error=str(e))
                await asyncio.sleep(3600)
    
    async def _check_expiring_secrets(self):
        """Check for secrets approaching expiry"""
        
        all_metadata = await self.secrets_manager._get_all_secret_metadata()
        now = datetime.now(timezone.utc)
        
        for metadata in all_metadata:
            if not metadata.expires_at:
                continue
            
            days_to_expiry = (metadata.expires_at - now).days
            
            # Get policy for warning thresholds
            policy = self.policies.get(metadata.secret_type)
            if not policy:
                continue
            
            # Check if warning notification needed
            if 0 <= days_to_expiry <= policy.rotation_warning_days:
                await self._create_expiry_notification(metadata, days_to_expiry)
    
    async def _create_expiry_notification(self, metadata: SecretMetadata, days_to_expiry: int):
        """Create expiry notification"""
        
        notification_id = str(uuid.uuid4())
        
        notification = ExpiryNotification(
            notification_id=notification_id,
            secret_id=metadata.secret_id,
            secret_type=metadata.secret_type,
            days_to_expiry=days_to_expiry,
            notification_type=NotificationType.EXPIRY_WARNING,
            recipients=self.policies[metadata.secret_type].notification_recipients,
            sent_at=None,
            acknowledged=False
        )
        
        # Store notification
        notification_path = f"{self.notifications_path}/{notification_id}"
        notification_data = asdict(notification)
        
        self.vault_client.secrets.kv.v2.create_or_update_secret(
            path=notification_path,
            secret=notification_data
        )
        
        # Update metrics
        secret_expiry_notifications.labels(
            notification_type=notification.notification_type.value,
            days_to_expiry=str(days_to_expiry)
        ).inc()
        
        logger.info("expiry_notification_created", 
                   notification_id=notification_id,
                   secret_id=metadata.secret_id,
                   days_to_expiry=days_to_expiry)
    
    async def _handle_expiry_warning(self, notification: ExpiryNotification):
        """Handle expiry warning notification"""
        
        message = f"""
        Secret Expiry Warning
        
        Secret ID: {notification.secret_id}
        Secret Type: {notification.secret_type.value}
        Days to Expiry: {notification.days_to_expiry}
        
        Action Required: Rotate this secret before it expires.
        """
        
        # Send notification (implementation would depend on notification system)
        logger.warning("secret_expiry_warning", 
                      secret_id=notification.secret_id,
                      days_to_expiry=notification.days_to_expiry)
    
    async def shutdown(self):
        """Shutdown the lifecycle manager"""
        self._running = False
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
        if self._notification_task:
            self._notification_task.cancel()
        if self._compliance_task:
            self._compliance_task.cancel()
        
        logger.info("secret_lifecycle_manager_shutdown")


# Global lifecycle manager instance
_lifecycle_manager: Optional[SecretLifecycleManager] = None


def get_lifecycle_manager() -> Optional[SecretLifecycleManager]:
    """Get the global lifecycle manager instance"""
    return _lifecycle_manager


async def initialize_lifecycle_manager(secrets_manager: SecretsManager, 
                                     vault_client: hvac.Client, 
                                     config: Dict[str, Any]) -> SecretLifecycleManager:
    """Initialize the global lifecycle manager"""
    global _lifecycle_manager
    
    _lifecycle_manager = SecretLifecycleManager(secrets_manager, vault_client, config)
    
    if await _lifecycle_manager.initialize():
        return _lifecycle_manager
    else:
        raise RuntimeError("Failed to initialize secret lifecycle manager")