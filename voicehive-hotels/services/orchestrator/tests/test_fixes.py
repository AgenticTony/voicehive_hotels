"""
Tests for P0/P1 fixes:
- Renamed pii_redactions_total metric
- JSON storage in Redis
- No duplicate metrics endpoints
"""

import pytest
import json
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_pii_redactions_total_metric_exists():
    """Test that pii_redactions_total metric is properly defined"""
    from metrics import pii_redactions_total
    
    # Verify it's a Counter
    assert hasattr(pii_redactions_total, '_metrics')
    # Note: Prometheus client doesn't automatically append _total to the internal name
    # It's added when the metric is collected/exposed
    assert pii_redactions_total._name == 'voicehive_pii_redactions'
    assert pii_redactions_total._documentation == 'PII redactions performed'


def test_no_duplicate_metrics_endpoint():
    """Test that metrics are only exposed at /metrics, not /health/metrics"""
    # This test verifies the /health/metrics endpoint was removed
    # We check by reading the health.py file content
    import pathlib
    
    health_content = pathlib.Path("health.py").read_text()
    
    # Should not contain a metrics endpoint definition
    assert '@router.get("/metrics"' not in health_content
    assert 'def metrics()' not in health_content
    
    # Should have a comment about metrics being at root
    assert 'metrics are exposed at the root /metrics endpoint' in health_content


@pytest.mark.asyncio
async def test_call_data_stored_as_json():
    """Test that call data is stored as JSON in Redis"""
    from routers.call import start_call
    from models import CallStartRequest
    
    # Mock dependencies
    mock_redis = AsyncMock()
    mock_api_key = "vh_test_key"
    
    request = CallStartRequest(
        caller_id="+1234567890",
        hotel_id="hotel_123",
        language="en-US"
    )
    
    # Capture what gets stored
    stored_data = None
    
    async def capture_setex(key, ttl, data):
        nonlocal stored_data
        stored_data = data
        
    mock_redis.setex = capture_setex
    
    # Call the endpoint function directly
    with patch('routers.call.verify_api_key', return_value=mock_api_key):
        with patch('routers.call.get_redis', return_value=mock_redis):
            # Import the function to test
            from routers.call import router
            
            # Get the actual endpoint function
            endpoint = None
            for route in router.routes:
                if route.path == "/start" and hasattr(route, 'endpoint'):
                    endpoint = route.endpoint
                    break
            
            assert endpoint is not None
            
            # Call with mocked dependencies
            await endpoint(request, mock_api_key, mock_redis)
    
    # Verify data was stored as JSON
    assert stored_data is not None
    
    # Should be valid JSON
    parsed = json.loads(stored_data)
    assert parsed["hotel_id"] == "hotel_123"
    assert parsed["language"] == "en-US"
    assert parsed["schema_version"] == "1.0"
    assert "caller_id" in parsed  # Should be hashed
    assert parsed["caller_id"] != "+1234567890"  # Should not be plaintext


@pytest.mark.asyncio
async def test_consent_data_stored_as_json():
    """Test that consent data is stored as JSON in Redis"""
    # Mock dependencies
    mock_redis = AsyncMock()
    mock_api_key = "vh_test_key"
    
    # Capture what gets stored
    stored_data = None
    
    async def capture_setex(key, ttl, data):
        nonlocal stored_data
        stored_data = data
        
    mock_redis.setex = capture_setex
    
    # Import after mocking
    from routers.gdpr import router
    
    # Get the consent endpoint
    endpoint = None
    for route in router.routes:
        if route.path == "/consent" and hasattr(route, 'endpoint'):
            endpoint = route.endpoint
            break
    
    assert endpoint is not None
    
    # Call with test data
    await endpoint(
        hotel_id="hotel_123",
        purpose="voice_processing", 
        consent=True,
        api_key=mock_api_key,
        redis_client=mock_redis
    )
    
    # Verify data was stored as JSON
    assert stored_data is not None
    
    # Should be valid JSON
    parsed = json.loads(stored_data)
    assert parsed["hotel_id"] == "hotel_123"
    assert parsed["purpose"] == "voice_processing"
    assert parsed["consent"] is True
    assert parsed["schema_version"] == "1.0"


def test_trusted_host_middleware_configured():
    """Test that TrustedHostMiddleware is configured"""
    from app import app
    
    # Check middleware stack
    middleware_names = []
    for middleware in app.user_middleware:
        if hasattr(middleware, 'cls'):
            middleware_names.append(middleware.cls.__name__)
    
    assert "TrustedHostMiddleware" in str(middleware_names)


def test_uvicorn_uses_env_variables():
    """Test that uvicorn configuration uses environment variables"""
    # This is a code inspection test
    import app
    
    # Check that the main block exists and uses env vars
    app_source = Path(app.__file__).read_text()
    
    # Verify the pattern exists
    assert 'os.getenv("HOST"' in app_source
    assert 'os.getenv("PORT"' in app_source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
