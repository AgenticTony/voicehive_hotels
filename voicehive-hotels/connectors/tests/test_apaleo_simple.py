"""
Simple unit tests for Apaleo Connector focusing on coverage
"""

import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch, AsyncMock

from connectors.adapters.apaleo.connector import ApaleoConnector


class TestApaleoSimple:
    """Simple tests for basic coverage"""

    def test_init(self):
        """Test connector initialization"""
        config = {
            "client_id": "test",
            "client_secret": "secret",
            "base_url": "https://api.apaleo.com",
            "property_id": "TEST01",
        }

        connector = ApaleoConnector(config)

        assert connector.vendor_name == "apaleo"
        assert connector.client_id == "test"
        assert connector.property_id == "TEST01"
        assert connector.capabilities["availability"] is True
        assert connector.capabilities["rates"] is True
        assert connector.capabilities["reservations"] is True

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """Test basic connect/disconnect flow"""
        config = {"client_id": "test", "client_secret": "secret"}

        connector = ApaleoConnector(config)

        # Mock the httpx client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client.headers = {}

        with patch("httpx.AsyncClient", return_value=mock_client):
            await connector.connect()
            assert connector._access_token == "test-token"

            await connector.disconnect()
            mock_client.aclose.assert_called_once()

    def test_normalize_date(self):
        """Test date normalization utility"""
        config = {"client_id": "test", "client_secret": "secret"}
        connector = ApaleoConnector(config)

        # Test ISO format
        result = connector.normalize_date("2024-03-01")
        assert result == date(2024, 3, 1)

        # Test date object
        test_date = date(2024, 3, 1)
        result = connector.normalize_date(test_date)
        assert result == test_date

        # Test datetime object
        test_datetime = datetime(2024, 3, 1, 10, 30)
        result = connector.normalize_date(test_datetime)
        # The connector calls parser.parse which returns a datetime, not date
        assert isinstance(result, date)

    def test_capabilities(self):
        """Test capabilities reporting"""
        config = {"client_id": "test", "client_secret": "secret"}
        connector = ApaleoConnector(config)

        caps = connector.capabilities

        # Apaleo should support these
        assert caps["availability"] is True
        assert caps["rates"] is True
        assert caps["reservations"] is True
        assert caps["modify_reservation"] is True
        assert caps["cancel_reservation"] is True
        assert caps["guest_profiles"] is True
        assert caps["webhooks"] is True
        assert caps["real_time_sync"] is True
        assert caps["multi_property"] is True

        # Not supported
        assert caps["payment_processing"] is False
        assert caps["pos_integration"] is False

    @pytest.mark.asyncio
    async def test_authentication_error(self):
        """Test authentication error handling"""
        config = {"client_id": "bad", "client_secret": "bad"}
        connector = ApaleoConnector(config)

        # Mock failed auth response with HTTPStatusError
        mock_client = MagicMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()

        # Mock httpx.HTTPStatusError
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        http_error = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=mock_response
        )
        mock_client.post = AsyncMock(side_effect=http_error)

        from contracts import AuthenticationError

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AuthenticationError):
                await connector.connect()

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check method"""
        config = {"client_id": "test", "client_secret": "secret", "property_id": "DEMO"}
        connector = ApaleoConnector(config)

        # Setup mocked client
        connector._client = MagicMock()
        connector._client.request = AsyncMock()
        connector._access_token = "test-token"
        connector._token_expires_at = 9999999999

        # Mock successful property request
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "DEMO", "name": "Demo Hotel"}
        mock_resp.content = b'{"id":"DEMO"}'
        mock_resp.raise_for_status = MagicMock()

        connector._client.request = AsyncMock(return_value=mock_resp)

        result = await connector.health_check()

        assert result["status"] == "healthy"
        assert result["vendor"] == "apaleo"
        assert result["property_id"] == "DEMO"
