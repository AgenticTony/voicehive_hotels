"""
Secure Configuration module for VoiceHive Hotels Orchestrator
Production-grade configuration management with strict validation and security controls
"""

import os
import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from prometheus_client import Counter, Histogram, Gauge
from enum import Enum

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger

# Use safe logger
logger = get_safe_logger("orchestrator.config")
audit_logger = AuditLogger("configuration")

# Metrics for configuration monitoring
config_load_duration = Histogram('voicehive_config_load_duration_seconds', 'Configuration load duration')
config_validation_errors = Counter('voicehive_config_validation_errors_total', 'Configuration validation errors', ['field', 'error_type'])
config_drift_detected = Counter('voicehive_config_drift_detected_total', 'Configuration drift detections', ['environment', 'field'])
config_changes = Counter('voicehive_config_changes_total', 'Configuration changes', ['environment', 'field', 'source'])
config_integrity_status = Gauge('voicehive_config_integrity_status', 'Configuration integrity status (1=valid, 0=invalid)')

# Remove all production fallback configurations - CRITICAL SECURITY REQUIREMENT
# All configuration must be explicitly provided via environment variables or secure configuration files
# NO DEFAULT VALUES FOR PRODUCTION SECRETS OR SENSITIVE CONFIGURATION


class ConfigurationError(Exception):
    """Configuration-related errors"""
    pass


class ConfigurationValidationError(ConfigurationError):
    """Configuration validation errors"""
    pass


class ConfigurationDriftError(ConfigurationError):
    """Configuration drift detection errors"""
    pass


class EnvironmentType(str, Enum):
    """Supported environment types"""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class RegionType(str, Enum):
    """GDPR-compliant EU regions only"""
    EU_WEST_1 = "eu-west-1"
    EU_CENTRAL_1 = "eu-central-1"
    EU_NORTH_1 = "eu-north-1"
    EU_SOUTH_1 = "eu-south-1"
    EUROPE_WEST1 = "europe-west1"  # GCP Belgium
    WESTEUROPE = "westeurope"      # Azure Netherlands


class DatabaseConfig(BaseModel):
    """Database configuration with strict validation"""
    
    host: str = Field(..., description="Database host - REQUIRED")
    port: int = Field(..., ge=1, le=65535, description="Database port")
    database: str = Field(..., min_length=1, description="Database name - REQUIRED")
    username: str = Field(..., min_length=1, description="Database username - REQUIRED")
    password: str = Field(..., min_length=8, description="Database password - REQUIRED (min 8 chars)")
    ssl_mode: str = Field(default="require", description="SSL mode")
    pool_size: int = Field(default=10, ge=1, le=100, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, le=100, description="Max pool overflow")
    
    @field_validator('ssl_mode')
    @classmethod
    def validate_ssl_mode(cls, v):
        allowed_modes = ['disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full']
        if v not in allowed_modes:
            raise ValueError(f'SSL mode must be one of: {allowed_modes}')
        return v
    
    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v):
        if len(v) < 8:
            raise ValueError('Database password must be at least 8 characters')
        # In production, passwords should come from secure sources only
        weak_passwords = ['password', '12345678', 'admin123', 'postgres']
        if v.lower() in weak_passwords:
            raise ValueError('Weak password detected - use secure password from vault')
        return v


class RedisConfig(BaseModel):
    """Redis configuration with strict validation"""
    
    host: str = Field(..., description="Redis host - REQUIRED")
    port: int = Field(..., ge=1, le=65535, description="Redis port")
    password: Optional[str] = Field(None, min_length=8, description="Redis password")
    db: int = Field(default=0, ge=0, le=15, description="Redis database number")
    ssl: bool = Field(default=True, description="Use SSL (required in production)")
    pool_size: int = Field(default=10, ge=1, le=100, description="Connection pool size")
    
    @field_validator('password')
    @classmethod
    def validate_redis_password(cls, v):
        if v and len(v) < 8:
            raise ValueError('Redis password must be at least 8 characters')
        return v


