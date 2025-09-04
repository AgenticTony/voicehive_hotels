#!/usr/bin/env python3
"""
Example: Using the PMS Connector Factory

This script demonstrates how to:
1. List available connectors
2. Check connector capabilities
3. Create connector instances
4. Use connectors for common operations
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from connectors import (
    get_connector,
    list_available_connectors,
    get_connector_metadata,
    get_capability_matrix,
    find_connectors_with_capability,
    GuestProfile,
    ReservationDraft
)


async def main():
    """Demonstrate connector factory usage"""
    
    print("=== VoiceHive Hotels PMS Connector Factory Demo ===\n")
    
    # 1. List available connectors
    print("Available PMS Connectors:")
    vendors = list_available_connectors()
    for vendor in vendors:
        metadata = get_connector_metadata(vendor)
        print(f"  - {vendor}: {metadata.name} (v{metadata.version}) - {metadata.status.value}")
    
    # 2. Show capability matrix
    print("\nCapability Matrix:")
    matrix = get_capability_matrix()
    for vendor, capabilities in matrix.items():
        print(f"\n  {vendor}:")
        for cap, supported in capabilities.items():
            if supported:
                print(f"    ✓ {cap}")
    
    # 3. Find connectors with specific capabilities
    print("\nConnectors with webhook support:")
    webhook_vendors = find_connectors_with_capability("webhooks")
    for vendor in webhook_vendors:
        print(f"  - {vendor}")
    
    # 4. Create a connector instance (example with Apaleo)
    if "apaleo" in vendors:
        print("\n=== Creating Apaleo Connector ===")
        
        # In production, these would come from environment variables or Vault
        config = {
            "client_id": os.getenv("APALEO_CLIENT_ID", "demo_client_id"),
            "client_secret": os.getenv("APALEO_CLIENT_SECRET", "demo_secret"),
            "base_url": "https://api.apaleo.com",
            "property_id": "DEMO01",
            "hotel_id": "DEMO01"
        }
        
        try:
            # Create connector
            connector = get_connector("apaleo", config)
            print("✓ Connector created successfully")
            
            # Use async context manager for automatic connection management
            async with connector:
                # 5. Perform health check
                print("\nPerforming health check...")
                health = await connector.health_check()
                print(f"Health Status: {health['status']}")
                
                # 6. Check availability
                print("\nChecking availability...")
                today = date.today()
                next_week = today + timedelta(days=7)
                
                availability = await connector.get_availability(
                    hotel_id="DEMO01",
                    start=today,
                    end=next_week
                )
                
                print(f"Room types available: {len(availability.room_types)}")
                for room_type in availability.room_types[:3]:  # Show first 3
                    print(f"  - {room_type.code}: {room_type.name} (max {room_type.max_occupancy} guests)")
                
                # 7. Get a rate quote
                if availability.room_types:
                    print("\nGetting rate quote...")
                    room_type = availability.room_types[0]
                    
                    quote = await connector.quote_rate(
                        hotel_id="DEMO01",
                        room_type=room_type.code,
                        rate_code="BAR",  # Best Available Rate
                        arrival=today,
                        departure=today + timedelta(days=2),
                        guest_count=2,
                        currency="EUR"
                    )
                    
                    print(f"Rate Quote for {room_type.name}:")
                    print(f"  Total: {quote.currency} {quote.total_amount}")
                    print(f"  Taxes: {quote.currency} {quote.taxes}")
                    print(f"  Cancellation: {quote.cancellation_policy}")
                
                # 8. Create a reservation (demo only - would fail without real API)
                print("\nCreating reservation (demo)...")
                
                guest = GuestProfile(
                    email="john.doe@example.com",
                    phone="+1234567890",
                    first_name="John",
                    last_name="Doe",
                    nationality="US",
                    language="en",
                    gdpr_consent=True,
                    marketing_consent=False,
                    preferences={"room": "high_floor", "bed": "king"}
                )
                
                reservation_draft = ReservationDraft(
                    hotel_id="DEMO01",
                    arrival=today,
                    departure=today + timedelta(days=2),
                    room_type=room_type.code if availability.room_types else "STD",
                    rate_code="BAR",
                    guest_count=2,
                    guest=guest,
                    special_requests="Late check-in after 10 PM"
                )
                
                # This would create a real reservation with valid credentials
                # reservation = await connector.create_reservation(reservation_draft)
                # print(f"✓ Reservation created: {reservation.confirmation_number}")
                print("✓ Reservation draft created (not submitted in demo mode)")
                
        except Exception as e:
            print(f"Error: {e}")
    
    # 9. Demonstrate error handling
    print("\n=== Error Handling Demo ===")
    try:
        # Try to create a connector for non-existent vendor
        bad_connector = get_connector("non_existent", {})
    except Exception as e:
        print(f"Expected error for non-existent vendor: {e}")
    
    # 10. Show how to use mock connector for testing
    print("\n=== Mock Connector Demo ===")
    from connectors.contracts import MockConnector
    from connectors import register_connector, ConnectorMetadata, ConnectorStatus
    
    # Register mock connector
    register_connector("mock_hotel", MockConnector, ConnectorMetadata(
        vendor="mock_hotel",
        name="Mock Hotel System",
        version="1.0.0",
        status=ConnectorStatus.AVAILABLE,
        capabilities={cap: True for cap in ["availability", "rates", "reservations"]},
        regions=["eu-west-1"],
        rate_limits={"requests_per_minute": 1000},
        authentication="api_key"
    ))
    
    # Use mock connector
    mock_config = {
        "api_key": "mock_key",
        "base_url": "https://mock.example.com",
        "hotel_id": "MOCK01"
    }
    
    mock_connector = get_connector("mock_hotel", mock_config)
    print("✓ Mock connector created for testing")
    
    print("\n=== Demo Complete ===")


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())
