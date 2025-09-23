"""
Authentication and Authorization module for VoiceHive Hotels Orchestrator

This module provides JWT authentication, API key validation, role-based access control,
and integration with HashiCorp Vault for secure credential management.
"""

from .middleware import AuthenticationMiddleware
from .models import UserContext, ServiceContext, JWTPayload
from .jwt_service import JWTService
from .vault_client import VaultClient, MockVaultClient

__all__ = [
    # Middleware
    "AuthenticationMiddleware",
    
    # Models
    "UserContext",
    "ServiceContext", 
    "JWTPayload",
    
    # Services
    "JWTService",
    "VaultClient",
    "MockVaultClient",
]