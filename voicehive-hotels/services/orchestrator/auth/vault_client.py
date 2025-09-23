"""
HashiCorp Vault client for API key management
"""

import hvac
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from auth_models import APIKeyRequest, APIKeyResponse, ServiceContext, Permission, AuthenticationError
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.vault_client")


class VaultClient:
    """HashiCorp Vault client for secure API key storage and management"""
    
    def __init__(self, vault_url: str, vault_token: Optional[str] = None):
        self.vault_url = vault_url
        self.client = hvac.Client(url=vault_url)
        
        if vault_token:
            self.client.token = vault_token
        
        # Vault paths
        self.api_keys_path = "secret/api-keys"
        self.service_configs_path = "secret/service-configs"
    
    async def initialize(self):
        """Initialize Vault client and verify connection"""
        try:
            # Check if Vault is accessible
            if not self.client.is_authenticated():
                logger.warning("vault_not_authenticated", url=self.vault_url)
                # In development, we might want to continue without Vault
                return False
            
            # Ensure KV v2 secrets engine is enabled
            try:
                self.client.secrets.kv.v2.create_or_update_secret(
                    path="test",
                    secret={"test": "value"}
                )
                self.client.secrets.kv.v2.delete_metadata_and_all_versions(path="test")
                logger.info("vault_initialized", url=self.vault_url)
                return True
            except Exception as e:
                logger.error("vault_kv_engine_error", error=str(e))
                return False
                
        except Exception as e:
            logger.error("vault_initialization_error", error=str(e))
            return False
    
    def _generate_api_key(self) -> str:
        """Generate a secure API key"""
        # Generate a 32-byte random key and encode as hex
        return f"vhh_{secrets.token_urlsafe(32)}"
    
    def _hash_api_key(self, api_key: str) -> str:
        """Hash API key for storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()
    
    async def create_api_key(self, request: APIKeyRequest) -> APIKeyResponse:
        """Create a new API key and store it in Vault"""
        try:
            api_key_id = str(uuid.uuid4())
            api_key = self._generate_api_key()
            api_key_hash = self._hash_api_key(api_key)
            
            now = datetime.utcnow()
            expires_at = None
            if request.expires_days:
                expires_at = now + timedelta(days=request.expires_days)
            
            # Store API key metadata in Vault
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
            
            # Store in Vault
            vault_path = f"{self.api_keys_path}/{api_key_id}"
            self.client.secrets.kv.v2.create_or_update_secret(
                path=vault_path,
                secret=key_data
            )
            
            # Also create a hash-to-id mapping for quick lookups
            hash_mapping_path = f"{self.api_keys_path}/hashes/{api_key_hash}"
            self.client.secrets.kv.v2.create_or_update_secret(
                path=hash_mapping_path,
                secret={"api_key_id": api_key_id}
            )
            
            logger.info(
                "api_key_created",
                api_key_id=api_key_id,
                service_name=request.service_name,
                permissions=len(request.permissions)
            )
            
            return APIKeyResponse(
                api_key_id=api_key_id,
                api_key=api_key,  # Only returned once
                name=request.name,
                service_name=request.service_name,
                permissions=request.permissions,
                created_at=now,
                expires_at=expires_at
            )
            
        except Exception as e:
            logger.error("api_key_creation_error", error=str(e))
            raise AuthenticationError(f"Failed to create API key: {str(e)}")
    
    async def validate_api_key(self, api_key: str) -> ServiceContext:
        """Validate API key and return service context"""
        try:
            api_key_hash = self._hash_api_key(api_key)
            
            # Look up API key ID by hash
            hash_mapping_path = f"{self.api_keys_path}/hashes/{api_key_hash}"
            try:
                hash_response = self.client.secrets.kv.v2.read_secret_version(
                    path=hash_mapping_path
                )
                api_key_id = hash_response["data"]["data"]["api_key_id"]
            except Exception:
                raise AuthenticationError("Invalid API key")
            
            # Get API key metadata
            vault_path = f"{self.api_keys_path}/{api_key_id}"
            response = self.client.secrets.kv.v2.read_secret_version(path=vault_path)
            key_data = response["data"]["data"]
            
            # Check if key is active
            if not key_data.get("active", False):
                raise AuthenticationError("API key is disabled")
            
            # Check expiration
            expires_at_str = key_data.get("expires_at")
            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.utcnow() > expires_at:
                    raise AuthenticationError("API key has expired")
            
            # Get rate limits for service
            rate_limits = await self._get_service_rate_limits(key_data["service_name"])
            
            service_context = ServiceContext(
                service_name=key_data["service_name"],
                api_key_id=api_key_id,
                permissions=[Permission(perm) for perm in key_data["permissions"]],
                rate_limits=rate_limits,
                expires_at=datetime.fromisoformat(expires_at_str) if expires_at_str else None
            )
            
            logger.info(
                "api_key_validated",
                api_key_id=api_key_id,
                service_name=key_data["service_name"]
            )
            
            return service_context
            
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error("api_key_validation_error", error=str(e))
            raise AuthenticationError("API key validation failed")
    
    async def revoke_api_key(self, api_key_id: str):
        """Revoke an API key"""
        try:
            vault_path = f"{self.api_keys_path}/{api_key_id}"
            
            # Get current data
            response = self.client.secrets.kv.v2.read_secret_version(path=vault_path)
            key_data = response["data"]["data"]
            
            # Mark as inactive
            key_data["active"] = False
            key_data["revoked_at"] = datetime.utcnow().isoformat()
            
            # Update in Vault
            self.client.secrets.kv.v2.create_or_update_secret(
                path=vault_path,
                secret=key_data
            )
            
            logger.info("api_key_revoked", api_key_id=api_key_id)
            
        except Exception as e:
            logger.error("api_key_revocation_error", api_key_id=api_key_id, error=str(e))
            raise AuthenticationError(f"Failed to revoke API key: {str(e)}")
    
    async def list_api_keys(self, service_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List API keys, optionally filtered by service"""
        try:
            # List all API key IDs
            response = self.client.secrets.kv.v2.list_secrets(path=self.api_keys_path)
            key_ids = response["data"]["keys"]
            
            api_keys = []
            for key_id in key_ids:
                if key_id.endswith("/"):  # Skip directories like "hashes/"
                    continue
                    
                try:
                    vault_path = f"{self.api_keys_path}/{key_id}"
                    key_response = self.client.secrets.kv.v2.read_secret_version(path=vault_path)
                    key_data = key_response["data"]["data"]
                    
                    # Filter by service if specified
                    if service_name and key_data.get("service_name") != service_name:
                        continue
                    
                    # Don't include the actual API key hash
                    safe_key_data = {k: v for k, v in key_data.items() if k != "api_key_hash"}
                    api_keys.append(safe_key_data)
                    
                except Exception as e:
                    logger.warning("failed_to_read_api_key", key_id=key_id, error=str(e))
                    continue
            
            return api_keys
            
        except Exception as e:
            logger.error("api_key_listing_error", error=str(e))
            raise AuthenticationError(f"Failed to list API keys: {str(e)}")
    
    async def _get_service_rate_limits(self, service_name: str) -> Dict[str, int]:
        """Get rate limits for a service"""
        try:
            config_path = f"{self.service_configs_path}/{service_name}"
            response = self.client.secrets.kv.v2.read_secret_version(path=config_path)
            config_data = response["data"]["data"]
            return config_data.get("rate_limits", {
                "requests_per_minute": 100,
                "requests_per_hour": 1000,
                "requests_per_day": 10000
            })
        except Exception:
            # Return default rate limits if service config not found
            return {
                "requests_per_minute": 100,
                "requests_per_hour": 1000,
                "requests_per_day": 10000
            }
    
    async def update_service_config(self, service_name: str, config: Dict[str, Any]):
        """Update service configuration"""
        try:
            config_path = f"{self.service_configs_path}/{service_name}"
            self.client.secrets.kv.v2.create_or_update_secret(
                path=config_path,
                secret=config
            )
            logger.info("service_config_updated", service_name=service_name)
        except Exception as e:
            logger.error("service_config_update_error", service_name=service_name, error=str(e))
            raise AuthenticationError(f"Failed to update service config: {str(e)}")


