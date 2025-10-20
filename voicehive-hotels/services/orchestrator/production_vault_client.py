#!/usr/bin/env python3
"""
Production Vault Client Implementation

Replaces mock implementations with production-grade Vault integration.
Implements:
- Real API key validation against Vault
- Transit engine for encryption operations
- Secret rotation automation
- Health monitoring
- HA configuration support

Following HashiCorp Vault Production Hardening Guidelines:
https://developer.hashicorp.com/vault/tutorials/operations/production-hardening
"""

import asyncio
import base64
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import json
import secrets

import hvac
import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from auth_models import Permission, APIKeyRequest, APIKeyResponse, ServiceContext
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.production_vault_client")


@dataclass
class VaultHealthStatus:
    """Vault health status information"""
    healthy: bool
    sealed: bool
    standby: bool
    replication_performance_mode: Optional[str]
    replication_dr_mode: Optional[str]
    server_time_utc: Optional[str]
    version: Optional[str]
    cluster_name: Optional[str]
    cluster_id: Optional[str]
    details: Dict[str, Any]


@dataclass
class EncryptionResult:
    """Result from encryption operation"""
    ciphertext: str
    key_version: int
    context: Optional[str] = None


@dataclass
class DecryptionResult:
    """Result from decryption operation"""
    plaintext: str
    key_version: int
    context: Optional[str] = None


