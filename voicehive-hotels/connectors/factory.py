"""
VoiceHive Hotels - PMS Connector Factory
Dynamic connector selection and initialization with capability validation
"""

import logging
import importlib
import inspect
import os
from typing import Dict, Type, Optional, List, Any
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import yaml

from connectors.contracts import PMSConnector, PMSError, NotFoundError, BaseConnector
from connectors.utils.vault_client import (
    get_vault_client,
    VaultError,
    DevelopmentVaultClient,
)

logger = logging.getLogger(__name__)


class ConnectorStatus(Enum):
    """Connector availability status"""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"


@dataclass
class ConnectorMetadata:
    """Metadata about a PMS connector"""

    vendor: str
    name: str
    version: str
    status: ConnectorStatus
    capabilities: Dict[str, bool]
    regions: List[str]
    rate_limits: Dict[str, int]
    authentication: str  # oauth2, api_key, basic, certificate
    documentation_url: Optional[str] = None
    support_contact: Optional[str] = None


class ConnectorRegistry:
    """Registry of available PMS connectors"""

    def __init__(self):
        self._connectors: Dict[str, Type[PMSConnector]] = {}
        self._metadata: Dict[str, ConnectorMetadata] = {}
        self._capability_matrix: Dict[str, Any] = {}
        self._load_capability_matrix()
        self._discover_connectors()

    def _load_capability_matrix(self):
        """Load capability matrix from YAML configuration"""
        matrix_path = Path(__file__).parent / "capability_matrix.yaml"
        if matrix_path.exists():
            with open(matrix_path, "r") as f:
                self._capability_matrix = yaml.safe_load(f)
                logger.info(
                    f"Loaded capability matrix with {len(self._capability_matrix.get('vendors', {}))} vendors"
                )
        else:
            logger.warning("Capability matrix not found, using defaults")
            self._capability_matrix = {"vendors": {}}

    def _discover_connectors(self):
        """Automatically discover and register connectors from adapters directory"""
        adapters_path = Path(__file__).parent / "adapters"
        if not adapters_path.exists():
            logger.warning("Adapters directory not found")
            return

        for vendor_dir in adapters_path.iterdir():
            if vendor_dir.is_dir() and not vendor_dir.name.startswith("_"):
                try:
                    # Try to import connector module
                    module_name = f"connectors.adapters.{vendor_dir.name}.connector"
                    module = importlib.import_module(module_name)

                    # Find PMSConnector implementation
                    for name, obj in inspect.getmembers(module):
                        if (
                            inspect.isclass(obj)
                            and issubclass(obj, BaseConnector)
                            and obj is not BaseConnector
                        ):
                            # Register the connector
                            vendor_name = vendor_dir.name
                            self._register_connector(vendor_name, obj)
                            logger.info(
                                f"Discovered connector: {vendor_name} ({obj.__name__})"
                            )

                except Exception as e:
                    logger.error(
                        f"Failed to load connector from {vendor_dir.name}: {e}"
                    )

    def _register_connector(self, vendor: str, connector_class: Type[PMSConnector]):
        """Register a connector with its metadata"""
        self._connectors[vendor] = connector_class

        # Load metadata from capability matrix or connector
        vendor_config = self._capability_matrix.get("vendors", {}).get(vendor, {})

        # Create metadata
        metadata = ConnectorMetadata(
            vendor=vendor,
            name=getattr(connector_class, "DISPLAY_NAME", vendor.title()),
            version=getattr(connector_class, "VERSION", "1.0.0"),
            status=ConnectorStatus(vendor_config.get("status", "available")),
            capabilities=vendor_config.get("capabilities", {}),
            regions=vendor_config.get("regions", ["eu-west-1"]),
            rate_limits=vendor_config.get("rate_limits", {"requests_per_minute": 60}),
            authentication=vendor_config.get("authentication", "api_key"),
            documentation_url=vendor_config.get("documentation_url"),
            support_contact=vendor_config.get("support_contact"),
        )

        self._metadata[vendor] = metadata

    def register(
        self,
        vendor: str,
        connector_class: Type[PMSConnector],
        metadata: Optional[ConnectorMetadata] = None,
    ):
        """Manually register a connector"""
        self._connectors[vendor] = connector_class

        if metadata:
            self._metadata[vendor] = metadata
        else:
            # Use defaults from capability matrix
            self._register_connector(vendor, connector_class)

    def get_connector_class(self, vendor: str) -> Type[PMSConnector]:
        """Get connector class by vendor name"""
        if vendor not in self._connectors:
            raise NotFoundError(f"Connector not found for vendor: {vendor}")
        return self._connectors[vendor]

    def get_metadata(self, vendor: str) -> ConnectorMetadata:
        """Get connector metadata"""
        if vendor not in self._metadata:
            raise NotFoundError(f"Metadata not found for vendor: {vendor}")
        return self._metadata[vendor]

    def list_vendors(self, status: Optional[ConnectorStatus] = None) -> List[str]:
        """List all registered vendors, optionally filtered by status"""
        if status:
            return [
                vendor
                for vendor, meta in self._metadata.items()
                if meta.status == status
            ]
        return list(self._connectors.keys())

    def get_capability_matrix(self) -> Dict[str, Dict[str, bool]]:
        """Get capability matrix for all vendors"""
        return {vendor: meta.capabilities for vendor, meta in self._metadata.items()}

    def find_vendors_with_capability(self, capability: str) -> List[str]:
        """Find vendors that support a specific capability"""
        return [
            vendor
            for vendor, meta in self._metadata.items()
            if meta.capabilities.get(capability, False)
        ]


# Global registry instance
_registry = ConnectorRegistry()


