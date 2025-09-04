"""
Shared test fixtures for connector tests
Uses pytest-httpx for mocking HTTP calls
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from typing import Dict, Any
import httpx
from pytest_httpx import HTTPXMock


@pytest.fixture
def oauth_token_response() -> Dict[str, Any]:
    """Standard OAuth token response"""
    return {
        "access_token": "test-token-123",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "read write",
    }


@pytest.fixture
def apaleo_property_response() -> Dict[str, Any]:
    """Mock Apaleo property details for health checks"""
    return {
        "id": "DEMO01",
        "name": "Demo Hotel",
        "location": {"city": "Berlin", "country": "DE"},
    }


@pytest.fixture
def apaleo_unit_groups_response() -> Dict[str, Any]:
    """Mock Apaleo unit groups (room types)"""
    return {
        "unitGroups": [
            {
                "id": "STD",
                "code": "STD",
                "name": "Standard Room",
                "description": "Comfortable standard room",
                "maxPersons": 2,
                "standardOccupancy": 2,
                "property": {"id": "DEMO01"},
            },
            {
                "id": "DLX",
                "code": "DLX",
                "name": "Deluxe Room",
                "description": "Spacious deluxe room",
                "maxPersons": 4,
                "standardOccupancy": 2,
                "property": {"id": "DEMO01"},
            },
        ]
    }


@pytest.fixture
def apaleo_booking_response() -> Dict[str, Any]:
    """Mock Apaleo booking/reservation"""
    return {
        "id": "RES123",
        "bookingId": "BOOK123",  # Note: some responses use bookingId
        "bookingNumber": "BOOK123",  # Others use bookingNumber
        "status": "Confirmed",
        "property": {"id": "DEMO01"},
        "primaryGuest": {
            "firstName": "John",
            "lastName": "Doe",
            "email": "john@example.com",
            "phone": "+1234567890",
        },
        "arrival": "2024-03-01",
        "departure": "2024-03-03",
        "adults": 2,
        "unitGroup": {"id": "STD", "code": "STD"},
        "ratePlan": {"id": "BAR", "code": "BAR"},
        "totalGrossAmount": {"amount": 220.00, "currency": "EUR"},
        "created": "2024-01-01T10:00:00Z",
        "modified": "2024-01-01T10:00:00Z",
    }


@pytest.fixture
def mock_apaleo_auth(httpx_mock: HTTPXMock, oauth_token_response: Dict[str, Any]):
    """Mock Apaleo OAuth authentication"""
    httpx_mock.add_response(
        method="POST",
        url="https://identity.apaleo.com/connect/token",
        json=oauth_token_response,
        status_code=200,
    )


@pytest.fixture
def mock_apaleo_health_check(
    httpx_mock: HTTPXMock, apaleo_property_response: Dict[str, Any]
):
    """Mock Apaleo health check endpoint"""
    httpx_mock.add_response(
        method="GET",
        url="https://api.apaleo.com/properties/v1/properties/DEMO01",
        json=apaleo_property_response,
        status_code=200,
    )


@pytest.fixture
def mock_apaleo_availability(
    httpx_mock: HTTPXMock, apaleo_unit_groups_response: Dict[str, Any]
):
    """Mock Apaleo availability endpoints"""
    # Mock unit groups endpoint
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.apaleo.com/inventory/v1/unit-groups",
            params={"propertyId": "DEMO01"},
        ),
        json=apaleo_unit_groups_response,
        status_code=200,
    )

    # Mock availability data
    availability_response = {
        "availableUnitItems": [
            {
                "unitGroup": {"id": "STD"},
                "grossAmount": {"amount": 100.00, "currency": "EUR"},
                "availableCount": 5,
            },
            {
                "unitGroup": {"id": "DLX"},
                "grossAmount": {"amount": 150.00, "currency": "EUR"},
                "availableCount": 2,
            },
        ]
    }

    httpx_mock.add_response(
        method="GET",
        url=httpx.URL("https://api.apaleo.com/availability/v1/availability"),
        match_content=None,  # Match any params
        json=availability_response,
        status_code=200,
    )


@pytest.fixture
def mock_apaleo_rates(httpx_mock: HTTPXMock):
    """Mock Apaleo rates endpoint"""
    rates_response = {
        "rates": [
            {
                "date": "2024-03-01",
                "amount": {"grossAmount": 110.00, "taxes": {"amount": 10.00}},
            },
            {
                "date": "2024-03-02",
                "amount": {"grossAmount": 110.00, "taxes": {"amount": 10.00}},
            },
        ]
    }

    httpx_mock.add_response(
        method="GET",
        url=httpx.URL("https://api.apaleo.com/rates/v1/rates"),
        match_content=None,
        json=rates_response,
        status_code=200,
    )


@pytest.fixture
def mock_apaleo_create_booking(
    httpx_mock: HTTPXMock, apaleo_booking_response: Dict[str, Any]
):
    """Mock Apaleo booking creation"""
    httpx_mock.add_response(
        method="POST",
        url="https://api.apaleo.com/booking/v1/bookings",
        json=apaleo_booking_response,
        status_code=201,
    )


@pytest.fixture
def mock_apaleo_get_booking(
    httpx_mock: HTTPXMock, apaleo_booking_response: Dict[str, Any]
):
    """Mock Apaleo get booking by ID"""
    httpx_mock.add_response(
        method="GET",
        url="https://api.apaleo.com/booking/v1/bookings/RES123",
        json=apaleo_booking_response,
        status_code=200,
    )


@pytest.fixture
def mock_apaleo_cancel_booking(httpx_mock: HTTPXMock):
    """Mock Apaleo booking cancellation (PATCH, not DELETE)"""
    httpx_mock.add_response(
        method="PATCH",
        url="https://api.apaleo.com/booking/v1/bookings/RES123",
        match_json={"status": "Canceled", "cancellationReason": "Guest request"},
        status_code=204,
    )


@pytest.fixture
def mock_apaleo_guest_search(httpx_mock: HTTPXMock):
    """Mock Apaleo guest search"""
    # Search by email returns results
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.apaleo.com/booking/v1/guests",
            params={"email": "john@example.com"},
        ),
        json={
            "guests": [
                {
                    "id": "GUEST123",
                    "firstName": "John",
                    "lastName": "Doe",
                    "email": "john@example.com",
                }
            ]
        },
        status_code=200,
    )

    # Text search by name
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            "https://api.apaleo.com/booking/v1/guests",
            params={"textSearch": "John Doe"},
        ),
        json={"guests": []},
        status_code=200,
    )


@pytest.fixture
def mock_apaleo_error_responses(httpx_mock: HTTPXMock):
    """Mock various error scenarios"""
    # 401 Unauthorized
    httpx_mock.add_response(
        method="POST",
        url="https://identity.apaleo.com/connect/token",
        match_content=b"invalid_client",
        status_code=401,
        text="Invalid client credentials",
    )

    # 404 Not Found
    httpx_mock.add_response(
        method="GET",
        url="https://api.apaleo.com/booking/v1/bookings/NONEXISTENT",
        status_code=404,
        json={"error": "Booking not found"},
    )

    # 422 Validation Error
    httpx_mock.add_response(
        method="POST",
        url="https://api.apaleo.com/booking/v1/bookings",
        match_content=b"invalid_dates",
        status_code=422,
        json={
            "errors": [
                {"field": "arrival", "message": "Arrival must be before departure"}
            ]
        },
    )

    # 429 Rate Limit
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL("https://api.apaleo.com/", path="/.*rate-limit.*/"),
        status_code=429,
        headers={"Retry-After": "60"},
    )


@pytest.fixture
def authenticated_apaleo_connector(mock_apaleo_auth):
    """Create an Apaleo connector with mocked auth and stable token"""
    from connectors.adapters.apaleo.connector import ApaleoConnector

    config = {
        "client_id": "test_client",
        "client_secret": "test_secret",
        "base_url": "https://api.apaleo.com",
        "property_id": "DEMO01",
    }

    connector = ApaleoConnector(config)

    # Pre-set stable token to avoid authentication in tests
    connector._access_token = "test-token-123"
    connector._token_expires_at = datetime.now(timezone.utc).timestamp() + 3600

    return connector


@pytest_asyncio.fixture
async def connected_apaleo(authenticated_apaleo_connector, httpx_mock: HTTPXMock):
    """Async fixture that provides a connected Apaleo instance"""
    connector = authenticated_apaleo_connector
    await connector.connect()

    yield connector

    await connector.disconnect()
