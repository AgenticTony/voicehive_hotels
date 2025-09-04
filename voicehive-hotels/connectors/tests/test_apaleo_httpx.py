"""
Unit tests for Apaleo Connector with HTTPX mocking
"""

import pytest
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
from pytest_httpx import HTTPXMock

from connectors.adapters.apaleo.connector import ApaleoConnector
from contracts import (
    NotFoundError,
    ValidationError,
    RateLimitError,
    AuthenticationError,
    GuestProfile,
    AvailabilityGrid,
    RateQuote,
    Reservation,
    ReservationDraft,
)

# Import shared fixtures


class TestApaleoConnectorWithHTTPX:
    """Unit tests for Apaleo connector using pytest-httpx"""

    @pytest.fixture
    def config(self):
        """Test configuration matching fixtures"""
        return {
            "client_id": "test_client",
            "client_secret": "test_secret",
            "base_url": "https://api.apaleo.com",
            "property_id": "DEMO01",
        }

    @pytest.mark.asyncio
    async def test_connect_and_authenticate(self, config, mock_apaleo_auth):
        """Test OAuth authentication flow"""
        connector = ApaleoConnector(config)
        await connector.connect()

        assert connector._access_token == "test-token-123"
        assert connector._token_expires_at > datetime.now(timezone.utc).timestamp()

        await connector.disconnect()

    @pytest.mark.asyncio
    async def test_health_check_success(
        self, connected_apaleo, mock_apaleo_health_check
    ):
        """Test health check with mocked property endpoint"""
        health = await connected_apaleo.health_check()

        assert health["status"] == "healthy"
        assert health["vendor"] == "apaleo"
        assert health["property_accessible"] is True
        assert health["token_valid"] is True

    @pytest.mark.asyncio
    async def test_get_availability(self, connected_apaleo, mock_apaleo_availability):
        """Test availability retrieval with mocked responses"""
        availability = await connected_apaleo.get_availability(
            hotel_id="DEMO01", start=date(2024, 3, 1), end=date(2024, 3, 3)
        )

        assert isinstance(availability, AvailabilityGrid)
        assert availability.hotel_id == "DEMO01"
        assert len(availability.room_types) == 2

        # Check room types
        std_room = next(rt for rt in availability.room_types if rt.code == "STD")
        assert std_room.name == "Standard Room"
        assert std_room.max_occupancy == 2

        dlx_room = next(rt for rt in availability.room_types if rt.code == "DLX")
        assert dlx_room.name == "Deluxe Room"
        assert dlx_room.max_occupancy == 4

    @pytest.mark.asyncio
    async def test_quote_rate(self, connected_apaleo, mock_apaleo_rates):
        """Test rate quotation with mocked response"""
        quote = await connected_apaleo.quote_rate(
            hotel_id="DEMO01",
            room_type="STD",
            rate_code="BAR",
            arrival=date(2024, 3, 1),
            departure=date(2024, 3, 3),
            guest_count=2,
            currency="EUR",
        )

        assert isinstance(quote, RateQuote)
        assert quote.room_type == "STD"
        assert quote.currency == "EUR"
        assert quote.total_amount == Decimal("220.00")  # 2 nights * 110
        assert quote.taxes == Decimal("20.00")  # 2 nights * 10

    @pytest.mark.asyncio
    async def test_create_reservation(
        self, connected_apaleo, mock_apaleo_create_booking
    ):
        """Test reservation creation with mocked response"""
        guest = GuestProfile(
            id=None,
            email="john@example.com",
            phone="+1234567890",
            first_name="John",
            last_name="Doe",
            nationality="US",
            language="en",
            vip_status=None,
            preferences={},
            gdpr_consent=True,
            marketing_consent=True,
        )

        draft = ReservationDraft(
            hotel_id="DEMO01",
            arrival=date(2024, 3, 1),
            departure=date(2024, 3, 3),
            room_type="STD",
            rate_code="BAR",
            guest_count=2,
            guest=guest,
            special_requests="Late check-in please",
            payment_method="credit_card",
        )

        reservation = await connected_apaleo.create_reservation(draft)

        assert isinstance(reservation, Reservation)
        assert reservation.confirmation_number == "BOOK123"
        assert reservation.status == "confirmed"
        assert reservation.guest.email == "john@example.com"

    @pytest.mark.asyncio
    async def test_get_reservation(self, connected_apaleo, mock_apaleo_get_booking):
        """Test fetching reservation by ID"""
        reservation = await connected_apaleo.get_reservation("RES123")

        assert isinstance(reservation, Reservation)
        assert reservation.id == "RES123"
        assert reservation.confirmation_number == "BOOK123"
        assert reservation.status == "confirmed"

    @pytest.mark.asyncio
    async def test_cancel_reservation(
        self, connected_apaleo, mock_apaleo_cancel_booking
    ):
        """Test reservation cancellation with PATCH"""
        await connected_apaleo.cancel_reservation("RES123", "Guest request")
        # Should complete without error

    @pytest.mark.asyncio
    async def test_search_guest_by_email(
        self, connected_apaleo, mock_apaleo_guest_search
    ):
        """Test guest search by email"""
        guests = await connected_apaleo.search_guest(email="john@example.com")

        assert isinstance(guests, list)
        assert len(guests) == 1
        assert guests[0].email == "john@example.com"
        assert guests[0].first_name == "John"

    @pytest.mark.asyncio
    async def test_search_guest_by_name(
        self, connected_apaleo, mock_apaleo_guest_search
    ):
        """Test guest search by name returns empty"""
        guests = await connected_apaleo.search_guest(last_name="Doe")

        assert isinstance(guests, list)
        assert len(guests) == 0  # Mock returns empty for name search

    @pytest.mark.asyncio
    async def test_authentication_error(self, config, httpx_mock: HTTPXMock):
        """Test handling of authentication failure"""
        # Mock 401 response
        httpx_mock.add_response(
            method="POST",
            url="https://identity.apaleo.com/connect/token",
            status_code=401,
            json={"error": "invalid_client"},
        )

        connector = ApaleoConnector(config)

        with pytest.raises(AuthenticationError):
            await connector.connect()

    @pytest.mark.asyncio
    async def test_not_found_error(self, connected_apaleo, httpx_mock: HTTPXMock):
        """Test 404 error handling"""
        httpx_mock.add_response(
            method="GET",
            url="https://api.apaleo.com/booking/v1/bookings/NONEXISTENT",
            status_code=404,
            json={"error": "Booking not found"},
        )

        with pytest.raises(NotFoundError):
            await connected_apaleo.get_reservation("NONEXISTENT")

    @pytest.mark.asyncio
    async def test_validation_error(self, connected_apaleo, httpx_mock: HTTPXMock):
        """Test 422 validation error"""
        httpx_mock.add_response(
            method="POST",
            url="https://api.apaleo.com/booking/v1/bookings",
            status_code=422,
            json={"errors": [{"field": "arrival", "message": "Invalid date"}]},
        )

        draft = ReservationDraft(
            hotel_id="DEMO01",
            arrival=date(2024, 3, 3),  # After departure
            departure=date(2024, 3, 1),
            room_type="STD",
            rate_code="BAR",
            guest_count=2,
            guest=GuestProfile(
                first_name="Test",
                last_name="User",
                email="test@example.com",
                gdpr_consent=True,
                marketing_consent=False,
            ),
            special_requests=None,
            payment_method=None,
        )

        with pytest.raises(ValidationError) as exc_info:
            await connected_apaleo.create_reservation(draft)
        assert "arrival" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rate_limit_handling(self, connected_apaleo, httpx_mock: HTTPXMock):
        """Test 429 rate limit error"""
        httpx_mock.add_response(
            method="GET",
            url="https://api.apaleo.com/availability/v1/availability",
            status_code=429,
            headers={"Retry-After": "60"},
        )

        with pytest.raises(RateLimitError) as exc_info:
            await connected_apaleo.get_availability(
                hotel_id="DEMO01",
                start=date.today(),
                end=date.today() + timedelta(days=1),
            )
        assert exc_info.value.retry_after == 60

    @pytest.mark.asyncio
    async def test_token_refresh(self, config, httpx_mock: HTTPXMock):
        """Test automatic token refresh when expired"""
        # Initial token
        httpx_mock.add_response(
            method="POST",
            url="https://identity.apaleo.com/connect/token",
            json={
                "access_token": "initial-token",
                "token_type": "Bearer",
                "expires_in": 1,  # Expires in 1 second
            },
        )

        connector = ApaleoConnector(config)
        await connector.connect()

        # Set token as expired
        connector._token_expires_at = datetime.now().timestamp() - 1

        # New token response
        httpx_mock.add_response(
            method="POST",
            url="https://identity.apaleo.com/connect/token",
            json={
                "access_token": "refreshed-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

        # Mock property endpoint for request
        httpx_mock.add_response(
            method="GET",
            url="https://api.apaleo.com/properties/v1/properties/DEMO01",
            json={"id": "DEMO01", "name": "Test Hotel"},
        )

        # Make request - should trigger token refresh
        await connector.health_check()

        assert connector._access_token == "refreshed-token"

        await connector.disconnect()
