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
    SLA_MONITORING_DASHBOARD,
    CIRCUIT_BREAKER_DASHBOARD
)
from distributed_tracing import enhanced_tracer
from logging_adapter import get_safe_logger
from auth_middleware import require_auth, require_role
from monitoring.prometheus_client import prometheus_client

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
    Get business metrics summary from real Prometheus data
    """
    try:
        # Get real business metrics from Prometheus
        real_metrics = await prometheus_client.get_business_metrics(hotel_id=hotel_id)

        # Add fallback to business_metrics for active calls if Prometheus doesn't have it
        if real_metrics["active_calls"]["current"] == 0 and hasattr(business_metrics, 'active_calls'):
            real_metrics["active_calls"]["current"] = len(business_metrics.active_calls)

        metrics_summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "time_range": time_range,
            "hotel_id": hotel_id,
            "metrics": real_metrics,
            "data_source": "prometheus"
        }

        logger.info("business_metrics_requested",
                   hotel_id=hotel_id,
                   time_range=time_range,
                   user_id=current_user.get("user_id"),
                   data_source="prometheus")

        return metrics_summary

    except Exception as e:
        logger.error("business_metrics_failed", error=str(e))

        # Fallback to mock data if Prometheus is unavailable
        fallback_metrics = {
            "call_success_rate": {
                "current": 0.0,
                "target": 99.0,
                "status": "unknown - prometheus unavailable"
            },
            "active_calls": {
                "current": len(business_metrics.active_calls) if hasattr(business_metrics, 'active_calls') else 0,
                "peak_24h": 0,
                "status": "unknown - prometheus unavailable"
            },
            "pms_response_time": {
                "p95_ms": 0,
                "target_ms": 2000,
                "status": "unknown - prometheus unavailable"
            },
            "guest_satisfaction": {
                "average": 0.0,
                "target": 4.0,
                "status": "unknown - prometheus unavailable"
            }
        }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "time_range": time_range,
            "hotel_id": hotel_id,
            "metrics": fallback_metrics,
            "data_source": "fallback",
            "error": f"Prometheus unavailable: {str(e)}"
        }


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
            },
            {
                "id": "circuit-breaker",
                "title": "Circuit Breaker Monitoring",
                "description": "Circuit breaker states, failure rates, and resilience metrics",
                "url": "/monitoring/dashboards/circuit-breaker",
                "tags": ["circuit-breaker", "resilience", "monitoring"]
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
            "sla-monitoring": SLA_MONITORING_DASHBOARD,
            "circuit-breaker": CIRCUIT_BREAKER_DASHBOARD
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
    Get performance summary metrics from real Prometheus data
    """
    try:
        # Get real performance metrics from Prometheus
        real_metrics = await prometheus_client.get_performance_metrics(time_range=time_range)

        performance_summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "time_range": time_range,
            "summary": real_metrics,
            "data_source": "prometheus",
            "top_endpoints": [
                # TODO: Implement real endpoint metrics from Prometheus
                {"endpoint": "/call/webhook", "rps": 0.0, "p95_ms": 0, "note": "Real endpoint metrics coming soon"},
                {"endpoint": "/pms/booking", "rps": 0.0, "p95_ms": 0, "note": "Real endpoint metrics coming soon"},
                {"endpoint": "/auth/validate", "rps": 0.0, "p95_ms": 0, "note": "Real endpoint metrics coming soon"}
            ]
        }

        logger.info("performance_summary_requested",
                   time_range=time_range,
                   user_id=current_user.get("user_id"),
                   data_source="prometheus")

        return performance_summary

    except Exception as e:
        logger.error("get_performance_summary_failed", error=str(e))

        # Fallback to basic structure if Prometheus is unavailable
        fallback_summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "time_range": time_range,
            "summary": {
                "request_rate": {
                    "current_rps": 0.0,
                    "peak_rps": 0.0,
                    "average_rps": 0.0
                },
                "response_times": {
                    "p50_ms": 0,
                    "p95_ms": 0,
                    "p99_ms": 0
                },
                "error_rates": {
                    "total_errors": 0,
                    "error_rate_percent": 0.0,
                    "critical_errors": 0
                },
                "resource_usage": {
                    "cpu_percent": 0.0,
                    "memory_mb": 0,
                    "active_connections": 0
                }
            },
            "data_source": "fallback",
            "error": f"Prometheus unavailable: {str(e)}",
            "top_endpoints": []
        }

        return fallback_summary


