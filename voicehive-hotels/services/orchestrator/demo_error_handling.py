"""
Demonstration of the comprehensive error handling system
"""

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from error_middleware import ComprehensiveErrorMiddleware
from correlation_middleware import CorrelationIDMiddleware
from error_models import (
    AuthenticationError, ValidationError, ExternalServiceError,
    PMSConnectorError, DatabaseError
)

# Create demo app
app = FastAPI(title="Error Handling Demo")

# Add middlewares
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(ComprehensiveErrorMiddleware)

# Register exception handlers
from error_middleware import http_exception_handler, generic_exception_handler
from pydantic import ValidationError as PydanticValidationError

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


@app.get("/demo/auth-error")
def demo_auth_error():
    """Demo authentication error"""
    raise AuthenticationError(
        "JWT token has expired",
        details={"token_type": "Bearer", "expiry": "2023-12-01T10:00:00Z"}
    )


@app.get("/demo/validation-error")
def demo_validation_error():
    """Demo validation error"""
    raise ValidationError(
        "Email format is invalid",
        field="email",
        details={"provided_value": "invalid-email", "expected_format": "user@domain.com"}
    )


@app.get("/demo/pms-error")
def demo_pms_error():
    """Demo PMS connector error"""
    raise PMSConnectorError(
        connector="apaleo",
        message="Failed to retrieve guest information",
        details={"hotel_id": "hotel_123", "room_number": "101", "error_code": "GUEST_NOT_FOUND"}
    )


@app.get("/demo/database-error")
def demo_database_error():
    """Demo database error"""
    raise DatabaseError(
        "Connection timeout to primary database",
        operation="select_guest_preferences",
        details={"timeout_seconds": 30, "retry_count": 3}
    )


@app.get("/demo/external-service-error")
def demo_external_service_error():
    """Demo external service error"""
    raise ExternalServiceError(
        service="elevenlabs_tts",
        message="Rate limit exceeded",
        status_code=429,
        details={"limit": "1000/hour", "reset_time": "2023-12-01T11:00:00Z"}
    )


@app.get("/demo/http-error")
def demo_http_error():
    """Demo HTTP error"""
    raise HTTPException(status_code=404, detail="Hotel configuration not found")


@app.get("/demo/generic-error")
def demo_generic_error():
    """Demo generic error"""
    raise ValueError("Invalid configuration parameter")


def demonstrate_error_handling():
    """Demonstrate the error handling system"""
    client = TestClient(app)
    
    print("🚨 VoiceHive Hotels - Error Handling System Demo\n")
    
    test_cases = [
        ("/demo/auth-error", "Authentication Error"),
        ("/demo/validation-error", "Validation Error"),
        ("/demo/pms-error", "PMS Connector Error"),
        ("/demo/database-error", "Database Error"),
        ("/demo/external-service-error", "External Service Error"),
        ("/demo/http-error", "HTTP Error"),
        ("/demo/generic-error", "Generic Error")
    ]
    
    for endpoint, description in test_cases:
        print(f"📍 Testing: {description}")
        print(f"   Endpoint: {endpoint}")
        
        # Test without correlation ID
        response = client.get(endpoint)
        data = response.json()
        
        print(f"   Status: {response.status_code}")
        print(f"   Error Code: {data['error']['code']}")
        print(f"   Message: {data['error']['message']}")
        print(f"   Category: {data['error']['category']}")
        print(f"   Severity: {data['error']['severity']}")
        print(f"   Correlation ID: {data['error']['correlation_id']}")
        
        if data['error'].get('details'):
            print(f"   Details: {data['error']['details']}")
        
        if response.headers.get('X-Correlation-ID'):
            print(f"   Response Header: X-Correlation-ID = {response.headers['X-Correlation-ID']}")
        
        print()
    
    # Test with custom correlation ID
    print("🔗 Testing Correlation ID Propagation")
    custom_correlation_id = "demo-correlation-12345"
    response = client.get(
        "/demo/auth-error",
        headers={"X-Correlation-ID": custom_correlation_id}
    )
    data = response.json()
    
    print(f"   Sent Correlation ID: {custom_correlation_id}")
    print(f"   Received Correlation ID: {data['error']['correlation_id']}")
    print(f"   Response Header: {response.headers.get('X-Correlation-ID')}")
    print(f"   ✅ Correlation ID preserved: {data['error']['correlation_id'] == custom_correlation_id}")
    print()
    
    print("✅ Error Handling System Demo Complete!")
    print("\nKey Features Demonstrated:")
    print("• Standardized error response format")
    print("• Correlation ID tracking for distributed tracing")
    print("• Structured logging with context")
    print("• Error categorization and severity levels")
    print("• Detailed error information for debugging")
    print("• HTTP status code mapping")
    print("• Response header management")


if __name__ == "__main__":
    demonstrate_error_handling()