"""
Golden Contract Test Suite - Base Tests
Ensures all PMS connectors behave identically from the application's perspective
"""

import pytest
import pytest_asyncio
from datetime import date, timedelta
from decimal import Decimal
from typing import Type, Dict, Any
import os

from contracts import PMSConnector, PMSError, NotFoundError, ValidationError


class GoldenContractTestBase:
    """
    Base class for golden contract tests
    Subclass this for each connector and set connector_class
    """

    connector_class: Type[PMSConnector] = None
    test_config: Dict[str, Any] = None

    @pytest_asyncio.fixture
    async def connector(self):
        """Create and yield a connector instance"""
        if not self.connector_class:
            pytest.skip("No connector class defined")

        # Use test config or environment variables
        config = self.test_config or self._get_test_config()

        connector = self.connector_class(config)

        # Initialize connection
        await connector.connect()

        yield connector

        # Cleanup
        await connector.disconnect()

    def _get_test_config(self) -> Dict[str, Any]:
        """Get test configuration from environment or defaults"""
        vendor = self.connector_class.vendor_name

        # Try to get from environment first
        config = {
            "hotel_id": os.getenv(f"{vendor.upper()}_TEST_HOTEL_ID", "TEST_HOTEL_01"),
            "base_url": os.getenv(f"{vendor.upper()}_TEST_BASE_URL"),
        }

        # Add vendor-specific auth
        if vendor == "apaleo":
            config.update(
                {
                    "client_id": os.getenv("APALEO_TEST_CLIENT_ID", "test_client"),
                    "client_secret": os.getenv(
                        "APALEO_TEST_CLIENT_SECRET", "test_secret"
                    ),
                    "property_id": os.getenv("APALEO_TEST_PROPERTY_ID", "DEMO01"),
                }
            )
        elif vendor == "mews":
            config.update(
                {
                    "client_token": os.getenv("MEWS_TEST_CLIENT_TOKEN", "test_token"),
                    "access_token": os.getenv("MEWS_TEST_ACCESS_TOKEN", "test_access"),
                }
            )
        # Add other vendors as needed

        return config

    @pytest.mark.asyncio
    async def test_health_check(self, connector):
        """Test that health check returns expected format"""
        health = await connector.health_check()

        assert "status" in health
        assert health["status"] in ["healthy", "unhealthy"]
        assert "vendor" in health
        assert health["vendor"] == connector.vendor_name
        assert "timestamp" in health

    @pytest.mark.asyncio
    async def test_get_availability(self, connector):
        """Test availability query returns correct structure"""
        # Skip if connector doesn't support availability
        if not connector.capabilities.get("availability"):
            pytest.skip(f"{connector.vendor_name} doesn't support availability")

        start = date.today() + timedelta(days=30)
        end = start + timedelta(days=2)

        availability = await connector.get_availability(
            hotel_id=connector.config.get("hotel_id", "TEST_HOTEL_01"),
            start=start,
            end=end,
        )

        # Verify structure
        assert availability.hotel_id
        assert isinstance(availability.room_types, list)
        assert len(availability.room_types) >= 0  # May be empty

        # Check room type structure if any
        for room_type in availability.room_types:
            assert room_type.code
            assert room_type.name
            assert room_type.max_occupancy >= room_type.base_occupancy
            assert room_type.base_occupancy > 0

        # Check availability grid
        assert isinstance(availability.availability, dict)

    @pytest.mark.asyncio
    async def test_quote_rate(self, connector):
        """Test rate quote returns consistent format"""
        if not connector.capabilities.get("rates"):
            pytest.skip(f"{connector.vendor_name} doesn't support rates")

        arrival = date.today() + timedelta(days=30)
        departure = arrival + timedelta(days=2)

        # First get available rooms
        if connector.capabilities.get("availability"):
            availability = await connector.get_availability(
                hotel_id=connector.config.get("hotel_id", "TEST_HOTEL_01"),
                start=arrival,
                end=departure,
            )
            if not availability.room_types:
                pytest.skip("No rooms available for rate test")
            room_type = availability.room_types[0].code
        else:
            room_type = "STD"  # Default room type

        quote = await connector.quote_rate(
            hotel_id=connector.config.get("hotel_id", "TEST_HOTEL_01"),
            room_type=room_type,
            rate_code="BAR",  # Best Available Rate
            arrival=arrival,
            departure=departure,
            guest_count=2,
            currency="EUR",
        )

        # Verify structure
        assert quote.room_type == room_type
        assert quote.rate_code
        assert quote.currency
        assert isinstance(quote.total_amount, Decimal)
        assert quote.total_amount > 0
        assert isinstance(quote.taxes, Decimal)
        assert isinstance(quote.fees, Decimal)
        assert quote.cancellation_policy

    @pytest.mark.asyncio
    async def test_guest_search(self, connector):
        """Test guest search functionality"""
        if not connector.capabilities.get("guest_profiles"):
            pytest.skip(f"{connector.vendor_name} doesn't support guest profiles")

        # Search by email - should return empty list for non-existent
        guests = await connector.search_guest(email="nonexistent@test.com")
        assert isinstance(guests, list)

        # Search by last name
        guests = await connector.search_guest(last_name="TestGuest")
        assert isinstance(guests, list)

    @pytest.mark.asyncio
    async def test_error_handling(self, connector):
        """Test that connectors raise consistent errors"""
        # Test NotFoundError
        with pytest.raises(NotFoundError):
            await connector.get_reservation("NONEXISTENT_ID_12345")

        # Test invalid date range if rates supported
        if connector.capabilities.get("rates"):
            with pytest.raises((ValidationError, PMSError)):
                await connector.quote_rate(
                    hotel_id=connector.config.get("hotel_id", "TEST_HOTEL_01"),
                    room_type="STD",
                    rate_code="BAR",
                    arrival=date.today() + timedelta(days=30),
                    departure=date.today() + timedelta(days=29),  # Before arrival
                    guest_count=2,
                    currency="EUR",
                )


class TestConnectorCapabilities(GoldenContractTestBase):
    """Test capability reporting is accurate"""

    @pytest.mark.asyncio
    async def test_capabilities_match_implementation(self, connector):
        """Verify that reported capabilities match actual implementation"""
        capabilities = connector.capabilities

        # Test each capability
        if capabilities.get("availability"):
            # Should not raise NotImplementedError
            try:
                await connector.get_availability(
                    hotel_id="TEST",
                    start=date.today(),
                    end=date.today() + timedelta(days=1),
                )
            except NotImplementedError:
                pytest.fail("Capability 'availability' reported but not implemented")
            except Exception:
                pass  # Other errors are OK

        if capabilities.get("rates"):
            try:
                await connector.quote_rate(
                    hotel_id="TEST",
                    room_type="STD",
                    rate_code="BAR",
                    arrival=date.today(),
                    departure=date.today() + timedelta(days=1),
                    guest_count=1,
                    currency="EUR",
                )
            except NotImplementedError:
                pytest.fail("Capability 'rates' reported but not implemented")
            except Exception:
                pass


# Helper function to run tests against a specific connector
def create_test_class(
    connector_class: Type[BaseConnector], config: Dict[str, Any] = None
):
    """
    Create a test class for a specific connector

    Usage:
        TestApaleo = create_test_class(ApaleoConnector, {"client_id": "..."})
    """
    class_name = f"Test{connector_class.__name__}GoldenContract"

    # Create new test class inheriting from base
    test_class = type(
        class_name,
        (GoldenContractTestBase,),
        {"connector_class": connector_class, "test_config": config},
    )

    return test_class
