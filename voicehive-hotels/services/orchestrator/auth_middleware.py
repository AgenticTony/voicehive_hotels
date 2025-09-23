"""
Authentication and Authorization middleware for VoiceHive Hotels Orchestrator
"""

import re
from datetime import datetime
from typing import Optional, Union, List
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from auth_models import (
    UserContext, ServiceContext, AuthenticationError, 
    AuthorizationError, Permission
)
from jwt_service import JWTService
from vault_client import VaultClient
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.auth_middleware")

# Security scheme for FastAPI docs
security = HTTPBearer(auto_error=False)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """JWT and API Key authentication middleware"""
    
    def __init__(self, app, jwt_service: JWTService, vault_client: VaultClient):
        super().__init__(app)
        self.jwt_service = jwt_service
        self.vault_client = vault_client
        
        # Paths that don't require authentication
        self.public_paths = [
            "/",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/healthz",
            "/metrics",
            "/auth/login",
            "/auth/refresh"
        ]
        
        # Paths that require specific permissions
        self.protected_paths = {
            r"/calls/.*": [Permission.CALL_START, Permission.CALL_VIEW],
            r"/hotels/.*": [Permission.HOTEL_VIEW],
            r"/admin/.*": [Permission.SYSTEM_ADMIN],
            r"/auth/api-keys.*": [Permission.SYSTEM_ADMIN],
        }
    
    async def dispatch(self, request: Request, call_next):
        """Process authentication for each request"""
        
        # Skip authentication for public paths
        if self._is_public_path(request.url.path):
            return await call_next(request)
        
        try:
            # Extract and validate authentication
            auth_context = await self._authenticate_request(request)
            
            # Add auth context to request state
            request.state.auth_context = auth_context
            
            # Check authorization for protected paths
            await self._authorize_request(request, auth_context)
            
            # Process request
            response = await call_next(request)
            
            # Add security headers
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            
            return response
            
        except AuthenticationError as e:
            logger.warning(
                "authentication_failed",
                path=request.url.path,
                method=request.method,
                error=str(e),
                user_agent=request.headers.get("User-Agent", "unknown")
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "AUTHENTICATION_ERROR",
                        "message": str(e),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                }
            )
        
        except AuthorizationError as e:
            logger.warning(
                "authorization_failed",
                path=request.url.path,
                method=request.method,
                error=str(e),
                user_id=getattr(request.state, 'auth_context', {}).get('user_id', 'unknown')
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "AUTHORIZATION_ERROR",
                        "message": str(e),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                }
            )
        
        except Exception as e:
            logger.error(
                "auth_middleware_error",
                path=request.url.path,
                method=request.method,
                error=str(e)
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Authentication service error",
                        "timestamp": datetime.utcnow().isoformat()
                    }
                }
            )
    
    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (doesn't require authentication)"""
        return any(path.startswith(public_path) for public_path in self.public_paths)
    
    async def _authenticate_request(self, request: Request) -> Union[UserContext, ServiceContext]:
        """Authenticate request using JWT or API key"""
        
        # Try Authorization header first
        auth_header = request.headers.get("Authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]  # Remove "Bearer " prefix
                return await self._authenticate_jwt(token)
            elif auth_header.startswith("ApiKey "):
                api_key = auth_header[7:]  # Remove "ApiKey " prefix
                return await self._authenticate_api_key(api_key)
        
        # Try X-API-Key header
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return await self._authenticate_api_key(api_key)
        
        raise AuthenticationError("No valid authentication provided")
    
    async def _authenticate_jwt(self, token: str) -> UserContext:
        """Authenticate using JWT token"""
        try:
            return await self.jwt_service.validate_token(token)
        except Exception as e:
            raise AuthenticationError(f"JWT validation failed: {str(e)}")
    
    async def _authenticate_api_key(self, api_key: str) -> ServiceContext:
        """Authenticate using API key"""
        try:
            return await self.vault_client.validate_api_key(api_key)
        except Exception as e:
            raise AuthenticationError(f"API key validation failed: {str(e)}")
    
    async def _authorize_request(self, request: Request, auth_context: Union[UserContext, ServiceContext]):
        """Check if authenticated user/service has permission for the request"""
        
        path = request.url.path
        method = request.method
        
        # Check path-based permissions
        required_permissions = self._get_required_permissions(path)
        if required_permissions:
            user_permissions = auth_context.permissions
            
            # Check if user has any of the required permissions
            if not any(perm in user_permissions for perm in required_permissions):
                raise AuthorizationError(
                    f"Insufficient permissions for {method} {path}. "
                    f"Required: {[p.value for p in required_permissions]}"
                )
        
        # Additional authorization checks based on context
        if isinstance(auth_context, UserContext):
            await self._authorize_user_request(request, auth_context)
        elif isinstance(auth_context, ServiceContext):
            await self._authorize_service_request(request, auth_context)
    
    def _get_required_permissions(self, path: str) -> List[Permission]:
        """Get required permissions for a path"""
        for pattern, permissions in self.protected_paths.items():
            if re.match(pattern, path):
                return permissions
        return []
    
    async def _authorize_user_request(self, request: Request, user_context: UserContext):
        """Additional authorization checks for user requests"""
        
        # Hotel-specific authorization
        if "/hotels/" in request.url.path and user_context.hotel_ids:
            # Extract hotel_id from path or query params
            hotel_id = self._extract_hotel_id(request)
            if hotel_id and hotel_id not in user_context.hotel_ids:
                raise AuthorizationError(f"Access denied to hotel {hotel_id}")
    
    async def _authorize_service_request(self, request: Request, service_context: ServiceContext):
        """Additional authorization checks for service requests"""
        
        # Service-specific rate limiting and restrictions can be added here
        pass
    
    def _extract_hotel_id(self, request: Request) -> Optional[str]:
        """Extract hotel ID from request path or parameters"""
        
        # Try to extract from path like /hotels/{hotel_id}/...
        path_parts = request.url.path.split('/')
        if len(path_parts) >= 3 and path_parts[1] == "hotels":
            return path_parts[2]
        
        # Try to extract from query parameters
        return request.query_params.get("hotel_id")


# Dependency functions for FastAPI route protection
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None
) -> UserContext:
    """FastAPI dependency to get current authenticated user"""
    
    if hasattr(request.state, 'auth_context'):
        auth_context = request.state.auth_context
        if isinstance(auth_context, UserContext):
            return auth_context
    
    raise HTTPException(
        status_code=401,
        detail="User authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_service(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    request: Request = None
) -> ServiceContext:
    """FastAPI dependency to get current authenticated service"""
    
    if hasattr(request.state, 'auth_context'):
        auth_context = request.state.auth_context
        if isinstance(auth_context, ServiceContext):
            return auth_context
    
    raise HTTPException(
        status_code=401,
        detail="Service authentication required",
        headers={"WWW-Authenticate": "ApiKey"},
    )


async def get_auth_context(
    request: Request = None
) -> Union[UserContext, ServiceContext]:
    """FastAPI dependency to get current authentication context"""
    
    if hasattr(request.state, 'auth_context'):
        return request.state.auth_context
    
    raise HTTPException(
        status_code=401,
        detail="Authentication required"
    )


def require_permissions(*required_perms: Permission):
    """Decorator to require specific permissions for a route"""
    
    def permission_checker(auth_context: Union[UserContext, ServiceContext] = Depends(get_auth_context)):
        user_permissions = auth_context.permissions
        
        if not any(perm in user_permissions for perm in required_perms):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required: {[p.value for p in required_perms]}"
            )
        
        return auth_context
    
    return permission_checker


def require_roles(*required_roles: str):
    """Decorator to require specific roles for a route (user authentication only)"""
    
    def role_checker(user_context: UserContext = Depends(get_current_user)):
        user_roles = [role.value for role in user_context.roles]
        
        if not any(role in user_roles for role in required_roles):
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient roles. Required: {required_roles}"
            )
        
        return user_context
    
    return role_checker