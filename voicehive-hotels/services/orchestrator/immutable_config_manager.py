"""
Immutable Configuration Management System
Provides immutable configuration with versioning, rollback, and integrity verification
"""

import os
import json
import hashlib
import shutil
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
# import aiofiles  # Not available, using standard file operations
from prometheus_client import Counter, Gauge, Histogram

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger
from config import VoiceHiveConfig, EnvironmentType

logger = get_safe_logger("orchestrator.immutable_config")
audit_logger = AuditLogger("immutable_config")

# Metrics
config_versions_created = Counter('voicehive_config_versions_created_total', 'Configuration versions created', ['environment'])
config_rollbacks = Counter('voicehive_config_rollbacks_total', 'Configuration rollbacks', ['environment', 'reason'])
config_integrity_checks = Counter('voicehive_config_integrity_checks_total', 'Configuration integrity checks', ['environment', 'status'])
config_version_count = Gauge('voicehive_config_version_count', 'Number of configuration versions', ['environment'])
config_storage_size = Gauge('voicehive_config_storage_size_bytes', 'Configuration storage size in bytes', ['environment'])


class ConfigurationVersionStatus(str, Enum):
    """Configuration version status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    CORRUPTED = "corrupted"


class RollbackReason(str, Enum):
    """Reasons for configuration rollback"""
    SECURITY_INCIDENT = "security_incident"
    CONFIGURATION_ERROR = "configuration_error"
    PERFORMANCE_ISSUE = "performance_issue"
    COMPLIANCE_VIOLATION = "compliance_violation"
    EMERGENCY_RESPONSE = "emergency_response"
    PLANNED_ROLLBACK = "planned_rollback"


@dataclass
class ConfigurationVersion:
    """Immutable configuration version"""
    
    version_id: str
    environment: EnvironmentType
    config_hash: str
    config_data: Dict[str, Any]
    created_at: datetime
    created_by: str
    status: ConfigurationVersionStatus
    parent_version_id: Optional[str] = None
    change_description: str = ""
    approval_request_id: Optional[str] = None
    
    # Integrity verification
    signature: Optional[str] = None
    checksum: Optional[str] = None
    
    # Metadata
    tags: List[str] = None
    retention_until: Optional[datetime] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        if self.retention_until:
            data['retention_until'] = self.retention_until.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigurationVersion':
        """Create from dictionary"""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('retention_until'):
            data['retention_until'] = datetime.fromisoformat(data['retention_until'])
        return cls(**data)
    
    def calculate_checksum(self) -> str:
        """Calculate checksum for integrity verification"""
        # Create deterministic representation
        config_json = json.dumps(self.config_data, sort_keys=True, separators=(',', ':'))
        metadata = f"{self.version_id}:{self.environment}:{self.created_at.isoformat()}"
        
        combined = f"{metadata}:{config_json}"
        return hashlib.sha256(combined.encode()).hexdigest()
    
    def verify_integrity(self) -> bool:
        """Verify configuration version integrity"""
        if not self.checksum:
            return False
        
        calculated_checksum = self.calculate_checksum()
        return calculated_checksum == self.checksum
    
    def is_expired(self) -> bool:
        """Check if configuration version has expired"""
        if not self.retention_until:
            return False
        return datetime.now(timezone.utc) > self.retention_until


@dataclass
class ConfigurationRollback:
    """Configuration rollback record"""
    
    rollback_id: str
    environment: EnvironmentType
    from_version_id: str
    to_version_id: str
    reason: RollbackReason
    initiated_by: str
    initiated_at: datetime
    completed_at: Optional[datetime] = None
    rollback_description: str = ""
    emergency: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['initiated_at'] = self.initiated_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConfigurationRollback':
        """Create from dictionary"""
        data['initiated_at'] = datetime.fromisoformat(data['initiated_at'])
        if data.get('completed_at'):
            data['completed_at'] = datetime.fromisoformat(data['completed_at'])
        return cls(**data)


class ImmutableConfigurationManager:
    """
    Immutable configuration management with versioning and rollback capabilities
    """
    
    def __init__(self, 
                 storage_path: str = "/var/lib/voicehive/config-versions",
                 max_versions_per_environment: int = 50,
                 enable_compression: bool = True):
        
        self.storage_path = Path(storage_path)
        self.max_versions_per_environment = max_versions_per_environment
        self.enable_compression = enable_compression
        
        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (self.storage_path / "versions").mkdir(exist_ok=True)
        (self.storage_path / "rollbacks").mkdir(exist_ok=True)
        (self.storage_path / "metadata").mkdir(exist_ok=True)
        
        # Active versions cache
        self._active_versions: Dict[str, ConfigurationVersion] = {}
        
        # Load active versions
        self._load_active_versions()
    
    def _load_active_versions(self):
        """Load active configuration versions from storage"""
        
        metadata_dir = self.storage_path / "metadata"
        
        for env_file in metadata_dir.glob("*_active.json"):
            try:
                with open(env_file, 'r') as f:
                    data = json.load(f)
                
                version = ConfigurationVersion.from_dict(data)
                self._active_versions[version.environment] = version
                
                logger.debug(
                    "loaded_active_configuration_version",
                    environment=version.environment,
                    version_id=version.version_id
                )
                
            except Exception as e:
                logger.error(
                    "failed_to_load_active_version",
                    env_file=str(env_file),
                    error=str(e)
                )
    
    async def create_version(self,
                           config: VoiceHiveConfig,
                           created_by: str,
                           change_description: str = "",
                           approval_request_id: Optional[str] = None,
                           tags: Optional[List[str]] = None) -> ConfigurationVersion:
        """
        Create a new immutable configuration version
        
        Args:
            config: Configuration to version
            created_by: User creating the version
            change_description: Description of changes
            approval_request_id: Associated approval request ID
            tags: Optional tags for the version
            
        Returns:
            Created configuration version
        """
        
        # Generate version ID
        timestamp = datetime.now(timezone.utc)
        version_id = f"{config.environment}_{timestamp.strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(str(timestamp).encode()).hexdigest()[:8]}"
        
        # Get parent version ID
        parent_version_id = None
        if config.environment in self._active_versions:
            parent_version_id = self._active_versions[config.environment].version_id
        
        # Create configuration version
        config_data = config.model_dump(exclude={'config_hash', 'last_updated'})
        
        version = ConfigurationVersion(
            version_id=version_id,
            environment=config.environment,
            config_hash=config.calculate_config_hash(),
            config_data=config_data,
            created_at=timestamp,
            created_by=created_by,
            status=ConfigurationVersionStatus.ACTIVE,
            parent_version_id=parent_version_id,
            change_description=change_description,
            approval_request_id=approval_request_id,
            tags=tags or []
        )
        
        # Calculate checksum for integrity
        version.checksum = version.calculate_checksum()
        
        # Save version to storage
        await self._save_version(version)
        
        # Update active version
        if config.environment in self._active_versions:
            old_version = self._active_versions[config.environment]
            old_version.status = ConfigurationVersionStatus.INACTIVE
            await self._save_version(old_version)
        
        self._active_versions[config.environment] = version
        await self._save_active_version_metadata(version)
        
        # Clean up old versions if needed
        await self._cleanup_old_versions(config.environment)
        
        # Update metrics
        config_versions_created.labels(environment=config.environment).inc()
        
        # Update version count
        version_count = await self._count_versions(config.environment)
        config_version_count.labels(environment=config.environment).set(version_count)
        
        # Audit log
        audit_logger.log_security_event(
            event_type="immutable_configuration_version_created",
            details={
                "version_id": version_id,
                "environment": config.environment,
                "created_by": created_by,
                "config_hash": version.config_hash[:16],
                "parent_version_id": parent_version_id,
                "approval_request_id": approval_request_id,
                "tags": tags or []
            },
            severity="medium"
        )
        
        logger.info(
            "immutable_configuration_version_created",
            version_id=version_id,
            environment=config.environment,
            created_by=created_by,
            config_hash=version.config_hash[:16]
        )
        
        return version
    
    async def get_active_version(self, environment: EnvironmentType) -> Optional[ConfigurationVersion]:
        """Get the active configuration version for an environment"""
        
        version = self._active_versions.get(environment)
        
        if version:
            # Verify integrity
            if not version.verify_integrity():
                logger.error(
                    "active_configuration_version_integrity_failed",
                    environment=environment,
                    version_id=version.version_id
                )
                
                version.status = ConfigurationVersionStatus.CORRUPTED
                await self._save_version(version)
                
                config_integrity_checks.labels(
                    environment=environment,
                    status="failed"
                ).inc()
                
                return None
            
            config_integrity_checks.labels(
                environment=environment,
                status="passed"
            ).inc()
        
        return version
    
    async def get_version(self, version_id: str) -> Optional[ConfigurationVersion]:
        """Get a specific configuration version by ID"""
        
        version_file = self.storage_path / "versions" / f"{version_id}.json"
        
        if not version_file.exists():
            return None
        
        try:
            with open(version_file, 'r') as f:
                data = json.load(f)
            
            version = ConfigurationVersion.from_dict(data)
            
            # Verify integrity
            if not version.verify_integrity():
                logger.warning(
                    "configuration_version_integrity_failed",
                    version_id=version_id
                )
                version.status = ConfigurationVersionStatus.CORRUPTED
                await self._save_version(version)
            
            return version
            
        except Exception as e:
            logger.error(
                "failed_to_load_configuration_version",
                version_id=version_id,
                error=str(e)
            )
            return None
    
    async def list_versions(self, 
                          environment: EnvironmentType,
                          limit: int = 20,
                          include_inactive: bool = True) -> List[ConfigurationVersion]:
        """List configuration versions for an environment"""
        
        versions = []
        
        # Get all version files for the environment
        version_files = list(self.storage_path.glob(f"versions/{environment}_*.json"))
        
        for version_file in version_files:
            try:
                version = await self.get_version(version_file.stem)
                if version:
                    if include_inactive or version.status == ConfigurationVersionStatus.ACTIVE:
                        versions.append(version)
                        
            except Exception as e:
                logger.error(
                    "failed_to_load_version_for_listing",
                    version_file=str(version_file),
                    error=str(e)
                )
        
        # Sort by creation time (newest first)
        versions.sort(key=lambda v: v.created_at, reverse=True)
        
        return versions[:limit]
    
    async def rollback_to_version(self,
                                environment: EnvironmentType,
                                target_version_id: str,
                                initiated_by: str,
                                reason: RollbackReason,
                                rollback_description: str = "",
                                emergency: bool = False) -> ConfigurationRollback:
        """
        Rollback configuration to a specific version
        
        Args:
            environment: Target environment
            target_version_id: Version ID to rollback to
            initiated_by: User initiating rollback
            reason: Reason for rollback
            rollback_description: Description of rollback
            emergency: Whether this is an emergency rollback
            
        Returns:
            Rollback record
        """
        
        # Get current active version
        current_version = await self.get_active_version(environment)
        if not current_version:
            raise ValueError(f"No active configuration version found for environment {environment}")
        
        # Get target version
        target_version = await self.get_version(target_version_id)
        if not target_version:
            raise ValueError(f"Target version not found: {target_version_id}")
        
        # Verify target version is for the same environment
        if target_version.environment != environment:
            raise ValueError(f"Target version is for different environment: {target_version.environment}")
        
        # Verify target version integrity
        if not target_version.verify_integrity():
            raise ValueError(f"Target version integrity check failed: {target_version_id}")
        
        # Create rollback record
        rollback_id = f"rollback_{environment}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        rollback = ConfigurationRollback(
            rollback_id=rollback_id,
            environment=environment,
            from_version_id=current_version.version_id,
            to_version_id=target_version_id,
            reason=reason,
            initiated_by=initiated_by,
            initiated_at=datetime.now(timezone.utc),
            rollback_description=rollback_description,
            emergency=emergency
        )
        
        # Perform rollback
        try:
            # Deactivate current version
            current_version.status = ConfigurationVersionStatus.INACTIVE
            await self._save_version(current_version)
            
            # Activate target version
            target_version.status = ConfigurationVersionStatus.ACTIVE
            await self._save_version(target_version)
            
            # Update active version
            self._active_versions[environment] = target_version
            await self._save_active_version_metadata(target_version)
            
            # Complete rollback
            rollback.completed_at = datetime.now(timezone.utc)
            await self._save_rollback(rollback)
            
            # Update metrics
            config_rollbacks.labels(
                environment=environment,
                reason=reason.value
            ).inc()
            
            # Audit log
            severity = "critical" if emergency else "high"
            audit_logger.log_security_event(
                event_type="configuration_rollback_completed",
                details={
                    "rollback_id": rollback_id,
                    "environment": environment,
                    "from_version_id": current_version.version_id,
                    "to_version_id": target_version_id,
                    "reason": reason.value,
                    "initiated_by": initiated_by,
                    "emergency": emergency,
                    "rollback_description": rollback_description
                },
                severity=severity
            )
            
            logger.warning(
                "configuration_rollback_completed",
                rollback_id=rollback_id,
                environment=environment,
                from_version=current_version.version_id,
                to_version=target_version_id,
                reason=reason.value,
                emergency=emergency
            )
            
            return rollback
            
        except Exception as e:
            logger.error(
                "configuration_rollback_failed",
                rollback_id=rollback_id,
                environment=environment,
                error=str(e)
            )
            
            # Log failed rollback
            audit_logger.log_security_event(
                event_type="configuration_rollback_failed",
                details={
                    "rollback_id": rollback_id,
                    "environment": environment,
                    "error": str(e)
                },
                severity="critical"
            )
            
            raise
    
    async def verify_all_versions(self, environment: EnvironmentType) -> Dict[str, bool]:
        """Verify integrity of all configuration versions for an environment"""
        
        results = {}
        versions = await self.list_versions(environment, limit=1000, include_inactive=True)
        
        for version in versions:
            is_valid = version.verify_integrity()
            results[version.version_id] = is_valid
            
            if not is_valid:
                logger.error(
                    "configuration_version_integrity_check_failed",
                    version_id=version.version_id,
                    environment=environment
                )
                
                # Mark as corrupted
                version.status = ConfigurationVersionStatus.CORRUPTED
                await self._save_version(version)
                
                config_integrity_checks.labels(
                    environment=environment,
                    status="failed"
                ).inc()
            else:
                config_integrity_checks.labels(
                    environment=environment,
                    status="passed"
                ).inc()
        
        return results
    
    async def _save_version(self, version: ConfigurationVersion):
        """Save configuration version to storage"""
        
        version_file = self.storage_path / "versions" / f"{version.version_id}.json"
        
        try:
            with open(version_file, 'w') as f:
                f.write(json.dumps(version.to_dict(), indent=2))
                
        except Exception as e:
            logger.error(
                "failed_to_save_configuration_version",
                version_id=version.version_id,
                error=str(e)
            )
            raise
    
    async def _save_active_version_metadata(self, version: ConfigurationVersion):
        """Save active version metadata"""
        
        metadata_file = self.storage_path / "metadata" / f"{version.environment}_active.json"
        
        try:
            with open(metadata_file, 'w') as f:
                f.write(json.dumps(version.to_dict(), indent=2))
                
        except Exception as e:
            logger.error(
                "failed_to_save_active_version_metadata",
                version_id=version.version_id,
                error=str(e)
            )
            raise
    
    async def _save_rollback(self, rollback: ConfigurationRollback):
        """Save rollback record to storage"""
        
        rollback_file = self.storage_path / "rollbacks" / f"{rollback.rollback_id}.json"
        
        try:
            with open(rollback_file, 'w') as f:
                f.write(json.dumps(rollback.to_dict(), indent=2))
                
        except Exception as e:
            logger.error(
                "failed_to_save_rollback_record",
                rollback_id=rollback.rollback_id,
                error=str(e)
            )
            raise
    
    async def _cleanup_old_versions(self, environment: EnvironmentType):
        """Clean up old configuration versions beyond retention limit"""
        
        versions = await self.list_versions(environment, limit=1000, include_inactive=True)
        
        if len(versions) <= self.max_versions_per_environment:
            return
        
        # Keep the most recent versions, remove the oldest
        versions_to_remove = versions[self.max_versions_per_environment:]
        
        for version in versions_to_remove:
            # Don't remove active versions or versions with retention requirements
            if version.status == ConfigurationVersionStatus.ACTIVE:
                continue
            
            if version.retention_until and not version.is_expired():
                continue
            
            try:
                # Remove version file
                version_file = self.storage_path / "versions" / f"{version.version_id}.json"
                if version_file.exists():
                    version_file.unlink()
                
                logger.info(
                    "configuration_version_cleaned_up",
                    version_id=version.version_id,
                    environment=environment
                )
                
            except Exception as e:
                logger.error(
                    "failed_to_cleanup_configuration_version",
                    version_id=version.version_id,
                    error=str(e)
                )
    
    async def _count_versions(self, environment: EnvironmentType) -> int:
        """Count configuration versions for an environment"""
        
        version_files = list(self.storage_path.glob(f"versions/{environment}_*.json"))
        return len(version_files)


# Global immutable configuration manager instance
immutable_config_manager = ImmutableConfigurationManager()


async def create_config_version(config: VoiceHiveConfig,
                              created_by: str,
                              change_description: str = "",
                              approval_request_id: Optional[str] = None,
                              tags: Optional[List[str]] = None) -> ConfigurationVersion:
    """Create a new immutable configuration version"""
    return await immutable_config_manager.create_version(
        config=config,
        created_by=created_by,
        change_description=change_description,
        approval_request_id=approval_request_id,
        tags=tags
    )


async def get_active_config_version(environment: EnvironmentType) -> Optional[ConfigurationVersion]:
    """Get the active configuration version for an environment"""
    return await immutable_config_manager.get_active_version(environment)


async def rollback_config(environment: EnvironmentType,
                        target_version_id: str,
                        initiated_by: str,
                        reason: RollbackReason,
                        rollback_description: str = "",
                        emergency: bool = False) -> ConfigurationRollback:
    """Rollback configuration to a specific version"""
    return await immutable_config_manager.rollback_to_version(
        environment=environment,
        target_version_id=target_version_id,
        initiated_by=initiated_by,
        reason=reason,
        rollback_description=rollback_description,
        emergency=emergency
    )


async def verify_config_integrity(environment: EnvironmentType) -> Dict[str, bool]:
    """Verify integrity of all configuration versions"""
    return await immutable_config_manager.verify_all_versions(environment)