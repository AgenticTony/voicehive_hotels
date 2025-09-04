"""
Golden Contract Test Suite
Ensures all PMS connectors behave identically from the application's perspective
"""

import pytest
import asyncio
from datetime import date, timedelta
from decimal import Decimal
from typing import Type

from connectors.contracts import (
    PMSConnector, PMSError, NotFoundError, ValidationError,
    GuestProfile, ReservationDraft, ReservationPatch
)
from connectors.adapters.apaleo.connector import ApaleoConnector
# from connectors.adapters.mews.connector import MewsConnector
# from connectors.adapters.cloudbeds.connector import CloudbedsConnector
# from connectors.adapters.opera.connector import OperaConnector


# Parametrize tests to run against all connectors
CONNECTOR_CLASSES = [
    ApaleoConnector,
    # MewsConnector,
    # CloudbedsConnector,
    # OperaConnector,
]


@pytest.fixture
async def connector_factory():
    """Factory to create connector instances with test config"""
    connectors = []
    
    async def _create_connector(connector_class: Type[PMSConnector]):
        config = {
            # Use environment variables or test config
            "client_id": f"test_{connector_class.vendor_name}_client",
            "client_secret": f"test_{connector_class.vendor_name}_secret",
            "property_id": "TEST_HOTEL_01",
            "base_url": "https://api.test.example.com",  # Mock endpoint
        }
        
        connector = connector_class(config)
        connectors.append(connector)
        await connector.connect()
        return connector
    
    yield _create_connector
    
    # Cleanup
    for conn in connectors:
        await conn.disconnect()


