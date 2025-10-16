-- Upselling Engine Database Schema for VoiceHive Hotels
-- Supports intelligent upselling with AI recommendations, A/B testing, and revenue optimization

-- Upsell offers table
CREATE TABLE IF NOT EXISTS upsell_offers (
    offer_id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,

    -- Offer details
    category VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,

    -- Pricing
    original_price NUMERIC(10,2) NOT NULL DEFAULT 0.0,
    upsell_price NUMERIC(10,2) NOT NULL,
    discount_percentage NUMERIC(5,2) DEFAULT 0.0,

    -- Offer configuration (full UpsellOffer JSON)
    offer_data JSONB NOT NULL,

    -- Quick access fields for querying
    applicable_room_types TEXT[] DEFAULT '{}',
    applicable_guest_segments TEXT[] DEFAULT '{}',
    minimum_stay_nights INTEGER DEFAULT 1,

    -- Availability
    available_quantity INTEGER DEFAULT 999,
    max_per_guest INTEGER DEFAULT 1,

    -- Validity period
    validity_start TIMESTAMP WITH TIME ZONE NOT NULL,
    validity_end TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Display settings
    priority INTEGER DEFAULT 100,
    call_to_action VARCHAR(255) DEFAULT 'Upgrade Now',
    image_url TEXT,

    -- Performance tracking
    times_shown INTEGER DEFAULT 0,
    times_accepted INTEGER DEFAULT 0,
    times_declined INTEGER DEFAULT 0,
    revenue_generated NUMERIC(12,2) DEFAULT 0.0,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,

    -- Audit trail
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_upsell_offer_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_offer_category CHECK (category IN ('room_upgrade', 'amenity_package', 'dining_package', 'spa_services', 'transportation', 'activities', 'extended_stay', 'early_checkin', 'late_checkout', 'special_occasions')),
    CONSTRAINT valid_pricing CHECK (upsell_price >= 0 AND original_price >= 0),
    CONSTRAINT valid_discount CHECK (discount_percentage >= 0 AND discount_percentage <= 100),
    CONSTRAINT valid_validity_period CHECK (validity_start < validity_end),
    CONSTRAINT valid_quantities CHECK (available_quantity >= 0 AND max_per_guest > 0),
    CONSTRAINT valid_performance_metrics CHECK (
        times_shown >= 0 AND
        times_accepted >= 0 AND
        times_declined >= 0 AND
        times_accepted <= times_shown AND
        times_declined <= times_shown AND
        revenue_generated >= 0
    )
);

-- Indexes for upsell offers
CREATE INDEX IF NOT EXISTS idx_upsell_offers_tenant ON upsell_offers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_upsell_offers_category ON upsell_offers(category);
CREATE INDEX IF NOT EXISTS idx_upsell_offers_active ON upsell_offers(is_active);
CREATE INDEX IF NOT EXISTS idx_upsell_offers_validity ON upsell_offers(validity_start, validity_end);
CREATE INDEX IF NOT EXISTS idx_upsell_offers_price ON upsell_offers(upsell_price);
CREATE INDEX IF NOT EXISTS idx_upsell_offers_performance ON upsell_offers(times_shown DESC, times_accepted DESC);
CREATE INDEX IF NOT EXISTS idx_upsell_offers_room_types ON upsell_offers USING GIN (applicable_room_types);
CREATE INDEX IF NOT EXISTS idx_upsell_offers_data_gin ON upsell_offers USING GIN (offer_data);

