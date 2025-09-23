"""
Production-grade Secrets Management and Rotation Automation
Implements comprehensive secret lifecycle management with HashiCorp Vault integration
"""

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

import hvac
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pydantic import BaseModel, Field, field_validator
from prometheus_client import Counter, Histogram, Gauge, Enum as PrometheusEnum

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger

# Configure logging
logger = get_safe_logger("orchestrator.secrets_manager")
audit_logger = AuditLogger("secrets_management")

# Metrics
secrets_rotation_total = Counter('voicehive_secrets_rotation_total', 'Total secret rotations', ['secret_type', 'status'])
secrets_access_total = Counter('voicehive_secrets_access_total', 'Total secret access attempts', ['secret_type', 'status'])
secrets_expiry_warnings = Counter('voicehive_secrets_expiry_warnings_total', 'Secrets approaching expiry', ['secret_type'])
secrets_rotation_duration = Histogram('voicehive_secrets_rotation_duration_seconds', 'Secret rotation duration', ['secret_type'])
secrets_health_status = Gauge('voicehive_secrets_health_status', 'Secrets health status (1=healthy, 0=unhealthy)')
secrets_vault_connection_status = PrometheusEnum('voicehive_vault_connection_status', 'Vault connection status', 
                                                states=['connected', 'disconnected', 'error'])


class SecretType(str, Enum):
    """Types of secrets managed by the system"""
    DATABASE_PASSWORD = "database_password"
    REDIS_PASSWORD = "redis_password"
    JWT_SECRET = "jwt_secret"
    API_KEY = "api_key"
    WEBHOOK_SECRET = "webhook_secret"
    ENCRYPTION_KEY = "encryption_key"
    TLS_CERTIFICATE = "tls_certificate"
    EXTERNAL_API_KEY = "external_api_key"
    PMS_CREDENTIALS = "pms_credentials"
    AI_SERVICE_KEY = "ai_service_key"


class SecretStatus(str, Enum):
    """Secret lifecycle status"""
    ACTIVE = "active"
    PENDING_ROTATION = "pending_rotation"
    ROTATING = "rotating"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"
    EXPIRED = "expired"


class RotationStrategy(str, Enum):
    """Secret rotation strategies"""
    TIME_BASED = "time_based"
    USAGE_BASED = "usage_based"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass
class SecretMetadata:
    """Metadata for secret lifecycle management"""
    secret_id: str
    secret_type: SecretType
    created_at: datetime
    expires_at: Optional[datetime]
    last_rotated: Optional[datetime]
    rotation_count: int
    status: SecretStatus
    rotation_strategy: RotationStrategy
    max_usage_count: Optional[int]
    current_usage_count: int
    tags: Dict[str, str]
    emergency_contacts: List[str]


class SecretRotationConfig(BaseModel):
    """Configuration for secret rotation"""
    secret_type: SecretType
    rotation_interval_days: int = Field(ge=1, le=365)
    warning_days_before_expiry: int = Field(ge=1, le=30)
    max_usage_count: Optional[int] = Field(None, ge=1)
    auto_rotation_enabled: bool = True
    emergency_rotation_enabled: bool = True
    backup_count: int = Field(default=3, ge=1, le=10)
    
    @field_validator('warning_days_before_expiry')
    @classmethod
    def validate_warning_period(cls, v, info):
        if 'rotation_interval_days' in info.data and v >= info.data['rotation_interval_days']:
            raise ValueError('Warning period must be less than rotation interval')
        return v


class SecretAccessAudit(BaseModel):
    """Audit record for secret access"""
    access_id: str
    secret_id: str
    secret_type: SecretType
    accessed_by: str
    access_time: datetime
    access_method: str
    source_ip: Optional[str]
    user_agent: Optional[str]
    success: bool
    failure_reason: Optional[str]


