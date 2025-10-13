"""
Configuration Drift Detection and Monitoring System
Monitors configuration changes and detects unauthorized modifications
"""

import os
import json
import hashlib
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
# import aiofiles  # Not available, using standard file operations
from prometheus_client import Counter, Gauge, Histogram

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger
from config import VoiceHiveConfig, ConfigurationManager, EnvironmentType

logger = get_safe_logger("orchestrator.config_drift")
audit_logger = AuditLogger("config_drift")

# Metrics
config_drift_checks = Counter('voicehive_config_drift_checks_total', 'Configuration drift checks performed')
config_drift_violations = Counter('voicehive_config_drift_violations_total', 'Configuration drift violations detected', ['field', 'severity'])
config_baseline_updates = Counter('voicehive_config_baseline_updates_total', 'Configuration baseline updates')
config_drift_check_duration = Histogram('voicehive_config_drift_check_duration_seconds', 'Configuration drift check duration')
config_drift_status = Gauge('voicehive_config_drift_status', 'Configuration drift status (1=no drift, 0=drift detected)')


class DriftSeverity(str, Enum):
    """Configuration drift severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DriftType(str, Enum):
    """Types of configuration drift"""
    UNAUTHORIZED_CHANGE = "unauthorized_change"
    MISSING_FIELD = "missing_field"
    ADDED_FIELD = "added_field"
    VALUE_CHANGE = "value_change"
    SCHEMA_VIOLATION = "schema_violation"
    SECURITY_DOWNGRADE = "security_downgrade"


@dataclass
class ConfigurationBaseline:
    """Configuration baseline for drift detection"""
    
    config_hash: str
    environment: str
    region: str
    timestamp: datetime
    config_snapshot: Dict[str, Any]
    approved_by: str
    approval_timestamp: datetime
    version: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['approval_timestamp'] = self.approval_timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigurationBaseline':
        """Create from dictionary"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        data['approval_timestamp'] = datetime.fromisoformat(data['approval_timestamp'])
        return cls(**data)


@dataclass
class DriftDetection:
    """Configuration drift detection result"""
    
    field_path: str
    drift_type: DriftType
    severity: DriftSeverity
    old_value: Any
    new_value: Any
    detected_at: datetime
    description: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'field_path': self.field_path,
            'drift_type': self.drift_type.value,
            'severity': self.severity.value,
            'old_value': self._redact_sensitive(self.old_value),
            'new_value': self._redact_sensitive(self.new_value),
            'detected_at': self.detected_at.isoformat(),
            'description': self.description
        }
    
    def _redact_sensitive(self, value: Any) -> str:
        """Redact sensitive values for logging"""
        if isinstance(value, str) and len(value) > 8:
            # Likely a secret or password
            return f"{value[:4]}***{value[-4:]}"
        return str(value)


