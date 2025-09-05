"""
Configuration module for VoiceHive Hotels Orchestrator
"""

import os
import yaml
from prometheus_client import Counter

from logging_adapter import get_safe_logger

# Use safe logger
logger = get_safe_logger("orchestrator.config")

# Configuration
CONFIG_PATH = os.getenv("CONFIG_PATH", "/config/security/gdpr-config.yaml")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://localhost:8200")
REGION = os.getenv("AWS_REGION", "eu-west-1")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "wss://livekit-eu.voicehive-hotels.eu")

# Load GDPR configuration with safe fallback for test environments
GDPR_FALLBACK_USED = False
try:
    with open(CONFIG_PATH, "r") as f:
        GDPR_CONFIG = yaml.safe_load(f)
except Exception:
    GDPR_FALLBACK_USED = True
    GDPR_CONFIG = {
        "regions": {
            "allowed": ["eu-west-1", "eu-central-1", "westeurope", "northeurope"],
            "services": {}
        },
        "retention": {"defaults": {"metadata": {"days": 1}}}
    }
    
if GDPR_FALLBACK_USED:
    logger.warning("gdpr_config_fallback_used", path=CONFIG_PATH)


# Metrics
region_violations = Counter('voicehive_region_violations', 'Non-EU region access attempts', ['service', 'region'])


# Region validation
class RegionValidator:
    @staticmethod
    def validate_service_region(service: str, region: str) -> bool:
        """Validate that a service is running in an allowed EU region"""
        allowed_regions = GDPR_CONFIG['regions']['allowed']
        if region not in allowed_regions:
            region_violations.labels(service=service, region=region).inc()
            logger.warning("region_violation", service=service, region=region, allowed=allowed_regions)
            return False
        return True
    
    @staticmethod
    def get_service_region(service: str) -> str:
        """Get the configured region for a service"""
        service_config = GDPR_CONFIG['regions']['services'].get(service, {})
        return service_config.get('region', 'unknown')
