"""
HashiCorp Vault Client for VoiceHive Hotels
Manages secrets and credentials for PMS connectors
"""

import os
import json
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import asyncio
from pathlib import Path

try:
    import hvac

    VAULT_AVAILABLE = True
except ImportError:
    VAULT_AVAILABLE = False
    logging.warning("hvac not installed. Vault integration will be disabled.")

from .pii_redactor import setup_logging_redaction

logger = logging.getLogger(__name__)
setup_logging_redaction(logger)


class VaultError(Exception):
    """Base exception for Vault operations"""

    pass


class VaultAuthError(VaultError):
    """Vault authentication failed"""

    pass


class VaultSecretNotFoundError(VaultError):
    """Secret not found in Vault"""

    pass


class VaultClient:
    """
    HashiCorp Vault client for secure credential management

    Features:
    - Automatic token renewal
    - Secret caching with TTL
    - Kubernetes auth support
    - Local development fallback
    """

    def __init__(
        self,
        vault_url: Optional[str] = None,
        vault_token: Optional[str] = None,
        kubernetes_role: str = "connector-service",
        mount_path: str = "voicehive",
        cache_ttl: int = 300,
    ):
        """
        Initialize Vault client

        Args:
            vault_url: Vault server URL (defaults to VAULT_ADDR env var)
            vault_token: Vault token (defaults to VAULT_TOKEN env var)
            kubernetes_role: Kubernetes auth role for pod authentication
            mount_path: KV v2 mount path
            cache_ttl: Secret cache TTL in seconds
        """
        self.vault_url = vault_url or os.getenv("VAULT_ADDR", "http://vault:8200")
        self.vault_token = vault_token or os.getenv("VAULT_TOKEN")
        self.kubernetes_role = kubernetes_role
        self.mount_path = mount_path
        self.cache_ttl = cache_ttl

        self._client: Optional[hvac.Client] = None
        self._cache: Dict[str, Tuple[Any, datetime]] = {}
        self._initialized = False

        # Check if running in Kubernetes
        self._k8s_token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        self._in_kubernetes = os.path.exists(self._k8s_token_path)

        logger.info(
            "Vault client initialized",
            vault_url=self.vault_url,
            in_kubernetes=self._in_kubernetes,
            mount_path=self.mount_path,
        )

    def _initialize(self):
        """Initialize Vault client connection"""
        if not VAULT_AVAILABLE:
            logger.warning("Vault client not available (hvac not installed)")
            return

        if self._initialized:
            return

        try:
            self._client = hvac.Client(url=self.vault_url)

            # Authenticate based on environment
            if self._in_kubernetes:
                self._authenticate_kubernetes()
            elif self.vault_token:
                self._authenticate_token()
            else:
                logger.warning("No Vault authentication method available")
                return

            # Verify authentication
            if not self._client.is_authenticated():
                raise VaultAuthError("Failed to authenticate with Vault")

            self._initialized = True
            logger.info("Successfully connected to Vault")

        except Exception as e:
            logger.error(f"Failed to initialize Vault client: {e}")
            raise VaultError(f"Vault initialization failed: {e}")

    def _authenticate_kubernetes(self):
        """Authenticate using Kubernetes service account"""
        try:
            with open(self._k8s_token_path, "r") as f:
                jwt_token = f.read().strip()

            # Authenticate with Kubernetes auth method
            self._client.auth.kubernetes.login(role=self.kubernetes_role, jwt=jwt_token)

            logger.info(
                f"Authenticated with Vault using Kubernetes role: {self.kubernetes_role}"
            )

        except Exception as e:
            logger.error(f"Kubernetes authentication failed: {e}")
            raise VaultAuthError(f"Kubernetes auth failed: {e}")

    def _authenticate_token(self):
        """Authenticate using direct token"""
        self._client.token = self.vault_token
        logger.info("Authenticated with Vault using direct token")

    def _get_cache_key(self, path: str) -> str:
        """Generate cache key for secret path"""
        return f"{self.mount_path}/{path}"

    def _is_cached(self, path: str) -> bool:
        """Check if secret is in cache and not expired"""
        cache_key = self._get_cache_key(path)

        if cache_key not in self._cache:
            return False

        _, expiry = self._cache[cache_key]
        return datetime.now(timezone.utc) < expiry

    def _get_from_cache(self, path: str) -> Optional[Dict[str, Any]]:
        """Get secret from cache if valid"""
        if not self._is_cached(path):
            return None

        cache_key = self._get_cache_key(path)
        data, _ = self._cache[cache_key]
        return data

    def _add_to_cache(self, path: str, data: Dict[str, Any]):
        """Add secret to cache with TTL"""
        cache_key = self._get_cache_key(path)
        expiry = datetime.now(timezone.utc) + timedelta(seconds=self.cache_ttl)
        self._cache[cache_key] = (data, expiry)

    def read_secret(self, path: str) -> Dict[str, Any]:
        """
        Read secret from Vault

        Args:
            path: Secret path (relative to mount_path)

        Returns:
            Secret data dictionary

        Raises:
            VaultSecretNotFoundError: Secret not found
            VaultError: Other Vault errors
        """
        # Check cache first
        cached = self._get_from_cache(path)
        if cached is not None:
            logger.debug(f"Secret retrieved from cache: {path}")
            return cached

        # Initialize if needed
        if not self._initialized:
            self._initialize()

        if not self._client:
            raise VaultError("Vault client not initialized")

        try:
            # Read from KV v2 secret engine
            mount_point = f"{self.mount_path}/data"
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path, mount_point=self.mount_path
            )

            if not response or "data" not in response:
                raise VaultSecretNotFoundError(f"Secret not found: {path}")

            data = response["data"]["data"]

            # Cache the secret
            self._add_to_cache(path, data)

            logger.info(f"Secret retrieved from Vault: {path}")
            return data

        except hvac.exceptions.InvalidPath:
            raise VaultSecretNotFoundError(f"Secret not found: {path}")
        except Exception as e:
            logger.error(f"Failed to read secret {path}: {e}")
            raise VaultError(f"Failed to read secret: {e}")

    def read_pms_credentials(self, vendor: str, hotel_id: str) -> Dict[str, Any]:
        """
        Read PMS-specific credentials from Vault

        Args:
            vendor: PMS vendor name (e.g., "apaleo", "mews")
            hotel_id: Hotel identifier

        Returns:
            Credential dictionary with vendor-specific fields
        """
        # Construct path for PMS credentials
        path = f"pms/{vendor}/{hotel_id}/api-credentials"

        try:
            return self.read_secret(path)
        except VaultSecretNotFoundError:
            # Try vendor-level credentials as fallback
            path = f"pms/{vendor}/default/api-credentials"
            return self.read_secret(path)

    def encrypt_data(self, plaintext: str, context: Optional[str] = None) -> str:
        """
        Encrypt data using Vault's transit engine

        Args:
            plaintext: Data to encrypt
            context: Optional encryption context

        Returns:
            Ciphertext string
        """
        if not self._initialized:
            self._initialize()

        if not self._client:
            raise VaultError("Vault client not initialized")

        try:
            import base64

            # Encode plaintext to base64 as required by Vault
            encoded = base64.b64encode(plaintext.encode()).decode()

            response = self._client.secrets.transit.encrypt_data(
                name="connector-data", plaintext=encoded, context=context
            )

            return response["data"]["ciphertext"]

        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise VaultError(f"Encryption failed: {e}")

    def decrypt_data(self, ciphertext: str, context: Optional[str] = None) -> str:
        """
        Decrypt data using Vault's transit engine

        Args:
            ciphertext: Data to decrypt
            context: Optional decryption context

        Returns:
            Decrypted plaintext
        """
        if not self._initialized:
            self._initialize()

        if not self._client:
            raise VaultError("Vault client not initialized")

        try:
            import base64

            response = self._client.secrets.transit.decrypt_data(
                name="connector-data", ciphertext=ciphertext, context=context
            )

            # Decode from base64
            encoded = response["data"]["plaintext"]
            return base64.b64decode(encoded).decode()

        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise VaultError(f"Decryption failed: {e}")

    def clear_cache(self):
        """Clear the secret cache"""
        self._cache.clear()
        logger.info("Vault cache cleared")


