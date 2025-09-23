"""
Secure Configuration Management for VoiceHive Hotels
Provides secure configuration loading, validation, and management with encryption support
"""

import os
import json
import yaml
from typing import Dict, Any, Optional, List, Union, Type, get_type_hints
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import base64
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None
    
from pydantic import BaseModel, Field, validator, ValidationError

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.secure_config")


class ConfigSensitivity(str, Enum):
    """Sensitivity levels for configuration values"""
    PUBLIC = "public"           # Can be logged and displayed
    INTERNAL = "internal"       # Internal use, don't log
    SENSITIVE = "sensitive"     # Encrypt at rest, redact in logs
    SECRET = "secret"          # Encrypt at rest, never log


class ConfigSource(str, Enum):
    """Sources for configuration values"""
    FILE = "file"              # Configuration file
    ENVIRONMENT = "environment" # Environment variables
    VAULT = "vault"            # HashiCorp Vault
    KUBERNETES = "kubernetes"   # Kubernetes secrets
    DEFAULT = "default"        # Default values


@dataclass
class ConfigField:
    """Configuration field metadata"""
    
    name: str
    sensitivity: ConfigSensitivity
    required: bool = True
    default: Any = None
    description: str = ""
    validation_pattern: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    allowed_values: Optional[List[Any]] = None
    env_var: Optional[str] = None
    vault_path: Optional[str] = None
    
    def __post_init__(self):
        """Set default environment variable name if not provided"""
        if self.env_var is None:
            self.env_var = self.name.upper().replace(".", "_")


