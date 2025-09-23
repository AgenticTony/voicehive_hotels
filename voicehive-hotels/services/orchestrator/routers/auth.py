"""
Authentication router for VoiceHive Hotels Orchestrator
Handles login, logout, token refresh, and API key management
"""

import bcrypt
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer

from auth_models import (
    LoginRequest, LoginResponse, RefreshTokenRequest, LogoutRequest,
    APIKeyRequest, APIKeyResponse, UserContext, ServiceContext,
    UserRole, get_permissions_for_roles, AuthenticationError
)
from auth_middleware import get_current_user, get_current_service, require_permissions, Permission
from jwt_service import JWTService
from vault_client import VaultClient
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.auth_router")

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


# Mock user database - In production, this would be a real database
MOCK_USERS = {
    "admin@voicehive-hotels.eu": {
        "user_id": "admin-001",
        "email": "admin@voicehive-hotels.eu",
        "password_hash": bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode(),
        "roles": [UserRole.ADMIN],
        "hotel_ids": None,  # Admin has access to all hotels
        "active": True
    },
    "operator@voicehive-hotels.eu": {
        "user_id": "operator-001",
        "email": "operator@voicehive-hotels.eu",
        "password_hash": bcrypt.hashpw("operator123".encode(), bcrypt.gensalt()).decode(),
        "roles": [UserRole.OPERATOR],
        "hotel_ids": None,
        "active": True
    },
    "manager@hotel1.com": {
        "user_id": "manager-001",
        "email": "manager@hotel1.com",
        "password_hash": bcrypt.hashpw("manager123".encode(), bcrypt.gensalt()).decode(),
        "roles": [UserRole.HOTEL_MANAGER],
        "hotel_ids": ["hotel-001"],
        "active": True
    }
}


class AuthService:
    """Authentication service for user management"""
    
    def __init__(self, jwt_service: JWTService):
        self.jwt_service = jwt_service
    
    async def authenticate_user(self, email: str, password: str) -> UserContext:
        """Authenticate user with email and password"""
        
        # Look up user in mock database
        user_data = MOCK_USERS.get(email)
        if not user_data or not user_data["active"]:
            raise AuthenticationError("Invalid credentials")
        
        # Verify password
        if not bcrypt.checkpw(password.encode(), user_data["password_hash"].encode()):
            raise AuthenticationError("Invalid credentials")
        
        # Create user context
        permissions = get_permissions_for_roles(user_data["roles"])
        
        user_context = UserContext(
            user_id=user_data["user_id"],
            email=user_data["email"],
            roles=user_data["roles"],
            permissions=permissions,
            session_id="",  # Will be set by JWT service
            expires_at=datetime.utcnow(),  # Will be set by JWT service
            hotel_ids=user_data["hotel_ids"]
        )
        
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
auth_service = None


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


def get_auth_service() -> AuthService:
    """Dependency to get Auth service"""
    global auth_service
    if not auth_service:
        raise HTTPException(status_code=500, detail="Auth service not initialized")
    return auth_service


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


# Service initialization functions (called from main app)
def initialize_auth_services(jwt_svc: JWTService, vault: VaultClient):
    """Initialize authentication services"""
    global jwt_service, vault_client, auth_service
    jwt_service = jwt_svc
    vault_client = vault
    auth_service = AuthService(jwt_svc)
    logger.info("auth_services_initialized")