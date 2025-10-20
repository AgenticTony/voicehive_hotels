"""
Multi-Factor Authentication (MFA) Middleware and Dependencies
Handles MFA verification requirements for protected endpoints
"""

from datetime import datetime, timezone
from typing import Optional, List, Callable
from fastapi import Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .mfa_service import MFAService
from auth_models import UserContext, AuthenticationError
from database.connection import get_db_session
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.mfa_middleware")

# Security scheme for MFA endpoints
mfa_security = HTTPBearer(auto_error=True)


class MFARequiredError(HTTPException):
    """Exception raised when MFA verification is required"""

    def __init__(self, detail: str = "Multi-factor authentication required"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "MFA_REQUIRED",
                "message": detail,
                "timestamp": datetime.utcnow().isoformat()
            }
        )


class MFANotEnabledError(HTTPException):
    """Exception raised when MFA is not enabled for user"""

    def __init__(self, detail: str = "Multi-factor authentication is not enabled"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "MFA_NOT_ENABLED",
                "message": detail,
                "timestamp": datetime.utcnow().isoformat()
            }
        )


async def get_mfa_service(
    db_session: AsyncSession = Depends(get_db_session)
) -> MFAService:
    """
    Dependency to get MFA service

    Args:
        db_session: Database session

    Returns:
        MFAService instance
    """
    # TODO: Get encryption key from secure configuration
    # This should be loaded from environment or vault
    encryption_key = "your-base64-encoded-fernet-key-here"  # Replace with actual key

    try:
        return MFAService(db_session, encryption_key)
    except Exception as e:
        logger.error("failed_to_create_mfa_service", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MFA service unavailable"
        )


async def require_mfa_enabled(
    current_user: UserContext,
    mfa_service: MFAService = Depends(get_mfa_service)
) -> UserContext:
    """
    Dependency that requires user to have MFA enabled

    Args:
        current_user: Current authenticated user
        mfa_service: MFA service instance

    Returns:
        UserContext if MFA is enabled

    Raises:
        MFANotEnabledError: If MFA is not enabled
    """
    try:
        is_enabled = await mfa_service.is_mfa_enabled(str(current_user.user_id))

        if not is_enabled:
            logger.warning(
                "mfa_not_enabled_access_attempt",
                user_id=current_user.user_id,
                email=current_user.email
            )
            raise MFANotEnabledError("Multi-factor authentication must be enabled to access this resource")

        logger.debug("mfa_enabled_check_passed", user_id=current_user.user_id)
        return current_user

    except MFANotEnabledError:
        raise
    except Exception as e:
        logger.error(
            "mfa_enabled_check_error",
            user_id=current_user.user_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to verify MFA status"
        )


async def require_recent_mfa_verification(
    current_user: UserContext,
    mfa_service: MFAService = Depends(get_mfa_service),
    max_age_minutes: int = 15
) -> UserContext:
    """
    Dependency that requires recent MFA verification

    Args:
        current_user: Current authenticated user
        mfa_service: MFA service instance
        max_age_minutes: Maximum age of MFA verification in minutes

    Returns:
        UserContext if recent MFA verification exists

    Raises:
        MFARequiredError: If recent MFA verification is required
    """
    try:
        # First check if MFA is enabled
        user_mfa = await mfa_service.get_user_mfa(str(current_user.user_id))

        if not user_mfa or not user_mfa.is_enrolled():
            raise MFANotEnabledError("Multi-factor authentication is required")

        # Check if recent verification exists
        if user_mfa.last_verified_at:
            time_since_verification = datetime.now(timezone.utc) - user_mfa.last_verified_at
            if time_since_verification.total_seconds() / 60 <= max_age_minutes:
                logger.debug(
                    "recent_mfa_verification_found",
                    user_id=current_user.user_id,
                    minutes_ago=time_since_verification.total_seconds() / 60
                )
                return current_user

        logger.warning(
            "recent_mfa_verification_required",
            user_id=current_user.user_id,
            email=current_user.email,
            max_age_minutes=max_age_minutes
        )

        raise MFARequiredError(
            f"Recent multi-factor authentication verification required (within {max_age_minutes} minutes)"
        )

    except (MFARequiredError, MFANotEnabledError):
        raise
    except Exception as e:
        logger.error(
            "recent_mfa_verification_check_error",
            user_id=current_user.user_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to verify recent MFA verification"
        )


