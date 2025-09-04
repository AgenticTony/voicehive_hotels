"""
Golden Contract Tests for Apaleo Connector
"""

import pytest
import os

from connectors.adapters.apaleo.connector import ApaleoConnector
from .test_base_contract import GoldenContractTestBase


class TestApaleoGoldenContract(GoldenContractTestBase):
    """Golden contract tests for Apaleo connector"""
    
    connector_class = ApaleoConnector
    
    # Override config if needed for Apaleo-specific settings
    def _get_test_config(self):
        """Get Apaleo-specific test configuration"""
        config = super()._get_test_config()
        
        # Apaleo-specific defaults if not in environment
        if not config.get("base_url"):
            config["base_url"] = "https://api.apaleo.com"
        
        # Use Apaleo sandbox property if available
        if not config.get("property_id"):
            config["property_id"] = os.getenv("APALEO_SANDBOX_PROPERTY", "DEMO01")
            
        return config
    
    @pytest.mark.asyncio
    async def test_apaleo_specific_features(self, connector):
        """Test Apaleo-specific features beyond the golden contract"""
        # Apaleo supports unit groups
        assert hasattr(connector, "property_id")
        
        # Apaleo uses OAuth2
        assert hasattr(connector, "_access_token")


# Run specific integration tests if credentials are available
@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("APALEO_TEST_CLIENT_ID"),
    reason="Apaleo test credentials not configured"
)
class TestApaleoIntegration(TestApaleoGoldenContract):
    """Integration tests that require real Apaleo credentials"""
    
    @pytest.mark.asyncio
    async def test_real_availability_check(self, connector):
        """Test against real Apaleo API"""
        # This will use actual credentials from environment
        await super().test_get_availability(connector)
    
    @pytest.mark.asyncio
    async def test_real_rate_quote(self, connector):
        """Test rate quotes against real API"""
        await super().test_quote_rate(connector)
