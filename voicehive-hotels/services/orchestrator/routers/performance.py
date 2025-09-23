"""
Performance Optimization Router for VoiceHive Hotels Orchestrator
Provides endpoints for monitoring and managing performance optimization components
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger
from auth_middleware import require_auth, require_admin
from connection_pool_manager import get_connection_pool_manager, ConnectionPoolStats
from intelligent_cache import get_cache_manager, CacheStats
from audio_memory_optimizer import get_audio_memory_optimizer
from performance_monitor import get_performance_monitor, PerformanceAlert

logger = get_safe_logger("orchestrator.performance_router")

router = APIRouter(prefix="/performance", tags=["performance"])


class PerformanceOverview(BaseModel):
    """Overall performance status"""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "healthy"
    
    # System metrics
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    active_requests: int = 0
    
    # Component status
    connection_pools_healthy: bool = True
    cache_systems_healthy: bool = True
    audio_optimizer_healthy: bool = True
    
    # Performance metrics
    avg_response_time_ms: float = 0.0
    requests_per_second: float = 0.0
    error_rate_percent: float = 0.0
    
    # Alerts
    active_alerts: int = 0
    critical_alerts: int = 0


class ConnectionPoolStatus(BaseModel):
    """Connection pool status"""
    pool_type: str
    pools: List[ConnectionPoolStats]
    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    health_status: Dict[str, bool] = Field(default_factory=dict)


class CacheStatus(BaseModel):
    """Cache system status"""
    cache_name: str
    levels: Dict[str, CacheStats]
    overall_hit_ratio: float = 0.0
    total_entries: int = 0
    total_size_mb: float = 0.0
    health_status: Dict[str, bool] = Field(default_factory=dict)


class AudioOptimizerStatus(BaseModel):
    """Audio memory optimizer status"""
    active_streams: int = 0
    total_memory_mb: float = 0.0
    buffer_pool_usage: Dict[str, Any] = Field(default_factory=dict)
    gc_stats: Dict[str, Any] = Field(default_factory=dict)


class PerformanceOptimizationRequest(BaseModel):
    """Request to trigger performance optimization"""
    component: str = Field(..., description="Component to optimize (cache, memory, connections)")
    action: str = Field(..., description="Action to perform (clear, gc, reset)")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Additional parameters")


@router.get("/overview", response_model=PerformanceOverview)
async def get_performance_overview(
    request: Request,
    _: dict = Depends(require_auth)
):
    """Get overall performance overview"""
    try:
        # Get performance monitor
        perf_monitor = get_performance_monitor()
        
        # Get current metrics
        current_metrics = await perf_monitor.get_current_metrics()
        
        # Get active alerts
        alerts = await perf_monitor.get_active_alerts()
        critical_alerts = [a for a in alerts if a.severity.value == "critical"]
        
        # Check component health
        pool_manager = get_connection_pool_manager()
        cache_manager = get_cache_manager()
        audio_optimizer = get_audio_memory_optimizer()
        
        pool_health = await pool_manager.health_check()
        cache_health = await cache_manager.health_check_all()
        
        # Calculate overall health
        pools_healthy = all(
            all(status.values()) for status in pool_health.values()
        )
        caches_healthy = all(
            all(status.values()) for status in cache_health.values()
        )
        
        # Extract key metrics
        system_metrics = current_metrics.get('system', {})
        app_metrics = current_metrics.get('application', {})
        
        overview = PerformanceOverview(
            memory_usage_mb=system_metrics.get('process_memory_rss', 0) / 1024 / 1024,
            cpu_usage_percent=system_metrics.get('cpu_percent', 0.0),
            active_requests=app_metrics.get('active_requests', 0),
            connection_pools_healthy=pools_healthy,
            cache_systems_healthy=caches_healthy,
            audio_optimizer_healthy=True,  # Assume healthy if no errors
            avg_response_time_ms=app_metrics.get('avg_response_time_ms', 0.0),
            requests_per_second=app_metrics.get('requests_per_second', 0.0),
            error_rate_percent=app_metrics.get('error_rate_percent', 0.0),
            active_alerts=len(alerts),
            critical_alerts=len(critical_alerts)
        )
        
        # Set overall status
        if critical_alerts:
            overview.status = "critical"
        elif alerts:
            overview.status = "warning"
        elif not (pools_healthy and caches_healthy):
            overview.status = "degraded"
        else:
            overview.status = "healthy"
        
        return overview
        
    except Exception as e:
        logger.error("performance_overview_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get performance overview")


@router.get("/connection-pools", response_model=List[ConnectionPoolStatus])
async def get_connection_pool_status(
    request: Request,
    _: dict = Depends(require_auth)
):
    """Get connection pool status"""
    try:
        pool_manager = get_connection_pool_manager()
        
        # Get pool statistics
        all_stats = await pool_manager.get_all_stats()
        
        # Get health status
        health_status = await pool_manager.health_check()
        
        result = []
        
        for pool_type, pools in all_stats.items():
            if pools:  # Only include pool types that have pools
                total_connections = sum(pool.size for pool in pools)
                active_connections = sum(pool.active for pool in pools)
                idle_connections = sum(pool.idle for pool in pools)
                
                status = ConnectionPoolStatus(
                    pool_type=pool_type,
                    pools=pools,
                    total_connections=total_connections,
                    active_connections=active_connections,
                    idle_connections=idle_connections,
                    health_status=health_status.get(pool_type, {})
                )
                result.append(status)
        
        return result
        
    except Exception as e:
        logger.error("connection_pool_status_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get connection pool status")


@router.get("/caches", response_model=List[CacheStatus])
async def get_cache_status(
    request: Request,
    _: dict = Depends(require_auth)
):
    """Get cache system status"""
    try:
        cache_manager = get_cache_manager()
        
        # Get cache statistics
        all_stats = await cache_manager.get_all_stats()
        
        # Get health status
        health_status = await cache_manager.health_check_all()
        
        result = []
        
        for cache_name, cache_stats in all_stats.items():
            # Calculate overall metrics
            total_entries = sum(stats.total_entries for stats in cache_stats.values())
            total_size_mb = sum(stats.total_size_bytes for stats in cache_stats.values()) / 1024 / 1024
            
            # Calculate weighted hit ratio
            total_hits = sum(stats.hits for stats in cache_stats.values())
            total_requests = sum(stats.hits + stats.misses for stats in cache_stats.values())
            overall_hit_ratio = (total_hits / total_requests * 100) if total_requests > 0 else 0.0
            
            status = CacheStatus(
                cache_name=cache_name,
                levels=cache_stats,
                overall_hit_ratio=overall_hit_ratio,
                total_entries=total_entries,
                total_size_mb=total_size_mb,
                health_status=health_status.get(cache_name, {})
            )
            result.append(status)
        
        return result
        
    except Exception as e:
        logger.error("cache_status_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get cache status")


@router.get("/audio-optimizer", response_model=AudioOptimizerStatus)
async def get_audio_optimizer_status(
    request: Request,
    _: dict = Depends(require_auth)
):
    """Get audio memory optimizer status"""
    try:
        audio_optimizer = get_audio_memory_optimizer()
        
        # Get optimization statistics
        stats = await audio_optimizer.get_optimization_stats()
        
        status = AudioOptimizerStatus(
            active_streams=stats.get('active_streams', 0),
            total_memory_mb=stats.get('process_memory_mb', 0.0),
            buffer_pool_usage=stats.get('buffer_pool', {}),
            gc_stats=stats.get('gc_collections', {})
        )
        
        return status
        
    except Exception as e:
        logger.error("audio_optimizer_status_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get audio optimizer status")


@router.get("/alerts", response_model=List[PerformanceAlert])
async def get_performance_alerts(
    request: Request,
    _: dict = Depends(require_auth)
):
    """Get active performance alerts"""
    try:
        perf_monitor = get_performance_monitor()
        alerts = await perf_monitor.get_active_alerts()
        
        return alerts
        
    except Exception as e:
        logger.error("performance_alerts_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get performance alerts")


@router.get("/metrics/history")
async def get_metrics_history(
    request: Request,
    metric_type: str = "system",
    hours: int = 1,
    _: dict = Depends(require_auth)
):
    """Get performance metrics history"""
    try:
        if metric_type not in ["system", "application", "gc"]:
            raise HTTPException(status_code=400, detail="Invalid metric type")
        
        if hours < 1 or hours > 24:
            raise HTTPException(status_code=400, detail="Hours must be between 1 and 24")
        
        perf_monitor = get_performance_monitor()
        history = await perf_monitor.get_metrics_history(metric_type, hours)
        
        return {
            "metric_type": metric_type,
            "hours": hours,
            "data_points": len(history),
            "metrics": history
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("metrics_history_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get metrics history")


@router.post("/optimize")
async def trigger_optimization(
    request: Request,
    optimization_request: PerformanceOptimizationRequest,
    _: dict = Depends(require_admin)
):
    """Trigger performance optimization actions"""
    try:
        component = optimization_request.component.lower()
        action = optimization_request.action.lower()
        
        result = {"component": component, "action": action, "success": False}
        
        if component == "cache":
            cache_manager = get_cache_manager()
            
            if action == "clear":
                cache_name = optimization_request.parameters.get("cache_name")
                if cache_name:
                    cache = cache_manager.get_cache(cache_name)
                    if cache:
                        await cache.clear()
                        result["success"] = True
                        result["message"] = f"Cache {cache_name} cleared"
                    else:
                        raise HTTPException(status_code=404, detail=f"Cache {cache_name} not found")
                else:
                    # Clear all caches
                    await cache_manager.close_all()
                    result["success"] = True
                    result["message"] = "All caches cleared"
            
            elif action == "warm":
                cache_name = optimization_request.parameters.get("cache_name")
                if cache_name:
                    cache = cache_manager.get_cache(cache_name)
                    if cache:
                        await cache.warm_cache()
                        result["success"] = True
                        result["message"] = f"Cache {cache_name} warmed"
                    else:
                        raise HTTPException(status_code=404, detail=f"Cache {cache_name} not found")
        
        elif component == "memory":
            if action == "gc":
                audio_optimizer = get_audio_memory_optimizer()
                collected = await audio_optimizer.force_garbage_collection()
                result["success"] = True
                result["message"] = f"Garbage collection completed, collected {collected} objects"
        
        elif component == "connections":
            pool_manager = get_connection_pool_manager()
            
            if action == "health_check":
                health_status = await pool_manager.health_check()
                result["success"] = True
                result["message"] = "Health check completed"
                result["health_status"] = health_status
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown component: {component}")
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        
        logger.info("performance_optimization_triggered", **result)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("performance_optimization_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to trigger optimization")


@router.get("/prometheus")
async def get_prometheus_metrics(
    request: Request,
    _: dict = Depends(require_auth)
):
    """Get Prometheus metrics"""
    try:
        perf_monitor = get_performance_monitor()
        metrics_text = await perf_monitor.get_prometheus_metrics()
        
        return {
            "content_type": "text/plain; version=0.0.4; charset=utf-8",
            "metrics": metrics_text
        }
        
    except Exception as e:
        logger.error("prometheus_metrics_error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get Prometheus metrics")


@router.get("/health")
async def performance_health_check(request: Request):
    """Performance system health check (no auth required)"""
    try:
        # Quick health check of all performance components
        pool_manager = get_connection_pool_manager()
        cache_manager = get_cache_manager()
        perf_monitor = get_performance_monitor()
        
        # Get basic health status
        pool_health = await pool_manager.health_check()
        cache_health = await cache_manager.health_check_all()
        
        # Check if any critical alerts
        alerts = await perf_monitor.get_active_alerts()
        critical_alerts = [a for a in alerts if a.severity.value == "critical"]
        
        # Determine overall health
        pools_healthy = all(
            all(status.values()) for status in pool_health.values()
        )
        caches_healthy = all(
            all(status.values()) for status in cache_health.values()
        )
        
        overall_healthy = pools_healthy and caches_healthy and not critical_alerts
        
        return {
            "status": "healthy" if overall_healthy else "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "connection_pools": pools_healthy,
                "cache_systems": caches_healthy,
                "critical_alerts": len(critical_alerts)
            }
        }
        
    except Exception as e:
        logger.error("performance_health_check_error", error=str(e))
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }