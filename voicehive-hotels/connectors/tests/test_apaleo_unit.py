"""
Comprehensive unit tests for Apaleo connector
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal

from connectors.adapters.apaleo.connector import ApaleoConnector
from connectors.contracts import (
    PMSError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    AuthenticationError,
    GuestProfile,
    AvailabilityGrid,
    RateQuote,
    Reservation,
)


class TestApaleoConnector:
    """Unit tests for Apaleo connector"""

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
    def connector(self, config):
        """Create connector instance"""
        return ApaleoConnector(config)

    @pytest.fixture
    def mock_session(self):
        """Mock aiohttp session"""
        session = AsyncMock()
        session.close = AsyncMock()
        session.request = AsyncMock()
        session.post = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_init(self, config):
        """Test connector initialization"""
        connector = ApaleoConnector(config)

        assert connector.config == config
        assert connector.vendor_name == "apaleo"
        assert connector._access_token is None
        assert connector._token_expires_at is None
        # _client is created in connect(), not init
        assert not hasattr(connector, "_client") or connector._client is None

    @pytest.mark.asyncio
    async def test_init_and_properties(self, connector):
        """Test initialization and properties"""
        assert connector.vendor_name == "apaleo"
        assert connector.base_url == "https://api.apaleo.com"
        assert connector.property_id == "DEMO01"
        assert connector.capabilities["availability"] is True
        assert connector.capabilities["rates"] is True
        assert connector.capabilities["reservations"] is True

    @pytest.mark.asyncio
    async def test_cancel_reservation_method(self, connector):
        """Test cancel reservation sends correct PATCH"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            await connector.cancel_reservation("RES123", "Guest requested")

            mock_request.assert_called_with(
                "PATCH",
                "/booking/v1/bookings/RES123",
                json={"status": "Canceled", "cancellationReason": "Guest requested"},
            )

    @pytest.mark.asyncio
    async def test_upsert_guest_profile(self, connector):
        """Test upsert_guest_profile returns profile unchanged"""
        guest = GuestProfile(
            id=None,
            email="test@example.com",
            phone="+123456",
            first_name="Test",
            last_name="Guest",
            nationality="US",
            language="en",
            vip_status=None,
            preferences={},
            gdpr_consent=True,
            marketing_consent=True,
        )

        result = await connector.upsert_guest_profile(guest)
        assert result == guest

    @pytest.mark.asyncio
    async def test_get_availability_with_room_type_filter(self, connector):
        """Test availability with specific room type"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = [
                {
                    "unitGroups": [
                        {"id": "STD", "name": "Standard Room", "maxPersons": 2}
                    ]
                },
                {"availability": []},
            ]

            result = await connector.get_availability(
                hotel_id="DEMO01",
                start=date.today(),
                end=date.today() + timedelta(days=1),
                room_type="STD",
            )

            # Check room_type was passed as unitGroup parameter
            call_args = mock_request.call_args_list[1]
            assert call_args[1]["params"]["unitGroup"] == "STD"

    @pytest.mark.asyncio
    async def test_connect(self, connector):
        """Test connection initialization"""
        with patch.object(
            connector, "_get_access_token", new_callable=AsyncMock
        ) as mock_get_token:
            mock_get_token.return_value = "test_token"

            await connector.connect()

            assert connector.session is not None
            # ClientSession is created in real implementation
            mock_get_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, connector):
        """Test disconnection"""
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        connector._client = mock_client

        await connector.disconnect()

        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_success(self, connector):
        """Test successful API request"""
        mock_client = AsyncMock()
        connector._client = mock_client
        connector._access_token = "test_token"
        connector._token_expires_at = 9999999999  # Far future timestamp

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = AsyncMock()
        mock_response.json = Mock(return_value={"test": "data"})
        mock_response.content = b'{"test": "data"}'

        mock_client.request = AsyncMock(return_value=mock_response)

        result = await connector._request("GET", "/test")

        assert result == {"test": "data"}
        mock_client.request.assert_called_with("GET", "/test")

    @pytest.mark.asyncio
    async def test_request_rate_limit(self, connector):
        """Test rate limit handling"""
        mock_client = AsyncMock()
        connector._client = mock_client
        connector._access_token = "test_token"

        mock_response = AsyncMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.raise_for_status = AsyncMock()

        mock_client.request = AsyncMock(return_value=mock_response)

        with pytest.raises(RateLimitError):
            await connector._request("GET", "/test")

    @pytest.mark.asyncio
    async def test_request_not_found(self, connector):
        """Test 404 handling"""
        mock_client = AsyncMock()
        connector._client = mock_client
        connector._access_token = "test_token"

        mock_response = AsyncMock()
        mock_response.status_code = 404

        # Mock httpx.HTTPStatusError
        import httpx

        error = httpx.HTTPStatusError(
            "Not found", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status = AsyncMock(side_effect=error)
        mock_client.request = AsyncMock(return_value=mock_response)

        with pytest.raises(NotFoundError):
            await connector._request("GET", "/test/123")

    @pytest.mark.asyncio
    async def test_request_server_error(self, connector):
        """Test server error handling"""
        mock_client = AsyncMock()
        connector._client = mock_client
        connector._access_token = "test_token"

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        # Mock httpx.HTTPStatusError
        import httpx

        error = httpx.HTTPStatusError(
            "Server error", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status = AsyncMock(side_effect=error)
        mock_client.request = AsyncMock(return_value=mock_response)

        with pytest.raises(PMSError) as exc:
            await connector._request("GET", "/test")

        assert "API error" in str(exc.value)

    @pytest.mark.asyncio
    async def test_health_check_success(self, connector):
        """Test health check"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"status": "Healthy", "version": "1.0.0"}

            result = await connector.health_check()

            assert result["status"] == "healthy"
            assert result["vendor"] == "apaleo"
            assert "timestamp" in result
            mock_request.assert_called_with("GET", "/status")

    @pytest.mark.asyncio
    async def test_health_check_error(self, connector):
        """Test health check error"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = Exception("API Error")

            result = await connector.health_check()

            assert result["status"] == "unhealthy"
            assert result["vendor"] == "apaleo"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_availability_success(self, connector):
        """Test availability retrieval"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            # Mock unit groups response
            mock_request.side_effect = [
                {
                    "unitGroups": [
                        {
                            "id": "UG1",
                            "code": "STD",
                            "name": "Standard Room",
                            "description": "Comfortable standard room",
                            "maxPersons": 2,
                            "property": {"id": "DEMO01"},
                        },
                        {
                            "id": "UG2",
                            "code": "DLX",
                            "name": "Deluxe Room",
                            "description": "Spacious deluxe room",
                            "maxPersons": 4,
                            "property": {"id": "DEMO01"},
                        },
                    ]
                },
                # Mock availability response
                {
                    "availableUnitItems": [
                        {
                            "unitGroup": {"id": "UG1"},
                            "grossAmount": {"amount": 100.00, "currency": "EUR"},
                            "availableCount": 5,
                        },
                        {
                            "unitGroup": {"id": "UG2"},
                            "grossAmount": {"amount": 150.00, "currency": "EUR"},
                            "availableCount": 2,
                        },
                    ]
                },
            ]

            result = await connector.get_availability(
                hotel_id="DEMO01",
                start=date.today(),
                end=date.today() + timedelta(days=1),
                guest_count=2,
            )

            assert isinstance(result, AvailabilityGrid)
            assert result.hotel_id == "DEMO01"
            assert len(result.room_types) == 2

            # Check room types
            std_room = result.room_types[0]
            assert std_room.code == "STD"
            assert std_room.name == "Standard Room"
            assert std_room.max_occupancy == 2

            # Check availability data
            assert "STD" in result.availability
            assert result.availability["STD"][str(date.today())]["available"] == 5
            assert result.availability["STD"][str(date.today())]["rate"] == 100.00

    @pytest.mark.asyncio
    async def test_quote_rate_success(self, connector):
        """Test rate quote"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "grossAmount": {"amount": 220.00, "currency": "EUR"},
                "taxes": {"amount": 20.00, "currency": "EUR"},
                "fees": [],
                "cancellationPolicy": {
                    "description": "Free cancellation until 6 PM on arrival day"
                },
            }

            result = await connector.quote_rate(
                hotel_id="DEMO01",
                room_type="STD",
                rate_code="BAR",
                arrival=date.today() + timedelta(days=30),
                departure=date.today() + timedelta(days=32),
                guest_count=2,
                currency="EUR",
            )

            assert isinstance(result, RateQuote)
            assert result.room_type == "STD"
            assert result.rate_code == "BAR"
            assert result.total_amount == Decimal("220.00")
            assert result.taxes == Decimal("20.00")
            assert result.fees == Decimal("0.00")
            assert "Free cancellation" in result.cancellation_policy

    @pytest.mark.asyncio
    async def test_create_reservation_success(self, connector):
        """Test reservation creation"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "id": "RES123",
                "bookingId": "BOOK123",
                "status": "Confirmed",
                "primaryGuest": {
                    "firstName": "John",
                    "lastName": "Doe",
                    "email": "john@example.com",
                },
                "arrival": "2024-03-01",
                "departure": "2024-03-03",
                "adults": 2,
                "totalGrossAmount": {"amount": 220.00, "currency": "EUR"},
            }

            result = await connector.create_reservation(
                hotel_id="DEMO01",
                guest_profile={
                    "first_name": "John",
                    "last_name": "Doe",
                    "email": "john@example.com",
                },
                room_type="STD",
                rate_code="BAR",
                arrival=date(2024, 3, 1),
                departure=date(2024, 3, 3),
                guest_count=2,
                amount=Decimal("220.00"),
                currency="EUR",
            )

            assert isinstance(result, Reservation)
            assert result.id == "RES123"
            assert result.confirmation_number == "BOOK123"
            assert result.status == "confirmed"
            assert result.guest.first_name == "John"
            assert result.guest.last_name == "Doe"

    @pytest.mark.asyncio
    async def test_get_reservation_success(self, connector):
        """Test reservation retrieval"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "id": "RES123",
                "bookingId": "BOOK123",
                "status": "Confirmed",
                "primaryGuest": {"firstName": "John", "lastName": "Doe"},
                "arrival": "2024-03-01",
                "departure": "2024-03-03",
                "adults": 2,
                "totalGrossAmount": {"amount": 220.00, "currency": "EUR"},
                "assignedUnitGroup": {"code": "STD"},
                "ratePlan": {"code": "BAR"},
            }

            result = await connector.get_reservation("RES123")

            assert isinstance(result, Reservation)
            assert result.id == "RES123"
            assert result.room_type == "STD"
            assert result.rate_code == "BAR"

    @pytest.mark.asyncio
    async def test_update_reservation_success(self, connector):
        """Test reservation update"""
        with patch.object(
            connector, "get_reservation", new_callable=AsyncMock
        ) as mock_get:
            # Create mock guest profile
            mock_guest = GuestProfile(
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
            mock_get.return_value = Reservation(
                id="RES123",
                confirmation_number="BOOK123",
                status="confirmed",
                hotel_id="DEMO01",
                arrival=date(2024, 3, 1),
                departure=date(2024, 3, 3),
                room_type="STD",
                rate_code="BAR",
                total_amount=Decimal("220.00"),
                guest=mock_guest,
                created_at=datetime.now(),
                modified_at=datetime.now(),
            )

            with patch.object(
                connector, "_request", new_callable=AsyncMock
            ) as mock_request:
                mock_request.return_value = {
                    "id": "RES123",
                    "arrival": "2024-03-02",
                    "departure": "2024-03-04",
                }

                from connectors.contracts import ReservationPatch

                patch_data = ReservationPatch(
                    arrival=date(2024, 3, 2), departure=date(2024, 3, 4)
                )
                result = await connector.modify_reservation("RES123", patch_data)

                assert result.arrival == date(2024, 3, 2)
                assert result.departure == date(2024, 3, 4)

    @pytest.mark.asyncio
    async def test_cancel_reservation_success(self, connector):
        """Test reservation cancellation"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = None  # 204 No Content

            await connector.cancel_reservation("RES123", "Guest request")

            mock_request.assert_called_with(
                "DELETE",
                "/booking/v1/reservations/RES123",
                json={"reason": "Guest request"},
            )

    @pytest.mark.asyncio
    async def test_search_guest_by_email(self, connector):
        """Test guest search by email"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "guests": [
                    {
                        "id": "GUEST123",
                        "firstName": "John",
                        "lastName": "Doe",
                        "email": "john@example.com",
                    }
                ]
            }

            result = await connector.search_guest(email="john@example.com")

            assert len(result) == 1
            assert result[0].id == "GUEST123"
            assert result[0].email == "john@example.com"

            # Verify search parameters
            mock_request.assert_called_with(
                "GET", "/booking/v1/guests", params={"email": "john@example.com"}
            )

    @pytest.mark.asyncio
    async def test_search_guest_by_name(self, connector):
        """Test guest search by name"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"guests": []}

            result = await connector.search_guest(first_name="John", last_name="Doe")

            assert result == []

            # Verify search used text search
            call_args = mock_request.call_args
            assert call_args[1]["params"]["textSearch"] == "John Doe"

    @pytest.mark.asyncio
    async def test_get_guest_profile(self, connector):
        """Test guest profile retrieval"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "id": "GUEST123",
                "firstName": "John",
                "lastName": "Doe",
                "email": "john@example.com",
                "phone": "+1234567890",
                "address": {
                    "addressLine1": "123 Main St",
                    "city": "New York",
                    "countryCode": "US",
                },
            }

            result = await connector.get_guest_profile("GUEST123")

            assert isinstance(result, GuestProfile)
            assert result.id == "GUEST123"
            assert result.email == "john@example.com"
            assert result.phone == "+1234567890"

    @pytest.mark.asyncio
    async def test_stream_arrivals(self, connector):
        """Test arrivals streaming"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            # Mock bookings response
            mock_request.return_value = {
                "bookings": [
                    {"id": "RES1", "bookingNumber": "BOOK1"},
                    {"id": "RES2", "bookingNumber": "BOOK2"},
                ]
            }

            # Mock get_reservation to return mock reservations
            with patch.object(
                connector, "get_reservation", new_callable=AsyncMock
            ) as mock_get:
                mock_guest = GuestProfile(
                    id=None,
                    email="test@example.com",
                    phone="+123456",
                    first_name="Test",
                    last_name="Guest",
                    nationality="US",
                    language="en",
                    vip_status=None,
                    preferences={},
                    gdpr_consent=True,
                    marketing_consent=False,
                )

                async def mock_get_res(res_id):
                    return Reservation(
                        id=res_id,
                        confirmation_number=f"BOOK{res_id[-1]}",
                        status="confirmed",
                        hotel_id="DEMO01",
                        arrival=date.today(),
                        departure=date.today() + timedelta(days=2),
                        room_type="STD",
                        rate_code="BAR",
                        total_amount=Decimal("100.00"),
                        guest=mock_guest,
                        created_at=datetime.now(),
                        modified_at=datetime.now(),
                    )

                mock_get.side_effect = mock_get_res

                reservations = []
                async for res in connector.stream_arrivals(
                    hotel_id="DEMO01", arrival_date=date.today()
                ):
                    reservations.append(res.id)

                assert len(reservations) == 2
                assert "RES1" in reservations
                assert "RES2" in reservations

    @pytest.mark.asyncio
    async def test_validate_config(self, connector):
        """Test configuration validation"""
        # Valid config should not raise
        connector._validate_config()

        # Missing client_id
        connector.config = {"client_secret": "secret"}
        with pytest.raises(ValidationError) as exc:
            connector._validate_config()
        assert "client_id" in str(exc.value)

        # Missing client_secret
        connector.config = {"client_id": "client"}
        with pytest.raises(ValidationError) as exc:
            connector._validate_config()
        assert "client_secret" in str(exc.value)

    @pytest.mark.asyncio
    async def test_format_date(self, connector):
        """Test date formatting"""
        test_date = date(2024, 3, 1)
        formatted = connector._format_date(test_date)
        assert formatted == "2024-03-01"

    @pytest.mark.asyncio
    async def test_parse_date(self, connector):
        """Test date parsing"""
        parsed = connector._parse_date("2024-03-01")
        assert parsed == date(2024, 3, 1)

        # Test datetime string
        parsed = connector._parse_date("2024-03-01T10:30:00")
        assert parsed == date(2024, 3, 1)

    @pytest.mark.asyncio
    async def test_map_reservation_status(self, connector):
        """Test status mapping"""
        assert connector._map_reservation_status("Confirmed") == "confirmed"
        assert connector._map_reservation_status("Canceled") == "cancelled"
        assert connector._map_reservation_status("CheckedIn") == "checked_in"
        assert connector._map_reservation_status("CheckedOut") == "checked_out"
        assert connector._map_reservation_status("NoShow") == "no_show"
        assert connector._map_reservation_status("Unknown") == "unknown"

    @pytest.mark.asyncio
    async def test_map_booking_status(self, connector):
        """Test booking status mapping"""
        assert connector._map_booking_status("Tentative") == "confirmed"
        assert connector._map_booking_status("Confirmed") == "confirmed"
        assert connector._map_booking_status("InHouse") == "checked_in"
        assert connector._map_booking_status("CheckedOut") == "checked_out"
        assert connector._map_booking_status("Canceled") == "cancelled"
        assert connector._map_booking_status("NoShow") == "cancelled"
        assert connector._map_booking_status("Unknown") == "unknown"

    @pytest.mark.asyncio
    async def test_authenticate_success(self, connector, mock_session):
        """Test OAuth authentication"""
        connector._client = mock_session

        # Mock token response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = AsyncMock()
        mock_response.json = Mock(
            return_value={
                "access_token": "test_token_123",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        )

        mock_session.post = AsyncMock(return_value=mock_response)

        await connector._authenticate()

        assert connector._access_token == "test_token_123"
        assert connector._token_expires_at is not None
        assert mock_session.headers["Authorization"] == "Bearer test_token_123"

    @pytest.mark.asyncio
    async def test_authenticate_failure(self, connector, mock_session):
        """Test authentication failure"""
        connector._client = mock_session

        mock_response = AsyncMock()
        mock_response.status_code = 401
        import httpx

        error = httpx.HTTPStatusError(
            "Unauthorized", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status = AsyncMock(side_effect=error)

        mock_session.post = AsyncMock(return_value=mock_response)

        with pytest.raises(AuthenticationError):
            await connector._authenticate()

    @pytest.mark.asyncio
    async def test_ensure_authenticated(self, connector):
        """Test token refresh logic"""
        # Test with no token
        with patch.object(
            connector, "_authenticate", new_callable=AsyncMock
        ) as mock_auth:
            await connector._ensure_authenticated()
            mock_auth.assert_called_once()

        # Test with valid token
        connector._access_token = "valid_token"
        connector._token_expires_at = datetime.now(timezone.utc).timestamp() + 3600

        with patch.object(
            connector, "_authenticate", new_callable=AsyncMock
        ) as mock_auth:
            await connector._ensure_authenticated()
            mock_auth.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_validation_error(self, connector):
        """Test 422 validation error handling"""
        mock_client = AsyncMock()
        connector._client = mock_client
        connector._access_token = "test_token"

        mock_response = AsyncMock()
        mock_response.status_code = 422
        mock_response.text = "Invalid date format"
        # Mock httpx.HTTPStatusError
        import httpx

        error = httpx.HTTPStatusError(
            "Validation failed", request=Mock(), response=mock_response
        )
        mock_response.raise_for_status = AsyncMock(side_effect=error)
        mock_client.request = AsyncMock(return_value=mock_response)

        with pytest.raises(ValidationError) as exc:
            await connector._request("POST", "/test")
        assert "Validation error" in str(exc.value)

    @pytest.mark.asyncio
    async def test_get_guest_profile_not_implemented(self, connector):
        """Test that get_guest_profile raises NotImplementedError"""
        with pytest.raises(NotImplementedError):
            await connector.get_guest_profile("GUEST123")

    @pytest.mark.asyncio
    async def test_stream_in_house(self, connector):
        """Test in-house guest streaming"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "bookings": [
                    {"id": "IN1", "bookingNumber": "INBOOK1"},
                    {"id": "IN2", "bookingNumber": "INBOOK2"},
                ]
            }

            with patch.object(
                connector, "get_reservation", new_callable=AsyncMock
            ) as mock_get:
                mock_guest = GuestProfile(
                    id=None,
                    email="guest@hotel.com",
                    phone="+999999",
                    first_name="In",
                    last_name="House",
                    nationality="US",
                    language="en",
                    vip_status=None,
                    preferences={},
                    gdpr_consent=True,
                    marketing_consent=False,
                )

                async def mock_res(res_id):
                    return Reservation(
                        id=res_id,
                        confirmation_number=f"INBOOK{res_id[-1]}",
                        status="checked_in",
                        hotel_id="DEMO01",
                        arrival=date.today() - timedelta(days=1),
                        departure=date.today() + timedelta(days=1),
                        room_type="DLX",
                        rate_code="RACK",
                        total_amount=Decimal("250.00"),
                        guest=mock_guest,
                        created_at=datetime.now() - timedelta(days=1),
                        modified_at=datetime.now(),
                    )

                mock_get.side_effect = mock_res

                guests = []
                async for res in connector.stream_in_house("DEMO01"):
                    guests.append(res.id)

                assert len(guests) == 2
                assert "IN1" in guests
                assert "IN2" in guests

    @pytest.mark.asyncio
    async def test_normalize_date(self, connector):
        """Test date normalization"""
        # Test ISO format
        result = connector.normalize_date("2024-03-15")
        assert result == date(2024, 3, 15)

        # Test datetime format
        result = connector.normalize_date("2024-03-15T10:30:00")
        assert result == date(2024, 3, 15)

        # Test with timezone
        result = connector.normalize_date("2024-03-15T10:30:00Z")
        assert result == date(2024, 3, 15)

    @pytest.mark.asyncio
    async def test_normalize_amount(self, connector):
        """Test amount normalization"""
        # Test with string
        result = connector.normalize_amount("123.45", "EUR")
        assert result == Decimal("123.45")

        # Test with comma
        result = connector.normalize_amount("1,234.56", "EUR")
        assert result == Decimal("1234.56")

        # Test with int
        result = connector.normalize_amount(100, "EUR")
        assert result == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_get_availability_empty_response(self, connector):
        """Test availability with no rooms"""
        with patch.object(
            connector, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.side_effect = [
                {"unitGroups": []},  # No room types
                {"availability": []},  # No availability
            ]

            result = await connector.get_availability(
                hotel_id="DEMO01",
                start=date.today(),
                end=date.today() + timedelta(days=1),
            )

            assert isinstance(result, AvailabilityGrid)
            assert len(result.room_types) == 0
            assert len(result.availability) == 0
