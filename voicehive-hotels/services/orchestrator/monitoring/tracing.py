"""
Enhanced Distributed Tracing for VoiceHive Hotels
Comprehensive tracing across all service boundaries with business context
"""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import json
from logging_adapter import get_safe_logger

try:
    from opentelemetry import trace, baggage, context
    from opentelemetry.trace import Status, StatusCode, SpanKind
    from opentelemetry.baggage import set_baggage, get_baggage
    from opentelemetry.context import attach, detach
    from opentelemetry.propagate import inject, extract
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    OTEL_AVAILABLE = True
except ImportError:
    trace = None
    OTEL_AVAILABLE = False

logger = get_safe_logger("distributed_tracing")


class SpanType(Enum):
    """Types of spans for business context"""
    CALL_HANDLING = "call_handling"
    PMS_OPERATION = "pms_operation"
    AI_PROCESSING = "ai_processing"
    AUDIO_PROCESSING = "audio_processing"
    AUTHENTICATION = "authentication"
    RATE_LIMITING = "rate_limiting"
    CIRCUIT_BREAKER = "circuit_breaker"
    DATABASE_OPERATION = "database_operation"
    CACHE_OPERATION = "cache_operation"
    EXTERNAL_API = "external_api"
    WEBHOOK_PROCESSING = "webhook_processing"
    ERROR_HANDLING = "error_handling"


@dataclass
class BusinessContext:
    """Business context for tracing"""
    hotel_id: Optional[str] = None
    call_id: Optional[str] = None
    guest_id: Optional[str] = None
    language: Optional[str] = None
    call_type: Optional[str] = None
    pms_type: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None
    custom_attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceMetrics:
    """Metrics collected during tracing"""
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    error_count: int = 0
    success_count: int = 0
    custom_metrics: Dict[str, float] = field(default_factory=dict)


