"""
Prometheus metrics for VoiceHive Hotels Orchestrator
Following Prometheus naming conventions and best practices
"""

from prometheus_client import Counter, Histogram, Gauge

# Call metrics - Following Prometheus naming conventions
voicehive_calls_total = Counter(
    'voicehive_calls_total', 
    'Total calls processed', 
    ['hotel_id', 'language', 'status']
)

voicehive_call_duration_seconds = Histogram(
    'voicehive_call_duration_seconds', 
    'Call duration in seconds', 
    ['hotel_id', 'language'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
)

voicehive_active_calls = Gauge(
    'voicehive_active_calls', 
    'Currently active calls', 
    ['hotel_id']
)

# HTTP request metrics
voicehive_http_requests_total = Counter(
    'voicehive_http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

voicehive_http_request_duration_seconds = Histogram(
    'voicehive_http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0]
)

# Event metrics
voicehive_call_events_total = Counter(
    'voicehive_call_events_total', 
    'Total call events received', 
    ['event_type', 'hotel_id']
)

# Compliance metrics
voicehive_pii_redactions_total = Counter(
    'voicehive_pii_redactions_total', 
    'PII redactions performed', 
    ['category', 'hotel_id']
)

# Error metrics
voicehive_errors_total = Counter(
    'voicehive_errors_total',
    'Total errors by type',
    ['error_type', 'component']
)

# Business metrics
voicehive_revenue_impact_total = Counter(
    'voicehive_revenue_impact_total',
    'Revenue impact from AI interactions',
    ['hotel_id', 'currency', 'impact_type']
)
