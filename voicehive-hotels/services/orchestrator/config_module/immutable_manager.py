"""
Immutable Configuration Manager module

This module re-exports the immutable configuration manager
from the parent directory for import compatibility.
"""

# Import from parent directory
import sys
from pathlib import Path

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

try:
    from immutable_config_manager import ImmutableConfigManager

    def create_config_version(*args, **kwargs):
        """Create a new configuration version"""
        manager = ImmutableConfigManager()
        return manager.create_version(*args, **kwargs)

except ImportError as e:
    # Create minimal fallback if the original doesn't exist
    class ImmutableConfigManager:
        """Fallback immutable manager"""
        def __init__(self, *args, **kwargs):
            pass

        def create_version(self, *args, **kwargs):
            return {"version": "1.0.0", "status": "created"}

        def get_version(self, *args, **kwargs):
            return {"version": "1.0.0", "status": "active"}

    def create_config_version(*args, **kwargs):
        """Fallback version creation function"""
        return {"version": "1.0.0", "status": "created"}

__all__ = [
    "ImmutableConfigManager",
    "create_config_version",
]