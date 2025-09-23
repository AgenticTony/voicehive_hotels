"""
Integration test configuration and fixtures
"""

import pytest
import asyncio
import os
from typing import AsyncGenerator, Dict, Any
from unittest.mock import AsyncMock, MagicMock
import httpx
from fastapi.testclient import TestClient
from httpx import AsyncClient

# Import the main app and dependencies
from app import app
from auth_models import UserContext, ServiceContext
from jwt_service import JWTService
from vault_client import MockVaultClient
from resilience_manager import ResilienceManager
from resilience_config import ResilienceConfig
from rate_limiter import RateLimiter, RateLimitConfig
from circuit_breaker import CircuitBreaker, CircuitBreakerConfig


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def mock_redis():
    """Mock Redis client for integration tests"""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock()
    redis_mock.hgetall = AsyncMock(return_value={})
    redis_mock.hset = AsyncMock()
    redis_mock.expire = AsyncMock()
    redis_mock.pipeline = MagicMock()
    redis_mock.execute = AsyncMock(return_value=[None, 1, None, None])
    redis_mock.zremrangebyscore = AsyncMock()
    redis_mock.zcard = AsyncMock(return_value=0)
    redis_mock.zadd = AsyncMock()
    redis_mock.zrem = AsyncMock()
    redis_mock.incr = AsyncMock(return_value=1)
    redis_mock.decr = AsyncMock(return_value=0)
    redis_mock.eval = AsyncMock(return_value=[1, 10, 0])
    redis_mock.keys = AsyncMock(return_value=[])
    redis_mock.delete = AsyncMock()
    return redis_mock


@pytest.fixture
async def mock_vault_client():
    """Mock Vault client for integration tests"""
    vault_mock = MockVaultClient()
    # Add some test API keys
    await vault_mock.store_api_key("test-service", "test-api-key-123", ["read", "write"])
    await vault_mock.store_api_key("pms-connector", "pms-api-key-456", ["pms:read", "pms:write"])
    return vault_mock


@pytest.fixture
async def jwt_service(mock_redis):
    """JWT service for integration tests"""
    service = JWTService(redis_url="redis://localhost:6379")
    service.redis = mock_redis
    return service


@pytest.fixture
async def test_user_context():
    """Test user context for authenticated requests"""
    return UserContext(
        user_id="test-user-123",
        email="test@voicehive-hotels.eu",
        roles=["user", "admin"],
        permissions=["read", "write", "admin"],
        session_id="test-session-123",
        expires_at=None
    )


@pytest.fixture
async def test_service_context():
    """Test service context for service-to-service requests"""
    return ServiceContext(
        service_name="test-service",
        api_key_id="test-api-key-123",
        permissions=["read", "write"],
        rate_limits={"requests_per_minute": 100}
    )


@pytest.fixture
async def authenticated_client(jwt_service, test_user_context):
    """HTTP client with valid JWT token"""
    token = await jwt_service.create_token(test_user_context)
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        client.headers.update({"Authorization": f"Bearer {token}"})
        yield client


@pytest.fixture
async def service_client(test_service_context):
    """HTTP client with valid API key"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        client.headers.update({"X-API-Key": "test-api-key-123"})
        yield client


@pytest.fixture
async def unauthenticated_client():
    """HTTP client without authentication"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_pms_server():
    """Mock PMS server for integration testing"""
    class MockPMSServer:
        def __init__(self):
            self.reservations = {
                "12345": {
                    "id": "12345",
                    "guest_name": "John Doe",
                    "room_number": "101",
                    "check_in": "2024-01-15",
                    "check_out": "2024-01-17",
                    "status": "confirmed"
                }
            }
            self.call_count = 0
            self.should_fail = False
            self.response_delay = 0
        
        async def get_reservation(self, reservation_id: str):
            self.call_count += 1
            if self.should_fail:
                raise Exception("PMS server error")
            
            if self.response_delay > 0:
                await asyncio.sleep(self.response_delay)
            
            return self.reservations.get(reservation_id)
        
        def reset(self):
            self.call_count = 0
            self.should_fail = False
            self.response_delay = 0
    
    return MockPMSServer()


