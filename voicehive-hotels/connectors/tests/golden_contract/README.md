# Golden Contract Tests

The Golden Contract test suite ensures that all PMS connectors behave identically from the application's perspective. This is critical for maintaining consistency across different PMS integrations.

## What are Golden Contract Tests?

Golden Contract tests define the expected behavior that ALL connectors must implement. They ensure:

1. **Consistent API**: All connectors expose the same methods with the same signatures
2. **Predictable Behavior**: Same inputs produce equivalent outputs across vendors
3. **Error Handling**: All connectors handle errors in a consistent way
4. **Data Formats**: Response data structures are normalized

## Test Structure

```
golden_contract/
├── __init__.py
├── test_base_contract.py    # Base test class with all golden tests
├── test_apaleo.py          # Apaleo-specific test configuration
├── test_mews.py            # Mews-specific test configuration
└── README.md               # This file
```

## Running Tests

### Run all golden contract tests:
```bash
pytest connectors/tests/golden_contract/ -v
```

### Run tests for a specific connector:
```bash
pytest connectors/tests/golden_contract/test_apaleo.py -v
```

### Run only fast tests (skip integration):
```bash
pytest connectors/tests/golden_contract/ -v -m "not integration"
```

### Run with real API credentials:
```bash
export APALEO_TEST_CLIENT_ID="your-client-id"
export APALEO_TEST_CLIENT_SECRET="your-secret"
export APALEO_TEST_PROPERTY_ID="your-property"

pytest connectors/tests/golden_contract/ -v -m integration
```

## Adding a New Connector

1. Create a test file: `test_vendor.py`
2. Import the base test class and your connector:
   ```python
   from connectors.adapters.vendor.connector import VendorConnector
   from .test_base_contract import GoldenContractTestBase
   ```

3. Create a test class:
   ```python
   class TestVendorGoldenContract(GoldenContractTestBase):
       connector_class = VendorConnector
   ```

4. Override `_get_test_config()` if needed for vendor-specific config

5. Run the tests - they should all pass!

## Test Categories

### Core Tests (Required)
- `test_health_check` - Connector health status
- `test_error_handling` - Consistent error types
- `test_capabilities_match_implementation` - Accurate capability reporting

### Feature Tests (Required if capability=True)
- `test_get_availability` - Room inventory queries
- `test_quote_rate` - Pricing queries
- `test_guest_search` - Guest profile lookup
- `test_reservation_lifecycle` - Full CRUD operations

### Performance Tests (Recommended)
- Concurrent operation handling
- Rate limit compliance
- Connection pooling

## Environment Variables

Each connector may require different credentials for testing:

### Apaleo
- `APALEO_TEST_CLIENT_ID`
- `APALEO_TEST_CLIENT_SECRET`
- `APALEO_TEST_PROPERTY_ID`
- `APALEO_TEST_BASE_URL` (optional)

### Mews
- `MEWS_TEST_CLIENT_TOKEN`
- `MEWS_TEST_ACCESS_TOKEN`
- `MEWS_TEST_PROPERTY_ID`

### Cloudbeds
- `CLOUDBEDS_TEST_API_KEY`
- `CLOUDBEDS_TEST_PROPERTY_ID`

## Writing Good Golden Contract Tests

1. **Test Behavior, Not Implementation**: Focus on what the connector does, not how
2. **Use Realistic Data**: Test with data that mirrors production usage
3. **Handle Optional Features**: Use `pytest.skip()` for unsupported capabilities
4. **Test Error Cases**: Ensure all connectors fail gracefully
5. **Document Vendor Quirks**: Add comments for vendor-specific behaviors

## Debugging Failed Tests

1. Check the capability matrix - is the feature supported?
2. Verify test credentials are correct
3. Check vendor API status/changes
4. Review connector logs with `-s` flag
5. Use `pytest.set_trace()` for debugging

## CI/CD Integration

Golden contract tests should run on:
- Every PR (mock/unit tests)
- Nightly builds (integration tests with real APIs)
- Before releases (full test suite)

Add to GitHub Actions:
```yaml
- name: Run Golden Contract Tests
  run: |
    pytest connectors/tests/golden_contract/ -v --junit-xml=test-results.xml
  env:
    APALEO_TEST_CLIENT_ID: ${{ secrets.APALEO_TEST_CLIENT_ID }}
    # ... other secrets
```
