"""
Hotel Chain Management System for VoiceHive Hotels
Provides hierarchical configuration, multi-property operations, and chain-level analytics.
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Union, Set, Tuple
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.orchestrator.tenant_management import TenantManager, TenantMetadata, TenantConfiguration
from services.orchestrator.logging_adapter import get_safe_logger

logger = get_safe_logger(__name__)


class PropertyType(str, Enum):
    """Types of properties in hotel chain hierarchy"""
    CHAIN_HEADQUARTERS = "chain_hq"      # Chain headquarters/corporate
    REGIONAL_OFFICE = "regional_office"  # Regional management office
    FLAGSHIP_HOTEL = "flagship_hotel"    # Premium flagship property
    STANDARD_HOTEL = "standard_hotel"    # Standard hotel property
    EXTENDED_STAY = "extended_stay"      # Extended stay property
    RESORT = "resort"                    # Resort property
    BOUTIQUE = "boutique"               # Boutique hotel
    FRANCHISE = "franchise"             # Franchised property


class PropertyStatus(str, Enum):
    """Status of properties in the chain"""
    ACTIVE = "active"
    UNDER_CONSTRUCTION = "under_construction"
    TEMPORARILY_CLOSED = "temporarily_closed"
    SUSPENDED = "suspended"
    SOLD = "sold"
    PLANNED = "planned"


class ConfigInheritanceType(str, Enum):
    """Types of configuration inheritance"""
    FULL_INHERITANCE = "full"           # Inherit all parent configurations
    SELECTIVE_INHERITANCE = "selective" # Inherit only selected configurations
    NO_INHERITANCE = "none"            # No inheritance, completely independent
    OVERRIDE_INHERITANCE = "override"   # Inherit with local overrides


class ChainOperationType(str, Enum):
    """Types of chain-wide operations"""
    CONFIG_UPDATE = "config_update"
    SOFTWARE_DEPLOYMENT = "software_deployment"
    POLICY_CHANGE = "policy_change"
    RATE_UPDATE = "rate_update"
    PROMOTION_LAUNCH = "promotion_launch"
    MAINTENANCE_WINDOW = "maintenance_window"
    TRAINING_ROLLOUT = "training_rollout"


class PropertyHierarchy(BaseModel):
    """Property hierarchy information"""
    property_id: str = Field(..., description="Unique property identifier (tenant_id)")
    property_name: str
    property_type: PropertyType
    property_status: PropertyStatus = PropertyStatus.ACTIVE

    # Hierarchy structure
    chain_id: str
    parent_property_id: Optional[str] = None
    level: int = Field(..., ge=0, le=5, description="Hierarchy level (0=chain HQ)")

    # Geographic information
    country: str
    region: str
    city: str
    address: Optional[str] = None
    coordinates: Optional[Tuple[float, float]] = None

    # Property details
    room_count: Optional[int] = None
    property_size_sqm: Optional[float] = None
    opening_date: Optional[datetime] = None

    # Management information
    general_manager: Optional[str] = None
    management_company: Optional[str] = None
    franchise_agreement_expires: Optional[datetime] = None

    # Configuration inheritance
    inheritance_type: ConfigInheritanceType = ConfigInheritanceType.SELECTIVE_INHERITANCE
    inherited_configs: List[str] = Field(default_factory=list)
    local_overrides: Dict[str, Any] = Field(default_factory=dict)

    # Operational flags
    accepts_reservations: bool = True
    shared_inventory: bool = False
    cross_property_services: bool = True

    # Audit trail
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChainMetadata(BaseModel):
    """Complete hotel chain metadata"""
    chain_id: str = Field(default_factory=lambda: f"chain_{uuid4().hex[:8]}")
    chain_name: str
    chain_code: str = Field(..., min_length=2, max_length=10, description="Unique chain code")

    # Chain details
    headquarters_property_id: str
    corporate_entity: str
    chain_tier: str = "standard"  # economy, standard, premium, luxury

    # Geographic footprint
    operating_countries: List[str] = Field(default_factory=list)
    primary_market: str
    expansion_markets: List[str] = Field(default_factory=list)

    # Brand portfolio
    brand_names: List[str] = Field(default_factory=list)
    brand_segments: List[str] = Field(default_factory=list)

    # Business model
    management_model: str = "mixed"  # owned, managed, franchised, mixed
    franchise_fee_percentage: Optional[float] = None
    royalty_percentage: Optional[float] = None

    # Financial information
    total_rooms: int = 0
    annual_revenue_usd: Optional[float] = None

    # Technology and services
    central_reservation_system: str = "voicehive"
    loyalty_program_name: Optional[str] = None
    unified_billing: bool = True

    # Chain-wide policies
    chain_policies: Dict[str, Any] = Field(default_factory=dict)
    quality_standards: Dict[str, Any] = Field(default_factory=dict)

    # Contact information
    corporate_contact_email: str
    corporate_phone: Optional[str] = None
    website_url: Optional[str] = None

    # Audit trail
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str


class ChainOperation(BaseModel):
    """Chain-wide operation tracking"""
    operation_id: str = Field(default_factory=lambda: f"op_{uuid4().hex[:12]}")
    chain_id: str
    operation_type: ChainOperationType
    operation_name: str
    description: Optional[str] = None

    # Scope and targeting
    target_properties: List[str] = Field(default_factory=list)  # Empty means all properties
    target_property_types: List[PropertyType] = Field(default_factory=list)
    exclude_properties: List[str] = Field(default_factory=list)

    # Execution details
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None

    # Operation data
    operation_payload: Dict[str, Any] = Field(default_factory=dict)
    rollback_data: Optional[Dict[str, Any]] = None

    # Status tracking
    status: str = "scheduled"  # scheduled, in_progress, completed, failed, cancelled
    progress_percentage: float = 0.0
    error_message: Optional[str] = None

    # Results tracking
    successful_properties: List[str] = Field(default_factory=list)
    failed_properties: List[str] = Field(default_factory=list)
    skipped_properties: List[str] = Field(default_factory=list)

    # Approval and authorization
    requires_approval: bool = True
    approved_by: Optional[str] = None
    approval_date: Optional[datetime] = None

    # Audit trail
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChainAnalytics(BaseModel):
    """Chain-level analytics and KPIs"""
    chain_id: str
    period_start: datetime
    period_end: datetime

    # Property metrics
    total_properties: int = 0
    active_properties: int = 0
    new_properties_added: int = 0
    properties_closed: int = 0

    # Operational metrics
    total_rooms: int = 0
    total_calls_handled: int = 0
    average_call_duration_minutes: float = 0.0
    total_reservations_made: int = 0

    # Financial metrics
    total_revenue_usd: float = 0.0
    revenue_per_property: float = 0.0
    average_daily_rate: float = 0.0
    occupancy_rate_percentage: float = 0.0

    # Service quality metrics
    average_response_time_seconds: float = 0.0
    customer_satisfaction_score: float = 0.0
    ai_accuracy_percentage: float = 0.0

    # Technology adoption
    voice_ai_adoption_rate: float = 0.0
    mobile_app_usage_rate: float = 0.0
    self_service_completion_rate: float = 0.0

    # Regional breakdown
    performance_by_region: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    top_performing_properties: List[str] = Field(default_factory=list)
    underperforming_properties: List[str] = Field(default_factory=list)

    # Benchmarking
    industry_benchmark_comparison: Dict[str, float] = Field(default_factory=dict)

    # Generated at
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HotelChainManager:
    """Comprehensive hotel chain management with hierarchical operations"""

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        tenant_manager: TenantManager
    ):
        self.redis = redis_client
        self.db = db_session
        self.tenant_manager = tenant_manager

        # Caching
        self.chain_cache: Dict[str, ChainMetadata] = {}
        self.property_cache: Dict[str, PropertyHierarchy] = {}
        self.cache_ttl = 1800  # 30 minutes

    # Chain Lifecycle Management

    async def create_hotel_chain(
        self,
        chain_name: str,
        chain_code: str,
        headquarters_tenant_id: str,
        corporate_entity: str,
        created_by: str,
        **kwargs
    ) -> ChainMetadata:
        """Create a new hotel chain"""

        # Validate headquarters property exists
        hq_tenant = await self.tenant_manager.get_tenant(headquarters_tenant_id)
        if not hq_tenant:
            raise ValueError(f"Headquarters tenant {headquarters_tenant_id} not found")

        # Check if chain code is unique
        if await self._chain_code_exists(chain_code):
            raise ValueError(f"Chain code {chain_code} already exists")

        # Create chain metadata
        chain = ChainMetadata(
            chain_name=chain_name,
            chain_code=chain_code,
            headquarters_property_id=headquarters_tenant_id,
            corporate_entity=corporate_entity,
            created_by=created_by,
            **kwargs
        )

        # Save to database
        await self._save_chain_to_db(chain)

        # Create headquarters property hierarchy
        hq_hierarchy = PropertyHierarchy(
            property_id=headquarters_tenant_id,
            property_name=f"{chain_name} Headquarters",
            property_type=PropertyType.CHAIN_HEADQUARTERS,
            chain_id=chain.chain_id,
            level=0,
            country=kwargs.get("country", "Unknown"),
            region=kwargs.get("region", "Corporate"),
            city=kwargs.get("city", "Unknown")
        )

        await self._save_property_hierarchy(hq_hierarchy)

        # Update tenant with chain information
        await self.tenant_manager.update_tenant(headquarters_tenant_id, {
            "chain_hierarchy": {
                "chain_id": chain.chain_id,
                "chain_name": chain_name,
                "property_level": 0
            }
        })

        # Cache the chain
        await self._cache_chain(chain)

        logger.info("hotel_chain_created",
                   chain_id=chain.chain_id,
                   chain_name=chain_name,
                   headquarters=headquarters_tenant_id)

        return chain

    async def add_property_to_chain(
        self,
        chain_id: str,
        property_tenant_id: str,
        property_name: str,
        property_type: PropertyType,
        parent_property_id: Optional[str] = None,
        inheritance_type: ConfigInheritanceType = ConfigInheritanceType.SELECTIVE_INHERITANCE,
        **property_details
    ) -> PropertyHierarchy:
        """Add a property to an existing hotel chain"""

        # Validate chain exists
        chain = await self.get_chain(chain_id)
        if not chain:
            raise ValueError(f"Chain {chain_id} not found")

        # Validate property tenant exists
        property_tenant = await self.tenant_manager.get_tenant(property_tenant_id)
        if not property_tenant:
            raise ValueError(f"Property tenant {property_tenant_id} not found")

        # Validate parent property if specified
        parent_level = 0
        if parent_property_id:
            parent_hierarchy = await self.get_property_hierarchy(parent_property_id)
            if not parent_hierarchy or parent_hierarchy.chain_id != chain_id:
                raise ValueError(f"Invalid parent property {parent_property_id}")
            parent_level = parent_hierarchy.level

        # Create property hierarchy
        property_hierarchy = PropertyHierarchy(
            property_id=property_tenant_id,
            property_name=property_name,
            property_type=property_type,
            chain_id=chain_id,
            parent_property_id=parent_property_id,
            level=parent_level + 1,
            inheritance_type=inheritance_type,
            **property_details
        )

        # Save property hierarchy
        await self._save_property_hierarchy(property_hierarchy)

        # Update tenant with chain information
        await self.tenant_manager.update_tenant(property_tenant_id, {
            "chain_hierarchy": {
                "chain_id": chain_id,
                "chain_name": chain.chain_name,
                "parent_property_id": parent_property_id,
                "property_level": property_hierarchy.level
            }
        })

        # Apply inherited configurations
        if inheritance_type != ConfigInheritanceType.NO_INHERITANCE:
            await self._apply_inherited_configurations(property_hierarchy)

        # Update chain statistics
        await self._update_chain_statistics(chain_id)

        logger.info("property_added_to_chain",
                   chain_id=chain_id,
                   property_id=property_tenant_id,
                   property_type=property_type.value,
                   parent_id=parent_property_id)

        return property_hierarchy

    async def remove_property_from_chain(
        self,
        chain_id: str,
        property_id: str,
        reason: str = "business_decision"
    ) -> bool:
        """Remove a property from a hotel chain"""

        # Get property hierarchy
        property_hierarchy = await self.get_property_hierarchy(property_id)
        if not property_hierarchy or property_hierarchy.chain_id != chain_id:
            raise ValueError(f"Property {property_id} not found in chain {chain_id}")

        # Check if property has children
        children = await self.get_child_properties(property_id)
        if children:
            raise ValueError(f"Cannot remove property {property_id} - it has {len(children)} child properties")

        # Update property status instead of hard delete (for audit trail)
        property_hierarchy.property_status = PropertyStatus.SOLD
        property_hierarchy.updated_at = datetime.now(timezone.utc)

        await self._save_property_hierarchy(property_hierarchy)

        # Update tenant to remove chain information
        await self.tenant_manager.update_tenant(property_id, {
            "chain_hierarchy": None
        })

        # Update chain statistics
        await self._update_chain_statistics(chain_id)

        logger.info("property_removed_from_chain",
                   chain_id=chain_id,
                   property_id=property_id,
                   reason=reason)

        return True

    # Configuration Management

    async def update_chain_configuration(
        self,
        chain_id: str,
        config_updates: Dict[str, Any],
        updated_by: str,
        propagate_to_properties: bool = True,
        target_property_types: Optional[List[PropertyType]] = None
    ) -> bool:
        """Update chain-wide configuration"""

        chain = await self.get_chain(chain_id)
        if not chain:
            raise ValueError(f"Chain {chain_id} not found")

        # Update chain configuration
        for key, value in config_updates.items():
            if key in ["chain_policies", "quality_standards"]:
                if hasattr(chain, key):
                    current_config = getattr(chain, key)
                    if isinstance(current_config, dict):
                        current_config.update(value)
                    else:
                        setattr(chain, key, value)
            else:
                if hasattr(chain, key):
                    setattr(chain, key, value)

        chain.updated_at = datetime.now(timezone.utc)
        await self._save_chain_to_db(chain)

        # Propagate to properties if requested
        if propagate_to_properties:
            operation = ChainOperation(
                chain_id=chain_id,
                operation_type=ChainOperationType.CONFIG_UPDATE,
                operation_name=f"Configuration Update: {', '.join(config_updates.keys())}",
                operation_payload=config_updates,
                scheduled_start=datetime.now(timezone.utc),
                target_property_types=target_property_types or [],
                created_by=updated_by
            )

            await self._execute_chain_operation(operation)

        logger.info("chain_configuration_updated",
                   chain_id=chain_id,
                   updated_keys=list(config_updates.keys()),
                   propagated=propagate_to_properties)

        return True

    async def get_effective_configuration(
        self,
        property_id: str,
        config_section: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get effective configuration for a property (including inheritance)"""

        property_hierarchy = await self.get_property_hierarchy(property_id)
        if not property_hierarchy:
            raise ValueError(f"Property {property_id} not found")

        # Start with property's base configuration
        property_tenant = await self.tenant_manager.get_tenant(property_id)
        if not property_tenant:
            raise ValueError(f"Property tenant {property_id} not found")

        effective_config = property_tenant.tenant_config.model_dump()

        # Apply inherited configurations based on inheritance type
        if property_hierarchy.inheritance_type != ConfigInheritanceType.NO_INHERITANCE:
            inherited_config = await self._get_inherited_configuration(property_hierarchy)

            if property_hierarchy.inheritance_type == ConfigInheritanceType.FULL_INHERITANCE:
                # Full inheritance: chain config overrides local config
                effective_config.update(inherited_config)
            elif property_hierarchy.inheritance_type == ConfigInheritanceType.SELECTIVE_INHERITANCE:
                # Selective inheritance: only specified sections
                for config_key in property_hierarchy.inherited_configs:
                    if config_key in inherited_config:
                        effective_config[config_key] = inherited_config[config_key]
            elif property_hierarchy.inheritance_type == ConfigInheritanceType.OVERRIDE_INHERITANCE:
                # Override inheritance: chain config as base, local overrides
                effective_config = {**inherited_config, **effective_config}

        # Apply local overrides
        if property_hierarchy.local_overrides:
            effective_config.update(property_hierarchy.local_overrides)

        # Return specific section if requested
        if config_section:
            return effective_config.get(config_section, {})

        return effective_config

    # Chain Operations

    async def execute_chain_wide_operation(
        self,
        chain_id: str,
        operation_type: ChainOperationType,
        operation_name: str,
        operation_payload: Dict[str, Any],
        created_by: str,
        target_properties: Optional[List[str]] = None,
        target_property_types: Optional[List[PropertyType]] = None,
        scheduled_start: Optional[datetime] = None
    ) -> ChainOperation:
        """Execute a chain-wide operation"""

        operation = ChainOperation(
            chain_id=chain_id,
            operation_type=operation_type,
            operation_name=operation_name,
            operation_payload=operation_payload,
            target_properties=target_properties or [],
            target_property_types=target_property_types or [],
            scheduled_start=scheduled_start or datetime.now(timezone.utc),
            created_by=created_by
        )

        # Save operation
        await self._save_chain_operation(operation)

        # Execute if scheduled for now
        if not scheduled_start or scheduled_start <= datetime.now(timezone.utc):
            await self._execute_chain_operation(operation)

        return operation

    async def _execute_chain_operation(self, operation: ChainOperation) -> bool:
        """Execute a chain operation across properties"""
        try:
            operation.status = "in_progress"
            operation.actual_start = datetime.now(timezone.utc)
            await self._save_chain_operation(operation)

            # Get target properties
            target_properties = await self._get_operation_targets(operation)
            total_properties = len(target_properties)

            if total_properties == 0:
                operation.status = "completed"
                operation.actual_end = datetime.now(timezone.utc)
                operation.progress_percentage = 100.0
                await self._save_chain_operation(operation)
                return True

            # Execute operation on each property
            for i, property_id in enumerate(target_properties):
                try:
                    success = await self._execute_property_operation(
                        property_id, operation.operation_type, operation.operation_payload
                    )

                    if success:
                        operation.successful_properties.append(property_id)
                    else:
                        operation.failed_properties.append(property_id)

                    # Update progress
                    operation.progress_percentage = ((i + 1) / total_properties) * 100
                    await self._save_chain_operation(operation)

                except Exception as e:
                    logger.error("property_operation_failed",
                               property_id=property_id,
                               error=str(e))
                    operation.failed_properties.append(property_id)

            # Complete operation
            operation.status = "completed" if not operation.failed_properties else "failed"
            operation.actual_end = datetime.now(timezone.utc)
            operation.progress_percentage = 100.0

            if operation.failed_properties:
                operation.error_message = f"Failed on {len(operation.failed_properties)} properties"

            await self._save_chain_operation(operation)

            logger.info("chain_operation_completed",
                       operation_id=operation.operation_id,
                       successful_count=len(operation.successful_properties),
                       failed_count=len(operation.failed_properties))

            return len(operation.failed_properties) == 0

        except Exception as e:
            operation.status = "failed"
            operation.error_message = str(e)
            operation.actual_end = datetime.now(timezone.utc)
            await self._save_chain_operation(operation)
            logger.error("chain_operation_failed", operation_id=operation.operation_id, error=str(e))
            return False

    # Analytics and Reporting

    async def generate_chain_analytics(
        self,
        chain_id: str,
        period_start: datetime,
        period_end: datetime
    ) -> ChainAnalytics:
        """Generate comprehensive chain analytics"""

        analytics = ChainAnalytics(
            chain_id=chain_id,
            period_start=period_start,
            period_end=period_end
        )

        try:
            # Get all properties in chain
            properties = await self.get_chain_properties(chain_id)
            analytics.total_properties = len(properties)
            analytics.active_properties = len([p for p in properties if p.property_status == PropertyStatus.ACTIVE])

            # Aggregate property metrics
            for property_hierarchy in properties:
                if property_hierarchy.property_status != PropertyStatus.ACTIVE:
                    continue

                property_tenant = await self.tenant_manager.get_tenant(property_hierarchy.property_id)
                if not property_tenant:
                    continue

                # Add room count
                if property_hierarchy.room_count:
                    analytics.total_rooms += property_hierarchy.room_count

                # Get usage metrics
                usage = property_tenant.current_usage
                analytics.total_calls_handled += usage.calls_count

                # Calculate regional metrics
                region = property_hierarchy.region
                if region not in analytics.performance_by_region:
                    analytics.performance_by_region[region] = {
                        "properties": 0,
                        "calls": 0,
                        "revenue": 0.0
                    }

                analytics.performance_by_region[region]["properties"] += 1
                analytics.performance_by_region[region]["calls"] += usage.calls_count

            # Calculate averages
            if analytics.active_properties > 0:
                analytics.revenue_per_property = analytics.total_revenue_usd / analytics.active_properties

            if analytics.total_calls_handled > 0:
                # This would be calculated from actual call data in production
                analytics.average_call_duration_minutes = 5.5  # Placeholder

            # Calculate performance rankings
            property_scores = []
            for property_hierarchy in properties:
                if property_hierarchy.property_status == PropertyStatus.ACTIVE:
                    property_tenant = await self.tenant_manager.get_tenant(property_hierarchy.property_id)
                    if property_tenant:
                        # Simple scoring based on call volume (would be more sophisticated in production)
                        score = property_tenant.current_usage.calls_count
                        property_scores.append((property_hierarchy.property_id, score))

            # Sort by performance
            property_scores.sort(key=lambda x: x[1], reverse=True)

            analytics.top_performing_properties = [p[0] for p in property_scores[:5]]
            analytics.underperforming_properties = [p[0] for p in property_scores[-5:] if p[1] < (sum(s[1] for s in property_scores) / len(property_scores) * 0.5)]

        except Exception as e:
            logger.error("chain_analytics_error", chain_id=chain_id, error=str(e))

        return analytics

    # Query Methods

    async def get_chain(self, chain_id: str) -> Optional[ChainMetadata]:
        """Get chain metadata"""
        # Check cache first
        if chain_id in self.chain_cache:
            return self.chain_cache[chain_id]

        # Load from database
        chain = await self._load_chain_from_db(chain_id)
        if chain:
            await self._cache_chain(chain)

        return chain

    async def get_property_hierarchy(self, property_id: str) -> Optional[PropertyHierarchy]:
        """Get property hierarchy information"""
        # Check cache first
        if property_id in self.property_cache:
            return self.property_cache[property_id]

        # Load from database
        hierarchy = await self._load_property_hierarchy_from_db(property_id)
        if hierarchy:
            self.property_cache[property_id] = hierarchy

        return hierarchy

    async def get_chain_properties(
        self,
        chain_id: str,
        property_type: Optional[PropertyType] = None,
        status: Optional[PropertyStatus] = None
    ) -> List[PropertyHierarchy]:
        """Get all properties in a chain"""
        query = """
            SELECT property_data FROM chain_property_hierarchies
            WHERE chain_id = :chain_id
        """
        params = {"chain_id": chain_id}

        if property_type:
            query += " AND property_data->>'property_type' = :property_type"
            params["property_type"] = property_type.value

        if status:
            query += " AND property_data->>'property_status' = :property_status"
            params["property_status"] = status.value

        try:
            result = await self.db.execute(text(query), params)
            properties = []

            for row in result.fetchall():
                property_data = json.loads(row[0])
                properties.append(PropertyHierarchy(**property_data))

            return properties

        except Exception as e:
            logger.error("get_chain_properties_error", chain_id=chain_id, error=str(e))
            return []

    async def get_child_properties(self, parent_property_id: str) -> List[PropertyHierarchy]:
        """Get direct child properties"""
        query = """
            SELECT property_data FROM chain_property_hierarchies
            WHERE property_data->>'parent_property_id' = :parent_id
        """

        try:
            result = await self.db.execute(text(query), {"parent_id": parent_property_id})
            children = []

            for row in result.fetchall():
                property_data = json.loads(row[0])
                children.append(PropertyHierarchy(**property_data))

            return children

        except Exception as e:
            logger.error("get_child_properties_error", parent_id=parent_property_id, error=str(e))
            return []

    # Utility Methods

    async def _chain_code_exists(self, chain_code: str) -> bool:
        """Check if chain code already exists"""
        query = text("SELECT COUNT(*) FROM hotel_chains WHERE chain_code = :chain_code")
        result = await self.db.execute(query, {"chain_code": chain_code})
        count = result.scalar()
        return count > 0

    async def _save_chain_to_db(self, chain: ChainMetadata):
        """Save chain metadata to database"""
        query = text("""
            INSERT INTO hotel_chains (
                chain_id, chain_name, chain_code, headquarters_tenant_id,
                corporate_entity, chain_data, created_at, updated_at
            ) VALUES (
                :chain_id, :chain_name, :chain_code, :headquarters_tenant_id,
                :corporate_entity, :chain_data, :created_at, :updated_at
            )
            ON CONFLICT (chain_id)
            DO UPDATE SET
                chain_name = :chain_name,
                chain_code = :chain_code,
                chain_data = :chain_data,
                updated_at = :updated_at
        """)

        await self.db.execute(query, {
            "chain_id": chain.chain_id,
            "chain_name": chain.chain_name,
            "chain_code": chain.chain_code,
            "headquarters_tenant_id": chain.headquarters_property_id,
            "corporate_entity": chain.corporate_entity,
            "chain_data": chain.model_dump_json(),
            "created_at": chain.created_at,
            "updated_at": chain.updated_at
        })
        await self.db.commit()

    async def _load_chain_from_db(self, chain_id: str) -> Optional[ChainMetadata]:
        """Load chain metadata from database"""
        query = text("SELECT chain_data FROM hotel_chains WHERE chain_id = :chain_id")
        result = await self.db.execute(query, {"chain_id": chain_id})
        row = result.fetchone()

        if row:
            return ChainMetadata.model_validate_json(row[0])
        return None

    async def _save_property_hierarchy(self, hierarchy: PropertyHierarchy):
        """Save property hierarchy to database"""
        query = text("""
            INSERT INTO chain_property_hierarchies (
                property_id, chain_id, property_data, created_at, updated_at
            ) VALUES (
                :property_id, :chain_id, :property_data, :created_at, :updated_at
            )
            ON CONFLICT (property_id)
            DO UPDATE SET
                chain_id = :chain_id,
                property_data = :property_data,
                updated_at = :updated_at
        """)

        await self.db.execute(query, {
            "property_id": hierarchy.property_id,
            "chain_id": hierarchy.chain_id,
            "property_data": hierarchy.model_dump_json(),
            "created_at": hierarchy.created_at,
            "updated_at": hierarchy.updated_at
        })
        await self.db.commit()

    async def _load_property_hierarchy_from_db(self, property_id: str) -> Optional[PropertyHierarchy]:
        """Load property hierarchy from database"""
        query = text("SELECT property_data FROM chain_property_hierarchies WHERE property_id = :property_id")
        result = await self.db.execute(query, {"property_id": property_id})
        row = result.fetchone()

        if row:
            return PropertyHierarchy.model_validate_json(row[0])
        return None

    async def _save_chain_operation(self, operation: ChainOperation):
        """Save chain operation to database"""
        query = text("""
            INSERT INTO chain_operations (
                operation_id, chain_id, operation_data, created_at, updated_at
            ) VALUES (
                :operation_id, :chain_id, :operation_data, :created_at, :updated_at
            )
            ON CONFLICT (operation_id)
            DO UPDATE SET
                operation_data = :operation_data,
                updated_at = :updated_at
        """)

        await self.db.execute(query, {
            "operation_id": operation.operation_id,
            "chain_id": operation.chain_id,
            "operation_data": operation.model_dump_json(),
            "created_at": operation.created_at,
            "updated_at": operation.updated_at
        })
        await self.db.commit()

    async def _get_operation_targets(self, operation: ChainOperation) -> List[str]:
        """Get list of properties targeted by an operation"""
        if operation.target_properties:
            return operation.target_properties

        # Get all properties in chain
        properties = await self.get_chain_properties(operation.chain_id)

        # Filter by property type if specified
        if operation.target_property_types:
            properties = [p for p in properties if p.property_type in operation.target_property_types]

        # Exclude specified properties
        target_ids = [p.property_id for p in properties if p.property_id not in operation.exclude_properties]

        return target_ids

    async def _execute_property_operation(
        self,
        property_id: str,
        operation_type: ChainOperationType,
        payload: Dict[str, Any]
    ) -> bool:
        """Execute operation on a specific property"""
        try:
            if operation_type == ChainOperationType.CONFIG_UPDATE:
                # Update property configuration
                await self.tenant_manager.update_tenant_config(property_id, payload)
                return True

            # Add more operation types as needed
            logger.warning("unsupported_operation_type",
                         property_id=property_id,
                         operation_type=operation_type.value)
            return False

        except Exception as e:
            logger.error("property_operation_error",
                       property_id=property_id,
                       operation_type=operation_type.value,
                       error=str(e))
            return False

    async def _apply_inherited_configurations(self, property_hierarchy: PropertyHierarchy):
        """Apply inherited configurations to a property"""
        if property_hierarchy.inheritance_type == ConfigInheritanceType.NO_INHERITANCE:
            return

        inherited_config = await self._get_inherited_configuration(property_hierarchy)

        if property_hierarchy.inheritance_type == ConfigInheritanceType.FULL_INHERITANCE:
            # Apply all inherited configurations
            await self.tenant_manager.update_tenant_config(
                property_hierarchy.property_id,
                inherited_config
            )
        elif property_hierarchy.inheritance_type == ConfigInheritanceType.SELECTIVE_INHERITANCE:
            # Apply only selected configurations
            selected_config = {
                key: inherited_config[key]
                for key in property_hierarchy.inherited_configs
                if key in inherited_config
            }
            await self.tenant_manager.update_tenant_config(
                property_hierarchy.property_id,
                selected_config
            )

    async def _get_inherited_configuration(self, property_hierarchy: PropertyHierarchy) -> Dict[str, Any]:
        """Get configuration that should be inherited from parent/chain"""
        inherited_config = {}

        # Get chain-level configuration
        chain = await self.get_chain(property_hierarchy.chain_id)
        if chain:
            inherited_config.update(chain.chain_policies)

        # Get parent property configuration if applicable
        if property_hierarchy.parent_property_id:
            parent_config = await self.get_effective_configuration(property_hierarchy.parent_property_id)
            inherited_config.update(parent_config)

        return inherited_config

    async def _update_chain_statistics(self, chain_id: str):
        """Update chain-level statistics"""
        try:
            chain = await self.get_chain(chain_id)
            if not chain:
                return

            # Get current properties
            properties = await self.get_chain_properties(chain_id, status=PropertyStatus.ACTIVE)

            # Update total rooms
            total_rooms = sum(p.room_count or 0 for p in properties)
            chain.total_rooms = total_rooms

            chain.updated_at = datetime.now(timezone.utc)
            await self._save_chain_to_db(chain)

        except Exception as e:
            logger.error("chain_statistics_update_error", chain_id=chain_id, error=str(e))

    async def _cache_chain(self, chain: ChainMetadata):
        """Cache chain metadata"""
        self.chain_cache[chain.chain_id] = chain

        # Schedule cache cleanup
        asyncio.create_task(self._cleanup_chain_cache(chain.chain_id))