@pytest.fixture
def mock_tts_service():
    """Mock TTS service for integration testing"""
    class MockTTSService:
        def __init__(self):
            self.call_count = 0
            self.should_fail = False
            self.response_delay = 0
        
        async def synthesize_speech(self, text: str, voice: str = "default"):
            self.call_count += 1
            if self.should_fail:
                raise Exception("TTS service error")
            
            if self.response_delay > 0:
                await asyncio.sleep(self.response_delay)
            
            return b"fake_audio_data"
        
        async def health_check(self):
            return not self.should_fail
        
        def reset(self):
            self.call_count = 0
            self.should_fail = False
            self.response_delay = 0
    
    return MockTTSService()


@pytest.fixture
def mock_livekit_service():
    """Mock LiveKit service for integration testing"""
    class MockLiveKitService:
        def __init__(self):
            self.active_rooms = {}
            self.call_count = 0
            self.should_fail = False
        
        async def create_room(self, room_name: str):
            self.call_count += 1
            if self.should_fail:
                raise Exception("LiveKit service error")
            
            room_id = f"room_{room_name}_{self.call_count}"
            self.active_rooms[room_id] = {
                "name": room_name,
                "participants": [],
                "created_at": "2024-01-15T10:00:00Z"
            }
            return room_id
        
        async def join_room(self, room_id: str, participant_name: str):
            if room_id in self.active_rooms:
                self.active_rooms[room_id]["participants"].append(participant_name)
                return True
            return False
        
        def reset(self):
            self.active_rooms = {}
            self.call_count = 0
            self.should_fail = False
    
    return MockLiveKitService()


@pytest.fixture
async def integration_test_app(
    mock_redis, 
    mock_vault_client, 
    jwt_service,
    mock_pms_server,
    mock_tts_service,
    mock_livekit_service
):
    """Configured app instance for integration testing"""
    # Override app dependencies with mocks
    app.state.redis = mock_redis
    app.state.vault_client = mock_vault_client
    app.state.jwt_service = jwt_service
    app.state.pms_server = mock_pms_server
    app.state.tts_service = mock_tts_service
    app.state.livekit_service = mock_livekit_service
    
    # Initialize resilience components with test configuration
    resilience_config = ResilienceConfig(
        rate_limiting_enabled=True,
        circuit_breaker_enabled=True,
        backpressure_enabled=True,
        default_rate_limit=RateLimitConfig(
            requests_per_minute=100,
            requests_per_hour=1000
        ),
        default_circuit_breaker=CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=5
        )
    )
    
    resilience_manager = ResilienceManager(resilience_config, mock_redis)
    app.state.resilience_manager = resilience_manager
    
    yield app
    
    # Cleanup
    if hasattr(app.state, 'redis'):
        delattr(app.state, 'redis')
    if hasattr(app.state, 'vault_client'):
        delattr(app.state, 'vault_client')


@pytest.fixture
def performance_test_config():
    """Configuration for performance regression tests"""
    return {
        "max_response_time": 1.0,  # seconds
        "max_memory_usage": 100 * 1024 * 1024,  # 100MB
        "concurrent_requests": 10,
        "test_duration": 30,  # seconds
        "acceptable_error_rate": 0.01  # 1%
    }


@pytest.fixture
def load_test_scenarios():
    """Load test scenarios for different endpoints"""
    return {
        "health_check": {
            "endpoint": "/healthz",
            "method": "GET",
            "expected_status": 200,
            "requests_per_second": 100
        },
        "authentication": {
            "endpoint": "/auth/login",
            "method": "POST",
            "payload": {"email": "test@example.com", "password": "testpass"},
            "expected_status": 200,
            "requests_per_second": 10
        },
        "call_webhook": {
            "endpoint": "/webhook/call-event",
            "method": "POST",
            "payload": {"event": "call.started", "call_id": "test-call"},
            "expected_status": 200,
            "requests_per_second": 50
        }
    }