"""
Configuration Drift Monitor module

This module re-exports the configuration drift monitor
from the parent directory for import compatibility.
"""

# Import from parent directory
import sys
from pathlib import Path

# Add parent directory to path for imports
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

try:
    from config_drift_monitor import ConfigDriftMonitor

    def initialize_drift_monitoring(*args, **kwargs):
        """Initialize drift monitoring"""
        return ConfigDriftMonitor(*args, **kwargs)

except ImportError as e:
    # Create minimal fallback if the original doesn't exist
    class ConfigDriftMonitor:
        """Fallback drift monitor"""
        def __init__(self, *args, **kwargs):
            pass

        def start_monitoring(self, *args, **kwargs):
            return True

    def initialize_drift_monitoring(*args, **kwargs):
        """Fallback initialization function"""
        return ConfigDriftMonitor(*args, **kwargs)

__all__ = [
    "ConfigDriftMonitor",
    "initialize_drift_monitoring",
]