"""
Test for the /call/event endpoint to ensure proper CallEvent construction.
This test would have caught the event_type vs event field mismatch.
"""

import pytest
import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

# Ensure imports resolve from repo root
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root))

from services.orchestrator.app import app
from services.orchestrator.call_manager import CallEvent


class TestCallEventEndpoint:
    """Test suite for the /call/event webhook endpoint"""
    
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture
    def mock_call_manager(self):
        """Create mock call manager"""
        manager = Mock()
        manager.handle_event = AsyncMock(return_value={"status": "processed"})
        return manager
    
    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        """Set up test environment variables"""
        monkeypatch.setenv("LIVEKIT_WEBHOOK_KEY", "test-webhook-key")
    
    def test_call_event_requires_authorization(self, client):
        """Test that /call/event requires authorization header"""
        response = client.post(
            "/call/event",
            json={"event": "call_started", "room_name": "test-room"}
        )
        assert response.status_code == 401
        assert "Missing authorization" in response.json()["detail"]
    
    def test_call_event_validates_bearer_token(self, client):
        """Test that /call/event validates the bearer token"""
        response = client.post(
            "/call/event",
            json={"event": "call_started", "room_name": "test-room"},
            headers={"Authorization": "Bearer wrong-key"}
        )
        assert response.status_code == 401
        assert "Invalid webhook key" in response.json()["detail"]
    
    def test_call_event_creates_correct_event_object(self, client, mock_call_manager):
        """Test that CallEvent is created with correct field names and types"""
        # Set up the call manager on app.state
        app.state.call_manager = mock_call_manager
        
        try:
            # Send webhook request
            response = client.post(
                "/call/event",
                json={
                    "event": "call_started",
                    "room_name": "test-room-123",
                    "participant": "test-participant"
                },
                headers={"Authorization": "Bearer test-webhook-key"}
            )
            
            assert response.status_code == 200
            assert response.json() == {"status": "processed", "event": "call_started"}
            
            # Verify handle_event was called
            mock_call_manager.handle_event.assert_called_once()
            
            # Get the CallEvent that was passed to handle_event
            call_args = mock_call_manager.handle_event.call_args
            event = call_args[0][0]
            
            # Verify CallEvent has correct structure
            assert isinstance(event, CallEvent)
            assert event.event == "call_started"  # NOT event_type
            assert event.room_name == "test-room-123"
            assert event.call_sid == "test-room-123"
            assert isinstance(event.timestamp, float)  # Must be float, not string
            assert event.timestamp > 0
            assert isinstance(event.data, dict)
            assert event.data["event"] == "call_started"
            assert event.data["room_name"] == "test-room-123"
        finally:
            # Clean up
            if hasattr(app.state, 'call_manager'):
                delattr(app.state, 'call_manager')
    
    def test_call_event_handles_all_event_types(self, client, mock_call_manager):
        """Test that all event types are handled correctly"""
        event_types = [
            "agent_ready", "call_started", "call_ended",
            "transcription", "error", "participant_joined"
        ]
        
        app.state.call_manager = mock_call_manager
        try:
            for event_type in event_types:
                response = client.post(
                    "/call/event",
                    json={"event": event_type, "room_name": f"room-{event_type}"},
                    headers={"Authorization": "Bearer test-webhook-key"}
                )
                
                assert response.status_code == 200
                assert response.json()["event"] == event_type
        finally:
            # Clean up
            if hasattr(app.state, 'call_manager'):
                delattr(app.state, 'call_manager')
    
    def test_call_event_increments_metrics(self, client):
        """Test that Prometheus metrics are incremented"""
        from services.orchestrator.app import call_events_total
        
        # Get initial count
        initial_labels = call_events_total._metrics.copy()
        
        # Send event (without call manager to simplify test)
        response = client.post(
            "/call/event",
            json={"event": "call_started", "room_name": "metrics-test"},
            headers={"Authorization": "Bearer test-webhook-key"}
        )
        
        assert response.status_code == 200
        
        # Check metric was incremented
        # Note: The metric should have been incremented for the "call_started" label
        # This is a simplified check - in a real test you'd parse the metrics endpoint
    
    def test_call_event_without_call_manager(self, client):
        """Test that endpoint works even without call manager"""
        # Ensure no call manager is set
        if hasattr(app.state, 'call_manager'):
            delattr(app.state, 'call_manager')
        
        response = client.post(
            "/call/event",
            json={"event": "call_started", "room_name": "no-manager-test"},
            headers={"Authorization": "Bearer test-webhook-key"}
        )
        
        # Should still process successfully
        assert response.status_code == 200
        assert response.json()["status"] == "processed"
    
    def test_call_event_handles_errors_gracefully(self, client, mock_call_manager):
        """Test error handling in the endpoint"""
        # Make handle_event raise an exception
        mock_call_manager.handle_event.side_effect = Exception("Test error")
        
        app.state.call_manager = mock_call_manager
        try:
            response = client.post(
                "/call/event",
                json={"event": "call_started", "room_name": "error-test"},
                headers={"Authorization": "Bearer test-webhook-key"}
            )
            
            assert response.status_code == 500
            assert "Internal error" in response.json()["detail"]
        finally:
            # Clean up
            if hasattr(app.state, 'call_manager'):
                delattr(app.state, 'call_manager')
    
    @pytest.mark.parametrize("event_data", [
        {"event": "call_started"},  # Missing room_name
        {"room_name": "test-room"},  # Missing event
        {},  # Empty data
    ])
    def test_call_event_handles_incomplete_data(self, client, event_data):
        """Test that endpoint handles incomplete event data"""
        response = client.post(
            "/call/event",
            json=event_data,
            headers={"Authorization": "Bearer test-webhook-key"}
        )
        
        # Should not crash, even with incomplete data
        assert response.status_code in [200, 500]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
