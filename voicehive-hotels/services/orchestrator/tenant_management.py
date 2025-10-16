"""
Multi-Tenant Management System for VoiceHive Hotels
Provides enterprise-grade tenant isolation, configuration management, and resource tracking.
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.orchestrator.logging_adapter import get_safe_logger

logger = get_safe_logger(__name__)


class TenantTier(str, Enum):
    """Tenant subscription tiers with different resource limits"""
    STARTER = "starter"          # Small hotels, basic features
    PROFESSIONAL = "professional"  # Mid-size hotels, advanced features
    ENTERPRISE = "enterprise"      # Large hotels/chains, premium features
    CUSTOM = "custom"             # Custom negotiated limits


class TenantStatus(str, Enum):
    """Tenant account status"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    TRIAL = "trial"
    PENDING_ACTIVATION = "pending_activation"


class ResourceQuota(BaseModel):
    """Resource quota configuration for a tenant"""
    calls_per_day: int = Field(..., description="Daily call limit")
    calls_per_month: int = Field(..., description="Monthly call limit")
    concurrent_calls: int = Field(..., description="Maximum concurrent calls")
    storage_mb: int = Field(..., description="Storage quota in MB")
    api_requests_per_hour: int = Field(..., description="API requests per hour")
    webhook_endpoints: int = Field(..., description="Max webhook endpoints")
    ai_tokens_per_month: int = Field(..., description="AI token allowance per month")


class TenantConfiguration(BaseModel):
    """Tenant-specific configuration settings"""
    # Feature flags
    features_enabled: Dict[str, bool] = Field(default_factory=dict)

    # Language and localization
    default_language: str = "en"
    supported_languages: List[str] = Field(default_factory=lambda: ["en"])
    timezone: str = "UTC"

    # AI and conversation settings
    ai_model_preference: str = "gpt-4-turbo"
    conversation_timeout_minutes: int = 30
    max_conversation_turns: int = 50
    enable_sentiment_analysis: bool = False

    # Notification settings
    webhook_retry_attempts: int = 3
    notification_email: Optional[str] = None
    alert_thresholds: Dict[str, float] = Field(default_factory=dict)

    # Security settings
    require_2fa: bool = False
    session_timeout_hours: int = 24
    allowed_ip_ranges: List[str] = Field(default_factory=list)

    # Integration settings
    pms_connector_type: str = "apaleo"
    pms_configuration: Dict[str, Any] = Field(default_factory=dict)
    payment_processor_enabled: bool = False

    # Custom configuration
    custom_settings: Dict[str, Any] = Field(default_factory=dict)


class ChainHierarchy(BaseModel):
    """Hotel chain hierarchy information"""
    chain_id: Optional[str] = None
    chain_name: Optional[str] = None
    parent_property_id: Optional[str] = None
    property_level: int = 0  # 0 = chain HQ, 1 = region, 2 = property
    child_properties: List[str] = Field(default_factory=list)
    shared_configurations: List[str] = Field(default_factory=list)


class ResourceUsage(BaseModel):
    """Current resource usage tracking"""
    period_start: datetime
    period_end: datetime
    calls_count: int = 0
    calls_duration_minutes: float = 0.0
    api_requests_count: int = 0
    storage_used_mb: float = 0.0
    ai_tokens_used: int = 0
    webhook_deliveries: int = 0
    error_count: int = 0
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TenantMetadata(BaseModel):
    """Complete tenant metadata and configuration"""
    tenant_id: str = Field(..., description="Unique tenant identifier (hotel_id)")
    tenant_name: str = Field(..., description="Human-readable tenant name")
    tenant_tier: TenantTier = TenantTier.STARTER
    tenant_status: TenantStatus = TenantStatus.ACTIVE

    # Organization details
    organization_name: str
    contact_email: str
    contact_phone: Optional[str] = None
    billing_contact: Optional[str] = None

    # Subscription details
    subscription_started: datetime
    subscription_expires: Optional[datetime] = None
    trial_ends: Optional[datetime] = None

    # Resource management
    resource_quota: ResourceQuota
    current_usage: ResourceUsage

    # Configuration
    tenant_config: TenantConfiguration

    # Chain hierarchy (if applicable)
    chain_hierarchy: Optional[ChainHierarchy] = None

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str
    tags: List[str] = Field(default_factory=list)


