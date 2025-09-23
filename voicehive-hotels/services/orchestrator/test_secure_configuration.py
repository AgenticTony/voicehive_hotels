"""
Test suite for secure configuration management system
"""

import os
import json
import tempfile
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import (
    VoiceHiveConfig, ConfigurationManager, EnvironmentType, RegionType,
    DatabaseConfig, RedisConfig, AuthConfig, SecurityConfig, ExternalServiceConfig,
    ConfigurationError, ConfigurationValidationError
)
from config_drift_monitor import (
    ConfigurationDriftMonitor, DriftSeverity, DriftType, 
    ConfigurationBaseline, DriftDetection
)
from config_approval_workflow import (
    ConfigurationApprovalWorkflow, ApprovalStatus, ApprovalPriority,
    ApproverRole, ConfigurationChange, ApprovalRequest
)
from environment_config_validator import (
    EnvironmentConfigurationValidator, ValidationSeverity,
    ValidationRule, ValidationViolation, ValidationReport
)
from immutable_config_manager import (
    ImmutableConfigurationManager, ConfigurationVersion,
    ConfigurationVersionStatus, RollbackReason
)


class TestSecureConfiguration:
    """Test secure configuration management"""
    
    def setup_method(self):
        """Setup test environment"""
        self.test_config_data = {
            "service_name": "voicehive-orchestrator",
            "environment": "staging",
            "region": "eu-west-1",
            "log_level": "INFO",
            "database": {
                "host": "test-db.example.com",
                "port": 5432,
                "database": "voicehive_test",
                "username": "test_user",
                "password": "test_password_123456",
                "ssl_mode": "require",
                "pool_size": 10,
                "max_overflow": 20
            },
            "redis": {
                "host": "test-redis.example.com",
                "port": 6379,
                "password": "redis_password_123456",
                "db": 0,
                "ssl": True,
                "pool_size": 10
            },
            "auth": {
                "jwt_secret_key": "test_jwt_secret_key_with_sufficient_length_for_security",
                "jwt_algorithm": "RS256",
                "jwt_expiration_minutes": 15,
                "refresh_token_expiration_days": 7,
                "api_key_length": 32,
                "max_login_attempts": 5,
                "lockout_duration_minutes": 15
            },
            "security": {
                "encryption_key": "test_encryption_key_with_sufficient_length",
                "webhook_signature_secret": "test_webhook_secret_123456",
                "cors_allowed_origins": ["https://test.voicehive-hotels.eu"],
                "session_timeout_minutes": 30,
                "rate_limit_per_minute": 100
            },
            "external_services": {
                "livekit_url": "wss://test-livekit.voicehive-hotels.eu",
                "vault_url": "https://test-vault.voicehive-hotels.eu",
                "pms_timeout_seconds": 30,
                "tts_timeout_seconds": 15,
                "asr_timeout_seconds": 30
            }
        }
    
    def test_configuration_validation_success(self):
        """Test successful configuration validation"""
        config = VoiceHiveConfig(**self.test_config_data)
        
        assert config.service_name == "voicehive-orchestrator"
        assert config.environment == EnvironmentType.STAGING
        assert config.region == RegionType.EU_WEST_1
        assert config.database.host == "test-db.example.com"
        assert config.redis.ssl is True
        assert config.auth.jwt_algorithm == "RS256"
    
    def test_configuration_validation_failure(self):
        """Test configuration validation failure"""
        invalid_config_data = self.test_config_data.copy()
        invalid_config_data["region"] = "us-east-1"  # Non-EU region
        
        with pytest.raises(ValueError, match="Region must be an EU region"):
            VoiceHiveConfig(**invalid_config_data)
    
    def test_weak_password_validation(self):
        """Test weak password validation"""
        invalid_config_data = self.test_config_data.copy()
        invalid_config_data["database"]["password"] = "weak"  # Too short
        
        with pytest.raises(ValueError, match="Database password must be at least 8 characters"):
            VoiceHiveConfig(**invalid_config_data)
    
    def test_insecure_jwt_algorithm(self):
        """Test insecure JWT algorithm validation"""
        invalid_config_data = self.test_config_data.copy()
        invalid_config_data["auth"]["jwt_algorithm"] = "HS256"  # Insecure algorithm
        
        with pytest.raises(ValueError, match="JWT algorithm must be one of"):
            VoiceHiveConfig(**invalid_config_data)
    
    def test_configuration_hash_calculation(self):
        """Test configuration hash calculation"""
        config = VoiceHiveConfig(**self.test_config_data)
        
        hash1 = config.calculate_config_hash()
        hash2 = config.calculate_config_hash()
        
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hash length
    
    def test_configuration_integrity_validation(self):
        """Test configuration integrity validation"""
        config_data = self.test_config_data.copy()
        config_data["config_hash"] = "invalid_hash"
        
        config = VoiceHiveConfig(**config_data)
        
        assert not config.validate_integrity()