class ProductionVaultClient:
    """
    Production-grade Vault client implementation

    Features:
    - Real API key validation using Vault KV store
    - Transit engine integration for encryption/decryption
    - Automatic secret rotation
    - Health monitoring and alerting
    - HA configuration support
    - Production security hardening
    """

    def __init__(self, vault_url: Optional[str] = None, vault_token: Optional[str] = None):
        self.vault_url = vault_url or os.getenv("VAULT_URL", "https://vault.voicehive.com:8200")
        self.vault_token = vault_token or os.getenv("VAULT_TOKEN")
        self.vault_role_id = os.getenv("VAULT_ROLE_ID")
        self.vault_secret_id = os.getenv("VAULT_SECRET_ID")
        self.vault_namespace = os.getenv("VAULT_NAMESPACE")

        # Initialize HVAC client
        self.client = hvac.Client(
            url=self.vault_url,
            namespace=self.vault_namespace
        )

        # Vault paths (configurable via environment)
        self.api_keys_path = os.getenv("VAULT_API_KEYS_PATH", "secret/data/api-keys")
        self.service_configs_path = os.getenv("VAULT_SERVICE_CONFIGS_PATH", "secret/data/service-configs")
        self.encryption_key_name = os.getenv("VAULT_ENCRYPTION_KEY", "voicehive-master")
        self.transit_mount_point = os.getenv("VAULT_TRANSIT_MOUNT", "transit")

        # Authentication status
        self._authenticated = False
        self._auth_method = None

        logger.info("production_vault_client_initialized",
                   vault_url=self.vault_url,
                   namespace=self.vault_namespace,
                   has_token=bool(self.vault_token),
                   has_approle=bool(self.vault_role_id and self.vault_secret_id))

    async def initialize(self) -> bool:
        """Initialize Vault client with authentication"""
        try:
            # Try authentication methods in order of preference
            if await self._authenticate_with_approle():
                self._auth_method = "approle"
                logger.info("vault_authenticated_with_approle")
            elif await self._authenticate_with_token():
                self._auth_method = "token"
                logger.info("vault_authenticated_with_token")
            elif await self._authenticate_with_kubernetes():
                self._auth_method = "kubernetes"
                logger.info("vault_authenticated_with_kubernetes")
            else:
                logger.error("vault_authentication_failed",
                           methods_tried=["approle", "token", "kubernetes"])
                return False

            # Verify authentication
            if not self.client.is_authenticated():
                logger.error("vault_authentication_verification_failed")
                return False

            # Initialize Transit engine if not already enabled
            await self._ensure_transit_engine()

            # Create master encryption key if it doesn't exist
            await self._ensure_master_encryption_key()

            self._authenticated = True
            logger.info("production_vault_client_ready", auth_method=self._auth_method)
            return True

        except Exception as e:
            logger.error("vault_initialization_failed", error=str(e))
            return False

    async def _authenticate_with_approle(self) -> bool:
        """Authenticate using AppRole method"""
        if not self.vault_role_id or not self.vault_secret_id:
            return False

        try:
            result = self.client.auth.approle.login(
                role_id=self.vault_role_id,
                secret_id=self.vault_secret_id
            )

            if result and 'auth' in result:
                self.client.token = result['auth']['client_token']
                return True

            return False

        except Exception as e:
            logger.warning("approle_authentication_failed", error=str(e))
            return False

    async def _authenticate_with_token(self) -> bool:
        """Authenticate using direct token"""
        if not self.vault_token:
            return False

        try:
            self.client.token = self.vault_token
            # Test the token by making a simple request
            self.client.sys.read_health_status()
            return True

        except Exception as e:
            logger.warning("token_authentication_failed", error=str(e))
            return False

    async def _authenticate_with_kubernetes(self) -> bool:
        """Authenticate using Kubernetes service account"""
        try:
            # Read service account token
            token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
            if not os.path.exists(token_path):
                return False

            with open(token_path, 'r') as f:
                k8s_token = f.read().strip()

            # Get Kubernetes role name
            k8s_role = os.getenv("VAULT_K8S_ROLE", "voicehive-orchestrator")

            result = self.client.auth.kubernetes.login(
                role=k8s_role,
                jwt=k8s_token
            )

            if result and 'auth' in result:
                self.client.token = result['auth']['client_token']
                return True

            return False

        except Exception as e:
            logger.warning("kubernetes_authentication_failed", error=str(e))
            return False

    async def _ensure_transit_engine(self) -> None:
        """Ensure Transit secrets engine is enabled"""
        try:
            # Check if transit engine is already enabled
            engines = self.client.sys.list_mounted_secrets_engines()
            transit_path = f"{self.transit_mount_point}/"

            if transit_path not in engines:
                logger.info("enabling_transit_engine", mount_point=self.transit_mount_point)
                self.client.sys.enable_secrets_engine(
                    backend_type='transit',
                    path=self.transit_mount_point,
                    description='VoiceHive Encryption as a Service'
                )
            else:
                logger.info("transit_engine_already_enabled", mount_point=self.transit_mount_point)

        except Exception as e:
            # Non-fatal if we can't enable transit (might be permission issue)
            logger.warning("transit_engine_setup_failed", error=str(e))

    async def _ensure_master_encryption_key(self) -> None:
        """Ensure master encryption key exists in Transit engine"""
        try:
            # Try to read the key first
            try:
                self.client.secrets.transit.read_key(
                    name=self.encryption_key_name,
                    mount_point=self.transit_mount_point
                )
                logger.info("master_encryption_key_exists", key_name=self.encryption_key_name)
                return
            except hvac.exceptions.InvalidPath:
                # Key doesn't exist, create it
                pass

            # Create master encryption key
            logger.info("creating_master_encryption_key", key_name=self.encryption_key_name)
            self.client.secrets.transit.create_key(
                name=self.encryption_key_name,
                mount_point=self.transit_mount_point,
                key_type='aes256-gcm96',  # AES-256-GCM for authenticated encryption
                exportable=False,  # Never allow key export for security
                allow_plaintext_backup=False,  # Disable plaintext backup
                deletion_allowed=False  # Prevent accidental deletion
            )

        except Exception as e:
            logger.warning("master_encryption_key_setup_failed", error=str(e))

    async def validate_api_key(self, api_key: str) -> ServiceContext:
        """Validate API key against Vault storage"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            # Hash the API key for lookup
            api_key_hash = self._hash_api_key(api_key)

            # Look up API key in Vault
            lookup_path = f"{self.api_keys_path}/hashes/{api_key_hash}"

            try:
                hash_result = self.client.secrets.kv.v2.read_secret_version(
                    path=lookup_path.replace("secret/data/", "")
                )
                api_key_id = hash_result['data']['data']['api_key_id']
            except hvac.exceptions.InvalidPath:
                raise Exception("API key not found")

            # Get full API key details
            key_path = f"{self.api_keys_path}/{api_key_id}"
            key_result = self.client.secrets.kv.v2.read_secret_version(
                path=key_path.replace("secret/data/", "")
            )
            key_data = key_result['data']['data']

            # Check if key is active
            if not key_data.get('active', False):
                raise Exception("API key is deactivated")

            # Check expiration
            expires_at = key_data.get('expires_at')
            if expires_at:
                expires_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if datetime.utcnow() > expires_date.replace(tzinfo=None):
                    raise Exception("API key has expired")

            # Create service context
            permissions = [Permission(perm) for perm in key_data.get('permissions', [])]

            service_context = ServiceContext(
                service_name=key_data['service_name'],
                api_key_id=api_key_id,
                permissions=permissions,
                created_at=datetime.fromisoformat(key_data['created_at'].replace('Z', '+00:00')),
                expires_at=expires_date.replace(tzinfo=None) if expires_at else None
            )

            logger.info("api_key_validated",
                       service_name=key_data['service_name'],
                       permissions_count=len(permissions))

            return service_context

        except Exception as e:
            logger.warning("api_key_validation_failed", error=str(e))
            raise Exception(f"API key validation failed: {str(e)}")

    async def encrypt_data(self, plaintext: str, context: Optional[str] = None) -> EncryptionResult:
        """Encrypt data using Vault Transit engine"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            # Encode plaintext to base64 (required by Vault)
            plaintext_b64 = base64.b64encode(plaintext.encode('utf-8')).decode('utf-8')

            # Prepare encryption request
            encrypt_params = {
                'plaintext': plaintext_b64,
                'mount_point': self.transit_mount_point
            }

            if context:
                # Context must be base64 encoded
                context_b64 = base64.b64encode(context.encode('utf-8')).decode('utf-8')
                encrypt_params['context'] = context_b64

            # Encrypt using Transit engine
            result = self.client.secrets.transit.encrypt_data(
                name=self.encryption_key_name,
                **encrypt_params
            )

            ciphertext = result['data']['ciphertext']
            key_version = result['data'].get('key_version', 1)

            logger.debug("data_encrypted",
                        key_name=self.encryption_key_name,
                        key_version=key_version,
                        has_context=bool(context))

            return EncryptionResult(
                ciphertext=ciphertext,
                key_version=key_version,
                context=context
            )

        except Exception as e:
            logger.error("encryption_failed", error=str(e))
            raise Exception(f"Encryption failed: {str(e)}")

    async def decrypt_data(self, ciphertext: str, context: Optional[str] = None) -> DecryptionResult:
        """Decrypt data using Vault Transit engine"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            # Prepare decryption request
            decrypt_params = {
                'ciphertext': ciphertext,
                'mount_point': self.transit_mount_point
            }

            if context:
                # Context must be base64 encoded
                context_b64 = base64.b64encode(context.encode('utf-8')).decode('utf-8')
                decrypt_params['context'] = context_b64

            # Decrypt using Transit engine
            result = self.client.secrets.transit.decrypt_data(
                name=self.encryption_key_name,
                **decrypt_params
            )

            # Decode from base64
            plaintext_b64 = result['data']['plaintext']
            plaintext = base64.b64decode(plaintext_b64).decode('utf-8')
            key_version = result['data'].get('key_version', 1)

            logger.debug("data_decrypted",
                        key_name=self.encryption_key_name,
                        key_version=key_version,
                        has_context=bool(context))

            return DecryptionResult(
                plaintext=plaintext,
                key_version=key_version,
                context=context
            )

        except Exception as e:
            logger.error("decryption_failed", error=str(e))
            raise Exception(f"Decryption failed: {str(e)}")

    async def rotate_encryption_key(self) -> Dict[str, Any]:
        """Rotate the master encryption key"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            result = self.client.secrets.transit.rotate_key(
                name=self.encryption_key_name,
                mount_point=self.transit_mount_point
            )

            logger.info("encryption_key_rotated", key_name=self.encryption_key_name)

            # Get updated key info
            key_info = self.client.secrets.transit.read_key(
                name=self.encryption_key_name,
                mount_point=self.transit_mount_point
            )

            return {
                "key_name": self.encryption_key_name,
                "latest_version": key_info['data']['latest_version'],
                "min_decryption_version": key_info['data']['min_decryption_version'],
                "min_encryption_version": key_info['data']['min_encryption_version'],
                "rotation_time": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error("key_rotation_failed", error=str(e))
            raise Exception(f"Key rotation failed: {str(e)}")

    async def health_check(self) -> VaultHealthStatus:
        """Comprehensive Vault health check"""
        try:
            # Get health status
            health = self.client.sys.read_health_status(
                standby_ok=True,
                active_code=200,
                standby_code=200,
                dr_secondary_code=200,
                performance_standby_code=200
            )

            # Get additional cluster info if available
            cluster_info = {}
            try:
                leader = self.client.sys.read_leader_status()
                cluster_info.update(leader)
            except:
                pass

            # Check authentication status
            auth_ok = self._authenticated and self.client.is_authenticated()

            details = {
                "authenticated": auth_ok,
                "auth_method": self._auth_method,
                "cluster_info": cluster_info,
                "vault_url": self.vault_url,
                "namespace": self.vault_namespace
            }

            return VaultHealthStatus(
                healthy=not health.get('sealed', True) and auth_ok,
                sealed=health.get('sealed', True),
                standby=health.get('standby', False),
                replication_performance_mode=health.get('replication_performance_mode'),
                replication_dr_mode=health.get('replication_dr_mode'),
                server_time_utc=health.get('server_time_utc'),
                version=health.get('version'),
                cluster_name=health.get('cluster_name'),
                cluster_id=health.get('cluster_id'),
                details=details
            )

        except Exception as e:
            logger.error("vault_health_check_failed", error=str(e))
            return VaultHealthStatus(
                healthy=False,
                sealed=True,
                standby=False,
                replication_performance_mode=None,
                replication_dr_mode=None,
                server_time_utc=None,
                version=None,
                cluster_name=None,
                cluster_id=None,
                details={"error": str(e)}
            )

    async def create_api_key(self, request: APIKeyRequest) -> APIKeyResponse:
        """Create new API key and store in Vault"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            api_key_id = f"api_key_{secrets.token_urlsafe(16)}"
            api_key = f"vh_{secrets.token_urlsafe(32)}"
            api_key_hash = self._hash_api_key(api_key)

            now = datetime.utcnow()
            expires_at = None
            if request.expires_days:
                expires_at = now + timedelta(days=request.expires_days)

            # Store API key metadata
            key_data = {
                "api_key_id": api_key_id,
                "api_key_hash": api_key_hash,
                "name": request.name,
                "service_name": request.service_name,
                "permissions": [perm.value for perm in request.permissions],
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "active": True
            }

            # Store in Vault KV
            vault_path = f"{self.api_keys_path}/{api_key_id}".replace("secret/data/", "")
            self.client.secrets.kv.v2.create_or_update_secret(
                path=vault_path,
                secret=key_data
            )

            # Create hash-to-id mapping
            hash_mapping_path = f"{self.api_keys_path}/hashes/{api_key_hash}".replace("secret/data/", "")
            self.client.secrets.kv.v2.create_or_update_secret(
                path=hash_mapping_path,
                secret={"api_key_id": api_key_id}
            )

            logger.info("api_key_created_in_vault",
                       api_key_id=api_key_id,
                       service_name=request.service_name,
                       permissions_count=len(request.permissions))

            return APIKeyResponse(
                api_key_id=api_key_id,
                api_key=api_key,
                name=request.name,
                service_name=request.service_name,
                permissions=request.permissions,
                created_at=now,
                expires_at=expires_at
            )

        except Exception as e:
            logger.error("api_key_creation_failed", error=str(e))
            raise Exception(f"API key creation failed: {str(e)}")

    async def revoke_api_key(self, api_key_id: str) -> bool:
        """Revoke an API key by marking it as inactive"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            # Get current key data
            vault_path = f"{self.api_keys_path}/{api_key_id}".replace("secret/data/", "")
            result = self.client.secrets.kv.v2.read_secret_version(path=vault_path)
            key_data = result['data']['data']

            # Mark as inactive
            key_data['active'] = False
            key_data['revoked_at'] = datetime.utcnow().isoformat()

            # Update in Vault
            self.client.secrets.kv.v2.create_or_update_secret(
                path=vault_path,
                secret=key_data
            )

            logger.info("api_key_revoked", api_key_id=api_key_id)
            return True

        except Exception as e:
            logger.error("api_key_revocation_failed", api_key_id=api_key_id, error=str(e))
            return False

    def _hash_api_key(self, api_key: str) -> str:
        """Hash API key for secure storage"""
        import hashlib
        return hashlib.sha256(api_key.encode('utf-8')).hexdigest()

    async def store_secret(self, path: str, secret_data: Dict[str, Any]) -> bool:
        """Store a secret in Vault KV store"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            # Ensure path doesn't include the mount point prefix
            clean_path = path.replace("secret/data/", "").replace("secret/", "")

            self.client.secrets.kv.v2.create_or_update_secret(
                path=clean_path,
                secret=secret_data
            )

            logger.info("secret_stored", path=clean_path)
            return True

        except Exception as e:
            logger.error("secret_storage_failed", path=path, error=str(e))
            return False

    async def get_secret(self, path: str) -> Optional[Dict[str, Any]]:
        """Retrieve a secret from Vault KV store"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            # Ensure path doesn't include the mount point prefix
            clean_path = path.replace("secret/data/", "").replace("secret/", "")

            result = self.client.secrets.kv.v2.read_secret_version(path=clean_path)
            return result['data']['data']

        except hvac.exceptions.InvalidPath:
            return None
        except Exception as e:
            logger.error("secret_retrieval_failed", path=path, error=str(e))
            return None

    async def delete_secret(self, path: str) -> bool:
        """Delete a secret from Vault KV store"""
        if not self._authenticated:
            raise Exception("Vault client not authenticated")

        try:
            # Ensure path doesn't include the mount point prefix
            clean_path = path.replace("secret/data/", "").replace("secret/", "")

            self.client.secrets.kv.v2.delete_metadata_and_all_versions(path=clean_path)
            logger.info("secret_deleted", path=clean_path)
            return True

        except Exception as e:
            logger.error("secret_deletion_failed", path=path, error=str(e))
            return False


# Factory function for dependency injection
def get_production_vault_client() -> ProductionVaultClient:
    """Get production Vault client instance"""
    return ProductionVaultClient()


async def main():
    """Example usage and testing"""
    client = ProductionVaultClient()

    if await client.initialize():
        print("✅ Vault client initialized successfully")

        # Test health check
        health = await client.health_check()
        print(f"🔍 Vault health: {'✅ Healthy' if health.healthy else '❌ Unhealthy'}")
        print(f"   Sealed: {health.sealed}")
        print(f"   Version: {health.version}")

        # Test encryption
        try:
            encrypted = await client.encrypt_data("Hello, World!", context="test")
            print(f"🔐 Encryption test: {encrypted.ciphertext[:50]}...")

            decrypted = await client.decrypt_data(encrypted.ciphertext, context="test")
            print(f"🔓 Decryption test: {decrypted.plaintext}")

        except Exception as e:
            print(f"❌ Encryption test failed: {e}")
    else:
        print("❌ Failed to initialize Vault client")


if __name__ == "__main__":
    asyncio.run(main())