class SecureConfigSchema(BaseModel):
    """Base class for secure configuration schemas"""
    
    class Config:
        # Validate assignment
        validate_assignment = True
        # Use enum values
        use_enum_values = True
        # Extra fields forbidden
        extra = "forbid"
    
    def get_field_sensitivity(self, field_name: str) -> ConfigSensitivity:
        """Get sensitivity level for a field"""
        # This would be overridden in subclasses or use metadata
        return ConfigSensitivity.INTERNAL
    
    def to_safe_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with sensitive fields redacted"""
        result = {}
        for field_name, value in self.dict().items():
            sensitivity = self.get_field_sensitivity(field_name)
            
            if sensitivity == ConfigSensitivity.PUBLIC:
                result[field_name] = value
            elif sensitivity == ConfigSensitivity.INTERNAL:
                result[field_name] = value
            elif sensitivity == ConfigSensitivity.SENSITIVE:
                result[field_name] = "<REDACTED_SENSITIVE>"
            elif sensitivity == ConfigSensitivity.SECRET:
                result[field_name] = "<REDACTED_SECRET>"
        
        return result


class DatabaseConfig(SecureConfigSchema):
    """Database configuration schema"""
    
    host: str = Field(..., description="Database host")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    database: str = Field(..., description="Database name")
    username: str = Field(..., description="Database username")
    password: str = Field(..., description="Database password")
    ssl_mode: str = Field(default="require", description="SSL mode")
    pool_size: int = Field(default=10, ge=1, le=100, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, le=100, description="Max pool overflow")
    
    def get_field_sensitivity(self, field_name: str) -> ConfigSensitivity:
        sensitive_fields = {"password"}
        if field_name in sensitive_fields:
            return ConfigSensitivity.SECRET
        return ConfigSensitivity.INTERNAL


class RedisConfig(SecureConfigSchema):
    """Redis configuration schema"""
    
    host: str = Field(default="localhost", description="Redis host")
    port: int = Field(default=6379, ge=1, le=65535, description="Redis port")
    password: Optional[str] = Field(default=None, description="Redis password")
    db: int = Field(default=0, ge=0, le=15, description="Redis database number")
    ssl: bool = Field(default=False, description="Use SSL")
    pool_size: int = Field(default=10, ge=1, le=100, description="Connection pool size")
    
    def get_field_sensitivity(self, field_name: str) -> ConfigSensitivity:
        sensitive_fields = {"password"}
        if field_name in sensitive_fields:
            return ConfigSensitivity.SECRET
        return ConfigSensitivity.INTERNAL


class AuthConfig(SecureConfigSchema):
    """Authentication configuration schema"""
    
    jwt_secret_key: str = Field(..., description="JWT secret key")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expiration_minutes: int = Field(default=15, ge=1, le=1440, description="JWT expiration in minutes")
    refresh_token_expiration_days: int = Field(default=30, ge=1, le=365, description="Refresh token expiration in days")
    password_min_length: int = Field(default=8, ge=6, le=128, description="Minimum password length")
    max_login_attempts: int = Field(default=5, ge=1, le=20, description="Max login attempts before lockout")
    lockout_duration_minutes: int = Field(default=15, ge=1, le=1440, description="Account lockout duration")
    
    def get_field_sensitivity(self, field_name: str) -> ConfigSensitivity:
        secret_fields = {"jwt_secret_key"}
        if field_name in secret_fields:
            return ConfigSensitivity.SECRET
        return ConfigSensitivity.INTERNAL


class SecurityConfig(SecureConfigSchema):
    """Security configuration schema"""
    
    encryption_key: str = Field(..., description="Encryption key for sensitive data")
    api_rate_limit_per_minute: int = Field(default=100, ge=1, le=10000, description="API rate limit per minute")
    webhook_signature_secret: str = Field(..., description="Webhook signature secret")
    cors_allowed_origins: List[str] = Field(default=["https://*.voicehive-hotels.eu"], description="CORS allowed origins")
    session_timeout_minutes: int = Field(default=30, ge=5, le=480, description="Session timeout in minutes")
    
    def get_field_sensitivity(self, field_name: str) -> ConfigSensitivity:
        secret_fields = {"encryption_key", "webhook_signature_secret"}
        if field_name in secret_fields:
            return ConfigSensitivity.SECRET
        return ConfigSensitivity.INTERNAL


class VoiceHiveConfig(SecureConfigSchema):
    """Main VoiceHive configuration schema"""
    
    # Service configuration
    service_name: str = Field(default="voicehive-orchestrator", description="Service name")
    environment: str = Field(default="production", description="Environment")
    region: str = Field(default="eu-west-1", description="AWS region")
    log_level: str = Field(default="INFO", description="Log level")
    
    # Component configurations
    database: DatabaseConfig
    redis: RedisConfig
    auth: AuthConfig
    security: SecurityConfig
    
    # External service URLs
    livekit_url: str = Field(..., description="LiveKit server URL")
    vault_url: str = Field(default="http://localhost:8200", description="HashiCorp Vault URL")
    
    @validator('environment')
    def validate_environment(cls, v):
        allowed_envs = ['development', 'staging', 'production']
        if v not in allowed_envs:
            raise ValueError(f'Environment must be one of: {allowed_envs}')
        return v
    
    @validator('region')
    def validate_region(cls, v):
        # Ensure EU regions for GDPR compliance
        eu_regions = ['eu-west-1', 'eu-central-1', 'eu-north-1', 'eu-south-1']
        if v not in eu_regions:
            raise ValueError(f'Region must be an EU region: {eu_regions}')
        return v


class SecureConfigManager:
    """Secure configuration manager with encryption and validation"""
    
    def __init__(self, 
                 config_file: Optional[str] = None,
                 encryption_key: Optional[str] = None,
                 vault_client: Optional[Any] = None):
        
        self.config_file = config_file
        self.vault_client = vault_client
        
        # Initialize encryption
        if encryption_key and CRYPTOGRAPHY_AVAILABLE:
            self.cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        else:
            self.cipher = None
            if encryption_key and not CRYPTOGRAPHY_AVAILABLE:
                logger.warning("Cryptography library not available, encryption disabled")
        
        # Configuration cache
        self._config_cache: Dict[str, Any] = {}
        
        # Field metadata
        self._field_metadata: Dict[str, ConfigField] = {}
    
    def load_config(self, schema_class: Type[SecureConfigSchema]) -> SecureConfigSchema:
        """
        Load and validate configuration from multiple sources
        
        Args:
            schema_class: Pydantic schema class for validation
            
        Returns:
            Validated configuration object
        """
        
        # Collect configuration from all sources
        config_data = {}
        
        # 1. Load from file
        if self.config_file:
            file_config = self._load_from_file(self.config_file)
            config_data.update(file_config)
        
        # 2. Load from environment variables
        env_config = self._load_from_environment(schema_class)
        config_data.update(env_config)
        
        # 3. Load from Vault (if available)
        if self.vault_client:
            vault_config = self._load_from_vault(schema_class)
            config_data.update(vault_config)
        
        # 4. Decrypt sensitive values
        config_data = self._decrypt_sensitive_values(config_data)
        
        # 5. Validate configuration
        try:
            config = schema_class(**config_data)
            
            # Log successful configuration load (with redaction)
            logger.info(
                "configuration_loaded",
                schema=schema_class.__name__,
                sources=self._get_config_sources(config_data),
                fields_count=len(config_data)
            )
            
            return config
            
        except ValidationError as e:
            logger.error(
                "configuration_validation_failed",
                schema=schema_class.__name__,
                errors=e.errors()
            )
            raise
    
    def save_config(self, config: SecureConfigSchema, file_path: Optional[str] = None):
        """
        Save configuration to file with encryption for sensitive fields
        
        Args:
            config: Configuration object to save
            file_path: Optional file path (uses default if not provided)
        """
        
        file_path = file_path or self.config_file
        if not file_path:
            raise ValueError("No file path provided for saving configuration")
        
        # Convert to dictionary and encrypt sensitive fields
        config_dict = config.dict()
        encrypted_dict = self._encrypt_sensitive_values(config_dict, config)
        
        # Save to file
        try:
            with open(file_path, 'w') as f:
                if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                    yaml.dump(encrypted_dict, f, default_flow_style=False)
                else:
                    json.dump(encrypted_dict, f, indent=2)
            
            logger.info(
                "configuration_saved",
                file_path=file_path,
                fields_count=len(config_dict)
            )
            
        except Exception as e:
            logger.error(
                "configuration_save_failed",
                file_path=file_path,
                error=str(e)
            )
            raise
    
    def get_config_value(self, key: str, default: Any = None, decrypt: bool = True) -> Any:
        """
        Get a specific configuration value
        
        Args:
            key: Configuration key (dot notation supported)
            default: Default value if key not found
            decrypt: Whether to decrypt the value if encrypted
            
        Returns:
            Configuration value
        """
        
        # Check cache first
        if key in self._config_cache:
            value = self._config_cache[key]
        else:
            # Load from sources
            value = self._get_value_from_sources(key, default)
            self._config_cache[key] = value
        
        # Decrypt if needed
        if decrypt and self.cipher and isinstance(value, str) and value.startswith('encrypted:'):
            try:
                encrypted_data = base64.b64decode(value[10:])  # Remove 'encrypted:' prefix
                value = self.cipher.decrypt(encrypted_data).decode()
            except Exception as e:
                logger.error(f"Failed to decrypt configuration value for key '{key}': {e}")
                return default
        
        return value
    
    def set_config_value(self, key: str, value: Any, encrypt: bool = False):
        """
        Set a configuration value
        
        Args:
            key: Configuration key
            value: Value to set
            encrypt: Whether to encrypt the value
        """
        
        if encrypt and self.cipher:
            encrypted_data = self.cipher.encrypt(str(value).encode())
            value = 'encrypted:' + base64.b64encode(encrypted_data).decode()
        
        self._config_cache[key] = value
        
        logger.info(
            "configuration_value_set",
            key=key,
            encrypted=encrypt
        )
    
    def validate_config_integrity(self, config: SecureConfigSchema) -> Dict[str, Any]:
        """
        Validate configuration integrity and security
        
        Args:
            config: Configuration to validate
            
        Returns:
            Validation report
        """
        
        report = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "security_issues": []
        }
        
        config_dict = config.dict()
        
        # Check for insecure values
        for field_name, value in config_dict.items():
            sensitivity = config.get_field_sensitivity(field_name)
            
            # Check for default/weak passwords
            if sensitivity == ConfigSensitivity.SECRET and isinstance(value, str):
                if value in ['password', '123456', 'admin', 'secret']:
                    report["security_issues"].append(f"Weak {field_name}: using default/weak value")
                    report["valid"] = False
                
                if len(value) < 8:
                    report["security_issues"].append(f"Short {field_name}: less than 8 characters")
                    report["valid"] = False
        
        # Environment-specific checks
        if hasattr(config, 'environment'):
            if config.environment == 'production':
                # Production-specific validations
                if hasattr(config, 'log_level') and config.log_level == 'DEBUG':
                    report["warnings"].append("Debug logging enabled in production")
        
        return report
    
    def _load_from_file(self, file_path: str) -> Dict[str, Any]:
        """Load configuration from file"""
        
        if not Path(file_path).exists():
            logger.warning(f"Configuration file not found: {file_path}")
            return {}
        
        try:
            with open(file_path, 'r') as f:
                if file_path.endswith('.yaml') or file_path.endswith('.yml'):
                    return yaml.safe_load(f) or {}
                else:
                    return json.load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load configuration from {file_path}: {e}")
            return {}
    
    def _load_from_environment(self, schema_class: Type[SecureConfigSchema]) -> Dict[str, Any]:
        """Load configuration from environment variables"""
        
        config_data = {}
        
        # Get type hints from schema
        type_hints = get_type_hints(schema_class)
        
        for field_name, field_type in type_hints.items():
            env_var = field_name.upper().replace(".", "_")
            env_value = os.getenv(env_var)
            
            if env_value is not None:
                # Convert string to appropriate type
                try:
                    if field_type == bool:
                        config_data[field_name] = env_value.lower() in ('true', '1', 'yes', 'on')
                    elif field_type == int:
                        config_data[field_name] = int(env_value)
                    elif field_type == float:
                        config_data[field_name] = float(env_value)
                    elif field_type == list:
                        config_data[field_name] = env_value.split(',')
                    else:
                        config_data[field_name] = env_value
                except ValueError as e:
                    logger.warning(f"Failed to convert environment variable {env_var}: {e}")
        
        return config_data
    
    def _load_from_vault(self, schema_class: Type[SecureConfigSchema]) -> Dict[str, Any]:
        """Load configuration from HashiCorp Vault"""
        
        if not self.vault_client:
            return {}
        
        config_data = {}
        
        try:
            # This would integrate with actual Vault client
            # For now, return empty dict
            logger.info("Vault configuration loading not implemented yet")
        except Exception as e:
            logger.error(f"Failed to load configuration from Vault: {e}")
        
        return config_data
    
    def _decrypt_sensitive_values(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt sensitive configuration values"""
        
        if not self.cipher:
            return config_data
        
        decrypted_data = {}
        
        for key, value in config_data.items():
            if isinstance(value, str) and value.startswith('encrypted:'):
                try:
                    encrypted_data = base64.b64decode(value[10:])
                    decrypted_value = self.cipher.decrypt(encrypted_data).decode()
                    decrypted_data[key] = decrypted_value
                except Exception as e:
                    logger.error(f"Failed to decrypt configuration value for key '{key}': {e}")
                    decrypted_data[key] = value
            elif isinstance(value, dict):
                decrypted_data[key] = self._decrypt_sensitive_values(value)
            else:
                decrypted_data[key] = value
        
        return decrypted_data
    
    def _encrypt_sensitive_values(self, config_data: Dict[str, Any], config: SecureConfigSchema) -> Dict[str, Any]:
        """Encrypt sensitive configuration values"""
        
        if not self.cipher:
            return config_data
        
        encrypted_data = {}
        
        for key, value in config_data.items():
            sensitivity = config.get_field_sensitivity(key)
            
            if sensitivity in [ConfigSensitivity.SENSITIVE, ConfigSensitivity.SECRET] and isinstance(value, str):
                encrypted_bytes = self.cipher.encrypt(value.encode())
                encrypted_data[key] = 'encrypted:' + base64.b64encode(encrypted_bytes).decode()
            elif isinstance(value, dict):
                # Recursively handle nested objects
                encrypted_data[key] = value  # Would need schema for nested objects
            else:
                encrypted_data[key] = value
        
        return encrypted_data
    
    def _get_config_sources(self, config_data: Dict[str, Any]) -> List[str]:
        """Get list of configuration sources used"""
        sources = []
        
        if self.config_file and Path(self.config_file).exists():
            sources.append("file")
        
        # Check if any environment variables were used
        for key in config_data.keys():
            env_var = key.upper().replace(".", "_")
            if os.getenv(env_var):
                sources.append("environment")
                break
        
        if self.vault_client:
            sources.append("vault")
        
        return sources
    
    def _get_value_from_sources(self, key: str, default: Any) -> Any:
        """Get configuration value from all sources with precedence"""
        
        # 1. Environment variable (highest precedence)
        env_var = key.upper().replace(".", "_")
        env_value = os.getenv(env_var)
        if env_value is not None:
            return env_value
        
        # 2. Vault (if available)
        if self.vault_client:
            # Would implement Vault lookup
            pass
        
        # 3. Configuration file
        if self.config_file:
            file_config = self._load_from_file(self.config_file)
            if key in file_config:
                return file_config[key]
        
        # 4. Default value
        return default


