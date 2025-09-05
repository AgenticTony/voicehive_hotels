"""
Simple test for Prometheus counter functionality.
Tests the call_events_total counter without requiring the full app imports.
"""

import pytest
from prometheus_client import Counter, CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families


class TestPrometheusCounter:
    """Test suite for prometheus counter functionality"""
    
    def setup_method(self):
        """Create a fresh counter for each test"""
        self.registry = CollectorRegistry()
        self.call_events_total = Counter(
            'voicehive_call_events_total',
            'Total call events received',
            ['event_type'],
            registry=self.registry
        )
    
    def test_counter_increment(self):
        """Test that the counter increments correctly"""
        # Increment counter for different event types
        self.call_events_total.labels(event_type='call_started').inc()
        self.call_events_total.labels(event_type='call_ended').inc()
        self.call_events_total.labels(event_type='call_started').inc()  # Second call_started
        
        # Get metrics
        metrics_output = generate_latest(self.registry).decode('utf-8')
        
        # Parse metrics
        metrics_dict = {}
        for family in text_string_to_metric_families(metrics_output):
            # Note: Prometheus removes '_total' from counter family names
            if family.name == 'voicehive_call_events':
                for sample in family.samples:
                    if sample.name == 'voicehive_call_events_total':
                        event_type = sample.labels.get('event_type')
                        metrics_dict[event_type] = sample.value
        
        # Verify counts
        assert metrics_dict.get('call_started') == 2.0
        assert metrics_dict.get('call_ended') == 1.0
    
    def test_counter_in_metrics_output(self):
        """Test that the counter appears correctly in metrics output"""
        # Increment once to ensure it appears
        self.call_events_total.labels(event_type='test_event').inc()
        
        metrics_output = generate_latest(self.registry).decode('utf-8')
        
        # Check that counter is present with correct metadata
        assert 'voicehive_call_events_total' in metrics_output
        assert '# HELP voicehive_call_events_total Total call events received' in metrics_output
        assert '# TYPE voicehive_call_events_total counter' in metrics_output
        assert 'event_type="test_event"' in metrics_output
    
    def test_multiple_labels(self):
        """Test counter with multiple different labels"""
        event_types = ['call_started', 'call_ended', 'call_failed', 'transcription', 'agent_ready']
        
        # Increment each event type
        for event_type in event_types:
            self.call_events_total.labels(event_type=event_type).inc()
        
        # Some events happen multiple times
        self.call_events_total.labels(event_type='call_started').inc(2)  # 3 more
        self.call_events_total.labels(event_type='transcription').inc(5)  # 5 more
        
        # Parse metrics
        metrics_output = generate_latest(self.registry).decode('utf-8')
        metrics_dict = {}
        
        for family in text_string_to_metric_families(metrics_output):
            # Note: Prometheus removes '_total' from counter family names
            if family.name == 'voicehive_call_events':
                for sample in family.samples:
                    if sample.name == 'voicehive_call_events_total':
                        event_type = sample.labels.get('event_type')
                        metrics_dict[event_type] = sample.value
        
        # Verify counts
        assert metrics_dict.get('call_started') == 3.0  # 1 + 2
        assert metrics_dict.get('call_ended') == 1.0
        assert metrics_dict.get('call_failed') == 1.0
        assert metrics_dict.get('transcription') == 6.0  # 1 + 5
        assert metrics_dict.get('agent_ready') == 1.0
    
    def test_counter_zero_not_shown(self):
        """Test that labels with zero count don't appear by default"""
        # Don't increment anything
        metrics_output = generate_latest(self.registry).decode('utf-8')
        
        # Should have the counter definition but no data lines
        assert '# TYPE voicehive_call_events_total counter' in metrics_output
        # Should not have any actual metric lines (those with values)
        assert 'voicehive_call_events_total{' not in metrics_output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