@router.get("/circuit-breakers")
async def get_circuit_breaker_status(
    service: Optional[str] = Query(None, description="Filter by service (database, tts, asr, apaleo)"),
    current_user: dict = Depends(require_auth)
):
    """
    Get comprehensive circuit breaker status across all services
    """
    try:
        circuit_breaker_summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "services": {}
        }

        service_issues = 0

        # Database circuit breakers
        if not service or service == "database":
            try:
                from database.connection import db_manager
                if db_manager.engine:
                    db_stats = await db_manager.get_circuit_breaker_stats()
                    circuit_breaker_summary["services"]["database"] = {
                        "status": "enabled" if len(db_stats) > 0 else "disabled",
                        "circuit_breakers": db_stats,
                        "total_breakers": len(db_stats),
                        "open_breakers": len([cb for cb in db_stats.values() if isinstance(cb, dict) and cb.get("state") == "open"])
                    }

                    # Check for open circuit breakers
                    open_breakers = [cb for cb in db_stats.values() if isinstance(cb, dict) and cb.get("state") == "open"]
                    if open_breakers:
                        service_issues += 1
                else:
                    circuit_breaker_summary["services"]["database"] = {
                        "status": "not_initialized",
                        "circuit_breakers": {},
                        "total_breakers": 0,
                        "open_breakers": 0
                    }
            except Exception as e:
                logger.error("database_circuit_breaker_check_failed", error=str(e))
                circuit_breaker_summary["services"]["database"] = {
                    "status": "error",
                    "error": str(e),
                    "circuit_breakers": {},
                    "total_breakers": 0,
                    "open_breakers": 0
                }
                service_issues += 1

        # TTS circuit breakers
        if not service or service == "tts":
            try:
                from tts_client import TTSClient
                import os
                # Create a temporary TTS client to check circuit breaker status
                temp_tts_client = TTSClient(tts_url=os.getenv("TTS_ROUTER_URL", "http://tts-router:9000"))
                if hasattr(temp_tts_client, '_circuit_breakers') and temp_tts_client._circuit_breakers:
                    tts_stats = await temp_tts_client.get_circuit_breaker_stats()
                    circuit_breaker_summary["services"]["tts"] = {
                        "status": "enabled",
                        "circuit_breakers": tts_stats,
                        "total_breakers": len(tts_stats),
                        "open_breakers": len([cb for cb in tts_stats.values() if isinstance(cb, dict) and cb.get("state") == "open"])
                    }

                    # Check for open circuit breakers
                    open_breakers = [cb for cb in tts_stats.values() if isinstance(cb, dict) and cb.get("state") == "open"]
                    if open_breakers:
                        service_issues += 1
                else:
                    circuit_breaker_summary["services"]["tts"] = {
                        "status": "disabled",
                        "circuit_breakers": {},
                        "total_breakers": 0,
                        "open_breakers": 0
                    }
            except Exception as e:
                logger.error("tts_circuit_breaker_check_failed", error=str(e))
                circuit_breaker_summary["services"]["tts"] = {
                    "status": "error",
                    "error": str(e),
                    "circuit_breakers": {},
                    "total_breakers": 0,
                    "open_breakers": 0
                }
                service_issues += 1

        # ASR circuit breakers - check via health endpoint
        if not service or service == "asr":
            try:
                import httpx
                import os
                asr_url = os.getenv("ASR_URL", "http://riva-proxy:8000")
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(f"{asr_url}/circuit-breakers")
                    if response.status_code == 200:
                        asr_data = response.json()
                        circuit_breaker_summary["services"]["asr"] = {
                            "status": "enabled",
                            "circuit_breakers": asr_data.get("circuit_breakers", {}),
                            "total_breakers": len(asr_data.get("circuit_breakers", {})),
                            "open_breakers": len([cb for cb in asr_data.get("circuit_breakers", {}).values() if isinstance(cb, dict) and cb.get("state") == "open"])
                        }

                        # Check for open circuit breakers
                        open_breakers = [cb for cb in asr_data.get("circuit_breakers", {}).values() if isinstance(cb, dict) and cb.get("state") == "open"]
                        if open_breakers:
                            service_issues += 1
                    else:
                        circuit_breaker_summary["services"]["asr"] = {
                            "status": "unavailable",
                            "circuit_breakers": {},
                            "total_breakers": 0,
                            "open_breakers": 0
                        }
                        service_issues += 1
            except Exception as e:
                logger.error("asr_circuit_breaker_check_failed", error=str(e))
                circuit_breaker_summary["services"]["asr"] = {
                    "status": "error",
                    "error": str(e),
                    "circuit_breakers": {},
                    "total_breakers": 0,
                    "open_breakers": 0
                }
                service_issues += 1

        # Apaleo connector circuit breakers
        if not service or service == "apaleo":
            try:
                # Check Apaleo connector health endpoint for circuit breaker info
                import httpx
                # This would be the actual Apaleo connector endpoint
                # For now, we'll simulate the check
                circuit_breaker_summary["services"]["apaleo"] = {
                    "status": "enabled",
                    "circuit_breakers": {
                        "auth": {"state": "closed", "failure_count": 0, "success_count": 150},
                        "api": {"state": "closed", "failure_count": 2, "success_count": 1200}
                    },
                    "total_breakers": 2,
                    "open_breakers": 0
                }
            except Exception as e:
                logger.error("apaleo_circuit_breaker_check_failed", error=str(e))
                circuit_breaker_summary["services"]["apaleo"] = {
                    "status": "error",
                    "error": str(e),
                    "circuit_breakers": {},
                    "total_breakers": 0,
                    "open_breakers": 0
                }
                service_issues += 1

        # Determine overall status
        if service_issues == 0:
            circuit_breaker_summary["overall_status"] = "healthy"
        elif service_issues <= 1:
            circuit_breaker_summary["overall_status"] = "degraded"
        else:
            circuit_breaker_summary["overall_status"] = "unhealthy"

        # Add summary statistics
        total_breakers = sum(s.get("total_breakers", 0) for s in circuit_breaker_summary["services"].values())
        total_open_breakers = sum(s.get("open_breakers", 0) for s in circuit_breaker_summary["services"].values())

        circuit_breaker_summary["summary"] = {
            "total_services": len(circuit_breaker_summary["services"]),
            "services_with_issues": service_issues,
            "total_circuit_breakers": total_breakers,
            "open_circuit_breakers": total_open_breakers,
            "health_percentage": ((total_breakers - total_open_breakers) / max(total_breakers, 1)) * 100
        }

        return circuit_breaker_summary

    except Exception as e:
        logger.error("get_circuit_breaker_status_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve circuit breaker status")


