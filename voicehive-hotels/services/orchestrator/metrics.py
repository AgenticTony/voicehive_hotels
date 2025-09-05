"""
Prometheus metrics for VoiceHive Hotels Orchestrator
"""

from prometheus_client import Counter, Histogram, Gauge

# Call metrics
call_counter = Counter(
    'voicehive_calls_total', 
    'Total calls processed', 
    ['hotel_id', 'language', 'status']
)

call_duration = Histogram(
    'voicehive_call_duration_seconds', 
    'Call duration', 
    ['hotel_id', 'language']
)

active_calls = Gauge(
    'voicehive_active_calls', 
    'Currently active calls', 
    ['hotel_id']
)

# Event metrics
call_events_total = Counter(
    'voicehive_call_events_total', 
    'Total call events received', 
    ['event_type']
)

# Compliance metrics
pii_redactions_total = Counter(
    'voicehive_pii_redactions', 
    'PII redactions performed', 
    ['category']
)