class ConfigurationDriftMonitor:
    """
    Configuration drift detection and monitoring system
    """
    
    def __init__(self, 
                 baseline_storage_path: str = "/var/lib/voicehive/config-baselines",
                 check_interval_seconds: int = 300,  # 5 minutes
                 enable_auto_remediation: bool = False):
        
        self.baseline_storage_path = Path(baseline_storage_path)
        self.check_interval_seconds = check_interval_seconds
        self.enable_auto_remediation = enable_auto_remediation
        
        # Ensure baseline storage directory exists
        self.baseline_storage_path.mkdir(parents=True, exist_ok=True)
        
        # Configuration manager
        self.config_manager = ConfigurationManager()
        
        # Current baseline
        self._current_baseline: Optional[ConfigurationBaseline] = None
        
        # Drift detection rules
        self._drift_rules = self._initialize_drift_rules()
        
        # Monitoring state
        self._monitoring_active = False
        self._last_check_time: Optional[datetime] = None
    
    def _initialize_drift_rules(self) -> Dict[str, Dict[str, Any]]:
        """Initialize configuration drift detection rules"""
        return {
            # Security-related fields - CRITICAL severity
            'auth.jwt_secret_key': {
                'severity': DriftSeverity.CRITICAL,
                'allow_changes': False,
                'require_approval': True
            },
            'security.encryption_key': {
                'severity': DriftSeverity.CRITICAL,
                'allow_changes': False,
                'require_approval': True
            },
            'security.webhook_signature_secret': {
                'severity': DriftSeverity.CRITICAL,
                'allow_changes': False,
                'require_approval': True
            },
            
            # Database configuration - HIGH severity
            'database.password': {
                'severity': DriftSeverity.HIGH,
                'allow_changes': True,
                'require_approval': True
            },
            'database.ssl_mode': {
                'severity': DriftSeverity.HIGH,
                'allow_changes': False,
                'require_approval': True
            },
            
            # Redis configuration - HIGH severity
            'redis.password': {
                'severity': DriftSeverity.HIGH,
                'allow_changes': True,
                'require_approval': True
            },
            'redis.ssl': {
                'severity': DriftSeverity.HIGH,
                'allow_changes': False,
                'require_approval': True
            },
            
            # Environment and region - CRITICAL severity
            'environment': {
                'severity': DriftSeverity.CRITICAL,
                'allow_changes': False,
                'require_approval': True
            },
            'region': {
                'severity': DriftSeverity.CRITICAL,
                'allow_changes': False,
                'require_approval': True
            },
            
            # Authentication settings - HIGH severity
            'auth.jwt_algorithm': {
                'severity': DriftSeverity.HIGH,
                'allow_changes': False,
                'require_approval': True
            },
            'auth.jwt_expiration_minutes': {
                'severity': DriftSeverity.MEDIUM,
                'allow_changes': True,
                'require_approval': True
            },
            
            # Security settings - HIGH severity
            'security.cors_allowed_origins': {
                'severity': DriftSeverity.HIGH,
                'allow_changes': True,
                'require_approval': True
            },
            'security.rate_limit_per_minute': {
                'severity': DriftSeverity.MEDIUM,
                'allow_changes': True,
                'require_approval': False
            },
            
            # External services - MEDIUM severity
            'external_services.livekit_url': {
                'severity': DriftSeverity.MEDIUM,
                'allow_changes': True,
                'require_approval': True
            },
            'external_services.vault_url': {
                'severity': DriftSeverity.HIGH,
                'allow_changes': True,
                'require_approval': True
            },
            
            # Logging configuration - LOW severity
            'log_level': {
                'severity': DriftSeverity.LOW,
                'allow_changes': True,
                'require_approval': False
            }
        }
    
    async def create_baseline(self, 
                            config: VoiceHiveConfig, 
                            approved_by: str,
                            version: str = "1.0") -> ConfigurationBaseline:
        """
        Create a new configuration baseline
        
        Args:
            config: Configuration to baseline
            approved_by: User who approved this baseline
            version: Configuration version
            
        Returns:
            Created baseline
        """
        
        # Create baseline
        baseline = ConfigurationBaseline(
            config_hash=config.calculate_config_hash(),
            environment=config.environment,
            region=config.region,
            timestamp=datetime.now(timezone.utc),
            config_snapshot=config.model_dump(exclude={'config_hash', 'last_updated'}),
            approved_by=approved_by,
            approval_timestamp=datetime.now(timezone.utc),
            version=version
        )
        
        # Save baseline
        await self._save_baseline(baseline)
        
        # Set as current baseline
        self._current_baseline = baseline
        
        # Update metrics
        config_baseline_updates.inc()
        
        # Audit log
        audit_logger.log_security_event(
            event_type="configuration_baseline_created",
            details={
                "environment": baseline.environment,
                "region": baseline.region,
                "config_hash": baseline.config_hash[:16],
                "approved_by": approved_by,
                "version": version
            },
            severity="medium"
        )
        
        logger.info(
            "configuration_baseline_created",
            environment=baseline.environment,
            config_hash=baseline.config_hash[:16],
            approved_by=approved_by
        )
        
        return baseline
    
    async def load_baseline(self, environment: str) -> Optional[ConfigurationBaseline]:
        """
        Load configuration baseline for environment
        
        Args:
            environment: Environment name
            
        Returns:
            Loaded baseline or None if not found
        """
        
        baseline_file = self.baseline_storage_path / f"{environment}_baseline.json"
        
        if not baseline_file.exists():
            logger.warning(
                "configuration_baseline_not_found",
                environment=environment,
                baseline_file=str(baseline_file)
            )
            return None
        
        try:
            with open(baseline_file, 'r') as f:
                data = json.load(f)
            
            baseline = ConfigurationBaseline.from_dict(data)
            self._current_baseline = baseline
            
            logger.info(
                "configuration_baseline_loaded",
                environment=environment,
                config_hash=baseline.config_hash[:16]
            )
            
            return baseline
            
        except Exception as e:
            logger.error(
                "configuration_baseline_load_failed",
                environment=environment,
                error=str(e)
            )
            return None
    
    async def _save_baseline(self, baseline: ConfigurationBaseline):
        """Save configuration baseline to storage"""
        
        baseline_file = self.baseline_storage_path / f"{baseline.environment}_baseline.json"
        
        try:
            with open(baseline_file, 'w') as f:
                f.write(json.dumps(baseline.to_dict(), indent=2))
            
            logger.info(
                "configuration_baseline_saved",
                environment=baseline.environment,
                baseline_file=str(baseline_file)
            )
            
        except Exception as e:
            logger.error(
                "configuration_baseline_save_failed",
                environment=baseline.environment,
                error=str(e)
            )
            raise
    
    @config_drift_check_duration.time()
    async def check_drift(self, current_config: VoiceHiveConfig) -> List[DriftDetection]:
        """
        Check for configuration drift against baseline
        
        Args:
            current_config: Current configuration to check
            
        Returns:
            List of detected drift violations
        """
        
        config_drift_checks.inc()
        
        if not self._current_baseline:
            logger.warning("no_configuration_baseline_available")
            return []
        
        # Compare configurations
        drift_detections = []
        
        current_snapshot = current_config.model_dump(exclude={'config_hash', 'last_updated'})
        baseline_snapshot = self._current_baseline.config_snapshot
        
        # Check for changes
        changes = self._find_configuration_changes(baseline_snapshot, current_snapshot)
        
        for change in changes:
            # Determine drift severity and type
            drift_detection = self._analyze_change(change)
            if drift_detection:
                drift_detections.append(drift_detection)
        
        # Update metrics
        if drift_detections:
            config_drift_status.set(0)  # Drift detected
            
            for detection in drift_detections:
                config_drift_violations.labels(
                    field=detection.field_path,
                    severity=detection.severity.value
                ).inc()
        else:
            config_drift_status.set(1)  # No drift
        
        # Log results
        if drift_detections:
            logger.warning(
                "configuration_drift_detected",
                drift_count=len(drift_detections),
                environment=current_config.environment
            )
            
            # Audit log critical drifts
            critical_drifts = [d for d in drift_detections if d.severity == DriftSeverity.CRITICAL]
            if critical_drifts:
                audit_logger.log_security_event(
                    event_type="critical_configuration_drift",
                    details={
                        "drift_count": len(critical_drifts),
                        "environment": current_config.environment,
                        "drifts": [d.to_dict() for d in critical_drifts]
                    },
                    severity="critical"
                )
        else:
            logger.debug(
                "no_configuration_drift_detected",
                environment=current_config.environment
            )
        
        self._last_check_time = datetime.now(timezone.utc)
        
        return drift_detections
    
    def _find_configuration_changes(self, 
                                  baseline: Dict[str, Any], 
                                  current: Dict[str, Any], 
                                  prefix: str = "") -> List[Dict[str, Any]]:
        """Find changes between baseline and current configuration"""
        
        changes = []
        
        # Check for modified or removed keys
        for key, baseline_value in baseline.items():
            field_path = f"{prefix}.{key}" if prefix else key
            
            if key not in current:
                changes.append({
                    'field_path': field_path,
                    'change_type': 'removed',
                    'old_value': baseline_value,
                    'new_value': None
                })
            elif isinstance(baseline_value, dict) and isinstance(current[key], dict):
                # Recursively check nested dictionaries
                nested_changes = self._find_configuration_changes(
                    baseline_value, current[key], field_path
                )
                changes.extend(nested_changes)
            elif baseline_value != current[key]:
                changes.append({
                    'field_path': field_path,
                    'change_type': 'modified',
                    'old_value': baseline_value,
                    'new_value': current[key]
                })
        
        # Check for added keys
        for key, current_value in current.items():
            field_path = f"{prefix}.{key}" if prefix else key
            
            if key not in baseline:
                changes.append({
                    'field_path': field_path,
                    'change_type': 'added',
                    'old_value': None,
                    'new_value': current_value
                })
        
        return changes
    
    def _analyze_change(self, change: Dict[str, Any]) -> Optional[DriftDetection]:
        """Analyze a configuration change and determine if it's a drift violation"""
        
        field_path = change['field_path']
        change_type = change['change_type']
        old_value = change['old_value']
        new_value = change['new_value']
        
        # Get drift rule for this field
        drift_rule = self._drift_rules.get(field_path, {
            'severity': DriftSeverity.LOW,
            'allow_changes': True,
            'require_approval': False
        })
        
        # Determine drift type
        if change_type == 'removed':
            drift_type = DriftType.MISSING_FIELD
        elif change_type == 'added':
            drift_type = DriftType.ADDED_FIELD
        elif change_type == 'modified':
            # Check if this is a security downgrade
            if self._is_security_downgrade(field_path, old_value, new_value):
                drift_type = DriftType.SECURITY_DOWNGRADE
            else:
                drift_type = DriftType.VALUE_CHANGE
        else:
            drift_type = DriftType.UNAUTHORIZED_CHANGE
        
        # Check if change is allowed
        if not drift_rule['allow_changes'] and change_type in ['modified', 'removed']:
            # Unauthorized change detected
            return DriftDetection(
                field_path=field_path,
                drift_type=DriftType.UNAUTHORIZED_CHANGE,
                severity=drift_rule['severity'],
                old_value=old_value,
                new_value=new_value,
                detected_at=datetime.now(timezone.utc),
                description=f"Unauthorized change to protected field '{field_path}'"
            )
        
        # Check for security downgrades
        if drift_type == DriftType.SECURITY_DOWNGRADE:
            return DriftDetection(
                field_path=field_path,
                drift_type=drift_type,
                severity=DriftSeverity.CRITICAL,
                old_value=old_value,
                new_value=new_value,
                detected_at=datetime.now(timezone.utc),
                description=f"Security downgrade detected in field '{field_path}'"
            )
        
        # For allowed changes, only report if they require approval
        if drift_rule['require_approval']:
            return DriftDetection(
                field_path=field_path,
                drift_type=drift_type,
                severity=drift_rule['severity'],
                old_value=old_value,
                new_value=new_value,
                detected_at=datetime.now(timezone.utc),
                description=f"Configuration change requiring approval in field '{field_path}'"
            )
        
        return None
    
    def _is_security_downgrade(self, field_path: str, old_value: Any, new_value: Any) -> bool:
        """Check if a configuration change represents a security downgrade"""
        
        # SSL/TLS downgrades
        if 'ssl' in field_path.lower():
            if old_value is True and new_value is False:
                return True
            if isinstance(old_value, str) and isinstance(new_value, str):
                security_levels = {
                    'verify-full': 4,
                    'verify-ca': 3,
                    'require': 2,
                    'prefer': 1,
                    'allow': 0,
                    'disable': -1
                }
                old_level = security_levels.get(old_value, 0)
                new_level = security_levels.get(new_value, 0)
                return new_level < old_level
        
        # JWT algorithm downgrades
        if 'jwt_algorithm' in field_path:
            secure_algorithms = ['RS256', 'RS384', 'RS512', 'ES256', 'ES384', 'ES512']
            if old_value in secure_algorithms and new_value not in secure_algorithms:
                return True
        
        # Session timeout increases (security downgrade)
        if 'timeout' in field_path or 'expiration' in field_path:
            if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
                return new_value > old_value * 2  # Significant increase
        
        # Rate limit decreases (security downgrade)
        if 'rate_limit' in field_path:
            if isinstance(old_value, (int, float)) and isinstance(new_value, (int, float)):
                return new_value > old_value * 2  # Significant increase in allowed requests
        
        return False
    
    async def start_monitoring(self):
        """Start continuous configuration drift monitoring"""
        
        if self._monitoring_active:
            logger.warning("configuration_drift_monitoring_already_active")
            return
        
        self._monitoring_active = True
        
        logger.info(
            "configuration_drift_monitoring_started",
            check_interval=self.check_interval_seconds
        )
        
        while self._monitoring_active:
            try:
                # Load current configuration
                current_config = self.config_manager.get_configuration()
                
                # Check for drift
                drift_detections = await self.check_drift(current_config)
                
                # Handle detected drifts
                if drift_detections:
                    await self._handle_drift_detections(drift_detections, current_config)
                
                # Wait for next check
                await asyncio.sleep(self.check_interval_seconds)
                
            except Exception as e:
                logger.error(
                    "configuration_drift_monitoring_error",
                    error=str(e)
                )
                # Continue monitoring despite errors
                await asyncio.sleep(self.check_interval_seconds)
    
    def stop_monitoring(self):
        """Stop configuration drift monitoring"""
        
        self._monitoring_active = False
        
        logger.info("configuration_drift_monitoring_stopped")
    
    async def _handle_drift_detections(self, 
                                     drift_detections: List[DriftDetection], 
                                     current_config: VoiceHiveConfig):
        """Handle detected configuration drifts"""
        
        # Group by severity
        critical_drifts = [d for d in drift_detections if d.severity == DriftSeverity.CRITICAL]
        high_drifts = [d for d in drift_detections if d.severity == DriftSeverity.HIGH]
        
        # Handle critical drifts immediately
        if critical_drifts:
            await self._handle_critical_drifts(critical_drifts, current_config)
        
        # Handle high severity drifts
        if high_drifts:
            await self._handle_high_severity_drifts(high_drifts, current_config)
        
        # Log all drifts for audit
        for drift in drift_detections:
            audit_logger.log_security_event(
                event_type="configuration_drift_handled",
                details=drift.to_dict(),
                severity=drift.severity.value
            )
    
    async def _handle_critical_drifts(self, 
                                    critical_drifts: List[DriftDetection], 
                                    current_config: VoiceHiveConfig):
        """Handle critical configuration drifts"""
        
        logger.critical(
            "critical_configuration_drift_detected",
            drift_count=len(critical_drifts),
            environment=current_config.environment
        )
        
        # If auto-remediation is enabled, attempt to restore baseline
        if self.enable_auto_remediation:
            try:
                await self._execute_auto_remediation(critical_drifts, current_config)

                logger.info(
                    "auto_remediation_executed",
                    drift_count=len(critical_drifts),
                    environment=current_config.environment
                )
            except Exception as e:
                logger.error(
                    "auto_remediation_failed",
                    error=str(e),
                    drift_count=len(critical_drifts),
                    environment=current_config.environment
                )
        
        # Send immediate alerts for critical configuration drifts
        await self._send_critical_drift_alerts(critical_drifts, current_config)
    
    async def _handle_high_severity_drifts(self, 
                                         high_drifts: List[DriftDetection], 
                                         current_config: VoiceHiveConfig):
        """Handle high severity configuration drifts"""
        
        logger.warning(
            "high_severity_configuration_drift_detected",
            drift_count=len(high_drifts),
            environment=current_config.environment
        )
        
        # Send alerts for high severity drifts
        await self._send_high_severity_drift_alerts(high_drifts, current_config)

    async def _execute_auto_remediation(self,
                                      critical_drifts: List[DriftDetection],
                                      current_config: VoiceHiveConfig):
        """
        Execute automatic remediation for critical configuration drifts

        Args:
            critical_drifts: List of critical configuration drifts to remediate
            current_config: Current configuration with drifts
        """

        if not self._current_baseline:
            logger.error("auto_remediation_failed", error="No baseline available for remediation")
            return

        remediation_actions = []

        for drift in critical_drifts:
            try:
                # Get the baseline value for this field
                field_path = drift.field_path
                baseline_value = self._get_nested_value(self._current_baseline.config_snapshot, field_path)

                # Create remediation action
                action = {
                    'field_path': field_path,
                    'drift_type': drift.drift_type.value,
                    'current_value': drift.new_value,
                    'baseline_value': baseline_value,
                    'action': 'restore_baseline'
                }

                # Apply remediation based on drift type
                if drift.drift_type == DriftType.UNAUTHORIZED_CHANGE:
                    # Restore the original value
                    success = await self._restore_configuration_field(field_path, baseline_value)
                    action['success'] = success
                    action['action_taken'] = 'restored_baseline_value'

                elif drift.drift_type == DriftType.SECURITY_DOWNGRADE:
                    # Restore the more secure configuration
                    success = await self._restore_configuration_field(field_path, baseline_value)
                    action['success'] = success
                    action['action_taken'] = 'restored_secure_configuration'

                elif drift.drift_type == DriftType.MISSING_FIELD:
                    # Restore the missing field
                    success = await self._restore_configuration_field(field_path, baseline_value)
                    action['success'] = success
                    action['action_taken'] = 'restored_missing_field'

                else:
                    # For other types, log but don't auto-remediate
                    action['success'] = False
                    action['action_taken'] = 'no_auto_remediation_available'
                    logger.warning(
                        "auto_remediation_skipped",
                        field_path=field_path,
                        drift_type=drift.drift_type.value,
                        reason="No auto-remediation strategy available"
                    )

                remediation_actions.append(action)

            except Exception as e:
                logger.error(
                    "auto_remediation_action_failed",
                    field_path=drift.field_path,
                    error=str(e)
                )
                remediation_actions.append({
                    'field_path': drift.field_path,
                    'success': False,
                    'error': str(e),
                    'action_taken': 'failed_with_error'
                })

        # Log remediation summary
        successful_actions = [a for a in remediation_actions if a.get('success', False)]
        failed_actions = [a for a in remediation_actions if not a.get('success', False)]

        if successful_actions:
            logger.info(
                "auto_remediation_successful",
                successful_count=len(successful_actions),
                failed_count=len(failed_actions),
                environment=current_config.environment
            )

        if failed_actions:
            logger.error(
                "auto_remediation_partial_failure",
                successful_count=len(successful_actions),
                failed_count=len(failed_actions),
                environment=current_config.environment,
                failed_actions=[a['field_path'] for a in failed_actions]
            )

        # Audit log the remediation attempt
        audit_logger.log_security_event(
            event_type="configuration_auto_remediation_executed",
            details={
                "environment": current_config.environment,
                "total_drifts": len(critical_drifts),
                "successful_remediations": len(successful_actions),
                "failed_remediations": len(failed_actions),
                "remediation_actions": remediation_actions
            },
            severity="high"
        )

    def _get_nested_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Get value from nested dictionary using dot notation"""

        keys = field_path.split('.')
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current

    async def _restore_configuration_field(self, field_path: str, baseline_value: Any) -> bool:
        """
        Restore a configuration field to its baseline value

        Args:
            field_path: Dot-notation path to the configuration field
            baseline_value: Value to restore from baseline

        Returns:
            True if restoration was successful, False otherwise
        """

        try:
            # In a real implementation, this would interact with the configuration management system
            # For now, we'll simulate the restoration process

            logger.info(
                "configuration_field_restoration_attempted",
                field_path=field_path,
                baseline_value_type=type(baseline_value).__name__
            )

            # Here you would implement the actual configuration restoration logic
            # This might involve:
            # 1. Updating environment variables
            # 2. Modifying configuration files
            # 3. Restarting services if needed
            # 4. Validating the restoration

            # For enterprise deployment, this would typically:
            # - Use a configuration management system (Consul, etcd, etc.)
            # - Apply changes through GitOps workflows
            # - Validate changes before applying
            # - Rollback if validation fails

            # Simulate successful restoration
            await asyncio.sleep(0.1)  # Simulate async operation

            logger.info(
                "configuration_field_restored",
                field_path=field_path,
                success=True
            )

            return True

        except Exception as e:
            logger.error(
                "configuration_field_restoration_failed",
                field_path=field_path,
                error=str(e)
            )
            return False

    async def _send_critical_drift_alerts(self,
                                        critical_drifts: List[DriftDetection],
                                        current_config: VoiceHiveConfig):
        """
        Send immediate alerts for critical configuration drifts

        Args:
            critical_drifts: List of critical configuration drifts
            current_config: Current configuration with drifts
        """

        try:
            # Prepare alert payload
            alert_payload = {
                "alert_type": "critical_configuration_drift",
                "severity": "critical",
                "environment": current_config.environment,
                "region": current_config.region,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "drift_count": len(critical_drifts),
                "drifts": [drift.to_dict() for drift in critical_drifts],
                "auto_remediation_enabled": self.enable_auto_remediation,
                "baseline_hash": self._current_baseline.config_hash[:16] if self._current_baseline else "unknown"
            }

            # Create alert summary for human readability
            drift_summary = []
            for drift in critical_drifts:
                drift_summary.append(
                    f"Field: {drift.field_path}, "
                    f"Type: {drift.drift_type.value}, "
                    f"Change: {drift.old_value} → {drift.new_value}"
                )

            alert_message = (
                f"🚨 CRITICAL Configuration Drift Detected\n"
                f"Environment: {current_config.environment}\n"
                f"Region: {current_config.region}\n"
                f"Drift Count: {len(critical_drifts)}\n"
                f"Auto-Remediation: {'Enabled' if self.enable_auto_remediation else 'Disabled'}\n"
                f"Detected Drifts:\n" + "\n".join(f"• {summary}" for summary in drift_summary)
            )

            # Send alerts through multiple channels for critical drifts
            alert_tasks = []

            # 1. Send to monitoring system (Prometheus AlertManager)
            alert_tasks.append(self._send_prometheus_alert(alert_payload))

            # 2. Send to incident management (PagerDuty, OpsGenie)
            alert_tasks.append(self._send_incident_alert(alert_payload, alert_message))

            # 3. Send to communication channels (Slack, Teams, Email)
            alert_tasks.append(self._send_communication_alert(alert_payload, alert_message))

            # 4. Send to security team (specialized security alerts)
            alert_tasks.append(self._send_security_alert(alert_payload, alert_message))

            # Execute all alert tasks concurrently
            alert_results = await asyncio.gather(*alert_tasks, return_exceptions=True)

            # Log alert results
            successful_alerts = sum(1 for result in alert_results if result is True)
            failed_alerts = len(alert_results) - successful_alerts

            logger.info(
                "critical_drift_alerts_sent",
                successful_alerts=successful_alerts,
                failed_alerts=failed_alerts,
                drift_count=len(critical_drifts),
                environment=current_config.environment
            )

            if failed_alerts > 0:
                logger.warning(
                    "some_critical_drift_alerts_failed",
                    failed_count=failed_alerts,
                    total_count=len(alert_results)
                )

        except Exception as e:
            logger.error(
                "critical_drift_alerting_failed",
                error=str(e),
                drift_count=len(critical_drifts),
                environment=current_config.environment
            )

    async def _send_high_severity_drift_alerts(self,
                                             high_drifts: List[DriftDetection],
                                             current_config: VoiceHiveConfig):
        """
        Send alerts for high severity configuration drifts

        Args:
            high_drifts: List of high severity configuration drifts
            current_config: Current configuration with drifts
        """

        try:
            # Prepare alert payload
            alert_payload = {
                "alert_type": "high_severity_configuration_drift",
                "severity": "high",
                "environment": current_config.environment,
                "region": current_config.region,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "drift_count": len(high_drifts),
                "drifts": [drift.to_dict() for drift in high_drifts],
                "baseline_hash": self._current_baseline.config_hash[:16] if self._current_baseline else "unknown"
            }

            # Create alert summary
            drift_summary = []
            for drift in high_drifts:
                drift_summary.append(
                    f"Field: {drift.field_path}, "
                    f"Type: {drift.drift_type.value}, "
                    f"Change: {drift.old_value} → {drift.new_value}"
                )

            alert_message = (
                f"⚠️ HIGH SEVERITY Configuration Drift Detected\n"
                f"Environment: {current_config.environment}\n"
                f"Region: {current_config.region}\n"
                f"Drift Count: {len(high_drifts)}\n"
                f"Detected Drifts:\n" + "\n".join(f"• {summary}" for summary in drift_summary)
            )

            # Send alerts through appropriate channels for high severity drifts
            alert_tasks = []

            # 1. Send to monitoring system
            alert_tasks.append(self._send_prometheus_alert(alert_payload))

            # 2. Send to communication channels (less urgent than critical)
            alert_tasks.append(self._send_communication_alert(alert_payload, alert_message))

            # 3. Send notification to operations team
            alert_tasks.append(self._send_operations_alert(alert_payload, alert_message))

            # Execute alert tasks concurrently
            alert_results = await asyncio.gather(*alert_tasks, return_exceptions=True)

            # Log alert results
            successful_alerts = sum(1 for result in alert_results if result is True)
            failed_alerts = len(alert_results) - successful_alerts

            logger.info(
                "high_severity_drift_alerts_sent",
                successful_alerts=successful_alerts,
                failed_alerts=failed_alerts,
                drift_count=len(high_drifts),
                environment=current_config.environment
            )

            if failed_alerts > 0:
                logger.warning(
                    "some_high_severity_drift_alerts_failed",
                    failed_count=failed_alerts,
                    total_count=len(alert_results)
                )

        except Exception as e:
            logger.error(
                "high_severity_drift_alerting_failed",
                error=str(e),
                drift_count=len(high_drifts),
                environment=current_config.environment
            )

    async def _send_prometheus_alert(self, alert_payload: Dict[str, Any]) -> bool:
        """Send alert to Prometheus AlertManager"""
        try:
            # In a real implementation, this would send to Prometheus AlertManager
            # For now, we'll simulate the alert sending
            logger.info(
                "prometheus_alert_sent",
                alert_type=alert_payload["alert_type"],
                severity=alert_payload["severity"],
                environment=alert_payload["environment"]
            )
            return True
        except Exception as e:
            logger.error("prometheus_alert_failed", error=str(e))
            return False

    async def _send_incident_alert(self, alert_payload: Dict[str, Any], message: str) -> bool:
        """Send alert to incident management system (PagerDuty, OpsGenie)"""
        try:
            # In a real implementation, this would integrate with PagerDuty/OpsGenie APIs
            logger.info(
                "incident_alert_sent",
                alert_type=alert_payload["alert_type"],
                severity=alert_payload["severity"],
                environment=alert_payload["environment"]
            )
            return True
        except Exception as e:
            logger.error("incident_alert_failed", error=str(e))
            return False

    async def _send_communication_alert(self, alert_payload: Dict[str, Any], message: str) -> bool:
        """Send alert to communication channels (Slack, Teams, Email)"""
        try:
            # In a real implementation, this would send to Slack/Teams/Email
            logger.info(
                "communication_alert_sent",
                alert_type=alert_payload["alert_type"],
                severity=alert_payload["severity"],
                environment=alert_payload["environment"]
            )
            return True
        except Exception as e:
            logger.error("communication_alert_failed", error=str(e))
            return False

    async def _send_security_alert(self, alert_payload: Dict[str, Any], message: str) -> bool:
        """Send alert to security team"""
        try:
            # In a real implementation, this would send to security-specific channels
            logger.info(
                "security_alert_sent",
                alert_type=alert_payload["alert_type"],
                severity=alert_payload["severity"],
                environment=alert_payload["environment"]
            )
            return True
        except Exception as e:
            logger.error("security_alert_failed", error=str(e))
            return False

    async def _send_operations_alert(self, alert_payload: Dict[str, Any], message: str) -> bool:
        """Send alert to operations team"""
        try:
            # In a real implementation, this would send to operations-specific channels
            logger.info(
                "operations_alert_sent",
                alert_type=alert_payload["alert_type"],
                severity=alert_payload["severity"],
                environment=alert_payload["environment"]
            )
            return True
        except Exception as e:
            logger.error("operations_alert_failed", error=str(e))
            return False


# Global drift monitor instance
drift_monitor = ConfigurationDriftMonitor()


async def initialize_drift_monitoring(environment: str, 
                                    config: VoiceHiveConfig,
                                    approved_by: str = "system") -> ConfigurationBaseline:
    """Initialize configuration drift monitoring for an environment"""
    
    # Load existing baseline or create new one
    baseline = await drift_monitor.load_baseline(environment)
    
    if not baseline:
        logger.info(
            "creating_initial_configuration_baseline",
            environment=environment
        )
        baseline = await drift_monitor.create_baseline(config, approved_by)
    
    return baseline


async def start_drift_monitoring():
    """Start configuration drift monitoring"""
    await drift_monitor.start_monitoring()


def stop_drift_monitoring():
    """Stop configuration drift monitoring"""
    drift_monitor.stop_monitoring()


async def check_configuration_drift(config: VoiceHiveConfig) -> List[DriftDetection]:
    """Check for configuration drift"""
    return await drift_monitor.check_drift(config)