"""
Basic test for secure configuration system
"""

import os
import tempfile
import pytest
from unittest.mock import patch

# Set required environment variables for testing
os.environ.update({
    "VOICEHIVE_SERVICE_NAME": "voicehive-orchestrator",
    "VOICEHIVE_ENVIRONMENT": "staging",
    "VOICEHIVE_REGION": "eu-west-1",
    "VOICEHIVE_LOG_LEVEL": "INFO",
    "VOICEHIVE_DATABASE__HOST": "test-db.example.com",
    "VOICEHIVE_DATABASE__PORT": "5432",
    "VOICEHIVE_DATABASE__DATABASE": "voicehive_test",
    "VOICEHIVE_DATABASE__USERNAME": "test_user",
    "VOICEHIVE_DATABASE__PASSWORD": "test_password_123456",
    "VOICEHIVE_DATABASE__SSL_MODE": "require",
    "VOICEHIVE_REDIS__HOST": "test-redis.example.com",
    "VOICEHIVE_REDIS__PORT": "6379",
    "VOICEHIVE_REDIS__PASSWORD": "redis_password_123456",
    "VOICEHIVE_REDIS__SSL": "true",
    "VOICEHIVE_AUTH__JWT_SECRET_KEY": "test_jwt_secret_key_with_sufficient_length_for_security",
    "VOICEHIVE_AUTH__JWT_ALGORITHM": "RS256",
    "VOICEHIVE_SECURITY__ENCRYPTION_KEY": "test_encryption_key_with_sufficient_length",
    "VOICEHIVE_SECURITY__WEBHOOK_SIGNATURE_SECRET": "test_webhook_secret_123456",
    "VOICEHIVE_EXTERNAL_SERVICES__LIVEKIT_URL": "wss://test-livekit.voicehive-hotels.eu",
    "VOICEHIVE_EXTERNAL_SERVICES__VAULT_URL": "https://test-vault.voicehive-hotels.eu"
})

from config import VoiceHiveConfig, EnvironmentType, RegionType


def test_basic_configuration_creation():
    """Test basic configuration creation with environment variables"""
    
    config = VoiceHiveConfig()
    
    assert config.service_name == "voicehive-orchestrator"
    assert config.environment == EnvironmentType.STAGING
    assert config.region == RegionType.EU_WEST_1
    assert config.database.host == "test-db.example.com"
    assert config.redis.ssl is True
    assert config.auth.jwt_algorithm == "RS256"


def test_configuration_hash():
    """Test configuration hash calculation"""
    
    config = VoiceHiveConfig()
    
    hash1 = config.calculate_config_hash()
    hash2 = config.calculate_config_hash()
    
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hash length


def test_configuration_validation():
    """Test configuration validation"""
    
    config = VoiceHiveConfig()
    
    # Should not raise any validation errors
    assert config.service_name is not None
    assert config.environment in [e for e in EnvironmentType]
    assert config.region in [r for r in RegionType]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])