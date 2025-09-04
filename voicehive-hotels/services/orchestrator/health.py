"""
Health Check Endpoint with Vault Monitoring
Provides comprehensive health status for orchestrator and dependencies
"""

from fastapi import APIRouter, HTTPException, Response
from typing import Dict, Any, List
from datetime import datetime, timezone
import asyncio
import logging
from enum import Enum

from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
from connectors.utils.vault_client_v2 import EnhancedVaultClient, VaultError

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth:
    """Health status for a single component"""
    def __init__(self, name: str, status: HealthStatus, details: Dict[str, Any] = None):
        self.name = name
        self.status = status
        self.details = details or {}
        self.checked_at = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "details": self.details,
            "checked_at": self.checked_at.isoformat()
        }


router = APIRouter(prefix="/health", tags=["health"])

# Prometheus metrics
g_overall_health = Gauge(
    "orchestrator_health",
    "Overall health status (1=healthy, 0=otherwise)",
    ["service"],
)
g_component_health = Gauge(
    "orchestrator_component_health",
    "Component health (1=healthy, 0=otherwise)",
    ["component"],
)
g_vault_token_valid = Gauge(
    "vault_token_valid",
    "Vault token validity (1=valid, 0=invalid)",
    ["service"],
)


class HealthChecker:
    """Orchestrator health checker with dependency monitoring"""
    
    def __init__(self):
        self.vault_client = None
        self._initialize_task = None
    
    async def initialize(self):
        """Initialize health checker components"""
        try:
            # Initialize Vault client
            self.vault_client = EnhancedVaultClient()
            await self.vault_client.initialize()
            logger.info("Health checker initialized")
        except Exception as e:
            logger.error(f"Failed to initialize health checker: {e}")
    
    async def check_vault_health(self) -> ComponentHealth:
        """Check Vault connectivity and health"""
        try:
            if not self.vault_client:
                return ComponentHealth(
                    name="vault",
                    status=HealthStatus.UNHEALTHY,
                    details={"error": "Vault client not initialized"}
                )
            
            # Get Vault health status
            vault_status = await self.vault_client.health_check()
            
            if vault_status.healthy:
                return ComponentHealth(
                    name="vault",
                    status=HealthStatus.HEALTHY,
                    details=vault_status.details
                )
            else:
                # Determine if degraded or unhealthy
                if vault_status.details.get("sealed"):
                    status = HealthStatus.UNHEALTHY
                else:
                    status = HealthStatus.DEGRADED
                
                return ComponentHealth(
                    name="vault",
                    status=status,
                    details=vault_status.details
                )
                
        except Exception as e:
            logger.error(f"Vault health check failed: {e}")
            return ComponentHealth(
                name="vault",
                status=HealthStatus.UNHEALTHY,
                details={"error": str(e)}
            )
    
    async def check_connector_health(self) -> ComponentHealth:
        """Check PMS connector availability"""
        try:
            # Import here to avoid circular dependency
            from connectors.factory import list_available_connectors
            
            available = list_available_connectors()
            total = len(available)
            
            if total == 0:
                return ComponentHealth(
                    name="pms_connectors",
                    status=HealthStatus.UNHEALTHY,
                    details={"error": "No connectors available"}
                )
            elif total < 3:  # Expected minimum connectors
                return ComponentHealth(
                    name="pms_connectors",
                    status=HealthStatus.DEGRADED,
                    details={
                        "available_count": total,
                        "available": available
                    }
                )
            else:
                return ComponentHealth(
                    name="pms_connectors",
                    status=HealthStatus.HEALTHY,
                    details={
                        "available_count": total,
                        "available": available[:5]  # Limit to first 5
                    }
                )
                
        except Exception as e:
            logger.error(f"Connector health check failed: {e}")
            return ComponentHealth(
                name="pms_connectors",
                status=HealthStatus.UNHEALTHY,
                details={"error": str(e)}
            )
    
    async def check_media_layer_health(self) -> ComponentHealth:
        """Check LiveKit media layer connectivity"""
        # TODO: Implement actual LiveKit health check
        return ComponentHealth(
            name="media_layer",
            status=HealthStatus.HEALTHY,
            details={"provider": "livekit", "region": "eu-west-1"}
        )
    
    async def check_ai_services_health(self) -> ComponentHealth:
        """Check AI services availability"""
        # TODO: Implement actual AI service checks
        return ComponentHealth(
            name="ai_services",
            status=HealthStatus.HEALTHY,
            details={
                "asr": "nvidia_riva",
                "tts": "elevenlabs",
                "llm": "azure_openai"
            }
        )
    
    async def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health status"""
        # Run all health checks concurrently
        checks = await asyncio.gather(
            self.check_vault_health(),
            self.check_connector_health(),
            self.check_media_layer_health(),
            self.check_ai_services_health(),
            return_exceptions=True
        )
        
        # Process results
        components = []
        overall_status = HealthStatus.HEALTHY
        
        for check in checks:
            if isinstance(check, Exception):
                components.append(ComponentHealth(
                    name="unknown",
                    status=HealthStatus.UNHEALTHY,
                    details={"error": str(check)}
                ))
                overall_status = HealthStatus.UNHEALTHY
            else:
                components.append(check)
                # Determine overall status
                if check.status == HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.UNHEALTHY
                elif check.status == HealthStatus.DEGRADED and overall_status != HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.DEGRADED
        
        return {
            "status": overall_status.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "voicehive-orchestrator",
            "version": "1.0.0",
            "components": [c.to_dict() for c in components]
        }


# Global health checker instance
health_checker = HealthChecker()


@router.on_event("startup")
async def startup_health_checker():
    """Initialize health checker on startup"""
    await health_checker.initialize()


@router.get("/", summary="Basic health check")
async def health_check() -> Dict[str, str]:
    """Basic health endpoint for load balancer"""
    return {
        "status": "healthy",
        "service": "voicehive-orchestrator",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/live", summary="Liveness probe")
async def liveness_probe() -> Dict[str, str]:
    """Kubernetes liveness probe endpoint"""
    return {"status": "alive"}


@router.get("/ready", summary="Readiness probe")
async def readiness_probe() -> Dict[str, Any]:
    """Kubernetes readiness probe endpoint"""
    health = await health_checker.get_system_health()
    
    # Return 503 if not ready
    if health["status"] == HealthStatus.UNHEALTHY.value:
        raise HTTPException(status_code=503, detail=health)
    
    return health


@router.get("/detailed", summary="Detailed health status")
async def detailed_health() -> Dict[str, Any]:
    """Detailed health status including all dependencies"""
    return await health_checker.get_system_health()


@router.get("/vault", summary="Vault connectivity check")
async def vault_health() -> Dict[str, Any]:
    """Specific Vault health check"""
    vault_status = await health_checker.check_vault_health()
    
    if vault_status.status == HealthStatus.UNHEALTHY:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "component": "vault",
                "details": vault_status.details
            }
        )
    
    return vault_status.to_dict()


@router.get("/connectors", summary="PMS connectors health")
async def connectors_health() -> Dict[str, Any]:
    """PMS connector availability check"""
    connector_status = await health_checker.check_connector_health()
    
    if connector_status.status == HealthStatus.UNHEALTHY:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "component": "pms_connectors",
                "details": connector_status.details
            }
        )
    
    return connector_status.to_dict()


# Prometheus metrics endpoint
@router.get("/metrics", summary="Prometheus metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint using official client."""
    health = await health_checker.get_system_health()

    # Update gauges
    overall = 1 if health["status"] == "healthy" else 0
    g_overall_health.labels(service="voicehive").set(overall)

    names = [c["name"] for c in health["components"]]
    for component in health["components"]:
        value = 1 if component["status"] == "healthy" else 0
        g_component_health.labels(component=component["name"]).set(value)
        if component["name"] == "vault":
            token_valid = 1 if component.get("details", {}).get("token_valid", False) else 0
            g_vault_token_valid.labels(service="voicehive").set(token_valid)

    content = generate_latest()
    return Response(content=content, headers={"Content-Type": CONTENT_TYPE_LATEST})