class EnhancedTracer:
    """Enhanced tracer with business context and metrics"""
    
    def __init__(self, service_name: str = "voicehive-orchestrator"):
        self.service_name = service_name
        self.tracer = None
        self.active_spans: Dict[str, Any] = {}
        self.business_contexts: Dict[str, BusinessContext] = {}
        self.trace_metrics: Dict[str, TraceMetrics] = {}
        
        if OTEL_AVAILABLE:
            self._initialize_tracing()
    
    def _initialize_tracing(self):
        """Initialize OpenTelemetry tracing"""
        try:
            # Set up tracer provider
            trace.set_tracer_provider(TracerProvider())
            
            # Configure exporters
            jaeger_exporter = JaegerExporter(
                agent_host_name="jaeger",
                agent_port=6831,
            )
            
            otlp_exporter = OTLPSpanExporter(
                endpoint="http://tempo:4317",
                insecure=True
            )
            
            # Add span processors
            trace.get_tracer_provider().add_span_processor(
                BatchSpanProcessor(jaeger_exporter)
            )
            trace.get_tracer_provider().add_span_processor(
                BatchSpanProcessor(otlp_exporter)
            )
            
            # Get tracer
            self.tracer = trace.get_tracer(self.service_name)
            
            # Instrument libraries
            RequestsInstrumentor().instrument()
            AioHttpClientInstrumentor().instrument()
            RedisInstrumentor().instrument()
            
            logger.info("distributed_tracing_initialized", service_name=self.service_name)
            
        except Exception as e:
            logger.error("tracing_initialization_failed", error=str(e))
            self.tracer = None
    
    def create_business_context(self, **kwargs) -> BusinessContext:
        """Create business context from keyword arguments"""
        return BusinessContext(**kwargs)
    
    def set_business_context(self, context_id: str, business_context: BusinessContext):
        """Set business context for a trace"""
        self.business_contexts[context_id] = business_context
        
        # Set baggage for context propagation
        if OTEL_AVAILABLE and business_context.correlation_id:
            set_baggage("correlation_id", business_context.correlation_id)
        if business_context.hotel_id:
            set_baggage("hotel_id", business_context.hotel_id)
        if business_context.call_id:
            set_baggage("call_id", business_context.call_id)
    
    def get_business_context(self, context_id: str) -> Optional[BusinessContext]:
        """Get business context for a trace"""
        return self.business_contexts.get(context_id)
    
    @asynccontextmanager
    async def trace_operation(self, operation_name: str, span_type: SpanType,
                            business_context: Optional[BusinessContext] = None,
                            **span_attributes):
        """Async context manager for tracing operations"""
        if not OTEL_AVAILABLE or not self.tracer:
            # Fallback to simple logging
            start_time = time.time()
            logger.info("operation_started", operation=operation_name, span_type=span_type.value)
            try:
                yield None
                duration = (time.time() - start_time) * 1000
                logger.info("operation_completed", 
                          operation=operation_name, 
                          duration_ms=duration)
            except Exception as e:
                duration = (time.time() - start_time) * 1000
                logger.error("operation_failed", 
                           operation=operation_name, 
                           duration_ms=duration,
                           error=str(e))
                raise
            return
        
        # Determine span kind
        span_kind_map = {
            SpanType.EXTERNAL_API: SpanKind.CLIENT,
            SpanType.PMS_OPERATION: SpanKind.CLIENT,
            SpanType.WEBHOOK_PROCESSING: SpanKind.SERVER,
            SpanType.DATABASE_OPERATION: SpanKind.CLIENT,
            SpanType.CACHE_OPERATION: SpanKind.CLIENT
        }
        span_kind = span_kind_map.get(span_type, SpanKind.INTERNAL)
        
        with self.tracer.start_as_current_span(
            operation_name,
            kind=span_kind
        ) as span:
            span_id = str(uuid.uuid4())
            
            try:
                # Set span attributes
                span.set_attribute("service.name", self.service_name)
                span.set_attribute("span.type", span_type.value)
                span.set_attribute("span.id", span_id)
                
                # Add custom attributes
                for key, value in span_attributes.items():
                    span.set_attribute(key, str(value))
                
                # Add business context attributes
                if business_context:
                    self.set_business_context(span_id, business_context)
                    
                    if business_context.hotel_id:
                        span.set_attribute("business.hotel_id", business_context.hotel_id)
                    if business_context.call_id:
                        span.set_attribute("business.call_id", business_context.call_id)
                    if business_context.guest_id:
                        span.set_attribute("business.guest_id", business_context.guest_id)
                    if business_context.language:
                        span.set_attribute("business.language", business_context.language)
                    if business_context.call_type:
                        span.set_attribute("business.call_type", business_context.call_type)
                    if business_context.pms_type:
                        span.set_attribute("business.pms_type", business_context.pms_type)
                    if business_context.correlation_id:
                        span.set_attribute("business.correlation_id", business_context.correlation_id)
                    
                    # Add custom attributes
                    for key, value in business_context.custom_attributes.items():
                        span.set_attribute(f"business.{key}", str(value))
                
                # Initialize metrics
                start_time = time.time()
                self.trace_metrics[span_id] = TraceMetrics(start_time=start_time)
                self.active_spans[span_id] = span
                
                logger.info("span_started", 
                          operation=operation_name, 
                          span_type=span_type.value,
                          span_id=span_id)
                
                yield span
                
                # Mark as successful
                span.set_status(Status(StatusCode.OK))
                self.trace_metrics[span_id].success_count += 1
                
            except Exception as e:
                # Record error
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                self.trace_metrics[span_id].error_count += 1
                
                logger.error("span_error", 
                           operation=operation_name,
                           span_id=span_id,
                           error=str(e))
                raise
            
            finally:
                # Calculate duration
                end_time = time.time()
                duration_ms = (end_time - start_time) * 1000
                
                span.set_attribute("duration_ms", duration_ms)
                
                # Update metrics
                if span_id in self.trace_metrics:
                    self.trace_metrics[span_id].end_time = end_time
                    self.trace_metrics[span_id].duration_ms = duration_ms
                
                # Clean up
                self.active_spans.pop(span_id, None)
                
                logger.info("span_completed", 
                          operation=operation_name,
                          span_id=span_id,
                          duration_ms=duration_ms)
    
    @contextmanager
    def trace_sync_operation(self, operation_name: str, span_type: SpanType,
                           business_context: Optional[BusinessContext] = None,
                           **span_attributes):
        """Synchronous context manager for tracing operations"""
        if not OTEL_AVAILABLE or not self.tracer:
            # Fallback to simple logging
            start_time = time.time()
            logger.info("sync_operation_started", operation=operation_name, span_type=span_type.value)
            try:
                yield None
                duration = (time.time() - start_time) * 1000
                logger.info("sync_operation_completed", 
                          operation=operation_name, 
                          duration_ms=duration)
            except Exception as e:
                duration = (time.time() - start_time) * 1000
                logger.error("sync_operation_failed", 
                           operation=operation_name, 
                           duration_ms=duration,
                           error=str(e))
                raise
            return
        
        with self.tracer.start_as_current_span(operation_name) as span:
            span_id = str(uuid.uuid4())
            
            try:
                # Set span attributes (similar to async version)
                span.set_attribute("service.name", self.service_name)
                span.set_attribute("span.type", span_type.value)
                span.set_attribute("span.id", span_id)
                
                for key, value in span_attributes.items():
                    span.set_attribute(key, str(value))
                
                if business_context:
                    self.set_business_context(span_id, business_context)
                    # Add business context attributes (same as async)
                
                start_time = time.time()
                self.trace_metrics[span_id] = TraceMetrics(start_time=start_time)
                
                yield span
                
                span.set_status(Status(StatusCode.OK))
                self.trace_metrics[span_id].success_count += 1
                
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                self.trace_metrics[span_id].error_count += 1
                raise
            
            finally:
                end_time = time.time()
                duration_ms = (end_time - start_time) * 1000
                span.set_attribute("duration_ms", duration_ms)
                
                if span_id in self.trace_metrics:
                    self.trace_metrics[span_id].end_time = end_time
                    self.trace_metrics[span_id].duration_ms = duration_ms
    
    def add_span_event(self, span_id: str, event_name: str, attributes: Dict[str, Any] = None):
        """Add an event to an active span"""
        if span_id in self.active_spans and OTEL_AVAILABLE:
            span = self.active_spans[span_id]
            span.add_event(event_name, attributes or {})
    
    def set_span_attribute(self, span_id: str, key: str, value: Any):
        """Set an attribute on an active span"""
        if span_id in self.active_spans and OTEL_AVAILABLE:
            span = self.active_spans[span_id]
            span.set_attribute(key, str(value))
    
    def record_custom_metric(self, span_id: str, metric_name: str, value: float):
        """Record a custom metric for a span"""
        if span_id in self.trace_metrics:
            self.trace_metrics[span_id].custom_metrics[metric_name] = value
    
    def get_trace_context_headers(self) -> Dict[str, str]:
        """Get trace context headers for propagation"""
        if not OTEL_AVAILABLE:
            return {}
        
        headers = {}
        inject(headers)
        return headers
    
    def extract_trace_context(self, headers: Dict[str, str]):
        """Extract trace context from headers"""
        if not OTEL_AVAILABLE:
            return
        
        ctx = extract(headers)
        attach(ctx)
    
    def create_child_span(self, parent_span_id: str, operation_name: str, 
                         span_type: SpanType, **attributes):
        """Create a child span"""
        if not OTEL_AVAILABLE or not self.tracer:
            return None
        
        parent_span = self.active_spans.get(parent_span_id)
        if not parent_span:
            return None
        
        with trace.use_span(parent_span):
            return self.tracer.start_span(operation_name, **attributes)
    
    def get_current_trace_id(self) -> Optional[str]:
        """Get current trace ID"""
        if not OTEL_AVAILABLE:
            return None
        
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            return format(current_span.get_span_context().trace_id, '032x')
        return None
    
    def get_current_span_id(self) -> Optional[str]:
        """Get current span ID"""
        if not OTEL_AVAILABLE:
            return None
        
        current_span = trace.get_current_span()
        if current_span and current_span.get_span_context().is_valid:
            return format(current_span.get_span_context().span_id, '016x')
        return None
    
    def flush_traces(self):
        """Flush all pending traces"""
        if OTEL_AVAILABLE and trace.get_tracer_provider():
            for processor in trace.get_tracer_provider()._active_span_processor._span_processors:
                if hasattr(processor, 'force_flush'):
                    processor.force_flush()


