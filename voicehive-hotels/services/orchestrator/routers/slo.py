"""
SLO Monitoring API Router
REST API endpoints for SLI/SLO monitoring and error budget tracking
"""

from fastapi import APIRouter, HTTPException, Depends, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import asyncio
from logging_adapter import get_safe_logger
from sli_slo_config import SLO_REGISTRY, SLODefinition, VoiceHiveSLOConfig
from slo_monitor import get_slo_monitor, SLOMonitor, SLOStatus
from runbook_automation import runbook_engine, RunbookExecution
from auth_middleware import require_auth, require_permission

logger = get_safe_logger("slo_api")

router = APIRouter(prefix="/slo", tags=["SLO Monitoring"])

# Dependency to get SLO monitor instance
async def get_monitor() -> SLOMonitor:
    """Get SLO monitor instance"""
    # In production, get these from configuration
    prometheus_url = "http://prometheus:9090"
    alert_webhook_url = "http://alertmanager-webhook:5001/slo-alerts"
    
    return get_slo_monitor(prometheus_url, alert_webhook_url)

@router.get("/status", summary="Get SLO Status Overview")
async def get_slo_status(
    slo_name: Optional[str] = Query(None, description="Filter by specific SLO name"),
    service: Optional[str] = Query(None, description="Filter by service name"),
    monitor: SLOMonitor = Depends(get_monitor),
    _auth = Depends(require_auth)
) -> Dict[str, Any]:
    """
    Get current SLO status and compliance information
    
    Returns comprehensive SLO status including:
    - Current SLI values
    - Compliance status
    - Error budget remaining
    - Burn rates
    - Active alerts
    """
    try:
        # Get dashboard data (includes all SLO evaluations)
        dashboard_data = await monitor.get_slo_dashboard_data()
        
        # Filter results if requested
        slos = dashboard_data["slos"]
        
        if slo_name:
            slos = {name: data for name, data in slos.items() if name == slo_name}
        
        if service:
            slos = {name: data for name, data in slos.items() if data.get("service") == service}
        
        if not slos and (slo_name or service):
            raise HTTPException(
                status_code=404,
                detail=f"No SLOs found for filters: slo_name={slo_name}, service={service}"
            )
        
        # Update summary with filtered data
        filtered_summary = {
            "total_slos": len(slos),
            "compliant": len([s for s in slos.values() if s["compliance_status"] == "compliant"]),
            "at_risk": len([s for s in slos.values() if s["compliance_status"] == "at_risk"]),
            "violated": len([s for s in slos.values() if s["compliance_status"] == "violated"]),
            "unknown": len([s for s in slos.values() if s["compliance_status"] == "unknown"]),
            "last_updated": dashboard_data["summary"]["last_updated"]
        }
        
        return {
            "summary": filtered_summary,
            "slos": slos,
            "filters_applied": {
                "slo_name": slo_name,
                "service": service
            }
        }
        
    except Exception as e:
        logger.error(
            "slo_status_api_error",
            error=str(e),
            slo_name=slo_name,
            service=service
        )
        raise HTTPException(status_code=500, detail=f"Failed to get SLO status: {str(e)}")

@router.get("/definitions", summary="Get SLO Definitions")
async def get_slo_definitions(
    _auth = Depends(require_auth)
) -> Dict[str, Any]:
    """
    Get all SLO definitions including SLI queries, targets, and error budget policies
    """
    try:
        definitions = []
        
        for slo in SLO_REGISTRY:
            definition_data = {
                "name": slo.name,
                "service": slo.service,
                "enabled": slo.enabled,
                "sli": {
                    "name": slo.sli.name,
                    "description": slo.sli.description,
                    "type": slo.sli.sli_type.value,
                    "query": slo.sli.query.strip(),
                    "unit": slo.sli.unit,
                    "good_total_ratio": slo.sli.good_total_ratio,
                    "labels": slo.sli.labels
                },
                "targets": [
                    {
                        "target_percentage": target.target_percentage,
                        "compliance_period": target.compliance_period,
                        "description": target.description
                    }
                    for target in slo.targets
                ],
                "error_budget_policy": {
                    "burn_rate_thresholds": {
                        window.value: threshold
                        for window, threshold in slo.error_budget_policy.burn_rate_thresholds.items()
                    },
                    "alert_on_exhaustion_percentage": slo.error_budget_policy.alert_on_exhaustion_percentage,
                    "freeze_deployments_percentage": slo.error_budget_policy.freeze_deployments_percentage
                },
                "tags": slo.tags
            }
            definitions.append(definition_data)
        
        return {
            "total_slos": len(definitions),
            "definitions": definitions
        }
        
    except Exception as e:
        logger.error("slo_definitions_api_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get SLO definitions: {str(e)}")

