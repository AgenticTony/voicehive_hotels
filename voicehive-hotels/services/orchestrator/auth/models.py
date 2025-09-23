"""
Authentication and Authorization models for VoiceHive Hotels Orchestrator
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class UserRole(str, Enum):
    """User roles for RBAC"""
    SYSTEM_ADMIN = "system_admin"
    HOTEL_ADMIN = "hotel_admin"
    HOTEL_STAFF = "hotel_staff"
    GUEST_USER = "guest_user"


class Permission(str, Enum):
    """System permissions"""
    # Call management
    CALL_START = "call:start"
    CALL_END = "call:end"
    CALL_VIEW = "call:view"
    CALL_MANAGE = "call:manage"
    
    # Hotel management
    HOTEL_CREATE = "hotel:create"
    HOTEL_UPDATE = "hotel:update"
    HOTEL_DELETE = "hotel:delete"
    HOTEL_VIEW = "hotel:view"
    
    # System administration
    SYSTEM_CONFIG = "system:config"
    SYSTEM_MONITOR = "system:monitor"
    SYSTEM_ADMIN = "system:admin"
    
    # User management
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_VIEW = "user:view"


class UserContext(BaseModel):
    """User context for authenticated requests"""
    user_id: str
    email: str
    roles: List[UserRole]
    permissions: List[Permission]
    session_id: str
    expires_at: datetime
    hotel_ids: Optional[List[str]] = None  # Hotels user has access to


class ServiceContext(BaseModel):
    """Service context for service-to-service authentication"""
    service_name: str
    api_key_id: str
    permissions: List[Permission]
    rate_limits: Dict[str, int]
    expires_at: Optional[datetime] = None


class JWTPayload(BaseModel):
    """JWT token payload"""
    sub: str  # user_id
    email: str
    roles: List[str]
    permissions: List[str]
    hotel_ids: Optional[List[str]] = None
    iat: int  # issued at
    exp: int  # expires at
    jti: str  # JWT ID for revocation
    session_id: str


class LoginRequest(BaseModel):
    """Login request model"""
    email: str
    password: str = Field(..., min_length=8)
    remember_me: bool = False


class LoginResponse(BaseModel):
    """Login response model"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserContext


class RefreshTokenRequest(BaseModel):
    """Refresh token request model"""
    refresh_token: str


class LogoutRequest(BaseModel):
    """Logout request model"""
    session_id: Optional[str] = None
    all_sessions: bool = False


class APIKeyRequest(BaseModel):
    """API key creation request"""
    name: str = Field(..., description="Human-readable name for the API key")
    service_name: str
    permissions: List[Permission]
    expires_days: Optional[int] = Field(None, description="Days until expiration, None for no expiration")


class APIKeyResponse(BaseModel):
    """API key creation response"""
    api_key_id: str
    api_key: str  # Only returned once during creation
    name: str
    service_name: str
    permissions: List[Permission]
    created_at: datetime
    expires_at: Optional[datetime] = None


class RateLimitConfig(BaseModel):
    """Rate limiting configuration"""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_limit: int = 10
    algorithm: str = "sliding_window"


class RateLimitResult(BaseModel):
    """Rate limiting check result"""
    allowed: bool
    current_usage: int
    remaining: int
    reset_time: datetime
    retry_after: Optional[int] = None


class AuthenticationError(Exception):
    """Authentication error"""
    pass


class AuthorizationError(Exception):
    """Authorization error"""
    pass


class RateLimitError(Exception):
    """Rate limit exceeded error"""
    pass


# Role-based permission mapping
ROLE_PERMISSIONS = {
    UserRole.SYSTEM_ADMIN: [
        Permission.CALL_START, Permission.CALL_END, Permission.CALL_VIEW, Permission.CALL_MANAGE,
        Permission.HOTEL_CREATE, Permission.HOTEL_UPDATE, Permission.HOTEL_DELETE, Permission.HOTEL_VIEW,
        Permission.SYSTEM_CONFIG, Permission.SYSTEM_MONITOR, Permission.SYSTEM_ADMIN,
        Permission.USER_CREATE, Permission.USER_UPDATE, Permission.USER_DELETE, Permission.USER_VIEW,
    ],
    UserRole.HOTEL_ADMIN: [
        Permission.CALL_START, Permission.CALL_END, Permission.CALL_VIEW, Permission.CALL_MANAGE,
        Permission.HOTEL_UPDATE, Permission.HOTEL_VIEW,
        Permission.USER_VIEW,
    ],
    UserRole.HOTEL_STAFF: [
        Permission.CALL_START, Permission.CALL_VIEW, Permission.HOTEL_VIEW,
    ],
    UserRole.GUEST_USER: [
        Permission.CALL_VIEW,
    ],
}


def get_permissions_for_roles(roles: List[UserRole]) -> List[Permission]:
    """Get all permissions for a list of roles"""
    permissions = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS.get(role, []))
    return list(permissions)