class SecretsManager:
    """
    Production-grade secrets manager with comprehensive lifecycle management
    """
    
    def __init__(self, vault_client: hvac.Client, config: Dict[str, Any]):
        self.vault_client = vault_client
        self.config = config
        self.secrets_path = config.get('secrets_path', 'voicehive/secrets')
        self.metadata_path = config.get('metadata_path', 'voicehive/metadata')
        self.audit_path = config.get('audit_path', 'voicehive/audit')
        
        # Rotation configurations
        self.rotation_configs: Dict[SecretType, SecretRotationConfig] = {}
        self._load_rotation_configs()
        
        # Background tasks
        self._rotation_task: Optional[asyncio.Task] = None
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Emergency rotation handlers
        self._emergency_handlers: Dict[SecretType, callable] = {}
        
    async def initialize(self) -> bool:
        """Initialize the secrets manager"""
        try:
            # Verify Vault connection
            if not self.vault_client.is_authenticated():
                logger.error("vault_authentication_failed")
                secrets_vault_connection_status.state('disconnected')
                return False
            
            # Ensure required paths exist
            await self._ensure_vault_paths()
            
            # Load existing secret metadata
            await self._load_secret_metadata()
            
            # Start background tasks
            await self._start_background_tasks()
            
            secrets_vault_connection_status.state('connected')
            secrets_health_status.set(1)
            
            audit_logger.log_security_event(
                event_type="secrets_manager_initialized",
                details={"vault_url": self.vault_client.url},
                severity="info"
            )
            
            logger.info("secrets_manager_initialized")
            return True
            
        except Exception as e:
            logger.error("secrets_manager_initialization_failed", error=str(e))
            secrets_vault_connection_status.state('error')
            secrets_health_status.set(0)
            return False
    
    async def create_secret(self, 
                          secret_type: SecretType,
                          secret_value: str,
                          metadata: Optional[Dict[str, Any]] = None,
                          expires_in_days: Optional[int] = None) -> str:
        """Create a new secret with metadata"""
        
        secret_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Calculate expiration
        expires_at = None
        if expires_in_days:
            expires_at = now + timedelta(days=expires_in_days)
        elif secret_type in self.rotation_configs:
            config = self.rotation_configs[secret_type]
            expires_at = now + timedelta(days=config.rotation_interval_days)
        
        # Create secret metadata
        secret_metadata = SecretMetadata(
            secret_id=secret_id,
            secret_type=secret_type,
            created_at=now,
            expires_at=expires_at,
            last_rotated=None,
            rotation_count=0,
            status=SecretStatus.ACTIVE,
            rotation_strategy=RotationStrategy.TIME_BASED,
            max_usage_count=None,
            current_usage_count=0,
            tags=metadata or {},
            emergency_contacts=self.config.get('emergency_contacts', [])
        )
        
        try:
            # Store secret in Vault
            secret_path = f"{self.secrets_path}/{secret_type.value}/{secret_id}"
            self.vault_client.secrets.kv.v2.create_or_update_secret(
                path=secret_path,
                secret={
                    "value": secret_value,
                    "created_at": now.isoformat(),
                    "secret_type": secret_type.value
                }
            )
            
            # Store metadata
            metadata_path = f"{self.metadata_path}/{secret_id}"
            self.vault_client.secrets.kv.v2.create_or_update_secret(
                path=metadata_path,
                secret=asdict(secret_metadata)
            )
            
            # Audit log
            audit_logger.log_security_event(
                event_type="secret_created",
                details={
                    "secret_id": secret_id,
                    "secret_type": secret_type.value,
                    "expires_at": expires_at.isoformat() if expires_at else None
                },
                severity="info"
            )
            
            logger.info("secret_created", secret_id=secret_id, secret_type=secret_type.value)
            return secret_id
            
        except Exception as e:
            logger.error("secret_creation_failed", secret_id=secret_id, error=str(e))
            raise
    
    async def get_secret(self, 
                        secret_id: str,
                        accessed_by: str,
                        access_context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Retrieve a secret with access auditing"""
        
        access_audit = SecretAccessAudit(
            access_id=str(uuid.uuid4()),
            secret_id=secret_id,
            secret_type=SecretType.API_KEY,  # Will be updated after metadata lookup
            accessed_by=accessed_by,
            access_time=datetime.now(timezone.utc),
            access_method="api",
            source_ip=access_context.get('source_ip') if access_context else None,
            user_agent=access_context.get('user_agent') if access_context else None,
            success=False,
            failure_reason=None
        )
        
        try:
            # Get secret metadata first
            metadata = await self._get_secret_metadata(secret_id)
            if not metadata:
                access_audit.failure_reason = "secret_not_found"
                await self._audit_secret_access(access_audit)
                secrets_access_total.labels(secret_type="unknown", status="not_found").inc()
                return None
            
            access_audit.secret_type = metadata.secret_type
            
            # Check if secret is active
            if metadata.status != SecretStatus.ACTIVE:
                access_audit.failure_reason = f"secret_status_{metadata.status.value}"
                await self._audit_secret_access(access_audit)
                secrets_access_total.labels(secret_type=metadata.secret_type.value, status="inactive").inc()
                return None
            
            # Check expiration
            if metadata.expires_at and datetime.now(timezone.utc) > metadata.expires_at:
                access_audit.failure_reason = "secret_expired"
                await self._audit_secret_access(access_audit)
                secrets_access_total.labels(secret_type=metadata.secret_type.value, status="expired").inc()
                
                # Mark as expired
                metadata.status = SecretStatus.EXPIRED
                await self._update_secret_metadata(secret_id, metadata)
                return None
            
            # Check usage limits
            if metadata.max_usage_count and metadata.current_usage_count >= metadata.max_usage_count:
                access_audit.failure_reason = "usage_limit_exceeded"
                await self._audit_secret_access(access_audit)
                secrets_access_total.labels(secret_type=metadata.secret_type.value, status="usage_exceeded").inc()
                return None
            
            # Retrieve secret value
            secret_path = f"{self.secrets_path}/{metadata.secret_type.value}/{secret_id}"
            response = self.vault_client.secrets.kv.v2.read_secret_version(path=secret_path)
            secret_value = response['data']['data']['value']
            
            # Update usage count
            metadata.current_usage_count += 1
            await self._update_secret_metadata(secret_id, metadata)
            
            # Successful access
            access_audit.success = True
            await self._audit_secret_access(access_audit)
            secrets_access_total.labels(secret_type=metadata.secret_type.value, status="success").inc()
            
            return secret_value
            
        except Exception as e:
            access_audit.failure_reason = f"error: {str(e)}"
            await self._audit_secret_access(access_audit)
            secrets_access_total.labels(secret_type="unknown", status="error").inc()
            logger.error("secret_access_failed", secret_id=secret_id, error=str(e))
            return None
    
    async def rotate_secret(self, 
                          secret_id: str,
                          new_value: Optional[str] = None,
                          rotation_strategy: RotationStrategy = RotationStrategy.MANUAL) -> bool:
        """Rotate a secret"""
        
        with secrets_rotation_duration.labels(secret_type="unknown").time():
            try:
                # Get current metadata
                metadata = await self._get_secret_metadata(secret_id)
                if not metadata:
                    logger.error("secret_rotation_failed_not_found", secret_id=secret_id)
                    return False
                
                # Update metrics label
                with secrets_rotation_duration.labels(secret_type=metadata.secret_type.value).time():
                    
                    # Mark as rotating
                    metadata.status = SecretStatus.ROTATING
                    await self._update_secret_metadata(secret_id, metadata)
                    
                    # Generate new value if not provided
                    if not new_value:
                        new_value = await self._generate_secret_value(metadata.secret_type)
                    
                    # Create backup of current secret
                    await self._backup_secret(secret_id, metadata)
                    
                    # Update secret value
                    secret_path = f"{self.secrets_path}/{metadata.secret_type.value}/{secret_id}"
                    now = datetime.now(timezone.utc)
                    
                    self.vault_client.secrets.kv.v2.create_or_update_secret(
                        path=secret_path,
                        secret={
                            "value": new_value,
                            "created_at": now.isoformat(),
                            "secret_type": metadata.secret_type.value,
                            "rotation_count": metadata.rotation_count + 1
                        }
                    )
                    
                    # Update metadata
                    metadata.last_rotated = now
                    metadata.rotation_count += 1
                    metadata.status = SecretStatus.ACTIVE
                    metadata.current_usage_count = 0
                    
                    # Update expiration if time-based rotation
                    if rotation_strategy == RotationStrategy.TIME_BASED and metadata.secret_type in self.rotation_configs:
                        config = self.rotation_configs[metadata.secret_type]
                        metadata.expires_at = now + timedelta(days=config.rotation_interval_days)
                    
                    await self._update_secret_metadata(secret_id, metadata)
                    
                    # Audit log
                    audit_logger.log_security_event(
                        event_type="secret_rotated",
                        details={
                            "secret_id": secret_id,
                            "secret_type": metadata.secret_type.value,
                            "rotation_strategy": rotation_strategy.value,
                            "rotation_count": metadata.rotation_count
                        },
                        severity="medium"
                    )
                    
                    secrets_rotation_total.labels(
                        secret_type=metadata.secret_type.value, 
                        status="success"
                    ).inc()
                    
                    logger.info("secret_rotated", secret_id=secret_id, rotation_count=metadata.rotation_count)
                    return True
                    
            except Exception as e:
                secrets_rotation_total.labels(secret_type="unknown", status="error").inc()
                logger.error("secret_rotation_failed", secret_id=secret_id, error=str(e))
                
                # Try to restore from backup if rotation failed
                try:
                    await self._restore_secret_from_backup(secret_id)
                except Exception as restore_error:
                    logger.error("secret_restore_failed", secret_id=secret_id, error=str(restore_error))
                
                return False
    
    async def emergency_rotate_all_secrets(self, secret_type: Optional[SecretType] = None) -> Dict[str, bool]:
        """Emergency rotation of all secrets of a given type or all secrets"""
        
        audit_logger.log_security_event(
            event_type="emergency_rotation_initiated",
            details={"secret_type": secret_type.value if secret_type else "all"},
            severity="high"
        )
        
        results = {}
        
        try:
            # Get all secrets to rotate
            secrets_to_rotate = await self._list_secrets_for_rotation(secret_type)
            
            # Rotate in parallel with limited concurrency
            semaphore = asyncio.Semaphore(5)  # Limit concurrent rotations
            
            async def rotate_with_semaphore(secret_id: str) -> Tuple[str, bool]:
                async with semaphore:
                    result = await self.rotate_secret(secret_id, rotation_strategy=RotationStrategy.EMERGENCY)
                    return secret_id, result
            
            # Execute rotations
            rotation_tasks = [rotate_with_semaphore(sid) for sid in secrets_to_rotate]
            rotation_results = await asyncio.gather(*rotation_tasks, return_exceptions=True)
            
            # Process results
            for result in rotation_results:
                if isinstance(result, Exception):
                    logger.error("emergency_rotation_task_failed", error=str(result))
                    continue
                
                secret_id, success = result
                results[secret_id] = success
            
            # Notify emergency contacts
            await self._notify_emergency_contacts(secret_type, results)
            
            logger.info("emergency_rotation_completed", 
                       total=len(results), 
                       successful=sum(results.values()))
            
            return results
            
        except Exception as e:
            logger.error("emergency_rotation_failed", error=str(e))
            return {}
    
    async def get_secrets_health_report(self) -> Dict[str, Any]:
        """Generate comprehensive secrets health report"""
        
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_health": "healthy",
            "secrets_by_type": {},
            "expiring_soon": [],
            "expired": [],
            "high_usage": [],
            "rotation_needed": [],
            "vault_status": "connected" if self.vault_client.is_authenticated() else "disconnected"
        }
        
        try:
            # Get all secret metadata
            all_metadata = await self._get_all_secret_metadata()
            
            now = datetime.now(timezone.utc)
            
            for metadata in all_metadata:
                secret_type = metadata.secret_type.value
                
                # Initialize type stats
                if secret_type not in report["secrets_by_type"]:
                    report["secrets_by_type"][secret_type] = {
                        "total": 0,
                        "active": 0,
                        "expired": 0,
                        "rotating": 0
                    }
                
                stats = report["secrets_by_type"][secret_type]
                stats["total"] += 1
                stats[metadata.status.value] = stats.get(metadata.status.value, 0) + 1
                
                # Check for issues
                if metadata.expires_at:
                    days_to_expiry = (metadata.expires_at - now).days
                    
                    if days_to_expiry <= 0:
                        report["expired"].append({
                            "secret_id": metadata.secret_id,
                            "secret_type": secret_type,
                            "expired_days_ago": abs(days_to_expiry)
                        })
                    elif days_to_expiry <= 7:
                        report["expiring_soon"].append({
                            "secret_id": metadata.secret_id,
                            "secret_type": secret_type,
                            "days_to_expiry": days_to_expiry
                        })
                
                # Check usage
                if metadata.max_usage_count:
                    usage_percentage = (metadata.current_usage_count / metadata.max_usage_count) * 100
                    if usage_percentage >= 80:
                        report["high_usage"].append({
                            "secret_id": metadata.secret_id,
                            "secret_type": secret_type,
                            "usage_percentage": usage_percentage
                        })
                
                # Check rotation needed
                if metadata.secret_type in self.rotation_configs:
                    config = self.rotation_configs[metadata.secret_type]
                    if metadata.last_rotated:
                        days_since_rotation = (now - metadata.last_rotated).days
                        if days_since_rotation >= config.rotation_interval_days:
                            report["rotation_needed"].append({
                                "secret_id": metadata.secret_id,
                                "secret_type": secret_type,
                                "days_since_rotation": days_since_rotation
                            })
            
            # Determine overall health
            if report["expired"] or report["vault_status"] != "connected":
                report["overall_health"] = "critical"
            elif report["expiring_soon"] or report["rotation_needed"]:
                report["overall_health"] = "warning"
            
            return report
            
        except Exception as e:
            logger.error("health_report_generation_failed", error=str(e))
            report["overall_health"] = "error"
            report["error"] = str(e)
            return report
    
    async def _ensure_vault_paths(self):
        """Ensure required Vault paths exist"""
        paths = [self.secrets_path, self.metadata_path, self.audit_path]
        
        for path in paths:
            try:
                # Try to list the path to see if it exists
                self.vault_client.secrets.kv.v2.list_secrets(path=path)
            except Exception:
                # Path doesn't exist, create it by writing a dummy secret
                self.vault_client.secrets.kv.v2.create_or_update_secret(
                    path=f"{path}/.initialized",
                    secret={"initialized_at": datetime.now(timezone.utc).isoformat()}
                )
    
    async def _load_rotation_configs(self):
        """Load rotation configurations from Vault or defaults"""
        default_configs = {
            SecretType.DATABASE_PASSWORD: SecretRotationConfig(
                secret_type=SecretType.DATABASE_PASSWORD,
                rotation_interval_days=90,
                warning_days_before_expiry=7
            ),
            SecretType.JWT_SECRET: SecretRotationConfig(
                secret_type=SecretType.JWT_SECRET,
                rotation_interval_days=30,
                warning_days_before_expiry=3
            ),
            SecretType.API_KEY: SecretRotationConfig(
                secret_type=SecretType.API_KEY,
                rotation_interval_days=180,
                warning_days_before_expiry=14
            ),
            SecretType.ENCRYPTION_KEY: SecretRotationConfig(
                secret_type=SecretType.ENCRYPTION_KEY,
                rotation_interval_days=365,
                warning_days_before_expiry=30
            )
        }
        
        self.rotation_configs = default_configs
    
    async def _get_secret_metadata(self, secret_id: str) -> Optional[SecretMetadata]:
        """Get secret metadata from Vault"""
        try:
            metadata_path = f"{self.metadata_path}/{secret_id}"
            response = self.vault_client.secrets.kv.v2.read_secret_version(path=metadata_path)
            data = response['data']['data']
            
            # Convert datetime strings back to datetime objects
            if data.get('created_at'):
                data['created_at'] = datetime.fromisoformat(data['created_at'])
            if data.get('expires_at'):
                data['expires_at'] = datetime.fromisoformat(data['expires_at'])
            if data.get('last_rotated'):
                data['last_rotated'] = datetime.fromisoformat(data['last_rotated'])
            
            # Convert enums
            data['secret_type'] = SecretType(data['secret_type'])
            data['status'] = SecretStatus(data['status'])
            data['rotation_strategy'] = RotationStrategy(data['rotation_strategy'])
            
            return SecretMetadata(**data)
            
        except Exception as e:
            logger.debug("secret_metadata_not_found", secret_id=secret_id, error=str(e))
            return None
    
    async def _update_secret_metadata(self, secret_id: str, metadata: SecretMetadata):
        """Update secret metadata in Vault"""
        metadata_path = f"{self.metadata_path}/{secret_id}"
        
        # Convert to serializable format
        data = asdict(metadata)
        
        # Convert datetime objects to ISO strings
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, (SecretType, SecretStatus, RotationStrategy)):
                data[key] = value.value
        
        self.vault_client.secrets.kv.v2.create_or_update_secret(
            path=metadata_path,
            secret=data
        )
    
    async def _audit_secret_access(self, audit: SecretAccessAudit):
        """Store secret access audit record"""
        audit_path = f"{self.audit_path}/access/{audit.access_id}"
        
        audit_data = audit.model_dump()
        audit_data['access_time'] = audit_data['access_time'].isoformat()
        audit_data['secret_type'] = audit_data['secret_type'].value
        
        self.vault_client.secrets.kv.v2.create_or_update_secret(
            path=audit_path,
            secret=audit_data
        )
    
    async def _generate_secret_value(self, secret_type: SecretType) -> str:
        """Generate a new secret value based on type"""
        if secret_type == SecretType.JWT_SECRET:
            return Fernet.generate_key().decode()
        elif secret_type == SecretType.API_KEY:
            return f"vh_{uuid.uuid4().hex}"
        elif secret_type == SecretType.ENCRYPTION_KEY:
            return Fernet.generate_key().decode()
        elif secret_type in [SecretType.DATABASE_PASSWORD, SecretType.REDIS_PASSWORD]:
            # Generate strong password
            import secrets
            import string
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            return ''.join(secrets.choice(alphabet) for _ in range(32))
        else:
            # Default: random hex string
            return uuid.uuid4().hex
    
    async def _backup_secret(self, secret_id: str, metadata: SecretMetadata):
        """Create backup of current secret before rotation"""
        try:
            # Get current secret value
            secret_path = f"{self.secrets_path}/{metadata.secret_type.value}/{secret_id}"
            response = self.vault_client.secrets.kv.v2.read_secret_version(path=secret_path)
            current_value = response['data']['data']['value']
            
            # Store backup
            backup_path = f"{self.secrets_path}/{metadata.secret_type.value}/{secret_id}/backups/{metadata.rotation_count}"
            self.vault_client.secrets.kv.v2.create_or_update_secret(
                path=backup_path,
                secret={
                    "value": current_value,
                    "backed_up_at": datetime.now(timezone.utc).isoformat(),
                    "rotation_count": metadata.rotation_count
                }
            )
            
        except Exception as e:
            logger.error("secret_backup_failed", secret_id=secret_id, error=str(e))
    
    async def _start_background_tasks(self):
        """Start background monitoring and rotation tasks"""
        self._running = True
        
        self._rotation_task = asyncio.create_task(self._rotation_monitor())
        self._monitoring_task = asyncio.create_task(self._health_monitor())
    
    async def _rotation_monitor(self):
        """Background task to monitor and trigger automatic rotations"""
        while self._running:
            try:
                await self._check_and_rotate_secrets()
                await asyncio.sleep(3600)  # Check every hour
            except Exception as e:
                logger.error("rotation_monitor_error", error=str(e))
                await asyncio.sleep(300)  # Wait 5 minutes on error
    
    async def _health_monitor(self):
        """Background task to monitor secrets health"""
        while self._running:
            try:
                report = await self.get_secrets_health_report()
                
                # Update metrics
                if report["overall_health"] == "healthy":
                    secrets_health_status.set(1)
                else:
                    secrets_health_status.set(0)
                
                # Check for expiring secrets
                for secret in report["expiring_soon"]:
                    secrets_expiry_warnings.labels(
                        secret_type=secret["secret_type"]
                    ).inc()
                
                await asyncio.sleep(1800)  # Check every 30 minutes
                
            except Exception as e:
                logger.error("health_monitor_error", error=str(e))
                secrets_health_status.set(0)
                await asyncio.sleep(300)
    
    async def shutdown(self):
        """Shutdown the secrets manager"""
        self._running = False
        
        if self._rotation_task:
            self._rotation_task.cancel()
        if self._monitoring_task:
            self._monitoring_task.cancel()
        
        logger.info("secrets_manager_shutdown")


# Global secrets manager instance
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> Optional[SecretsManager]:
    """Get the global secrets manager instance"""
    return _secrets_manager


async def initialize_secrets_manager(vault_client: hvac.Client, config: Dict[str, Any]) -> SecretsManager:
    """Initialize the global secrets manager"""
    global _secrets_manager
    
    _secrets_manager = SecretsManager(vault_client, config)
    
    if await _secrets_manager.initialize():
        return _secrets_manager
    else:
        raise RuntimeError("Failed to initialize secrets manager")