"""
Business Metrics Collection for VoiceHive Hotels
Comprehensive metrics for call success rates, PMS response times, and business KPIs
"""

from prometheus_client import Counter, Histogram, Gauge, Summary
from typing import Dict, Optional
import time
from contextlib import contextmanager
from logging_adapter import get_safe_logger

logger = get_safe_logger("business_metrics")

# Call Success Metrics
call_success_rate = Counter(
    'voicehive_call_success_total',
    'Total successful calls',
    ['hotel_id', 'language', 'call_type', 'outcome']
)

call_failure_rate = Counter(
    'voicehive_call_failures_total',
    'Total failed calls',
    ['hotel_id', 'language', 'call_type', 'failure_reason']
)

call_abandonment_rate = Counter(
    'voicehive_call_abandonment_total',
    'Total abandoned calls',
    ['hotel_id', 'language', 'abandonment_stage']
)

# PMS Integration Metrics
pms_response_time = Histogram(
    'voicehive_pms_response_seconds',
    'PMS connector response time',
    ['hotel_id', 'pms_type', 'operation'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
)

pms_success_rate = Counter(
    'voicehive_pms_operations_total',
    'Total PMS operations',
    ['hotel_id', 'pms_type', 'operation', 'status']
)

pms_availability = Gauge(
    'voicehive_pms_availability',
    'PMS system availability (0-1)',
    ['hotel_id', 'pms_type']
)

# Business KPI Metrics
guest_satisfaction_score = Histogram(
    'voicehive_guest_satisfaction',
    'Guest satisfaction scores',
    ['hotel_id', 'language'],
    buckets=[1, 2, 3, 4, 5]
)

booking_conversion_rate = Counter(
    'voicehive_booking_conversions_total',
    'Booking conversion events',
    ['hotel_id', 'conversion_type', 'outcome']
)

revenue_impact = Counter(
    'voicehive_revenue_impact_total',
    'Revenue impact from AI interactions',
    ['hotel_id', 'currency', 'impact_type']
)

# Service Quality Metrics
response_accuracy = Histogram(
    'voicehive_response_accuracy',
    'AI response accuracy scores',
    ['hotel_id', 'language', 'intent_type'],
    buckets=[0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]
)

intent_recognition_confidence = Histogram(
    'voicehive_intent_confidence',
    'Intent recognition confidence scores',
    ['hotel_id', 'language', 'intent_type'],
    buckets=[0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]
)

# System Performance Metrics
audio_quality_score = Histogram(
    'voicehive_audio_quality',
    'Audio quality metrics',
    ['hotel_id', 'codec', 'direction'],
    buckets=[0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]
)

latency_end_to_end = Histogram(
    'voicehive_e2e_latency_seconds',
    'End-to-end response latency',
    ['hotel_id', 'language', 'interaction_type'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
)

# Resource Utilization Metrics
concurrent_calls_gauge = Gauge(
    'voicehive_concurrent_calls',
    'Current concurrent calls',
    ['hotel_id']
)

memory_usage_bytes = Gauge(
    'voicehive_memory_usage_bytes',
    'Memory usage in bytes',
    ['component']
)

cpu_usage_percent = Gauge(
    'voicehive_cpu_usage_percent',
    'CPU usage percentage',
    ['component']
)


class BusinessMetricsCollector:
    """Centralized business metrics collection and management"""
    
    def __init__(self):
        self.active_calls: Dict[str, float] = {}
        self.pms_health_status: Dict[str, bool] = {}
    
    def record_call_start(self, call_id: str, hotel_id: str, language: str, call_type: str):
        """Record the start of a call"""
        self.active_calls[call_id] = time.time()
        concurrent_calls_gauge.labels(hotel_id=hotel_id).inc()
        
        logger.info(
            "call_started",
            call_id=call_id,
            hotel_id=hotel_id,
            language=language,
            call_type=call_type
        )
    
    def record_call_success(self, call_id: str, hotel_id: str, language: str, 
                          call_type: str, outcome: str):
        """Record a successful call completion"""
        if call_id in self.active_calls:
            duration = time.time() - self.active_calls[call_id]
            del self.active_calls[call_id]
            concurrent_calls_gauge.labels(hotel_id=hotel_id).dec()
        
        call_success_rate.labels(
            hotel_id=hotel_id,
            language=language,
            call_type=call_type,
            outcome=outcome
        ).inc()
        
        logger.info(
            "call_completed_successfully",
            call_id=call_id,
            hotel_id=hotel_id,
            outcome=outcome,
            duration=duration if call_id in self.active_calls else None
        )
    
    def record_call_failure(self, call_id: str, hotel_id: str, language: str,
                          call_type: str, failure_reason: str):
        """Record a failed call"""
        if call_id in self.active_calls:
            duration = time.time() - self.active_calls[call_id]
            del self.active_calls[call_id]
            concurrent_calls_gauge.labels(hotel_id=hotel_id).dec()
        
        call_failure_rate.labels(
            hotel_id=hotel_id,
            language=language,
            call_type=call_type,
            failure_reason=failure_reason
        ).inc()
        
        logger.error(
            "call_failed",
            call_id=call_id,
            hotel_id=hotel_id,
            failure_reason=failure_reason,
            duration=duration if call_id in self.active_calls else None
        )
    
    def record_call_abandonment(self, call_id: str, hotel_id: str, language: str,
                              abandonment_stage: str):
        """Record a call abandonment"""
        if call_id in self.active_calls:
            del self.active_calls[call_id]
            concurrent_calls_gauge.labels(hotel_id=hotel_id).dec()
        
        call_abandonment_rate.labels(
            hotel_id=hotel_id,
            language=language,
            abandonment_stage=abandonment_stage
        ).inc()
        
        logger.info(
            "call_abandoned",
            call_id=call_id,
            hotel_id=hotel_id,
            abandonment_stage=abandonment_stage
        )
    
    @contextmanager
    def measure_pms_operation(self, hotel_id: str, pms_type: str, operation: str):
        """Context manager to measure PMS operation duration"""
        start_time = time.time()
        success = False
        
        try:
            yield
            success = True
        except Exception as e:
            logger.error(
                "pms_operation_failed",
                hotel_id=hotel_id,
                pms_type=pms_type,
                operation=operation,
                error=str(e)
            )
            raise
        finally:
            duration = time.time() - start_time
            pms_response_time.labels(
                hotel_id=hotel_id,
                pms_type=pms_type,
                operation=operation
            ).observe(duration)
            
            pms_success_rate.labels(
                hotel_id=hotel_id,
                pms_type=pms_type,
                operation=operation,
                status="success" if success else "failure"
            ).inc()
    
    def update_pms_availability(self, hotel_id: str, pms_type: str, is_available: bool):
        """Update PMS availability status"""
        availability_value = 1.0 if is_available else 0.0
        pms_availability.labels(hotel_id=hotel_id, pms_type=pms_type).set(availability_value)
        
        # Track health status changes
        key = f"{hotel_id}:{pms_type}"
        previous_status = self.pms_health_status.get(key)
        
        if previous_status is not None and previous_status != is_available:
            logger.warning(
                "pms_availability_changed",
                hotel_id=hotel_id,
                pms_type=pms_type,
                previous_status=previous_status,
                current_status=is_available
            )
        
        self.pms_health_status[key] = is_available
    
    def record_guest_satisfaction(self, hotel_id: str, language: str, score: float):
        """Record guest satisfaction score (1-5)"""
        guest_satisfaction_score.labels(
            hotel_id=hotel_id,
            language=language
        ).observe(score)
        
        logger.info(
            "guest_satisfaction_recorded",
            hotel_id=hotel_id,
            language=language,
            score=score
        )
    
    def record_booking_conversion(self, hotel_id: str, conversion_type: str, outcome: str):
        """Record booking conversion event"""
        booking_conversion_rate.labels(
            hotel_id=hotel_id,
            conversion_type=conversion_type,
            outcome=outcome
        ).inc()
        
        logger.info(
            "booking_conversion_recorded",
            hotel_id=hotel_id,
            conversion_type=conversion_type,
            outcome=outcome
        )
    
    def record_revenue_impact(self, hotel_id: str, currency: str, impact_type: str, amount: float):
        """Record revenue impact from AI interactions"""
        revenue_impact.labels(
            hotel_id=hotel_id,
            currency=currency,
            impact_type=impact_type
        ).inc(amount)
        
        logger.info(
            "revenue_impact_recorded",
            hotel_id=hotel_id,
            currency=currency,
            impact_type=impact_type,
            amount=amount
        )
    
    def record_response_accuracy(self, hotel_id: str, language: str, intent_type: str, accuracy: float):
        """Record AI response accuracy score"""
        response_accuracy.labels(
            hotel_id=hotel_id,
            language=language,
            intent_type=intent_type
        ).observe(accuracy)
    
    def record_intent_confidence(self, hotel_id: str, language: str, intent_type: str, confidence: float):
        """Record intent recognition confidence"""
        intent_recognition_confidence.labels(
            hotel_id=hotel_id,
            language=language,
            intent_type=intent_type
        ).observe(confidence)
    
    def record_audio_quality(self, hotel_id: str, codec: str, direction: str, quality_score: float):
        """Record audio quality metrics"""
        audio_quality_score.labels(
            hotel_id=hotel_id,
            codec=codec,
            direction=direction
        ).observe(quality_score)
    
    def record_e2e_latency(self, hotel_id: str, language: str, interaction_type: str, latency: float):
        """Record end-to-end response latency"""
        latency_end_to_end.labels(
            hotel_id=hotel_id,
            language=language,
            interaction_type=interaction_type
        ).observe(latency)
    
    def update_resource_usage(self, component: str, memory_bytes: Optional[int] = None, 
                            cpu_percent: Optional[float] = None):
        """Update resource usage metrics"""
        if memory_bytes is not None:
            memory_usage_bytes.labels(component=component).set(memory_bytes)
        
        if cpu_percent is not None:
            cpu_usage_percent.labels(component=component).set(cpu_percent)


# Global instance
business_metrics = BusinessMetricsCollector()