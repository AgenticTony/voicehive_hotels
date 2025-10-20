"""
Authentication router for VoiceHive Hotels Orchestrator
Handles login, logout, token refresh, and API key management
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from auth_models import (
    LoginRequest, LoginResponse, RefreshTokenRequest, LogoutRequest,
    APIKeyRequest, APIKeyResponse, UserContext, ServiceContext,
    UserRole, get_permissions_for_roles, AuthenticationError
)
from auth.mfa_models import (
    MFAEnrollmentRequest, MFAEnrollmentResponse, MFAEnrollmentVerificationRequest,
    MFAEnrollmentVerificationResponse, MFAVerificationRequest, MFAVerificationResponse,
    MFAStatusResponse, MFADisableRequest, MFADisableResponse,
    MFARecoveryCodesRegenerateRequest, MFARecoveryCodesRegenerateResponse,
    MFAAuditLogResponse, MFAAdminStatusResponse
)
from auth.mfa_service import MFAService
from auth.mfa_middleware import get_mfa_service, RequireMFAEnabled, RequireRecentMFA, mfa_verification_tracker
from auth_middleware import get_current_user, get_current_service, require_permissions, Permission
from jwt_service import JWTService
from vault_client import VaultClient
from user_service import UserService
from database.connection import get_db_session
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.auth_router")

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


class AuthService:
    """Authentication service using database-backed user management"""

    def __init__(self, jwt_service: JWTService, user_service: UserService):
        self.jwt_service = jwt_service
        self.user_service = user_service

    async def authenticate_user(self, email: str, password: str) -> UserContext:
        """Authenticate user with email and password using database"""

        # Authenticate with database
        user_context = await self.user_service.authenticate_user(email, password)
        if not user_context:
            raise AuthenticationError("Invalid credentials")

        logger.info(
            "user_authenticated",
            user_id=user_context.user_id,
            email=user_context.email,
            roles=[role.value for role in user_context.roles]
        )

        return user_context


# Initialize services (these would be injected in production)
jwt_service = None
vault_client = None


def get_jwt_service() -> JWTService:
    """Dependency to get JWT service"""
    global jwt_service
    if not jwt_service:
        raise HTTPException(status_code=500, detail="JWT service not initialized")
    return jwt_service


def get_vault_client() -> VaultClient:
    """Dependency to get Vault client"""
    global vault_client
    if not vault_client:
        raise HTTPException(status_code=500, detail="Vault client not initialized")
    return vault_client


async def get_auth_service(
    db_session: AsyncSession = Depends(get_db_session),
    jwt_svc: JWTService = Depends(get_jwt_service)
) -> AuthService:
    """Dependency to get Auth service with database session"""
    user_service = UserService(db_session)
    return AuthService(jwt_svc, user_service)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    auth_svc: AuthService = Depends(get_auth_service),
    jwt_svc: JWTService = Depends(get_jwt_service)
):
    """
    Authenticate user and return JWT tokens
    """
    try:
        # Authenticate user
        user_context = await auth_svc.authenticate_user(request.email, request.password)
        
        # Create JWT tokens
        tokens = await jwt_svc.create_tokens(user_context)
        
        # Update user context with session info
        user_context.session_id = tokens["session_id"]
        
        response = LoginResponse(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            token_type=tokens["token_type"],
            expires_in=tokens["expires_in"],
            user=user_context
        )
        
        logger.info(
            "user_logged_in",
            user_id=user_context.user_id,
            email=user_context.email,
            session_id=user_context.session_id
        )
        
        return response
        
    except AuthenticationError as e:
        logger.warning("login_failed", email=request.email, error=str(e))
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error("login_error", email=request.email, error=str(e))
        raise HTTPException(status_code=500, detail="Login failed")


@router.post("/refresh")
async def refresh_token(
    request: RefreshTokenRequest,
    jwt_svc: JWTService = Depends(get_jwt_service)
):
    """
    Refresh access token using refresh token
    """
    try:
        tokens = await jwt_svc.refresh_token(request.refresh_token)
        
        logger.info("token_refreshed")
        
        return tokens
        
    except AuthenticationError as e:
        logger.warning("token_refresh_failed", error=str(e))
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        logger.error("token_refresh_error", error=str(e))
        raise HTTPException(status_code=500, detail="Token refresh failed")


@router.post("/logout")
async def logout(
    request: LogoutRequest,
    current_user: UserContext = Depends(get_current_user),
    jwt_svc: JWTService = Depends(get_jwt_service)
):
    """
    Logout user and invalidate session(s)
    """
    try:
        if request.all_sessions:
            # Logout all sessions for the user
            await jwt_svc.logout_all_sessions(current_user.user_id)
            logger.info("all_sessions_logged_out", user_id=current_user.user_id)
        else:
            # Logout specific session
            session_id = request.session_id or current_user.session_id
            await jwt_svc.logout_session(session_id)
            logger.info("session_logged_out", user_id=current_user.user_id, session_id=session_id)
        
        return {"message": "Logged out successfully"}
        
    except Exception as e:
        logger.error("logout_error", user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Logout failed")


@router.post("/api-keys", response_model=APIKeyResponse)
async def create_api_key(
    request: APIKeyRequest,
    current_user: UserContext = Depends(require_permissions(Permission.SYSTEM_ADMIN)),
    vault: VaultClient = Depends(get_vault_client)
):
    """
    Create a new API key for service-to-service authentication
    Requires SYSTEM_ADMIN permission
    """
    try:
        api_key_response = await vault.create_api_key(request)
        
        logger.info(
            "api_key_created",
            api_key_id=api_key_response.api_key_id,
            service_name=request.service_name,
            created_by=current_user.user_id
        )
        
        return api_key_response
        
    except Exception as e:
        logger.error("api_key_creation_error", service_name=request.service_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to create API key: {str(e)}")


@router.get("/api-keys")
async def list_api_keys(
    service_name: Optional[str] = None,
    current_user: UserContext = Depends(require_permissions(Permission.SYSTEM_ADMIN)),
    vault: VaultClient = Depends(get_vault_client)
):
    """
    List API keys, optionally filtered by service name
    Requires SYSTEM_ADMIN permission
    """
    try:
        api_keys = await vault.list_api_keys(service_name)
        
        logger.info(
            "api_keys_listed",
            count=len(api_keys),
            service_filter=service_name,
            requested_by=current_user.user_id
        )
        
        return {"api_keys": api_keys}
        
    except Exception as e:
        logger.error("api_key_listing_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to list API keys: {str(e)}")


@router.delete("/api-keys/{api_key_id}")
async def revoke_api_key(
    api_key_id: str,
    current_user: UserContext = Depends(require_permissions(Permission.SYSTEM_ADMIN)),
    vault: VaultClient = Depends(get_vault_client)
):
    """
    Revoke an API key
    Requires SYSTEM_ADMIN permission
    """
    try:
        await vault.revoke_api_key(api_key_id)
        
        logger.info(
            "api_key_revoked",
            api_key_id=api_key_id,
            revoked_by=current_user.user_id
        )
        
        return {"message": f"API key {api_key_id} revoked successfully"}
        
    except Exception as e:
        logger.error("api_key_revocation_error", api_key_id=api_key_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to revoke API key: {str(e)}")


@router.get("/me")
async def get_current_user_info(
    current_user: UserContext = Depends(get_current_user)
):
    """
    Get current user information
    """
    return {
        "user": current_user,
        "authenticated_at": datetime.utcnow().isoformat()
    }


@router.get("/service-info")
async def get_current_service_info(
    current_service: ServiceContext = Depends(get_current_service)
):
    """
    Get current service information
    """
    return {
        "service": current_service,
        "authenticated_at": datetime.utcnow().isoformat()
    }


# ==================== MFA ENDPOINTS ====================

@router.post("/mfa/enroll", response_model=MFAEnrollmentResponse)
async def start_mfa_enrollment(
    request: MFAEnrollmentRequest,
    current_user: UserContext = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service)
):
    """
    Start MFA enrollment process for the current user
    Returns QR code and provisioning URI for authenticator app setup
    """
    try:
        enrollment_data = await mfa_service.start_enrollment(
            user_id=str(current_user.user_id),
            enrolled_by=str(current_user.user_id)
        )

        logger.info(
            "mfa_enrollment_started",
            user_id=current_user.user_id,
            email=current_user.email
        )

        return MFAEnrollmentResponse(
            provisioning_uri=enrollment_data["provisioning_uri"],
            qr_code=enrollment_data["qr_code"]
        )

    except Exception as e:
        logger.error("mfa_enrollment_start_error", user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mfa/enroll/verify", response_model=MFAEnrollmentVerificationResponse)
async def complete_mfa_enrollment(
    request: MFAEnrollmentVerificationRequest,
    current_user: UserContext = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service),
    http_request: Request = None
):
    """
    Complete MFA enrollment by verifying the first TOTP code
    Returns recovery codes that should be saved securely
    """
    try:
        ip_address = http_request.client.host if http_request else None
        user_agent = http_request.headers.get("User-Agent") if http_request else None

        completion_data = await mfa_service.complete_enrollment(
            user_id=str(current_user.user_id),
            verification_code=request.verification_code,
            ip_address=ip_address,
            user_agent=user_agent
        )

        logger.info(
            "mfa_enrollment_completed",
            user_id=current_user.user_id,
            email=current_user.email
        )

        return MFAEnrollmentVerificationResponse(
            success=True,
            recovery_codes=completion_data["recovery_codes"]
        )

    except Exception as e:
        logger.error("mfa_enrollment_completion_error", user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mfa/verify", response_model=MFAVerificationResponse)
async def verify_mfa_code(
    request: MFAVerificationRequest,
    current_user: UserContext = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service),
    http_request: Request = None
):
    """
    Verify MFA code (TOTP or recovery code)
    Marks the session as MFA-verified for subsequent operations
    """
    try:
        ip_address = http_request.client.host if http_request else None
        user_agent = http_request.headers.get("User-Agent") if http_request else None
        session_id = getattr(current_user, 'session_id', None)

        is_valid = await mfa_service.verify_code(
            user_id=str(current_user.user_id),
            code=request.code,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id
        )

        if is_valid:
            # Mark session as MFA verified
            if session_id:
                mfa_verification_tracker.mark_mfa_verified(session_id, str(current_user.user_id))

            # Determine verification method
            verification_method = "totp" if len(request.code) == 6 else "recovery_code"

            # Get remaining recovery codes if used
            remaining_codes = None
            if verification_method == "recovery_code":
                mfa_status = await mfa_service.get_mfa_status(str(current_user.user_id))
                remaining_codes = mfa_status.get("recovery_codes_available", 0)

            logger.info(
                "mfa_verification_success",
                user_id=current_user.user_id,
                verification_method=verification_method
            )

            return MFAVerificationResponse(
                success=True,
                verification_method=verification_method,
                message="MFA verification successful",
                remaining_recovery_codes=remaining_codes
            )
        else:
            logger.warning("mfa_verification_failed", user_id=current_user.user_id)
            return MFAVerificationResponse(
                success=False,
                verification_method="unknown",
                message="Invalid MFA code"
            )

    except Exception as e:
        logger.error("mfa_verification_error", user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/mfa/status", response_model=MFAStatusResponse)
async def get_mfa_status(
    current_user: UserContext = Depends(get_current_user),
    mfa_service: MFAService = Depends(get_mfa_service)
):
    """
    Get current user's MFA status and configuration
    """
    try:
        status_data = await mfa_service.get_mfa_status(str(current_user.user_id))

        return MFAStatusResponse(
            enabled=status_data["enabled"],
            enrolled=status_data["enrolled"],
            enrolled_at=status_data.get("enrolled_at"),
            last_verified_at=status_data.get("last_verified_at"),
            recovery_codes_available=status_data["recovery_codes_available"],
            recovery_codes_used=status_data["recovery_codes_used"]
        )

    except Exception as e:
        logger.error("mfa_status_error", user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve MFA status")


@router.post("/mfa/disable", response_model=MFADisableResponse)
async def disable_mfa(
    request: MFADisableRequest,
    current_user: UserContext = RequireMFAEnabled,
    mfa_service: MFAService = Depends(get_mfa_service),
    auth_svc: AuthService = Depends(get_auth_service)
):
    """
    Disable MFA for the current user
    Requires current password confirmation and MFA to be currently enabled
    """
    try:
        # Verify current password
        try:
            await auth_svc.authenticate_user(current_user.email, request.current_password)
        except AuthenticationError:
            raise HTTPException(status_code=401, detail="Invalid current password")

        await mfa_service.disable_mfa(
            user_id=str(current_user.user_id),
            disabled_by=str(current_user.user_id)
        )

        logger.info("mfa_disabled", user_id=current_user.user_id, email=current_user.email)

        return MFADisableResponse(success=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("mfa_disable_error", user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to disable MFA: {str(e)}")


@router.post("/mfa/recovery-codes/regenerate", response_model=MFARecoveryCodesRegenerateResponse)
async def regenerate_recovery_codes(
    request: MFARecoveryCodesRegenerateRequest,
    current_user: UserContext = RequireRecentMFA,
    mfa_service: MFAService = Depends(get_mfa_service),
    auth_svc: AuthService = Depends(get_auth_service)
):
    """
    Regenerate recovery codes for the current user
    Requires recent MFA verification and current password
    """
    try:
        # Verify current password
        try:
            await auth_svc.authenticate_user(current_user.email, request.current_password)
        except AuthenticationError:
            raise HTTPException(status_code=401, detail="Invalid current password")

        recovery_codes = await mfa_service.regenerate_recovery_codes(str(current_user.user_id))

        logger.info("recovery_codes_regenerated", user_id=current_user.user_id)

        return MFARecoveryCodesRegenerateResponse(recovery_codes=recovery_codes)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("recovery_codes_regenerate_error", user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to regenerate recovery codes: {str(e)}")


@router.get("/mfa/audit-log", response_model=MFAAuditLogResponse)
async def get_mfa_audit_log(
    page: int = 1,
    page_size: int = 50,
    current_user: UserContext = RequireMFAEnabled,
    mfa_service: MFAService = Depends(get_mfa_service)
):
    """
    Get MFA audit log for the current user
    Shows recent MFA-related events for security monitoring
    """
    try:
        # This would need to be implemented in the MFA service
        # For now, return empty response
        return MFAAuditLogResponse(
            events=[],
            total_count=0,
            page=page,
            page_size=page_size
        )

    except Exception as e:
        logger.error("mfa_audit_log_error", user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve audit log")


# Admin MFA endpoints
@router.get("/admin/mfa/users/{user_id}/status", response_model=MFAAdminStatusResponse)
async def get_user_mfa_status_admin(
    user_id: str,
    current_user: UserContext = Depends(require_permissions(Permission.SYSTEM_ADMIN)),
    mfa_service: MFAService = Depends(get_mfa_service),
    db_session: AsyncSession = Depends(get_db_session)
):
    """
    Get MFA status for any user (admin only)
    """
    try:
        # Get user details
        from sqlalchemy import select
        from database.models import User

        result = await db_session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        status_data = await mfa_service.get_mfa_status(user_id)

        return MFAAdminStatusResponse(
            user_id=user_id,
            email=user.email,
            mfa_enabled=status_data["enabled"],
            enrolled_at=status_data.get("enrolled_at"),
            last_verified_at=status_data.get("last_verified_at"),
            recovery_codes_available=status_data["recovery_codes_available"],
            failed_attempts_today=0  # Would need implementation
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("admin_mfa_status_error", target_user_id=user_id, admin_user_id=current_user.user_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve user MFA status")


@router.post("/admin/mfa/users/{user_id}/disable")
async def disable_user_mfa_admin(
    user_id: str,
    current_user: UserContext = Depends(require_permissions(Permission.SYSTEM_ADMIN)),
    mfa_service: MFAService = Depends(get_mfa_service)
):
    """
    Disable MFA for any user (admin only)
    Emergency function for account recovery
    """
    try:
        await mfa_service.disable_mfa(
            user_id=user_id,
            disabled_by=str(current_user.user_id)
        )

        logger.info(
            "admin_mfa_disabled",
            target_user_id=user_id,
            admin_user_id=current_user.user_id,
            admin_email=current_user.email
        )

        return {"message": f"MFA disabled for user {user_id}"}

    except Exception as e:
        logger.error(
            "admin_mfa_disable_error",
            target_user_id=user_id,
            admin_user_id=current_user.user_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Failed to disable user MFA: {str(e)}")


# Service initialization functions (called from main app)
def initialize_auth_services(jwt_svc: JWTService, vault: VaultClient):
    """Initialize authentication services"""
    global jwt_service, vault_client
    jwt_service = jwt_svc
    vault_client = vault
    logger.info("auth_services_initialized")