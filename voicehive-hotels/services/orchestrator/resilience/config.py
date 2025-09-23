"""
Configuration for Rate Limiting and Circuit Breaker Infrastructure
Centralized configuration for all resilience patterns
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field

from rate_limiter import RateLimitConfig, RateLimitRule, RateLimitAlgorithm
from circuit_breaker import CircuitBreakerConfig
from backpressure_handler import BackpressureConfig, BackpressureStrategy


@dataclass
class ResilienceConfig:
    """Main configuration class for all resilience features"""
    
    # Redis configuration
    redis_url: str = "redis://localhost:6379"
    redis_max_connections: int = 20
    
    # Rate limiting configuration
    rate_limiting_enabled: bool = True
    rate_limiting_rules: List[Dict] = field(default_factory=list)
    default_rate_limit_config: Optional[RateLimitConfig] = None
    
    # Circuit breaker configuration
    circuit_breakers_enabled: bool = True
    circuit_breaker_configs: Dict[str, CircuitBreakerConfig] = field(default_factory=dict)
    
    # Backpressure configuration
    backpressure_enabled: bool = True
    backpressure_configs: Dict[str, BackpressureConfig] = field(default_factory=dict)
    
    # Internal service bypass
    internal_service_headers: List[str] = field(default_factory=lambda: [
        "X-Internal-Service",
        "X-Service-Token",
        "X-Kubernetes-Service"
    ])
    
    # Excluded paths from rate limiting
    excluded_paths: List[str] = field(default_factory=lambda: [
        "/healthz",
        "/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/_internal"
    ])


def create_default_resilience_config() -> ResilienceConfig:
    """Create default resilience configuration"""
    
    # Default rate limiting configuration
    default_rate_limit = RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        requests_per_day=10000,
        burst_limit=10,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW,
        bypass_internal=True
    )
    
    # Rate limiting rules for different endpoints
    rate_limiting_rules = [
        # Authentication endpoints - strict limits
        {
            "path_pattern": r"/auth/login",
            "method": "POST",
            "config": {
                "requests_per_minute": 5,
                "requests_per_hour": 20,
                "requests_per_day": 100,
                "algorithm": "sliding_window",
                "bypass_internal": True
            }
        },
        {
            "path_pattern": r"/auth/register",
            "method": "POST", 
            "config": {
                "requests_per_minute": 3,
                "requests_per_hour": 10,
                "requests_per_day": 50,
                "algorithm": "sliding_window",
                "bypass_internal": True
            }
        },
        
        # API endpoints - moderate limits
        {
            "path_pattern": r"/api/.*",
            "config": {
                "requests_per_minute": 100,
                "requests_per_hour": 1000,
                "requests_per_day": 10000,
                "algorithm": "sliding_window",
                "bypass_internal": True
            }
        },
        
        # Webhook endpoints - higher limits for legitimate traffic
        {
            "path_pattern": r"/webhook/.*",
            "config": {
                "requests_per_minute": 200,
                "requests_per_hour": 2000,
                "requests_per_day": 20000,
                "algorithm": "token_bucket",
                "burst_limit": 50,
                "bypass_internal": True
            }
        },
        
        # Call endpoints - streaming audio needs higher limits
        {
            "path_pattern": r"/call/.*",
            "config": {
                "requests_per_minute": 500,
                "requests_per_hour": 5000,
                "requests_per_day": 50000,
                "algorithm": "token_bucket",
                "burst_limit": 100,
                "bypass_internal": True
            }
        },
        
        # GDPR endpoints - moderate limits
        {
            "path_pattern": r"/gdpr/.*",
            "config": {
                "requests_per_minute": 30,
                "requests_per_hour": 300,
                "requests_per_day": 1000,
                "algorithm": "sliding_window",
                "bypass_internal": True
            }
        },
        
        # Anonymous users - stricter limits
        {
            "path_pattern": r".*",
            "client_type": "anonymous",
            "config": {
                "requests_per_minute": 20,
                "requests_per_hour": 200,
                "requests_per_day": 1000,
                "algorithm": "sliding_window",
                "bypass_internal": False
            }
        },
        
        # Authenticated users - higher limits
        {
            "path_pattern": r".*",
            "client_type": "authenticated",
            "config": {
                "requests_per_minute": 200,
                "requests_per_hour": 2000,
                "requests_per_day": 20000,
                "algorithm": "sliding_window",
                "bypass_internal": True
            }
        }
    ]
    
    # Circuit breaker configurations for different services
    circuit_breaker_configs = {
        "tts_service": CircuitBreakerConfig(
            name="tts_service",
            failure_threshold=5,
            recovery_timeout=60,
            success_threshold=3,
            timeout=30.0,
            expected_exception=(Exception,)
        ),
        
        "pms_connector": CircuitBreakerConfig(
            name="pms_connector",
            failure_threshold=3,
            recovery_timeout=30,
            success_threshold=2,
            timeout=15.0,
            expected_exception=(Exception,)
        ),
        
        "livekit_service": CircuitBreakerConfig(
            name="livekit_service",
            failure_threshold=5,
            recovery_timeout=45,
            success_threshold=3,
            timeout=20.0,
            expected_exception=(Exception,)
        ),
        
        "vault_service": CircuitBreakerConfig(
            name="vault_service",
            failure_threshold=3,
            recovery_timeout=20,
            success_threshold=2,
            timeout=10.0,
            expected_exception=(Exception,)
        ),
        
        "external_api": CircuitBreakerConfig(
            name="external_api",
            failure_threshold=5,
            recovery_timeout=60,
            success_threshold=3,
            timeout=25.0,
            expected_exception=(Exception,)
        )
    }
    
    # Backpressure configurations for different operations
    backpressure_configs = {
        "tts_synthesis": BackpressureConfig(
            max_queue_size=100,
            max_memory_mb=50,
            strategy=BackpressureStrategy.ADAPTIVE,
            timeout_seconds=30.0,
            warning_threshold=0.8,
            adaptive_threshold=0.9
        ),
        
        "audio_streaming": BackpressureConfig(
            max_queue_size=200,
            max_memory_mb=100,
            strategy=BackpressureStrategy.DROP_OLDEST,
            timeout_seconds=10.0,
            warning_threshold=0.7,
            adaptive_threshold=0.85
        ),
        
        "pms_operations": BackpressureConfig(
            max_queue_size=50,
            max_memory_mb=25,
            strategy=BackpressureStrategy.BLOCK,
            timeout_seconds=20.0,
            warning_threshold=0.8,
            adaptive_threshold=0.9
        ),
        
        "webhook_processing": BackpressureConfig(
            max_queue_size=500,
            max_memory_mb=200,
            strategy=BackpressureStrategy.ADAPTIVE,
            timeout_seconds=15.0,
            warning_threshold=0.75,
            adaptive_threshold=0.9
        ),
        
        "gdpr_operations": BackpressureConfig(
            max_queue_size=30,
            max_memory_mb=15,
            strategy=BackpressureStrategy.BLOCK,
            timeout_seconds=60.0,
            warning_threshold=0.8,
            adaptive_threshold=0.9
        )
    }
    
    return ResilienceConfig(
        rate_limiting_enabled=True,
        rate_limiting_rules=rate_limiting_rules,
        default_rate_limit_config=default_rate_limit,
        circuit_breakers_enabled=True,
        circuit_breaker_configs=circuit_breaker_configs,
        backpressure_enabled=True,
        backpressure_configs=backpressure_configs
    )


def create_production_resilience_config() -> ResilienceConfig:
    """Create production-optimized resilience configuration"""
    
    config = create_default_resilience_config()
    
    # Adjust for production workloads
    config.redis_max_connections = 50
    
    # Stricter rate limits for production
    production_rules = []
    for rule in config.rate_limiting_rules:
        rule_config = rule.get("config", {})
        
        # Reduce limits by 20% for production safety
        if "requests_per_minute" in rule_config:
            rule_config["requests_per_minute"] = int(rule_config["requests_per_minute"] * 0.8)
        if "requests_per_hour" in rule_config:
            rule_config["requests_per_hour"] = int(rule_config["requests_per_hour"] * 0.8)
        if "requests_per_day" in rule_config:
            rule_config["requests_per_day"] = int(rule_config["requests_per_day"] * 0.8)
        
        production_rules.append(rule)
    
    config.rate_limiting_rules = production_rules
    
    # More aggressive circuit breaker settings for production
    for cb_config in config.circuit_breaker_configs.values():
        cb_config.failure_threshold = max(3, cb_config.failure_threshold - 1)
        cb_config.recovery_timeout = min(120, cb_config.recovery_timeout + 30)
    
    # Smaller queue sizes for production to prevent memory issues
    for bp_config in config.backpressure_configs.values():
        bp_config.max_queue_size = int(bp_config.max_queue_size * 0.7)
        bp_config.max_memory_mb = int(bp_config.max_memory_mb * 0.7)
        bp_config.timeout_seconds = min(60, bp_config.timeout_seconds + 10)
    
    return config


def create_development_resilience_config() -> ResilienceConfig:
    """Create development-friendly resilience configuration"""
    
    config = create_default_resilience_config()
    
    # More lenient settings for development
    config.redis_max_connections = 10
    
    # Higher rate limits for development
    dev_rules = []
    for rule in config.rate_limiting_rules:
        rule_config = rule.get("config", {})
        
        # Increase limits by 50% for development
        if "requests_per_minute" in rule_config:
            rule_config["requests_per_minute"] = int(rule_config["requests_per_minute"] * 1.5)
        if "requests_per_hour" in rule_config:
            rule_config["requests_per_hour"] = int(rule_config["requests_per_hour"] * 1.5)
        if "requests_per_day" in rule_config:
            rule_config["requests_per_day"] = int(rule_config["requests_per_day"] * 1.5)
        
        dev_rules.append(rule)
    
    config.rate_limiting_rules = dev_rules
    
    # More lenient circuit breaker settings for development
    for cb_config in config.circuit_breaker_configs.values():
        cb_config.failure_threshold = cb_config.failure_threshold + 2
        cb_config.recovery_timeout = max(10, cb_config.recovery_timeout - 20)
    
    return config


def get_resilience_config(environment: str = "production") -> ResilienceConfig:
    """Get resilience configuration based on environment"""
    
    if environment.lower() in ["prod", "production"]:
        return create_production_resilience_config()
    elif environment.lower() in ["dev", "development", "local"]:
        return create_development_resilience_config()
    else:
        return create_default_resilience_config()


# Environment-specific configurations
PRODUCTION_CONFIG = create_production_resilience_config()
DEVELOPMENT_CONFIG = create_development_resilience_config()
DEFAULT_CONFIG = create_default_resilience_config()