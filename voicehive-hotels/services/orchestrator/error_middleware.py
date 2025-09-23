"""
Error Middleware for VoiceHive Hotels
Handles exceptions and provides standardized error responses
"""

import traceback
from typing import Dict, Any, Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from pydantic import ValidationError

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.error_middleware")


class ComprehensiveErrorMiddleware(BaseHTTPMiddleware):
    """Comprehensive error handling middleware"""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        """Handle all exceptions and provide standardized responses"""
        
        try:
            response = await call_next(request)
            return response
            
        except Exception as e:
            return await self._handle_exception(request, e)
    
    async def _handle_exception(self, request: Request, exc: Exception) -> JSONResponse:
        """Handle different types of exceptions"""
        
        # Get correlation ID for tracking
        correlation_id = request.headers.get("X-Correlation-ID", "unknown")
        
        # Log the error
        logger.error(
            "request_exception",
            path=request.url.path,
            method=request.method,
            correlation_id=correlation_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback=traceback.format_exc()
        )
        
        # Handle specific exception types
        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": {
                        "code": "HTTP_ERROR",
                        "message": exc.detail,
                        "correlation_id": correlation_id
                    }
                }
            )
        
        elif isinstance(exc, ValidationError):
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Input validation failed",
                        "details": exc.errors(),
                        "correlation_id": correlation_id
                    }
                }
            )
        
        else:
            # Generic server error
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An internal server error occurred",
                        "correlation_id": correlation_id
                    }
                }
            )


# Exception handlers for FastAPI
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors"""
    correlation_id = request.headers.get("X-Correlation-ID", "unknown")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Input validation failed",
                "details": exc.errors(),
                "correlation_id": correlation_id
            }
        }
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    correlation_id = request.headers.get("X-Correlation-ID", "unknown")
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": exc.detail,
                "correlation_id": correlation_id
            }
        }
    )


async def generic_exception_handler(request: Request, exc: Exception):
    """Handle generic exceptions"""
    correlation_id = request.headers.get("X-Correlation-ID", "unknown")
    
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        correlation_id=correlation_id,
        error_type=type(exc).__name__,
        error_message=str(exc),
        traceback=traceback.format_exc()
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An internal server error occurred",
                "correlation_id": correlation_id
            }
        }
    )