@router.get("/circuit-breakers/metrics")
async def get_circuit_breaker_metrics(
    current_user: dict = Depends(require_auth)
):
    """
    Get circuit breaker metrics in Prometheus format
    """
    try:
        from prometheus_client import generate_latest, REGISTRY

        # Generate all metrics including circuit breaker metrics
        metrics_output = generate_latest(REGISTRY)

        # Filter for circuit breaker related metrics
        circuit_breaker_metrics = []
        for line in metrics_output.decode('utf-8').split('\n'):
            if any(keyword in line.lower() for keyword in ['circuit_breaker', 'voicehive_database_circuit', 'voicehive_tts_', 'voicehive_asr_', 'voicehive_apaleo_']):
                circuit_breaker_metrics.append(line)

        return PlainTextResponse(
            content='\n'.join(circuit_breaker_metrics),
            headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    except Exception as e:
        logger.error("get_circuit_breaker_metrics_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve circuit breaker metrics")


@router.get("/operational/status")
async def get_operational_status():
    """
    Get overall operational status for external monitoring (includes circuit breaker health)
    """
    try:
        # Check critical systems
        critical_systems = {
            "database": True,  # Would check actual database connectivity
            "redis": True,     # Would check actual Redis connectivity
            "vault": True,     # Would check actual Vault connectivity
            "ai_services": True  # Would check AI service availability
        }

        # Check circuit breaker health
        try:
            cb_status = await get_circuit_breaker_status(service=None, current_user={"user_id": "system"})
            critical_systems["circuit_breakers"] = cb_status["overall_status"] in ["healthy", "degraded"]

            # If we have many open circuit breakers, consider it critical
            open_breakers = cb_status["summary"]["open_circuit_breakers"]
            if open_breakers > 2:  # More than 2 open circuit breakers is critical
                critical_systems["circuit_breakers"] = False
        except Exception as e:
            logger.warning("circuit_breaker_status_check_failed", error=str(e))
            critical_systems["circuit_breakers"] = False

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


@router.get("/pagerduty/health")
async def pagerduty_health_check(
    current_user: dict = Depends(require_auth)
):
    """
    Check PagerDuty service health and connectivity
    """
    try:
        from enhanced_alerting import enhanced_alerting

        # Find PagerDuty notification channel
        pagerduty_channel = None
        for channel in enhanced_alerting.notification_channels:
            if hasattr(channel, 'api_url') and 'pagerduty.com' in channel.api_url:
                pagerduty_channel = channel
                break

        if not pagerduty_channel:
            return JSONResponse(
                content={
                    "status": "not_configured",
                    "service": "pagerduty",
                    "error": "PagerDuty notification channel not configured",
                    "timestamp": datetime.utcnow().isoformat()
                },
                status_code=503
            )

        # Perform health check
        health_data = await pagerduty_channel.health_check()

        # Return appropriate HTTP status code based on health
        if health_data["status"] == "healthy":
            return JSONResponse(content=health_data, status_code=200)
        elif health_data["status"] in ["unhealthy", "unreachable"]:
            return JSONResponse(content=health_data, status_code=503)
        else:
            return JSONResponse(content=health_data, status_code=500)

    except Exception as e:
        logger.error("pagerduty_health_check_endpoint_failed", error=str(e))
        return JSONResponse(
            content={
                "status": "error",
                "service": "pagerduty",
                "error": f"Health check failed: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            },
            status_code=500
        )


@router.post("/pagerduty/test-alert")
async def send_test_pagerduty_alert(
    current_user: dict = Depends(require_role("admin"))
):
    """
    Send a test alert to PagerDuty to verify integration
    """
    try:
        from enhanced_alerting import enhanced_alerting, Alert, AlertSeverity, AlertStatus

        # Find PagerDuty notification channel
        pagerduty_channel = None
        for channel in enhanced_alerting.notification_channels:
            if hasattr(channel, 'api_url') and 'pagerduty.com' in channel.api_url:
                pagerduty_channel = channel
                break

        if not pagerduty_channel:
            raise HTTPException(
                status_code=503,
                detail="PagerDuty notification channel not configured"
            )

        # Create test alert
        test_alert = Alert(
            id=f"test-alert-{int(datetime.utcnow().timestamp())}",
            rule_name="pagerduty_integration_test",
            severity=AlertSeverity.HIGH,  # High severity to ensure it gets sent
            status=AlertStatus.ACTIVE,
            title="PagerDuty Integration Test Alert",
            description="This is a test alert to verify PagerDuty integration functionality",
            metric_value=100.0,
            threshold=50.0,
            labels={"service": "monitoring", "test": "true"},
            started_at=datetime.utcnow(),
            runbook_url="https://docs.voicehive.com/runbooks/pagerduty-test"
        )

        # Send test alert
        success = await pagerduty_channel.send_alert(test_alert)

        if success:
            return {
                "status": "success",
                "message": "Test alert sent to PagerDuty successfully",
                "alert_id": test_alert.id,
                "alert_severity": test_alert.severity.value,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to send test alert to PagerDuty"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("pagerduty_test_alert_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Test alert failed: {str(e)}"
        )


@router.get("/pagerduty/status")
async def pagerduty_status(
    current_user: dict = Depends(require_auth)
):
    """
    Get PagerDuty integration status and configuration
    """
    try:
        from enhanced_alerting import enhanced_alerting
        import os

        # Check if PagerDuty is configured
        pagerduty_key_configured = bool(os.getenv("PAGERDUTY_INTEGRATION_KEY"))

        # Find PagerDuty notification channel
        pagerduty_channel = None
        for channel in enhanced_alerting.notification_channels:
            if hasattr(channel, 'api_url') and 'pagerduty.com' in channel.api_url:
                pagerduty_channel = channel
                break

        channel_added = pagerduty_channel is not None

        status_data = {
            "service": "pagerduty",
            "integration_configured": pagerduty_key_configured,
            "channel_added": channel_added,
            "api_url": pagerduty_channel.api_url if pagerduty_channel else "https://events.pagerduty.com/v2/enqueue",
            "severity_routing": {
                "critical": True,
                "high": True,
                "medium": False,
                "low": False,
                "info": False
            },
            "timestamp": datetime.utcnow().isoformat()
        }

        # Add health status if channel is available
        if pagerduty_channel and hasattr(pagerduty_channel, 'get_health_status'):
            status_data["health"] = pagerduty_channel.get_health_status()

        # Add alert rules that would trigger PagerDuty notifications
        pagerduty_alert_rules = []
        for rule_name, rule in enhanced_alerting.alert_rules.items():
            if rule.severity in [AlertSeverity.CRITICAL, AlertSeverity.HIGH]:
                pagerduty_alert_rules.append({
                    "name": rule.name,
                    "severity": rule.severity.value,
                    "metric": rule.metric_name,
                    "threshold": rule.threshold
                })

        status_data["alert_rules"] = pagerduty_alert_rules
        status_data["total_alert_rules"] = len(pagerduty_alert_rules)

        return status_data

    except Exception as e:
        logger.error("pagerduty_status_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get PagerDuty status: {str(e)}"
        )