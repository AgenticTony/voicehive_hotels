"""
Golden Contract Tests for Apaleo Connector
"""

import pytest
import os

from connectors.adapters.apaleo.connector import ApaleoConnector
from .test_base_contract import GoldenContractTestBase
# Import shared fixtures


@pytest.mark.usefixtures("mock_apaleo_auth", "mock_apaleo_health_check")
class TestApaleoGoldenContract(GoldenContractTestBase):
    """Golden contract tests for Apaleo connector with mocked HTTP calls"""

    connector_class = ApaleoConnector

    # Override config if needed for Apaleo-specific settings
    def _get_test_config(self):
        """Get Apaleo-specific test configuration"""
        config = super()._get_test_config()

        # Use test credentials that match our fixtures
        config["client_id"] = "test_client"
        config["client_secret"] = "test_secret"
        config["base_url"] = "https://api.apaleo.com"
        config["property_id"] = "DEMO01"  # Match fixture data

        return config

    @pytest.mark.asyncio
    async def test_apaleo_specific_features(self, connector):
        """Test Apaleo-specific features beyond the golden contract"""
        # Apaleo supports unit groups
        assert hasattr(connector, "property_id")
        assert connector.property_id == "DEMO01"

        # Apaleo uses OAuth2 - should have token after connect
        assert hasattr(connector, "_access_token")
        assert connector._access_token == "test-token-123"  # From mock


# Mock-based tests for specific scenarios
@pytest.mark.usefixtures(
    "mock_apaleo_availability", "mock_apaleo_rates", "mock_apaleo_create_booking"
)
class TestApaleoWithMocks(TestApaleoGoldenContract):
    """Mocked golden contract tests for reliable CI/CD"""

    @pytest.mark.asyncio
    async def test_golden_availability(self, connector):
        """Test availability check with mocked responses"""
        await super().test_get_availability(connector)

    @pytest.mark.asyncio
    async def test_golden_rates(self, connector):
        """Test rate quotes with mocked responses"""
        await super().test_quote_rate(connector)

    @pytest.mark.asyncio
    async def test_golden_booking_flow(self, connector):
        """Test complete booking flow with mocks"""
        await super().test_create_booking(connector)


# Real integration tests (marked for manual/staging runs)
@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("APALEO_TEST_CLIENT_ID"),
    reason="Apaleo test credentials not configured",
)
class TestApaleoIntegration:
    """Integration tests that require real Apaleo credentials"""

    @pytest.fixture
    def real_config(self):
        """Get real credentials from environment"""
        return {
            "client_id": os.getenv("APALEO_TEST_CLIENT_ID"),
            "client_secret": os.getenv("APALEO_TEST_CLIENT_SECRET"),
            "base_url": "https://api.apaleo.com",
            "property_id": os.getenv("APALEO_SANDBOX_PROPERTY", "DEMO01"),
        }

    @pytest.mark.asyncio
    async def test_real_connection(self, real_config):
        """Test real OAuth connection"""
        connector = ApaleoConnector(real_config)
        await connector.connect()
        assert connector._access_token is not None
        await connector.disconnect()
