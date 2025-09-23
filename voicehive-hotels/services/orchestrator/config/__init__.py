"""
Configuration Management module for VoiceHive Hotels Orchestrator

This module provides secure configuration management including environment validation,
drift monitoring, change approval workflows, and immutable configuration versioning.
"""

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