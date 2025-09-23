"""
Integration test for error handling system with FastAPI
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from error_middleware import (
    ComprehensiveErrorMiddleware,
    validation_exception_handler,
    http_exception_handler,
    generic_exception_handler
)
from correlation_middleware import CorrelationIDMiddleware
from error_models import ValidationError, AuthenticationError


# Create test app
app = FastAPI()

# Add middlewares
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(ComprehensiveErrorMiddleware)

# Register exception handlers
app.add_exception_handler(PydanticValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


@app.get("/test-auth-error")
def test_auth_error():
    """Test endpoint that raises authentication error"""
    raise AuthenticationError("Invalid token provided")


@app.get("/test-validation-error")
def test_validation_error():
    """Test endpoint that raises validation error"""
    raise ValidationError("Invalid input format", field="email")


@app.get("/test-http-error")
def test_http_error():
    """Test endpoint that raises HTTP error"""
    raise HTTPException(status_code=404, detail="Resource not found")


@app.get("/test-generic-error")
def test_generic_error():
    """Test endpoint that raises generic error"""
    raise ValueError("Something went wrong")


def test_authentication_error_handling():
    """Test authentication error handling"""
    client = TestClient(app)
    
    response = client.get("/test-auth-error")
    
    assert response.status_code == 401
    data = response.json()
    
    assert data["error"]["code"] == "AUTHENTICATION_FAILED"
    assert data["error"]["message"] == "Invalid token provided"
    assert data["error"]["category"] == "authentication"
    assert data["error"]["severity"] == "high"
    assert "correlation_id" in data["error"]
    assert data["path"] == "/test-auth-error"
    assert data["method"] == "GET"


def test_validation_error_handling():
    """Test validation error handling"""
    client = TestClient(app)
    
    response = client.get("/test-validation-error")
    
    assert response.status_code == 400
    data = response.json()
    
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert data["error"]["message"] == "Invalid input format"
    assert data["error"]["category"] == "validation"
    assert data["error"]["severity"] == "low"
    assert data["error"]["details"]["field"] == "email"


def test_http_error_handling():
    """Test HTTP error handling"""
    client = TestClient(app)
    
    response = client.get("/test-http-error")
    
    assert response.status_code == 404
    data = response.json()
    
    assert data["error"]["code"] == "NOT_FOUND"
    assert data["error"]["message"] == "Resource not found"


def test_generic_error_handling():
    """Test generic error handling"""
    client = TestClient(app)
    
    response = client.get("/test-generic-error")
    
    assert response.status_code == 400
    data = response.json()
    
    assert data["error"]["code"] == "INVALID_VALUE"
    assert "Something went wrong" in data["error"]["message"]


def test_correlation_id_propagation():
    """Test correlation ID propagation"""
    client = TestClient(app)
    
    # Send request with correlation ID
    correlation_id = "test-correlation-123"
    response = client.get(
        "/test-auth-error",
        headers={"X-Correlation-ID": correlation_id}
    )
    
    assert response.status_code == 401
    data = response.json()
    
    # Check correlation ID is preserved
    assert data["error"]["correlation_id"] == correlation_id
    assert data["request_id"] == correlation_id
    
    # Check response header
    assert response.headers["X-Correlation-ID"] == correlation_id


if __name__ == "__main__":
    pytest.main([__file__])