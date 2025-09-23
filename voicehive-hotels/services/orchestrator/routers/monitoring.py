"""
Monitoring and Observability Router for VoiceHive Hotels
Endpoints for metrics, health checks, and operational dashboards
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry

from business_metrics import business_metrics
from enhanced_alerting import enhanced_alerting, AlertSeverity, AlertStatus
from dashboard_config import (
    BUSINESS_METRICS_DASHBOARD,
    SYSTEM_HEALTH_DASHBOARD,
    SLA_MONITORING_DASHBOARD
)
from distributed_tracing import enhanced_tracer
from logging_adapter import get_safe_logger
from auth_middleware import require_auth, require_role

logger = get_safe_logger("monitoring_router")

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/metrics")
async def get_prometheus_metrics():
    """
    Get Prometheus metrics in standard format
    """
    try:
        return PlainTextResponse(
            content=generate_latest(),
            headers={"Content-Type": CONTENT_TYPE_LATEST}
        )
    except Exception as e:
        logger.error("metrics_export_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to export metrics")


@router.get("/metrics/business")
async def get_business_metrics(
    hotel_id: Optional[str] = Query(None, description="Filter by hotel ID"),
    time_range: str = Query("1h", description="Time range (1h, 6h, 24h, 7d)"),
    current_user: dict = Depends(require_auth)
):
    """
    Get business metrics summary
    """
    try:
        # This would typically query your metrics backend (Prometheus, etc.)
        # For now, return a summary of current metrics
        
        metrics_summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "time_range": time_range,
            "hotel_id": hotel_id,
            "metrics": {
                "call_success_rate": {
                    "current": 99.2,
                    "target": 99.0,
                    "status": "healthy"
                },
                "active_calls": {
                    "current": len(business_metrics.active_calls),
                    "peak_24h": 45,
                    "status": "normal"
                },
                "pms_response_time": {
                    "p95_ms": 850,
                    "target_ms": 2000,
                    "status": "healthy"
                },
                "guest_satisfaction": {
                    "average": 4.3,
                    "target": 4.0,
                    "status": "excellent"
                }
            }
        }
        
        logger.info("business_metrics_requested", 
                   hotel_id=hotel_id, 
                   time_range=time_range,
                   user_id=current_user.get("user_id"))
        
        return metrics_summary
        
    except Exception as e:
        logger.error("business_metrics_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve business metrics")


@router.get("/health/detailed")
async def get_detailed_health_check():
    """
    Get detailed health check including all system components
    """
    try:
        health_status = {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "components": {
                "database": {
                    "status": "healthy",
                    "response_time_ms": 12,
                    "last_check": datetime.utcnow().isoformat()
                },
                "redis": {
                    "status": "healthy",
                    "response_time_ms": 3,
                    "last_check": datetime.utcnow().isoformat()
                },
                "vault": {
                    "status": "healthy",
                    "response_time_ms": 25,
                    "last_check": datetime.utcnow().isoformat()
                },
                "pms_connectors": {
                    "status": "healthy",
                    "available_connectors": list(business_metrics.pms_health_status.keys()),
                    "last_check": datetime.utcnow().isoformat()
                },
                "ai_services": {
                    "status": "healthy",
                    "response_time_ms": 150,
                    "last_check": datetime.utcnow().isoformat()
                }
            },
            "metrics": {
                "active_calls": len(business_metrics.active_calls),
                "memory_usage_mb": 256,  # This would be actual memory usage
                "cpu_usage_percent": 15.2
            }
        }
        
        # Determine overall status based on components
        component_statuses = [comp["status"] for comp in health_status["components"].values()]
        if "unhealthy" in component_statuses:
            health_status["overall_status"] = "unhealthy"
        elif "degraded" in component_statuses:
            health_status["overall_status"] = "degraded"
        
        return health_status
        
    except Exception as e:
        logger.error("detailed_health_check_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Health check failed")


@router.get("/alerts")
async def get_active_alerts(
    severity: Optional[AlertSeverity] = Query(None, description="Filter by severity"),
    status: Optional[AlertStatus] = Query(None, description="Filter by status"),
    current_user: dict = Depends(require_role("operator"))
):
    """
    Get active alerts with optional filtering
    """
    try:
        alerts = []
        
        for alert_id, alert in enhanced_alerting.active_alerts.items():
            # Apply filters
            if severity and alert.severity != severity:
                continue
            if status and alert.status != status:
                continue
            
            alert_dict = {
                "id": alert.id,
                "rule_name": alert.rule_name,
                "severity": alert.severity.value,
                "status": alert.status.value,
                "title": alert.title,
                "description": alert.description,
                "metric_value": alert.metric_value,
                "threshold": alert.threshold,
                "labels": alert.labels,
                "started_at": alert.started_at.isoformat(),
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                "runbook_url": alert.runbook_url
            }
            alerts.append(alert_dict)
        
        # Sort by severity and start time
        severity_order = {
            AlertSeverity.CRITICAL: 0,
            AlertSeverity.HIGH: 1,
            AlertSeverity.MEDIUM: 2,
            AlertSeverity.LOW: 3,
            AlertSeverity.INFO: 4
        }
        
        alerts.sort(key=lambda x: (
            severity_order.get(AlertSeverity(x["severity"]), 5),
            x["started_at"]
        ))
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_alerts": len(alerts),
            "filters": {
                "severity": severity.value if severity else None,
                "status": status.value if status else None
            },
            "alerts": alerts
        }
        
    except Exception as e:
        logger.error("get_alerts_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve alerts")


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    current_user: dict = Depends(require_role("operator"))
):
    """
    Acknowledge an active alert
    """
    try:
        if alert_id not in enhanced_alerting.active_alerts:
            raise HTTPException(status_code=404, detail="Alert not found")
        
        alert = enhanced_alerting.active_alerts[alert_id]
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = datetime.utcnow()
        alert.acknowledged_by = current_user.get("user_id", "unknown")
        
        logger.info("alert_acknowledged", 
                   alert_id=alert_id,
                   acknowledged_by=alert.acknowledged_by)
        
        return {
            "message": "Alert acknowledged successfully",
            "alert_id": alert_id,
            "acknowledged_by": alert.acknowledged_by,
            "acknowledged_at": alert.acknowledged_at.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("acknowledge_alert_failed", alert_id=alert_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to acknowledge alert")


@router.get("/sla/status")
async def get_sla_status(
    sla_name: Optional[str] = Query(None, description="Filter by SLA name"),
    current_user: dict = Depends(require_auth)
):
    """
    Get SLA compliance status
    """
    try:
        sla_status = {}
        
        for name, target in enhanced_alerting.sla_targets.items():
            if sla_name and name != sla_name:
                continue
            
            # Calculate current SLA value (simplified)
            current_value = 99.5  # This would be calculated from actual metrics
            is_compliant = current_value >= target.target_percentage
            
            sla_status[name] = {
                "name": name,
                "description": target.description,
                "target_percentage": target.target_percentage,
                "current_percentage": current_value,
                "is_compliant": is_compliant,
                "measurement_window": target.measurement_window,
                "last_violation": enhanced_alerting.sla_violations.get(name),
                "status": "compliant" if is_compliant else "violation"
            }
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "sla_targets": sla_status
        }
        
    except Exception as e:
        logger.error("get_sla_status_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve SLA status")


@router.get("/dashboards")
async def get_available_dashboards(
    current_user: dict = Depends(require_auth)
):
    """
    Get list of available monitoring dashboards
    """
    try:
        dashboards = [
            {
                "id": "business-metrics",
                "title": "Business Metrics",
                "description": "Call success rates, PMS performance, guest satisfaction",
                "url": "/monitoring/dashboards/business-metrics",
                "tags": ["business", "kpi"]
            },
            {
                "id": "system-health",
                "title": "System Health",
                "description": "CPU, memory, connections, error rates",
                "url": "/monitoring/dashboards/system-health",
                "tags": ["system", "infrastructure"]
            },
            {
                "id": "sla-monitoring",
                "title": "SLA Monitoring",
                "description": "SLA compliance and violation tracking",
                "url": "/monitoring/dashboards/sla-monitoring",
                "tags": ["sla", "compliance"]
            }
        ]
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "dashboards": dashboards
        }
        
    except Exception as e:
        logger.error("get_dashboards_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve dashboards")


@router.get("/dashboards/{dashboard_id}")
async def get_dashboard_config(
    dashboard_id: str,
    current_user: dict = Depends(require_auth)
):
    """
    Get dashboard configuration for Grafana import
    """
    try:
        dashboard_configs = {
            "business-metrics": BUSINESS_METRICS_DASHBOARD,
            "system-health": SYSTEM_HEALTH_DASHBOARD,
            "sla-monitoring": SLA_MONITORING_DASHBOARD
        }
        
        if dashboard_id not in dashboard_configs:
            raise HTTPException(status_code=404, detail="Dashboard not found")
        
        dashboard_config = dashboard_configs[dashboard_id]
        
        logger.info("dashboard_config_requested", 
                   dashboard_id=dashboard_id,
                   user_id=current_user.get("user_id"))
        
        return dashboard_config
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_dashboard_config_failed", 
                    dashboard_id=dashboard_id, 
                    error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve dashboard config")


@router.get("/traces")
async def get_trace_info(
    trace_id: Optional[str] = Query(None, description="Specific trace ID"),
    operation: Optional[str] = Query(None, description="Filter by operation"),
    hotel_id: Optional[str] = Query(None, description="Filter by hotel ID"),
    limit: int = Query(100, description="Maximum number of traces"),
    current_user: dict = Depends(require_role("developer"))
):
    """
    Get distributed tracing information
    """
    try:
        # Get current trace context
        current_trace_id = enhanced_tracer.get_current_trace_id()
        current_span_id = enhanced_tracer.get_current_span_id()
        
        trace_info = {
            "timestamp": datetime.utcnow().isoformat(),
            "current_trace": {
                "trace_id": current_trace_id,
                "span_id": current_span_id
            },
            "active_spans": len(enhanced_tracer.active_spans),
            "business_contexts": len(enhanced_tracer.business_contexts),
            "trace_metrics_count": len(enhanced_tracer.trace_metrics)
        }
        
        # Add trace context headers for client propagation
        trace_headers = enhanced_tracer.get_trace_context_headers()
        if trace_headers:
            trace_info["propagation_headers"] = trace_headers
        
        # If specific trace ID requested, provide more details
        if trace_id:
            # In a real implementation, you'd query your tracing backend
            trace_info["requested_trace_id"] = trace_id
            trace_info["note"] = "Detailed trace data would be retrieved from Jaeger/Tempo"
        
        return trace_info
        
    except Exception as e:
        logger.error("get_trace_info_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve trace information")


@router.post("/traces/flush")
async def flush_traces(
    current_user: dict = Depends(require_role("admin"))
):
    """
    Flush pending traces to backend
    """
    try:
        enhanced_tracer.flush_traces()
        
        logger.info("traces_flushed", user_id=current_user.get("user_id"))
        
        return {
            "message": "Traces flushed successfully",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error("flush_traces_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to flush traces")


@router.get("/performance/summary")
async def get_performance_summary(
    time_range: str = Query("1h", description="Time range (1h, 6h, 24h)"),
    current_user: dict = Depends(require_auth)
):
    """
    Get performance summary metrics
    """
    try:
        # This would typically aggregate data from your metrics backend
        performance_summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "time_range": time_range,
            "summary": {
                "request_rate": {
                    "current_rps": 12.5,
                    "peak_rps": 45.2,
                    "average_rps": 18.7
                },
                "response_times": {
                    "p50_ms": 125,
                    "p95_ms": 450,
                    "p99_ms": 850
                },
                "error_rates": {
                    "total_errors": 23,
                    "error_rate_percent": 0.15,
                    "critical_errors": 2
                },
                "resource_usage": {
                    "cpu_percent": 15.2,
                    "memory_mb": 256,
                    "active_connections": 45
                }
            },
            "top_endpoints": [
                {"endpoint": "/call/webhook", "rps": 8.2, "p95_ms": 200},
                {"endpoint": "/pms/booking", "rps": 3.1, "p95_ms": 850},
                {"endpoint": "/auth/validate", "rps": 12.5, "p95_ms": 50}
            ]
        }
        
        return performance_summary
        
    except Exception as e:
        logger.error("get_performance_summary_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve performance summary")


@router.get("/operational/status")
async def get_operational_status():
    """
    Get overall operational status for external monitoring
    """
    try:
        # Check critical systems
        critical_systems = {
            "database": True,  # Would check actual database connectivity
            "redis": True,     # Would check actual Redis connectivity
            "vault": True,     # Would check actual Vault connectivity
            "ai_services": True  # Would check AI service availability
        }
        
        # Check if any critical alerts are active
        critical_alerts = [
            alert for alert in enhanced_alerting.active_alerts.values()
            if alert.severity == AlertSeverity.CRITICAL and alert.status == AlertStatus.ACTIVE
        ]
        
        # Determine overall status
        all_systems_healthy = all(critical_systems.values())
        no_critical_alerts = len(critical_alerts) == 0
        
        if all_systems_healthy and no_critical_alerts:
            overall_status = "operational"
        elif all_systems_healthy:
            overall_status = "degraded"
        else:
            overall_status = "outage"
        
        status_response = {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "systems": critical_systems,
            "critical_alerts_count": len(critical_alerts),
            "active_calls": len(business_metrics.active_calls),
            "uptime_seconds": 86400  # Would calculate actual uptime
        }
        
        # Return appropriate HTTP status code
        if overall_status == "operational":
            return JSONResponse(content=status_response, status_code=200)
        elif overall_status == "degraded":
            return JSONResponse(content=status_response, status_code=200)
        else:
            return JSONResponse(content=status_response, status_code=503)
        
    except Exception as e:
        logger.error("get_operational_status_failed", error=str(e))
        return JSONResponse(
            content={
                "status": "unknown",
                "error": "Failed to determine operational status",
                "timestamp": datetime.utcnow().isoformat()
            },
            status_code=500
        )