@router.get("/error-budget", summary="Get Error Budget Status")
async def get_error_budget_status(
    slo_name: Optional[str] = Query(None, description="Filter by specific SLO name"),
    monitor: SLOMonitor = Depends(get_monitor),
    _auth = Depends(require_auth)
) -> Dict[str, Any]:
    """
    Get detailed error budget information for SLOs
    """
    try:
        # Evaluate all SLOs to get current status
        slo_statuses = await monitor.evaluate_all_slos()
        
        # Filter if requested
        if slo_name:
            if slo_name not in slo_statuses:
                raise HTTPException(status_code=404, detail=f"SLO '{slo_name}' not found")
            slo_statuses = {slo_name: slo_statuses[slo_name]}
        
        error_budget_data = {}
        
        for name, status in slo_statuses.items():
            error_budget_data[name] = {
                "slo_name": name,
                "service": status.service,
                "target_percentage": status.target_percentage,
                "current_sli": status.current_sli_value,
                "error_budget_remaining": status.error_budget_remaining,
                "error_budget_consumed": status.error_budget_consumed,
                "compliance_status": status.compliance_status.value,
                "burn_rates": {
                    "1h": status.burn_rate_1h,
                    "6h": status.burn_rate_6h,
                    "24h": status.burn_rate_24h,
                    "72h": status.burn_rate_72h
                },
                "alerts_active": status.alerts_active,
                "last_updated": status.last_updated.isoformat(),
                "budget_exhaustion_eta": _calculate_budget_exhaustion_eta(status),
                "deployment_freeze_recommended": status.error_budget_remaining < 5.0
            }
        
        return {
            "error_budgets": error_budget_data,
            "summary": {
                "total_slos": len(error_budget_data),
                "budgets_healthy": len([b for b in error_budget_data.values() if b["error_budget_remaining"] > 50]),
                "budgets_at_risk": len([b for b in error_budget_data.values() if 10 < b["error_budget_remaining"] <= 50]),
                "budgets_critical": len([b for b in error_budget_data.values() if b["error_budget_remaining"] <= 10]),
                "deployment_freeze_count": len([b for b in error_budget_data.values() if b["deployment_freeze_recommended"]])
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("error_budget_api_error", error=str(e), slo_name=slo_name)
        raise HTTPException(status_code=500, detail=f"Failed to get error budget status: {str(e)}")

def _calculate_budget_exhaustion_eta(status: SLOStatus) -> Optional[str]:
    """Calculate estimated time to error budget exhaustion"""
    try:
        if status.burn_rate_1h <= 0 or status.error_budget_remaining <= 0:
            return None
        
        # Calculate hours until exhaustion based on current 1h burn rate
        hours_remaining = status.error_budget_remaining / status.burn_rate_1h
        
        if hours_remaining > 8760:  # More than a year
            return None
        
        eta = datetime.utcnow() + timedelta(hours=hours_remaining)
        return eta.isoformat()
        
    except Exception:
        return None

@router.get("/burn-rate", summary="Get Burn Rate Analysis")
async def get_burn_rate_analysis(
    slo_name: Optional[str] = Query(None, description="Filter by specific SLO name"),
    window: Optional[str] = Query("1h", description="Time window for analysis"),
    monitor: SLOMonitor = Depends(get_monitor),
    _auth = Depends(require_auth)
) -> Dict[str, Any]:
    """
    Get detailed burn rate analysis for SLOs
    """
    try:
        # Evaluate all SLOs
        slo_statuses = await monitor.evaluate_all_slos()
        
        # Filter if requested
        if slo_name:
            if slo_name not in slo_statuses:
                raise HTTPException(status_code=404, detail=f"SLO '{slo_name}' not found")
            slo_statuses = {slo_name: slo_statuses[slo_name]}
        
        burn_rate_analysis = {}
        
        for name, status in slo_statuses.items():
            # Get SLO definition for thresholds
            slo_def = next((slo for slo in SLO_REGISTRY if slo.name == name), None)
            if not slo_def:
                continue
            
            burn_rates = {
                "1h": status.burn_rate_1h,
                "6h": status.burn_rate_6h,
                "24h": status.burn_rate_24h,
                "72h": status.burn_rate_72h
            }
            
            thresholds = {
                window.value: threshold
                for window, threshold in slo_def.error_budget_policy.burn_rate_thresholds.items()
            }
            
            # Analyze burn rate trends
            burn_rate_analysis[name] = {
                "slo_name": name,
                "service": status.service,
                "burn_rates": burn_rates,
                "thresholds": thresholds,
                "alerts": {
                    window: {
                        "current_rate": burn_rates.get(window, 0),
                        "threshold": thresholds.get(window, float('inf')),
                        "exceeds_threshold": burn_rates.get(window, 0) > thresholds.get(window, float('inf')),
                        "severity": _get_burn_rate_severity(window, burn_rates.get(window, 0), thresholds.get(window, float('inf')))
                    }
                    for window in ["1h", "6h", "24h", "72h"]
                },
                "trend_analysis": {
                    "accelerating": status.burn_rate_1h > status.burn_rate_6h,
                    "sustained_high": all(rate > 1.0 for rate in [status.burn_rate_1h, status.burn_rate_6h, status.burn_rate_24h]),
                    "risk_level": _assess_burn_rate_risk(status)
                }
            }
        
        return {
            "burn_rate_analysis": burn_rate_analysis,
            "analysis_timestamp": datetime.utcnow().isoformat(),
            "window_requested": window
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("burn_rate_analysis_error", error=str(e), slo_name=slo_name)
        raise HTTPException(status_code=500, detail=f"Failed to analyze burn rates: {str(e)}")

def _get_burn_rate_severity(window: str, current_rate: float, threshold: float) -> str:
    """Determine burn rate alert severity"""
    if current_rate <= threshold:
        return "ok"
    elif window in ["1h", "6h"]:
        return "critical"
    else:
        return "warning"

def _assess_burn_rate_risk(status: SLOStatus) -> str:
    """Assess overall burn rate risk level"""
    if status.burn_rate_1h > 10:
        return "critical"
    elif status.burn_rate_1h > 5 or status.burn_rate_6h > 3:
        return "high"
    elif status.burn_rate_24h > 1.5:
        return "medium"
    else:
        return "low"

@router.post("/evaluate", summary="Trigger SLO Evaluation")
async def trigger_slo_evaluation(
    background_tasks: BackgroundTasks,
    slo_name: Optional[str] = Query(None, description="Evaluate specific SLO only"),
    monitor: SLOMonitor = Depends(get_monitor),
    _auth = Depends(require_permission("slo:evaluate"))
) -> Dict[str, Any]:
    """
    Manually trigger SLO evaluation (useful for testing and debugging)
    """
    try:
        if slo_name:
            # Evaluate specific SLO
            slo_def = next((slo for slo in SLO_REGISTRY if slo.name == slo_name), None)
            if not slo_def:
                raise HTTPException(status_code=404, detail=f"SLO '{slo_name}' not found")
            
            status = await monitor.evaluate_slo(slo_def)
            
            return {
                "message": f"SLO '{slo_name}' evaluated successfully",
                "status": {
                    "slo_name": status.slo_name,
                    "current_sli": status.current_sli_value,
                    "compliance_status": status.compliance_status.value,
                    "error_budget_remaining": status.error_budget_remaining,
                    "alerts_active": status.alerts_active
                }
            }
        else:
            # Evaluate all SLOs in background
            background_tasks.add_task(monitor.evaluate_all_slos)
            
            return {
                "message": "SLO evaluation triggered for all SLOs",
                "total_slos": len(SLO_REGISTRY),
                "evaluation_started_at": datetime.utcnow().isoformat()
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error("slo_evaluation_trigger_error", error=str(e), slo_name=slo_name)
        raise HTTPException(status_code=500, detail=f"Failed to trigger SLO evaluation: {str(e)}")

@router.get("/runbooks", summary="Get Runbook Automation Status")
async def get_runbook_status(
    limit: int = Query(50, description="Limit number of executions returned"),
    _auth = Depends(require_auth)
) -> Dict[str, Any]:
    """
    Get runbook automation status and execution history
    """
    try:
        # Get runbook definitions
        definitions = runbook_engine.get_runbook_definitions()
        
        # Get execution history
        executions = runbook_engine.get_execution_history(limit=limit)
        
        # Format execution data
        execution_data = []
        for execution in executions:
            execution_data.append({
                "execution_id": execution.execution_id,
                "runbook_name": execution.runbook_name,
                "trigger_alert": execution.trigger_alert,
                "status": execution.status.value,
                "started_at": execution.started_at.isoformat(),
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
                "duration_seconds": (
                    (execution.completed_at - execution.started_at).total_seconds()
                    if execution.completed_at else None
                ),
                "steps_executed": len(execution.steps_executed or []),
                "error_message": execution.error_message
            })
        
        # Summary statistics
        recent_executions = [e for e in executions if e.started_at > datetime.utcnow() - timedelta(hours=24)]
        
        return {
            "runbook_definitions": {
                name: {
                    "name": rb.name,
                    "description": rb.description,
                    "severity": rb.severity.value,
                    "enabled": rb.enabled,
                    "trigger_conditions": rb.trigger_conditions,
                    "step_count": len(rb.steps),
                    "cooldown_minutes": rb.cooldown_minutes,
                    "max_executions_per_hour": rb.max_executions_per_hour,
                    "tags": rb.tags
                }
                for name, rb in definitions.items()
            },
            "execution_history": execution_data,
            "summary": {
                "total_runbooks": len(definitions),
                "enabled_runbooks": len([rb for rb in definitions.values() if rb.enabled]),
                "total_executions": len(executions),
                "executions_24h": len(recent_executions),
                "success_rate_24h": (
                    len([e for e in recent_executions if e.status.value == "success"]) / len(recent_executions) * 100
                    if recent_executions else 0
                )
            }
        }
        
    except Exception as e:
        logger.error("runbook_status_error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get runbook status: {str(e)}")

@router.post("/runbooks/{runbook_name}/execute", summary="Manually Execute Runbook")
async def execute_runbook_manually(
    runbook_name: str,
    background_tasks: BackgroundTasks,
    _auth = Depends(require_permission("runbook:execute"))
) -> Dict[str, Any]:
    """
    Manually execute a specific runbook (for testing and emergency response)
    """
    try:
        # Get runbook definition
        definitions = runbook_engine.get_runbook_definitions()
        if runbook_name not in definitions:
            raise HTTPException(status_code=404, detail=f"Runbook '{runbook_name}' not found")
        
        runbook = definitions[runbook_name]
        
        if not runbook.enabled:
            raise HTTPException(status_code=400, detail=f"Runbook '{runbook_name}' is disabled")
        
        # Create mock alert and SLO status for manual execution
        from slo_monitor import ErrorBudgetAlert, SLOStatus, SLOCompliance
        
        mock_alert = ErrorBudgetAlert(
            slo_name="manual_execution",
            alert_type="manual_trigger",
            severity="info",
            message=f"Manual execution of runbook {runbook_name}",
            current_value=0.0,
            threshold=0.0,
            window="manual",
            timestamp=datetime.utcnow(),
            runbook_url=""
        )
        
        mock_slo_status = SLOStatus(
            slo_name="manual_execution",
            service="manual",
            current_sli_value=100.0,
            target_percentage=99.0,
            compliance_period="manual",
            compliance_status=SLOCompliance.COMPLIANT,
            error_budget_remaining=100.0,
            error_budget_consumed=0.0,
            burn_rate_1h=0.0,
            burn_rate_6h=0.0,
            burn_rate_24h=0.0,
            burn_rate_72h=0.0,
            last_updated=datetime.utcnow(),
            alerts_active=[],
            metadata={"manual_execution": True}
        )
        
        # Execute runbook in background
        async def execute_runbook():
            try:
                execution = await runbook_engine._execute_runbook(runbook, mock_alert, mock_slo_status)
                logger.info(
                    "manual_runbook_execution_completed",
                    runbook_name=runbook_name,
                    execution_id=execution.execution_id,
                    status=execution.status.value
                )
            except Exception as e:
                logger.error(
                    "manual_runbook_execution_failed",
                    runbook_name=runbook_name,
                    error=str(e)
                )
        
        background_tasks.add_task(execute_runbook)
        
        return {
            "message": f"Runbook '{runbook_name}' execution started",
            "runbook_name": runbook_name,
            "execution_type": "manual",
            "started_at": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("manual_runbook_execution_error", error=str(e), runbook_name=runbook_name)
        raise HTTPException(status_code=500, detail=f"Failed to execute runbook: {str(e)}")

@router.get("/health", summary="SLO Monitoring Health Check")
async def slo_monitoring_health(
    monitor: SLOMonitor = Depends(get_monitor)
) -> Dict[str, Any]:
    """
    Health check for SLO monitoring system
    """
    try:
        # Test Prometheus connectivity
        prometheus_healthy = False
        try:
            async with monitor.prometheus_client() as prom:
                await prom.query("up")
                prometheus_healthy = True
        except Exception as e:
            logger.warning("prometheus_health_check_failed", error=str(e))
        
        # Check SLO definitions
        slo_definitions_count = len(SLO_REGISTRY)
        enabled_slos = len([slo for slo in SLO_REGISTRY if slo.enabled])
        
        # Check runbook system
        runbook_definitions = runbook_engine.get_runbook_definitions()
        enabled_runbooks = len([rb for rb in runbook_definitions.values() if rb.enabled])
        
        health_status = "healthy" if prometheus_healthy else "degraded"
        
        return {
            "status": health_status,
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "prometheus": {
                    "status": "healthy" if prometheus_healthy else "unhealthy",
                    "url": monitor.prometheus_url
                },
                "slo_definitions": {
                    "status": "healthy",
                    "total_slos": slo_definitions_count,
                    "enabled_slos": enabled_slos
                },
                "runbook_automation": {
                    "status": "healthy",
                    "total_runbooks": len(runbook_definitions),
                    "enabled_runbooks": enabled_runbooks
                }
            }
        }
        
    except Exception as e:
        logger.error("slo_health_check_error", error=str(e))
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }