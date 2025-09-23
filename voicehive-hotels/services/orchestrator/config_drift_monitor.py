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
            logger.warning("auto_remediation_not_implemented")
            # TODO: Implement auto-remediation logic
        
        # Send immediate alerts
        # TODO: Integrate with alerting system
    
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
        # TODO: Integrate with alerting system


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