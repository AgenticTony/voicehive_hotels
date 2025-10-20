"""
Multi-Factor Authentication (MFA) Service
Handles MFA enrollment, verification, recovery codes, and audit logging
"""

import base64
import json
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
import bcrypt
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload

from .totp_service import TOTPService
from database.models import User, UserMFA, MFAAuditLog, MFARecoveryCode
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.mfa_service")


class MFAError(Exception):
    """Base exception for MFA operations"""
    pass


class MFAEnrollmentError(MFAError):
    """Exception raised during MFA enrollment"""
    pass


class MFAVerificationError(MFAError):
    """Exception raised during MFA verification"""
    pass


class MFAService:
    """Service for handling Multi-Factor Authentication operations"""

    def __init__(self, db_session: AsyncSession, encryption_key: str):
        """
        Initialize MFA service

        Args:
            db_session: Database session for MFA operations
            encryption_key: Base64-encoded Fernet encryption key for secrets
        """
        self.db_session = db_session
        self.totp_service = TOTPService()

        # Initialize Fernet cipher for encrypting TOTP secrets
        try:
            self.cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        except Exception as e:
            logger.error("failed_to_initialize_mfa_encryption", error=str(e))
            raise MFAError(f"Failed to initialize MFA encryption: {str(e)}")

    @classmethod
    def generate_encryption_key(cls) -> str:
        """
        Generate a new Fernet encryption key for MFA secrets

        Returns:
            Base64-encoded Fernet key
        """
        key = Fernet.generate_key()
        return key.decode('utf-8')

    def _encrypt_secret(self, secret: str) -> str:
        """
        Encrypt a TOTP secret

        Args:
            secret: Plain text TOTP secret

        Returns:
            Encrypted secret as base64 string
        """
        try:
            encrypted_bytes = self.cipher.encrypt(secret.encode('utf-8'))
            return base64.b64encode(encrypted_bytes).decode('utf-8')
        except Exception as e:
            logger.error("failed_to_encrypt_totp_secret", error=str(e))
            raise MFAError("Failed to encrypt TOTP secret")

    def _decrypt_secret(self, encrypted_secret: str) -> str:
        """
        Decrypt a TOTP secret

        Args:
            encrypted_secret: Base64-encoded encrypted secret

        Returns:
            Plain text TOTP secret
        """
        try:
            encrypted_bytes = base64.b64decode(encrypted_secret.encode('utf-8'))
            decrypted_bytes = self.cipher.decrypt(encrypted_bytes)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error("failed_to_decrypt_totp_secret", error=str(e))
            raise MFAError("Failed to decrypt TOTP secret")

    async def _log_mfa_event(
        self,
        user_id: str,
        event_type: str,
        event_result: str,
        verification_method: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log MFA event for audit purposes

        Args:
            user_id: User ID
            event_type: Type of MFA event
            event_result: Result of the event (success, failure, error)
            verification_method: Method used for verification
            ip_address: Client IP address
            user_agent: Client user agent
            session_id: Session ID
            metadata: Additional event metadata
        """
        try:
            audit_log = MFAAuditLog(
                user_id=user_id,
                event_type=event_type,
                event_result=event_result,
                verification_method=verification_method,
                ip_address=ip_address,
                user_agent=user_agent,
                session_id=session_id,
                metadata=metadata or {}
            )

            self.db_session.add(audit_log)
            await self.db_session.commit()

            logger.info(
                "mfa_event_logged",
                user_id=user_id,
                event_type=event_type,
                event_result=event_result,
                verification_method=verification_method
            )
        except Exception as e:
            logger.error("failed_to_log_mfa_event", user_id=user_id, error=str(e))
            # Don't raise here as this is a logging operation

    async def get_user_mfa(self, user_id: str) -> Optional[UserMFA]:
        """
        Get user's MFA settings

        Args:
            user_id: User ID

        Returns:
            UserMFA object or None if not found
        """
        try:
            result = await self.db_session.execute(
                select(UserMFA).where(UserMFA.user_id == user_id)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error("failed_to_get_user_mfa", user_id=user_id, error=str(e))
            raise MFAError("Failed to retrieve MFA settings")

    async def is_mfa_enabled(self, user_id: str) -> bool:
        """
        Check if MFA is enabled for user

        Args:
            user_id: User ID

        Returns:
            True if MFA is enabled and properly configured
        """
        user_mfa = await self.get_user_mfa(user_id)
        return user_mfa is not None and user_mfa.is_enrolled()

    async def start_enrollment(self, user_id: str, enrolled_by: str) -> Dict[str, Any]:
        """
        Start MFA enrollment process for a user

        Args:
            user_id: User ID to enroll
            enrolled_by: User ID of who is enrolling this user

        Returns:
            Dictionary with provisioning URI and QR code data
        """
        try:
            # Check if user already has MFA enabled
            existing_mfa = await self.get_user_mfa(user_id)
            if existing_mfa and existing_mfa.is_enrolled():
                raise MFAEnrollmentError("MFA is already enabled for this user")

            # Get user details for QR code
            result = await self.db_session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                raise MFAEnrollmentError("User not found")

            # Generate TOTP secret
            totp_secret = self.totp_service.generate_secret()

            # Encrypt the secret
            encrypted_secret = self._encrypt_secret(totp_secret)

            # Create or update MFA record
            if existing_mfa:
                existing_mfa.totp_secret = encrypted_secret
                existing_mfa.enabled = False  # Will be enabled after verification
                existing_mfa.enrolled_by = enrolled_by
                existing_mfa.updated_at = datetime.now(timezone.utc)
            else:
                user_mfa = UserMFA(
                    user_id=user_id,
                    totp_secret=encrypted_secret,
                    enabled=False,  # Will be enabled after verification
                    enrolled_by=enrolled_by
                )
                self.db_session.add(user_mfa)

            await self.db_session.commit()

            # Generate provisioning URI and QR code
            provisioning_uri = self.totp_service.generate_provisioning_uri(
                totp_secret, user.email
            )
            qr_code_data = self.totp_service.generate_qr_code(provisioning_uri)

            await self._log_mfa_event(
                user_id=user_id,
                event_type="enrollment",
                event_result="success",
                metadata={"enrolled_by": enrolled_by}
            )

            logger.info("mfa_enrollment_started", user_id=user_id, enrolled_by=enrolled_by)

            return {
                "provisioning_uri": provisioning_uri,
                "qr_code": base64.b64encode(qr_code_data).decode('utf-8'),
                "secret": totp_secret  # Only return for initial setup
            }

        except MFAEnrollmentError:
            await self._log_mfa_event(
                user_id=user_id,
                event_type="enrollment",
                event_result="failure"
            )
            raise
        except Exception as e:
            await self._log_mfa_event(
                user_id=user_id,
                event_type="enrollment",
                event_result="error",
                metadata={"error": str(e)}
            )
            logger.error("mfa_enrollment_error", user_id=user_id, error=str(e))
            raise MFAEnrollmentError(f"Failed to start MFA enrollment: {str(e)}")

    async def complete_enrollment(
        self,
        user_id: str,
        verification_code: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """
        Complete MFA enrollment by verifying the first TOTP code

        Args:
            user_id: User ID
            verification_code: TOTP code to verify
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Dictionary with recovery codes
        """
        try:
            user_mfa = await self.get_user_mfa(user_id)
            if not user_mfa or not user_mfa.totp_secret:
                raise MFAEnrollmentError("MFA enrollment not started")

            if user_mfa.enabled:
                raise MFAEnrollmentError("MFA is already enabled")

            # Decrypt secret and verify code
            totp_secret = self._decrypt_secret(user_mfa.totp_secret)

            # Get user email for logging
            result = await self.db_session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            user_email = user.email if user else None

            if not self.totp_service.verify_token(totp_secret, verification_code, user_email):
                await self._log_mfa_event(
                    user_id=user_id,
                    event_type="enrollment",
                    event_result="failure",
                    verification_method="totp",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={"reason": "invalid_verification_code"}
                )
                raise MFAVerificationError("Invalid verification code")

            # Enable MFA
            user_mfa.enabled = True
            user_mfa.enrolled_at = datetime.now(timezone.utc)
            user_mfa.last_verified_at = datetime.now(timezone.utc)

            # Generate recovery codes
            recovery_codes = await self._generate_recovery_codes(user_id)

            await self.db_session.commit()

            await self._log_mfa_event(
                user_id=user_id,
                event_type="enrollment",
                event_result="success",
                verification_method="totp",
                ip_address=ip_address,
                user_agent=user_agent
            )

            logger.info("mfa_enrollment_completed", user_id=user_id)

            return {"recovery_codes": recovery_codes}

        except (MFAEnrollmentError, MFAVerificationError):
            raise
        except Exception as e:
            await self._log_mfa_event(
                user_id=user_id,
                event_type="enrollment",
                event_result="error",
                metadata={"error": str(e)}
            )
            logger.error("mfa_enrollment_completion_error", user_id=user_id, error=str(e))
            raise MFAEnrollmentError(f"Failed to complete MFA enrollment: {str(e)}")

    async def verify_code(
        self,
        user_id: str,
        code: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Verify MFA code (TOTP or recovery code)

        Args:
            user_id: User ID
            code: MFA code to verify
            ip_address: Client IP address
            user_agent: Client user agent
            session_id: Session ID

        Returns:
            True if verification successful
        """
        try:
            user_mfa = await self.get_user_mfa(user_id)
            if not user_mfa or not user_mfa.is_enrolled():
                raise MFAVerificationError("MFA is not enabled for this user")

            # Get user email for logging
            result = await self.db_session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            user_email = user.email if user else None

            # Try TOTP verification first
            totp_secret = self._decrypt_secret(user_mfa.totp_secret)
            if self.totp_service.verify_token(totp_secret, code, user_email):
                # Update last verified time
                user_mfa.last_verified_at = datetime.now(timezone.utc)
                await self.db_session.commit()

                await self._log_mfa_event(
                    user_id=user_id,
                    event_type="verification",
                    event_result="success",
                    verification_method="totp",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    session_id=session_id
                )

                logger.info("mfa_totp_verification_success", user_id=user_id)
                return True

            # Try recovery code verification
            if await self._verify_recovery_code(user_id, code, ip_address):
                user_mfa.last_verified_at = datetime.now(timezone.utc)
                await self.db_session.commit()

                await self._log_mfa_event(
                    user_id=user_id,
                    event_type="verification",
                    event_result="success",
                    verification_method="recovery_code",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    session_id=session_id
                )

                logger.info("mfa_recovery_verification_success", user_id=user_id)
                return True

            # Verification failed
            await self._log_mfa_event(
                user_id=user_id,
                event_type="verification",
                event_result="failure",
                ip_address=ip_address,
                user_agent=user_agent,
                session_id=session_id,
                metadata={"reason": "invalid_code"}
            )

            logger.warning("mfa_verification_failed", user_id=user_id)
            return False

        except MFAVerificationError:
            raise
        except Exception as e:
            await self._log_mfa_event(
                user_id=user_id,
                event_type="verification",
                event_result="error",
                metadata={"error": str(e)}
            )
            logger.error("mfa_verification_error", user_id=user_id, error=str(e))
            raise MFAVerificationError(f"MFA verification failed: {str(e)}")

    async def _generate_recovery_codes(self, user_id: str, count: int = 10) -> List[str]:
        """
        Generate recovery codes for user

        Args:
            user_id: User ID
            count: Number of recovery codes to generate

        Returns:
            List of recovery codes (plaintext, only returned once)
        """
        recovery_codes = []

        # Delete existing recovery codes
        await self.db_session.execute(
            delete(MFARecoveryCode).where(MFARecoveryCode.user_id == user_id)
        )

        # Generate new recovery codes
        for _ in range(count):
            # Generate 8-character alphanumeric code
            code = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8))
            recovery_codes.append(code)

            # Hash and store the code
            code_hash = bcrypt.hashpw(code.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            recovery_code_record = MFARecoveryCode(
                user_id=user_id,
                code_hash=code_hash,
                generated_by=user_id  # User generates their own codes
            )
            self.db_session.add(recovery_code_record)

        # Update user MFA record
        user_mfa = await self.get_user_mfa(user_id)
        if user_mfa:
            user_mfa.recovery_codes_generated_at = datetime.now(timezone.utc)
            user_mfa.recovery_codes_used_count = 0

        await self.db_session.commit()

        await self._log_mfa_event(
            user_id=user_id,
            event_type="recovery_code_generated",
            event_result="success",
            metadata={"count": count}
        )

        logger.info("recovery_codes_generated", user_id=user_id, count=count)
        return recovery_codes

    async def _verify_recovery_code(self, user_id: str, code: str, ip_address: Optional[str] = None) -> bool:
        """
        Verify a recovery code

        Args:
            user_id: User ID
            code: Recovery code to verify
            ip_address: Client IP address

        Returns:
            True if valid recovery code
        """
        try:
            # Get unused recovery codes for user
            result = await self.db_session.execute(
                select(MFARecoveryCode).where(
                    MFARecoveryCode.user_id == user_id,
                    MFARecoveryCode.used == False
                )
            )
            recovery_codes = result.scalars().all()

            # Check each code
            for recovery_code_record in recovery_codes:
                if bcrypt.checkpw(code.encode('utf-8'), recovery_code_record.code_hash.encode('utf-8')):
                    # Mark code as used
                    recovery_code_record.mark_used(ip_address)

                    # Update user MFA used count
                    user_mfa = await self.get_user_mfa(user_id)
                    if user_mfa:
                        user_mfa.recovery_codes_used_count += 1

                    await self.db_session.commit()

                    await self._log_mfa_event(
                        user_id=user_id,
                        event_type="recovery_code_used",
                        event_result="success",
                        verification_method="recovery_code",
                        ip_address=ip_address
                    )

                    return True

            return False

        except Exception as e:
            logger.error("recovery_code_verification_error", user_id=user_id, error=str(e))
            return False

    async def disable_mfa(self, user_id: str, disabled_by: str) -> None:
        """
        Disable MFA for a user

        Args:
            user_id: User ID
            disabled_by: User ID of who is disabling MFA
        """
        try:
            user_mfa = await self.get_user_mfa(user_id)
            if not user_mfa:
                raise MFAError("MFA is not configured for this user")

            # Disable MFA
            user_mfa.enabled = False
            user_mfa.totp_secret = None
            user_mfa.updated_at = datetime.now(timezone.utc)

            # Delete recovery codes
            await self.db_session.execute(
                delete(MFARecoveryCode).where(MFARecoveryCode.user_id == user_id)
            )

            await self.db_session.commit()

            await self._log_mfa_event(
                user_id=user_id,
                event_type="disabled",
                event_result="success",
                metadata={"disabled_by": disabled_by}
            )

            logger.info("mfa_disabled", user_id=user_id, disabled_by=disabled_by)

        except Exception as e:
            await self._log_mfa_event(
                user_id=user_id,
                event_type="disabled",
                event_result="error",
                metadata={"error": str(e)}
            )
            logger.error("mfa_disable_error", user_id=user_id, error=str(e))
            raise MFAError(f"Failed to disable MFA: {str(e)}")

    async def regenerate_recovery_codes(self, user_id: str) -> List[str]:
        """
        Regenerate recovery codes for a user

        Args:
            user_id: User ID

        Returns:
            New list of recovery codes
        """
        user_mfa = await self.get_user_mfa(user_id)
        if not user_mfa or not user_mfa.is_enrolled():
            raise MFAError("MFA is not enabled for this user")

        return await self._generate_recovery_codes(user_id)

    async def get_mfa_status(self, user_id: str) -> Dict[str, Any]:
        """
        Get MFA status for a user

        Args:
            user_id: User ID

        Returns:
            Dictionary with MFA status information
        """
        user_mfa = await self.get_user_mfa(user_id)

        if not user_mfa:
            return {
                "enabled": False,
                "enrolled": False,
                "recovery_codes_available": 0
            }

        # Count unused recovery codes
        result = await self.db_session.execute(
            select(MFARecoveryCode).where(
                MFARecoveryCode.user_id == user_id,
                MFARecoveryCode.used == False
            )
        )
        unused_codes_count = len(result.scalars().all())

        return {
            "enabled": user_mfa.enabled,
            "enrolled": user_mfa.is_enrolled(),
            "enrolled_at": user_mfa.enrolled_at.isoformat() if user_mfa.enrolled_at else None,
            "last_verified_at": user_mfa.last_verified_at.isoformat() if user_mfa.last_verified_at else None,
            "recovery_codes_available": unused_codes_count,
            "recovery_codes_used": user_mfa.recovery_codes_used_count
        }