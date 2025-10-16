"""
Advanced Upselling Engine for VoiceHive Hotels
Provides intelligent upselling recommendations with revenue optimization and A/B testing.
"""

import asyncio
import json
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.orchestrator.tenant_management import TenantManager
from services.orchestrator.hotel_chain_manager import HotelChainManager
from services.orchestrator.logging_adapter import get_safe_logger

logger = get_safe_logger(__name__)


class UpsellCategory(str, Enum):
    """Categories of upselling opportunities"""
    ROOM_UPGRADE = "room_upgrade"
    AMENITY_PACKAGE = "amenity_package"
    DINING_PACKAGE = "dining_package"
    SPA_SERVICES = "spa_services"
    TRANSPORTATION = "transportation"
    ACTIVITIES = "activities"
    EXTENDED_STAY = "extended_stay"
    EARLY_CHECKIN = "early_checkin"
    LATE_CHECKOUT = "late_checkout"
    SPECIAL_OCCASIONS = "special_occasions"


class UpsellTrigger(str, Enum):
    """Triggers for upselling opportunities"""
    RESERVATION_INQUIRY = "reservation_inquiry"
    BOOKING_CONFIRMATION = "booking_confirmation"
    PRE_ARRIVAL = "pre_arrival"
    CHECK_IN = "check_in"
    DURING_STAY = "during_stay"
    GUEST_REQUEST = "guest_request"
    SPECIAL_EVENT = "special_event"
    WEATHER_BASED = "weather_based"
    INVENTORY_AVAILABILITY = "inventory_availability"


class UpsellStrategy(str, Enum):
    """Upselling strategies"""
    AGGRESSIVE = "aggressive"       # Maximum revenue focus
    BALANCED = "balanced"          # Balance revenue and guest satisfaction
    CONSERVATIVE = "conservative"  # Guest satisfaction focus
    PERSONALIZED = "personalized" # AI-driven personalization
    AB_TEST = "ab_test"           # A/B testing mode


class UpsellOffer(BaseModel):
    """Individual upsell offer"""
    offer_id: str = Field(default_factory=lambda: f"offer_{uuid4().hex[:12]}")
    category: UpsellCategory
    title: str
    description: str

    # Pricing
    original_price: float
    upsell_price: float
    discount_percentage: float = 0.0

    # Offer details
    items_included: List[str] = Field(default_factory=list)
    terms_conditions: List[str] = Field(default_factory=list)
    validity_start: datetime
    validity_end: datetime

    # Inventory
    available_quantity: int = 999
    max_per_guest: int = 1

    # Targeting
    applicable_room_types: List[str] = Field(default_factory=list)
    applicable_guest_segments: List[str] = Field(default_factory=list)
    minimum_stay_nights: int = 1

    # Presentation
    image_url: Optional[str] = None
    priority: int = 100  # Higher priority = shown first
    call_to_action: str = "Upgrade Now"

    # Performance tracking
    times_shown: int = 0
    times_accepted: int = 0
    times_declined: int = 0
    revenue_generated: float = 0.0

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "system"


class UpsellRecommendation(BaseModel):
    """AI-generated upselling recommendation"""
    recommendation_id: str = Field(default_factory=lambda: f"rec_{uuid4().hex[:12]}")
    tenant_id: str
    guest_context: Dict[str, Any]

    # Recommended offers
    primary_offer: UpsellOffer
    alternative_offers: List[UpsellOffer] = Field(default_factory=list)

    # AI reasoning
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    trigger: UpsellTrigger
    strategy: UpsellStrategy

    # Personalization factors
    guest_profile_score: float = 0.0
    historical_preferences: Dict[str, float] = Field(default_factory=dict)
    current_context_factors: Dict[str, float] = Field(default_factory=dict)

    # Revenue optimization
    expected_revenue: float
    probability_of_acceptance: float
    revenue_lift_percentage: float

    # Presentation guidance
    recommended_timing: str  # immediate, after_booking, pre_arrival, etc.
    recommended_channel: str  # voice, email, app, front_desk
    recommended_script: str

    # A/B testing
    test_variant: Optional[str] = None
    control_group: bool = False

    # Tracking
    shown_at: Optional[datetime] = None
    guest_response: Optional[str] = None  # accepted, declined, ignored
    response_time_seconds: Optional[float] = None

    # Audit trail
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=24))


class GuestProfile(BaseModel):
    """Guest profile for personalization"""
    guest_id: str
    tenant_id: str

    # Demographics
    age_range: Optional[str] = None
    travel_purpose: Optional[str] = None  # business, leisure, group, family
    guest_type: str = "individual"  # individual, couple, family, group, corporate

    # Preferences
    room_preferences: List[str] = Field(default_factory=list)
    amenity_preferences: List[str] = Field(default_factory=list)
    dining_preferences: List[str] = Field(default_factory=list)
    budget_tier: str = "standard"  # budget, standard, premium, luxury

    # Behavioral data
    booking_lead_time_days: int = 0
    average_stay_duration: float = 1.0
    preferred_booking_channel: str = "direct"

    # Historical upselling
    total_upsells_accepted: int = 0
    total_upsells_declined: int = 0
    favorite_upsell_categories: List[UpsellCategory] = Field(default_factory=list)
    average_upsell_spend: float = 0.0

    # Loyalty and value
    loyalty_tier: str = "standard"
    lifetime_value: float = 0.0
    stay_frequency_per_year: float = 0.0

    # Special considerations
    special_occasions: List[str] = Field(default_factory=list)  # birthday, anniversary, etc.
    accessibility_needs: List[str] = Field(default_factory=list)
    dietary_restrictions: List[str] = Field(default_factory=list)

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UpsellCampaign(BaseModel):
    """Upselling campaign configuration"""
    campaign_id: str = Field(default_factory=lambda: f"camp_{uuid4().hex[:8]}")
    tenant_id: str
    campaign_name: str

    # Campaign targeting
    target_segments: List[str] = Field(default_factory=list)
    target_room_types: List[str] = Field(default_factory=list)
    target_booking_channels: List[str] = Field(default_factory=list)

    # Campaign offers
    featured_offers: List[str] = Field(default_factory=list)  # offer_ids
    campaign_strategy: UpsellStrategy = UpsellStrategy.BALANCED

    # A/B testing configuration
    ab_test_enabled: bool = False
    test_variants: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    traffic_split_percentage: float = 50.0  # Percentage for test group

    # Campaign schedule
    start_date: datetime
    end_date: datetime
    active_hours: List[int] = Field(default_factory=lambda: list(range(24)))  # Hours of day when active

    # Performance targets
    target_conversion_rate: float = 0.15
    target_revenue_lift: float = 0.20
    minimum_sample_size: int = 100

    # Status
    is_active: bool = True
    auto_optimize: bool = True

    # Results tracking
    total_impressions: int = 0
    total_conversions: int = 0
    total_revenue: float = 0.0

    # Audit trail
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UpsellMetrics(BaseModel):
    """Upselling performance metrics"""
    tenant_id: str
    period_start: datetime
    period_end: datetime

    # Overall performance
    total_opportunities: int = 0
    total_presentations: int = 0
    total_acceptances: int = 0
    total_revenue_generated: float = 0.0

    # Conversion metrics
    presentation_rate: float = 0.0  # opportunities -> presentations
    conversion_rate: float = 0.0    # presentations -> acceptances
    overall_success_rate: float = 0.0  # opportunities -> acceptances

    # Revenue metrics
    average_upsell_value: float = 0.0
    revenue_per_opportunity: float = 0.0
    revenue_lift_percentage: float = 0.0

    # Category performance
    performance_by_category: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    top_performing_offers: List[str] = Field(default_factory=list)

    # Guest segment analysis
    performance_by_segment: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    highest_value_segments: List[str] = Field(default_factory=list)

    # Channel effectiveness
    performance_by_channel: Dict[str, Dict[str, float]] = Field(default_factory=dict)

    # Timing analysis
    best_presentation_times: List[int] = Field(default_factory=list)  # Hours of day

    # A/B testing results
    ab_test_results: Dict[str, Dict[str, float]] = Field(default_factory=dict)