class TestConfigurationDriftMonitor:
    """Test configuration drift monitoring"""
    
    def setup_method(self):
        """Setup test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.drift_monitor = ConfigurationDriftMonitor(
            baseline_storage_path=self.temp_dir,
            check_interval_seconds=1
        )
    
    @pytest.mark.asyncio
    async def test_create_baseline(self):
        """Test creating configuration baseline"""
        config_data = {
            "service_name": "test-service",
            "environment": "staging",
            "region": "eu-west-1",
            "database": {
                "host": "test-db",
                "port": 5432,
                "database": "test",
                "username": "user",
                "password": "password123",
                "ssl_mode": "require"
            },
            "redis": {
                "host": "test-redis",
                "port": 6379,
                "ssl": True
            },
            "auth": {
                "jwt_secret_key": "test_secret_key_with_sufficient_length",
                "jwt_algorithm": "RS256"
            },
            "security": {
                "encryption_key": "test_encryption_key_sufficient_length",
                "webhook_signature_secret": "webhook_secret_123"
            },
            "external_services": {
                "livekit_url": "wss://test.example.com",
                "vault_url": "https://vault.example.com"
            }
        }
        
        config = VoiceHiveConfig(**config_data)
        
        baseline = await self.drift_monitor.create_baseline(
            config=config,
            approved_by="test_user",
            version="1.0"
        )
        
        assert baseline.environment == "staging"
        assert baseline.approved_by == "test_user"
        assert baseline.version == "1.0"
        assert baseline.config_hash == config.calculate_config_hash()
    
    @pytest.mark.asyncio
    async def test_drift_detection(self):
        """Test configuration drift detection"""
        # Create baseline
        config_data = {
            "service_name": "test-service",
            "environment": "staging",
            "region": "eu-west-1",
            "database": {
                "host": "test-db",
                "port": 5432,
                "database": "test",
                "username": "user",
                "password": "password123",
                "ssl_mode": "require"
            },
            "redis": {
                "host": "test-redis",
                "port": 6379,
                "ssl": True
            },
            "auth": {
                "jwt_secret_key": "test_secret_key_with_sufficient_length",
                "jwt_algorithm": "RS256"
            },
            "security": {
                "encryption_key": "test_encryption_key_sufficient_length",
                "webhook_signature_secret": "webhook_secret_123"
            },
            "external_services": {
                "livekit_url": "wss://test.example.com",
                "vault_url": "https://vault.example.com"
            }
        }
        
        config = VoiceHiveConfig(**config_data)
        await self.drift_monitor.create_baseline(config, "test_user")
        
        # Modify configuration
        modified_config_data = config_data.copy()
        modified_config_data["auth"]["jwt_expiration_minutes"] = 60  # Changed from default
        
        modified_config = VoiceHiveConfig(**modified_config_data)
        
        # Check for drift
        drift_detections = await self.drift_monitor.check_drift(modified_config)
        
        assert len(drift_detections) > 0
        assert any(d.field_path == "auth.jwt_expiration_minutes" for d in drift_detections)


class TestConfigurationApprovalWorkflow:
    """Test configuration approval workflow"""
    
    def setup_method(self):
        """Setup test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.approval_workflow = ConfigurationApprovalWorkflow(
            approval_storage_path=self.temp_dir
        )
    
    @pytest.mark.asyncio
    async def test_create_approval_request(self):
        """Test creating approval request"""
        changes = [
            ConfigurationChange(
                field_path="auth.jwt_expiration_minutes",
                old_value=15,
                new_value=30,
                change_type="modify",
                justification="Increase session duration for better UX",
                impact_assessment="Low impact, improves user experience",
                rollback_plan="Revert to 15 minutes if issues occur"
            )
        ]
        
        request = await self.approval_workflow.create_approval_request(
            environment=EnvironmentType.PRODUCTION,
            requester="test_user",
            requester_role="developer",
            changes=changes,
            justification="Improve user experience",
            impact_assessment="Low impact change",
            rollback_plan="Simple revert"
        )
        
        assert request.environment == EnvironmentType.PRODUCTION
        assert request.requester == "test_user"
        assert request.status == ApprovalStatus.PENDING
        assert len(request.changes) == 1
        assert ApproverRole.SECURITY_ADMIN in request.required_approvers
    
    @pytest.mark.asyncio
    async def test_approve_request(self):
        """Test approving configuration change request"""
        changes = [
            ConfigurationChange(
                field_path="security.rate_limit_per_minute",
                old_value=100,
                new_value=200,
                change_type="modify",
                justification="Handle increased traffic",
                impact_assessment="Medium impact",
                rollback_plan="Revert if performance issues"
            )
        ]
        
        request = await self.approval_workflow.create_approval_request(
            environment=EnvironmentType.STAGING,
            requester="test_user",
            requester_role="developer",
            changes=changes,
            justification="Handle traffic increase",
            impact_assessment="Medium impact",
            rollback_plan="Simple revert"
        )
        
        # Approve the request
        updated_request = await self.approval_workflow.approve_request(
            request_id=request.request_id,
            approver="admin_user",
            approver_role=ApproverRole.SYSTEM_ADMIN,
            approval_comments="Approved for staging"
        )
        
        assert len(updated_request.approvals) == 1
        assert updated_request.approvals[0]["approver"] == "admin_user"
        
        # Check if fully approved (depends on required approvers)
        if updated_request.is_fully_approved():
            assert updated_request.status == ApprovalStatus.APPROVED


