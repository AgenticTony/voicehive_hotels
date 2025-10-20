"""
Configuration Settings module

This module re-exports the main configuration classes and functions
from the parent directory's config.py for import compatibility.
"""

# Import from parent directory's config.py
import sys
from pathlib import Path

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

try:
    from config import (
        VoiceHiveConfig as Config,
        get_config,
        load_config,
        ConfigurationError,
        ConfigurationValidationError,
        ConfigurationDriftError,
    )
except ImportError as e:
    # Fallback imports if the parent structure is different
    try:
        import config as parent_config
        Config = parent_config.VoiceHiveConfig
        get_config = parent_config.get_config
        load_config = parent_config.load_config
        ConfigurationError = parent_config.ConfigurationError
        ConfigurationValidationError = parent_config.ConfigurationValidationError
        ConfigurationDriftError = parent_config.ConfigurationDriftError
    except ImportError:
        raise ImportError(f"Could not import configuration from parent directory: {e}")

__all__ = [
    "Config",
    "get_config",
    "load_config",
    "ConfigurationError",
    "ConfigurationValidationError",
    "ConfigurationDriftError",
]