"""
Health Check Endpoint with Vault Monitoring
Provides comprehensive health status for orchestrator and dependencies
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime, timezone
import asyncio
import logging
import os
from pydantic import BaseModel
from enum import Enum

from prometheus_client import Gauge
from connectors.utils.vault_client_v2 import EnhancedVaultClient

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
        try:
            import os
            import httpx
            
            # Get LiveKit configuration
            livekit_url = os.getenv("LIVEKIT_URL", "wss://voicehive.livekit.cloud")
            livekit_api_key = os.getenv("LIVEKIT_API_KEY")
            livekit_api_secret = os.getenv("LIVEKIT_API_SECRET")
            
            if not livekit_api_key or not livekit_api_secret:
                return ComponentHealth(
                    name="media_layer",
                    status=HealthStatus.UNHEALTHY,
                    details={"error": "LiveKit credentials not configured"}
                )
            
            # Convert WebSocket URL to HTTP for health check
            http_url = livekit_url.replace("wss://", "https://").replace("ws://", "http://")
            
            # Perform health check request
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{http_url}/health")
                
                if response.status_code == 200:
                    return ComponentHealth(
                        name="media_layer",
                        status=HealthStatus.HEALTHY,
                        details={
                            "provider": "livekit",
                            "url": livekit_url,
                            "response_time_ms": response.elapsed.total_seconds() * 1000
                        }
                    )
                else:
                    return ComponentHealth(
                        name="media_layer",
                        status=HealthStatus.DEGRADED,
                        details={
                            "provider": "livekit",
                            "url": livekit_url,
                            "status_code": response.status_code
                        }
                    )
                    
        except Exception as e:
            logger.error(f"LiveKit health check failed: {e}")
            return ComponentHealth(
                name="media_layer",
                status=HealthStatus.UNHEALTHY,
                details={"error": str(e), "provider": "livekit"}
            )
    
    async def check_ai_services_health(self) -> ComponentHealth:
        """Check AI services availability"""
        try:
            import os
            import httpx
            
            services_status = {}
            overall_healthy = True
            
            # Check ASR service (Riva proxy)
            asr_url = os.getenv("ASR_URL", "http://riva-proxy:8000")
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(f"{asr_url}/health")
                    if response.status_code == 200:
                        asr_data = response.json()
                        services_status["asr"] = {
                            "status": "healthy" if asr_data.get("riva_connected") else "unhealthy",
                            "provider": "nvidia_riva",
                            "connected": asr_data.get("riva_connected", False)
                        }
                        if not asr_data.get("riva_connected"):
                            overall_healthy = False
                    else:
                        services_status["asr"] = {"status": "unhealthy", "provider": "nvidia_riva"}
                        overall_healthy = False
            except Exception as e:
                services_status["asr"] = {"status": "unhealthy", "provider": "nvidia_riva", "error": str(e)}
                overall_healthy = False
            
            # Check TTS service
            tts_url = os.getenv("TTS_URL", "http://tts-router:9000")
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(f"{tts_url}/health")
                    if response.status_code == 200:
                        services_status["tts"] = {"status": "healthy", "provider": "elevenlabs_azure"}
                    else:
                        services_status["tts"] = {"status": "unhealthy", "provider": "elevenlabs_azure"}
                        overall_healthy = False
            except Exception as e:
                services_status["tts"] = {"status": "unhealthy", "provider": "elevenlabs_azure", "error": str(e)}
                overall_healthy = False
            
            # Check LLM service (Azure OpenAI)
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            azure_key = os.getenv("AZURE_OPENAI_KEY")
            if azure_endpoint and azure_key:
                try:
                    # Simple connectivity test to Azure OpenAI
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        # Test with a minimal request to check connectivity
                        headers = {
                            "api-key": azure_key,
                            "Content-Type": "application/json"
                        }
                        # Use the models endpoint for a lightweight check
                        response = await client.get(
                            f"{azure_endpoint}/openai/models?api-version=2024-02-01",
                            headers=headers
                        )
                        if response.status_code == 200:
                            services_status["llm"] = {"status": "healthy", "provider": "azure_openai"}
                        else:
                            services_status["llm"] = {"status": "unhealthy", "provider": "azure_openai"}
                            overall_healthy = False
                except Exception as e:
                    services_status["llm"] = {"status": "unhealthy", "provider": "azure_openai", "error": str(e)}
                    overall_healthy = False
            else:
                services_status["llm"] = {"status": "unconfigured", "provider": "azure_openai"}
                overall_healthy = False
            
            # Determine overall status
            if overall_healthy:
                status = HealthStatus.HEALTHY
            elif any(s.get("status") == "healthy" for s in services_status.values()):
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY
            
            return ComponentHealth(
                name="ai_services",
                status=status,
                details=services_status
            )
            
        except Exception as e:
            logger.error(f"AI services health check failed: {e}")
            return ComponentHealth(
                name="ai_services",
                status=HealthStatus.UNHEALTHY,
                details={"error": str(e)}
            )
    
    async def check_service_dependencies(self) -> ComponentHealth:
        """Check all service dependencies comprehensively"""
        try:
            import httpx
            
            dependencies = {}
            overall_healthy = True
            
            # Define service dependencies with their health endpoints
            services = {
                "redis": {
                    "url": os.getenv("REDIS_URL", "redis://localhost:6379"),
                    "check_method": "redis"
                },
                "database": {
                    "url": os.getenv("DATABASE_URL", ""),
                    "check_method": "database"
                },
                "asr_service": {
                    "url": os.getenv("ASR_URL", "http://riva-proxy:8000") + "/health",
                    "check_method": "http"
                },
                "tts_service": {
                    "url": os.getenv("TTS_URL", "http://tts-router:9000") + "/health",
                    "check_method": "http"
                },
                "livekit": {
                    "url": os.getenv("LIVEKIT_URL", "wss://voicehive.livekit.cloud"),
                    "check_method": "livekit"
                }
            }
            
            # Check each service
            for service_name, config in services.items():
                try:
                    if config["check_method"] == "http":
                        async with httpx.AsyncClient(timeout=3.0) as client:
                            response = await client.get(config["url"])
                            if response.status_code == 200:
                                service_data = response.json()
                                dependencies[service_name] = {
                                    "status": "healthy",
                                    "response_time_ms": response.elapsed.total_seconds() * 1000,
                                    "details": service_data
                                }
                            else:
                                dependencies[service_name] = {
                                    "status": "unhealthy",
                                    "status_code": response.status_code
                                }
                                overall_healthy = False
                    
                    elif config["check_method"] == "redis":
                        # Check Redis connectivity
                        import redis.asyncio as redis
                        redis_client = redis.from_url(config["url"])
                        await redis_client.ping()
                        await redis_client.close()
                        dependencies[service_name] = {"status": "healthy"}
                    
                    elif config["check_method"] == "database":
                        # Check database connectivity if configured
                        if config["url"]:
                            import asyncpg
                            conn = await asyncpg.connect(config["url"])
                            await conn.execute("SELECT 1")
                            await conn.close()
                            dependencies[service_name] = {"status": "healthy"}
                        else:
                            dependencies[service_name] = {"status": "not_configured"}
                    
                    elif config["check_method"] == "livekit":
                        # Check LiveKit connectivity
                        livekit_http_url = config["url"].replace("wss://", "https://").replace("ws://", "http://")
                        async with httpx.AsyncClient(timeout=3.0) as client:
                            response = await client.get(f"{livekit_http_url}/health")
                            if response.status_code == 200:
                                dependencies[service_name] = {
                                    "status": "healthy",
                                    "response_time_ms": response.elapsed.total_seconds() * 1000
                                }
                            else:
                                dependencies[service_name] = {
                                    "status": "unhealthy",
                                    "status_code": response.status_code
                                }
                                overall_healthy = False
                
                except Exception as e:
                    dependencies[service_name] = {
                        "status": "unhealthy",
                        "error": str(e)
                    }
                    overall_healthy = False
            
            # Determine overall status
            if overall_healthy:
                status = HealthStatus.HEALTHY
            elif any(d.get("status") == "healthy" for d in dependencies.values()):
                status = HealthStatus.DEGRADED
            else:
                status = HealthStatus.UNHEALTHY
            
            return ComponentHealth(
                name="service_dependencies",
                status=status,
                details=dependencies
            )
            
        except Exception as e:
            logger.error(f"Service dependency check failed: {e}")
            return ComponentHealth(
                name="service_dependencies",
                status=HealthStatus.UNHEALTHY,
                details={"error": str(e)}
            )

    async def get_system_health(self) -> Dict[str, Any]:
        """Get comprehensive system health status"""
        # Run all health checks concurrently
        checks = await asyncio.gather(
            self.check_vault_health(),
            self.check_connector_health(),
            self.check_media_layer_health(),
            self.check_ai_services_health(),
            self.check_service_dependencies(),
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
        
        # Update Prometheus metrics
        g_overall_health.labels(service="voicehive-orchestrator").set(
            1 if overall_status == HealthStatus.HEALTHY else 0
        )
        
        for component in components:
            g_component_health.labels(component=component.name).set(
                1 if component.status == HealthStatus.HEALTHY else 0
            )
        
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


@router.get("/dependencies", summary="Service dependencies health")
async def dependencies_health() -> Dict[str, Any]:
    """Check all service dependencies"""
    dependencies_status = await health_checker.check_service_dependencies()
    
    if dependencies_status.status == HealthStatus.UNHEALTHY:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "component": "service_dependencies",
                "details": dependencies_status.details
            }
        )
    
    return dependencies_status.to_dict()


# Note: Prometheus metrics are exposed at the root /metrics endpoint in app.py
# This health router focuses on health checks only