# Utility functions
def generate_encryption_key() -> str:
    """Generate a new encryption key for configuration"""
    if not CRYPTOGRAPHY_AVAILABLE:
        raise ImportError("Cryptography library required for encryption key generation")
    return Fernet.generate_key().decode()


def derive_key_from_password(password: str, salt: Optional[bytes] = None) -> str:
    """Derive encryption key from password"""
    if not CRYPTOGRAPHY_AVAILABLE:
        raise ImportError("Cryptography library required for key derivation")
        
    if salt is None:
        salt = os.urandom(16)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key.decode()


# Example usage
if __name__ == "__main__":
    # Test secure configuration management
    
    # Create sample configuration
    config_data = {
        "database": {
            "host": "localhost",
            "port": 5432,
            "database": "voicehive",
            "username": "app_user",
            "password": "secure_password_123"
        },
        "redis": {
            "host": "localhost",
            "port": 6379,
            "password": "redis_password_456"
        },
        "auth": {
            "jwt_secret_key": "super_secret_jwt_key_789",
            "jwt_expiration_minutes": 15
        },
        "security": {
            "encryption_key": "encryption_key_012",
            "webhook_signature_secret": "webhook_secret_345"
        },
        "livekit_url": "wss://livekit.example.com"
    }
    
    # Create configuration manager
    encryption_key = generate_encryption_key()
    manager = SecureConfigManager(encryption_key=encryption_key)
    
    # Load and validate configuration
    try:
        config = VoiceHiveConfig(**config_data)
        print("Configuration loaded successfully")
        
        # Validate integrity
        report = manager.validate_config_integrity(config)
        print(f"Validation report: {report}")
        
        # Test safe dictionary conversion
        safe_dict = config.to_safe_dict()
        print(f"Safe config (redacted): {json.dumps(safe_dict, indent=2)}")
        
    except ValidationError as e:
        print(f"Configuration validation failed: {e}")