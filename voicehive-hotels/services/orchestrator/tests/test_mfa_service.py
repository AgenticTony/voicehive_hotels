"""
Unit tests for MFA Service
Tests MFA enrollment, verification, recovery codes, and audit logging
"""

import pytest
import json
import base64
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from uuid import uuid4

import bcrypt
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from services.orchestrator.auth.mfa_service import (
    MFAService, MFAError, MFAEnrollmentError, MFAVerificationError
)
from services.orchestrator.database.models import User, UserMFA, MFAAuditLog, MFARecoveryCode


class TestMFAService:
    """Test suite for MFA Service"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mock_db_session = Mock(spec=AsyncSession)
        self.encryption_key = Fernet.generate_key().decode('utf-8')
        self.mfa_service = MFAService(self.mock_db_session, self.encryption_key)

        # Test data
        self.user_id = str(uuid4())
        self.enrolled_by = str(uuid4())
        self.test_email = "test@example.com"

    def test_init_success(self):
        """Test successful MFA service initialization"""
        assert self.mfa_service.db_session == self.mock_db_session
        assert self.mfa_service.cipher is not None
        assert self.mfa_service.totp_service is not None

    def test_init_invalid_encryption_key(self):
        """Test MFA service initialization with invalid encryption key"""
        with pytest.raises(MFAError, match="Failed to initialize MFA encryption"):
            MFAService(self.mock_db_session, "invalid_key")

    def test_generate_encryption_key(self):
        """Test encryption key generation"""
        key = MFAService.generate_encryption_key()

        assert isinstance(key, str)
        assert len(key) > 0

        # Should be valid Fernet key
        fernet = Fernet(key.encode())
        assert fernet is not None

        # Multiple calls should generate different keys
        key2 = MFAService.generate_encryption_key()
        assert key != key2

    def test_encrypt_decrypt_secret(self):
        """Test secret encryption and decryption"""
        secret = "JBSWY3DPEHPK3PXP"

        # Encrypt secret
        encrypted = self.mfa_service._encrypt_secret(secret)
        assert isinstance(encrypted, str)
        assert encrypted != secret

        # Decrypt secret
        decrypted = self.mfa_service._decrypt_secret(encrypted)
        assert decrypted == secret

    def test_encrypt_secret_error(self):
        """Test secret encryption error handling"""
        # Break the cipher to cause an error
        self.mfa_service.cipher = None

        with pytest.raises(MFAError, match="Failed to encrypt TOTP secret"):
            self.mfa_service._encrypt_secret("test_secret")

    def test_decrypt_secret_error(self):
        """Test secret decryption error handling"""
        with pytest.raises(MFAError, match="Failed to decrypt TOTP secret"):
            self.mfa_service._decrypt_secret("invalid_encrypted_data")

    @pytest.mark.asyncio
    async def test_log_mfa_event_success(self):
        """Test successful MFA event logging"""
        event_data = {
            "user_id": self.user_id,
            "event_type": "enrollment",
            "event_result": "success",
            "verification_method": "totp",
            "ip_address": "192.168.1.1",
            "user_agent": "test-agent",
            "session_id": "test-session",
            "metadata": {"test": "data"}
        }

        await self.mfa_service._log_mfa_event(**event_data)

        # Should add audit log to session
        self.mock_db_session.add.assert_called_once()
        added_log = self.mock_db_session.add.call_args[0][0]

        assert isinstance(added_log, MFAAuditLog)
        assert added_log.user_id == self.user_id
        assert added_log.event_type == "enrollment"
        assert added_log.event_result == "success"
        assert added_log.verification_method == "totp"
        assert added_log.ip_address == "192.168.1.1"
        assert added_log.user_agent == "test-agent"
        assert added_log.session_id == "test-session"
        assert added_log.metadata == {"test": "data"}

        # Should commit transaction
        self.mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_mfa_event_error_handling(self):
        """Test MFA event logging error handling"""
        # Make commit raise an exception
        self.mock_db_session.commit.side_effect = Exception("Database error")

        # Should not raise exception (logging is non-critical)
        await self.mfa_service._log_mfa_event(
            user_id=self.user_id,
            event_type="test",
            event_result="error"
        )

    @pytest.mark.asyncio
    async def test_get_user_mfa_success(self):
        """Test getting user MFA settings successfully"""
        mock_result = Mock()
        mock_user_mfa = Mock(spec=UserMFA)
        mock_result.scalar_one_or_none.return_value = mock_user_mfa

        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await self.mfa_service.get_user_mfa(self.user_id)

        assert result == mock_user_mfa
        self.mock_db_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_mfa_not_found(self):
        """Test getting user MFA settings when not found"""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None

        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await self.mfa_service.get_user_mfa(self.user_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_mfa_error(self):
        """Test getting user MFA settings with database error"""
        self.mock_db_session.execute.side_effect = Exception("Database error")

        with pytest.raises(MFAError, match="Failed to retrieve MFA settings"):
            await self.mfa_service.get_user_mfa(self.user_id)

    @pytest.mark.asyncio
    async def test_is_mfa_enabled_true(self):
        """Test checking if MFA is enabled when it is"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.is_enrolled.return_value = True

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            result = await self.mfa_service.is_mfa_enabled(self.user_id)
            assert result is True

    @pytest.mark.asyncio
    async def test_is_mfa_enabled_false(self):
        """Test checking if MFA is enabled when it's not"""
        # Test with no MFA record
        with patch.object(self.mfa_service, 'get_user_mfa', return_value=None):
            result = await self.mfa_service.is_mfa_enabled(self.user_id)
            assert result is False

        # Test with MFA record but not enrolled
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.is_enrolled.return_value = False

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            result = await self.mfa_service.is_mfa_enabled(self.user_id)
            assert result is False

    @pytest.mark.asyncio
    async def test_start_enrollment_success(self):
        """Test successful MFA enrollment start"""
        # Mock no existing MFA
        with patch.object(self.mfa_service, 'get_user_mfa', return_value=None):
            # Mock user lookup
            mock_user = Mock(spec=User)
            mock_user.email = self.test_email
            mock_result = Mock()
            mock_result.scalar_one_or_none.return_value = mock_user
            self.mock_db_session.execute = AsyncMock(return_value=mock_result)

            # Mock TOTP service calls
            with patch.object(self.mfa_service.totp_service, 'generate_secret', return_value="TEST_SECRET"):
                with patch.object(self.mfa_service.totp_service, 'generate_provisioning_uri', return_value="test_uri"):
                    with patch.object(self.mfa_service.totp_service, 'generate_qr_code', return_value=b"qr_data"):
                        result = await self.mfa_service.start_enrollment(self.user_id, self.enrolled_by)

                        assert "provisioning_uri" in result
                        assert "qr_code" in result
                        assert "secret" in result
                        assert result["provisioning_uri"] == "test_uri"
                        assert result["qr_code"] == base64.b64encode(b"qr_data").decode('utf-8')
                        assert result["secret"] == "TEST_SECRET"

                        # Should add UserMFA to session
                        self.mock_db_session.add.assert_called_once()
                        self.mock_db_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_start_enrollment_already_enabled(self):
        """Test MFA enrollment start when already enabled"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.is_enrolled.return_value = True

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with pytest.raises(MFAEnrollmentError, match="MFA is already enabled"):
                await self.mfa_service.start_enrollment(self.user_id, self.enrolled_by)

    @pytest.mark.asyncio
    async def test_start_enrollment_user_not_found(self):
        """Test MFA enrollment start when user not found"""
        with patch.object(self.mfa_service, 'get_user_mfa', return_value=None):
            # Mock user lookup returning None
            mock_result = Mock()
            mock_result.scalar_one_or_none.return_value = None
            self.mock_db_session.execute = AsyncMock(return_value=mock_result)

            with pytest.raises(MFAEnrollmentError, match="User not found"):
                await self.mfa_service.start_enrollment(self.user_id, self.enrolled_by)

    @pytest.mark.asyncio
    async def test_complete_enrollment_success(self):
        """Test successful MFA enrollment completion"""
        # Mock existing MFA record (not enabled yet)
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.totp_secret = "encrypted_secret"
        mock_user_mfa.enabled = False

        # Mock user lookup
        mock_user = Mock(spec=User)
        mock_user.email = self.test_email
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with patch.object(self.mfa_service, '_decrypt_secret', return_value="TEST_SECRET"):
                with patch.object(self.mfa_service.totp_service, 'verify_token', return_value=True):
                    with patch.object(self.mfa_service, '_generate_recovery_codes', return_value=["CODE1", "CODE2"]):
                        result = await self.mfa_service.complete_enrollment(
                            self.user_id, "123456", "192.168.1.1", "test-agent"
                        )

                        assert "recovery_codes" in result
                        assert result["recovery_codes"] == ["CODE1", "CODE2"]

                        # Should enable MFA
                        assert mock_user_mfa.enabled is True
                        assert mock_user_mfa.enrolled_at is not None
                        assert mock_user_mfa.last_verified_at is not None

                        self.mock_db_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_complete_enrollment_not_started(self):
        """Test MFA enrollment completion when not started"""
        with patch.object(self.mfa_service, 'get_user_mfa', return_value=None):
            with pytest.raises(MFAEnrollmentError, match="MFA enrollment not started"):
                await self.mfa_service.complete_enrollment(self.user_id, "123456")

    @pytest.mark.asyncio
    async def test_complete_enrollment_already_enabled(self):
        """Test MFA enrollment completion when already enabled"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.totp_secret = "encrypted_secret"
        mock_user_mfa.enabled = True

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with pytest.raises(MFAEnrollmentError, match="MFA is already enabled"):
                await self.mfa_service.complete_enrollment(self.user_id, "123456")

    @pytest.mark.asyncio
    async def test_complete_enrollment_invalid_code(self):
        """Test MFA enrollment completion with invalid verification code"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.totp_secret = "encrypted_secret"
        mock_user_mfa.enabled = False

        # Mock user lookup
        mock_user = Mock(spec=User)
        mock_user.email = self.test_email
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with patch.object(self.mfa_service, '_decrypt_secret', return_value="TEST_SECRET"):
                with patch.object(self.mfa_service.totp_service, 'verify_token', return_value=False):
                    with pytest.raises(MFAVerificationError, match="Invalid verification code"):
                        await self.mfa_service.complete_enrollment(self.user_id, "123456")

    @pytest.mark.asyncio
    async def test_verify_code_totp_success(self):
        """Test successful TOTP code verification"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.is_enrolled.return_value = True
        mock_user_mfa.totp_secret = "encrypted_secret"

        # Mock user lookup
        mock_user = Mock(spec=User)
        mock_user.email = self.test_email
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with patch.object(self.mfa_service, '_decrypt_secret', return_value="TEST_SECRET"):
                with patch.object(self.mfa_service.totp_service, 'verify_token', return_value=True):
                    result = await self.mfa_service.verify_code(self.user_id, "123456")

                    assert result is True
                    assert mock_user_mfa.last_verified_at is not None
                    self.mock_db_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_verify_code_recovery_code_success(self):
        """Test successful recovery code verification"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.is_enrolled.return_value = True
        mock_user_mfa.totp_secret = "encrypted_secret"

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with patch.object(self.mfa_service, '_decrypt_secret', return_value="TEST_SECRET"):
                with patch.object(self.mfa_service.totp_service, 'verify_token', return_value=False):
                    with patch.object(self.mfa_service, '_verify_recovery_code', return_value=True):
                        result = await self.mfa_service.verify_code(self.user_id, "ABCD1234")

                        assert result is True
                        self.mock_db_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_verify_code_not_enrolled(self):
        """Test code verification when MFA not enrolled"""
        with patch.object(self.mfa_service, 'get_user_mfa', return_value=None):
            with pytest.raises(MFAVerificationError, match="MFA is not enabled"):
                await self.mfa_service.verify_code(self.user_id, "123456")

    @pytest.mark.asyncio
    async def test_verify_code_both_fail(self):
        """Test code verification when both TOTP and recovery fail"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.is_enrolled.return_value = True
        mock_user_mfa.totp_secret = "encrypted_secret"

        # Mock user lookup
        mock_user = Mock(spec=User)
        mock_user.email = self.test_email
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_user
        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with patch.object(self.mfa_service, '_decrypt_secret', return_value="TEST_SECRET"):
                with patch.object(self.mfa_service.totp_service, 'verify_token', return_value=False):
                    with patch.object(self.mfa_service, '_verify_recovery_code', return_value=False):
                        result = await self.mfa_service.verify_code(self.user_id, "123456")

                        assert result is False

    @pytest.mark.asyncio
    async def test_generate_recovery_codes(self):
        """Test recovery codes generation"""
        mock_user_mfa = Mock(spec=UserMFA)

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            recovery_codes = await self.mfa_service._generate_recovery_codes(self.user_id, count=5)

            assert len(recovery_codes) == 5
            for code in recovery_codes:
                assert isinstance(code, str)
                assert len(code) == 8
                assert code.isalnum()

            # Should delete existing codes and add new ones
            self.mock_db_session.execute.assert_called()
            assert self.mock_db_session.add.call_count == 5  # 5 recovery codes added
            self.mock_db_session.commit.assert_called()

            # Should update user MFA record
            assert mock_user_mfa.recovery_codes_generated_at is not None
            assert mock_user_mfa.recovery_codes_used_count == 0

    @pytest.mark.asyncio
    async def test_verify_recovery_code_success(self):
        """Test successful recovery code verification"""
        # Create mock recovery code
        test_code = "ABCD1234"
        hashed_code = bcrypt.hashpw(test_code.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        mock_recovery_code = Mock(spec=MFARecoveryCode)
        mock_recovery_code.code_hash = hashed_code
        mock_recovery_code.mark_used = Mock()

        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [mock_recovery_code]
        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.recovery_codes_used_count = 0

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            result = await self.mfa_service._verify_recovery_code(self.user_id, test_code, "192.168.1.1")

            assert result is True
            mock_recovery_code.mark_used.assert_called_once_with("192.168.1.1")
            assert mock_user_mfa.recovery_codes_used_count == 1
            self.mock_db_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_verify_recovery_code_not_found(self):
        """Test recovery code verification when code not found"""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await self.mfa_service._verify_recovery_code(self.user_id, "INVALID123")
        assert result is False

    @pytest.mark.asyncio
    async def test_disable_mfa(self):
        """Test MFA disabling"""
        mock_user_mfa = Mock(spec=UserMFA)

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            await self.mfa_service.disable_mfa(self.user_id, self.enrolled_by)

            # Should disable MFA and clear secret
            assert mock_user_mfa.enabled is False
            assert mock_user_mfa.totp_secret is None
            assert mock_user_mfa.updated_at is not None

            # Should delete recovery codes
            self.mock_db_session.execute.assert_called()
            self.mock_db_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_disable_mfa_not_configured(self):
        """Test MFA disabling when not configured"""
        with patch.object(self.mfa_service, 'get_user_mfa', return_value=None):
            with pytest.raises(MFAError, match="MFA is not configured"):
                await self.mfa_service.disable_mfa(self.user_id, self.enrolled_by)

    @pytest.mark.asyncio
    async def test_regenerate_recovery_codes(self):
        """Test recovery codes regeneration"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.is_enrolled.return_value = True

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with patch.object(self.mfa_service, '_generate_recovery_codes', return_value=["NEW1", "NEW2"]):
                recovery_codes = await self.mfa_service.regenerate_recovery_codes(self.user_id)

                assert recovery_codes == ["NEW1", "NEW2"]

    @pytest.mark.asyncio
    async def test_regenerate_recovery_codes_not_enrolled(self):
        """Test recovery codes regeneration when not enrolled"""
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.is_enrolled.return_value = False

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            with pytest.raises(MFAError, match="MFA is not enabled"):
                await self.mfa_service.regenerate_recovery_codes(self.user_id)

    @pytest.mark.asyncio
    async def test_get_mfa_status(self):
        """Test getting MFA status"""
        # Test with no MFA configured
        with patch.object(self.mfa_service, 'get_user_mfa', return_value=None):
            # Mock empty recovery codes result
            mock_result = Mock()
            mock_result.scalars.return_value.all.return_value = []
            self.mock_db_session.execute = AsyncMock(return_value=mock_result)

            status = await self.mfa_service.get_mfa_status(self.user_id)

            assert status["enabled"] is False
            assert status["enrolled"] is False
            assert status["recovery_codes_available"] == 0

        # Test with MFA configured
        mock_user_mfa = Mock(spec=UserMFA)
        mock_user_mfa.enabled = True
        mock_user_mfa.is_enrolled.return_value = True
        mock_user_mfa.enrolled_at = datetime.now(timezone.utc)
        mock_user_mfa.last_verified_at = datetime.now(timezone.utc)
        mock_user_mfa.recovery_codes_used_count = 2

        # Mock 3 unused recovery codes
        mock_codes = [Mock(), Mock(), Mock()]
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_codes
        self.mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(self.mfa_service, 'get_user_mfa', return_value=mock_user_mfa):
            status = await self.mfa_service.get_mfa_status(self.user_id)

            assert status["enabled"] is True
            assert status["enrolled"] is True
            assert status["recovery_codes_available"] == 3
            assert status["recovery_codes_used"] == 2
            assert status["enrolled_at"] is not None
            assert status["last_verified_at"] is not None