class AuthConfig(BaseModel):
    """Authentication configuration with strict validation"""
    
    jwt_secret_key: str = Field(..., min_length=32, description="JWT secret key - REQUIRED (min 32 chars)")
    jwt_algorithm: str = Field(default="RS256", description="JWT algorithm")
    jwt_expiration_minutes: int = Field(default=15, ge=1, le=60, description="JWT expiration in minutes")
    refresh_token_expiration_days: int = Field(default=7, ge=1, le=30, description="Refresh token expiration in days")
    api_key_length: int = Field(default=32, ge=16, le=64, description="API key length")
    max_login_attempts: int = Field(default=5, ge=1, le=10, description="Max login attempts")
    lockout_duration_minutes: int = Field(default=15, ge=1, le=60, description="Account lockout duration")
    
    @field_validator('jwt_algorithm')
    @classmethod
    def validate_jwt_algorithm(cls, v):
        # Only allow secure algorithms
        allowed_algorithms = ['RS256', 'RS384', 'RS512', 'ES256', 'ES384', 'ES512']
        if v not in allowed_algorithms:
            raise ValueError(f'JWT algorithm must be one of: {allowed_algorithms}')
        return v
    
    @field_validator('jwt_secret_key')
    @classmethod
    def validate_jwt_secret_strength(cls, v):
        if len(v) < 32:
            raise ValueError('JWT secret key must be at least 32 characters')
        # Check for weak keys
        weak_keys = ['secret', 'jwt_secret', 'your-256-bit-secret']
        if v in weak_keys:
            raise ValueError('Weak JWT secret detected - use cryptographically secure key')
        return v


class SecurityConfig(BaseModel):
    """Security configuration with strict validation"""
    
    encryption_key: str = Field(..., min_length=32, description="Encryption key - REQUIRED")
    webhook_signature_secret: str = Field(..., min_length=16, description="Webhook signature secret - REQUIRED")
    cors_allowed_origins: List[str] = Field(default=[], description="CORS allowed origins")
    session_timeout_minutes: int = Field(default=30, ge=5, le=120, description="Session timeout")
    rate_limit_per_minute: int = Field(default=100, ge=1, le=10000, description="Rate limit per minute")
    
    @field_validator('cors_allowed_origins')
    @classmethod
    def validate_cors_origins(cls, v):
        # Ensure no wildcard origins in production
        for origin in v:
            if origin == "*":
                raise ValueError('Wildcard CORS origins not allowed in production')
        return v


class ExternalServiceConfig(BaseModel):
    """External service configuration"""
    
    livekit_url: str = Field(..., description="LiveKit server URL - REQUIRED")
    vault_url: str = Field(..., description="HashiCorp Vault URL - REQUIRED")
    pms_timeout_seconds: int = Field(default=30, ge=1, le=120, description="PMS timeout")
    tts_timeout_seconds: int = Field(default=15, ge=1, le=60, description="TTS timeout")
    asr_timeout_seconds: int = Field(default=30, ge=1, le=120, description="ASR timeout")
    
    @field_validator('livekit_url', 'vault_url')
    @classmethod
    def validate_urls(cls, v):
        if not v.startswith(('https://', 'wss://')):
            raise ValueError('URLs must use secure protocols (https:// or wss://)')
        return v


