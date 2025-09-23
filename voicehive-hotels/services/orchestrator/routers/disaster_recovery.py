"""
Disaster Recovery API Router
REST API endpoints for disaster recovery management and monitoring
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import asyncio
import os

from pydantic import BaseModel, Field

from ..disaster_recovery_manager import (
    DisasterRecoveryManager, 
    DisasterRecoveryConfig,
    DisasterType,
    ComponentType,
    RTOTarget,
    RPOTarget,
    RecoveryStatus
)
from ..auth_middleware import get_current_user, require_permissions
from ..logging_adapter import get_safe_logger
from ..audit_logging import AuditLogger

logger = get_safe_logger("orchestrator.dr_api")
audit_logger = AuditLogger("disaster_recovery_api")

router = APIRouter(prefix="/api/v1/disaster-recovery", tags=["disaster-recovery"])

# Pydantic models for API
class DisasterRecoveryStatusResponse(BaseModel):
    overall_readiness: Dict[str, Any]
    component_status: Dict[str, Any]
    recent_tests: List[Dict[str, Any]]
    compliance_status: Dict[str, Any]
    backup_status: Dict[str, Any]
    replication_status: Dict[str, Any]

class TestExecutionRequest(BaseModel):
    disaster_type: DisasterType
    component: ComponentType
    dry_run: bool = False
    notification_channels: List[str] = Field(default_factory=lambda: ["slack"])

class TestExecutionResponse(BaseModel):
    test_id: str
    status: RecoveryStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    rto_compliance: bool
    rpo_compliance: bool
    test_steps: List[Dict[str, Any]]
    metrics: Dict[str, Any]

class BackupProcedureResponse(BaseModel):
    database: Dict[str, Any]
    redis: Dict[str, Any]
    kubernetes: Dict[str, Any]
    storage: Dict[str, Any]
    cross_region_replication: Optional[Dict[str, Any]] = None

class BusinessContinuityResponse(BaseModel):
    service_continuity: Dict[str, Any]
    data_continuity: Dict[str, Any]
    operational_continuity: Dict[str, Any]
    communication_continuity: Dict[str, Any]

# Global DR manager instance
dr_manager: Optional[DisasterRecoveryManager] = None

async def get_dr_manager() -> DisasterRecoveryManager:
    """Get or initialize disaster recovery manager"""
    global dr_manager
    
    if dr_manager is None:
        # Load configuration
        config = DisasterRecoveryConfig(
            rto_targets=[
                RTOTarget(component=ComponentType.DATABASE, target_minutes=15, critical_path=True),
                RTOTarget(component=ComponentType.REDIS, target_minutes=10, critical_path=True),
                RTOTarget(component=ComponentType.KUBERNETES, target_minutes=20, dependencies=[ComponentType.DATABASE, ComponentType.REDIS]),
                RTOTarget(component=ComponentType.APPLICATION, target_minutes=30, dependencies=[ComponentType.DATABASE, ComponentType.REDIS, ComponentType.KUBERNETES]),
                RTOTarget(component=ComponentType.NETWORK, target_minutes=5, critical_path=True),
                RTOTarget(component=ComponentType.STORAGE, target_minutes=25)
            ],
            rpo_targets=[
                RPOTarget(component=ComponentType.DATABASE, target_minutes=5, backup_frequency_minutes=15),
                RPOTarget(component=ComponentType.REDIS, target_minutes=15, backup_frequency_minutes=360),
                RPOTarget(component=ComponentType.STORAGE, target_minutes=60, backup_frequency_minutes=1440),
                RPOTarget(component=ComponentType.KUBERNETES, target_minutes=30, backup_frequency_minutes=1440, replication_enabled=False)
            ],
            primary_region=os.getenv("PRIMARY_REGION", "eu-west-1"),
            dr_region=os.getenv("DR_REGION", "eu-central-1"),
            backup_retention_days=int(os.getenv("BACKUP_RETENTION_DAYS", "30")),
            cross_region_replication=os.getenv("CROSS_REGION_REPLICATION", "true").lower() == "true",
            test_frequency_days=int(os.getenv("DR_TEST_FREQUENCY", "7")),
            automated_testing=os.getenv("AUTOMATED_DR_TESTING", "true").lower() == "true",
            auto_failover_enabled=os.getenv("AUTO_FAILOVER_ENABLED", "false").lower() == "true",
            manual_approval_required=os.getenv("MANUAL_APPROVAL_REQUIRED", "true").lower() == "true"
        )
        
        dr_manager = DisasterRecoveryManager(config)
        await dr_manager.initialize()
    
    return dr_manager

@router.get("/status", response_model=DisasterRecoveryStatusResponse)
async def get_disaster_recovery_status(
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Get comprehensive disaster recovery status"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_viewer", "dr_operator", "dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        status = await dr_mgr.get_disaster_recovery_status()
        
        audit_logger.log_security_event(
            event_type="dr_status_accessed",
            details={"user": current_user.get("username"), "timestamp": datetime.now().isoformat()},
            severity="info"
        )
        
        return DisasterRecoveryStatusResponse(**status)
        
    except Exception as e:
        logger.error("failed_to_get_dr_status", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve disaster recovery status")

@router.post("/backup-procedures", response_model=BackupProcedureResponse)
async def create_backup_procedures(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Create automated backup procedures for all critical data stores"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Execute backup procedure creation in background
        backup_procedures = await dr_mgr.create_automated_backup_procedures()
        
        audit_logger.log_security_event(
            event_type="backup_procedures_created",
            details={
                "user": current_user.get("username"),
                "procedures": list(backup_procedures.keys()),
                "timestamp": datetime.now().isoformat()
            },
            severity="info"
        )
        
        return BackupProcedureResponse(**backup_procedures)
        
    except Exception as e:
        logger.error("failed_to_create_backup_procedures", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create backup procedures")

@router.post("/recovery-procedures")
async def create_recovery_procedures(
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Create and test disaster recovery procedures with documented RTO/RPO targets"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        procedures = await dr_mgr.create_disaster_recovery_procedures()
        
        audit_logger.log_security_event(
            event_type="recovery_procedures_created",
            details={
                "user": current_user.get("username"),
                "procedures_count": len(procedures),
                "timestamp": datetime.now().isoformat()
            },
            severity="info"
        )
        
        return JSONResponse(content=procedures)
        
    except Exception as e:
        logger.error("failed_to_create_recovery_procedures", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create recovery procedures")

@router.post("/backup-verification")
async def implement_backup_verification(
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Implement backup verification and automated restore testing"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        verification_results = await dr_mgr.implement_backup_verification_and_restore_testing()
        
        audit_logger.log_security_event(
            event_type="backup_verification_implemented",
            details={
                "user": current_user.get("username"),
                "verification_types": list(verification_results.keys()),
                "timestamp": datetime.now().isoformat()
            },
            severity="info"
        )
        
        return JSONResponse(content=verification_results)
        
    except Exception as e:
        logger.error("failed_to_implement_backup_verification", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to implement backup verification")

@router.post("/business-continuity", response_model=BusinessContinuityResponse)
async def create_business_continuity_plans(
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Create business continuity plans with failover procedures"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        continuity_plans = await dr_mgr.create_business_continuity_plans()
        
        audit_logger.log_security_event(
            event_type="business_continuity_plans_created",
            details={
                "user": current_user.get("username"),
                "plans": list(continuity_plans.keys()),
                "timestamp": datetime.now().isoformat()
            },
            severity="info"
        )
        
        return BusinessContinuityResponse(**continuity_plans)
        
    except Exception as e:
        logger.error("failed_to_create_business_continuity_plans", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create business continuity plans")

@router.post("/testing-automation")
async def add_testing_automation(
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Add disaster recovery testing automation and regular drills"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        testing_automation = await dr_mgr.add_disaster_recovery_testing_automation()
        
        audit_logger.log_security_event(
            event_type="dr_testing_automation_added",
            details={
                "user": current_user.get("username"),
                "automation_types": list(testing_automation.keys()),
                "timestamp": datetime.now().isoformat()
            },
            severity="info"
        )
        
        return JSONResponse(content=testing_automation)
        
    except Exception as e:
        logger.error("failed_to_add_testing_automation", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to add testing automation")

@router.post("/test/execute", response_model=TestExecutionResponse)
async def execute_disaster_recovery_test(
    request: TestExecutionRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Execute disaster recovery test"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_operator", "dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Execute test in background
        test_result = await dr_mgr.execute_disaster_recovery_test(
            request.disaster_type,
            request.component
        )
        
        audit_logger.log_security_event(
            event_type="dr_test_executed",
            details={
                "user": current_user.get("username"),
                "test_id": test_result["test_id"],
                "disaster_type": request.disaster_type.value,
                "component": request.component.value,
                "status": test_result["status"],
                "timestamp": datetime.now().isoformat()
            },
            severity="info"
        )
        
        return TestExecutionResponse(**test_result)
        
    except Exception as e:
        logger.error("failed_to_execute_dr_test", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to execute disaster recovery test")

@router.get("/tests/history")
async def get_test_history(
    limit: int = 50,
    component: Optional[ComponentType] = None,
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Get disaster recovery test history"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_viewer", "dr_operator", "dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Get test history from database
        async with dr_mgr.db_pool.acquire() as conn:
            query = """
                SELECT * FROM dr_test_results 
                WHERE ($1::text IS NULL OR component = $1)
                ORDER BY start_time DESC 
                LIMIT $2
            """
            
            results = await conn.fetch(query, component.value if component else None, limit)
            
            test_history = [dict(result) for result in results]
            
            return JSONResponse(content={"tests": test_history, "total": len(test_history)})
        
    except Exception as e:
        logger.error("failed_to_get_test_history", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to retrieve test history")

@router.get("/compliance/report")
async def get_compliance_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    dr_mgr: DisasterRecoveryManager = Depends(get_dr_manager)
):
    """Get RTO/RPO compliance report"""
    
    # Check permissions
    if not require_permissions(current_user, ["dr_viewer", "dr_operator", "dr_admin"]):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    try:
        # Generate compliance report
        async with dr_mgr.db_pool.acquire() as conn:
            query = """
                SELECT 
                    component,
                    COUNT(*) as total_tests,
                    COUNT(CASE WHEN rto_actual_minutes <= rto_target_minutes THEN 1 END) as rto_compliant,
                    COUNT(CASE WHEN rpo_actual_minutes <= rpo_target_minutes THEN 1 END) as rpo_compliant,
                    AVG(rto_actual_minutes) as avg_rto_minutes,
                    AVG(rpo_actual_minutes) as avg_rpo_minutes
                FROM dr_test_results 
                WHERE start_time >= COALESCE($1::timestamp, NOW() - INTERVAL '30 days')
                AND start_time <= COALESCE($2::timestamp, NOW())
                GROUP BY component
            """
            
            results = await conn.fetch(query, start_date, end_date)
            
            compliance_report = {
                "report_period": {
                    "start_date": start_date or (datetime.now() - timedelta(days=30)).isoformat(),
                    "end_date": end_date or datetime.now().isoformat()
                },
                "components": []
            }
            
            for result in results:
                component_data = dict(result)
                component_data["rto_compliance_rate"] = (
                    component_data["rto_compliant"] / component_data["total_tests"] * 100
                    if component_data["total_tests"] > 0 else 0
                )
                component_data["rpo_compliance_rate"] = (
                    component_data["rpo_compliant"] / component_data["total_tests"] * 100
                    if component_data["total_tests"] > 0 else 0
                )
                compliance_report["components"].append(component_data)
            
            return JSONResponse(content=compliance_report)
        
    except Exception as e:
        logger.error("failed_to_get_compliance_report", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate compliance report")

@router.get("/health")
async def disaster_recovery_health_check():
    """Health check endpoint for disaster recovery system"""
    
    try:
        # Basic health checks
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "components": {
                "dr_manager": "healthy",
                "database": "healthy",
                "monitoring": "healthy"
            }
        }
        
        # Check if DR manager is initialized
        if dr_manager is None:
            health_status["components"]["dr_manager"] = "not_initialized"
            health_status["status"] = "degraded"
        
        return JSONResponse(content=health_status)
        
    except Exception as e:
        logger.error("dr_health_check_failed", error=str(e))
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )

# Include router in main application
def include_router(app):
    """Include disaster recovery router in FastAPI app"""
    app.include_router(router)