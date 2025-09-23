"""
Core exceptions for VoiceHive Hotels Orchestrator

This module defines the core exception hierarchy used throughout the application.
"""

from typing import Optional, Dict, Any


class OrchestratorError(Exception):
    """Base exception for all orchestrator-related errors"""
    
    def __init__(self, message: str, error_code: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}


class ConfigurationError(OrchestratorError):
    """Configuration-related errors"""
    pass


class AuthenticationError(OrchestratorError):
    """Authentication-related errors"""
    pass


class AuthorizationError(OrchestratorError):
    """Authorization-related errors"""
    pass


class ValidationError(OrchestratorError):
    """Input validation errors"""
    pass


class RateLimitError(OrchestratorError):
    """Rate limiting errors"""
    pass


class CircuitBreakerOpenError(OrchestratorError):
    """Circuit breaker open errors"""
    pass


class ExternalServiceError(OrchestratorError):
    """External service communication errors"""
    pass


class DatabaseError(OrchestratorError):
    """Database-related errors"""
    pass


class CacheError(OrchestratorError):
    """Cache-related errors"""
    pass


class ComplianceError(OrchestratorError):
    """Compliance-related errors"""
    pass


class SecurityError(OrchestratorError):
    """Security-related errors"""
    pass