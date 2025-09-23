"""
Resilience Manager - Coordinates Rate Limiting, Circuit Breakers, and Backpressure
Central management for all resilience patterns in the application
"""

import asyncio
from typing import Dict, Optional, Any, List
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import FastAPI

from rate_limiter import RateLimiter, RateLimitRule, RateLimitConfig
from circuit_breaker import CircuitBreakerManager, CircuitBreakerConfig
from backpressure_handler import BackpressureManager, BackpressureConfig
from rate_limit_middleware import RateLimitMiddleware, create_rate_limit_rules
from resilience_config import ResilienceConfig, get_resilience_config
from enhanced_tts_client import TTSClientManager
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.resilience_manager")


class ResilienceManager:
    """
    Central manager for all resilience patterns
    """
    
    def __init__(
        self, 
        config: Optional[ResilienceConfig] = None,
        environment: str = "production"
    ):
        self.config = config or get_resilience_config(environment)
        self.environment = environment
        
        # Core components
        self.redis_client: Optional[aioredis.Redis] = None
        self.rate_limiter: Optional[RateLimiter] = None
        self.circuit_breaker_manager: Optional[CircuitBreakerManager] = None
        self.backpressure_manager: Optional[BackpressureManager] = None
        self.tts_client_manager: Optional[TTSClientManager] = None
        
        # Middleware
        self.rate_limit_middleware: Optional[RateLimitMiddleware] = None
        
        # State
        self.initialized = False
        self.startup_time: Optional[datetime] = None
        
        logger.info("resilience_manager_created", environment=environment)
    
    async def initialize(self) -> bool:
        """Initialize all resilience components"""
        
        if self.initialized:
            logger.warning("resilience_manager_already_initialized")
            return True
        
        try:
            self.startup_time = datetime.now()
            
            # Initialize Redis connection
            await self._initialize_redis()
            
            # Initialize rate limiter
            if self.config.rate_limiting_enabled:
                await self._initialize_rate_limiter()
            
            # Initialize circuit breaker manager
            if self.config.circuit_breakers_enabled:
                await self._initialize_circuit_breakers()
            
            # Initialize backpressure manager
            if self.config.backpressure_enabled:
                await self._initialize_backpressure()
            
            # Initialize TTS client manager
            await self._initialize_tts_manager()
            
            self.initialized = True
            
            logger.info(
                "resilience_manager_initialized",
                environment=self.environment,
                redis_connected=self.redis_client is not None,
                rate_limiting=self.config.rate_limiting_enabled,
                circuit_breakers=self.config.circuit_breakers_enabled,
                backpressure=self.config.backpressure_enabled
            )
            
            return True
            
        except Exception as e:
            logger.error("resilience_manager_initialization_failed", error=str(e))
            return False
    
    async def _initialize_redis(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = aioredis.from_url(
                self.config.redis_url,
                decode_responses=False,
                max_connections=self.config.redis_max_connections,
                retry_on_timeout=True,
                socket_keepalive=True,
                socket_keepalive_options={}
            )
            
            # Test connection
            await self.redis_client.ping()
            
            logger.info("redis_connection_established", url=self.config.redis_url)
            
        except Exception as e:
            logger.error("redis_connection_failed", error=str(e))
            self.redis_client = None
            # Continue without Redis - components will work in local mode
    
    async def _initialize_rate_limiter(self):
        """Initialize rate limiter with configured rules"""
        if not self.redis_client:
            logger.warning("rate_limiter_disabled_no_redis")
            return
        
        self.rate_limiter = RateLimiter(self.redis_client)
        
        # Add configured rules
        for rule_config in self.config.rate_limiting_rules:
            try:
                # Convert config dict to RateLimitConfig object
                config_dict = rule_config.get("config", {})
                rate_config = RateLimitConfig(**config_dict)
                
                rule = RateLimitRule(
                    path_pattern=rule_config["path_pattern"],
                    method=rule_config.get("method"),
                    client_type=rule_config.get("client_type"),
                    config=rate_config
                )
                
                self.rate_limiter.add_rule(rule)
                
            except Exception as e:
                logger.error("failed_to_add_rate_limit_rule", rule=rule_config, error=str(e))
        
        logger.info("rate_limiter_initialized", rules_count=len(self.config.rate_limiting_rules))
    
    async def _initialize_circuit_breakers(self):
        """Initialize circuit breaker manager"""
        self.circuit_breaker_manager = CircuitBreakerManager(self.redis_client)
        
        # Pre-create circuit breakers for configured services
        for name, config in self.config.circuit_breaker_configs.items():
            try:
                self.circuit_breaker_manager.get_or_create_breaker(name, config)
                logger.debug("circuit_breaker_created", name=name)
            except Exception as e:
                logger.error("failed_to_create_circuit_breaker", name=name, error=str(e))
        
        logger.info(
            "circuit_breaker_manager_initialized", 
            breakers_count=len(self.config.circuit_breaker_configs)
        )
    
    async def _initialize_backpressure(self):
        """Initialize backpressure manager"""
        self.backpressure_manager = BackpressureManager(self.redis_client)
        
        # Pre-create backpressure handlers for configured operations
        for name, config in self.config.backpressure_configs.items():
            try:
                self.backpressure_manager.create_handler(name, config)
                logger.debug("backpressure_handler_created", name=name)
            except Exception as e:
                logger.error("failed_to_create_backpressure_handler", name=name, error=str(e))
        
        logger.info(
            "backpressure_manager_initialized",
            handlers_count=len(self.config.backpressure_configs)
        )
    
    async def _initialize_tts_manager(self):
        """Initialize TTS client manager"""
        self.tts_client_manager = TTSClientManager(self.redis_client)
        logger.info("tts_client_manager_initialized")
    
    def create_rate_limit_middleware(self) -> Optional[RateLimitMiddleware]:
        """Create rate limiting middleware for FastAPI"""
        
        if not self.config.rate_limiting_enabled or not self.redis_client:
            logger.warning("rate_limit_middleware_disabled")
            return None
        
        # Convert config rules to middleware format
        middleware_rules = []
        for rule_config in self.config.rate_limiting_rules:
            middleware_rules.append({
                "path_pattern": rule_config["path_pattern"],
                "method": rule_config.get("method"),
                "client_type": rule_config.get("client_type"),
                "config": rule_config["config"]
            })
        
        self.rate_limit_middleware = RateLimitMiddleware(
            app=None,  # Will be set when added to FastAPI app
            redis_url=self.config.redis_url,
            default_config=self.config.default_rate_limit_config,
            rules=middleware_rules
        )
        
        logger.info("rate_limit_middleware_created")
        return self.rate_limit_middleware
    
    def get_circuit_breaker(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """Get or create a circuit breaker"""
        if not self.circuit_breaker_manager:
            logger.warning("circuit_breaker_manager_not_initialized")
            return None
        
        return self.circuit_breaker_manager.get_or_create_breaker(name, config)
    
    def get_backpressure_handler(self, name: str, config: Optional[BackpressureConfig] = None):
        """Get or create a backpressure handler"""
        if not self.backpressure_manager:
            logger.warning("backpressure_manager_not_initialized")
            return None
        
        if name not in self.backpressure_manager.handlers:
            if config is None:
                config = BackpressureConfig()
            return self.backpressure_manager.create_handler(name, config)
        
        return self.backpressure_manager.get_handler(name)
    
    def get_tts_client(self, name: str = "default"):
        """Get or create a TTS client"""
        if not self.tts_client_manager:
            logger.warning("tts_client_manager_not_initialized")
            return None
        
        client = self.tts_client_manager.get_client(name)
        if client is None:
            # Create default client
            circuit_config = self.config.circuit_breaker_configs.get("tts_service")
            backpressure_config = self.config.backpressure_configs.get("tts_synthesis")
            
            client = self.tts_client_manager.create_client(
                name,
                circuit_breaker_config=circuit_config,
                backpressure_config=backpressure_config
            )
        
        return client
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all resilience components"""
        
        status = {
            "initialized": self.initialized,
            "startup_time": self.startup_time.isoformat() if self.startup_time else None,
            "environment": self.environment,
            "redis_connected": False,
            "components": {}
        }
        
        # Check Redis connection
        if self.redis_client:
            try:
                await self.redis_client.ping()
                status["redis_connected"] = True
            except Exception as e:
                logger.warning("redis_health_check_failed", error=str(e))
        
        # Check rate limiter
        if self.rate_limiter:
            status["components"]["rate_limiter"] = {
                "enabled": True,
                "rules_count": len(self.rate_limiter.rules)
            }
        
        # Check circuit breakers
        if self.circuit_breaker_manager:
            try:
                cb_stats = await self.circuit_breaker_manager.get_all_stats()
                status["components"]["circuit_breakers"] = {
                    "enabled": True,
                    "breakers_count": len(cb_stats),
                    "stats": {name: stats.dict() for name, stats in cb_stats.items()}
                }
            except Exception as e:
                logger.error("circuit_breaker_health_check_failed", error=str(e))
                status["components"]["circuit_breakers"] = {"enabled": True, "error": str(e)}
        
        # Check backpressure handlers
        if self.backpressure_manager:
            try:
                bp_stats = await self.backpressure_manager.get_all_stats()
                status["components"]["backpressure"] = {
                    "enabled": True,
                    "handlers_count": len(bp_stats),
                    "stats": {name: stats.dict() for name, stats in bp_stats.items()}
                }
            except Exception as e:
                logger.error("backpressure_health_check_failed", error=str(e))
                status["components"]["backpressure"] = {"enabled": True, "error": str(e)}
        
        # Check TTS clients
        if self.tts_client_manager:
            try:
                tts_health = await self.tts_client_manager.health_check_all()
                status["components"]["tts_clients"] = {
                    "enabled": True,
                    "clients_count": len(tts_health),
                    "health": tts_health
                }
            except Exception as e:
                logger.error("tts_health_check_failed", error=str(e))
                status["components"]["tts_clients"] = {"enabled": True, "error": str(e)}
        
        return status
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get metrics from all resilience components"""
        
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "environment": self.environment
        }
        
        # Rate limiter metrics
        if self.rate_limiter and self.redis_client:
            try:
                # Get sample client stats (this would need to be implemented)
                metrics["rate_limiter"] = {
                    "rules_count": len(self.rate_limiter.rules),
                    "redis_connected": True
                }
            except Exception as e:
                logger.error("rate_limiter_metrics_failed", error=str(e))
        
        # Circuit breaker metrics
        if self.circuit_breaker_manager:
            try:
                cb_stats = await self.circuit_breaker_manager.get_all_stats()
                metrics["circuit_breakers"] = {
                    name: {
                        "state": stats.state.value,
                        "failure_count": stats.failure_count,
                        "success_count": stats.success_count,
                        "total_requests": stats.total_requests,
                        "total_failures": stats.total_failures,
                        "total_successes": stats.total_successes
                    }
                    for name, stats in cb_stats.items()
                }
            except Exception as e:
                logger.error("circuit_breaker_metrics_failed", error=str(e))
        
        # Backpressure metrics
        if self.backpressure_manager:
            try:
                bp_stats = await self.backpressure_manager.get_all_stats()
                metrics["backpressure"] = {
                    name: {
                        "current_queue_size": stats.current_queue_size,
                        "max_queue_size": stats.max_queue_size,
                        "current_memory_mb": stats.current_memory_mb,
                        "total_processed": stats.total_processed,
                        "total_dropped": stats.total_dropped,
                        "total_blocked": stats.total_blocked,
                        "strategy": stats.strategy.value
                    }
                    for name, stats in bp_stats.items()
                }
            except Exception as e:
                logger.error("backpressure_metrics_failed", error=str(e))
        
        # TTS client metrics
        if self.tts_client_manager:
            try:
                tts_stats = await self.tts_client_manager.get_all_stats()
                metrics["tts_clients"] = tts_stats
            except Exception as e:
                logger.error("tts_metrics_failed", error=str(e))
        
        return metrics
    
    async def reset_all_circuit_breakers(self):
        """Reset all circuit breakers (admin function)"""
        if self.circuit_breaker_manager:
            await self.circuit_breaker_manager.reset_all()
            logger.info("all_circuit_breakers_reset")
        
        if self.tts_client_manager:
            await self.tts_client_manager.reset_all_circuit_breakers()
    
    async def shutdown(self):
        """Gracefully shutdown all resilience components"""
        
        logger.info("resilience_manager_shutdown_started")
        
        try:
            # Shutdown backpressure handlers
            if self.backpressure_manager:
                await self.backpressure_manager.shutdown_all()
            
            # Close TTS clients
            if self.tts_client_manager:
                await self.tts_client_manager.close_all()
            
            # Close Redis connection
            if self.redis_client:
                await self.redis_client.close()
            
            self.initialized = False
            
            logger.info("resilience_manager_shutdown_completed")
            
        except Exception as e:
            logger.error("resilience_manager_shutdown_error", error=str(e))


# Global resilience manager instance
_resilience_manager: Optional[ResilienceManager] = None


def get_resilience_manager(
    config: Optional[ResilienceConfig] = None,
    environment: str = "production"
) -> ResilienceManager:
    """Get or create global resilience manager"""
    global _resilience_manager
    
    if _resilience_manager is None:
        _resilience_manager = ResilienceManager(config, environment)
        logger.info("global_resilience_manager_created", environment=environment)
    
    return _resilience_manager


async def initialize_resilience_for_app(
    app: FastAPI,
    config: Optional[ResilienceConfig] = None,
    environment: str = "production"
) -> ResilienceManager:
    """Initialize resilience components for a FastAPI application"""
    
    manager = get_resilience_manager(config, environment)
    
    # Initialize the manager
    success = await manager.initialize()
    if not success:
        logger.error("failed_to_initialize_resilience_manager")
        return manager
    
    # Add rate limiting middleware
    if manager.config.rate_limiting_enabled:
        middleware = manager.create_rate_limit_middleware()
        if middleware:
            app.add_middleware(RateLimitMiddleware, **middleware.__dict__)
            logger.info("rate_limit_middleware_added_to_app")
    
    # Store manager in app state for access in endpoints
    app.state.resilience_manager = manager
    
    # Add shutdown handler
    @app.on_event("shutdown")
    async def shutdown_resilience():
        await manager.shutdown()
    
    logger.info("resilience_initialized_for_app", environment=environment)
    return manager