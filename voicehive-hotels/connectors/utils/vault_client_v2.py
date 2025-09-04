"""
Enhanced HashiCorp Vault Client v2
Includes audit logging, token renewal, health checks, and better error handling
"""

import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from pathlib import Path
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class VaultError(Exception):
    """Base Vault error"""

    pass


class VaultConnectionError(VaultError):
    """Vault connection issues"""

    pass


class VaultAuthenticationError(VaultError):
    """Authentication failures"""

    pass


class VaultHealthStatus:
    """Vault health check result"""

    def __init__(self, healthy: bool, details: Dict[str, Any]):
        self.healthy = healthy
        self.details = details
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "healthy": self.healthy,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


class EnhancedVaultClient:
    """
    Enhanced Vault client with:
    - Audit logging configuration
    - Automatic token renewal
    - Health check endpoint
    - Better error handling
    - Async support
    """

    def __init__(
        self,
        vault_addr: Optional[str] = None,
        namespace: Optional[str] = None,
        role: Optional[str] = None,
        mount_path: str = "kv",
        transit_mount: str = "transit",
        cache_ttl: int = 300,
        enable_audit: bool = True,
        token_renewal_threshold: float = 0.8,  # Renew when 80% of TTL consumed
    ):
        self.vault_addr = vault_addr or os.getenv("VAULT_ADDR", "http://localhost:8200")
        self.namespace = namespace or os.getenv("VAULT_NAMESPACE", "voicehive")
        self.role = role or os.getenv("VAULT_ROLE", "connector-sdk")
        self.mount_path = mount_path
        self.transit_mount = transit_mount
        self.cache_ttl = cache_ttl
        self.enable_audit = enable_audit
        self.token_renewal_threshold = token_renewal_threshold

        self._client: Optional[httpx.AsyncClient] = None
        self._token: Optional[str] = None
        self._token_info: Optional[Dict[str, Any]] = None
        self._cache: Dict[str, Any] = {}
        self._renewal_task: Optional[asyncio.Task] = None

        # Initialize async client
        self._client = httpx.AsyncClient(
            base_url=self.vault_addr,
            timeout=30.0,
            headers={"X-Vault-Namespace": self.namespace},
        )

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def initialize(self):
        """Initialize Vault connection and authentication"""
        try:
            # Authenticate
            await self._authenticate()

            # Enable audit logging if configured
            if self.enable_audit:
                await self._configure_audit_logging()

            # Start token renewal task
            if self._token_info and "ttl" in self._token_info:
                self._renewal_task = asyncio.create_task(self._token_renewal_loop())

            logger.info(
                "Vault client initialized successfully",
                extra={"vault_addr": self.vault_addr, "namespace": self.namespace},
            )

        except Exception as e:
            logger.error(f"Failed to initialize Vault client: {e}")
            raise VaultConnectionError(f"Vault initialization failed: {e}")

    async def close(self):
        """Clean up resources"""
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.aclose()

    async def _authenticate(self):
        """Authenticate with Vault using Kubernetes auth or token"""
        # Try Kubernetes auth first
        if await self._try_kubernetes_auth():
            return

        # Fall back to token auth
        if await self._try_token_auth():
            return

        # Fall back to local dev token
        await self._try_dev_auth()

    async def _try_kubernetes_auth(self) -> bool:
        """Try Kubernetes service account authentication"""
        sa_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        if not Path(sa_token_path).exists():
            return False

        try:
            with open(sa_token_path) as f:
                jwt_token = f.read().strip()

            response = await self._client.post(
                "/v1/auth/kubernetes/login", json={"role": self.role, "jwt": jwt_token}
            )

            if response.status_code == 200:
                data = response.json()
                self._token = data["auth"]["client_token"]
                self._token_info = data["auth"]
                self._client.headers["X-Vault-Token"] = self._token
                logger.info("Authenticated with Vault using Kubernetes auth")
                return True

        except Exception as e:
            logger.debug(f"Kubernetes auth failed: {e}")

        return False

    async def _try_token_auth(self) -> bool:
        """Try token authentication from environment"""
        token = os.getenv("VAULT_TOKEN")
        if not token:
            return False

        try:
            # Validate token
            response = await self._client.get(
                "/v1/auth/token/lookup-self", headers={"X-Vault-Token": token}
            )

            if response.status_code == 200:
                data = response.json()
                self._token = token
                self._token_info = data["data"]
                self._client.headers["X-Vault-Token"] = self._token
                logger.info("Authenticated with Vault using token")
                return True

        except Exception as e:
            logger.debug(f"Token auth failed: {e}")

        return False

    async def _try_dev_auth(self):
        """Try development root token (local only)"""
        if "localhost" not in self.vault_addr and "127.0.0.1" not in self.vault_addr:
            raise VaultAuthenticationError("No valid authentication method available")

        # Try common dev tokens
        for token in ["root", "dev-only-token"]:
            try:
                response = await self._client.get(
                    "/v1/sys/health", headers={"X-Vault-Token": token}
                )

                if response.status_code == 200:
                    self._token = token
                    self._client.headers["X-Vault-Token"] = self._token
                    logger.warning("Using development token - NOT FOR PRODUCTION")
                    return

            except Exception:
                continue

        raise VaultAuthenticationError("Failed to authenticate with Vault")

    async def _token_renewal_loop(self):
        """Background task to renew token before expiry"""
        while True:
            try:
                if not self._token_info:
                    break

                # Prefer expire_time if available, else use ttl seconds
                sleep_secs: Optional[float] = None
                expire_time = self._token_info.get("expire_time")
                if expire_time:
                    try:
                        # expire_time like "2025-09-04T13:22:33.000000000Z"
                        # Normalize and compute delta
                        iso = expire_time.replace("Z", "+00:00")
                        exp_dt = datetime.fromisoformat(iso)
                        now = datetime.now(timezone.utc)
                        total = (exp_dt - now).total_seconds()
                        if total > 0:
                            sleep_secs = total * self.token_renewal_threshold
                    except Exception:
                        sleep_secs = None

                if sleep_secs is None:
                    ttl = self._token_info.get("ttl")
                    if ttl is None:
                        break
                    sleep_secs = float(ttl) * self.token_renewal_threshold

                # Wait until renewal is needed (minimum 5 seconds)
                await asyncio.sleep(max(5.0, sleep_secs))

                # Renew token
                await self._renew_token()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Token renewal failed: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute

    async def _renew_token(self):
        """Renew the current token"""
        try:
            response = await self._client.post(
                "/v1/auth/token/renew-self", headers={"X-Vault-Token": self._token}
            )

            if response.status_code == 200:
                data = response.json()
                self._token_info = data["auth"]
                logger.info("Successfully renewed Vault token")
            else:
                logger.error(f"Token renewal failed: {response.status_code}")

        except Exception as e:
            logger.error(f"Token renewal error: {e}")
            raise VaultAuthenticationError(f"Failed to renew token: {e}")

    async def _configure_audit_logging(self):
        """Configure audit logging backends and optional header hashing"""
        try:
            # Check enabled audit devices
            response = await self._client.get("/v1/sys/audit")
            enabled = set()
            if response.status_code == 200:
                # response is a map like {"file/": {...}, "syslog/": {...}}
                enabled = set(response.json().keys())

            # Enable file audit backend (idempotent)
            if "file/" not in enabled:
                audit_config = {
                    "type": "file",
                    "options": {
                        "file_path": "/vault/logs/audit.log",
                        "log_raw": "false",
                        "hmac_accessor": "true",
                        "mode": "0600",
                        "format": "json",
                    },
                }
                resp_file = await self._client.put(
                    "/v1/sys/audit/file", json=audit_config
                )
                if resp_file.status_code in [200, 204]:
                    logger.info("Vault file audit logging enabled")
                else:
                    logger.warning(
                        f"Failed to enable file audit logging: {resp_file.status_code}"
                    )

            # Optionally enable syslog audit backend
            enable_syslog = os.getenv("VAULT_AUDIT_SYSLOG", "false").lower() in (
                "1",
                "true",
                "yes",
            )
            if enable_syslog and "syslog/" not in enabled:
                syslog_config = {
                    "type": "syslog",
                    "options": {
                        "tag": os.getenv("VAULT_AUDIT_SYSLOG_TAG", "vault-voicehive"),
                        "facility": os.getenv("VAULT_AUDIT_SYSLOG_FACILITY", "LOCAL0"),
                        "log_raw": "false",
                    },
                }
                resp_syslog = await self._client.put(
                    "/v1/sys/audit/syslog", json=syslog_config
                )
                if resp_syslog.status_code in [200, 204]:
                    logger.info("Vault syslog audit logging enabled")
                else:
                    logger.warning(
                        f"Failed to enable syslog audit logging: {resp_syslog.status_code}"
                    )

            # Optionally configure header HMAC settings
            configure_headers = os.getenv(
                "VAULT_AUDIT_HEADERS_HMAC", "false"
            ).lower() in ("1", "true", "yes")
            if configure_headers:
                headers_map = os.getenv("VAULT_AUDIT_HEADERS_MAP")
                # Expect JSON mapping for flexibility, else apply a safe default
                if headers_map:
                    try:
                        hdr_json = json.loads(headers_map)
                    except json.JSONDecodeError:
                        hdr_json = {"hmac": {"X-Correlation-ID": True}}
                else:
                    hdr_json = {"hmac": {"X-Correlation-ID": True}}
                _ = await self._client.post(
                    "/v1/sys/config/auditing/request-headers", json=hdr_json
                )

        except Exception as e:
            logger.warning(f"Audit logging configuration failed: {e}")

    async def health_check(self) -> VaultHealthStatus:
        """Check Vault health and connectivity"""
        try:
            # Check system health
            response = await self._client.get("/v1/sys/health")
            health_data = response.json() if response.status_code == 200 else {}

            # Check seal status
            seal_response = await self._client.get("/v1/sys/seal-status")
            seal_data = seal_response.json() if seal_response.status_code == 200 else {}

            # Test KV mount
            kv_healthy = await self._test_kv_mount()

            # Test Transit mount
            transit_healthy = await self._test_transit_mount()

            details = {
                "initialized": health_data.get("initialized", False),
                "sealed": seal_data.get("sealed", True),
                "standby": health_data.get("standby", False),
                "version": seal_data.get("version", "unknown"),
                "cluster_id": seal_data.get("cluster_id", "unknown"),
                "kv_mount": kv_healthy,
                "transit_mount": transit_healthy,
                "token_valid": self._token is not None,
            }

            healthy = (
                details["initialized"]
                and not details["sealed"]
                and details["kv_mount"]
                and details["transit_mount"]
                and details["token_valid"]
            )

            return VaultHealthStatus(healthy, details)

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return VaultHealthStatus(False, {"error": str(e)})

    async def _test_kv_mount(self) -> bool:
        """Test if KV mount is accessible"""
        try:
            response = await self._client.get(f"/v1/{self.mount_path}/metadata/")
            return response.status_code in [200, 404]  # 404 is ok (no keys yet)
        except Exception:
            return False

    async def _test_transit_mount(self) -> bool:
        """Test if Transit mount is accessible"""
        try:
            response = await self._client.get(f"/v1/{self.transit_mount}/keys")
            return response.status_code in [200, 404]  # 404 is ok (no keys yet)
        except Exception:
            return False

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def get_secret(
        self, path: str, version: Optional[int] = None
    ) -> Dict[str, Any]:
        """Get secret from KV store with caching"""
        cache_key = f"{path}:{version or 'latest'}"

        # Check cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if datetime.now().timestamp() - cached["timestamp"] < self.cache_ttl:
                return cached["data"]

        # Fetch from Vault
        url = f"/v1/{self.mount_path}/data/{path}"
        params = {"version": version} if version else {}

        try:
            response = await self._client.get(url, params=params)

            if response.status_code == 404:
                raise VaultError(f"Secret not found: {path}")
            elif response.status_code != 200:
                raise VaultError(f"Failed to get secret: {response.status_code}")

            data = response.json()
            secret_data = data["data"]["data"]

            # Update cache
            self._cache[cache_key] = {
                "data": secret_data,
                "timestamp": datetime.now().timestamp(),
            }

            return secret_data

        except httpx.RequestError as e:
            raise VaultConnectionError(f"Connection error: {e}")

    @retry(
        stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def put_secret(self, path: str, data: Dict[str, Any]) -> None:
        """Store secret in KV store"""
        url = f"/v1/{self.mount_path}/data/{path}"

        try:
            response = await self._client.post(url, json={"data": data})

            if response.status_code not in [200, 204]:
                raise VaultError(f"Failed to store secret: {response.status_code}")

            # Invalidate cache
            for key in list(self._cache.keys()):
                if key.startswith(f"{path}:"):
                    del self._cache[key]

        except httpx.RequestError as e:
            raise VaultConnectionError(f"Connection error: {e}")

    async def delete_secret(self, path: str) -> None:
        """Delete secret from KV store"""
        url = f"/v1/{self.mount_path}/metadata/{path}"

        try:
            response = await self._client.delete(url)

            if response.status_code not in [204, 404]:
                raise VaultError(f"Failed to delete secret: {response.status_code}")

            # Invalidate cache
            for key in list(self._cache.keys()):
                if key.startswith(f"{path}:"):
                    del self._cache[key]

        except httpx.RequestError as e:
            raise VaultConnectionError(f"Connection error: {e}")

    async def encrypt_data(self, key_name: str, plaintext: str) -> str:
        """Encrypt data using Transit engine"""
        import base64

        url = f"/v1/{self.transit_mount}/encrypt/{key_name}"
        encoded = base64.b64encode(plaintext.encode()).decode()

        try:
            response = await self._client.post(url, json={"plaintext": encoded})

            if response.status_code != 200:
                raise VaultError(f"Encryption failed: {response.status_code}")

            data = response.json()
            return data["data"]["ciphertext"]

        except httpx.RequestError as e:
            raise VaultConnectionError(f"Connection error: {e}")

    async def decrypt_data(self, key_name: str, ciphertext: str) -> str:
        """Decrypt data using Transit engine"""
        import base64

        url = f"/v1/{self.transit_mount}/decrypt/{key_name}"

        try:
            response = await self._client.post(url, json={"ciphertext": ciphertext})

            if response.status_code != 200:
                raise VaultError(f"Decryption failed: {response.status_code}")

            data = response.json()
            decoded = base64.b64decode(data["data"]["plaintext"]).decode()
            return decoded

        except httpx.RequestError as e:
            raise VaultConnectionError(f"Connection error: {e}")

    async def configure_policy(self, policy_name: str, policy_hcl: str) -> None:
        """Create or update a Vault policy"""
        url = f"/v1/sys/policies/acl/{policy_name}"

        try:
            response = await self._client.put(url, json={"policy": policy_hcl})

            if response.status_code not in [200, 204]:
                raise VaultError(f"Failed to configure policy: {response.status_code}")

            logger.info(f"Policy '{policy_name}' configured successfully")

        except httpx.RequestError as e:
            raise VaultConnectionError(f"Connection error: {e}")

    async def list_secrets(self, path: str = "") -> List[str]:
        """List secrets at a given path"""
        url = f"/v1/{self.mount_path}/metadata/{path}"

        try:
            response = await self._client.request("LIST", url)

            if response.status_code == 404:
                return []
            elif response.status_code != 200:
                raise VaultError(f"Failed to list secrets: {response.status_code}")

            data = response.json()
            return data["data"]["keys"]

        except httpx.RequestError as e:
            raise VaultConnectionError(f"Connection error: {e}")