def require_mfa_for_sensitive_operations(max_age_minutes: int = 5):
    """
    Factory function to create MFA requirement dependency for sensitive operations

    Args:
        max_age_minutes: Maximum age of MFA verification in minutes

    Returns:
        Dependency function that requires recent MFA verification
    """
    async def _require_recent_mfa(
        current_user: UserContext,
        mfa_service: MFAService = Depends(get_mfa_service)
    ) -> UserContext:
        return await require_recent_mfa_verification(
            current_user, mfa_service, max_age_minutes
        )

    return _require_recent_mfa


class MFAVerificationTracker:
    """
    Service to track MFA verification status in user sessions
    """

    def __init__(self):
        # In production, this should use Redis or database storage
        # For now, using in-memory storage (will be lost on restart)
        self._verification_cache = {}

    def mark_mfa_verified(self, session_id: str, user_id: str) -> None:
        """
        Mark session as MFA verified

        Args:
            session_id: Session ID
            user_id: User ID
        """
        self._verification_cache[session_id] = {
            "user_id": user_id,
            "verified_at": datetime.now(timezone.utc)
        }

        logger.info(
            "mfa_session_marked_verified",
            session_id=session_id,
            user_id=user_id
        )

    def is_mfa_verified(self, session_id: str, user_id: str, max_age_minutes: int = 15) -> bool:
        """
        Check if session has valid MFA verification

        Args:
            session_id: Session ID to check
            user_id: User ID to verify
            max_age_minutes: Maximum age of verification

        Returns:
            True if session has valid MFA verification
        """
        if session_id not in self._verification_cache:
            return False

        verification_data = self._verification_cache[session_id]

        # Check user ID matches
        if verification_data["user_id"] != user_id:
            return False

        # Check age
        verification_age = datetime.now(timezone.utc) - verification_data["verified_at"]
        if verification_age.total_seconds() / 60 > max_age_minutes:
            # Remove expired verification
            del self._verification_cache[session_id]
            return False

        return True

    def clear_mfa_verification(self, session_id: str) -> None:
        """
        Clear MFA verification for session

        Args:
            session_id: Session ID to clear
        """
        if session_id in self._verification_cache:
            del self._verification_cache[session_id]
            logger.info("mfa_session_verification_cleared", session_id=session_id)


# Global instance for MFA verification tracking
mfa_verification_tracker = MFAVerificationTracker()


async def require_session_mfa_verification(
    request: Request,
    current_user: UserContext,
    max_age_minutes: int = 15
) -> UserContext:
    """
    Dependency that requires session-based MFA verification

    Args:
        request: FastAPI request object
        current_user: Current authenticated user
        max_age_minutes: Maximum age of verification in minutes

    Returns:
        UserContext if session has valid MFA verification

    Raises:
        MFARequiredError: If session MFA verification is required
    """
    # Get session ID from user context or request
    session_id = getattr(current_user, 'session_id', None)

    if not session_id:
        logger.warning(
            "no_session_id_for_mfa_check",
            user_id=current_user.user_id
        )
        raise MFARequiredError("Session-based MFA verification required")

    if mfa_verification_tracker.is_mfa_verified(
        session_id,
        str(current_user.user_id),
        max_age_minutes
    ):
        logger.debug(
            "session_mfa_verification_valid",
            user_id=current_user.user_id,
            session_id=session_id
        )
        return current_user

    logger.warning(
        "session_mfa_verification_required",
        user_id=current_user.user_id,
        session_id=session_id,
        max_age_minutes=max_age_minutes
    )

    raise MFARequiredError(
        f"Session multi-factor authentication verification required (within {max_age_minutes} minutes)"
    )


def create_mfa_dependency(
    verification_type: str = "recent",
    max_age_minutes: int = 15
) -> Callable:
    """
    Factory function to create different types of MFA dependencies

    Args:
        verification_type: Type of verification ("enabled", "recent", "session")
        max_age_minutes: Maximum age for time-based verifications

    Returns:
        Dependency function for the specified MFA requirement
    """
    if verification_type == "enabled":
        return require_mfa_enabled
    elif verification_type == "recent":
        return require_mfa_for_sensitive_operations(max_age_minutes)
    elif verification_type == "session":
        async def _require_session_mfa(
            request: Request,
            current_user: UserContext
        ) -> UserContext:
            return await require_session_mfa_verification(
                request, current_user, max_age_minutes
            )
        return _require_session_mfa
    else:
        raise ValueError(f"Unknown MFA verification type: {verification_type}")


# Predefined MFA dependencies for common use cases
RequireMFAEnabled = Depends(require_mfa_enabled)
RequireRecentMFA = Depends(require_mfa_for_sensitive_operations(15))
RequireSensitiveMFA = Depends(require_mfa_for_sensitive_operations(5))
RequireSessionMFA = Depends(create_mfa_dependency("session", 15))