# Global tracer instance
enhanced_tracer = EnhancedTracer()


# Decorator for automatic tracing
def trace_function(operation_name: str = None, span_type: SpanType = SpanType.AI_PROCESSING):
    """Decorator to automatically trace function calls"""
    def decorator(func: Callable):
        async def async_wrapper(*args, **kwargs):
            op_name = operation_name or f"{func.__module__}.{func.__name__}"
            async with enhanced_tracer.trace_operation(op_name, span_type):
                return await func(*args, **kwargs)
        
        def sync_wrapper(*args, **kwargs):
            op_name = operation_name or f"{func.__module__}.{func.__name__}"
            with enhanced_tracer.trace_sync_operation(op_name, span_type):
                return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Utility functions for common tracing patterns
async def trace_call_handling(call_id: str, hotel_id: str, language: str):
    """Trace call handling operations"""
    business_context = BusinessContext(
        call_id=call_id,
        hotel_id=hotel_id,
        language=language,
        call_type="inbound",
        correlation_id=str(uuid.uuid4())
    )
    
    return enhanced_tracer.trace_operation(
        "call_handling",
        SpanType.CALL_HANDLING,
        business_context=business_context
    )


async def trace_pms_operation(hotel_id: str, pms_type: str, operation: str):
    """Trace PMS operations"""
    business_context = BusinessContext(
        hotel_id=hotel_id,
        pms_type=pms_type,
        correlation_id=str(uuid.uuid4())
    )
    
    return enhanced_tracer.trace_operation(
        f"pms_{operation}",
        SpanType.PMS_OPERATION,
        business_context=business_context,
        pms_operation=operation
    )


def trace_authentication(user_id: str = None, session_id: str = None):
    """Trace authentication operations"""
    business_context = BusinessContext(
        user_id=user_id,
        session_id=session_id,
        correlation_id=str(uuid.uuid4())
    )
    
    return enhanced_tracer.trace_sync_operation(
        "authentication",
        SpanType.AUTHENTICATION,
        business_context=business_context
    )


# Initialize tracing on module import
if OTEL_AVAILABLE:
    logger.info("distributed_tracing_module_loaded", otel_available=True)
else:
    logger.warning("distributed_tracing_module_loaded", 
                  otel_available=False,
                  message="OpenTelemetry not available, using fallback logging")