class MockVaultClient(VaultClient):
    """Mock Vault client for development/testing"""
    
    def __init__(self):
        self.api_keys = {}
        self.service_configs = {}
        logger.info("mock_vault_client_initialized")
    
    async def initialize(self):
        """Mock initialization always succeeds"""
        return True
    
    async def create_api_key(self, request: APIKeyRequest) -> APIKeyResponse:
        """Create API key in memory"""
        api_key_id = str(uuid.uuid4())
        api_key = self._generate_api_key()
        
        now = datetime.utcnow()
        expires_at = None
        if request.expires_days:
            expires_at = now + timedelta(days=request.expires_days)
        
        key_data = {
            "api_key": api_key,
            "name": request.name,
            "service_name": request.service_name,
            "permissions": request.permissions,
            "created_at": now,
            "expires_at": expires_at,
            "active": True
        }
        
        self.api_keys[api_key_id] = key_data
        
        return APIKeyResponse(
            api_key_id=api_key_id,
            api_key=api_key,
            name=request.name,
            service_name=request.service_name,
            permissions=request.permissions,
            created_at=now,
            expires_at=expires_at
        )
    
    async def validate_api_key(self, api_key: str) -> ServiceContext:
        """Validate API key from memory"""
        for api_key_id, key_data in self.api_keys.items():
            if key_data["api_key"] == api_key and key_data["active"]:
                # Check expiration
                if key_data["expires_at"] and datetime.utcnow() > key_data["expires_at"]:
                    raise AuthenticationError("API key has expired")
                
                return ServiceContext(
                    service_name=key_data["service_name"],
                    api_key_id=api_key_id,
                    permissions=key_data["permissions"],
                    rate_limits={"requests_per_minute": 100, "requests_per_hour": 1000},
                    expires_at=key_data["expires_at"]
                )
        
        raise AuthenticationError("Invalid API key")
    
    async def revoke_api_key(self, api_key_id: str):
        """Revoke API key in memory"""
        if api_key_id in self.api_keys:
            self.api_keys[api_key_id]["active"] = False
    
    async def list_api_keys(self, service_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """List API keys from memory"""
        result = []
        for api_key_id, key_data in self.api_keys.items():
            if service_name and key_data["service_name"] != service_name:
                continue
            
            # Don't include the actual API key
            safe_data = {k: v for k, v in key_data.items() if k != "api_key"}
            safe_data["api_key_id"] = api_key_id
            result.append(safe_data)
        
        return result