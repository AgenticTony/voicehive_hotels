"""
Resilience Management API Endpoints
Provides monitoring and management capabilities for rate limiting, circuit breakers, and backpressure
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from resilience_manager import ResilienceManager, get_resilience_manager
from auth_middleware import require_admin_role, get_current_user
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.resilience_api")

router = APIRouter(prefix="/resilience", tags=["resilience"])


class ResilienceHealthResponse(BaseModel):
    """Response model for resilience health check"""
    status: str
    initialized: bool
    startup_time: Optional[str]
    environment: str
    redis_connected: bool
    components: Dict[str, Any]


class ResilienceMetricsResponse(BaseModel):
    """Response model for resilience metrics"""
    timestamp: str
    environment: str
    rate_limiter: Optional[Dict[str, Any]] = None
    circuit_breakers: Optional[Dict[str, Any]] = None
    backpressure: Optional[Dict[str, Any]] = None
    tts_clients: Optional[Dict[str, Any]] = None


class CircuitBreakerStatsResponse(BaseModel):
    """Response model for circuit breaker statistics"""
    name: str
    state: str
    failure_count: int
    success_count: int
    total_requests: int
    total_failures: int
    total_successes: int
    last_failure_time: Optional[str]
    last_success_time: Optional[str]
    next_attempt_time: Optional[str]


class BackpressureStatsResponse(BaseModel):
    """Response model for backpressure statistics"""
    name: str
    current_queue_size: int
    max_queue_size: int
    current_memory_mb: float
    max_memory_mb: float
    total_processed: int
    total_dropped: int
    total_blocked: int
    average_processing_time: float
    strategy: str


class RateLimitStatsResponse(BaseModel):
    """Response model for rate limit statistics"""
    client_id: str
    stats: Dict[str, Dict[str, int]]


def get_resilience_manager_dependency() -> ResilienceManager:
    """Dependency to get resilience manager"""
    manager = get_resilience_manager()
    if not manager.initialized:
        raise HTTPException(
            status_code=503,
            detail="Resilience manager not initialized"
        )
    return manager


@router.get("/health", response_model=ResilienceHealthResponse)
async def get_resilience_health(
    manager: ResilienceManager = Depends(get_resilience_manager_dependency)
):
    """Get health status of all resilience components"""
    
    try:
        health_data = await manager.get_health_status()
        
        return ResilienceHealthResponse(
            status="healthy" if health_data["initialized"] else "unhealthy",
            **health_data
        )
        
    except Exception as e:
        logger.error("resilience_health_check_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Health check failed: {str(e)}"
        )


@router.get("/metrics", response_model=ResilienceMetricsResponse)
async def get_resilience_metrics(
    manager: ResilienceManager = Depends(get_resilience_manager_dependency)
):
    """Get metrics from all resilience components"""
    
    try:
        metrics_data = await manager.get_metrics()
        return ResilienceMetricsResponse(**metrics_data)
        
    except Exception as e:
        logger.error("resilience_metrics_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Metrics collection failed: {str(e)}"
        )


@router.get("/circuit-breakers", response_model=List[CircuitBreakerStatsResponse])
async def get_circuit_breaker_stats(
    manager: ResilienceManager = Depends(get_resilience_manager_dependency)
):
    """Get statistics for all circuit breakers"""
    
    try:
        if not manager.circuit_breaker_manager:
            raise HTTPException(
                status_code=404,
                detail="Circuit breaker manager not available"
            )
        
        stats = await manager.circuit_breaker_manager.get_all_stats()
        
        response = []
        for name, cb_stats in stats.items():
            response.append(CircuitBreakerStatsResponse(
                name=name,
                state=cb_stats.state.value,
                failure_count=cb_stats.failure_count,
                success_count=cb_stats.success_count,
                total_requests=cb_stats.total_requests,
                total_failures=cb_stats.total_failures,
                total_successes=cb_stats.total_successes,
                last_failure_time=cb_stats.last_failure_time.isoformat() if cb_stats.last_failure_time else None,
                last_success_time=cb_stats.last_success_time.isoformat() if cb_stats.last_success_time else None,
                next_attempt_time=cb_stats.next_attempt_time.isoformat() if cb_stats.next_attempt_time else None
            ))
        
        return response
        
    except Exception as e:
        logger.error("circuit_breaker_stats_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Circuit breaker stats failed: {str(e)}"
        )


@router.get("/circuit-breakers/{name}", response_model=CircuitBreakerStatsResponse)
async def get_circuit_breaker_stats_by_name(
    name: str,
    manager: ResilienceManager = Depends(get_resilience_manager_dependency)
):
    """Get statistics for a specific circuit breaker"""
    
    try:
        if not manager.circuit_breaker_manager:
            raise HTTPException(
                status_code=404,
                detail="Circuit breaker manager not available"
            )
        
        breaker = manager.circuit_breaker_manager.breakers.get(name)
        if not breaker:
            raise HTTPException(
                status_code=404,
                detail=f"Circuit breaker '{name}' not found"
            )
        
        stats = await breaker.get_stats()
        
        return CircuitBreakerStatsResponse(
            name=name,
            state=stats.state.value,
            failure_count=stats.failure_count,
            success_count=stats.success_count,
            total_requests=stats.total_requests,
            total_failures=stats.total_failures,
            total_successes=stats.total_successes,
            last_failure_time=stats.last_failure_time.isoformat() if stats.last_failure_time else None,
            last_success_time=stats.last_success_time.isoformat() if stats.last_success_time else None,
            next_attempt_time=stats.next_attempt_time.isoformat() if stats.next_attempt_time else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("circuit_breaker_stats_by_name_failed", name=name, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Circuit breaker stats failed: {str(e)}"
        )


@router.post("/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(
    name: str,
    manager: ResilienceManager = Depends(get_resilience_manager_dependency),
    current_user = Depends(require_admin_role)
):
    """Reset a specific circuit breaker (admin only)"""
    
    try:
        if not manager.circuit_breaker_manager:
            raise HTTPException(
                status_code=404,
                detail="Circuit breaker manager not available"
            )
        
        breaker = manager.circuit_breaker_manager.breakers.get(name)
        if not breaker:
            raise HTTPException(
                status_code=404,
                detail=f"Circuit breaker '{name}' not found"
            )
        
        await breaker.reset()
        
        logger.info("circuit_breaker_reset_by_admin", name=name, admin_user=current_user.get("user_id"))
        
        return {"message": f"Circuit breaker '{name}' reset successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("circuit_breaker_reset_failed", name=name, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Circuit breaker reset failed: {str(e)}"
        )


@router.post("/circuit-breakers/reset-all")
async def reset_all_circuit_breakers(
    manager: ResilienceManager = Depends(get_resilience_manager_dependency),
    current_user = Depends(require_admin_role)
):
    """Reset all circuit breakers (admin only)"""
    
    try:
        await manager.reset_all_circuit_breakers()
        
        logger.info("all_circuit_breakers_reset_by_admin", admin_user=current_user.get("user_id"))
        
        return {"message": "All circuit breakers reset successfully"}
        
    except Exception as e:
        logger.error("reset_all_circuit_breakers_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Reset all circuit breakers failed: {str(e)}"
        )


@router.get("/backpressure", response_model=List[BackpressureStatsResponse])
async def get_backpressure_stats(
    manager: ResilienceManager = Depends(get_resilience_manager_dependency)
):
    """Get statistics for all backpressure handlers"""
    
    try:
        if not manager.backpressure_manager:
            raise HTTPException(
                status_code=404,
                detail="Backpressure manager not available"
            )
        
        stats = await manager.backpressure_manager.get_all_stats()
        
        response = []
        for name, bp_stats in stats.items():
            response.append(BackpressureStatsResponse(
                name=name,
                current_queue_size=bp_stats.current_queue_size,
                max_queue_size=bp_stats.max_queue_size,
                current_memory_mb=bp_stats.current_memory_mb,
                max_memory_mb=bp_stats.max_memory_mb,
                total_processed=bp_stats.total_processed,
                total_dropped=bp_stats.total_dropped,
                total_blocked=bp_stats.total_blocked,
                average_processing_time=bp_stats.average_processing_time,
                strategy=bp_stats.strategy.value
            ))
        
        return response
        
    except Exception as e:
        logger.error("backpressure_stats_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Backpressure stats failed: {str(e)}"
        )


@router.get("/backpressure/{name}", response_model=BackpressureStatsResponse)
async def get_backpressure_stats_by_name(
    name: str,
    manager: ResilienceManager = Depends(get_resilience_manager_dependency)
):
    """Get statistics for a specific backpressure handler"""
    
    try:
        if not manager.backpressure_manager:
            raise HTTPException(
                status_code=404,
                detail="Backpressure manager not available"
            )
        
        handler = manager.backpressure_manager.get_handler(name)
        if not handler:
            raise HTTPException(
                status_code=404,
                detail=f"Backpressure handler '{name}' not found"
            )
        
        stats = await handler.get_stats()
        
        return BackpressureStatsResponse(
            name=name,
            current_queue_size=stats.current_queue_size,
            max_queue_size=stats.max_queue_size,
            current_memory_mb=stats.current_memory_mb,
            max_memory_mb=stats.max_memory_mb,
            total_processed=stats.total_processed,
            total_dropped=stats.total_dropped,
            total_blocked=stats.total_blocked,
            average_processing_time=stats.average_processing_time,
            strategy=stats.strategy.value
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("backpressure_stats_by_name_failed", name=name, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Backpressure stats failed: {str(e)}"
        )


@router.get("/rate-limits/{client_id}", response_model=RateLimitStatsResponse)
async def get_rate_limit_stats(
    client_id: str,
    manager: ResilienceManager = Depends(get_resilience_manager_dependency),
    current_user = Depends(require_admin_role)
):
    """Get rate limit statistics for a specific client (admin only)"""
    
    try:
        if not manager.rate_limiter:
            raise HTTPException(
                status_code=404,
                detail="Rate limiter not available"
            )
        
        stats = await manager.rate_limiter.get_client_stats(client_id)
        
        return RateLimitStatsResponse(
            client_id=client_id,
            stats=stats
        )
        
    except Exception as e:
        logger.error("rate_limit_stats_failed", client_id=client_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Rate limit stats failed: {str(e)}"
        )


@router.post("/rate-limits/{client_id}/reset")
async def reset_rate_limits(
    client_id: str,
    path: Optional[str] = Query(None, description="Optional path to reset (resets all if not specified)"),
    manager: ResilienceManager = Depends(get_resilience_manager_dependency),
    current_user = Depends(require_admin_role)
):
    """Reset rate limits for a specific client (admin only)"""
    
    try:
        if not manager.rate_limiter:
            raise HTTPException(
                status_code=404,
                detail="Rate limiter not available"
            )
        
        await manager.rate_limiter.reset_client_limits(client_id, path)
        
        logger.info(
            "rate_limits_reset_by_admin",
            client_id=client_id,
            path=path,
            admin_user=current_user.get("user_id")
        )
        
        message = f"Rate limits reset for client '{client_id}'"
        if path:
            message += f" and path '{path}'"
        
        return {"message": message}
        
    except Exception as e:
        logger.error("rate_limit_reset_failed", client_id=client_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Rate limit reset failed: {str(e)}"
        )


@router.get("/tts-clients")
async def get_tts_client_stats(
    manager: ResilienceManager = Depends(get_resilience_manager_dependency)
):
    """Get statistics for all TTS clients"""
    
    try:
        if not manager.tts_client_manager:
            raise HTTPException(
                status_code=404,
                detail="TTS client manager not available"
            )
        
        stats = await manager.tts_client_manager.get_all_stats()
        health = await manager.tts_client_manager.health_check_all()
        
        return {
            "stats": stats,
            "health": health
        }
        
    except Exception as e:
        logger.error("tts_client_stats_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"TTS client stats failed: {str(e)}"
        )


@router.post("/tts-clients/reset-circuit-breakers")
async def reset_tts_circuit_breakers(
    manager: ResilienceManager = Depends(get_resilience_manager_dependency),
    current_user = Depends(require_admin_role)
):
    """Reset circuit breakers for all TTS clients (admin only)"""
    
    try:
        if not manager.tts_client_manager:
            raise HTTPException(
                status_code=404,
                detail="TTS client manager not available"
            )
        
        await manager.tts_client_manager.reset_all_circuit_breakers()
        
        logger.info("tts_circuit_breakers_reset_by_admin", admin_user=current_user.get("user_id"))
        
        return {"message": "TTS circuit breakers reset successfully"}
        
    except Exception as e:
        logger.error("tts_circuit_breaker_reset_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"TTS circuit breaker reset failed: {str(e)}"
        )


@router.get("/config")
async def get_resilience_config(
    manager: ResilienceManager = Depends(get_resilience_manager_dependency),
    current_user = Depends(require_admin_role)
):
    """Get current resilience configuration (admin only)"""
    
    try:
        config_dict = {
            "environment": manager.environment,
            "redis_url": manager.config.redis_url,
            "redis_max_connections": manager.config.redis_max_connections,
            "rate_limiting_enabled": manager.config.rate_limiting_enabled,
            "circuit_breakers_enabled": manager.config.circuit_breakers_enabled,
            "backpressure_enabled": manager.config.backpressure_enabled,
            "excluded_paths": manager.config.excluded_paths,
            "internal_service_headers": manager.config.internal_service_headers,
            "rate_limiting_rules_count": len(manager.config.rate_limiting_rules),
            "circuit_breaker_configs_count": len(manager.config.circuit_breaker_configs),
            "backpressure_configs_count": len(manager.config.backpressure_configs)
        }
        
        return config_dict
        
    except Exception as e:
        logger.error("resilience_config_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Config retrieval failed: {str(e)}"
        )