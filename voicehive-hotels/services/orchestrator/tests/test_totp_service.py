"""
Unit tests for TOTP Service
Tests MFA TOTP generation, verification, and QR code functionality
"""

import pytest
import base64
import io
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

import pyotp
from PIL import Image

from services.orchestrator.auth.totp_service import TOTPService


class TestTOTPService:
    """Test suite for TOTP Service"""

    def setup_method(self):
        """Set up test fixtures"""
        self.totp_service = TOTPService(issuer_name="VoiceHive Hotels Test")

    def test_init_default_issuer(self):
        """Test TOTP service initialization with default issuer"""
        service = TOTPService()
        assert service.issuer_name == "VoiceHive Hotels"
        assert service.window == 1

    def test_init_custom_issuer(self):
        """Test TOTP service initialization with custom issuer"""
        assert self.totp_service.issuer_name == "VoiceHive Hotels Test"
        assert self.totp_service.window == 1

    def test_generate_secret(self):
        """Test secret generation"""
        secret = self.totp_service.generate_secret()

        # Should be base32 encoded
        assert isinstance(secret, str)
        assert len(secret) > 0

        # Should be valid base32
        decoded = base64.b32decode(secret)
        assert len(decoded) == 20  # 160 bits

        # Multiple calls should generate different secrets
        secret2 = self.totp_service.generate_secret()
        assert secret != secret2

    def test_create_totp(self):
        """Test TOTP object creation"""
        secret = "JBSWY3DPEHPK3PXP"  # Valid base32 secret
        totp = self.totp_service.create_totp(secret)

        assert isinstance(totp, pyotp.TOTP)
        assert totp.secret == secret
        assert totp.issuer == "VoiceHive Hotels Test"
        assert totp.digits == 6
        assert totp.interval == 30

    def test_generate_provisioning_uri(self):
        """Test provisioning URI generation"""
        secret = "JBSWY3DPEHPK3PXP"
        user_email = "test@example.com"

        uri = self.totp_service.generate_provisioning_uri(secret, user_email)

        assert uri.startswith("otpauth://totp/")
        assert user_email in uri
        assert secret in uri
        assert "VoiceHive Hotels Test" in uri
        assert "digits=6" in uri
        assert "period=30" in uri

    def test_generate_qr_code(self):
        """Test QR code generation"""
        secret = "JBSWY3DPEHPK3PXP"
        user_email = "test@example.com"

        uri = self.totp_service.generate_provisioning_uri(secret, user_email)
        qr_data = self.totp_service.generate_qr_code(uri)

        # Should return bytes
        assert isinstance(qr_data, bytes)
        assert len(qr_data) > 0

        # Should be valid PNG data
        assert qr_data.startswith(b'\x89PNG')

        # Should be readable as image
        image = Image.open(io.BytesIO(qr_data))
        assert image.format == 'PNG'
        assert image.size[0] > 0
        assert image.size[1] > 0

    def test_verify_token_valid(self):
        """Test TOTP token verification with valid token"""
        secret = "JBSWY3DPEHPK3PXP"

        # Generate current token
        totp = pyotp.TOTP(secret)
        current_token = totp.now()

        # Should verify successfully
        is_valid = self.totp_service.verify_token(secret, current_token)
        assert is_valid is True

    def test_verify_token_invalid_format(self):
        """Test TOTP token verification with invalid format"""
        secret = "JBSWY3DPEHPK3PXP"

        # Test various invalid formats
        invalid_tokens = [
            "",           # Empty
            "12345",      # Too short
            "1234567",    # Too long
            "12345a",     # Non-numeric
            "abcdef",     # All letters
            None,         # None
        ]

        for token in invalid_tokens:
            is_valid = self.totp_service.verify_token(secret, token)
            assert is_valid is False

    def test_verify_token_wrong_token(self):
        """Test TOTP token verification with wrong token"""
        secret = "JBSWY3DPEHPK3PXP"

        # Use a fixed wrong token
        wrong_token = "000000"

        is_valid = self.totp_service.verify_token(secret, wrong_token)
        assert is_valid is False

    def test_verify_token_with_user_email_logging(self):
        """Test TOTP token verification with user email for logging"""
        secret = "JBSWY3DPEHPK3PXP"
        user_email = "test@example.com"

        totp = pyotp.TOTP(secret)
        current_token = totp.now()

        with patch('services.orchestrator.auth.totp_service.logger') as mock_logger:
            is_valid = self.totp_service.verify_token(secret, current_token, user_email)
            assert is_valid is True

            # Should log success with user email
            mock_logger.info.assert_called_with(
                "totp_verification_success",
                user_email=user_email
            )

    def test_verify_token_exception_handling(self):
        """Test TOTP token verification with exception handling"""
        secret = "INVALID_SECRET"  # Invalid base32
        token = "123456"

        with patch('services.orchestrator.auth.totp_service.logger') as mock_logger:
            is_valid = self.totp_service.verify_token(secret, token)
            assert is_valid is False

            # Should log error
            mock_logger.error.assert_called_once()
            args = mock_logger.error.call_args[1]
            assert "totp_verification_error" in mock_logger.error.call_args[0]
            assert "error" in args

    def test_get_current_token(self):
        """Test getting current TOTP token"""
        secret = "JBSWY3DPEHPK3PXP"

        current_token = self.totp_service.get_current_token(secret)

        assert isinstance(current_token, str)
        assert len(current_token) == 6
        assert current_token.isdigit()

        # Should match pyotp directly
        totp = pyotp.TOTP(secret)
        expected_token = totp.now()
        assert current_token == expected_token

    def test_verify_token_with_drift(self):
        """Test TOTP token verification with time drift"""
        secret = "JBSWY3DPEHPK3PXP"

        # Generate token for current time
        totp = pyotp.TOTP(secret)
        current_token = totp.now()

        # Should verify with default drift
        is_valid, offset = self.totp_service.verify_token_with_drift(secret, current_token)
        assert is_valid is True
        assert offset == 0  # Current time

    def test_verify_token_with_drift_invalid_format(self):
        """Test drift verification with invalid token format"""
        secret = "JBSWY3DPEHPK3PXP"

        is_valid, offset = self.totp_service.verify_token_with_drift(secret, "invalid")
        assert is_valid is False
        assert offset is None

    def test_verify_token_with_drift_extended_window(self):
        """Test drift verification with extended time window"""
        secret = "JBSWY3DPEHPK3PXP"

        # This test might be flaky due to timing, so we'll mock time
        with patch('services.orchestrator.auth.totp_service.datetime') as mock_datetime:
            # Mock current time
            fixed_time = datetime.now(timezone.utc)
            mock_datetime.now.return_value = fixed_time

            totp = pyotp.TOTP(secret)

            # Generate token for different time periods
            for offset in [-2, -1, 0, 1, 2]:
                test_time = fixed_time.timestamp() + (offset * 30)
                test_token = totp.at(int(test_time // 30))

                is_valid, found_offset = self.totp_service.verify_token_with_drift(
                    secret, test_token, drift=2
                )

                # Should find valid token within drift window
                if -2 <= offset <= 2:
                    assert is_valid is True
                    assert found_offset == offset

    def test_verify_token_with_drift_exception_handling(self):
        """Test drift verification exception handling"""
        secret = "INVALID_SECRET"
        token = "123456"

        with patch('services.orchestrator.auth.totp_service.logger') as mock_logger:
            is_valid, offset = self.totp_service.verify_token_with_drift(secret, token)
            assert is_valid is False
            assert offset is None

            # Should log error
            mock_logger.error.assert_called_once()

    def test_is_secret_valid(self):
        """Test secret validation"""
        # Valid base32 secrets
        valid_secrets = [
            "JBSWY3DPEHPK3PXP",
            "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
            "MFRGG43FMZQW4ZZOMNXW2ZLUMV2GS3LB",
        ]

        for secret in valid_secrets:
            assert self.totp_service.is_secret_valid(secret) is True

        # Invalid secrets
        invalid_secrets = [
            "",                    # Empty
            "INVALID1",           # Invalid base32 chars
            "JBSWY3DPEHPK3PX1",   # Invalid base32 char '1'
            "not_base32_at_all",  # Completely invalid
        ]

        for secret in invalid_secrets:
            assert self.totp_service.is_secret_valid(secret) is False

    def test_window_tolerance(self):
        """Test time window tolerance"""
        secret = "JBSWY3DPEHPK3PXP"

        # Create TOTP with custom window
        service = TOTPService()
        service.window = 2  # 2 time steps tolerance

        totp = pyotp.TOTP(secret)
        current_token = totp.now()

        # Should verify with current window setting
        with patch.object(totp, 'verify', return_value=True) as mock_verify:
            is_valid = service.verify_token(secret, current_token)
            assert is_valid is True

            # Should call verify with correct window
            mock_verify.assert_called_once_with(current_token, valid_window=2)

    @patch('services.orchestrator.auth.totp_service.logger')
    def test_logging_integration(self, mock_logger):
        """Test that logging is properly integrated"""
        secret = self.totp_service.generate_secret()

        # Should log secret generation
        mock_logger.info.assert_called_with(
            "totp_secret_generated",
            secret_length=len(secret)
        )

        # Reset mock
        mock_logger.reset_mock()

        # Test provisioning URI generation logging
        user_email = "test@example.com"
        self.totp_service.generate_provisioning_uri(secret, user_email)

        mock_logger.info.assert_called_with(
            "provisioning_uri_generated",
            user_email=user_email
        )

        # Reset mock
        mock_logger.reset_mock()

        # Test QR code generation logging
        uri = self.totp_service.generate_provisioning_uri(secret, user_email)
        qr_data = self.totp_service.generate_qr_code(uri)

        mock_logger.info.assert_called_with(
            "qr_code_generated",
            data_size=len(qr_data)
        )