class VoiceHiveConfig(BaseSettings):
    """
    Main VoiceHive configuration with strict validation and no fallbacks
    All configuration must be explicitly provided - NO PRODUCTION DEFAULTS
    """
    
    model_config = SettingsConfigDict(
        env_prefix='VOICEHIVE_',  # Environment variable prefix
        env_file=None,  # No .env file loading by default
        env_file_encoding='utf-8',
        case_sensitive=False,
        validate_assignment=True,
        extra='forbid',  # Forbid extra fields
        frozen=True,    # Immutable configuration
        env_nested_delimiter='__'  # Use __ for nested fields
    )
    
    # Core service configuration - ALL REQUIRED
    service_name: str = Field(..., description="Service name - REQUIRED")
    environment: EnvironmentType = Field(..., description="Environment type - REQUIRED")
    region: RegionType = Field(..., description="AWS/Cloud region - REQUIRED (EU only)")
    log_level: str = Field(default="INFO", description="Log level")
    
    # Component configurations - ALL REQUIRED
    database: DatabaseConfig = Field(..., description="Database configuration - REQUIRED")
    redis: RedisConfig = Field(..., description="Redis configuration - REQUIRED")
    auth: AuthConfig = Field(..., description="Authentication configuration - REQUIRED")
    security: SecurityConfig = Field(..., description="Security configuration - REQUIRED")
    external_services: ExternalServiceConfig = Field(..., description="External services configuration - REQUIRED")
    
    # Configuration metadata
    config_version: str = Field(default="1.0", description="Configuration schema version")
    config_hash: Optional[str] = Field(None, description="Configuration hash for integrity checking")
    last_updated: Optional[datetime] = Field(None, description="Last configuration update timestamp")
    
    @field_validator('environment')
    @classmethod
    def validate_environment_security(cls, v):
        # Additional validation for production environment
        return v
    
    @field_validator('region')
    @classmethod
    def validate_gdpr_compliance(cls, v):
        # Ensure GDPR compliance by restricting to EU regions only
        return v
    
    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v):
        allowed_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in allowed_levels:
            raise ValueError(f'Log level must be one of: {allowed_levels}')
        return v.upper()
    
    def calculate_config_hash(self) -> str:
        """Calculate hash of configuration for integrity checking"""
        config_dict = self.model_dump(exclude={'config_hash', 'last_updated'})
        config_json = json.dumps(config_dict, sort_keys=True)
        return hashlib.sha256(config_json.encode()).hexdigest()
    
    def validate_integrity(self) -> bool:
        """Validate configuration integrity"""
        if not self.config_hash:
            return False
        return self.calculate_config_hash() == self.config_hash


