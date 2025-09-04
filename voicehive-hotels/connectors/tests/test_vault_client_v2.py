"""
Unit tests for Enhanced Vault Client v2
Tests audit logging, token renewal, health checks, and error handling
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime
import base64
import httpx

from connectors.utils.vault_client_v2 import (
    EnhancedVaultClient,
    VaultError,
    VaultConnectionError,
)


class TestEnhancedVaultClient:
    """Unit tests for enhanced Vault client"""

    @pytest.fixture
    def vault_config(self):
        """Test configuration"""
        return {
            "vault_addr": "http://localhost:8200",
            "namespace": "voicehive",
            "role": "test-role",
            "mount_path": "kv",
            "transit_mount": "transit",
        }

    @pytest.fixture
    def mock_httpx_client(self):
        """Mock httpx async client"""
        client = AsyncMock()
        client.headers = {}
        client.aclose = AsyncMock()
        return client

    @pytest.fixture
    def vault_client(self, vault_config, mock_httpx_client):
        """Create Vault client with mocked httpx"""
        with patch(
            "connectors.utils.vault_client_v2.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client_cls.return_value = mock_httpx_client
            client = EnhancedVaultClient(**vault_config)
            client._client = mock_httpx_client
            return client

    @pytest.mark.asyncio
    async def test_init(self, vault_config):
        """Test client initialization"""
        with patch("connectors.utils.vault_client_v2.httpx.AsyncClient"):
            client = EnhancedVaultClient(**vault_config)

            assert client.vault_addr == vault_config["vault_addr"]
            assert client.namespace == vault_config["namespace"]
            assert client.role == vault_config["role"]
            assert client.mount_path == vault_config["mount_path"]
            assert client.transit_mount == vault_config["transit_mount"]
            assert client.enable_audit is True
            assert client.token_renewal_threshold == 0.8

    @pytest.mark.asyncio
    async def test_kubernetes_auth_success(self, vault_client, mock_httpx_client):
        """Test successful Kubernetes authentication"""
        # Mock K8s service account token
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = (
                "fake-jwt-token"
            )

            with patch("pathlib.Path.exists", return_value=True):
                # Mock successful auth response
                mock_response = AsyncMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "auth": {
                        "client_token": "test-token-123",
                        "ttl": 3600,
                        "renewable": True,
                    }
                }
                mock_httpx_client.post.return_value = mock_response

                result = await vault_client._try_kubernetes_auth()

                assert result is True
                assert vault_client._token == "test-token-123"
                assert vault_client._token_info["ttl"] == 3600
                assert mock_httpx_client.headers["X-Vault-Token"] == "test-token-123"

    @pytest.mark.asyncio
    async def test_token_auth_success(self, vault_client, mock_httpx_client):
        """Test successful token authentication"""
        with patch.dict("os.environ", {"VAULT_TOKEN": "env-token-456"}):
            # Mock token lookup response
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {"id": "env-token-456", "ttl": 7200, "renewable": True}
            }
            mock_httpx_client.get.return_value = mock_response

            result = await vault_client._try_token_auth()

            assert result is True
            assert vault_client._token == "env-token-456"
            assert vault_client._token_info["ttl"] == 7200

    @pytest.mark.asyncio
    async def test_dev_auth_success(self, vault_client, mock_httpx_client):
        """Test development token authentication"""
        # Mock health check response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_httpx_client.get.return_value = mock_response

        await vault_client._try_dev_auth()

        assert vault_client._token == "root"
        assert mock_httpx_client.headers["X-Vault-Token"] == "root"

    @pytest.mark.asyncio
    async def test_token_renewal(self, vault_client, mock_httpx_client):
        """Test automatic token renewal"""
        vault_client._token = "current-token"
        vault_client._token_info = {"ttl": 3600}

        # Mock renewal response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "auth": {"client_token": "current-token", "ttl": 3600}
        }
        mock_httpx_client.post.return_value = mock_response

        await vault_client._renew_token()

        mock_httpx_client.post.assert_called_with(
            "/v1/auth/token/renew-self", headers={"X-Vault-Token": "current-token"}
        )

    @pytest.mark.asyncio
    async def test_configure_audit_logging(self, vault_client, mock_httpx_client):
        """Test audit logging configuration"""
        # Mock audit check response (not enabled)
        mock_get_response = AsyncMock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {}

        # Mock audit enable response
        mock_put_response = AsyncMock()
        mock_put_response.status_code = 204

        mock_httpx_client.get.return_value = mock_get_response
        mock_httpx_client.put.return_value = mock_put_response

        await vault_client._configure_audit_logging()

        # Verify audit was enabled
        mock_httpx_client.put.assert_called_once()
        call_args = mock_httpx_client.put.call_args
        assert call_args[0][0] == "/v1/sys/audit/file"
        assert call_args[1]["json"]["type"] == "file"

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, vault_client, mock_httpx_client):
        """Test health check when Vault is healthy"""
        # Mock health response
        health_response = AsyncMock()
        health_response.status_code = 200
        health_response.json.return_value = {
            "initialized": True,
            "sealed": False,
            "standby": False,
        }

        # Mock seal status response
        seal_response = AsyncMock()
        seal_response.status_code = 200
        seal_response.json.return_value = {
            "sealed": False,
            "version": "1.12.0",
            "cluster_id": "test-cluster",
        }

        # Mock mount tests
        mount_response = AsyncMock()
        mount_response.status_code = 404  # OK for empty mounts

        mock_httpx_client.get.side_effect = [
            health_response,
            seal_response,
            mount_response,  # KV
            mount_response,  # Transit
        ]

        vault_client._token = "valid-token"

        health_status = await vault_client.health_check()

        assert health_status.healthy is True
        assert health_status.details["initialized"] is True
        assert health_status.details["sealed"] is False
        assert health_status.details["version"] == "1.12.0"

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, vault_client, mock_httpx_client):
        """Test health check when Vault is unhealthy"""
        # Mock sealed Vault
        health_response = AsyncMock()
        health_response.status_code = 503
        health_response.json.return_value = {"sealed": True}

        mock_httpx_client.get.side_effect = Exception("Connection failed")

        health_status = await vault_client.health_check()

        assert health_status.healthy is False
        assert "error" in health_status.details

    @pytest.mark.asyncio
    async def test_get_secret_success(self, vault_client, mock_httpx_client):
        """Test successful secret retrieval"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"data": {"username": "admin", "password": "secret123"}}
        }
        mock_httpx_client.get.return_value = mock_response

        secret = await vault_client.get_secret("database/creds")

        assert secret["username"] == "admin"
        assert secret["password"] == "secret123"

        # Test caching
        cached_secret = await vault_client.get_secret("database/creds")
        assert cached_secret == secret
        # Should only be called once due to cache
        mock_httpx_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_secret_not_found(self, vault_client, mock_httpx_client):
        """Test secret not found error"""
        mock_response = AsyncMock()
        mock_response.status_code = 404
        mock_httpx_client.get.return_value = mock_response

        with pytest.raises(VaultError) as exc:
            await vault_client.get_secret("nonexistent")

        assert "Secret not found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_put_secret_success(self, vault_client, mock_httpx_client):
        """Test storing secret"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_httpx_client.post.return_value = mock_response

        # Pre-populate cache
        vault_client._cache["test/secret:latest"] = {
            "data": {"old": "value"},
            "timestamp": datetime.now().timestamp(),
        }

        await vault_client.put_secret("test/secret", {"new": "value"})

        # Verify cache was invalidated
        assert "test/secret:latest" not in vault_client._cache

    @pytest.mark.asyncio
    async def test_delete_secret(self, vault_client, mock_httpx_client):
        """Test deleting secret"""
        mock_response = AsyncMock()
        mock_response.status_code = 204
        mock_httpx_client.delete.return_value = mock_response

        await vault_client.delete_secret("obsolete/secret")

        mock_httpx_client.delete.assert_called_with("/v1/kv/metadata/obsolete/secret")

    @pytest.mark.asyncio
    async def test_encrypt_data(self, vault_client, mock_httpx_client):
        """Test data encryption"""
        plaintext = "sensitive data"
        ciphertext = "vault:v1:encrypted123"

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"ciphertext": ciphertext}}
        mock_httpx_client.post.return_value = mock_response

        result = await vault_client.encrypt_data("pii-key", plaintext)

        assert result == ciphertext

        # Verify base64 encoding
        call_args = mock_httpx_client.post.call_args
        sent_data = call_args[1]["json"]["plaintext"]
        decoded = base64.b64decode(sent_data).decode()
        assert decoded == plaintext

    @pytest.mark.asyncio
    async def test_decrypt_data(self, vault_client, mock_httpx_client):
        """Test data decryption"""
        plaintext = "sensitive data"
        ciphertext = "vault:v1:encrypted123"

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"plaintext": base64.b64encode(plaintext.encode()).decode()}
        }
        mock_httpx_client.post.return_value = mock_response

        result = await vault_client.decrypt_data("pii-key", ciphertext)

        assert result == plaintext

    @pytest.mark.asyncio
    async def test_configure_policy(self, vault_client, mock_httpx_client):
        """Test policy configuration"""
        policy_hcl = """
        path "kv/data/connectors/*" {
            capabilities = ["read", "list"]
        }
        """

        mock_response = AsyncMock()
        mock_response.status_code = 204
        mock_httpx_client.put.return_value = mock_response

        await vault_client.configure_policy("connector-policy", policy_hcl)

        mock_httpx_client.put.assert_called_with(
            "/v1/sys/policies/acl/connector-policy", json={"policy": policy_hcl}
        )

    @pytest.mark.asyncio
    async def test_list_secrets(self, vault_client, mock_httpx_client):
        """Test listing secrets"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"keys": ["apaleo/", "mews/", "opera/"]}
        }
        mock_httpx_client.request.return_value = mock_response

        secrets = await vault_client.list_secrets("connectors")

        assert len(secrets) == 3
        assert "apaleo/" in secrets
        assert "mews/" in secrets

    @pytest.mark.asyncio
    async def test_context_manager(self, vault_config):
        """Test async context manager"""
        with patch("connectors.utils.vault_client_v2.httpx.AsyncClient"):
            async with EnhancedVaultClient(**vault_config) as client:
                assert client is not None

    @pytest.mark.asyncio
    async def test_connection_error_handling(self, vault_client, mock_httpx_client):
        """Test connection error handling"""
        mock_httpx_client.get.side_effect = httpx.RequestError("Connection refused")

        with pytest.raises(VaultConnectionError) as exc:
            await vault_client.get_secret("test")

        assert "Connection error" in str(exc.value)

    @pytest.mark.asyncio
    async def test_token_renewal_loop(self, vault_client, mock_httpx_client):
        """Test token renewal background task"""
        vault_client._token = "test-token"
        vault_client._token_info = {"ttl": 10}  # Short TTL for test
        vault_client.token_renewal_threshold = 0.5  # Renew at 50%

        # Mock renewal response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"auth": {"ttl": 10}}
        mock_httpx_client.post.return_value = mock_response

        # Start renewal task
        task = asyncio.create_task(vault_client._token_renewal_loop())

        # Wait for renewal to happen
        await asyncio.sleep(6)

        # Cancel task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify renewal was called
        assert mock_httpx_client.post.called

    @pytest.mark.asyncio
    async def test_retry_mechanism(self, vault_client, mock_httpx_client):
        """Test retry on transient failures"""
        # First two calls fail, third succeeds
        mock_response_fail = AsyncMock()
        mock_response_fail.status_code = 503

        mock_response_success = AsyncMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {"data": {"data": {"key": "value"}}}

        mock_httpx_client.get.side_effect = [
            httpx.RequestError("Temporary failure"),
            httpx.RequestError("Temporary failure"),
            mock_response_success,
        ]

        # Should succeed after retries
        result = await vault_client.get_secret("test/retry")
        assert result["key"] == "value"
        assert mock_httpx_client.get.call_count == 3
