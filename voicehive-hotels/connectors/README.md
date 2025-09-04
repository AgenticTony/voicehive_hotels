# PMS Connector Framework

The VoiceHive Hotels PMS Connector Framework implements the **80/20 pattern** for partner integrations:
- **80% common functionality** in the core framework (contracts, factory, base classes)
- **20% vendor-specific logic** in individual adapters

## Architecture

```
connectors/
├── contracts.py          # Universal interface all PMS must implement
├── factory.py            # Dynamic connector selection and initialization
├── capability_matrix.yaml # Vendor feature support matrix
└── adapters/             # Vendor-specific implementations
    ├── apaleo/           # Quick win - modern REST API
    ├── mews/             # Popular in Europe
    ├── cloudbeds/        # Strong in small/boutique hotels
    ├── opera/            # Enterprise standard (Oracle OHIP)
    └── siteminder/       # Channel manager integration
```

## Quick Start

```python
from connectors import get_connector, list_available_connectors

# List available PMS connectors
vendors = list_available_connectors()
print(f"Available: {vendors}")  # ['apaleo', 'mews', 'opera', ...]

# Create a connector instance
config = {
    "client_id": "your_client_id",
    "client_secret": "your_secret", 
    "base_url": "https://api.apaleo.com",
    "hotel_id": "HOTEL01"
}

connector = get_connector("apaleo", config)

# Use the connector
async with connector:
    # Check availability
    availability = await connector.get_availability(
        hotel_id="HOTEL01",
        start=date.today(),
        end=date.today() + timedelta(days=7)
    )
    
    # Create reservation
    reservation = await connector.create_reservation(reservation_draft)
```

## Universal Contract

All PMS connectors must implement the `PMSConnector` protocol defined in `contracts.py`:

### Core Operations

1. **Availability Management**
   ```python
   async def get_availability(hotel_id, start, end, room_type=None) -> AvailabilityGrid
   ```

2. **Rate Management**
   ```python
   async def quote_rate(hotel_id, room_type, rate_code, arrival, departure, guest_count) -> RateQuote
   ```

3. **Reservation Management**
   ```python
   async def create_reservation(payload: ReservationDraft) -> Reservation
   async def get_reservation(reservation_id) -> Reservation
   async def modify_reservation(reservation_id, changes: ReservationPatch) -> Reservation
   async def cancel_reservation(reservation_id, reason) -> None
   ```

4. **Guest Profile Management**
   ```python
   async def search_guest(email=None, phone=None, last_name=None) -> List[GuestProfile]
   async def get_guest_profile(guest_id) -> GuestProfile
   async def upsert_guest_profile(profile: GuestProfile) -> GuestProfile
   ```

### Capability Matrix

Not all PMS support all features. Check capabilities before using:

```python
from connectors import get_connector_metadata, find_connectors_with_capability

# Check what a vendor supports
metadata = get_connector_metadata("cloudbeds")
print(metadata.capabilities)  # {'reservations': True, 'webhooks': 'limited', ...}

# Find vendors with specific capabilities
webhook_vendors = find_connectors_with_capability("webhooks")
realtime_vendors = find_connectors_with_capability("real_time_sync")
```

## Adding a New Connector

### 1. Create Adapter Structure

```bash
mkdir -p connectors/adapters/newpms
touch connectors/adapters/newpms/__init__.py
touch connectors/adapters/newpms/connector.py
```

### 2. Implement the Connector

```python
# connectors/adapters/newpms/connector.py
from connectors.contracts import BaseConnector, Capabilities

class NewPMSConnector(BaseConnector):
    vendor_name = "newpms"
    
    capabilities = {
        Capabilities.AVAILABILITY.value: True,
        Capabilities.RATES.value: True,
        Capabilities.RESERVATIONS.value: True,
        # ... define what this PMS supports
    }
    
    async def connect(self):
        """Initialize connection to PMS API"""
        # Set up HTTP client, authenticate, etc.
        pass
    
    async def get_availability(self, hotel_id, start, end, room_type=None):
        """Implement availability check"""
        # Transform PMS-specific response to AvailabilityGrid
        pass
    
    # ... implement other required methods
```

