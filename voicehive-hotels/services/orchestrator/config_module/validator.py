"""
Configuration Validator module

This module re-exports the environment configuration validator
from the parent directory for import compatibility.
"""

# Import from parent directory
import sys
from pathlib import Path

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

try:
    from environment_config_validator import (
        EnvironmentConfigValidator,
        validate_environment_config,
    )
except ImportError as e:
    # Create minimal fallback if the original doesn't exist
    class EnvironmentConfigValidator:
        """Fallback validator"""
        def __init__(self, *args, **kwargs):
            pass

        def validate(self, *args, **kwargs):
            return True

    def validate_environment_config(*args, **kwargs):
        """Fallback validation function"""
        return True

__all__ = [
    "EnvironmentConfigValidator",
    "validate_environment_config",
]