-- Guest profiles table for personalization
CREATE TABLE IF NOT EXISTS guest_profiles (
    guest_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,

    -- Profile data (full GuestProfile JSON)
    profile_data JSONB NOT NULL,

    -- Quick access fields for querying
    age_range VARCHAR(20),
    travel_purpose VARCHAR(50),
    guest_type VARCHAR(20) DEFAULT 'individual',
    budget_tier VARCHAR(20) DEFAULT 'standard',

    -- Behavioral metrics
    booking_lead_time_days INTEGER DEFAULT 0,
    average_stay_duration NUMERIC(4,1) DEFAULT 1.0,
    preferred_booking_channel VARCHAR(50) DEFAULT 'direct',

    -- Upselling history
    total_upsells_accepted INTEGER DEFAULT 0,
    total_upsells_declined INTEGER DEFAULT 0,
    average_upsell_spend NUMERIC(8,2) DEFAULT 0.0,

    -- Value metrics
    loyalty_tier VARCHAR(20) DEFAULT 'standard',
    lifetime_value NUMERIC(10,2) DEFAULT 0.0,
    stay_frequency_per_year NUMERIC(4,2) DEFAULT 0.0,

    -- Preferences (arrays for indexing)
    room_preferences TEXT[] DEFAULT '{}',
    amenity_preferences TEXT[] DEFAULT '{}',
    dining_preferences TEXT[] DEFAULT '{}',
    favorite_upsell_categories TEXT[] DEFAULT '{}',

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Primary key
    PRIMARY KEY (guest_id, tenant_id),

    -- Foreign key constraints
    CONSTRAINT fk_guest_profile_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_guest_type CHECK (guest_type IN ('individual', 'couple', 'family', 'group', 'corporate')),
    CONSTRAINT valid_budget_tier CHECK (budget_tier IN ('budget', 'standard', 'premium', 'luxury')),
    CONSTRAINT valid_loyalty_tier CHECK (loyalty_tier IN ('standard', 'silver', 'gold', 'platinum', 'diamond')),
    CONSTRAINT valid_behavioral_metrics CHECK (
        booking_lead_time_days >= 0 AND
        average_stay_duration > 0 AND
        total_upsells_accepted >= 0 AND
        total_upsells_declined >= 0 AND
        lifetime_value >= 0 AND
        stay_frequency_per_year >= 0
    )
);

-- Indexes for guest profiles
CREATE INDEX IF NOT EXISTS idx_guest_profiles_tenant ON guest_profiles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_guest_profiles_guest_id ON guest_profiles(guest_id);
CREATE INDEX IF NOT EXISTS idx_guest_profiles_budget_tier ON guest_profiles(budget_tier);
CREATE INDEX IF NOT EXISTS idx_guest_profiles_loyalty_tier ON guest_profiles(loyalty_tier);
CREATE INDEX IF NOT EXISTS idx_guest_profiles_lifetime_value ON guest_profiles(lifetime_value DESC);
CREATE INDEX IF NOT EXISTS idx_guest_profiles_preferences ON guest_profiles USING GIN (room_preferences, amenity_preferences, dining_preferences);
CREATE INDEX IF NOT EXISTS idx_guest_profiles_upsell_cats ON guest_profiles USING GIN (favorite_upsell_categories);
CREATE INDEX IF NOT EXISTS idx_guest_profiles_data_gin ON guest_profiles USING GIN (profile_data);

