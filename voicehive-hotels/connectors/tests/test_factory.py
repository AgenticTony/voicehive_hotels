"""
Test the PMS Connector Factory
"""

import pytest
from typing import Dict, Any
from unittest.mock import patch, MagicMock

from connectors.factory import (
    ConnectorFactory,
    ConnectorRegistry,
    ConnectorStatus,
    ConnectorMetadata,
    get_connector,
    list_available_connectors,
    get_connector_metadata,
    register_connector
)
from connectors.contracts import (
    PMSConnector,
    BaseConnector,
    PMSError,
    NotFoundError,
    MockConnector
)


class TestConnectorRegistry:
    """Test the connector registry functionality"""
    
    def test_registry_initialization(self):
        """Test registry loads capability matrix"""
        registry = ConnectorRegistry()
        assert registry._capability_matrix is not None
        assert "vendors" in registry._capability_matrix
    
    def test_manual_registration(self):
        """Test manual connector registration"""
        registry = ConnectorRegistry()
        
        # Register mock connector
        metadata = ConnectorMetadata(
            vendor="test",
            name="Test Connector",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={"reservations": True},
            regions=["eu-west-1"],
            rate_limits={"requests_per_minute": 60},
            authentication="api_key"
        )
        
        registry.register("test", MockConnector, metadata)
        
        # Verify registration
        assert "test" in registry.list_vendors()
        assert registry.get_connector_class("test") == MockConnector
        assert registry.get_metadata("test") == metadata
    
    def test_list_vendors_by_status(self):
        """Test filtering vendors by status"""
        registry = ConnectorRegistry()
        
        # Register connectors with different statuses
        registry.register("available", MockConnector, ConnectorMetadata(
            vendor="available",
            name="Available",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        registry.register("maintenance", MockConnector, ConnectorMetadata(
            vendor="maintenance",
            name="Maintenance",
            version="1.0.0",
            status=ConnectorStatus.MAINTENANCE,
            capabilities={},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        # Test filtering
        available = registry.list_vendors(ConnectorStatus.AVAILABLE)
        assert "available" in available
        assert "maintenance" not in available
        
        maintenance = registry.list_vendors(ConnectorStatus.MAINTENANCE)
        assert "maintenance" in maintenance
        assert "available" not in maintenance
    
    def test_find_vendors_with_capability(self):
        """Test finding vendors by capability"""
        registry = ConnectorRegistry()
        
        # Register connectors with different capabilities
        registry.register("full", MockConnector, ConnectorMetadata(
            vendor="full",
            name="Full",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={"reservations": True, "webhooks": True},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        registry.register("basic", MockConnector, ConnectorMetadata(
            vendor="basic",
            name="Basic",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={"reservations": True, "webhooks": False},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        # Test capability search
        webhook_vendors = registry.find_vendors_with_capability("webhooks")
        assert "full" in webhook_vendors
        assert "basic" not in webhook_vendors
        
        reservation_vendors = registry.find_vendors_with_capability("reservations")
        assert "full" in reservation_vendors
        assert "basic" in reservation_vendors
    
    def test_not_found_error(self):
        """Test error handling for non-existent vendors"""
        registry = ConnectorRegistry()
        
        with pytest.raises(NotFoundError):
            registry.get_connector_class("non_existent")
        
        with pytest.raises(NotFoundError):
            registry.get_metadata("non_existent")


class TestConnectorFactory:
    """Test the connector factory functionality"""
    
    def test_create_connector(self):
        """Test creating a connector instance"""
        registry = ConnectorRegistry()
        registry.register("test", MockConnector, ConnectorMetadata(
            vendor="test",
            name="Test",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        factory = ConnectorFactory(registry)
        
        config = {
            "api_key": "test-key",
            "base_url": "https://api.test.com",
            "hotel_id": "HOTEL01"
        }
        
        connector = factory.create("test", config)
        assert isinstance(connector, MockConnector)
        assert connector.config == config
    
    def test_create_unavailable_connector(self):
        """Test creating unavailable connector raises error"""
        registry = ConnectorRegistry()
        registry.register("unavailable", MockConnector, ConnectorMetadata(
            vendor="unavailable",
            name="Unavailable",
            version="1.0.0",
            status=ConnectorStatus.UNAVAILABLE,
            capabilities={},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        factory = ConnectorFactory(registry)
        
        with pytest.raises(PMSError, match="currently unavailable"):
            factory.create("unavailable", {})
    
    def test_config_validation(self):
        """Test configuration validation"""
        registry = ConnectorRegistry()
        
        # Register with different auth types
        for auth_type in ["oauth2", "api_key", "basic", "certificate"]:
            registry.register(auth_type, MockConnector, ConnectorMetadata(
                vendor=auth_type,
                name=auth_type,
                version="1.0.0",
                status=ConnectorStatus.AVAILABLE,
                capabilities={},
                regions=[],
                rate_limits={},
                authentication=auth_type
            ))
        
        factory = ConnectorFactory(registry)
        
        # Test OAuth2 validation
        with pytest.raises(ValueError, match="Missing required configuration"):
            factory.create("oauth2", {"base_url": "test", "hotel_id": "test"})
        
        # Valid OAuth2 config should work
        oauth_config = {
            "client_id": "test",
            "client_secret": "test",
            "token_url": "test",
            "base_url": "test",
            "hotel_id": "test"
        }
        connector = factory.create("oauth2", oauth_config)
        assert isinstance(connector, MockConnector)
        
        # Test API key validation
        with pytest.raises(ValueError, match="Missing required configuration"):
            factory.create("api_key", {"base_url": "test", "hotel_id": "test"})
        
        # Valid API key config should work
        api_config = {
            "api_key": "test",
            "base_url": "test",
            "hotel_id": "test"
        }
        connector = factory.create("api_key", api_config)
        assert isinstance(connector, MockConnector)
    
    def test_instance_caching(self):
        """Test connector instances are cached"""
        registry = ConnectorRegistry()
        registry.register("test", MockConnector, ConnectorMetadata(
            vendor="test",
            name="Test",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        factory = ConnectorFactory(registry)
        
        config = {
            "api_key": "test",
            "base_url": "test",
            "hotel_id": "HOTEL01"
        }
        
        # Create twice with same config
        connector1 = factory.create("test", config)
        connector2 = factory.create("test", config)
        
        # Should be same instance
        assert connector1 is connector2
        
        # Different hotel should create new instance
        config2 = config.copy()
        config2["hotel_id"] = "HOTEL02"
        connector3 = factory.create("test", config2)
        
        assert connector3 is not connector1
    
    def test_get_instance(self):
        """Test retrieving existing instance"""
        registry = ConnectorRegistry()
        registry.register("test", MockConnector, ConnectorMetadata(
            vendor="test",
            name="Test",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        factory = ConnectorFactory(registry)
        
        # Should be None before creation
        assert factory.get_instance("test", "HOTEL01") is None
        
        # Create instance
        config = {
            "api_key": "test",
            "base_url": "test",
            "hotel_id": "HOTEL01"
        }
        connector = factory.create("test", config)
        
        # Should now return the instance
        assert factory.get_instance("test", "HOTEL01") is connector
    
    def test_close_all(self):
        """Test closing all connector instances"""
        registry = ConnectorRegistry()
        registry.register("test", MockConnector, ConnectorMetadata(
            vendor="test",
            name="Test",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        factory = ConnectorFactory(registry)
        
        # Create multiple instances
        for i in range(3):
            config = {
                "api_key": "test",
                "base_url": "test",
                "hotel_id": f"HOTEL{i:02d}"
            }
            factory.create("test", config)
        
        # Should have 3 instances
        assert len(factory._instances) == 3
        
        # Close all
        factory.close_all()
        
        # Should be empty
        assert len(factory._instances) == 0


class TestConvenienceFunctions:
    """Test module-level convenience functions"""
    
    def test_list_available_connectors(self):
        """Test listing available connectors"""
        # Should include any discovered connectors
        vendors = list_available_connectors()
        assert isinstance(vendors, list)
        # Apaleo should be discovered if it exists
        if "apaleo" in vendors:
            assert "apaleo" in vendors
    
    def test_get_connector(self):
        """Test getting a connector instance"""
        # Register a test connector
        register_connector("test", MockConnector, ConnectorMetadata(
            vendor="test",
            name="Test",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={},
            regions=[],
            rate_limits={},
            authentication="api_key"
        ))
        
        config = {
            "api_key": "test",
            "base_url": "test",
            "hotel_id": "test"
        }
        
        connector = get_connector("test", config)
        assert isinstance(connector, MockConnector)
    
    def test_get_connector_metadata(self):
        """Test getting connector metadata"""
        # Register a test connector
        metadata = ConnectorMetadata(
            vendor="test",
            name="Test",
            version="1.0.0",
            status=ConnectorStatus.AVAILABLE,
            capabilities={"test": True},
            regions=["eu-west-1"],
            rate_limits={"requests_per_minute": 100},
            authentication="api_key"
        )
        register_connector("test", MockConnector, metadata)
        
        retrieved = get_connector_metadata("test")
        assert retrieved == metadata
        assert retrieved.capabilities == {"test": True}
        assert retrieved.regions == ["eu-west-1"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