class TestGoldenContract:
    """Golden contract tests that all connectors must pass"""
    
    @pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
    @pytest.mark.asyncio
    async def test_health_check(self, connector_factory, connector_class):
        """Test that health check returns expected format"""
        connector = await connector_factory(connector_class)
        
        health = await connector.health_check()
        
        assert "status" in health
        assert health["status"] in ["healthy", "unhealthy"]
        assert "vendor" in health
        assert health["vendor"] == connector.vendor_name
        assert "timestamp" in health
    
    @pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
    async def test_get_availability(self, connector_factory, connector_class):
        """Test availability query returns correct structure"""
        connector = await connector_factory(connector_class)
        
        # Skip if connector doesn't support availability
        if not connector.capabilities.get("availability"):
            pytest.skip(f"{connector.vendor_name} doesn't support availability")
        
        start = date.today() + timedelta(days=30)
        end = start + timedelta(days=2)
        
        availability = await connector.get_availability(
            hotel_id="TEST_HOTEL_01",
            start=start,
            end=end
        )
        
        # Verify structure
        assert availability.hotel_id == "TEST_HOTEL_01"
        assert isinstance(availability.room_types, list)
        assert len(availability.room_types) > 0
        
        # Check room type structure
        for room_type in availability.room_types:
            assert room_type.code
            assert room_type.name
            assert room_type.max_occupancy >= room_type.base_occupancy
            assert room_type.base_occupancy > 0
        
        # Check availability grid
        assert isinstance(availability.availability, dict)
        # Should have entries for each date in range
        current = start
        while current <= end:
            assert current in availability.availability
            current += timedelta(days=1)
    
    @pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
    async def test_quote_rate(self, connector_factory, connector_class):
        """Test rate quote returns consistent format"""
        connector = await connector_factory(connector_class)
        
        if not connector.capabilities.get("rates"):
            pytest.skip(f"{connector.vendor_name} doesn't support rates")
        
        arrival = date.today() + timedelta(days=30)
        departure = arrival + timedelta(days=2)
        
        quote = await connector.quote_rate(
            hotel_id="TEST_HOTEL_01",
            room_type="STD",
            rate_code="BAR",
            arrival=arrival,
            departure=departure,
            guest_count=2,
            currency="EUR"
        )
        
        # Verify structure
        assert quote.room_type == "STD"
        assert quote.rate_code == "BAR"
        assert quote.currency == "EUR"
        assert isinstance(quote.total_amount, Decimal)
        assert quote.total_amount > 0
        assert isinstance(quote.taxes, Decimal)
        assert isinstance(quote.fees, Decimal)
        assert quote.cancellation_policy
        
        # Check breakdown
        assert len(quote.breakdown) == 2  # 2 nights
        for night_date, amount in quote.breakdown.items():
            assert isinstance(night_date, date)
            assert isinstance(amount, Decimal)
            assert amount > 0
    
    @pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
    async def test_reservation_lifecycle(self, connector_factory, connector_class):
        """Test complete reservation lifecycle: create, get, modify, cancel"""
        connector = await connector_factory(connector_class)
        
        if not connector.capabilities.get("reservations"):
            pytest.skip(f"{connector.vendor_name} doesn't support reservations")
        
        # Create guest
        guest = GuestProfile(
            id=None,
            email="john.doe@test.com",
            phone="+1234567890",
            first_name="John",
            last_name="Doe",
            nationality="US",
            language="en",
            vip_status=None,
            preferences={},
            gdpr_consent=True,
            marketing_consent=False
        )
        
        # Create reservation
        arrival = date.today() + timedelta(days=30)
        departure = arrival + timedelta(days=2)
        
        draft = ReservationDraft(
            hotel_id="TEST_HOTEL_01",
            arrival=arrival,
            departure=departure,
            room_type="STD",
            rate_code="BAR",
            guest_count=2,
            guest=guest,
            special_requests="Late arrival",
            payment_method="credit_card"
        )
        
        reservation = await connector.create_reservation(draft)
        
        # Verify created reservation
        assert reservation.id
        assert reservation.confirmation_number
        assert reservation.status == "confirmed"
        assert reservation.hotel_id == "TEST_HOTEL_01"
        assert reservation.arrival == arrival
        assert reservation.departure == departure
        assert reservation.room_type == "STD"
        assert isinstance(reservation.total_amount, Decimal)
        assert reservation.total_amount > 0
        
        # Get reservation by ID
        fetched = await connector.get_reservation(reservation.id)
        assert fetched.id == reservation.id
        assert fetched.confirmation_number == reservation.confirmation_number
        
        # Get by confirmation number
        fetched_by_conf = await connector.get_reservation(
            reservation.confirmation_number,
            by_confirmation=True
        )
        assert fetched_by_conf.id == reservation.id
        
        # Modify reservation (if supported)
        if connector.capabilities.get("modify_reservation"):
            new_departure = departure + timedelta(days=1)
            changes = ReservationPatch(
                departure=new_departure,
                special_requests="Late arrival + Extra towels"
            )
            
            modified = await connector.modify_reservation(reservation.id, changes)
            assert modified.departure == new_departure
            assert "Extra towels" in (modified.special_requests or "")
        
        # Cancel reservation (if supported)
        if connector.capabilities.get("cancel_reservation"):
            await connector.cancel_reservation(reservation.id, "Testing cancellation")
            
            # Verify cancellation
            cancelled = await connector.get_reservation(reservation.id)
            assert cancelled.status == "cancelled"
    
    @pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
    async def test_guest_search(self, connector_factory, connector_class):
        """Test guest search functionality"""
        connector = await connector_factory(connector_class)
        
        if not connector.capabilities.get("guest_profiles"):
            pytest.skip(f"{connector.vendor_name} doesn't support guest profiles")
        
        # Search by email
        guests = await connector.search_guest(email="john.doe@test.com")
        assert isinstance(guests, list)
        
        # Search by last name
        guests = await connector.search_guest(last_name="Doe")
        assert isinstance(guests, list)
        
        # Verify guest structure
        for guest in guests[:1]:  # Check first guest
            assert guest.first_name
            assert guest.last_name
            assert guest.email or guest.phone
            assert isinstance(guest.gdpr_consent, bool)
    
    @pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
    async def test_streaming_operations(self, connector_factory, connector_class):
        """Test streaming operations return async iterators"""
        connector = await connector_factory(connector_class)
        
        # Test arrivals stream
        arrivals = connector.stream_arrivals("TEST_HOTEL_01", date.today())
        assert hasattr(arrivals, "__aiter__")
        
        # Consume first item (if any)
        try:
            async for arrival in arrivals:
                assert arrival.status in ["confirmed", "checked_in"]
                assert arrival.arrival == date.today()
                break
        except StopAsyncIteration:
            pass  # No arrivals today
        
        # Test in-house stream
        in_house = connector.stream_in_house("TEST_HOTEL_01")
        assert hasattr(in_house, "__aiter__")
        
        try:
            async for guest in in_house:
                assert guest.status == "checked_in"
                break
        except StopAsyncIteration:
            pass  # No in-house guests
    
    @pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
    async def test_error_handling(self, connector_factory, connector_class):
        """Test that connectors raise consistent errors"""
        connector = await connector_factory(connector_class)
        
        # Test NotFoundError
        with pytest.raises(NotFoundError):
            await connector.get_reservation("NONEXISTENT_ID")
        
        # Test ValidationError (if reservations supported)
        if connector.capabilities.get("reservations"):
            invalid_guest = GuestProfile(
                id=None,
                email="invalid",  # Invalid email
                phone="",
                first_name="",  # Empty name
                last_name="",
                nationality=None,
                language=None,
                vip_status=None,
                preferences={},
                gdpr_consent=True,
                marketing_consent=False
            )
            
            invalid_draft = ReservationDraft(
                hotel_id="TEST_HOTEL_01",
                arrival=date.today() - timedelta(days=1),  # Past date
                departure=date.today() - timedelta(days=2),  # Before arrival
                room_type="INVALID_ROOM",
                rate_code="INVALID_RATE",
                guest_count=0,  # Invalid count
                guest=invalid_guest,
                special_requests=None,
                payment_method=None
            )
            
            with pytest.raises((ValidationError, PMSError)):
                await connector.create_reservation(invalid_draft)
    
    @pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
    async def test_capability_enforcement(self, connector_factory, connector_class):
        """Test that capabilities are properly enforced"""
        connector = await connector_factory(connector_class)
        
        # If a capability is False, the method should raise NotImplementedError
        if not connector.capabilities.get("payment_processing", False):
            # Assuming we add a process_payment method later
            with pytest.raises(NotImplementedError):
                await connector.process_payment("RES123", Decimal("100.00"))


@pytest.mark.parametrize("connector_class", CONNECTOR_CLASSES)
async def test_concurrent_operations(connector_factory, connector_class):
    """Test that connectors handle concurrent operations correctly"""
    connector = await connector_factory(connector_class)
    
    if not connector.capabilities.get("availability"):
        pytest.skip(f"{connector.vendor_name} doesn't support availability")
    
    # Run multiple queries concurrently
    start = date.today() + timedelta(days=30)
    tasks = []
    
    for i in range(5):
        tasks.append(
            connector.get_availability(
                hotel_id="TEST_HOTEL_01",
                start=start + timedelta(days=i),
                end=start + timedelta(days=i+2)
            )
        )
    
    # Should complete without errors
    results = await asyncio.gather(*tasks)
    assert len(results) == 5
    for result in results:
        assert result.hotel_id == "TEST_HOTEL_01"
