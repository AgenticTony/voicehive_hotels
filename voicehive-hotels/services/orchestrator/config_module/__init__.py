"""
Configuration Management module for VoiceHive Hotels Orchestrator

This module provides secure configuration management including environment validation,
drift monitoring, change approval workflows, and immutable configuration versioning.
"""

# Import from parent directory's config.py file
import sys
from pathlib import Path

# Add parent directory to path to access config.py
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

# Import directly from config.py in parent directory
try:
    import config as parent_config

    # Re-export main config classes and functions
    Config = parent_config.VoiceHiveConfig
    get_config = parent_config.get_config
    load_config = parent_config.load_config
    ConfigurationError = parent_config.ConfigurationError

    # Import other classes from their respective files
    from environment_config_validator import EnvironmentConfigValidator
    from config_drift_monitor import ConfigDriftMonitor
    from config_approval_workflow import ConfigApprovalWorkflow
    from immutable_config_manager import ImmutableConfigManager

    def validate_environment_config(*args, **kwargs):
        """Validate environment configuration"""
        validator = EnvironmentConfigValidator()
        return validator.validate(*args, **kwargs)

    def initialize_drift_monitoring(*args, **kwargs):
        """Initialize drift monitoring"""
        return ConfigDriftMonitor(*args, **kwargs)

    def create_config_version(*args, **kwargs):
        """Create config version"""
        manager = ImmutableConfigManager()
        return manager.create_version(*args, **kwargs)

except ImportError as e:
    # Fallback for missing dependencies
    from .settings import Config, get_config, load_config, ConfigurationError
    from .validator import EnvironmentConfigValidator, validate_environment_config
    from .drift_monitor import ConfigDriftMonitor, initialize_drift_monitoring
    from .approval_workflow import ConfigApprovalWorkflow
    from .immutable_manager import ImmutableConfigManager, create_config_version

__all__ = [
    # Core Configuration
    "Config",
    "get_config",
    "load_config",
    "ConfigurationError",
    
    # Validation
    "EnvironmentConfigValidator",
    "validate_environment_config",
    
    # Drift Monitoring
    "ConfigDriftMonitor",
    "initialize_drift_monitoring",
    
    # Change Management
    "ConfigApprovalWorkflow",
    
    # Immutable Management
    "ImmutableConfigManager",
    "create_config_version",
]