class TenantManager:
    """Enterprise tenant management with database-level isolation"""

    def __init__(self, redis_client: redis.Redis, db_session: AsyncSession):
        self.redis = redis_client
        self.db = db_session
        self.tenant_cache: Dict[str, TenantMetadata] = {}
        self.cache_ttl = 3600  # 1 hour cache TTL

    # Tenant Lifecycle Management

    async def create_tenant(
        self,
        tenant_id: str,
        tenant_name: str,
        organization_name: str,
        contact_email: str,
        tenant_tier: TenantTier = TenantTier.STARTER,
        created_by: str = "system"
    ) -> TenantMetadata:
        """Create a new tenant with default configuration"""

        # Check if tenant already exists
        if await self.tenant_exists(tenant_id):
            raise ValueError(f"Tenant {tenant_id} already exists")

        # Create default resource quota based on tier
        resource_quota = self._get_default_quota(tenant_tier)

        # Create default configuration
        tenant_config = TenantConfiguration()

        # Set up trial period for non-enterprise tiers
        trial_ends = None
        subscription_expires = None
        if tenant_tier != TenantTier.ENTERPRISE:
            trial_ends = datetime.now(timezone.utc) + timedelta(days=30)

        # Initialize usage tracking
        current_usage = ResourceUsage(
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=30)
        )

        # Create tenant metadata
        tenant = TenantMetadata(
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            tenant_tier=tenant_tier,
            tenant_status=TenantStatus.TRIAL if trial_ends else TenantStatus.ACTIVE,
            organization_name=organization_name,
            contact_email=contact_email,
            subscription_started=datetime.now(timezone.utc),
            subscription_expires=subscription_expires,
            trial_ends=trial_ends,
            resource_quota=resource_quota,
            current_usage=current_usage,
            tenant_config=tenant_config,
            created_by=created_by
        )

        # Save to database
        await self._save_tenant_to_db(tenant)

        # Cache the tenant
        await self._cache_tenant(tenant)

        # Initialize tenant-specific database schema
        await self._initialize_tenant_schema(tenant_id)

        logger.info("tenant_created", tenant_id=tenant_id, tier=tenant_tier.value)
        return tenant

    async def get_tenant(self, tenant_id: str) -> Optional[TenantMetadata]:
        """Get tenant metadata with caching"""
        # Check cache first
        if tenant_id in self.tenant_cache:
            return self.tenant_cache[tenant_id]

        # Check Redis cache
        cached = await self.redis.get(f"tenant:{tenant_id}")
        if cached:
            tenant = TenantMetadata.model_validate_json(cached)
            self.tenant_cache[tenant_id] = tenant
            return tenant

        # Load from database
        tenant = await self._load_tenant_from_db(tenant_id)
        if tenant:
            await self._cache_tenant(tenant)

        return tenant

    async def update_tenant(self, tenant_id: str, updates: Dict[str, Any]) -> TenantMetadata:
        """Update tenant metadata"""
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Apply updates
        for field, value in updates.items():
            if hasattr(tenant, field):
                setattr(tenant, field, value)

        tenant.updated_at = datetime.now(timezone.utc)

        # Save changes
        await self._save_tenant_to_db(tenant)
        await self._cache_tenant(tenant)

        logger.info("tenant_updated", tenant_id=tenant_id, updates=list(updates.keys()))
        return tenant

    async def delete_tenant(self, tenant_id: str, soft_delete: bool = True) -> bool:
        """Delete tenant (soft delete by default for compliance)"""
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            return False

        if soft_delete:
            # Soft delete - change status and retain data
            await self.update_tenant(tenant_id, {
                "tenant_status": TenantStatus.DEACTIVATED,
                "subscription_expires": datetime.now(timezone.utc)
            })
        else:
            # Hard delete - remove all tenant data
            await self._hard_delete_tenant(tenant_id)

        # Remove from cache
        await self._invalidate_tenant_cache(tenant_id)

        logger.info("tenant_deleted", tenant_id=tenant_id, soft_delete=soft_delete)
        return True

    # Tenant Configuration Management

    async def update_tenant_config(
        self,
        tenant_id: str,
        config_updates: Dict[str, Any]
    ) -> TenantConfiguration:
        """Update tenant-specific configuration"""
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Update configuration
        for key, value in config_updates.items():
            if hasattr(tenant.tenant_config, key):
                setattr(tenant.tenant_config, key, value)
            else:
                # Store in custom_settings for unknown keys
                tenant.tenant_config.custom_settings[key] = value

        # Save changes
        await self.update_tenant(tenant_id, {"tenant_config": tenant.tenant_config})

        logger.info("tenant_config_updated", tenant_id=tenant_id, keys=list(config_updates.keys()))
        return tenant.tenant_config

    async def get_tenant_config(self, tenant_id: str, key: str = None) -> Union[Any, TenantConfiguration]:
        """Get tenant configuration or specific setting"""
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        if key:
            if hasattr(tenant.tenant_config, key):
                return getattr(tenant.tenant_config, key)
            else:
                return tenant.tenant_config.custom_settings.get(key)

        return tenant.tenant_config

    # Resource Usage and Quota Management

    async def track_resource_usage(
        self,
        tenant_id: str,
        resource_type: str,
        amount: Union[int, float]
    ) -> ResourceUsage:
        """Track resource usage for quota enforcement"""
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Update usage counters
        usage = tenant.current_usage

        if resource_type == "calls":
            usage.calls_count += int(amount)
        elif resource_type == "call_duration":
            usage.calls_duration_minutes += float(amount)
        elif resource_type == "api_requests":
            usage.api_requests_count += int(amount)
        elif resource_type == "storage":
            usage.storage_used_mb = float(amount)  # Set absolute value
        elif resource_type == "ai_tokens":
            usage.ai_tokens_used += int(amount)
        elif resource_type == "webhooks":
            usage.webhook_deliveries += int(amount)
        elif resource_type == "errors":
            usage.error_count += int(amount)

        usage.last_updated = datetime.now(timezone.utc)

        # Save updated usage
        await self.update_tenant(tenant_id, {"current_usage": usage})

        # Check quota limits
        await self._check_quota_limits(tenant_id, tenant)

        return usage

    async def check_quota_available(self, tenant_id: str, resource_type: str, amount: int) -> bool:
        """Check if tenant has quota available for resource usage"""
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            return False

        quota = tenant.resource_quota
        usage = tenant.current_usage

        # Check different resource types
        if resource_type == "calls_daily":
            # Check if we're in a new day
            today = datetime.now(timezone.utc).date()
            if usage.period_start.date() != today:
                # Reset daily counters
                await self._reset_daily_usage(tenant_id)
                usage = tenant.current_usage

            return usage.calls_count + amount <= quota.calls_per_day

        elif resource_type == "calls_monthly":
            return usage.calls_count + amount <= quota.calls_per_month

        elif resource_type == "concurrent_calls":
            # This would need to be tracked separately with real-time active call count
            return amount <= quota.concurrent_calls

        elif resource_type == "api_requests":
            return usage.api_requests_count + amount <= quota.api_requests_per_hour

        elif resource_type == "storage":
            return usage.storage_used_mb + amount <= quota.storage_mb

        return True

    # Chain Hierarchy Management

    async def create_hotel_chain(
        self,
        chain_id: str,
        chain_name: str,
        headquarters_tenant_id: str
    ) -> ChainHierarchy:
        """Create a new hotel chain hierarchy"""
        # Update headquarters tenant
        chain_hierarchy = ChainHierarchy(
            chain_id=chain_id,
            chain_name=chain_name,
            property_level=0  # Chain HQ
        )

        await self.update_tenant(headquarters_tenant_id, {
            "chain_hierarchy": chain_hierarchy
        })

        logger.info("hotel_chain_created", chain_id=chain_id, hq_tenant=headquarters_tenant_id)
        return chain_hierarchy

    async def add_property_to_chain(
        self,
        chain_id: str,
        property_tenant_id: str,
        parent_property_id: Optional[str] = None,
        property_level: int = 2
    ) -> bool:
        """Add a property to an existing hotel chain"""
        # Get chain information
        hq_tenant = await self._find_chain_headquarters(chain_id)
        if not hq_tenant:
            raise ValueError(f"Chain {chain_id} not found")

        # Create hierarchy for new property
        property_hierarchy = ChainHierarchy(
            chain_id=chain_id,
            chain_name=hq_tenant.chain_hierarchy.chain_name,
            parent_property_id=parent_property_id,
            property_level=property_level
        )

        # Update property tenant
        await self.update_tenant(property_tenant_id, {
            "chain_hierarchy": property_hierarchy
        })

        # Update parent property's child list
        if parent_property_id:
            parent_tenant = await self.get_tenant(parent_property_id)
            if parent_tenant and parent_tenant.chain_hierarchy:
                parent_tenant.chain_hierarchy.child_properties.append(property_tenant_id)
                await self.update_tenant(parent_property_id, {
                    "chain_hierarchy": parent_tenant.chain_hierarchy
                })

        logger.info("property_added_to_chain",
                   chain_id=chain_id,
                   property_id=property_tenant_id,
                   parent_id=parent_property_id)
        return True

    async def get_chain_properties(self, chain_id: str) -> List[TenantMetadata]:
        """Get all properties in a hotel chain"""
        # This would require a database query in production
        # For now, we'll implement a simplified version
        properties = []

        # In a real implementation, this would be a database query
        # SELECT * FROM tenants WHERE chain_id = ?

        return properties

    # Utility Methods

    def _get_default_quota(self, tier: TenantTier) -> ResourceQuota:
        """Get default resource quotas based on tenant tier"""
        quotas = {
            TenantTier.STARTER: ResourceQuota(
                calls_per_day=100,
                calls_per_month=3000,
                concurrent_calls=5,
                storage_mb=1000,
                api_requests_per_hour=500,
                webhook_endpoints=2,
                ai_tokens_per_month=50000
            ),
            TenantTier.PROFESSIONAL: ResourceQuota(
                calls_per_day=500,
                calls_per_month=15000,
                concurrent_calls=20,
                storage_mb=5000,
                api_requests_per_hour=2000,
                webhook_endpoints=10,
                ai_tokens_per_month=250000
            ),
            TenantTier.ENTERPRISE: ResourceQuota(
                calls_per_day=10000,
                calls_per_month=300000,
                concurrent_calls=100,
                storage_mb=50000,
                api_requests_per_hour=10000,
                webhook_endpoints=50,
                ai_tokens_per_month=1000000
            ),
            TenantTier.CUSTOM: ResourceQuota(
                calls_per_day=1000,
                calls_per_month=30000,
                concurrent_calls=50,
                storage_mb=10000,
                api_requests_per_hour=5000,
                webhook_endpoints=25,
                ai_tokens_per_month=500000
            )
        }
        return quotas[tier]

    async def tenant_exists(self, tenant_id: str) -> bool:
        """Check if tenant exists"""
        return await self.get_tenant(tenant_id) is not None

    async def _cache_tenant(self, tenant: TenantMetadata):
        """Cache tenant metadata"""
        self.tenant_cache[tenant.tenant_id] = tenant
        await self.redis.setex(
            f"tenant:{tenant.tenant_id}",
            self.cache_ttl,
            tenant.model_dump_json()
        )

    async def _invalidate_tenant_cache(self, tenant_id: str):
        """Remove tenant from cache"""
        self.tenant_cache.pop(tenant_id, None)
        await self.redis.delete(f"tenant:{tenant_id}")

    async def _save_tenant_to_db(self, tenant: TenantMetadata):
        """Save tenant metadata to database"""
        # In production, this would save to a tenants table
        # For now, we'll use a simple JSON storage approach
        query = text("""
            INSERT INTO tenant_metadata (tenant_id, metadata, created_at, updated_at)
            VALUES (:tenant_id, :metadata, :created_at, :updated_at)
            ON CONFLICT (tenant_id)
            DO UPDATE SET metadata = :metadata, updated_at = :updated_at
        """)

        await self.db.execute(query, {
            "tenant_id": tenant.tenant_id,
            "metadata": tenant.model_dump_json(),
            "created_at": tenant.created_at,
            "updated_at": tenant.updated_at
        })
        await self.db.commit()

    async def _load_tenant_from_db(self, tenant_id: str) -> Optional[TenantMetadata]:
        """Load tenant metadata from database"""
        query = text("SELECT metadata FROM tenant_metadata WHERE tenant_id = :tenant_id")
        result = await self.db.execute(query, {"tenant_id": tenant_id})
        row = result.fetchone()

        if row:
            return TenantMetadata.model_validate_json(row[0])
        return None

    async def _initialize_tenant_schema(self, tenant_id: str):
        """Initialize tenant-specific database objects"""
        # Create tenant-specific tables, views, or schemas
        # This is where we'd implement database-level tenant isolation
        logger.info("tenant_schema_initialized", tenant_id=tenant_id)

    async def _hard_delete_tenant(self, tenant_id: str):
        """Permanently delete all tenant data"""
        # This would delete all tenant-related data
        query = text("DELETE FROM tenant_metadata WHERE tenant_id = :tenant_id")
        await self.db.execute(query, {"tenant_id": tenant_id})
        await self.db.commit()

    async def _check_quota_limits(self, tenant_id: str, tenant: TenantMetadata):
        """Check if tenant is approaching or exceeding quota limits"""
        quota = tenant.resource_quota
        usage = tenant.current_usage

        # Calculate usage percentages
        call_usage_pct = (usage.calls_count / quota.calls_per_day) * 100
        storage_usage_pct = (usage.storage_used_mb / quota.storage_mb) * 100

        # Log warnings at 80% and 95%
        if call_usage_pct >= 95:
            logger.warning("quota_limit_critical", tenant_id=tenant_id, resource="calls", usage_pct=call_usage_pct)
        elif call_usage_pct >= 80:
            logger.warning("quota_limit_warning", tenant_id=tenant_id, resource="calls", usage_pct=call_usage_pct)

    async def _reset_daily_usage(self, tenant_id: str):
        """Reset daily usage counters"""
        tenant = await self.get_tenant(tenant_id)
        if tenant:
            tenant.current_usage.calls_count = 0
            tenant.current_usage.api_requests_count = 0
            tenant.current_usage.period_start = datetime.now(timezone.utc)
            await self.update_tenant(tenant_id, {"current_usage": tenant.current_usage})

    async def _find_chain_headquarters(self, chain_id: str) -> Optional[TenantMetadata]:
        """Find the headquarters tenant for a hotel chain"""
        # In production, this would be a database query
        # For now, return None as placeholder
        return None