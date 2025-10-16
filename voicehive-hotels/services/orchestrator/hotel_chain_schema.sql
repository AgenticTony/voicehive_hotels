-- Hotel Chain Management Schema Extension
-- Additional tables for chain operations, hierarchy tracking, and analytics

-- Chain property hierarchies table (detailed property relationships)
CREATE TABLE IF NOT EXISTS chain_property_hierarchies (
    property_id VARCHAR(100) PRIMARY KEY,
    chain_id VARCHAR(100) NOT NULL,

    -- Hierarchy data (full PropertyHierarchy JSON)
    property_data JSONB NOT NULL,

    -- Quick access fields (extracted from JSON for indexing)
    property_name VARCHAR(255) NOT NULL,
    property_type VARCHAR(50) NOT NULL,
    property_status VARCHAR(50) NOT NULL DEFAULT 'active',
    parent_property_id VARCHAR(100),
    hierarchy_level INTEGER NOT NULL DEFAULT 0,

    -- Geographic indexing
    country VARCHAR(100),
    region VARCHAR(100),
    city VARCHAR(100),

    -- Operational flags
    accepts_reservations BOOLEAN DEFAULT TRUE,
    shared_inventory BOOLEAN DEFAULT FALSE,
    cross_property_services BOOLEAN DEFAULT TRUE,

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_property_hierarchy_chain FOREIGN KEY (chain_id) REFERENCES hotel_chains(chain_id) ON DELETE CASCADE,
    CONSTRAINT fk_property_hierarchy_parent FOREIGN KEY (parent_property_id) REFERENCES chain_property_hierarchies(property_id) ON DELETE SET NULL,
    CONSTRAINT fk_property_hierarchy_tenant FOREIGN KEY (property_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_property_type CHECK (property_type IN ('chain_hq', 'regional_office', 'flagship_hotel', 'standard_hotel', 'extended_stay', 'resort', 'boutique', 'franchise')),
    CONSTRAINT valid_property_status CHECK (property_status IN ('active', 'under_construction', 'temporarily_closed', 'suspended', 'sold', 'planned')),
    CONSTRAINT valid_hierarchy_level CHECK (hierarchy_level >= 0 AND hierarchy_level <= 5),
    CONSTRAINT no_self_parent CHECK (property_id != parent_property_id)
);

-- Indexes for property hierarchies
CREATE INDEX IF NOT EXISTS idx_property_hierarchy_chain ON chain_property_hierarchies(chain_id);
CREATE INDEX IF NOT EXISTS idx_property_hierarchy_parent ON chain_property_hierarchies(parent_property_id);
CREATE INDEX IF NOT EXISTS idx_property_hierarchy_type ON chain_property_hierarchies(property_type);
CREATE INDEX IF NOT EXISTS idx_property_hierarchy_status ON chain_property_hierarchies(property_status);
CREATE INDEX IF NOT EXISTS idx_property_hierarchy_level ON chain_property_hierarchies(hierarchy_level);
CREATE INDEX IF NOT EXISTS idx_property_hierarchy_location ON chain_property_hierarchies(country, region, city);
CREATE INDEX IF NOT EXISTS idx_property_hierarchy_data_gin ON chain_property_hierarchies USING GIN (property_data);

-- Chain operations tracking table
CREATE TABLE IF NOT EXISTS chain_operations (
    operation_id VARCHAR(36) PRIMARY KEY,
    chain_id VARCHAR(100) NOT NULL,

    -- Operation details
    operation_type VARCHAR(50) NOT NULL,
    operation_name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Operation data (full ChainOperation JSON)
    operation_data JSONB NOT NULL,

    -- Quick access fields for querying
    status VARCHAR(50) NOT NULL DEFAULT 'scheduled',
    progress_percentage NUMERIC(5,2) DEFAULT 0.0,

    -- Scheduling
    scheduled_start TIMESTAMP WITH TIME ZONE NOT NULL,
    scheduled_end TIMESTAMP WITH TIME ZONE,
    actual_start TIMESTAMP WITH TIME ZONE,
    actual_end TIMESTAMP WITH TIME ZONE,

    -- Targeting
    target_properties TEXT[], -- Array of property IDs
    target_property_types TEXT[], -- Array of property types
    exclude_properties TEXT[], -- Array of excluded property IDs

    -- Results tracking
    successful_properties TEXT[] DEFAULT '{}',
    failed_properties TEXT[] DEFAULT '{}',
    skipped_properties TEXT[] DEFAULT '{}',

    -- Error handling
    error_message TEXT,
    rollback_data JSONB,

    -- Approval workflow
    requires_approval BOOLEAN DEFAULT TRUE,
    approved_by VARCHAR(100),
    approval_date TIMESTAMP WITH TIME ZONE,

    -- Audit trail
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_chain_operation_chain FOREIGN KEY (chain_id) REFERENCES hotel_chains(chain_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_operation_type CHECK (operation_type IN ('config_update', 'software_deployment', 'policy_change', 'rate_update', 'promotion_launch', 'maintenance_window', 'training_rollout')),
    CONSTRAINT valid_operation_status CHECK (status IN ('scheduled', 'in_progress', 'completed', 'failed', 'cancelled')),
    CONSTRAINT valid_progress_percentage CHECK (progress_percentage >= 0 AND progress_percentage <= 100),
    CONSTRAINT valid_scheduling CHECK (scheduled_start <= COALESCE(scheduled_end, scheduled_start + INTERVAL '1 day'))
);

-- Indexes for chain operations
CREATE INDEX IF NOT EXISTS idx_chain_operations_chain ON chain_operations(chain_id);
CREATE INDEX IF NOT EXISTS idx_chain_operations_status ON chain_operations(status);
CREATE INDEX IF NOT EXISTS idx_chain_operations_type ON chain_operations(operation_type);
CREATE INDEX IF NOT EXISTS idx_chain_operations_scheduled ON chain_operations(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_chain_operations_created_by ON chain_operations(created_by);
CREATE INDEX IF NOT EXISTS idx_chain_operations_approval ON chain_operations(requires_approval, approved_by);
CREATE INDEX IF NOT EXISTS idx_chain_operations_data_gin ON chain_operations USING GIN (operation_data);

-- Chain analytics tracking table
CREATE TABLE IF NOT EXISTS chain_analytics (
    analytics_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    chain_id VARCHAR(100) NOT NULL,

    -- Analysis period
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    period_type VARCHAR(20) NOT NULL DEFAULT 'daily', -- daily, weekly, monthly, quarterly, annual

    -- Analytics data (full ChainAnalytics JSON)
    analytics_data JSONB NOT NULL,

    -- Quick access metrics for querying and dashboards
    total_properties INTEGER DEFAULT 0,
    active_properties INTEGER DEFAULT 0,
    total_rooms INTEGER DEFAULT 0,
    total_calls_handled INTEGER DEFAULT 0,
    total_reservations_made INTEGER DEFAULT 0,

    -- Financial metrics
    total_revenue_usd NUMERIC(15,2) DEFAULT 0.0,
    revenue_per_property NUMERIC(10,2) DEFAULT 0.0,
    average_daily_rate NUMERIC(8,2) DEFAULT 0.0,
    occupancy_rate_percentage NUMERIC(5,2) DEFAULT 0.0,

    -- Service quality metrics
    average_response_time_seconds NUMERIC(6,2) DEFAULT 0.0,
    customer_satisfaction_score NUMERIC(3,2) DEFAULT 0.0,
    ai_accuracy_percentage NUMERIC(5,2) DEFAULT 0.0,

    -- Technology adoption
    voice_ai_adoption_rate NUMERIC(5,2) DEFAULT 0.0,
    mobile_app_usage_rate NUMERIC(5,2) DEFAULT 0.0,
    self_service_completion_rate NUMERIC(5,2) DEFAULT 0.0,

    -- Generation metadata
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    generated_by VARCHAR(100) DEFAULT 'system',

    -- Foreign key constraints
    CONSTRAINT fk_chain_analytics_chain FOREIGN KEY (chain_id) REFERENCES hotel_chains(chain_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_period_type CHECK (period_type IN ('daily', 'weekly', 'monthly', 'quarterly', 'annual')),
    CONSTRAINT valid_period_order CHECK (period_start < period_end),
    CONSTRAINT valid_percentages CHECK (
        occupancy_rate_percentage >= 0 AND occupancy_rate_percentage <= 100 AND
        ai_accuracy_percentage >= 0 AND ai_accuracy_percentage <= 100 AND
        voice_ai_adoption_rate >= 0 AND voice_ai_adoption_rate <= 100 AND
        mobile_app_usage_rate >= 0 AND mobile_app_usage_rate <= 100 AND
        self_service_completion_rate >= 0 AND self_service_completion_rate <= 100 AND
        customer_satisfaction_score >= 0 AND customer_satisfaction_score <= 10
    )
);

-- Indexes for chain analytics
CREATE INDEX IF NOT EXISTS idx_chain_analytics_chain ON chain_analytics(chain_id);
CREATE INDEX IF NOT EXISTS idx_chain_analytics_period ON chain_analytics(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_chain_analytics_type ON chain_analytics(period_type);
CREATE INDEX IF NOT EXISTS idx_chain_analytics_generated ON chain_analytics(generated_at);
CREATE INDEX IF NOT EXISTS idx_chain_analytics_data_gin ON chain_analytics USING GIN (analytics_data);

-- Unique constraint for analytics periods per chain
CREATE UNIQUE INDEX IF NOT EXISTS idx_chain_analytics_unique_period
ON chain_analytics(chain_id, period_start, period_type);

-- Chain configuration inheritance tracking
CREATE TABLE IF NOT EXISTS chain_config_inheritance (
    inheritance_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    chain_id VARCHAR(100) NOT NULL,
    property_id VARCHAR(100) NOT NULL,

    -- Inheritance configuration
    inheritance_type VARCHAR(20) NOT NULL DEFAULT 'selective',
    config_section VARCHAR(100) NOT NULL,
    inherited_value JSONB,
    local_override_value JSONB,
    effective_value JSONB,

    -- Inheritance metadata
    inherited_from VARCHAR(100), -- property_id or 'chain' for chain-level
    inheritance_path TEXT[], -- full inheritance path
    override_reason TEXT,

    -- Status and lifecycle
    is_active BOOLEAN DEFAULT TRUE,
    effective_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expiry_date TIMESTAMP WITH TIME ZONE,

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) NOT NULL,

    -- Foreign key constraints
    CONSTRAINT fk_config_inheritance_chain FOREIGN KEY (chain_id) REFERENCES hotel_chains(chain_id) ON DELETE CASCADE,
    CONSTRAINT fk_config_inheritance_property FOREIGN KEY (property_id) REFERENCES chain_property_hierarchies(property_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_inheritance_type CHECK (inheritance_type IN ('full', 'selective', 'none', 'override'))
);

-- Indexes for configuration inheritance
CREATE INDEX IF NOT EXISTS idx_config_inheritance_chain ON chain_config_inheritance(chain_id);
CREATE INDEX IF NOT EXISTS idx_config_inheritance_property ON chain_config_inheritance(property_id);
CREATE INDEX IF NOT EXISTS idx_config_inheritance_section ON chain_config_inheritance(config_section);
CREATE INDEX IF NOT EXISTS idx_config_inheritance_active ON chain_config_inheritance(is_active);
CREATE INDEX IF NOT EXISTS idx_config_inheritance_path ON chain_config_inheritance USING GIN (inheritance_path);

-- Unique constraint for active config sections per property
CREATE UNIQUE INDEX IF NOT EXISTS idx_config_inheritance_unique_active
ON chain_config_inheritance(property_id, config_section)
WHERE is_active = TRUE;

-- Chain performance benchmarks table
CREATE TABLE IF NOT EXISTS chain_performance_benchmarks (
    benchmark_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    chain_id VARCHAR(100) NOT NULL,

    -- Benchmark details
    benchmark_name VARCHAR(255) NOT NULL,
    benchmark_category VARCHAR(100) NOT NULL, -- operational, financial, customer_service, technology
    metric_name VARCHAR(100) NOT NULL,

    -- Benchmark values
    target_value NUMERIC(15,4) NOT NULL,
    minimum_acceptable NUMERIC(15,4),
    industry_average NUMERIC(15,4),
    best_in_class NUMERIC(15,4),

    -- Measurement details
    measurement_unit VARCHAR(50) NOT NULL, -- percentage, currency, seconds, count, etc.
    measurement_frequency VARCHAR(20) NOT NULL DEFAULT 'monthly', -- daily, weekly, monthly, quarterly

    -- Benchmark scope
    applies_to_property_types TEXT[] DEFAULT '{}',
    applies_to_regions TEXT[] DEFAULT '{}',

    -- Status and lifecycle
    is_active BOOLEAN DEFAULT TRUE,
    effective_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    review_date TIMESTAMP WITH TIME ZONE,

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) NOT NULL,

    -- Foreign key constraints
    CONSTRAINT fk_benchmark_chain FOREIGN KEY (chain_id) REFERENCES hotel_chains(chain_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_benchmark_category CHECK (benchmark_category IN ('operational', 'financial', 'customer_service', 'technology', 'compliance', 'sustainability')),
    CONSTRAINT valid_measurement_frequency CHECK (measurement_frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'annual')),
    CONSTRAINT valid_target_value CHECK (target_value >= 0)
);

-- Indexes for performance benchmarks
CREATE INDEX IF NOT EXISTS idx_benchmarks_chain ON chain_performance_benchmarks(chain_id);
CREATE INDEX IF NOT EXISTS idx_benchmarks_category ON chain_performance_benchmarks(benchmark_category);
CREATE INDEX IF NOT EXISTS idx_benchmarks_metric ON chain_performance_benchmarks(metric_name);
CREATE INDEX IF NOT EXISTS idx_benchmarks_active ON chain_performance_benchmarks(is_active);
CREATE INDEX IF NOT EXISTS idx_benchmarks_review ON chain_performance_benchmarks(review_date);

-- Chain communication log (for tracking chain-wide announcements, alerts, etc.)
CREATE TABLE IF NOT EXISTS chain_communications (
    communication_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    chain_id VARCHAR(100) NOT NULL,

    -- Communication details
    communication_type VARCHAR(50) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    message_content TEXT NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',

    -- Targeting
    target_properties TEXT[] DEFAULT '{}', -- Empty means all properties
    target_roles TEXT[] DEFAULT '{}', -- hotel_admin, hotel_staff, etc.
    target_property_types TEXT[] DEFAULT '{}',

    -- Delivery tracking
    total_recipients INTEGER DEFAULT 0,
    delivered_count INTEGER DEFAULT 0,
    read_count INTEGER DEFAULT 0,
    acknowledged_count INTEGER DEFAULT 0,

    -- Scheduling
    scheduled_send_time TIMESTAMP WITH TIME ZONE,
    actual_send_time TIMESTAMP WITH TIME ZONE,

    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'draft',

    -- Communication metadata
    requires_acknowledgment BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMP WITH TIME ZONE,

    -- Audit trail
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_communication_chain FOREIGN KEY (chain_id) REFERENCES hotel_chains(chain_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_communication_type CHECK (communication_type IN ('announcement', 'alert', 'policy_update', 'training_notice', 'system_maintenance', 'emergency', 'newsletter')),
    CONSTRAINT valid_priority CHECK (priority IN ('low', 'normal', 'high', 'urgent', 'critical')),
    CONSTRAINT valid_communication_status CHECK (status IN ('draft', 'scheduled', 'sending', 'sent', 'cancelled'))
);

-- Indexes for chain communications
CREATE INDEX IF NOT EXISTS idx_communications_chain ON chain_communications(chain_id);
CREATE INDEX IF NOT EXISTS idx_communications_type ON chain_communications(communication_type);
CREATE INDEX IF NOT EXISTS idx_communications_priority ON chain_communications(priority);
CREATE INDEX IF NOT EXISTS idx_communications_status ON chain_communications(status);
CREATE INDEX IF NOT EXISTS idx_communications_scheduled ON chain_communications(scheduled_send_time);

-- Enable Row Level Security for chain tables
ALTER TABLE chain_property_hierarchies ENABLE ROW LEVEL SECURITY;
ALTER TABLE chain_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE chain_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE chain_config_inheritance ENABLE ROW LEVEL SECURITY;
ALTER TABLE chain_performance_benchmarks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chain_communications ENABLE ROW LEVEL SECURITY;

-- RLS policies for chain tables (following same pattern as tenant isolation)

-- Chain property hierarchies access policy
CREATE POLICY chain_property_hierarchy_isolation ON chain_property_hierarchies
    FOR ALL
    TO application_role
    USING (
        property_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR chain_id IN (
            SELECT chain_id FROM hotel_chains
            WHERE headquarters_tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        )
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Chain operations access policy
CREATE POLICY chain_operations_isolation ON chain_operations
    FOR ALL
    TO application_role
    USING (
        chain_id IN (
            SELECT chain_id FROM hotel_chains
            WHERE headquarters_tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        )
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Chain analytics access policy
CREATE POLICY chain_analytics_isolation ON chain_analytics
    FOR ALL
    TO application_role
    USING (
        chain_id IN (
            SELECT chain_id FROM hotel_chains
            WHERE headquarters_tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        )
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Chain config inheritance access policy
CREATE POLICY chain_config_inheritance_isolation ON chain_config_inheritance
    FOR ALL
    TO application_role
    USING (
        property_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR chain_id IN (
            SELECT chain_id FROM hotel_chains
            WHERE headquarters_tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        )
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Chain benchmarks access policy
CREATE POLICY chain_benchmarks_isolation ON chain_performance_benchmarks
    FOR ALL
    TO application_role
    USING (
        chain_id IN (
            SELECT chain_id FROM hotel_chains
            WHERE headquarters_tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        )
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Chain communications access policy
CREATE POLICY chain_communications_isolation ON chain_communications
    FOR ALL
    TO application_role
    USING (
        chain_id IN (
            SELECT chain_id FROM hotel_chains
            WHERE headquarters_tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        )
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Functions for chain hierarchy operations

-- Function to get property hierarchy path
CREATE OR REPLACE FUNCTION get_property_hierarchy_path(property_id TEXT)
RETURNS TEXT[] AS $$
DECLARE
    path TEXT[] := ARRAY[]::TEXT[];
    current_id TEXT := property_id;
    parent_id TEXT;
    counter INTEGER := 0;
BEGIN
    -- Build hierarchy path from property to chain root
    WHILE current_id IS NOT NULL AND counter < 10 LOOP -- Prevent infinite loops
        path := array_prepend(current_id, path);

        -- Get parent property
        SELECT property_data->>'parent_property_id'
        INTO parent_id
        FROM chain_property_hierarchies
        WHERE property_id = current_id;

        current_id := parent_id;
        counter := counter + 1;
    END LOOP;

    RETURN path;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get all descendant properties
CREATE OR REPLACE FUNCTION get_descendant_properties(parent_property_id TEXT)
RETURNS TABLE(property_id TEXT, level INTEGER) AS $$
WITH RECURSIVE property_tree AS (
    -- Base case: direct children
    SELECT p.property_id, p.hierarchy_level as level
    FROM chain_property_hierarchies p
    WHERE p.parent_property_id = $1

    UNION ALL

    -- Recursive case: children of children
    SELECT p.property_id, p.hierarchy_level as level
    FROM chain_property_hierarchies p
    INNER JOIN property_tree pt ON p.parent_property_id = pt.property_id
)
SELECT * FROM property_tree ORDER BY level, property_id;
$$ LANGUAGE SQL SECURITY DEFINER;

-- Function to validate chain hierarchy integrity
CREATE OR REPLACE FUNCTION validate_chain_hierarchy(chain_id TEXT)
RETURNS TABLE(
    issue_type TEXT,
    property_id TEXT,
    description TEXT
) AS $$
BEGIN
    RETURN QUERY
    -- Check for circular references
    WITH RECURSIVE hierarchy_check AS (
        SELECT p.property_id, p.parent_property_id, p.hierarchy_level, 1 as depth,
               ARRAY[p.property_id] as path
        FROM chain_property_hierarchies p
        WHERE p.chain_id = $1

        UNION ALL

        SELECT p.property_id, p.parent_property_id, p.hierarchy_level, hc.depth + 1,
               hc.path || p.property_id
        FROM chain_property_hierarchies p
        INNER JOIN hierarchy_check hc ON p.property_id = hc.parent_property_id
        WHERE hc.depth < 10 AND NOT (p.property_id = ANY(hc.path))
    )
    SELECT 'CIRCULAR_REFERENCE'::TEXT,
           hc.property_id,
           'Property has circular reference in hierarchy'::TEXT
    FROM hierarchy_check hc
    WHERE hc.depth >= 10

    UNION ALL

    -- Check for orphaned properties (parent doesn't exist)
    SELECT 'ORPHANED_PROPERTY'::TEXT,
           p.property_id,
           'Property references non-existent parent: ' || p.parent_property_id
    FROM chain_property_hierarchies p
    LEFT JOIN chain_property_hierarchies parent ON p.parent_property_id = parent.property_id
    WHERE p.chain_id = $1
      AND p.parent_property_id IS NOT NULL
      AND parent.property_id IS NULL

    UNION ALL

    -- Check for incorrect hierarchy levels
    SELECT 'INCORRECT_LEVEL'::TEXT,
           p.property_id,
           'Property level (' || p.hierarchy_level || ') should be ' || (COALESCE(parent.hierarchy_level, -1) + 1)
    FROM chain_property_hierarchies p
    LEFT JOIN chain_property_hierarchies parent ON p.parent_property_id = parent.property_id
    WHERE p.chain_id = $1
      AND (
          (p.parent_property_id IS NULL AND p.hierarchy_level != 0) OR
          (p.parent_property_id IS NOT NULL AND p.hierarchy_level != parent.hierarchy_level + 1)
      );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to calculate chain analytics
CREATE OR REPLACE FUNCTION calculate_chain_metrics(
    chain_id TEXT,
    period_start TIMESTAMP WITH TIME ZONE,
    period_end TIMESTAMP WITH TIME ZONE
)
RETURNS TABLE(
    metric_name TEXT,
    metric_value NUMERIC,
    metric_unit TEXT
) AS $$
BEGIN
    RETURN QUERY
    -- Total properties
    SELECT 'total_properties'::TEXT,
           COUNT(*)::NUMERIC,
           'count'::TEXT
    FROM chain_property_hierarchies
    WHERE chain_id = $1

    UNION ALL

    -- Active properties
    SELECT 'active_properties'::TEXT,
           COUNT(*)::NUMERIC,
           'count'::TEXT
    FROM chain_property_hierarchies
    WHERE chain_id = $1 AND property_status = 'active'

    UNION ALL

    -- Total rooms
    SELECT 'total_rooms'::TEXT,
           COALESCE(SUM((property_data->>'room_count')::INTEGER), 0)::NUMERIC,
           'count'::TEXT
    FROM chain_property_hierarchies
    WHERE chain_id = $1 AND property_status = 'active'

    UNION ALL

    -- Average property size
    SELECT 'avg_property_rooms'::TEXT,
           COALESCE(AVG((property_data->>'room_count')::INTEGER), 0)::NUMERIC,
           'count'::TEXT
    FROM chain_property_hierarchies
    WHERE chain_id = $1
      AND property_status = 'active'
      AND (property_data->>'room_count') IS NOT NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Triggers for maintaining data consistency

-- Trigger to update hierarchy levels when parent changes
CREATE OR REPLACE FUNCTION update_hierarchy_levels()
RETURNS TRIGGER AS $$
DECLARE
    new_level INTEGER;
BEGIN
    -- Calculate new level based on parent
    IF NEW.parent_property_id IS NULL THEN
        new_level := 0;
    ELSE
        SELECT hierarchy_level + 1 INTO new_level
        FROM chain_property_hierarchies
        WHERE property_id = NEW.parent_property_id;

        IF new_level IS NULL THEN
            RAISE EXCEPTION 'Parent property % not found', NEW.parent_property_id;
        END IF;
    END IF;

    -- Update level if it changed
    IF NEW.hierarchy_level != new_level THEN
        NEW.hierarchy_level := new_level;
    END IF;

    -- Update JSON data to match
    NEW.property_data := jsonb_set(NEW.property_data, '{level}', to_jsonb(new_level));
    NEW.updated_at := NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_property_hierarchy_levels
    BEFORE INSERT OR UPDATE ON chain_property_hierarchies
    FOR EACH ROW
    EXECUTE FUNCTION update_hierarchy_levels();

-- Trigger to update chain statistics when properties change
CREATE OR REPLACE FUNCTION update_chain_statistics()
RETURNS TRIGGER AS $$
BEGIN
    -- Update chain metadata with current statistics
    UPDATE hotel_chains
    SET updated_at = NOW()
    WHERE chain_id = COALESCE(NEW.chain_id, OLD.chain_id);

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_chain_stats_on_property_change
    AFTER INSERT OR UPDATE OR DELETE ON chain_property_hierarchies
    FOR EACH ROW
    EXECUTE FUNCTION update_chain_statistics();

-- Views for easy chain reporting

-- Chain overview view
CREATE OR REPLACE VIEW chain_overview AS
SELECT
    hc.chain_id,
    hc.chain_name,
    hc.chain_code,
    hc.corporate_entity,
    hc.primary_market,
    hc.headquarters_tenant_id,

    -- Property counts
    COUNT(cph.property_id) as total_properties,
    COUNT(CASE WHEN cph.property_status = 'active' THEN 1 END) as active_properties,
    COUNT(CASE WHEN cph.property_type = 'standard_hotel' THEN 1 END) as standard_hotels,
    COUNT(CASE WHEN cph.property_type = 'flagship_hotel' THEN 1 END) as flagship_hotels,
    COUNT(CASE WHEN cph.property_type = 'resort' THEN 1 END) as resorts,

    -- Geographic spread
    COUNT(DISTINCT cph.country) as countries,
    COUNT(DISTINCT cph.region) as regions,
    COUNT(DISTINCT cph.city) as cities,

    -- Room inventory
    COALESCE(SUM((cph.property_data->>'room_count')::INTEGER), 0) as total_rooms,
    COALESCE(AVG((cph.property_data->>'room_count')::INTEGER), 0) as avg_rooms_per_property,

    -- Operational flags
    COUNT(CASE WHEN cph.accepts_reservations THEN 1 END) as properties_accepting_reservations,
    COUNT(CASE WHEN cph.shared_inventory THEN 1 END) as properties_with_shared_inventory,
    COUNT(CASE WHEN cph.cross_property_services THEN 1 END) as properties_with_cross_services,

    hc.created_at,
    hc.updated_at

FROM hotel_chains hc
LEFT JOIN chain_property_hierarchies cph ON hc.chain_id = cph.chain_id
GROUP BY hc.chain_id, hc.chain_name, hc.chain_code, hc.corporate_entity,
         hc.primary_market, hc.headquarters_tenant_id, hc.created_at, hc.updated_at
ORDER BY hc.chain_name;

-- Property hierarchy view with full path
CREATE OR REPLACE VIEW property_hierarchy_view AS
SELECT
    cph.property_id,
    cph.property_name,
    cph.property_type,
    cph.property_status,
    cph.chain_id,
    hc.chain_name,
    cph.parent_property_id,
    cph.hierarchy_level,
    cph.country,
    cph.region,
    cph.city,

    -- Hierarchy path
    get_property_hierarchy_path(cph.property_id) as hierarchy_path,

    -- Parent property name
    parent.property_name as parent_property_name,

    -- Children count
    (SELECT COUNT(*) FROM chain_property_hierarchies children
     WHERE children.parent_property_id = cph.property_id) as children_count,

    -- Room information
    (cph.property_data->>'room_count')::INTEGER as room_count,
    (cph.property_data->>'property_size_sqm')::NUMERIC as property_size_sqm,

    -- Operational details
    cph.accepts_reservations,
    cph.shared_inventory,
    cph.cross_property_services,

    cph.created_at,
    cph.updated_at

FROM chain_property_hierarchies cph
JOIN hotel_chains hc ON cph.chain_id = hc.chain_id
LEFT JOIN chain_property_hierarchies parent ON cph.parent_property_id = parent.property_id
ORDER BY hc.chain_name, cph.hierarchy_level, cph.property_name;

-- Comments for documentation
COMMENT ON TABLE chain_property_hierarchies IS 'Detailed property hierarchy and relationships within hotel chains';
COMMENT ON TABLE chain_operations IS 'Chain-wide operations tracking and execution results';
COMMENT ON TABLE chain_analytics IS 'Historical analytics and KPIs for hotel chains';
COMMENT ON TABLE chain_config_inheritance IS 'Configuration inheritance tracking between chain and properties';
COMMENT ON TABLE chain_performance_benchmarks IS 'Performance benchmarks and targets for chain properties';
COMMENT ON TABLE chain_communications IS 'Chain-wide communications and announcements tracking';

COMMENT ON VIEW chain_overview IS 'High-level overview of hotel chains with key statistics';
COMMENT ON VIEW property_hierarchy_view IS 'Complete property hierarchy with parent-child relationships';

COMMENT ON FUNCTION get_property_hierarchy_path IS 'Get the full hierarchy path from property to chain root';
COMMENT ON FUNCTION get_descendant_properties IS 'Get all descendant properties of a given parent property';
COMMENT ON FUNCTION validate_chain_hierarchy IS 'Validate chain hierarchy integrity and report issues';
COMMENT ON FUNCTION calculate_chain_metrics IS 'Calculate key metrics for a hotel chain over a time period';