class UpsellEngine:
    """Advanced upselling engine with AI-driven recommendations"""

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        tenant_manager: TenantManager,
        chain_manager: HotelChainManager
    ):
        self.redis = redis_client
        self.db = db_session
        self.tenant_manager = tenant_manager
        self.chain_manager = chain_manager

        # Cache for performance
        self.offers_cache: Dict[str, List[UpsellOffer]] = {}
        self.guest_profiles_cache: Dict[str, GuestProfile] = {}
        self.campaigns_cache: Dict[str, List[UpsellCampaign]] = {}

        # AI model placeholders (would be real ML models in production)
        self.guest_segmentation_model = None
        self.revenue_optimization_model = None
        self.timing_optimization_model = None

    # Core Recommendation Engine

    async def generate_upsell_recommendations(
        self,
        tenant_id: str,
        guest_context: Dict[str, Any],
        trigger: UpsellTrigger,
        strategy: UpsellStrategy = UpsellStrategy.BALANCED,
        max_offers: int = 3
    ) -> UpsellRecommendation:
        """Generate AI-driven upselling recommendations"""

        try:
            # Get guest profile
            guest_profile = await self._get_or_create_guest_profile(
                tenant_id, guest_context
            )

            # Get available offers
            available_offers = await self._get_available_offers(
                tenant_id, guest_context, trigger
            )

            # Score and rank offers
            scored_offers = await self._score_offers(
                available_offers, guest_profile, guest_context, strategy
            )

            if not scored_offers:
                return await self._create_fallback_recommendation(
                    tenant_id, guest_context, trigger, strategy
                )

            # Select primary and alternative offers
            primary_offer = scored_offers[0][0]  # (offer, score) tuple
            alternative_offers = [offer for offer, score in scored_offers[1:max_offers]]

            # Calculate recommendation metrics
            confidence_score = min(scored_offers[0][1], 1.0)
            expected_revenue = await self._calculate_expected_revenue(
                primary_offer, guest_profile
            )
            probability_of_acceptance = await self._calculate_acceptance_probability(
                primary_offer, guest_profile, guest_context
            )

            # Generate reasoning
            reasoning = await self._generate_recommendation_reasoning(
                primary_offer, guest_profile, guest_context, confidence_score
            )

            # Check for A/B testing
            test_variant, control_group = await self._check_ab_testing(
                tenant_id, guest_profile
            )

            # Create recommendation
            recommendation = UpsellRecommendation(
                tenant_id=tenant_id,
                guest_context=guest_context,
                primary_offer=primary_offer,
                alternative_offers=alternative_offers,
                confidence_score=confidence_score,
                reasoning=reasoning,
                trigger=trigger,
                strategy=strategy,
                expected_revenue=expected_revenue,
                probability_of_acceptance=probability_of_acceptance,
                revenue_lift_percentage=await self._calculate_revenue_lift(
                    expected_revenue, guest_context
                ),
                recommended_timing=await self._get_optimal_timing(
                    trigger, guest_profile
                ),
                recommended_channel=await self._get_optimal_channel(
                    guest_profile, guest_context
                ),
                recommended_script=await self._generate_script(
                    primary_offer, guest_profile, guest_context
                ),
                test_variant=test_variant,
                control_group=control_group
            )

            # Cache recommendation
            await self._cache_recommendation(recommendation)

            logger.info("upsell_recommendation_generated",
                       tenant_id=tenant_id,
                       recommendation_id=recommendation.recommendation_id,
                       primary_offer=primary_offer.offer_id,
                       confidence=confidence_score,
                       expected_revenue=expected_revenue)

            return recommendation

        except Exception as e:
            logger.error("upsell_recommendation_error",
                        tenant_id=tenant_id,
                        error=str(e))
            return await self._create_fallback_recommendation(
                tenant_id, guest_context, trigger, strategy
            )

    async def present_upsell_offer(
        self,
        recommendation_id: str,
        presentation_channel: str = "voice"
    ) -> Dict[str, Any]:
        """Present upsell offer to guest and track metrics"""

        # Get recommendation
        recommendation = await self._get_recommendation(recommendation_id)
        if not recommendation:
            raise ValueError(f"Recommendation {recommendation_id} not found")

        # Check if already presented
        if recommendation.shown_at:
            return {
                "status": "already_presented",
                "original_presentation": recommendation.shown_at
            }

        # Mark as shown
        recommendation.shown_at = datetime.now(timezone.utc)
        await self._update_recommendation(recommendation)

        # Track presentation metrics
        await self._track_presentation(recommendation, presentation_channel)

        # Prepare presentation data
        presentation = {
            "recommendation_id": recommendation_id,
            "primary_offer": recommendation.primary_offer.model_dump(),
            "alternative_offers": [offer.model_dump() for offer in recommendation.alternative_offers],
            "recommended_script": recommendation.recommended_script,
            "confidence_score": recommendation.confidence_score,
            "expected_revenue": recommendation.expected_revenue,
            "call_to_action": recommendation.primary_offer.call_to_action,
            "validity_end": recommendation.primary_offer.validity_end.isoformat(),
            "presentation_channel": presentation_channel
        }

        logger.info("upsell_offer_presented",
                   recommendation_id=recommendation_id,
                   tenant_id=recommendation.tenant_id,
                   offer_id=recommendation.primary_offer.offer_id,
                   channel=presentation_channel)

        return {
            "status": "presented",
            "presentation": presentation
        }

    async def record_guest_response(
        self,
        recommendation_id: str,
        response: str,  # accepted, declined, ignored
        response_details: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Record guest response to upsell offer"""

        recommendation = await self._get_recommendation(recommendation_id)
        if not recommendation:
            return False

        # Calculate response time
        if recommendation.shown_at:
            response_time = (datetime.now(timezone.utc) - recommendation.shown_at).total_seconds()
        else:
            response_time = 0

        # Update recommendation
        recommendation.guest_response = response
        recommendation.response_time_seconds = response_time
        await self._update_recommendation(recommendation)

        # Track response metrics
        await self._track_response(recommendation, response, response_details)

        # Update guest profile
        await self._update_guest_profile_from_response(
            recommendation, response, response_details
        )

        # Update offer performance
        await self._update_offer_performance(
            recommendation.primary_offer, response, response_details
        )

        # Trigger follow-up actions if accepted
        if response == "accepted":
            await self._handle_upsell_acceptance(recommendation, response_details)

        logger.info("guest_response_recorded",
                   recommendation_id=recommendation_id,
                   response=response,
                   response_time_seconds=response_time)

        return True

    # Offer Management

    async def create_upsell_offer(
        self,
        tenant_id: str,
        offer_data: Dict[str, Any],
        created_by: str
    ) -> UpsellOffer:
        """Create a new upsell offer"""

        offer = UpsellOffer(**offer_data, created_by=created_by)

        # Validate offer
        await self._validate_offer(tenant_id, offer)

        # Save to database
        await self._save_offer(tenant_id, offer)

        # Clear cache
        self.offers_cache.pop(tenant_id, None)

        logger.info("upsell_offer_created",
                   tenant_id=tenant_id,
                   offer_id=offer.offer_id,
                   category=offer.category.value)

        return offer

    async def update_upsell_offer(
        self,
        tenant_id: str,
        offer_id: str,
        updates: Dict[str, Any]
    ) -> Optional[UpsellOffer]:
        """Update an existing upsell offer"""

        offer = await self._get_offer(tenant_id, offer_id)
        if not offer:
            return None

        # Apply updates
        for key, value in updates.items():
            if hasattr(offer, key):
                setattr(offer, key, value)

        # Save changes
        await self._save_offer(tenant_id, offer)

        # Clear cache
        self.offers_cache.pop(tenant_id, None)

        return offer

    async def get_tenant_offers(
        self,
        tenant_id: str,
        category: Optional[UpsellCategory] = None,
        active_only: bool = True
    ) -> List[UpsellOffer]:
        """Get all offers for a tenant"""

        # Check cache first
        cache_key = f"{tenant_id}_{category or 'all'}_{active_only}"
        if cache_key in self.offers_cache:
            return self.offers_cache[cache_key]

        # Load from database
        offers = await self._load_offers_from_db(tenant_id, category, active_only)

        # Cache results
        self.offers_cache[cache_key] = offers

        return offers

    # Campaign Management

    async def create_upsell_campaign(
        self,
        tenant_id: str,
        campaign_data: Dict[str, Any],
        created_by: str
    ) -> UpsellCampaign:
        """Create a new upselling campaign"""

        campaign = UpsellCampaign(**campaign_data, tenant_id=tenant_id, created_by=created_by)

        # Validate campaign
        await self._validate_campaign(tenant_id, campaign)

        # Save to database
        await self._save_campaign(campaign)

        # Clear cache
        self.campaigns_cache.pop(tenant_id, None)

        logger.info("upsell_campaign_created",
                   tenant_id=tenant_id,
                   campaign_id=campaign.campaign_id,
                   strategy=campaign.campaign_strategy.value)

        return campaign

    async def get_active_campaigns(self, tenant_id: str) -> List[UpsellCampaign]:
        """Get active campaigns for a tenant"""

        # Check cache
        if tenant_id in self.campaigns_cache:
            return self.campaigns_cache[tenant_id]

        # Load from database
        campaigns = await self._load_campaigns_from_db(tenant_id, active_only=True)

        # Cache results
        self.campaigns_cache[tenant_id] = campaigns

        return campaigns

    # Analytics and Optimization

    async def generate_upsell_metrics(
        self,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime
    ) -> UpsellMetrics:
        """Generate comprehensive upselling metrics"""

        metrics = UpsellMetrics(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end
        )

        try:
            # Get raw data from database
            raw_data = await self._get_metrics_data(tenant_id, period_start, period_end)

            # Calculate overall metrics
            if raw_data["opportunities"]:
                metrics.total_opportunities = raw_data["opportunities"]
                metrics.total_presentations = raw_data["presentations"]
                metrics.total_acceptances = raw_data["acceptances"]
                metrics.total_revenue_generated = raw_data["revenue"]

                # Calculate rates
                if metrics.total_opportunities > 0:
                    metrics.presentation_rate = metrics.total_presentations / metrics.total_opportunities
                    metrics.overall_success_rate = metrics.total_acceptances / metrics.total_opportunities

                if metrics.total_presentations > 0:
                    metrics.conversion_rate = metrics.total_acceptances / metrics.total_presentations

                if metrics.total_acceptances > 0:
                    metrics.average_upsell_value = metrics.total_revenue_generated / metrics.total_acceptances

                if metrics.total_opportunities > 0:
                    metrics.revenue_per_opportunity = metrics.total_revenue_generated / metrics.total_opportunities

            # Category analysis
            metrics.performance_by_category = await self._analyze_category_performance(
                tenant_id, period_start, period_end
            )

            # Segment analysis
            metrics.performance_by_segment = await self._analyze_segment_performance(
                tenant_id, period_start, period_end
            )

            # Channel analysis
            metrics.performance_by_channel = await self._analyze_channel_performance(
                tenant_id, period_start, period_end
            )

            # Timing analysis
            metrics.best_presentation_times = await self._analyze_timing_performance(
                tenant_id, period_start, period_end
            )

        except Exception as e:
            logger.error("upsell_metrics_generation_error",
                        tenant_id=tenant_id,
                        error=str(e))

        return metrics

    async def optimize_campaigns(self, tenant_id: str) -> Dict[str, Any]:
        """Optimize active campaigns based on performance data"""

        campaigns = await self.get_active_campaigns(tenant_id)
        optimization_results = []

        for campaign in campaigns:
            if not campaign.auto_optimize:
                continue

            # Get campaign performance
            metrics = await self.generate_upsell_metrics(
                tenant_id,
                campaign.start_date,
                datetime.now(timezone.utc)
            )

            # Determine optimizations
            optimizations = await self._determine_campaign_optimizations(
                campaign, metrics
            )

            if optimizations:
                # Apply optimizations
                for optimization in optimizations:
                    await self._apply_campaign_optimization(campaign, optimization)

                optimization_results.append({
                    "campaign_id": campaign.campaign_id,
                    "optimizations": optimizations
                })

        return {
            "optimized_campaigns": len(optimization_results),
            "results": optimization_results
        }

    # Helper Methods

    async def _get_or_create_guest_profile(
        self,
        tenant_id: str,
        guest_context: Dict[str, Any]
    ) -> GuestProfile:
        """Get existing guest profile or create new one"""

        guest_id = guest_context.get("guest_id", f"guest_{uuid4().hex[:8]}")

        # Check cache
        cache_key = f"{tenant_id}:{guest_id}"
        if cache_key in self.guest_profiles_cache:
            return self.guest_profiles_cache[cache_key]

        # Try to load from database
        profile = await self._load_guest_profile(tenant_id, guest_id)

        if not profile:
            # Create new profile
            profile = GuestProfile(
                guest_id=guest_id,
                tenant_id=tenant_id,
                **self._extract_profile_data_from_context(guest_context)
            )
            await self._save_guest_profile(profile)

        # Cache profile
        self.guest_profiles_cache[cache_key] = profile

        return profile

    async def _get_available_offers(
        self,
        tenant_id: str,
        guest_context: Dict[str, Any],
        trigger: UpsellTrigger
    ) -> List[UpsellOffer]:
        """Get offers available for current context"""

        all_offers = await self.get_tenant_offers(tenant_id, active_only=True)
        available_offers = []

        current_time = datetime.now(timezone.utc)

        for offer in all_offers:
            # Check validity period
            if offer.validity_start <= current_time <= offer.validity_end:
                # Check room type compatibility
                guest_room_type = guest_context.get("room_type", "")
                if (not offer.applicable_room_types or
                    guest_room_type in offer.applicable_room_types):

                    # Check minimum stay
                    stay_nights = guest_context.get("stay_nights", 1)
                    if stay_nights >= offer.minimum_stay_nights:

                        # Check inventory
                        if offer.available_quantity > 0:
                            available_offers.append(offer)

        return available_offers

    async def _score_offers(
        self,
        offers: List[UpsellOffer],
        guest_profile: GuestProfile,
        guest_context: Dict[str, Any],
        strategy: UpsellStrategy
    ) -> List[Tuple[UpsellOffer, float]]:
        """Score and rank offers based on strategy and guest profile"""

        scored_offers = []

        for offer in offers:
            score = 0.0

            # Base score from offer priority
            score += offer.priority / 100.0

            # Historical performance
            if offer.times_shown > 0:
                acceptance_rate = offer.times_accepted / offer.times_shown
                score += acceptance_rate * 0.3

            # Guest preference alignment
            if offer.category in guest_profile.favorite_upsell_categories:
                score += 0.2

            # Price appropriateness
            if guest_profile.budget_tier == "luxury" and offer.upsell_price > 500:
                score += 0.15
            elif guest_profile.budget_tier == "budget" and offer.upsell_price < 100:
                score += 0.15

            # Strategy-specific adjustments
            if strategy == UpsellStrategy.AGGRESSIVE:
                # Favor high-revenue offers
                score += (offer.upsell_price / 1000) * 0.2
            elif strategy == UpsellStrategy.CONSERVATIVE:
                # Favor high-acceptance-rate offers
                if offer.times_shown > 10:
                    acceptance_rate = offer.times_accepted / offer.times_shown
                    score += acceptance_rate * 0.4

            # Add randomness for variety
            score += random.random() * 0.1

            scored_offers.append((offer, score))

        # Sort by score descending
        scored_offers.sort(key=lambda x: x[1], reverse=True)

        return scored_offers

    async def _calculate_expected_revenue(
        self,
        offer: UpsellOffer,
        guest_profile: GuestProfile
    ) -> float:
        """Calculate expected revenue from offer"""

        base_probability = 0.15  # Base 15% acceptance rate

        # Adjust based on guest history
        if guest_profile.total_upsells_accepted > 0:
            guest_acceptance_rate = (
                guest_profile.total_upsells_accepted /
                (guest_profile.total_upsells_accepted + guest_profile.total_upsells_declined)
            )
            base_probability = (base_probability + guest_acceptance_rate) / 2

        # Adjust based on offer performance
        if offer.times_shown > 10:
            offer_acceptance_rate = offer.times_accepted / offer.times_shown
            base_probability = (base_probability + offer_acceptance_rate) / 2

        return offer.upsell_price * base_probability

    async def _calculate_acceptance_probability(
        self,
        offer: UpsellOffer,
        guest_profile: GuestProfile,
        guest_context: Dict[str, Any]
    ) -> float:
        """Calculate probability of guest accepting the offer"""

        # This would use a trained ML model in production
        # For now, using heuristic approach

        base_probability = 0.15

        # Guest factors
        if guest_profile.total_upsells_accepted > guest_profile.total_upsells_declined:
            base_probability += 0.1

        if offer.category in guest_profile.favorite_upsell_categories:
            base_probability += 0.15

        # Offer factors
        if offer.discount_percentage > 0:
            base_probability += min(offer.discount_percentage / 100 * 0.2, 0.2)

        # Context factors
        special_occasion = guest_context.get("special_occasion", False)
        if special_occasion and offer.category == UpsellCategory.SPECIAL_OCCASIONS:
            base_probability += 0.25

        return min(base_probability, 0.8)  # Cap at 80%

    async def _generate_recommendation_reasoning(
        self,
        offer: UpsellOffer,
        guest_profile: GuestProfile,
        guest_context: Dict[str, Any],
        confidence_score: float
    ) -> str:
        """Generate human-readable reasoning for the recommendation"""

        reasons = []

        if offer.category in guest_profile.favorite_upsell_categories:
            reasons.append(f"Guest has shown preference for {offer.category.value} upgrades")

        if guest_profile.budget_tier == "luxury" and offer.upsell_price > 500:
            reasons.append("Guest profile indicates luxury preference")

        if offer.discount_percentage > 0:
            reasons.append(f"Attractive {offer.discount_percentage}% discount available")

        if guest_context.get("special_occasion"):
            reasons.append("Special occasion detected - enhanced experience appropriate")

        if offer.times_shown > 0:
            acceptance_rate = (offer.times_accepted / offer.times_shown) * 100
            if acceptance_rate > 20:
                reasons.append(f"High acceptance rate ({acceptance_rate:.1f}%) for this offer")

        if not reasons:
            reasons.append("Standard upselling opportunity based on guest profile")

        return "; ".join(reasons)

    async def _check_ab_testing(
        self,
        tenant_id: str,
        guest_profile: GuestProfile
    ) -> Tuple[Optional[str], bool]:
        """Check if guest should be included in A/B testing"""

        campaigns = await self.get_active_campaigns(tenant_id)

        for campaign in campaigns:
            if campaign.ab_test_enabled:
                # Simple hash-based assignment
                guest_hash = hash(guest_profile.guest_id) % 100
                if guest_hash < campaign.traffic_split_percentage:
                    # Randomly assign to test variants
                    if campaign.test_variants:
                        variant = random.choice(list(campaign.test_variants.keys()))
                        return variant, False
                    return "test", False
                else:
                    return None, True  # Control group

        return None, False

    async def _create_fallback_recommendation(
        self,
        tenant_id: str,
        guest_context: Dict[str, Any],
        trigger: UpsellTrigger,
        strategy: UpsellStrategy
    ) -> UpsellRecommendation:
        """Create a basic fallback recommendation when no suitable offers exist"""

        # Create a generic room upgrade offer
        fallback_offer = UpsellOffer(
            category=UpsellCategory.ROOM_UPGRADE,
            title="Room Upgrade Available",
            description="Enhance your stay with a complimentary room upgrade",
            original_price=0.0,
            upsell_price=0.0,
            validity_start=datetime.now(timezone.utc),
            validity_end=datetime.now(timezone.utc) + timedelta(hours=2),
            call_to_action="Ask about upgrades"
        )

        return UpsellRecommendation(
            tenant_id=tenant_id,
            guest_context=guest_context,
            primary_offer=fallback_offer,
            confidence_score=0.1,
            reasoning="No specific offers available - generic upgrade opportunity",
            trigger=trigger,
            strategy=strategy,
            expected_revenue=0.0,
            probability_of_acceptance=0.05,
            revenue_lift_percentage=0.0,
            recommended_timing="immediate",
            recommended_channel="voice",
            recommended_script="I'd be happy to check if we have any complimentary upgrades available for your stay."
        )

    # Database Implementation Methods

    async def _save_offer(self, tenant_id: str, offer: UpsellOffer):
        """Save offer to database"""
        try:
            query = text("""
                INSERT INTO upsell_offers (
                    offer_id, tenant_id, category, title, description,
                    original_price, upsell_price, discount_percentage,
                    offer_data, applicable_room_types, applicable_guest_segments,
                    minimum_stay_nights, available_quantity, max_per_guest,
                    validity_start, validity_end, priority, call_to_action,
                    image_url, times_shown, times_accepted, times_declined,
                    revenue_generated, is_active, created_by
                ) VALUES (
                    :offer_id, :tenant_id, :category, :title, :description,
                    :original_price, :upsell_price, :discount_percentage,
                    :offer_data, :applicable_room_types, :applicable_guest_segments,
                    :minimum_stay_nights, :available_quantity, :max_per_guest,
                    :validity_start, :validity_end, :priority, :call_to_action,
                    :image_url, :times_shown, :times_accepted, :times_declined,
                    :revenue_generated, :is_active, :created_by
                )
                ON CONFLICT (offer_id) DO UPDATE SET
                    category = EXCLUDED.category,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    original_price = EXCLUDED.original_price,
                    upsell_price = EXCLUDED.upsell_price,
                    discount_percentage = EXCLUDED.discount_percentage,
                    offer_data = EXCLUDED.offer_data,
                    applicable_room_types = EXCLUDED.applicable_room_types,
                    applicable_guest_segments = EXCLUDED.applicable_guest_segments,
                    minimum_stay_nights = EXCLUDED.minimum_stay_nights,
                    available_quantity = EXCLUDED.available_quantity,
                    max_per_guest = EXCLUDED.max_per_guest,
                    validity_start = EXCLUDED.validity_start,
                    validity_end = EXCLUDED.validity_end,
                    priority = EXCLUDED.priority,
                    call_to_action = EXCLUDED.call_to_action,
                    image_url = EXCLUDED.image_url,
                    times_shown = EXCLUDED.times_shown,
                    times_accepted = EXCLUDED.times_accepted,
                    times_declined = EXCLUDED.times_declined,
                    revenue_generated = EXCLUDED.revenue_generated,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
            """)

            await self.db.execute(query, {
                "offer_id": offer.offer_id,
                "tenant_id": tenant_id,
                "category": offer.category.value,
                "title": offer.title,
                "description": offer.description,
                "original_price": offer.original_price,
                "upsell_price": offer.upsell_price,
                "discount_percentage": offer.discount_percentage,
                "offer_data": offer.model_dump_json(),
                "applicable_room_types": offer.applicable_room_types,
                "applicable_guest_segments": offer.applicable_guest_segments,
                "minimum_stay_nights": offer.minimum_stay_nights,
                "available_quantity": offer.available_quantity,
                "max_per_guest": offer.max_per_guest,
                "validity_start": offer.validity_start,
                "validity_end": offer.validity_end,
                "priority": offer.priority,
                "call_to_action": offer.call_to_action,
                "image_url": offer.image_url,
                "times_shown": offer.times_shown,
                "times_accepted": offer.times_accepted,
                "times_declined": offer.times_declined,
                "revenue_generated": offer.revenue_generated,
                "is_active": True,
                "created_by": offer.created_by
            })
            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error("save_offer_error", tenant_id=tenant_id, offer_id=offer.offer_id, error=str(e))
            raise

    async def _get_offer(self, tenant_id: str, offer_id: str) -> Optional[UpsellOffer]:
        """Get offer from database"""
        try:
            query = text("""
                SELECT offer_data FROM upsell_offers
                WHERE tenant_id = :tenant_id AND offer_id = :offer_id
            """)

            result = await self.db.execute(query, {
                "tenant_id": tenant_id,
                "offer_id": offer_id
            })

            row = result.fetchone()
            if row:
                return UpsellOffer.model_validate_json(row.offer_data)
            return None

        except Exception as e:
            logger.error("get_offer_error", tenant_id=tenant_id, offer_id=offer_id, error=str(e))
            return None

    async def _load_offers_from_db(
        self, tenant_id: str, category: Optional[UpsellCategory], active_only: bool
    ) -> List[UpsellOffer]:
        """Load offers from database"""
        try:
            query_parts = [
                "SELECT offer_data FROM upsell_offers",
                "WHERE tenant_id = :tenant_id"
            ]
            params = {"tenant_id": tenant_id}

            if category:
                query_parts.append("AND category = :category")
                params["category"] = category.value

            if active_only:
                query_parts.append("AND is_active = true")
                query_parts.append("AND validity_start <= NOW()")
                query_parts.append("AND validity_end >= NOW()")

            query_parts.append("ORDER BY priority DESC, created_at DESC")

            query = text(" ".join(query_parts))
            result = await self.db.execute(query, params)

            offers = []
            for row in result.fetchall():
                try:
                    offer = UpsellOffer.model_validate_json(row.offer_data)
                    offers.append(offer)
                except Exception as e:
                    logger.warning("invalid_offer_data", tenant_id=tenant_id, error=str(e))

            return offers

        except Exception as e:
            logger.error("load_offers_error", tenant_id=tenant_id, error=str(e))
            return []

    async def _validate_offer(self, tenant_id: str, offer: UpsellOffer):
        """Validate offer data"""
        # Check tenant exists
        tenant_exists = await self.tenant_manager.get_tenant(tenant_id)
        if not tenant_exists:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Validate pricing
        if offer.upsell_price < 0:
            raise ValueError("Upsell price cannot be negative")

        # Validate validity period
        if offer.validity_start >= offer.validity_end:
            raise ValueError("Validity start must be before validity end")

        # Validate quantities
        if offer.available_quantity < 0 or offer.max_per_guest <= 0:
            raise ValueError("Invalid quantity values")

    async def _save_guest_profile(self, profile: GuestProfile):
        """Save guest profile to database"""
        try:
            query = text("""
                INSERT INTO guest_profiles (
                    guest_id, tenant_id, profile_data, age_range, travel_purpose,
                    guest_type, budget_tier, booking_lead_time_days,
                    average_stay_duration, preferred_booking_channel,
                    total_upsells_accepted, total_upsells_declined,
                    average_upsell_spend, loyalty_tier, lifetime_value,
                    stay_frequency_per_year, room_preferences, amenity_preferences,
                    dining_preferences, favorite_upsell_categories
                ) VALUES (
                    :guest_id, :tenant_id, :profile_data, :age_range, :travel_purpose,
                    :guest_type, :budget_tier, :booking_lead_time_days,
                    :average_stay_duration, :preferred_booking_channel,
                    :total_upsells_accepted, :total_upsells_declined,
                    :average_upsell_spend, :loyalty_tier, :lifetime_value,
                    :stay_frequency_per_year, :room_preferences, :amenity_preferences,
                    :dining_preferences, :favorite_upsell_categories
                )
                ON CONFLICT (guest_id, tenant_id) DO UPDATE SET
                    profile_data = EXCLUDED.profile_data,
                    age_range = EXCLUDED.age_range,
                    travel_purpose = EXCLUDED.travel_purpose,
                    guest_type = EXCLUDED.guest_type,
                    budget_tier = EXCLUDED.budget_tier,
                    booking_lead_time_days = EXCLUDED.booking_lead_time_days,
                    average_stay_duration = EXCLUDED.average_stay_duration,
                    preferred_booking_channel = EXCLUDED.preferred_booking_channel,
                    total_upsells_accepted = EXCLUDED.total_upsells_accepted,
                    total_upsells_declined = EXCLUDED.total_upsells_declined,
                    average_upsell_spend = EXCLUDED.average_upsell_spend,
                    loyalty_tier = EXCLUDED.loyalty_tier,
                    lifetime_value = EXCLUDED.lifetime_value,
                    stay_frequency_per_year = EXCLUDED.stay_frequency_per_year,
                    room_preferences = EXCLUDED.room_preferences,
                    amenity_preferences = EXCLUDED.amenity_preferences,
                    dining_preferences = EXCLUDED.dining_preferences,
                    favorite_upsell_categories = EXCLUDED.favorite_upsell_categories,
                    updated_at = NOW()
            """)

            favorite_categories = [cat.value if isinstance(cat, UpsellCategory) else cat
                                 for cat in profile.favorite_upsell_categories]

            await self.db.execute(query, {
                "guest_id": profile.guest_id,
                "tenant_id": profile.tenant_id,
                "profile_data": profile.model_dump_json(),
                "age_range": profile.age_range,
                "travel_purpose": profile.travel_purpose,
                "guest_type": profile.guest_type,
                "budget_tier": profile.budget_tier,
                "booking_lead_time_days": profile.booking_lead_time_days,
                "average_stay_duration": profile.average_stay_duration,
                "preferred_booking_channel": profile.preferred_booking_channel,
                "total_upsells_accepted": profile.total_upsells_accepted,
                "total_upsells_declined": profile.total_upsells_declined,
                "average_upsell_spend": profile.average_upsell_spend,
                "loyalty_tier": profile.loyalty_tier,
                "lifetime_value": profile.lifetime_value,
                "stay_frequency_per_year": profile.stay_frequency_per_year,
                "room_preferences": profile.room_preferences,
                "amenity_preferences": profile.amenity_preferences,
                "dining_preferences": profile.dining_preferences,
                "favorite_upsell_categories": favorite_categories
            })
            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error("save_guest_profile_error",
                        guest_id=profile.guest_id,
                        tenant_id=profile.tenant_id,
                        error=str(e))
            raise

    async def _load_guest_profile(self, tenant_id: str, guest_id: str) -> Optional[GuestProfile]:
        """Load guest profile from database"""
        try:
            query = text("""
                SELECT profile_data FROM guest_profiles
                WHERE tenant_id = :tenant_id AND guest_id = :guest_id
            """)

            result = await self.db.execute(query, {
                "tenant_id": tenant_id,
                "guest_id": guest_id
            })

            row = result.fetchone()
            if row:
                return GuestProfile.model_validate_json(row.profile_data)
            return None

        except Exception as e:
            logger.error("load_guest_profile_error",
                        tenant_id=tenant_id,
                        guest_id=guest_id,
                        error=str(e))
            return None

    async def _extract_profile_data_from_context(self, guest_context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract guest profile data from context"""
        profile_data = {}

        # Map context fields to profile fields
        field_mapping = {
            "age_range": "age_range",
            "travel_purpose": "travel_purpose",
            "guest_type": "guest_type",
            "budget_tier": "budget_tier",
            "room_preferences": "room_preferences",
            "amenity_preferences": "amenity_preferences",
            "dining_preferences": "dining_preferences",
            "booking_lead_time": "booking_lead_time_days",
            "stay_duration": "average_stay_duration",
            "booking_channel": "preferred_booking_channel",
            "loyalty_tier": "loyalty_tier",
            "lifetime_value": "lifetime_value"
        }

        for context_key, profile_key in field_mapping.items():
            if context_key in guest_context:
                profile_data[profile_key] = guest_context[context_key]

        return profile_data

    async def _cache_recommendation(self, recommendation: UpsellRecommendation):
        """Cache recommendation in Redis"""
        try:
            cache_key = f"upsell_rec:{recommendation.recommendation_id}"
            cache_data = recommendation.model_dump_json()

            # Cache for 24 hours
            await self.redis.setex(
                cache_key,
                86400,  # 24 hours in seconds
                cache_data
            )

        except Exception as e:
            logger.warning("cache_recommendation_error",
                          rec_id=recommendation.recommendation_id,
                          error=str(e))

    async def _get_recommendation(self, recommendation_id: str) -> Optional[UpsellRecommendation]:
        """Get recommendation from cache or database"""
        try:
            # Try cache first
            cache_key = f"upsell_rec:{recommendation_id}"
            cached_data = await self.redis.get(cache_key)

            if cached_data:
                return UpsellRecommendation.model_validate_json(cached_data)

            # Fall back to database
            query = text("""
                SELECT recommendation_data FROM upsell_recommendations
                WHERE recommendation_id = :recommendation_id
            """)

            result = await self.db.execute(query, {
                "recommendation_id": recommendation_id
            })

            row = result.fetchone()
            if row:
                recommendation = UpsellRecommendation.model_validate_json(row.recommendation_data)
                # Cache for future use
                await self._cache_recommendation(recommendation)
                return recommendation

            return None

        except Exception as e:
            logger.error("get_recommendation_error",
                        rec_id=recommendation_id,
                        error=str(e))
            return None

    async def _update_recommendation(self, recommendation: UpsellRecommendation):
        """Update recommendation in database and cache"""
        try:
            # Update database
            query = text("""
                UPDATE upsell_recommendations
                SET recommendation_data = :recommendation_data,
                    shown_at = :shown_at,
                    guest_response = :guest_response,
                    response_time_seconds = :response_time_seconds
                WHERE recommendation_id = :recommendation_id
            """)

            await self.db.execute(query, {
                "recommendation_id": recommendation.recommendation_id,
                "recommendation_data": recommendation.model_dump_json(),
                "shown_at": recommendation.shown_at,
                "guest_response": recommendation.guest_response,
                "response_time_seconds": recommendation.response_time_seconds
            })
            await self.db.commit()

            # Update cache
            await self._cache_recommendation(recommendation)

        except Exception as e:
            await self.db.rollback()
            logger.error("update_recommendation_error",
                        rec_id=recommendation.recommendation_id,
                        error=str(e))
            raise

    async def _track_presentation(self, recommendation: UpsellRecommendation, channel: str):
        """Track presentation metrics"""
        try:
            # Log event
            event_query = text("""
                INSERT INTO upsell_events (
                    tenant_id, recommendation_id, guest_id, event_type,
                    event_data, offer_id, channel
                ) VALUES (
                    :tenant_id, :recommendation_id, :guest_id, 'offer_presented',
                    :event_data, :offer_id, :channel
                )
            """)

            await self.db.execute(event_query, {
                "tenant_id": recommendation.tenant_id,
                "recommendation_id": recommendation.recommendation_id,
                "guest_id": recommendation.guest_context.get("guest_id"),
                "event_data": json.dumps({
                    "confidence_score": recommendation.confidence_score,
                    "expected_revenue": recommendation.expected_revenue,
                    "presentation_channel": channel
                }),
                "offer_id": recommendation.primary_offer.offer_id,
                "channel": channel
            })

            # Update offer presentation count
            offer_query = text("""
                UPDATE upsell_offers
                SET times_shown = times_shown + 1
                WHERE offer_id = :offer_id
            """)

            await self.db.execute(offer_query, {
                "offer_id": recommendation.primary_offer.offer_id
            })

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error("track_presentation_error",
                        rec_id=recommendation.recommendation_id,
                        error=str(e))

    async def _track_response(
        self,
        recommendation: UpsellRecommendation,
        response: str,
        response_details: Optional[Dict[str, Any]]
    ):
        """Track guest response metrics"""
        try:
            # Log response event
            event_query = text("""
                INSERT INTO upsell_events (
                    tenant_id, recommendation_id, guest_id, event_type,
                    event_data, offer_id, revenue_amount
                ) VALUES (
                    :tenant_id, :recommendation_id, :guest_id, 'guest_response',
                    :event_data, :offer_id, :revenue_amount
                )
            """)

            revenue_amount = (recommendation.expected_revenue
                            if response == "accepted" else 0.0)

            await self.db.execute(event_query, {
                "tenant_id": recommendation.tenant_id,
                "recommendation_id": recommendation.recommendation_id,
                "guest_id": recommendation.guest_context.get("guest_id"),
                "event_data": json.dumps({
                    "response": response,
                    "response_time_seconds": recommendation.response_time_seconds,
                    "details": response_details or {}
                }),
                "offer_id": recommendation.primary_offer.offer_id,
                "revenue_amount": revenue_amount
            })

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error("track_response_error",
                        rec_id=recommendation.recommendation_id,
                        error=str(e))

    async def _update_guest_profile_from_response(
        self,
        recommendation: UpsellRecommendation,
        response: str,
        response_details: Optional[Dict[str, Any]]
    ):
        """Update guest profile based on upselling response"""
        guest_id = recommendation.guest_context.get("guest_id")
        if not guest_id:
            return

        try:
            # The database trigger will handle most updates
            # Here we can add category preference learning
            if response == "accepted":
                category = recommendation.primary_offer.category

                # Update favorite categories
                query = text("""
                    UPDATE guest_profiles
                    SET favorite_upsell_categories =
                        CASE
                            WHEN :category = ANY(favorite_upsell_categories)
                            THEN favorite_upsell_categories
                            ELSE array_append(favorite_upsell_categories, :category)
                        END,
                        updated_at = NOW()
                    WHERE guest_id = :guest_id AND tenant_id = :tenant_id
                """)

                await self.db.execute(query, {
                    "guest_id": guest_id,
                    "tenant_id": recommendation.tenant_id,
                    "category": category.value
                })

            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error("update_guest_profile_response_error",
                        guest_id=guest_id,
                        tenant_id=recommendation.tenant_id,
                        error=str(e))

    async def _update_offer_performance(
        self,
        offer: UpsellOffer,
        response: str,
        response_details: Optional[Dict[str, Any]]
    ):
        """Update offer performance metrics"""
        # The database trigger handles this automatically
        # This method can be used for additional custom logic
        pass

    async def _handle_upsell_acceptance(
        self,
        recommendation: UpsellRecommendation,
        response_details: Optional[Dict[str, Any]]
    ):
        """Handle actions when upsell is accepted"""
        try:
            # Log revenue event
            event_query = text("""
                INSERT INTO upsell_events (
                    tenant_id, recommendation_id, guest_id, event_type,
                    event_data, offer_id, revenue_amount
                ) VALUES (
                    :tenant_id, :recommendation_id, :guest_id, 'upsell_completed',
                    :event_data, :offer_id, :revenue_amount
                )
            """)

            await self.db.execute(event_query, {
                "tenant_id": recommendation.tenant_id,
                "recommendation_id": recommendation.recommendation_id,
                "guest_id": recommendation.guest_context.get("guest_id"),
                "event_data": json.dumps({
                    "offer_title": recommendation.primary_offer.title,
                    "revenue": recommendation.expected_revenue,
                    "details": response_details or {}
                }),
                "offer_id": recommendation.primary_offer.offer_id,
                "revenue_amount": recommendation.expected_revenue
            })

            # Update inventory if limited
            if recommendation.primary_offer.available_quantity < 999:
                inventory_query = text("""
                    UPDATE upsell_offers
                    SET available_quantity = GREATEST(available_quantity - 1, 0)
                    WHERE offer_id = :offer_id
                """)

                await self.db.execute(inventory_query, {
                    "offer_id": recommendation.primary_offer.offer_id
                })

            await self.db.commit()

            logger.info("upsell_accepted",
                       rec_id=recommendation.recommendation_id,
                       offer_id=recommendation.primary_offer.offer_id,
                       revenue=recommendation.expected_revenue)

        except Exception as e:
            await self.db.rollback()
            logger.error("handle_acceptance_error",
                        rec_id=recommendation.recommendation_id,
                        error=str(e))

    async def _save_campaign(self, campaign: UpsellCampaign):
        """Save campaign to database"""
        try:
            query = text("""
                INSERT INTO upsell_campaigns (
                    campaign_id, tenant_id, campaign_name, campaign_data,
                    campaign_strategy, target_segments, target_room_types,
                    featured_offers, ab_test_enabled, traffic_split_percentage,
                    start_date, end_date, active_hours, target_conversion_rate,
                    target_revenue_lift, minimum_sample_size, is_active,
                    auto_optimize, created_by
                ) VALUES (
                    :campaign_id, :tenant_id, :campaign_name, :campaign_data,
                    :campaign_strategy, :target_segments, :target_room_types,
                    :featured_offers, :ab_test_enabled, :traffic_split_percentage,
                    :start_date, :end_date, :active_hours, :target_conversion_rate,
                    :target_revenue_lift, :minimum_sample_size, :is_active,
                    :auto_optimize, :created_by
                )
            """)

            await self.db.execute(query, {
                "campaign_id": campaign.campaign_id,
                "tenant_id": campaign.tenant_id,
                "campaign_name": campaign.campaign_name,
                "campaign_data": campaign.model_dump_json(),
                "campaign_strategy": campaign.campaign_strategy.value,
                "target_segments": campaign.target_segments,
                "target_room_types": campaign.target_room_types,
                "featured_offers": campaign.featured_offers,
                "ab_test_enabled": campaign.ab_test_enabled,
                "traffic_split_percentage": campaign.traffic_split_percentage,
                "start_date": campaign.start_date,
                "end_date": campaign.end_date,
                "active_hours": campaign.active_hours,
                "target_conversion_rate": campaign.target_conversion_rate,
                "target_revenue_lift": campaign.target_revenue_lift,
                "minimum_sample_size": campaign.minimum_sample_size,
                "is_active": campaign.is_active,
                "auto_optimize": campaign.auto_optimize,
                "created_by": campaign.created_by
            })
            await self.db.commit()

        except Exception as e:
            await self.db.rollback()
            logger.error("save_campaign_error",
                        campaign_id=campaign.campaign_id,
                        error=str(e))
            raise

    async def _validate_campaign(self, tenant_id: str, campaign: UpsellCampaign):
        """Validate campaign configuration"""
        # Check tenant exists
        tenant_exists = await self.tenant_manager.get_tenant(tenant_id)
        if not tenant_exists:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Validate dates
        if campaign.start_date >= campaign.end_date:
            raise ValueError("Campaign start date must be before end date")

        # Validate targets
        if campaign.target_conversion_rate <= 0 or campaign.target_conversion_rate > 1:
            raise ValueError("Target conversion rate must be between 0 and 1")

    async def _load_campaigns_from_db(self, tenant_id: str, active_only: bool = True) -> List[UpsellCampaign]:
        """Load campaigns from database"""
        try:
            query_parts = [
                "SELECT campaign_data FROM upsell_campaigns",
                "WHERE tenant_id = :tenant_id"
            ]
            params = {"tenant_id": tenant_id}

            if active_only:
                query_parts.append("AND is_active = true")
                query_parts.append("AND start_date <= NOW()")
                query_parts.append("AND end_date >= NOW()")

            query_parts.append("ORDER BY created_at DESC")

            query = text(" ".join(query_parts))
            result = await self.db.execute(query, params)

            campaigns = []
            for row in result.fetchall():
                try:
                    campaign = UpsellCampaign.model_validate_json(row.campaign_data)
                    campaigns.append(campaign)
                except Exception as e:
                    logger.warning("invalid_campaign_data", tenant_id=tenant_id, error=str(e))

            return campaigns

        except Exception as e:
            logger.error("load_campaigns_error", tenant_id=tenant_id, error=str(e))
            return []

    async def _get_metrics_data(
        self,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime
    ) -> Dict[str, Any]:
        """Get raw metrics data from database"""
        try:
            query = text("""
                SELECT
                    COUNT(DISTINCT recommendation_id) as opportunities,
                    COUNT(DISTINCT CASE WHEN shown_at IS NOT NULL THEN recommendation_id END) as presentations,
                    COUNT(DISTINCT CASE WHEN guest_response = 'accepted' THEN recommendation_id END) as acceptances,
                    COALESCE(SUM(CASE WHEN guest_response = 'accepted' THEN expected_revenue ELSE 0 END), 0) as revenue
                FROM upsell_recommendations
                WHERE tenant_id = :tenant_id
                  AND generated_at BETWEEN :period_start AND :period_end
            """)

            result = await self.db.execute(query, {
                "tenant_id": tenant_id,
                "period_start": period_start,
                "period_end": period_end
            })

            row = result.fetchone()
            if row:
                return {
                    "opportunities": row.opportunities or 0,
                    "presentations": row.presentations or 0,
                    "acceptances": row.acceptances or 0,
                    "revenue": float(row.revenue or 0)
                }

            return {"opportunities": 0, "presentations": 0, "acceptances": 0, "revenue": 0.0}

        except Exception as e:
            logger.error("get_metrics_data_error", tenant_id=tenant_id, error=str(e))
            return {"opportunities": 0, "presentations": 0, "acceptances": 0, "revenue": 0.0}

    # Analytics helper methods with placeholder implementations
    async def _analyze_category_performance(self, tenant_id: str, start: datetime, end: datetime) -> Dict[str, Dict[str, float]]:
        return {}

    async def _analyze_segment_performance(self, tenant_id: str, start: datetime, end: datetime) -> Dict[str, Dict[str, float]]:
        return {}

    async def _analyze_channel_performance(self, tenant_id: str, start: datetime, end: datetime) -> Dict[str, Dict[str, float]]:
        return {}

    async def _analyze_timing_performance(self, tenant_id: str, start: datetime, end: datetime) -> List[int]:
        return []

    async def _determine_campaign_optimizations(self, campaign: UpsellCampaign, metrics: UpsellMetrics) -> List[Dict[str, Any]]:
        return []

    async def _apply_campaign_optimization(self, campaign: UpsellCampaign, optimization: Dict[str, Any]):
        pass

    async def _calculate_revenue_lift(self, expected_revenue: float, guest_context: Dict[str, Any]) -> float:
        # Simple heuristic - would use more sophisticated calculation in production
        base_booking_value = guest_context.get("booking_value", 200.0)
        return (expected_revenue / base_booking_value) * 100 if base_booking_value > 0 else 0.0

    async def _get_optimal_timing(self, trigger: UpsellTrigger, guest_profile: GuestProfile) -> str:
        timing_map = {
            UpsellTrigger.RESERVATION_INQUIRY: "immediate",
            UpsellTrigger.BOOKING_CONFIRMATION: "after_booking",
            UpsellTrigger.PRE_ARRIVAL: "pre_arrival",
            UpsellTrigger.CHECK_IN: "at_checkin",
            UpsellTrigger.DURING_STAY: "during_stay"
        }
        return timing_map.get(trigger, "immediate")

    async def _get_optimal_channel(self, guest_profile: GuestProfile, guest_context: Dict[str, Any]) -> str:
        # Use guest's preferred booking channel as proxy for communication preference
        return guest_profile.preferred_booking_channel

    async def _generate_script(self, offer: UpsellOffer, guest_profile: GuestProfile, guest_context: Dict[str, Any]) -> str:
        scripts = {
            UpsellCategory.ROOM_UPGRADE: f"I'd like to offer you a complimentary upgrade to our {offer.title}. This includes {', '.join(offer.items_included[:2])} and more.",
            UpsellCategory.DINING_PACKAGE: f"Would you be interested in our {offer.title}? It's perfect for your stay and includes {', '.join(offer.items_included[:2])}.",
            UpsellCategory.SPA_SERVICES: f"I noticed you might enjoy our {offer.title}. It's a great way to enhance your stay with {', '.join(offer.items_included[:2])}."
        }

        base_script = scripts.get(offer.category, f"I'd like to offer you our {offer.title}.")

        if offer.discount_percentage > 0:
            base_script += f" As a special offer, you'll receive {offer.discount_percentage}% off."

        return base_script