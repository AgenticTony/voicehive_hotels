"""
Runbook Automation System for VoiceHive Hotels
Automated incident response and remediation based on SLO violations
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import aiohttp
from logging_adapter import get_safe_logger
from slo_monitor import SLOStatus, ErrorBudgetAlert, SLOCompliance

logger = get_safe_logger("runbook_automation")

class RunbookSeverity(str, Enum):
    """Runbook execution severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class RunbookStatus(str, Enum):
    """Runbook execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

@dataclass
class RunbookStep:
    """Individual runbook step definition"""
    name: str
    description: str
    action_type: str  # "command", "api_call", "notification", "check"
    action_config: Dict[str, Any]
    timeout_seconds: int = 300
    retry_count: int = 3
    required: bool = True
    condition: Optional[str] = None  # Optional condition to execute step

@dataclass
class RunbookDefinition:
    """Complete runbook definition"""
    name: str
    description: str
    trigger_conditions: List[str]  # Alert names or SLO conditions
    severity: RunbookSeverity
    steps: List[RunbookStep]
    cooldown_minutes: int = 30  # Minimum time between executions
    max_executions_per_hour: int = 5
    enabled: bool = True
    tags: Dict[str, str]

@dataclass
class RunbookExecution:
    """Runbook execution instance"""
    execution_id: str
    runbook_name: str
    trigger_alert: str
    status: RunbookStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    steps_executed: List[Dict[str, Any]] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = None

class RunbookActionExecutor:
    """Executes different types of runbook actions"""
    
    def __init__(self):
        self.action_handlers = {
            "command": self._execute_command,
            "api_call": self._execute_api_call,
            "notification": self._send_notification,
            "check": self._execute_check,
            "scale_service": self._scale_service,
            "restart_service": self._restart_service,
            "circuit_breaker_reset": self._reset_circuit_breaker,
            "clear_cache": self._clear_cache,
            "database_connection_reset": self._reset_database_connections
        }
    
    async def execute_step(self, step: RunbookStep, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single runbook step"""
        start_time = datetime.utcnow()
        
        try:
            # Check condition if specified
            if step.condition and not self._evaluate_condition(step.condition, context):
                return {
                    "step_name": step.name,
                    "status": "skipped",
                    "reason": f"Condition not met: {step.condition}",
                    "duration_seconds": 0
                }
            
            # Get action handler
            handler = self.action_handlers.get(step.action_type)
            if not handler:
                raise ValueError(f"Unknown action type: {step.action_type}")
            
            # Execute with timeout and retries
            result = await self._execute_with_retry(
                handler, step, context, step.retry_count, step.timeout_seconds
            )
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            return {
                "step_name": step.name,
                "status": "success",
                "result": result,
                "duration_seconds": duration
            }
            
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            
            logger.error(
                "runbook_step_failed",
                step_name=step.name,
                action_type=step.action_type,
                error=str(e),
                duration_seconds=duration
            )
            
            return {
                "step_name": step.name,
                "status": "failed",
                "error": str(e),
                "duration_seconds": duration
            }
    
    async def _execute_with_retry(self, handler: Callable, step: RunbookStep, 
                                 context: Dict[str, Any], retry_count: int, 
                                 timeout_seconds: int) -> Any:
        """Execute handler with retry logic"""
        last_error = None
        
        for attempt in range(retry_count + 1):
            try:
                return await asyncio.wait_for(
                    handler(step, context),
                    timeout=timeout_seconds
                )
            except Exception as e:
                last_error = e
                if attempt < retry_count:
                    wait_time = min(2 ** attempt, 30)  # Exponential backoff, max 30s
                    await asyncio.sleep(wait_time)
                    logger.warning(
                        "runbook_step_retry",
                        step_name=step.name,
                        attempt=attempt + 1,
                        max_attempts=retry_count + 1,
                        error=str(e)
                    )
        
        raise last_error
    
    def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """Evaluate step execution condition"""
        try:
            # Simple condition evaluation - can be extended
            # Format: "context.key operator value"
            # Example: "slo_status.error_budget_remaining < 10"
            
            # For now, implement basic conditions
            if "error_budget_remaining" in condition:
                if "<" in condition:
                    threshold = float(condition.split("<")[1].strip())
                    return context.get("error_budget_remaining", 100) < threshold
                elif ">" in condition:
                    threshold = float(condition.split(">")[1].strip())
                    return context.get("error_budget_remaining", 0) > threshold
            
            return True  # Default to true if condition can't be evaluated
            
        except Exception as e:
            logger.warning(
                "condition_evaluation_failed",
                condition=condition,
                error=str(e)
            )
            return True
    
    async def _execute_command(self, step: RunbookStep, context: Dict[str, Any]) -> str:
        """Execute shell command"""
        command = step.action_config.get("command", "")
        
        # Template substitution
        for key, value in context.items():
            command = command.replace(f"{{{key}}}", str(value))
        
        logger.info(
            "executing_command",
            step_name=step.name,
            command=command
        )
        
        # In production, use proper subprocess execution with security controls
        # For now, simulate command execution
        await asyncio.sleep(1)  # Simulate execution time
        
        return f"Command executed: {command}"
    
    async def _execute_api_call(self, step: RunbookStep, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute HTTP API call"""
        config = step.action_config
        url = config.get("url", "")
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        payload = config.get("payload", {})
        
        # Template substitution
        for key, value in context.items():
            url = url.replace(f"{{{key}}}", str(value))
            if isinstance(payload, dict):
                payload = json.loads(json.dumps(payload).replace(f"{{{key}}}", str(value)))
        
        logger.info(
            "executing_api_call",
            step_name=step.name,
            method=method,
            url=url
        )
        
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                json=payload if method in ["POST", "PUT", "PATCH"] else None
            ) as response:
                response.raise_for_status()
                result = await response.json() if response.content_type == "application/json" else await response.text()
                
                return {
                    "status_code": response.status,
                    "response": result
                }
    
    async def _send_notification(self, step: RunbookStep, context: Dict[str, Any]) -> str:
        """Send notification"""
        config = step.action_config
        notification_type = config.get("type", "slack")
        message = config.get("message", "")
        
        # Template substitution
        for key, value in context.items():
            message = message.replace(f"{{{key}}}", str(value))
        
        logger.info(
            "sending_notification",
            step_name=step.name,
            type=notification_type,
            message=message
        )
        
        # Simulate notification sending
        await asyncio.sleep(0.5)
        
        return f"Notification sent via {notification_type}: {message}"
    
    async def _execute_check(self, step: RunbookStep, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute health check or validation"""
        config = step.action_config
        check_type = config.get("type", "http")
        
        if check_type == "http":
            url = config.get("url", "")
            expected_status = config.get("expected_status", 200)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    success = response.status == expected_status
                    
                    return {
                        "check_type": check_type,
                        "success": success,
                        "status_code": response.status,
                        "expected_status": expected_status
                    }
        
        return {"check_type": check_type, "success": True}
    
    async def _scale_service(self, step: RunbookStep, context: Dict[str, Any]) -> str:
        """Scale Kubernetes service"""
        config = step.action_config
        service_name = config.get("service_name", "")
        replicas = config.get("replicas", 1)
        namespace = config.get("namespace", "voicehive-production")
        
        logger.info(
            "scaling_service",
            step_name=step.name,
            service_name=service_name,
            replicas=replicas,
            namespace=namespace
        )
        
        # In production, use Kubernetes API
        await asyncio.sleep(2)  # Simulate scaling time
        
        return f"Scaled {service_name} to {replicas} replicas in namespace {namespace}"
    
    async def _restart_service(self, step: RunbookStep, context: Dict[str, Any]) -> str:
        """Restart Kubernetes service"""
        config = step.action_config
        service_name = config.get("service_name", "")
        namespace = config.get("namespace", "voicehive-production")
        
        logger.info(
            "restarting_service",
            step_name=step.name,
            service_name=service_name,
            namespace=namespace
        )
        
        # In production, use Kubernetes API to restart deployment
        await asyncio.sleep(3)  # Simulate restart time
        
        return f"Restarted service {service_name} in namespace {namespace}"
    
    async def _reset_circuit_breaker(self, step: RunbookStep, context: Dict[str, Any]) -> str:
        """Reset circuit breaker state"""
        config = step.action_config
        service_name = config.get("service_name", "")
        
        logger.info(
            "resetting_circuit_breaker",
            step_name=step.name,
            service_name=service_name
        )
        
        # In production, call circuit breaker reset API
        await asyncio.sleep(1)
        
        return f"Reset circuit breaker for service {service_name}"
    
    async def _clear_cache(self, step: RunbookStep, context: Dict[str, Any]) -> str:
        """Clear Redis cache"""
        config = step.action_config
        cache_pattern = config.get("pattern", "*")
        
        logger.info(
            "clearing_cache",
            step_name=step.name,
            pattern=cache_pattern
        )
        
        # In production, connect to Redis and clear cache
        await asyncio.sleep(1)
        
        return f"Cleared cache with pattern: {cache_pattern}"
    
    async def _reset_database_connections(self, step: RunbookStep, context: Dict[str, Any]) -> str:
        """Reset database connection pool"""
        config = step.action_config
        pool_name = config.get("pool_name", "default")
        
        logger.info(
            "resetting_db_connections",
            step_name=step.name,
            pool_name=pool_name
        )
        
        # In production, reset connection pool
        await asyncio.sleep(2)
        
        return f"Reset database connection pool: {pool_name}"

class RunbookAutomationEngine:
    """Main runbook automation engine"""
    
    def __init__(self):
        self.runbooks: Dict[str, RunbookDefinition] = {}
        self.execution_history: List[RunbookExecution] = []
        self.executor = RunbookActionExecutor()
        self.cooldown_tracker: Dict[str, datetime] = {}
        self.execution_counter: Dict[str, List[datetime]] = {}
        
        # Load default runbooks
        self._load_default_runbooks()
    
    def _load_default_runbooks(self):
        """Load default runbook definitions"""
        
        # API Availability SLO Violation Runbook
        self.runbooks["api_availability_slo_violation"] = RunbookDefinition(
            name="api_availability_slo_violation",
            description="Automated response to API availability SLO violations",
            trigger_conditions=["VoiceHiveAPIAvailabilityFastBurnRate", "VoiceHiveAPIAvailabilityErrorBudgetExhaustion"],
            severity=RunbookSeverity.CRITICAL,
            steps=[
                RunbookStep(
                    name="check_service_health",
                    description="Check orchestrator service health",
                    action_type="check",
                    action_config={
                        "type": "http",
                        "url": "http://voicehive-orchestrator:8000/health",
                        "expected_status": 200
                    }
                ),
                RunbookStep(
                    name="notify_oncall",
                    description="Notify on-call team",
                    action_type="notification",
                    action_config={
                        "type": "slack",
                        "message": "🚨 API Availability SLO violation detected. Current SLI: {current_sli}%. Error budget remaining: {error_budget_remaining}%"
                    }
                ),
                RunbookStep(
                    name="scale_orchestrator",
                    description="Scale orchestrator service",
                    action_type="scale_service",
                    action_config={
                        "service_name": "voicehive-orchestrator",
                        "replicas": 5,
                        "namespace": "voicehive-production"
                    },
                    condition="error_budget_remaining < 20"
                ),
                RunbookStep(
                    name="reset_circuit_breakers",
                    description="Reset all circuit breakers",
                    action_type="circuit_breaker_reset",
                    action_config={
                        "service_name": "all"
                    }
                ),
                RunbookStep(
                    name="verify_recovery",
                    description="Verify service recovery",
                    action_type="check",
                    action_config={
                        "type": "http",
                        "url": "http://voicehive-orchestrator:8000/health",
                        "expected_status": 200
                    }
                )
            ],
            cooldown_minutes=15,
            max_executions_per_hour=3,
            tags={"service": "orchestrator", "type": "availability"}
        )
        
        # High Latency SLO Violation Runbook
        self.runbooks["api_latency_slo_violation"] = RunbookDefinition(
            name="api_latency_slo_violation",
            description="Automated response to API latency SLO violations",
            trigger_conditions=["VoiceHiveAPILatencyFastBurnRate"],
            severity=RunbookSeverity.HIGH,
            steps=[
                RunbookStep(
                    name="clear_application_cache",
                    description="Clear application cache to improve performance",
                    action_type="clear_cache",
                    action_config={
                        "pattern": "voicehive:cache:*"
                    }
                ),
                RunbookStep(
                    name="reset_db_connections",
                    description="Reset database connection pool",
                    action_type="database_connection_reset",
                    action_config={
                        "pool_name": "orchestrator_pool"
                    }
                ),
                RunbookStep(
                    name="notify_performance_team",
                    description="Notify performance team",
                    action_type="notification",
                    action_config={
                        "type": "slack",
                        "message": "⚠️ API Latency SLO violation. P95 latency degraded. Automated remediation in progress."
                    }
                ),
                RunbookStep(
                    name="check_latency_improvement",
                    description="Verify latency improvement",
                    action_type="api_call",
                    action_config={
                        "method": "GET",
                        "url": "http://prometheus:9090/api/v1/query?query=histogram_quantile(0.95,rate(voicehive_request_duration_seconds_bucket[5m]))"
                    }
                )
            ],
            cooldown_minutes=10,
            max_executions_per_hour=5,
            tags={"service": "orchestrator", "type": "latency"}
        )
        
        # Call Success Rate SLO Violation Runbook
        self.runbooks["call_success_slo_violation"] = RunbookDefinition(
            name="call_success_slo_violation",
            description="Automated response to call success rate SLO violations",
            trigger_conditions=["VoiceHiveCallSuccessFastBurnRate"],
            severity=RunbookSeverity.CRITICAL,
            steps=[
                RunbookStep(
                    name="check_pms_connectivity",
                    description="Check PMS connector health",
                    action_type="check",
                    action_config={
                        "type": "http",
                        "url": "http://voicehive-orchestrator:8000/health/pms",
                        "expected_status": 200
                    }
                ),
                RunbookStep(
                    name="restart_call_manager",
                    description="Restart call manager service",
                    action_type="restart_service",
                    action_config={
                        "service_name": "voicehive-call-manager",
                        "namespace": "voicehive-production"
                    },
                    condition="error_budget_remaining < 10"
                ),
                RunbookStep(
                    name="notify_voice_team",
                    description="Notify voice engineering team",
                    action_type="notification",
                    action_config={
                        "type": "slack",
                        "message": "🔴 Call Success Rate SLO violation. Current success rate: {current_sli}%. Investigating call failures."
                    }
                ),
                RunbookStep(
                    name="enable_fallback_mode",
                    description="Enable fallback mode for voice processing",
                    action_type="api_call",
                    action_config={
                        "method": "POST",
                        "url": "http://voicehive-orchestrator:8000/admin/fallback-mode",
                        "payload": {"enabled": True, "reason": "SLO violation"}
                    }
                )
            ],
            cooldown_minutes=20,
            max_executions_per_hour=2,
            tags={"service": "call-manager", "type": "business"}
        )
        
        # Database Connection Pool Exhaustion Runbook
        self.runbooks["database_connection_exhaustion"] = RunbookDefinition(
            name="database_connection_exhaustion",
            description="Automated response to database connection pool exhaustion",
            trigger_conditions=["VoiceHiveConnectionPoolExhaustion"],
            severity=RunbookSeverity.HIGH,
            steps=[
                RunbookStep(
                    name="reset_connection_pool",
                    description="Reset database connection pool",
                    action_type="database_connection_reset",
                    action_config={
                        "pool_name": "main_pool"
                    }
                ),
                RunbookStep(
                    name="scale_database_connections",
                    description="Increase database connection pool size",
                    action_type="api_call",
                    action_config={
                        "method": "POST",
                        "url": "http://voicehive-orchestrator:8000/admin/db-pool/scale",
                        "payload": {"max_connections": 30}
                    }
                ),
                RunbookStep(
                    name="notify_dba_team",
                    description="Notify database team",
                    action_type="notification",
                    action_config={
                        "type": "slack",
                        "message": "⚠️ Database connection pool exhaustion detected. Pool scaled automatically."
                    }
                )
            ],
            cooldown_minutes=5,
            max_executions_per_hour=10,
            tags={"service": "database", "type": "infrastructure"}
        )
    
    async def trigger_runbook(self, alert: ErrorBudgetAlert, slo_status: SLOStatus) -> Optional[RunbookExecution]:
        """Trigger appropriate runbook based on alert"""
        
        # Find matching runbook
        matching_runbook = None
        for runbook in self.runbooks.values():
            if not runbook.enabled:
                continue
                
            if any(condition in alert.alert_type or condition in alert.slo_name 
                   for condition in runbook.trigger_conditions):
                matching_runbook = runbook
                break
        
        if not matching_runbook:
            logger.info(
                "no_matching_runbook",
                alert_type=alert.alert_type,
                slo_name=alert.slo_name
            )
            return None
        
        # Check cooldown and rate limits
        if not self._can_execute_runbook(matching_runbook):
            logger.info(
                "runbook_execution_throttled",
                runbook_name=matching_runbook.name,
                reason="cooldown or rate limit"
            )
            return None
        
        # Execute runbook
        execution = await self._execute_runbook(matching_runbook, alert, slo_status)
        
        # Update tracking
        self._update_execution_tracking(matching_runbook.name)
        
        return execution
    
    def _can_execute_runbook(self, runbook: RunbookDefinition) -> bool:
        """Check if runbook can be executed (cooldown and rate limits)"""
        now = datetime.utcnow()
        
        # Check cooldown
        last_execution = self.cooldown_tracker.get(runbook.name)
        if last_execution:
            cooldown_expires = last_execution + timedelta(minutes=runbook.cooldown_minutes)
            if now < cooldown_expires:
                return False
        
        # Check rate limit
        executions = self.execution_counter.get(runbook.name, [])
        hour_ago = now - timedelta(hours=1)
        recent_executions = [exec_time for exec_time in executions if exec_time > hour_ago]
        
        if len(recent_executions) >= runbook.max_executions_per_hour:
            return False
        
        return True
    
    def _update_execution_tracking(self, runbook_name: str):
        """Update execution tracking for cooldown and rate limiting"""
        now = datetime.utcnow()
        
        # Update cooldown tracker
        self.cooldown_tracker[runbook_name] = now
        
        # Update execution counter
        if runbook_name not in self.execution_counter:
            self.execution_counter[runbook_name] = []
        
        self.execution_counter[runbook_name].append(now)
        
        # Clean old entries (keep only last 24 hours)
        day_ago = now - timedelta(hours=24)
        self.execution_counter[runbook_name] = [
            exec_time for exec_time in self.execution_counter[runbook_name] 
            if exec_time > day_ago
        ]
    
    async def _execute_runbook(self, runbook: RunbookDefinition, alert: ErrorBudgetAlert, 
                              slo_status: SLOStatus) -> RunbookExecution:
        """Execute a runbook"""
        execution_id = f"{runbook.name}_{int(datetime.utcnow().timestamp())}"
        
        execution = RunbookExecution(
            execution_id=execution_id,
            runbook_name=runbook.name,
            trigger_alert=alert.alert_type,
            status=RunbookStatus.RUNNING,
            started_at=datetime.utcnow(),
            steps_executed=[],
            metadata={
                "alert": asdict(alert),
                "slo_status": asdict(slo_status)
            }
        )
        
        logger.info(
            "runbook_execution_started",
            execution_id=execution_id,
            runbook_name=runbook.name,
            trigger_alert=alert.alert_type
        )
        
        try:
            # Prepare execution context
            context = {
                "alert": alert,
                "slo_status": slo_status,
                "current_sli": slo_status.current_sli_value,
                "error_budget_remaining": slo_status.error_budget_remaining,
                "execution_id": execution_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Execute steps
            for step in runbook.steps:
                step_result = await self.executor.execute_step(step, context)
                execution.steps_executed.append(step_result)
                
                # Stop execution if required step failed
                if step.required and step_result.get("status") == "failed":
                    execution.status = RunbookStatus.FAILED
                    execution.error_message = f"Required step '{step.name}' failed: {step_result.get('error')}"
                    break
            
            # Mark as successful if we completed all steps
            if execution.status == RunbookStatus.RUNNING:
                execution.status = RunbookStatus.SUCCESS
            
        except Exception as e:
            execution.status = RunbookStatus.FAILED
            execution.error_message = str(e)
            
            logger.error(
                "runbook_execution_failed",
                execution_id=execution_id,
                runbook_name=runbook.name,
                error=str(e)
            )
        
        finally:
            execution.completed_at = datetime.utcnow()
            self.execution_history.append(execution)
            
            logger.info(
                "runbook_execution_completed",
                execution_id=execution_id,
                runbook_name=runbook.name,
                status=execution.status.value,
                duration_seconds=(execution.completed_at - execution.started_at).total_seconds()
            )
        
        return execution
    
    def get_execution_history(self, limit: int = 100) -> List[RunbookExecution]:
        """Get recent runbook execution history"""
        return sorted(
            self.execution_history,
            key=lambda x: x.started_at,
            reverse=True
        )[:limit]
    
    def get_runbook_definitions(self) -> Dict[str, RunbookDefinition]:
        """Get all runbook definitions"""
        return self.runbooks.copy()
    
    def add_runbook(self, runbook: RunbookDefinition):
        """Add or update a runbook definition"""
        self.runbooks[runbook.name] = runbook
        
        logger.info(
            "runbook_added",
            runbook_name=runbook.name,
            severity=runbook.severity.value,
            step_count=len(runbook.steps)
        )
    
    def remove_runbook(self, runbook_name: str) -> bool:
        """Remove a runbook definition"""
        if runbook_name in self.runbooks:
            del self.runbooks[runbook_name]
            logger.info("runbook_removed", runbook_name=runbook_name)
            return True
        return False

# Global runbook automation engine
runbook_engine = RunbookAutomationEngine()