class ConnectorFactory:
    """Factory for creating PMS connector instances"""

    def __init__(
        self, registry: Optional[ConnectorRegistry] = None, use_vault: bool = True
    ):
        self.registry = registry or _registry
        self._instances: Dict[str, PMSConnector] = {}
        self.use_vault = use_vault

        # Initialize Vault client if enabled
        if self.use_vault:
            try:
                # Use development client if in dev mode
                if os.getenv("VOICEHIVE_ENV", "production") == "development":
                    self.vault_client = DevelopmentVaultClient()
                else:
                    self.vault_client = get_vault_client()
            except Exception as e:
                logger.warning(
                    f"Failed to initialize Vault client: {e}. Falling back to config-based credentials."
                )
                self.vault_client = None
        else:
            self.vault_client = None

    def create(self, vendor: str, config: Dict[str, Any]) -> PMSConnector:
        """Create a connector instance for the specified vendor"""
        # Check if connector exists
        connector_class = self.registry.get_connector_class(vendor)
        metadata = self.registry.get_metadata(vendor)

        # Check if connector is available
        if metadata.status == ConnectorStatus.UNAVAILABLE:
            raise PMSError(f"Connector {vendor} is currently unavailable")

        if metadata.status == ConnectorStatus.MAINTENANCE:
            logger.warning(f"Connector {vendor} is in maintenance mode")

        # Merge Vault credentials with provided config
        final_config = self._prepare_config(vendor, config)

        # Validate required configuration
        self._validate_config(vendor, final_config)

        # Create instance
        instance_key = f"{vendor}:{final_config.get('hotel_id', 'default')}"

        if instance_key not in self._instances:
            try:
                instance = connector_class(final_config)
                self._instances[instance_key] = instance
                logger.info(f"Created connector instance: {instance_key}")
            except Exception as e:
                logger.error(f"Failed to create connector {vendor}: {e}")
                raise PMSError(f"Failed to initialize {vendor} connector: {str(e)}")

        return self._instances[instance_key]

    def _prepare_config(self, vendor: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare configuration by merging Vault credentials with provided config

        Args:
            vendor: PMS vendor name
            config: User-provided configuration

        Returns:
            Complete configuration with credentials
        """
        final_config = config.copy()

        # Skip Vault if disabled or client not available
        if not self.use_vault or not self.vault_client:
            return final_config

        # Get hotel ID from config
        hotel_id = config.get("hotel_id", "default")

        try:
            # Fetch credentials from Vault
            vault_creds = self.vault_client.read_pms_credentials(vendor, hotel_id)

            # Merge Vault credentials (Vault takes precedence for security)
            for key, value in vault_creds.items():
                if key not in final_config or final_config[key] is None:
                    final_config[key] = value
                    logger.debug(f"Using credential from Vault: {key}")

            logger.info(
                f"Successfully loaded credentials from Vault for {vendor}/{hotel_id}"
            )

        except VaultError as e:
            # Log warning but continue with config-based credentials
            logger.warning(
                f"Failed to fetch credentials from Vault: {e}. Using config-based credentials."
            )
        except Exception as e:
            logger.error(f"Unexpected error fetching from Vault: {e}")

        return final_config

    def _validate_config(self, vendor: str, config: Dict[str, Any]):
        """Validate configuration for a vendor"""
        metadata = self.registry.get_metadata(vendor)

        # Check authentication requirements
        if metadata.authentication == "oauth2":
            required = ["client_id", "client_secret", "token_url"]
        elif metadata.authentication == "api_key":
            required = ["api_key"]
        elif metadata.authentication == "basic":
            required = ["username", "password"]
        elif metadata.authentication == "certificate":
            required = ["cert_path", "key_path"]
        else:
            required = []

        # Add common requirements
        required.extend(["base_url", "hotel_id"])

        # Check for missing configuration
        missing = [key for key in required if key not in config]
        if missing:
            raise ValueError(f"Missing required configuration for {vendor}: {missing}")

    def get_instance(self, vendor: str, hotel_id: str) -> Optional[PMSConnector]:
        """Get existing connector instance"""
        instance_key = f"{vendor}:{hotel_id}"
        return self._instances.get(instance_key)

    def close_all(self):
        """Close all connector instances"""
        for instance_key, connector in self._instances.items():
            try:
                if hasattr(connector, "close"):
                    connector.close()
                logger.info(f"Closed connector: {instance_key}")
            except Exception as e:
                logger.error(f"Error closing connector {instance_key}: {e}")

        self._instances.clear()


# Convenience functions
def get_connector(vendor: str, config: Dict[str, Any]) -> PMSConnector:
    """Get a connector instance for the specified vendor"""
    factory = ConnectorFactory()
    return factory.create(vendor, config)


def list_available_connectors() -> List[str]:
    """List all available connector vendors"""
    return _registry.list_vendors(ConnectorStatus.AVAILABLE)


def get_connector_metadata(vendor: str) -> ConnectorMetadata:
    """Get metadata for a specific vendor"""
    return _registry.get_metadata(vendor)


def get_capability_matrix() -> Dict[str, Dict[str, bool]]:
    """Get the capability matrix for all vendors"""
    return _registry.get_capability_matrix()


def find_connectors_with_capability(capability: str) -> List[str]:
    """Find all connectors that support a specific capability"""
    return _registry.find_vendors_with_capability(capability)


# Allow manual registration for testing
def register_connector(
    vendor: str,
    connector_class: Type[PMSConnector],
    metadata: Optional[ConnectorMetadata] = None,
):
    """Register a custom connector"""
    _registry.register(vendor, connector_class, metadata)