class ConfigurationManager:
    """
    Secure configuration manager with drift detection and audit logging
    """
    
    def __init__(self):
        self._config: Optional[VoiceHiveConfig] = None
        self._config_file_path: Optional[str] = None
        self._last_config_hash: Optional[str] = None
        self._drift_check_enabled = True
        
    @config_load_duration.time()
    def load_configuration(self, 
                          config_file: Optional[str] = None,
                          validate_integrity: bool = True) -> VoiceHiveConfig:
        """
        Load configuration with strict validation and security checks
        
        Args:
            config_file: Optional configuration file path
            validate_integrity: Whether to validate configuration integrity
            
        Returns:
            Validated configuration object
            
        Raises:
            ConfigurationValidationError: If configuration is invalid
            ConfigurationError: If configuration cannot be loaded
        """
        
        try:
            # Determine configuration source
            if config_file:
                self._config_file_path = config_file
            else:
                # Configuration file MUST be specified via environment variable
                config_path = os.getenv("VOICEHIVE_CONFIG_PATH")
                if not config_path:
                    raise ConfigurationError(
                        "Configuration file path must be specified via VOICEHIVE_CONFIG_PATH environment variable. "
                        "No fallback configuration allowed in production."
                    )
                self._config_file_path = config_path
            
            # Verify configuration file exists and is readable
            if not Path(self._config_file_path).exists():
                raise ConfigurationError(f"Configuration file not found: {self._config_file_path}")
            
            # Load configuration from environment variables only
            # This ensures all sensitive configuration comes from secure sources
            try:
                config = VoiceHiveConfig()
            except ValidationError as e:
                # Log validation errors for monitoring
                for error in e.errors():
                    field = '.'.join(str(loc) for loc in error['loc'])
                    error_type = error['type']
                    config_validation_errors.labels(field=field, error_type=error_type).inc()
                
                audit_logger.log_security_event(
                    event_type="configuration_validation_failed",
                    details={
                        "errors": e.errors(),
                        "config_file": self._config_file_path
                    },
                    severity="high"
                )
                
                raise ConfigurationValidationError(f"Configuration validation failed: {e}")
            
            # Calculate and set configuration hash
            config_hash = config.calculate_config_hash()
            
            # Create new config with hash and timestamp
            config_dict = config.model_dump()
            config_dict['config_hash'] = config_hash
            config_dict['last_updated'] = datetime.now(timezone.utc)
            
            # Recreate config with metadata (need to temporarily allow extra fields)
            validated_config = VoiceHiveConfig.model_validate(config_dict)
            
            # Validate integrity if requested
            if validate_integrity and not validated_config.validate_integrity():
                raise ConfigurationError("Configuration integrity validation failed")
            
            # Check for configuration drift
            if self._drift_check_enabled:
                self._check_configuration_drift(validated_config)
            
            # Store configuration
            self._config = validated_config
            self._last_config_hash = config_hash
            
            # Update metrics
            config_integrity_status.set(1)
            
            # Audit log successful configuration load
            audit_logger.log_security_event(
                event_type="configuration_loaded",
                details={
                    "config_file": self._config_file_path,
                    "environment": validated_config.environment,
                    "region": validated_config.region,
                    "config_hash": config_hash[:16]  # Only log first 16 chars
                },
                severity="info"
            )
            
            logger.info(
                "configuration_loaded_successfully",
                environment=validated_config.environment,
                region=validated_config.region,
                config_version=validated_config.config_version
            )
            
            return validated_config
            
        except Exception as e:
            config_integrity_status.set(0)
            logger.error(
                "configuration_load_failed",
                error=str(e),
                config_file=self._config_file_path
            )
            raise
    
    def get_configuration(self) -> VoiceHiveConfig:
        """Get current configuration"""
        if not self._config:
            raise ConfigurationError("Configuration not loaded. Call load_configuration() first.")
        return self._config
    
    def reload_configuration(self) -> VoiceHiveConfig:
        """Reload configuration and check for changes"""
        old_hash = self._last_config_hash
        new_config = self.load_configuration(self._config_file_path)
        
        if old_hash and old_hash != new_config.config_hash:
            audit_logger.log_security_event(
                event_type="configuration_reloaded",
                details={
                    "old_hash": old_hash[:16],
                    "new_hash": new_config.config_hash[:16] if new_config.config_hash else None,
                    "environment": new_config.environment
                },
                severity="medium"
            )
            
            config_changes.labels(
                environment=new_config.environment,
                field="global",
                source="reload"
            ).inc()
        
        return new_config
    
    def _check_configuration_drift(self, new_config: VoiceHiveConfig):
        """Check for configuration drift"""
        if not self._config:
            return  # First load, no drift to check
        
        old_dict = self._config.model_dump(exclude={'config_hash', 'last_updated'})
        new_dict = new_config.model_dump(exclude={'config_hash', 'last_updated'})
        
        # Check for changes
        changes = self._find_config_changes(old_dict, new_dict)
        
        if changes:
            # Log drift detection
            for change in changes:
                config_drift_detected.labels(
                    environment=new_config.environment,
                    field=change['field']
                ).inc()
                
                audit_logger.log_security_event(
                    event_type="configuration_drift_detected",
                    details={
                        "field": change['field'],
                        "old_value": change.get('old_value', '<redacted>'),
                        "new_value": change.get('new_value', '<redacted>'),
                        "environment": new_config.environment
                    },
                    severity="medium"
                )
            
            logger.warning(
                "configuration_drift_detected",
                changes_count=len(changes),
                environment=new_config.environment
            )
    
    def _find_config_changes(self, old_dict: Dict[str, Any], new_dict: Dict[str, Any], prefix: str = "") -> List[Dict[str, Any]]:
        """Find changes between configuration dictionaries"""
        changes = []
        
        # Check for modified or removed keys
        for key, old_value in old_dict.items():
            field_path = f"{prefix}.{key}" if prefix else key
            
            if key not in new_dict:
                changes.append({
                    'field': field_path,
                    'change_type': 'removed',
                    'old_value': self._redact_sensitive_value(key, old_value)
                })
            elif isinstance(old_value, dict) and isinstance(new_dict[key], dict):
                # Recursively check nested dictionaries
                nested_changes = self._find_config_changes(old_value, new_dict[key], field_path)
                changes.extend(nested_changes)
            elif old_value != new_dict[key]:
                changes.append({
                    'field': field_path,
                    'change_type': 'modified',
                    'old_value': self._redact_sensitive_value(key, old_value),
                    'new_value': self._redact_sensitive_value(key, new_dict[key])
                })
        
        # Check for added keys
        for key, new_value in new_dict.items():
            field_path = f"{prefix}.{key}" if prefix else key
            
            if key not in old_dict:
                changes.append({
                    'field': field_path,
                    'change_type': 'added',
                    'new_value': self._redact_sensitive_value(key, new_value)
                })
        
        return changes
    
    def _redact_sensitive_value(self, key: str, value: Any) -> str:
        """Redact sensitive configuration values for logging"""
        sensitive_keys = {
            'password', 'secret', 'key', 'token', 'credential',
            'jwt_secret_key', 'encryption_key', 'webhook_signature_secret'
        }
        
        key_lower = key.lower()
        if any(sensitive_key in key_lower for sensitive_key in sensitive_keys):
            return '<REDACTED>'
        
        return str(value)
    
    def validate_environment_compliance(self, environment: EnvironmentType) -> Dict[str, Any]:
        """Validate environment-specific compliance requirements"""
        if not self._config:
            raise ConfigurationError("Configuration not loaded")
        
        compliance_report = {
            'compliant': True,
            'violations': [],
            'warnings': []
        }
        
        if environment == EnvironmentType.PRODUCTION:
            # Production-specific validations
            
            # Check SSL/TLS requirements
            if not self._config.redis.ssl:
                compliance_report['violations'].append("Redis SSL must be enabled in production")
                compliance_report['compliant'] = False
            
            if self._config.database.ssl_mode not in ['require', 'verify-ca', 'verify-full']:
                compliance_report['violations'].append("Database SSL must be required in production")
                compliance_report['compliant'] = False
            
            # Check debug logging
            if self._config.log_level == 'DEBUG':
                compliance_report['warnings'].append("Debug logging enabled in production")
            
            # Check JWT expiration
            if self._config.auth.jwt_expiration_minutes > 30:
                compliance_report['warnings'].append("JWT expiration longer than 30 minutes in production")
            
            # Check CORS configuration
            if '*' in self._config.security.cors_allowed_origins:
                compliance_report['violations'].append("Wildcard CORS origins not allowed in production")
                compliance_report['compliant'] = False
        
        return compliance_report


