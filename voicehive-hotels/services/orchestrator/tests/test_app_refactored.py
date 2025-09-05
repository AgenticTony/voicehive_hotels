"""
Tests for the refactored app structure
Ensures all modules and routers are properly integrated
"""

import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_app_imports_successfully():
    """Test that the refactored app imports without errors"""
    try:
        from app import app
        assert app is not None
        assert app.title == "VoiceHive Hotels Orchestrator"
    except ImportError as e:
        pytest.fail(f"Failed to import app: {e}")


def test_routers_included():
    """Test that all routers are properly included"""
    from app import app
    
    # Get all routes
    routes = [route.path for route in app.routes]
    
    # Check health endpoints
    assert "/health" in routes or any("/health" in r for r in routes)
    
    # Check webhook endpoints
    assert any("webhook" in r for r in routes)
    assert "/call/event" in routes
    
    # Check GDPR endpoints  
    assert any("gdpr" in r for r in routes)
    
    # Check call endpoints
    assert "/v1/call/start" in routes
    
    # Check metrics endpoint
    assert "/metrics" in routes
    
    # Check root endpoint
    assert "/" in routes


def test_root_endpoint():
    """Test the root endpoint returns expected response"""
    from app import app
    
    client = TestClient(app)
    response = client.get("/")
    
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "VoiceHive Hotels Orchestrator"
    assert data["version"] == "1.0.0"
    assert "region" in data
    assert data["docs"] == "/docs"


def test_metrics_endpoint_exists():
    """Test that metrics endpoint is available"""
    from app import app
    
    client = TestClient(app)
    response = client.get("/metrics")
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"


def test_healthz_endpoint():
    """Test the healthz endpoint"""
    from app import app
    
    client = TestClient(app)
    response = client.get("/healthz")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "region" in data
    assert "version" in data
    assert "gdpr_compliant" in data
    assert "services" in data


def test_app_middleware():
    """Test that CORS middleware is properly configured"""
    from app import app
    
    # Check that middleware is added
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in str(middleware_classes)


def test_error_handler():
    """Test that global error handler is registered"""
    from app import app
    
    # Check exception handlers
    assert Exception in app.exception_handlers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
