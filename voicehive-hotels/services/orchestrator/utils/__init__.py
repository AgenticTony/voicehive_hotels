"""
Utilities module for VoiceHive Hotels Orchestrator

This module provides shared utility functions and classes including logging,
correlation handling, error handling, and external service clients.
"""

from .logging_adapter import get_safe_logger, LoggingAdapter
from .correlation import CorrelationMiddleware
from .error_handler import ErrorHandler, StandardErrorResponse
from .tts_client import TTSClient, EnhancedTTSClient

__all__ = [
    # Logging
    "get_safe_logger",
    "LoggingAdapter",
    
    # Request Correlation
    "CorrelationMiddleware",
    
    # Error Handling
    "ErrorHandler",
    "StandardErrorResponse",
    
    # External Services
    "TTSClient",
    "EnhancedTTSClient",
]