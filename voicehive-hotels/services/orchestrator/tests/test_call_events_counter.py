#!/usr/bin/env python3
"""
Test that call_events_total counter increments correctly in orchestrator
"""

import os
import pytest
from fastapi.testclient import TestClient
from prometheus_parser import text_string_to_metric_families
import json

# Set test environment variables
os.environ["LIVEKIT_WEBHOOK_KEY"] = "test_webhook_key"
os.environ["VAULT_ADDR"] = "http://localhost:8200"
os.environ["CONFIG_PATH"] = "../../config/security/gdpr-config.yaml"

from services.orchestrator.app import app


class TestCallEventsCounter:
    """Test that call_events_total Prometheus counter works correctly"""
    
    def setup_method(self):
        """Set up test client"""
        self.client = TestClient(app)
        self.webhook_headers = {
            "Authorization": "Bearer test_webhook_key"
        }
        
    def _get_counter_value(self, metrics_text: str, counter_name: str, labels: dict) -> float:
        """Parse Prometheus metrics and get counter value for specific labels"""
        for family in text_string_to_metric_families(metrics_text):
            if family.name == counter_name:
                for sample in family.samples:
                    # Check if all label key-value pairs match
                    if all(sample.labels.get(k) == v for k, v in labels.items()):
                        return sample.value
        return 0.0
        
    def test_metrics_endpoint_returns_prometheus_format(self):
        """Test that /metrics returns proper Prometheus format"""
        response = self.client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
        assert "voicehive_call_events_total" in response.text
        
    def test_call_event_increments_counter(self):
        """Test that posting to /call/event increments the counter"""
        # Get initial counter value
        metrics_before = self.client.get("/metrics").text
        initial_value = self._get_counter_value(
            metrics_before, 
            "voicehive_call_events_total",
            {"event_type": "transcription"}
        )
        
        # Send a call event
        event_data = {
            "event": "transcription",
            "room_name": "test_room_123",
            "data": {
                "text": "Hello, I need a room",
                "language": "en-US",
                "confidence": 0.95
            }
        }
        
        response = self.client.post(
            "/call/event",
            json=event_data,
            headers=self.webhook_headers
        )
        assert response.status_code == 200
        
        # Get counter value after
        metrics_after = self.client.get("/metrics").text
        final_value = self._get_counter_value(
            metrics_after,
            "voicehive_call_events_total", 
            {"event_type": "transcription"}
        )
        
        # Counter should have incremented by 1
        assert final_value == initial_value + 1
        
    def test_different_event_types_have_separate_counters(self):
        """Test that different event types maintain separate counter values"""
        # Send different types of events
        event_types = ["agent_ready", "call_started", "intent_detected", "call_ended"]
        
        for event_type in event_types:
            event_data = {
                "event": event_type,
                "room_name": f"room_{event_type}",
                "data": {}
            }
            
            response = self.client.post(
                "/call/event",
                json=event_data,
                headers=self.webhook_headers
            )
            assert response.status_code == 200
            
        # Check metrics
        metrics = self.client.get("/metrics").text
        
        # Each event type should have its own counter
        for event_type in event_types:
            value = self._get_counter_value(
                metrics,
                "voicehive_call_events_total",
                {"event_type": event_type}
            )
            assert value >= 1  # At least one of each type
            
    def test_counter_persists_across_requests(self):
        """Test that counter values persist across multiple requests"""
        # Send multiple events
        for i in range(5):
            event_data = {
                "event": "test_event",
                "room_name": f"room_{i}",
                "data": {"index": i}
            }
            
            response = self.client.post(
                "/call/event",
                json=event_data,
                headers=self.webhook_headers
            )
            assert response.status_code == 200
            
        # Check final counter value
        metrics = self.client.get("/metrics").text
        value = self._get_counter_value(
            metrics,
            "voicehive_call_events_total",
            {"event_type": "test_event"}
        )
        
        # Should have counted all 5 events
        assert value >= 5
        
    def test_unauthorized_request_does_not_increment_counter(self):
        """Test that unauthorized requests don't increment the counter"""
        # Get initial value
        metrics_before = self.client.get("/metrics").text
        initial_value = self._get_counter_value(
            metrics_before,
            "voicehive_call_events_total",
            {"event_type": "unauthorized_test"}
        )
        
        # Send unauthorized request (no auth header)
        event_data = {
            "event": "unauthorized_test",
            "room_name": "test_room",
            "data": {}
        }
        
        response = self.client.post("/call/event", json=event_data)
        assert response.status_code == 401  # Unauthorized
        
        # Counter should not have incremented
        metrics_after = self.client.get("/metrics").text
        final_value = self._get_counter_value(
            metrics_after,
            "voicehive_call_events_total",
            {"event_type": "unauthorized_test"}
        )
        
        assert final_value == initial_value
        
    def test_metrics_include_all_default_prometheus_collectors(self):
        """Test that metrics include process and Python collectors"""
        response = self.client.get("/metrics")
        metrics_text = response.text
        
        # Should include default Prometheus collectors
        assert "process_virtual_memory_bytes" in metrics_text
        assert "process_resident_memory_bytes" in metrics_text
        assert "process_cpu_seconds_total" in metrics_text
        assert "python_info" in metrics_text
        assert "python_gc_objects_collected_total" in metrics_text
        
    def test_counter_help_text_exists(self):
        """Test that counter has proper HELP text"""
        response = self.client.get("/metrics")
        metrics_text = response.text
        
        # Should have HELP text for our counter
        assert "# HELP voicehive_call_events_total Total call events received" in metrics_text
        assert "# TYPE voicehive_call_events_total counter" in metrics_text


# Helper class to parse Prometheus metrics
class text_string_to_metric_families:
    """Simple parser for Prometheus text format"""
    
    def __init__(self, text):
        self.text = text
        
    def __iter__(self):
        """Parse metrics text and yield metric families"""
        lines = self.text.strip().split('\n')
        current_metric = None
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines and comments (except TYPE)
            if not line or (line.startswith('#') and not line.startswith('# TYPE')):
                continue
                
            # Parse TYPE line
            if line.startswith('# TYPE'):
                parts = line.split()
                if len(parts) >= 4:
                    metric_name = parts[2]
                    metric_type = parts[3]
                    current_metric = MetricFamily(metric_name, metric_type)
                    
            # Parse metric line
            elif current_metric and not line.startswith('#'):
                # Simple parser for: metric_name{label1="value1",label2="value2"} value
                if '{' in line:
                    name_part, rest = line.split('{', 1)
                    labels_part, value_part = rest.split('}', 1)
                    
                    # Parse labels
                    labels = {}
                    if labels_part:
                        for label in labels_part.split(','):
                            if '=' in label:
                                key, value = label.split('=', 1)
                                labels[key.strip()] = value.strip('" ')
                    
                    # Parse value
                    value = float(value_part.strip())
                    
                    # Add sample
                    current_metric.add_sample(name_part, labels, value)
                    
        # Yield the last metric
        if current_metric:
            yield current_metric


class MetricFamily:
    """Simple metric family representation"""
    
    def __init__(self, name, metric_type):
        self.name = name
        self.type = metric_type
        self.samples = []
        
    def add_sample(self, name, labels, value):
        self.samples.append(Sample(name, labels, value))


class Sample:
    """Simple metric sample representation"""
    
    def __init__(self, name, labels, value):
        self.name = name
        self.labels = labels
        self.value = value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