### 3. Update Capability Matrix

```yaml
# connectors/capability_matrix.yaml
vendors:
  newpms:
    display_name: "New PMS System"
    api_type: "REST"
    oauth: true
    capabilities:
      availability: true
      rates: true
      reservations: true
      # ... list all capabilities
    rate_limits:
      requests_per_second: 10
      burst_limit: 50
    regions:
      - eu-west-1
    certification_required: true
```

### 4. Write Golden Contract Tests

```python
# connectors/tests/golden_contract/test_newpms.py
import pytest
from connectors.tests.golden_contract.base import GoldenContractTestSuite

class TestNewPMSGoldenContract(GoldenContractTestSuite):
    vendor = "newpms"
    
    @pytest.fixture
    def test_config(self):
        return {
            "api_key": "test_key",
            "base_url": "https://sandbox.newpms.com",
            "hotel_id": "TEST01"
        }
```

## Error Handling

All connectors use standardized exceptions:

- `AuthenticationError` - Invalid credentials or expired tokens
- `RateLimitError` - API rate limits exceeded (includes retry_after)
- `ValidationError` - Invalid data sent to PMS
- `NotFoundError` - Resource not found
- `PMSError` - General PMS errors

Example:
```python
from connectors import PMSError, RateLimitError

try:
    reservation = await connector.create_reservation(draft)
except RateLimitError as e:
    # Wait and retry
    await asyncio.sleep(e.retry_after or 60)
except ValidationError as e:
    # Fix the data and retry
    logger.error(f"Invalid data: {e}")
except PMSError as e:
    # Handle general errors
    logger.error(f"PMS error: {e}")
```

## Testing

### Unit Tests
```bash
pytest connectors/tests/test_factory.py -v
```

### Golden Contract Tests
```bash
# Test all connectors against universal behavior
pytest connectors/tests/golden_contract/ -v

# Test specific vendor
pytest connectors/tests/golden_contract/ -k apaleo
```

### Integration Tests
```bash
# Requires real credentials
APALEO_CLIENT_ID=xxx APALEO_CLIENT_SECRET=yyy pytest connectors/tests/integration/test_apaleo.py
```

## Performance Considerations

1. **Connection Pooling**: Connectors reuse HTTP connections
2. **Rate Limiting**: Built-in rate limit handling with exponential backoff
3. **Caching**: Connector instances are cached per hotel
4. **Async First**: All operations are async for concurrent requests

## Security

1. **Credentials**: Never hardcode - use environment variables or HashiCorp Vault
2. **Token Refresh**: OAuth tokens are automatically refreshed
3. **Audit Logging**: All operations are logged with correlation IDs
4. **Data Validation**: Input/output validation with Pydantic models

## Monitoring

Connectors emit structured logs and metrics:

```python
{
    "timestamp": "2025-01-15T10:30:45Z",
    "level": "INFO",
    "vendor": "apaleo",
    "operation": "create_reservation",
    "hotel_id": "HOTEL01",
    "duration_ms": 245,
    "status": "success",
    "correlation_id": "abc-123"
}
```

## Troubleshooting

### Connector Not Found
```python
NotFoundError: Connector not found for vendor: xyz
```
- Check vendor name matches capability_matrix.yaml
- Ensure adapter directory exists and has __init__.py
- Verify connector.py implements BaseConnector

### Authentication Failures
- Check credentials are correct for environment (sandbox vs production)
- Verify OAuth scopes match required capabilities
- Check token expiration and refresh logic

### Rate Limits
- Review rate limits in capability_matrix.yaml
- Implement caching for frequently accessed data
- Use batch operations where available

## Contributing

1. Follow the 80/20 pattern - maximize reuse of common code
2. All new connectors must pass golden contract tests
3. Document vendor-specific quirks in the adapter
4. Update capability matrix with accurate feature support
5. Add integration tests with sandbox credentials

## License

Proprietary - see LICENSE file in repository root
