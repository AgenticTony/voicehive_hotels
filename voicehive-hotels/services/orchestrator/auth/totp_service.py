"""
TOTP (Time-based One-Time Password) Service
Handles TOTP generation, verification, and QR code creation for MFA
"""

import base64
import io
from datetime import datetime, timezone
from typing import Optional, Tuple
import secrets
import pyotp
import qrcode
from qrcode.image.pil import PilImage

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.totp_service")


class TOTPService:
    """Service for handling TOTP operations in MFA"""

    def __init__(self, issuer_name: str = "VoiceHive Hotels"):
        """
        Initialize TOTP service

        Args:
            issuer_name: Name of the service issuing the TOTP tokens
        """
        self.issuer_name = issuer_name
        self.window = 1  # Accept tokens from ±1 time window (30 second tolerance)

    def generate_secret(self) -> str:
        """
        Generate a cryptographically secure random base32 secret

        Returns:
            Base32 encoded secret string
        """
        # Generate 32 bytes of random data for a 160-bit secret
        random_bytes = secrets.token_bytes(20)
        secret = base64.b32encode(random_bytes).decode('utf-8')

        logger.info("totp_secret_generated", secret_length=len(secret))
        return secret

    def create_totp(self, secret: str) -> pyotp.TOTP:
        """
        Create a TOTP object with the given secret

        Args:
            secret: Base32 encoded secret

        Returns:
            TOTP object configured for this service
        """
        return pyotp.TOTP(
            secret,
            issuer=self.issuer_name,
            digits=6,           # 6-digit codes (standard)
            interval=30         # 30-second intervals (standard)
        )

    def generate_provisioning_uri(self, secret: str, user_email: str) -> str:
        """
        Generate a provisioning URI for authenticator apps

        Args:
            secret: Base32 encoded secret
            user_email: User's email address for identification

        Returns:
            Provisioning URI that can be used to generate QR codes
        """
        totp = self.create_totp(secret)
        uri = totp.provisioning_uri(
            name=user_email,
            issuer_name=self.issuer_name
        )

        logger.info("provisioning_uri_generated", user_email=user_email)
        return uri

    def generate_qr_code(self, provisioning_uri: str) -> bytes:
        """
        Generate QR code image data from provisioning URI

        Args:
            provisioning_uri: URI from generate_provisioning_uri()

        Returns:
            PNG image data as bytes
        """
        # Create QR code with optimal settings for authenticator apps
        qr = qrcode.QRCode(
            version=1,          # Automatic sizing
            error_correction=qrcode.constants.ERROR_CORRECT_L,  # Low error correction for smaller size
            box_size=10,        # Size of each box in pixels
            border=4,           # Minimum border size
        )

        qr.add_data(provisioning_uri)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white", image_factory=PilImage)

        # Convert to bytes
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_data = img_buffer.getvalue()

        logger.info("qr_code_generated", data_size=len(img_data))
        return img_data

    def verify_token(self, secret: str, token: str, user_email: str = None) -> bool:
        """
        Verify a TOTP token

        Args:
            secret: Base32 encoded secret
            token: 6-digit TOTP token to verify
            user_email: Optional user email for logging

        Returns:
            True if token is valid, False otherwise
        """
        try:
            # Validate token format
            if not token or not token.isdigit() or len(token) != 6:
                logger.warning(
                    "invalid_totp_format",
                    user_email=user_email,
                    token_length=len(token) if token else 0
                )
                return False

            totp = self.create_totp(secret)

            # Verify with time window tolerance
            is_valid = totp.verify(token, valid_window=self.window)

            if is_valid:
                logger.info("totp_verification_success", user_email=user_email)
            else:
                logger.warning("totp_verification_failed", user_email=user_email)

            return is_valid

        except Exception as e:
            logger.error(
                "totp_verification_error",
                user_email=user_email,
                error=str(e)
            )
            return False

    def get_current_token(self, secret: str) -> str:
        """
        Get the current TOTP token for testing/debugging purposes

        Args:
            secret: Base32 encoded secret

        Returns:
            Current 6-digit TOTP token
        """
        totp = self.create_totp(secret)
        current_token = totp.now()

        logger.debug("current_totp_generated")
        return current_token

    def verify_token_with_drift(self, secret: str, token: str, drift: int = 1) -> Tuple[bool, Optional[int]]:
        """
        Verify a TOTP token with extended drift tolerance
        Useful for handling clock skew between client and server

        Args:
            secret: Base32 encoded secret
            token: 6-digit TOTP token to verify
            drift: Number of time windows to check (±drift)

        Returns:
            Tuple of (is_valid, time_offset_used)
        """
        try:
            if not token or not token.isdigit() or len(token) != 6:
                return False, None

            totp = self.create_totp(secret)
            current_time = datetime.now(timezone.utc).timestamp()

            # Check current time and ±drift windows
            for offset in range(-drift, drift + 1):
                check_time = current_time + (offset * 30)  # 30-second intervals
                expected_token = totp.at(int(check_time // 30))

                if expected_token == token:
                    logger.info("totp_verified_with_drift", offset=offset)
                    return True, offset

            logger.warning("totp_verification_failed_with_drift", drift=drift)
            return False, None

        except Exception as e:
            logger.error("totp_drift_verification_error", error=str(e))
            return False, None

    def is_secret_valid(self, secret: str) -> bool:
        """
        Validate that a secret is properly formatted

        Args:
            secret: Base32 encoded secret to validate

        Returns:
            True if secret is valid base32 format
        """
        try:
            # Try to decode the secret
            base64.b32decode(secret)
            return True
        except Exception:
            return False