class TestEnvironmentConfigurationValidator:
    """Test environment-specific configuration validation"""
    
    def setup_method(self):
        """Setup test environment"""
        self.validator = EnvironmentConfigurationValidator()
    
    @pytest.mark.asyncio
    async def test_production_validation_success(self):
        """Test successful production configuration validation"""
        config_data = {
            "service_name": "voicehive-orchestrator",
            "environment": "production",
            "region": "eu-west-1",
            "log_level": "INFO",
            "database": {
                "host": "prod-db.example.com",
                "port": 5432,
                "database": "voicehive_prod",
                "username": "prod_user",
                "password": "very_secure_production_password_123456",
                "ssl_mode": "require"
            },
            "redis": {
                "host": "prod-redis.example.com",
                "port": 6379,
                "password": "secure_redis_password_123456",
                "ssl": True
            },
            "auth": {
                "jwt_secret_key": "production_jwt_secret_key_with_very_long_secure_length",
                "jwt_algorithm": "RS256",
                "jwt_expiration_minutes": 15
            },
            "security": {
                "encryption_key": "production_encryption_key_with_sufficient_length",
                "webhook_signature_secret": "production_webhook_secret_123456",
                "cors_allowed_origins": ["https://app.voicehive-hotels.eu"],
                "rate_limit_per_minute": 1000
            },
            "external_services": {
                "livekit_url": "wss://livekit.voicehive-hotels.eu",
                "vault_url": "https://vault.voicehive-hotels.eu"
            }
        }
        
        config = VoiceHiveConfig(**config_data)
        report = await self.validator.validate_configuration(config)
        
        # Should have minimal violations for a well-configured production setup
        critical_violations = [v for v in report.violations if v.severity == ValidationSeverity.CRITICAL]
        assert len(critical_violations) == 0
        
        assert report.compliance_score > 80  # Should have high compliance score
    
    @pytest.mark.asyncio
    async def test_production_validation_failures(self):
        """Test production configuration validation failures"""
        config_data = {
            "service_name": "voicehive-orchestrator",
            "environment": "production",
            "region": "eu-west-1",
            "log_level": "DEBUG",  # Should not be DEBUG in production
            "database": {
                "host": "prod-db.example.com",
                "port": 5432,
                "database": "voicehive_prod",
                "username": "prod_user",
                "password": "weak",  # Too weak for production
                "ssl_mode": "disable"  # Should require SSL
            },
            "redis": {
                "host": "prod-redis.example.com",
                "port": 6379,
                "ssl": False  # Should require SSL in production
            },
            "auth": {
                "jwt_secret_key": "short",  # Too short
                "jwt_algorithm": "HS256",  # Insecure algorithm
                "jwt_expiration_minutes": 120  # Too long for production
            },
            "security": {
                "encryption_key": "short",  # Too short
                "webhook_signature_secret": "short",  # Too short
                "cors_allowed_origins": ["*"],  # Wildcard not allowed
                "rate_limit_per_minute": 5  # Too restrictive
            },
            "external_services": {
                "livekit_url": "http://insecure.example.com",  # Should use HTTPS/WSS
                "vault_url": "http://insecure-vault.example.com"  # Should use HTTPS
            }
        }
        
        # This should fail validation due to insecure configuration
        with pytest.raises(ValueError):
            VoiceHiveConfig(**config_data)


