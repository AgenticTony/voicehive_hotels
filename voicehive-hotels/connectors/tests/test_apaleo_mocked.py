"""
Unit tests for Apaleo Connector with simple mocking
"""

import pytest
import pytest_asyncio
from datetime import date, timedelta, datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import json

from connectors.adapters.apaleo.connector import ApaleoConnector
from contracts import (
    NotFoundError,
    RateLimitError,
    AuthenticationError,
    GuestProfile,
    AvailabilityGrid,
    ReservationDraft,
)


class TestApaleoConnectorMocked:
    """Unit tests for Apaleo connector with mocks"""

    @pytest.fixture
    def config(self):
        """Test configuration"""
        return {
            "client_id": "test_client",
            "client_secret": "test_secret",
            "base_url": "https://api.apaleo.com",
            "property_id": "DEMO01",
        }

    @pytest.fixture
    def oauth_response(self):
        """Mock OAuth token response"""
        return {
            "access_token": "test-token-123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read write",
        }

    @pytest.fixture
    def mock_httpx_client(self, oauth_response):
        """Create a mocked httpx client"""
        client = AsyncMock()

        # Mock OAuth token request
        oauth_resp = MagicMock()
        oauth_resp.status_code = 200
        oauth_resp.json.return_value = (
            oauth_response  # json() returns directly, not async
        )
        oauth_resp.raise_for_status = MagicMock()  # raise_for_status is sync
        oauth_resp.content = json.dumps(oauth_response).encode()

        # Default response
        default_resp = MagicMock()
        default_resp.status_code = 200
        default_resp.json.return_value = {"status": "ok"}
        default_resp.raise_for_status = MagicMock()
        default_resp.content = b'{"status": "ok"}'

        # Configure request method for POST auth
        async def mock_post(url, **kwargs):
            if "connect/token" in url:
                return oauth_resp
            return default_resp

        # Configure general request method
        async def mock_request(method, url, **kwargs):
            if "connect/token" in url:
                return oauth_resp
            return default_resp

        client.post = AsyncMock(side_effect=mock_post)
        client.request = AsyncMock(side_effect=mock_request)
        client.aclose = AsyncMock()
        client.headers = {}  # Add mutable headers dict

        return client

    @pytest_asyncio.fixture
    async def connected_connector(self, config, mock_httpx_client):
        """Create a connected connector with mocked client"""
        connector = ApaleoConnector(config)

        # Patch httpx.AsyncClient
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_httpx_client
            await connector.connect()

        yield connector

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_connect_success(self, config, mock_httpx_client):
        """Test successful OAuth connection"""
        connector = ApaleoConnector(config)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_httpx_client
            await connector.connect()

        assert connector._access_token == "test-token-123"
        assert connector._token_expires_at > datetime.now(timezone.utc).timestamp()

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_health_check(self, connected_connector):
        """Test health check"""
        # Mock property response
        property_resp = MagicMock()
        property_resp.status_code = 200
        property_resp.json.return_value = {
            "id": "DEMO01",
            "name": "Demo Hotel",
            "location": {"city": "Berlin", "country": "DE"},
        }
        property_resp.raise_for_status = MagicMock()
        property_resp.content = b'{"id": "DEMO01"}'

        connected_connector._client.request = AsyncMock(return_value=property_resp)

        health = await connected_connector.health_check()

        assert health["status"] == "healthy"
        assert health["vendor"] == "apaleo"
        assert health["property_id"] == "DEMO01"
        assert "timestamp" in health

    @pytest.mark.asyncio
    async def test_get_availability(self, connected_connector):
        """Test getting availability"""
        # Mock unit groups response
        unit_resp = MagicMock()
        unit_resp.status_code = 200
        unit_resp.json.return_value = {
            "unitGroups": [
                {
                    "id": "STD",
                    "code": "STD",
                    "name": "Standard Room",
                    "description": "Comfortable room",
                    "maxPersons": 2,
                    "standardOccupancy": 2,
                }
            ]
        }
        unit_resp.raise_for_status = MagicMock()
        unit_resp.content = b'"unitGroups":[{"id":"STD"}]'

        # Mock availability response
        avail_resp = MagicMock()
        avail_resp.status_code = 200
        avail_resp.json.return_value = {
            "availableUnitItems": [
                {
                    "unitGroup": {"id": "STD"},
                    "grossAmount": {"amount": 100.0, "currency": "EUR"},
                    "availableCount": 5,
                }
            ]
        }
        avail_resp.raise_for_status = MagicMock()
        avail_resp.content = b'"availableUnitItems":[{"unitGroup":{"id":"STD"}}]'

        # Set up mock to return different responses
        responses = [unit_resp, avail_resp]
        connected_connector._client.request = AsyncMock(side_effect=responses)

        availability = await connected_connector.get_availability(
            hotel_id="DEMO01", start=date(2024, 3, 1), end=date(2024, 3, 3)
        )

        # Verify structure
        assert availability.__class__.__name__ == "AvailabilityGrid"
        assert availability.hotel_id == "DEMO01"
        assert len(availability.room_types) == 1
        assert availability.room_types[0].code == "STD"
        assert availability.room_types[0].name == "Standard Room"
        
        # Verify availability data exists for the date range
        assert len(availability.availability) > 0
        # Should have entries for March 1, 2, and 3
        assert date(2024, 3, 1) in availability.availability
        assert date(2024, 3, 2) in availability.availability 
        assert date(2024, 3, 3) in availability.availability
        
        # Verify room counts
        assert availability.availability[date(2024, 3, 1)]["STD"] == 5
        assert availability.availability[date(2024, 3, 2)]["STD"] == 5

    @pytest.mark.asyncio
    async def test_create_reservation(self, connected_connector):
        """Test creating a reservation"""
        # Mock response
        booking_resp = MagicMock()
        booking_resp.status_code = 201
        booking_resp.json.return_value = {
            "id": "RES123",
            "bookingId": "BOOK123",
            "status": "Confirmed",
            "property": {"id": "DEMO01"},
            "primaryGuest": {
                "firstName": "John",
                "lastName": "Doe",
                "email": "john@example.com",
            },
            "arrival": "2024-03-01",
            "departure": "2024-03-03",
            "unitGroup": {"id": "STD"},
            "ratePlan": {"id": "BAR"},
            "totalGrossAmount": {"amount": 220.0, "currency": "EUR"},
        }
        booking_resp.raise_for_status = MagicMock()
        booking_resp.content = b'{"id":"RES123"}'

        connected_connector._client.request = AsyncMock(return_value=booking_resp)

        guest = GuestProfile(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            gdpr_consent=True,
            marketing_consent=False,
        )

        draft = ReservationDraft(
            hotel_id="DEMO01",
            arrival=date(2024, 3, 1),
            departure=date(2024, 3, 3),
            room_type="STD",
            rate_code="BAR",
            guest_count=2,
            guest=guest,
            special_requests="Late check-in",
            payment_method="credit_card",
        )

        reservation = await connected_connector.create_reservation(draft)

        assert reservation.id == "RES123"
        assert reservation.confirmation_number == "BOOK123"
        assert reservation.status == "confirmed"

    @pytest.mark.asyncio
    async def test_cancel_reservation(self, connected_connector):
        """Test cancelling a reservation"""
        # Mock response for PATCH
        cancel_resp = MagicMock()
        cancel_resp.status_code = 204
        cancel_resp.raise_for_status = MagicMock()
        cancel_resp.content = b""

        connected_connector._client.request = AsyncMock(return_value=cancel_resp)

        await connected_connector.cancel_reservation("RES123", "Guest request")

        # Verify PATCH was called with correct data
        connected_connector._client.request.assert_called_with(
            "PATCH",
            "/booking/v1/bookings/RES123",
            json={"status": "Canceled", "cancellationReason": "Guest request"},
        )

    @pytest.mark.asyncio
    async def test_authentication_error(self, config):
        """Test authentication failure"""
        connector = ApaleoConnector(config)

        # Mock 401 response
        auth_error_resp = AsyncMock()
        auth_error_resp.status_code = 401
        auth_error_resp.raise_for_status.side_effect = Exception("401 Unauthorized")

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=auth_error_resp)
        mock_client.aclose = AsyncMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value = mock_client

            with pytest.raises(AuthenticationError):
                await connector.connect()

    @pytest.mark.asyncio
    async def test_not_found_error(self, connected_connector):
        """Test 404 error handling"""
        # Mock 404 response
        not_found_resp = MagicMock()
        not_found_resp.status_code = 404
        not_found_resp.raise_for_status = MagicMock()
        not_found_resp.content = b'{"error":"Not found"}'

        connected_connector._client.request = AsyncMock(return_value=not_found_resp)

        with pytest.raises(NotFoundError):
            await connected_connector.get_reservation("NONEXISTENT")

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, connected_connector):
        """Test rate limit handling"""
        # Mock 429 response
        rate_limit_resp = MagicMock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.headers = {"Retry-After": "60"}
        rate_limit_resp.raise_for_status = MagicMock()
        rate_limit_resp.content = b'{"error":"Rate limit"}'

        connected_connector._client.request = AsyncMock(return_value=rate_limit_resp)

        with pytest.raises(RateLimitError) as exc_info:
            await connected_connector.get_availability(
                hotel_id="DEMO01",
                start=date.today(),
                end=date.today() + timedelta(days=1)
            )
        assert exc_info.value.retry_after == 60
    
    @pytest.mark.asyncio
    async def test_get_availability_empty(self, connected_connector):
        """Test availability with no available units"""
        # Mock unit groups response
        unit_resp = MagicMock()
        unit_resp.status_code = 200
        unit_resp.json.return_value = {
            "unitGroups": [
                {
                    "id": "STD",
                    "code": "STD",
                    "name": "Standard Room",
                    "description": "Sold out room",
                    "maxPersons": 2,
                    "standardOccupancy": 2
                }
            ]
        }
        unit_resp.raise_for_status = MagicMock()
        unit_resp.content = b'{"unitGroups":[{"id":"STD"}]}'
        
        # Mock empty availability response
        avail_resp = MagicMock()
        avail_resp.status_code = 200
        avail_resp.json.return_value = {
            "availableUnitItems": []  # No rooms available
        }
        avail_resp.raise_for_status = MagicMock()
        avail_resp.content = b'{"availableUnitItems":[]}'
        
        # Set up mock to return different responses
        responses = [unit_resp, avail_resp]
        connected_connector._client.request = AsyncMock(side_effect=responses)
        
        availability = await connected_connector.get_availability(
            hotel_id="DEMO01",
            start=date(2024, 3, 1),
            end=date(2024, 3, 3)
        )
        
        assert availability.__class__.__name__ == "AvailabilityGrid"
        assert len(availability.room_types) == 1
        
        # Verify dates exist but with 0 availability
        assert len(availability.availability) == 3  # 3 days
        for check_date in [date(2024, 3, 1), date(2024, 3, 2), date(2024, 3, 3)]:
            assert check_date in availability.availability
            # No STD rooms available (empty dict for that date)
            assert availability.availability[check_date] == {}
    
    @pytest.mark.asyncio
    async def test_availability_rate_limit_retry(self, connected_connector):
        """Test that rate limits during availability fetch are handled"""
        # First mock unit groups response
        unit_resp = MagicMock()
        unit_resp.status_code = 200
        unit_resp.json.return_value = {
            "unitGroups": [{"id": "STD", "name": "Standard", "maxPersons": 2}]
        }
        unit_resp.raise_for_status = MagicMock()
        unit_resp.content = b'{}'
        
        # Mock rate limit response for availability
        rate_limit_resp = MagicMock()
        rate_limit_resp.status_code = 429
        rate_limit_resp.headers = {"Retry-After": "1"}  # 1 second retry
        rate_limit_resp.raise_for_status = MagicMock()
        rate_limit_resp.content = b''
        
        # Set up responses: unit groups OK, then rate limit on availability
        responses = [unit_resp, rate_limit_resp]
        connected_connector._client.request = AsyncMock(side_effect=responses)
        
        # Should raise RateLimitError (no automatic retry in get_availability)
        with pytest.raises(RateLimitError) as exc_info:
            await connected_connector.get_availability(
                hotel_id="DEMO01",
                start=date(2024, 3, 1),
                end=date(2024, 3, 2)
            )
        
        assert exc_info.value.retry_after == 1