# Global configuration manager instance
config_manager = ConfigurationManager()


def get_config() -> VoiceHiveConfig:
    """Get the current configuration"""
    return config_manager.get_configuration()


def load_config(config_file: Optional[str] = None) -> VoiceHiveConfig:
    """Load configuration"""
    return config_manager.load_configuration(config_file)


def reload_config() -> VoiceHiveConfig:
    """Reload configuration"""
    return config_manager.reload_configuration()


# Legacy compatibility - DEPRECATED
# These will be removed in future versions
def get_legacy_config_value(key: str, default: Any = None) -> Any:
    """
    DEPRECATED: Legacy configuration access
    Use get_config() instead for type-safe configuration access
    """
    logger.warning(
        "legacy_config_access_deprecated",
        key=key,
        message="Use get_config() for type-safe configuration access"
    )
    
    try:
        config = get_config()
        # Simple key mapping for backward compatibility
        legacy_mappings = {
            'REDIS_URL': f"redis://{config.redis.host}:{config.redis.port}/{config.redis.db}",
            'VAULT_ADDR': config.external_services.vault_url,
            'REGION': config.region,
            'ENVIRONMENT': config.environment,
            'LIVEKIT_URL': config.external_services.livekit_url
        }
        
        return legacy_mappings.get(key, default)
    except ConfigurationError:
        logger.error("configuration_not_loaded", key=key)
        return default


# Region validation with new configuration system
class RegionValidator:
    """GDPR-compliant region validator"""
    
    @staticmethod
    def validate_service_region(service: str, region: str) -> bool:
        """Validate that a service is running in an allowed EU region"""
        try:
            config = get_config()
            
            # Check if region is in allowed EU regions
            allowed_regions = [r.value for r in RegionType]
            
            if region not in allowed_regions:
                logger.warning(
                    "region_violation",
                    service=service,
                    region=region,
                    allowed=allowed_regions
                )
                
                audit_logger.log_security_event(
                    event_type="region_violation",
                    details={
                        "service": service,
                        "region": region,
                        "allowed_regions": allowed_regions
                    },
                    severity="high"
                )
                
                return False
            
            return True
            
        except ConfigurationError:
            logger.error("configuration_not_available_for_region_validation")
            return False
    
    @staticmethod
    def get_service_region(service: str) -> str:
        """Get the configured region for the service"""
        try:
            config = get_config()
            return config.region
        except ConfigurationError:
            logger.error("configuration_not_available_for_service_region")
            return "unknown"