class TestImmutableConfigurationManager:
    """Test immutable configuration management"""
    
    def setup_method(self):
        """Setup test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.immutable_manager = ImmutableConfigurationManager(
            storage_path=self.temp_dir
        )
    
    @pytest.mark.asyncio
    async def test_create_version(self):
        """Test creating immutable configuration version"""
        config_data = {
            "service_name": "test-service",
            "environment": "staging",
            "region": "eu-west-1",
            "database": {
                "host": "test-db",
                "port": 5432,
                "database": "test",
                "username": "user",
                "password": "password123",
                "ssl_mode": "require"
            },
            "redis": {
                "host": "test-redis",
                "port": 6379,
                "ssl": True
            },
            "auth": {
                "jwt_secret_key": "test_secret_key_with_sufficient_length",
                "jwt_algorithm": "RS256"
            },
            "security": {
                "encryption_key": "test_encryption_key_sufficient_length",
                "webhook_signature_secret": "webhook_secret_123"
            },
            "external_services": {
                "livekit_url": "wss://test.example.com",
                "vault_url": "https://vault.example.com"
            }
        }
        
        config = VoiceHiveConfig(**config_data)
        
        version = await self.immutable_manager.create_version(
            config=config,
            created_by="test_user",
            change_description="Initial version",
            tags=["initial", "test"]
        )
        
        assert version.environment == EnvironmentType.STAGING
        assert version.created_by == "test_user"
        assert version.status == ConfigurationVersionStatus.ACTIVE
        assert version.verify_integrity()
        assert "initial" in version.tags
    
    @pytest.mark.asyncio
    async def test_rollback_configuration(self):
        """Test configuration rollback"""
        # Create initial version
        config_data = {
            "service_name": "test-service",
            "environment": "staging",
            "region": "eu-west-1",
            "database": {
                "host": "test-db",
                "port": 5432,
                "database": "test",
                "username": "user",
                "password": "password123",
                "ssl_mode": "require"
            },
            "redis": {
                "host": "test-redis",
                "port": 6379,
                "ssl": True
            },
            "auth": {
                "jwt_secret_key": "test_secret_key_with_sufficient_length",
                "jwt_algorithm": "RS256"
            },
            "security": {
                "encryption_key": "test_encryption_key_sufficient_length",
                "webhook_signature_secret": "webhook_secret_123"
            },
            "external_services": {
                "livekit_url": "wss://test.example.com",
                "vault_url": "https://vault.example.com"
            }
        }
        
        config1 = VoiceHiveConfig(**config_data)
        version1 = await self.immutable_manager.create_version(
            config=config1,
            created_by="test_user",
            change_description="Version 1"
        )
        
        # Create second version
        config_data["auth"]["jwt_expiration_minutes"] = 30
        config2 = VoiceHiveConfig(**config_data)
        version2 = await self.immutable_manager.create_version(
            config=config2,
            created_by="test_user",
            change_description="Version 2"
        )
        
        # Rollback to version 1
        rollback = await self.immutable_manager.rollback_to_version(
            environment=EnvironmentType.STAGING,
            target_version_id=version1.version_id,
            initiated_by="admin_user",
            reason=RollbackReason.CONFIGURATION_ERROR,
            rollback_description="Rolling back due to issues"
        )
        
        assert rollback.from_version_id == version2.version_id
        assert rollback.to_version_id == version1.version_id
        assert rollback.reason == RollbackReason.CONFIGURATION_ERROR
        assert rollback.completed_at is not None
        
        # Verify active version is now version 1
        active_version = await self.immutable_manager.get_active_version(EnvironmentType.STAGING)
        assert active_version.version_id == version1.version_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])