-- Upsell recommendations table
CREATE TABLE IF NOT EXISTS upsell_recommendations (
    recommendation_id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    guest_id VARCHAR(100),

    -- Recommendation data (full UpsellRecommendation JSON)
    recommendation_data JSONB NOT NULL,

    -- Quick access fields
    primary_offer_id VARCHAR(36) NOT NULL,
    confidence_score NUMERIC(3,2) NOT NULL,
    expected_revenue NUMERIC(8,2) NOT NULL,
    probability_of_acceptance NUMERIC(3,2) NOT NULL,

    -- Trigger and strategy
    trigger_type VARCHAR(50) NOT NULL,
    strategy_type VARCHAR(20) NOT NULL,

    -- Presentation tracking
    shown_at TIMESTAMP WITH TIME ZONE,
    presentation_channel VARCHAR(50),

    -- Response tracking
    guest_response VARCHAR(20), -- accepted, declined, ignored
    response_time_seconds NUMERIC(8,2),

    -- A/B testing
    test_variant VARCHAR(50),
    control_group BOOLEAN DEFAULT FALSE,

    -- Lifecycle
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    -- Foreign key constraints
    CONSTRAINT fk_upsell_rec_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_upsell_rec_offer FOREIGN KEY (primary_offer_id) REFERENCES upsell_offers(offer_id) ON DELETE CASCADE,
    CONSTRAINT fk_upsell_rec_guest FOREIGN KEY (guest_id, tenant_id) REFERENCES guest_profiles(guest_id, tenant_id) ON DELETE SET NULL,

    -- Constraints
    CONSTRAINT valid_trigger_type CHECK (trigger_type IN ('reservation_inquiry', 'booking_confirmation', 'pre_arrival', 'check_in', 'during_stay', 'guest_request', 'special_event', 'weather_based', 'inventory_availability')),
    CONSTRAINT valid_strategy_type CHECK (strategy_type IN ('aggressive', 'balanced', 'conservative', 'personalized', 'ab_test')),
    CONSTRAINT valid_guest_response CHECK (guest_response IN ('accepted', 'declined', 'ignored') OR guest_response IS NULL),
    CONSTRAINT valid_scores CHECK (
        confidence_score >= 0 AND confidence_score <= 1 AND
        probability_of_acceptance >= 0 AND probability_of_acceptance <= 1 AND
        expected_revenue >= 0
    ),
    CONSTRAINT valid_lifecycle CHECK (generated_at < expires_at)
);