# Singleton instance
_vault_client: Optional[VaultClient] = None


def get_vault_client() -> VaultClient:
    """Get or create the default Vault client instance"""
    global _vault_client
    if _vault_client is None:
        _vault_client = VaultClient()
    return _vault_client


class DevelopmentVaultClient(VaultClient):
    """
    Development/testing Vault client that uses local files

    WARNING: This is for development only! Never use in production!
    """

    def __init__(self, secrets_dir: str = ".secrets"):
        super().__init__()
        self.secrets_dir = Path(secrets_dir)
        logger.warning("Using DevelopmentVaultClient - NOT FOR PRODUCTION USE!")

    def read_secret(self, path: str) -> Dict[str, Any]:
        """Read secret from local file"""
        file_path = self.secrets_dir / f"{path}.json"

        if not file_path.exists():
            raise VaultSecretNotFoundError(f"Secret file not found: {file_path}")

        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except Exception as e:
            raise VaultError(f"Failed to read secret file: {e}")

    def encrypt_data(self, plaintext: str, context: Optional[str] = None) -> str:
        """Mock encryption for development"""
        import base64

        # Simple base64 encoding for dev - NOT SECURE!
        return f"dev::{base64.b64encode(plaintext.encode()).decode()}"

    def decrypt_data(self, ciphertext: str, context: Optional[str] = None) -> str:
        """Mock decryption for development"""
        import base64

        if not ciphertext.startswith("dev::"):
            raise VaultError("Invalid development ciphertext")
        encoded = ciphertext[5:]
        return base64.b64decode(encoded).decode()


# Async wrapper for use in async contexts
class AsyncVaultClient:
    """Async wrapper for VaultClient"""

    def __init__(self, vault_client: Optional[VaultClient] = None):
        self._client = vault_client or get_vault_client()
        self._executor = None

    async def read_secret(self, path: str) -> Dict[str, Any]:
        """Async read secret"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._client.read_secret, path
        )

    async def read_pms_credentials(self, vendor: str, hotel_id: str) -> Dict[str, Any]:
        """Async read PMS credentials"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._client.read_pms_credentials, vendor, hotel_id
        )

    async def encrypt_data(self, plaintext: str, context: Optional[str] = None) -> str:
        """Async encrypt data"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._client.encrypt_data, plaintext, context
        )

    async def decrypt_data(self, ciphertext: str, context: Optional[str] = None) -> str:
        """Async decrypt data"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._client.decrypt_data, ciphertext, context
        )