-- Indexes for upsell recommendations
CREATE INDEX IF NOT EXISTS idx_upsell_rec_tenant ON upsell_recommendations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_guest ON upsell_recommendations(guest_id, tenant_id);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_offer ON upsell_recommendations(primary_offer_id);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_trigger ON upsell_recommendations(trigger_type);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_strategy ON upsell_recommendations(strategy_type);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_shown ON upsell_recommendations(shown_at);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_response ON upsell_recommendations(guest_response);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_confidence ON upsell_recommendations(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_revenue ON upsell_recommendations(expected_revenue DESC);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_ab_test ON upsell_recommendations(test_variant, control_group);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_expires ON upsell_recommendations(expires_at);
CREATE INDEX IF NOT EXISTS idx_upsell_rec_data_gin ON upsell_recommendations USING GIN (recommendation_data);

-- Upselling campaigns table
CREATE TABLE IF NOT EXISTS upsell_campaigns (
    campaign_id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    campaign_name VARCHAR(255) NOT NULL,

    -- Campaign data (full UpsellCampaign JSON)
    campaign_data JSONB NOT NULL,

    -- Quick access fields
    campaign_strategy VARCHAR(20) NOT NULL DEFAULT 'balanced',
    target_segments TEXT[] DEFAULT '{}',
    target_room_types TEXT[] DEFAULT '{}',
    featured_offers TEXT[] DEFAULT '{}',

    -- A/B testing configuration
    ab_test_enabled BOOLEAN DEFAULT FALSE,
    traffic_split_percentage NUMERIC(5,2) DEFAULT 50.0,

    -- Campaign schedule
    start_date TIMESTAMP WITH TIME ZONE NOT NULL,
    end_date TIMESTAMP WITH TIME ZONE NOT NULL,
    active_hours INTEGER[] DEFAULT ARRAY[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23],

    -- Performance targets
    target_conversion_rate NUMERIC(5,4) DEFAULT 0.15,
    target_revenue_lift NUMERIC(5,4) DEFAULT 0.20,
    minimum_sample_size INTEGER DEFAULT 100,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    auto_optimize BOOLEAN DEFAULT TRUE,

    -- Performance tracking
    total_impressions INTEGER DEFAULT 0,
    total_conversions INTEGER DEFAULT 0,
    total_revenue NUMERIC(12,2) DEFAULT 0.0,

    -- Audit trail
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_upsell_campaign_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_campaign_strategy CHECK (campaign_strategy IN ('aggressive', 'balanced', 'conservative', 'personalized', 'ab_test')),
    CONSTRAINT valid_campaign_schedule CHECK (start_date < end_date),
    CONSTRAINT valid_performance_targets CHECK (
        target_conversion_rate > 0 AND target_conversion_rate <= 1 AND
        target_revenue_lift >= 0 AND
        minimum_sample_size > 0
    ),
    CONSTRAINT valid_traffic_split CHECK (traffic_split_percentage >= 0 AND traffic_split_percentage <= 100),
    CONSTRAINT valid_performance_tracking CHECK (
        total_impressions >= 0 AND
        total_conversions >= 0 AND
        total_conversions <= total_impressions AND
        total_revenue >= 0
    )
);

-- Indexes for upsell campaigns
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_tenant ON upsell_campaigns(tenant_id);
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_active ON upsell_campaigns(is_active);
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_schedule ON upsell_campaigns(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_strategy ON upsell_campaigns(campaign_strategy);
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_ab_test ON upsell_campaigns(ab_test_enabled);
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_performance ON upsell_campaigns(total_conversions DESC, total_revenue DESC);
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_segments ON upsell_campaigns USING GIN (target_segments);
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_offers ON upsell_campaigns USING GIN (featured_offers);
CREATE INDEX IF NOT EXISTS idx_upsell_campaigns_data_gin ON upsell_campaigns USING GIN (campaign_data);

-- Upselling metrics aggregation table
CREATE TABLE IF NOT EXISTS upsell_metrics_daily (
    metrics_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id VARCHAR(100) NOT NULL,
    metrics_date DATE NOT NULL,

    -- Overall performance
    total_opportunities INTEGER DEFAULT 0,
    total_presentations INTEGER DEFAULT 0,
    total_acceptances INTEGER DEFAULT 0,
    total_revenue NUMERIC(12,2) DEFAULT 0.0,

    -- Calculated rates
    presentation_rate NUMERIC(5,4) DEFAULT 0.0,
    conversion_rate NUMERIC(5,4) DEFAULT 0.0,
    overall_success_rate NUMERIC(5,4) DEFAULT 0.0,
    average_upsell_value NUMERIC(8,2) DEFAULT 0.0,

    -- Category breakdown (JSON for flexible categories)
    performance_by_category JSONB DEFAULT '{}',
    performance_by_segment JSONB DEFAULT '{}',
    performance_by_channel JSONB DEFAULT '{}',

    -- Top performers
    top_performing_offers TEXT[] DEFAULT '{}',
    best_presentation_hours INTEGER[] DEFAULT '{}',

    -- A/B testing results
    ab_test_results JSONB DEFAULT '{}',

    -- Generated metadata
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_upsell_metrics_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_metrics_data CHECK (
        total_opportunities >= 0 AND
        total_presentations >= 0 AND
        total_acceptances >= 0 AND
        total_presentations <= total_opportunities AND
        total_acceptances <= total_presentations AND
        total_revenue >= 0
    )
);

-- Unique constraint for daily metrics per tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_upsell_metrics_daily_unique
ON upsell_metrics_daily(tenant_id, metrics_date);

-- Indexes for daily metrics
CREATE INDEX IF NOT EXISTS idx_upsell_metrics_tenant ON upsell_metrics_daily(tenant_id);
CREATE INDEX IF NOT EXISTS idx_upsell_metrics_date ON upsell_metrics_daily(metrics_date DESC);
CREATE INDEX IF NOT EXISTS idx_upsell_metrics_revenue ON upsell_metrics_daily(total_revenue DESC);
CREATE INDEX IF NOT EXISTS idx_upsell_metrics_conversion ON upsell_metrics_daily(conversion_rate DESC);

-- Upselling events log for detailed tracking
CREATE TABLE IF NOT EXISTS upsell_events (
    event_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id VARCHAR(100) NOT NULL,
    recommendation_id VARCHAR(36),
    guest_id VARCHAR(100),

    -- Event details
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB DEFAULT '{}',

    -- Context
    offer_id VARCHAR(36),
    campaign_id VARCHAR(36),
    session_id VARCHAR(100),
    channel VARCHAR(50),

    -- Revenue tracking
    revenue_amount NUMERIC(10,2) DEFAULT 0.0,

    -- Timing
    event_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_upsell_event_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,
    CONSTRAINT fk_upsell_event_recommendation FOREIGN KEY (recommendation_id) REFERENCES upsell_recommendations(recommendation_id) ON DELETE SET NULL,
    CONSTRAINT fk_upsell_event_offer FOREIGN KEY (offer_id) REFERENCES upsell_offers(offer_id) ON DELETE SET NULL,
    CONSTRAINT fk_upsell_event_campaign FOREIGN KEY (campaign_id) REFERENCES upsell_campaigns(campaign_id) ON DELETE SET NULL,

    -- Constraints
    CONSTRAINT valid_event_type CHECK (event_type IN ('opportunity_detected', 'recommendation_generated', 'offer_presented', 'guest_response', 'upsell_completed', 'revenue_recorded')),
    CONSTRAINT valid_revenue_amount CHECK (revenue_amount >= 0)
);

-- Indexes for upsell events
CREATE INDEX IF NOT EXISTS idx_upsell_events_tenant ON upsell_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_upsell_events_recommendation ON upsell_events(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_upsell_events_guest ON upsell_events(guest_id);
CREATE INDEX IF NOT EXISTS idx_upsell_events_type ON upsell_events(event_type);
CREATE INDEX IF NOT EXISTS idx_upsell_events_timestamp ON upsell_events(event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_upsell_events_offer ON upsell_events(offer_id);
CREATE INDEX IF NOT EXISTS idx_upsell_events_campaign ON upsell_events(campaign_id);
CREATE INDEX IF NOT EXISTS idx_upsell_events_channel ON upsell_events(channel);
CREATE INDEX IF NOT EXISTS idx_upsell_events_revenue ON upsell_events(revenue_amount DESC);

-- Enable Row Level Security for upselling tables
ALTER TABLE upsell_offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE guest_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE upsell_recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE upsell_campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE upsell_metrics_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE upsell_events ENABLE ROW LEVEL SECURITY;

-- RLS policies for upselling tables (tenant isolation)

-- Upsell offers access policy
CREATE POLICY upsell_offers_isolation ON upsell_offers
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Guest profiles access policy
CREATE POLICY guest_profiles_isolation ON guest_profiles
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Upsell recommendations access policy
CREATE POLICY upsell_recommendations_isolation ON upsell_recommendations
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Upsell campaigns access policy
CREATE POLICY upsell_campaigns_isolation ON upsell_campaigns
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Upsell metrics access policy
CREATE POLICY upsell_metrics_isolation ON upsell_metrics_daily
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Upsell events access policy
CREATE POLICY upsell_events_isolation ON upsell_events
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Functions for upselling analytics and optimization

-- Function to calculate upselling metrics for a period
CREATE OR REPLACE FUNCTION calculate_upselling_metrics(
    tenant_id TEXT,
    start_date DATE,
    end_date DATE
)
RETURNS TABLE(
    metric_name TEXT,
    metric_value NUMERIC,
    metric_unit TEXT
) AS $$
BEGIN
    RETURN QUERY
    -- Total opportunities
    SELECT 'total_opportunities'::TEXT,
           COUNT(DISTINCT recommendation_id)::NUMERIC,
           'count'::TEXT
    FROM upsell_recommendations
    WHERE tenant_id = $1
      AND DATE(generated_at) BETWEEN start_date AND end_date

    UNION ALL

    -- Total presentations
    SELECT 'total_presentations'::TEXT,
           COUNT(DISTINCT recommendation_id)::NUMERIC,
           'count'::TEXT
    FROM upsell_recommendations
    WHERE tenant_id = $1
      AND DATE(generated_at) BETWEEN start_date AND end_date
      AND shown_at IS NOT NULL

    UNION ALL

    -- Total acceptances
    SELECT 'total_acceptances'::TEXT,
           COUNT(DISTINCT recommendation_id)::NUMERIC,
           'count'::TEXT
    FROM upsell_recommendations
    WHERE tenant_id = $1
      AND DATE(generated_at) BETWEEN start_date AND end_date
      AND guest_response = 'accepted'

    UNION ALL

    -- Total revenue
    SELECT 'total_revenue'::TEXT,
           COALESCE(SUM(expected_revenue), 0)::NUMERIC,
           'currency'::TEXT
    FROM upsell_recommendations
    WHERE tenant_id = $1
      AND DATE(generated_at) BETWEEN start_date AND end_date
      AND guest_response = 'accepted'

    UNION ALL

    -- Conversion rate
    SELECT 'conversion_rate'::TEXT,
           CASE
               WHEN COUNT(CASE WHEN shown_at IS NOT NULL THEN 1 END) > 0
               THEN COUNT(CASE WHEN guest_response = 'accepted' THEN 1 END)::NUMERIC /
                    COUNT(CASE WHEN shown_at IS NOT NULL THEN 1 END)::NUMERIC
               ELSE 0
           END,
           'percentage'::TEXT
    FROM upsell_recommendations
    WHERE tenant_id = $1
      AND DATE(generated_at) BETWEEN start_date AND end_date;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get top performing offers
CREATE OR REPLACE FUNCTION get_top_performing_offers(
    tenant_id TEXT,
    limit_count INTEGER DEFAULT 10
)
RETURNS TABLE(
    offer_id TEXT,
    title TEXT,
    category TEXT,
    acceptance_rate NUMERIC,
    total_revenue NUMERIC,
    times_shown INTEGER,
    times_accepted INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT o.offer_id,
           o.title,
           o.category,
           CASE
               WHEN o.times_shown > 0
               THEN o.times_accepted::NUMERIC / o.times_shown::NUMERIC
               ELSE 0
           END as acceptance_rate,
           o.revenue_generated,
           o.times_shown,
           o.times_accepted
    FROM upsell_offers o
    WHERE o.tenant_id = $1
      AND o.is_active = TRUE
      AND o.times_shown > 0
    ORDER BY
        (CASE WHEN o.times_shown > 0 THEN o.times_accepted::NUMERIC / o.times_shown::NUMERIC ELSE 0 END) DESC,
        o.revenue_generated DESC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to analyze guest segment performance
CREATE OR REPLACE FUNCTION analyze_guest_segment_performance(
    tenant_id TEXT,
    start_date DATE,
    end_date DATE
)
RETURNS TABLE(
    guest_segment TEXT,
    total_opportunities INTEGER,
    total_acceptances INTEGER,
    conversion_rate NUMERIC,
    average_revenue NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT gp.budget_tier as guest_segment,
           COUNT(ur.recommendation_id)::INTEGER as total_opportunities,
           COUNT(CASE WHEN ur.guest_response = 'accepted' THEN 1 END)::INTEGER as total_acceptances,
           CASE
               WHEN COUNT(ur.recommendation_id) > 0
               THEN COUNT(CASE WHEN ur.guest_response = 'accepted' THEN 1 END)::NUMERIC /
                    COUNT(ur.recommendation_id)::NUMERIC
               ELSE 0
           END as conversion_rate,
           COALESCE(AVG(CASE WHEN ur.guest_response = 'accepted' THEN ur.expected_revenue END), 0) as average_revenue
    FROM guest_profiles gp
    LEFT JOIN upsell_recommendations ur ON gp.guest_id = ur.guest_id AND gp.tenant_id = ur.tenant_id
    WHERE gp.tenant_id = $1
      AND (ur.recommendation_id IS NULL OR DATE(ur.generated_at) BETWEEN start_date AND end_date)
    GROUP BY gp.budget_tier
    ORDER BY conversion_rate DESC, average_revenue DESC;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to update offer performance metrics
CREATE OR REPLACE FUNCTION update_offer_performance()
RETURNS TRIGGER AS $$
BEGIN
    -- Update offer performance when recommendation response is recorded
    IF NEW.guest_response IS NOT NULL AND OLD.guest_response IS NULL THEN
        UPDATE upsell_offers
        SET times_accepted = CASE WHEN NEW.guest_response = 'accepted' THEN times_accepted + 1 ELSE times_accepted END,
            times_declined = CASE WHEN NEW.guest_response = 'declined' THEN times_declined + 1 ELSE times_declined END,
            revenue_generated = CASE WHEN NEW.guest_response = 'accepted' THEN revenue_generated + NEW.expected_revenue ELSE revenue_generated END,
            updated_at = NOW()
        WHERE offer_id = NEW.primary_offer_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update offer performance
CREATE TRIGGER update_upsell_offer_performance
    AFTER UPDATE ON upsell_recommendations
    FOR EACH ROW
    EXECUTE FUNCTION update_offer_performance();

-- Function to update guest profile from upselling activity
CREATE OR REPLACE FUNCTION update_guest_profile_from_upselling()
RETURNS TRIGGER AS $$
DECLARE
    profile_exists BOOLEAN;
BEGIN
    -- Check if guest profile exists
    SELECT EXISTS(
        SELECT 1 FROM guest_profiles
        WHERE guest_id = NEW.guest_id AND tenant_id = NEW.tenant_id
    ) INTO profile_exists;

    IF profile_exists THEN
        -- Update existing profile
        UPDATE guest_profiles
        SET total_upsells_accepted = CASE WHEN NEW.guest_response = 'accepted' THEN total_upsells_accepted + 1 ELSE total_upsells_accepted END,
            total_upsells_declined = CASE WHEN NEW.guest_response = 'declined' THEN total_upsells_declined + 1 ELSE total_upsells_declined END,
            average_upsell_spend = CASE
                WHEN NEW.guest_response = 'accepted' AND total_upsells_accepted > 0
                THEN (average_upsell_spend * total_upsells_accepted + NEW.expected_revenue) / (total_upsells_accepted + 1)
                ELSE average_upsell_spend
            END,
            updated_at = NOW()
        WHERE guest_id = NEW.guest_id AND tenant_id = NEW.tenant_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update guest profiles from upselling activity
CREATE TRIGGER update_guest_profile_from_upsell_response
    AFTER UPDATE ON upsell_recommendations
    FOR EACH ROW
    WHEN (NEW.guest_response IS NOT NULL AND OLD.guest_response IS NULL)
    EXECUTE FUNCTION update_guest_profile_from_upselling();

-- Views for upselling reporting

-- Upselling performance overview
CREATE OR REPLACE VIEW upselling_performance_overview AS
SELECT
    uo.tenant_id,
    uo.category,
    COUNT(uo.offer_id) as total_offers,
    COUNT(CASE WHEN uo.is_active THEN 1 END) as active_offers,
    COALESCE(SUM(uo.times_shown), 0) as total_impressions,
    COALESCE(SUM(uo.times_accepted), 0) as total_acceptances,
    COALESCE(SUM(uo.times_declined), 0) as total_declines,
    COALESCE(SUM(uo.revenue_generated), 0) as total_revenue,

    -- Calculate rates
    CASE
        WHEN SUM(uo.times_shown) > 0
        THEN SUM(uo.times_accepted)::NUMERIC / SUM(uo.times_shown)::NUMERIC
        ELSE 0
    END as acceptance_rate,

    CASE
        WHEN SUM(uo.times_accepted) > 0
        THEN SUM(uo.revenue_generated) / SUM(uo.times_accepted)
        ELSE 0
    END as average_accepted_value

FROM upsell_offers uo
GROUP BY uo.tenant_id, uo.category
ORDER BY uo.tenant_id, total_revenue DESC;

-- Guest segment upselling analysis
CREATE OR REPLACE VIEW guest_segment_upselling_analysis AS
SELECT
    gp.tenant_id,
    gp.budget_tier,
    gp.loyalty_tier,
    COUNT(DISTINCT gp.guest_id) as total_guests,
    COALESCE(AVG(gp.total_upsells_accepted), 0) as avg_upsells_accepted,
    COALESCE(AVG(gp.average_upsell_spend), 0) as avg_spend_per_upsell,
    COALESCE(AVG(gp.lifetime_value), 0) as avg_lifetime_value,

    -- Calculate segment acceptance rate
    CASE
        WHEN AVG(gp.total_upsells_accepted + gp.total_upsells_declined) > 0
        THEN AVG(gp.total_upsells_accepted) / AVG(gp.total_upsells_accepted + gp.total_upsells_declined)
        ELSE 0
    END as segment_acceptance_rate

FROM guest_profiles gp
GROUP BY gp.tenant_id, gp.budget_tier, gp.loyalty_tier
ORDER BY gp.tenant_id, avg_lifetime_value DESC;

-- Campaign performance summary
CREATE OR REPLACE VIEW campaign_performance_summary AS
SELECT
    uc.campaign_id,
    uc.tenant_id,
    uc.campaign_name,
    uc.campaign_strategy,
    uc.start_date,
    uc.end_date,
    uc.is_active,
    uc.total_impressions,
    uc.total_conversions,
    uc.total_revenue,

    -- Calculate performance metrics
    CASE
        WHEN uc.total_impressions > 0
        THEN uc.total_conversions::NUMERIC / uc.total_impressions::NUMERIC
        ELSE 0
    END as conversion_rate,

    CASE
        WHEN uc.total_conversions > 0
        THEN uc.total_revenue / uc.total_conversions
        ELSE 0
    END as revenue_per_conversion,

    -- Compare to targets
    CASE
        WHEN uc.total_impressions >= uc.minimum_sample_size
        THEN (uc.total_conversions::NUMERIC / uc.total_impressions::NUMERIC) >= uc.target_conversion_rate
        ELSE NULL
    END as meeting_conversion_target

FROM upsell_campaigns uc
ORDER BY uc.tenant_id, uc.total_revenue DESC;

-- Comments for documentation
COMMENT ON TABLE upsell_offers IS 'Upselling offers with performance tracking and tenant isolation';
COMMENT ON TABLE guest_profiles IS 'Guest profiles for personalized upselling recommendations';
COMMENT ON TABLE upsell_recommendations IS 'AI-generated upselling recommendations with response tracking';
COMMENT ON TABLE upsell_campaigns IS 'Upselling campaigns with A/B testing support';
COMMENT ON TABLE upsell_metrics_daily IS 'Daily aggregated upselling performance metrics';
COMMENT ON TABLE upsell_events IS 'Detailed event log for upselling activity tracking';

COMMENT ON VIEW upselling_performance_overview IS 'High-level upselling performance by category and tenant';
COMMENT ON VIEW guest_segment_upselling_analysis IS 'Guest segment analysis for upselling optimization';
COMMENT ON VIEW campaign_performance_summary IS 'Campaign performance metrics and target achievement';

COMMENT ON FUNCTION calculate_upselling_metrics IS 'Calculate comprehensive upselling metrics for a date range';
COMMENT ON FUNCTION get_top_performing_offers IS 'Get top performing offers by acceptance rate and revenue';
COMMENT ON FUNCTION analyze_guest_segment_performance IS 'Analyze upselling performance by guest segment';