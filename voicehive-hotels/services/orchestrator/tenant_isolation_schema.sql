-- Enhanced Multi-Tenant Database Schema for VoiceHive Hotels
-- Provides enterprise-grade tenant isolation with proper constraints and audit trails

-- Tenant metadata and configuration table
CREATE TABLE IF NOT EXISTS tenant_metadata (
    tenant_id VARCHAR(100) PRIMARY KEY,
    tenant_name VARCHAR(255) NOT NULL,
    organization_name VARCHAR(255) NOT NULL,
    tenant_tier VARCHAR(50) NOT NULL DEFAULT 'starter',
    tenant_status VARCHAR(50) NOT NULL DEFAULT 'active',
    contact_email VARCHAR(255) NOT NULL,
    contact_phone VARCHAR(50),
    billing_contact VARCHAR(255),

    -- Subscription management
    subscription_started TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    subscription_expires TIMESTAMP WITH TIME ZONE,
    trial_ends TIMESTAMP WITH TIME ZONE,

    -- JSON configuration (full tenant metadata)
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) NOT NULL DEFAULT 'system',

    -- Constraints
    CONSTRAINT valid_tenant_tier CHECK (tenant_tier IN ('starter', 'professional', 'enterprise', 'custom')),
    CONSTRAINT valid_tenant_status CHECK (tenant_status IN ('active', 'suspended', 'deactivated', 'trial', 'pending_activation')),
    CONSTRAINT valid_contact_email CHECK (contact_email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

-- Indexes for tenant metadata
CREATE INDEX IF NOT EXISTS idx_tenant_metadata_status ON tenant_metadata(tenant_status);
CREATE INDEX IF NOT EXISTS idx_tenant_metadata_tier ON tenant_metadata(tenant_tier);
CREATE INDEX IF NOT EXISTS idx_tenant_metadata_organization ON tenant_metadata(organization_name);
CREATE INDEX IF NOT EXISTS idx_tenant_metadata_created_at ON tenant_metadata(created_at);

-- Hotel chain hierarchy table
CREATE TABLE IF NOT EXISTS hotel_chains (
    chain_id VARCHAR(100) PRIMARY KEY,
    chain_name VARCHAR(255) NOT NULL UNIQUE,
    headquarters_tenant_id VARCHAR(100) NOT NULL,
    chain_description TEXT,

    -- Chain configuration
    shared_configurations JSONB DEFAULT '[]',
    chain_settings JSONB DEFAULT '{}',

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_chain_headquarters FOREIGN KEY (headquarters_tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE
);

-- Property relationships within chains
CREATE TABLE IF NOT EXISTS chain_properties (
    property_id VARCHAR(100) PRIMARY KEY,
    chain_id VARCHAR(100) NOT NULL,
    parent_property_id VARCHAR(100),
    property_level INTEGER NOT NULL DEFAULT 2, -- 0=chain HQ, 1=region, 2=property
    property_name VARCHAR(255) NOT NULL,

    -- Configuration inheritance
    inherits_config_from_parent BOOLEAN DEFAULT TRUE,
    config_overrides JSONB DEFAULT '{}',

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_property_chain FOREIGN KEY (chain_id) REFERENCES hotel_chains(chain_id) ON DELETE CASCADE,
    CONSTRAINT fk_property_parent FOREIGN KEY (parent_property_id) REFERENCES chain_properties(property_id) ON DELETE SET NULL,
    CONSTRAINT fk_property_tenant FOREIGN KEY (property_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_property_level CHECK (property_level >= 0 AND property_level <= 3),
    CONSTRAINT no_self_parent CHECK (property_id != parent_property_id)
);

-- Indexes for chain properties
CREATE INDEX IF NOT EXISTS idx_chain_properties_chain_id ON chain_properties(chain_id);
CREATE INDEX IF NOT EXISTS idx_chain_properties_parent ON chain_properties(parent_property_id);
CREATE INDEX IF NOT EXISTS idx_chain_properties_level ON chain_properties(property_level);

-- Resource usage tracking table (with proper tenant isolation)
CREATE TABLE IF NOT EXISTS tenant_resource_usage (
    usage_id VARCHAR(100) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id VARCHAR(100) NOT NULL,

    -- Usage period
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    period_type VARCHAR(20) NOT NULL DEFAULT 'daily', -- daily, monthly, annual

    -- Resource counters
    calls_count INTEGER NOT NULL DEFAULT 0,
    calls_duration_minutes NUMERIC(10,2) NOT NULL DEFAULT 0,
    api_requests_count INTEGER NOT NULL DEFAULT 0,
    storage_used_mb NUMERIC(10,2) NOT NULL DEFAULT 0,
    ai_tokens_used INTEGER NOT NULL DEFAULT 0,
    webhook_deliveries INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,

    -- Billing and cost
    estimated_cost NUMERIC(10,2) DEFAULT 0,
    currency VARCHAR(3) DEFAULT 'USD',

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_usage_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_period_type CHECK (period_type IN ('daily', 'weekly', 'monthly', 'annual')),
    CONSTRAINT valid_period_order CHECK (period_start < period_end),
    CONSTRAINT non_negative_counters CHECK (
        calls_count >= 0 AND
        calls_duration_minutes >= 0 AND
        api_requests_count >= 0 AND
        storage_used_mb >= 0 AND
        ai_tokens_used >= 0 AND
        webhook_deliveries >= 0 AND
        error_count >= 0
    )
);

-- Indexes for resource usage
CREATE INDEX IF NOT EXISTS idx_tenant_usage_tenant_period ON tenant_resource_usage(tenant_id, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_tenant_usage_period_type ON tenant_resource_usage(period_type);
CREATE INDEX IF NOT EXISTS idx_tenant_usage_created_at ON tenant_resource_usage(created_at);

-- Unique constraint for period tracking per tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenant_usage_unique_period
ON tenant_resource_usage(tenant_id, period_start, period_type);

-- Enhanced GDPR compliance tables with tenant isolation
-- Update existing GDPR tables to include tenant_id for proper isolation

-- Drop and recreate GDPR processing records with tenant support
DROP TABLE IF EXISTS gdpr_processing_records;
CREATE TABLE gdpr_processing_records (
    record_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id VARCHAR(100) NOT NULL, -- CRITICAL: Add tenant isolation
    data_subject_id VARCHAR(255) NOT NULL,
    processing_purpose TEXT NOT NULL,
    legal_basis VARCHAR(100) NOT NULL,
    data_categories TEXT[] NOT NULL,
    recipient_categories TEXT[],
    retention_period_days INTEGER,

    -- Processing details
    processing_start_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    processing_end_date TIMESTAMP WITH TIME ZONE,
    automated_decision_making BOOLEAN DEFAULT FALSE,
    profiling_involved BOOLEAN DEFAULT FALSE,

    -- Cross-border transfers
    third_country_transfers JSONB DEFAULT '[]',
    adequacy_decision BOOLEAN DEFAULT FALSE,
    safeguards_applied TEXT,

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) NOT NULL,

    -- Foreign key constraints
    CONSTRAINT fk_gdpr_record_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_legal_basis CHECK (legal_basis IN ('consent', 'contract', 'legal_obligation', 'vital_interests', 'public_task', 'legitimate_interests')),
    CONSTRAINT valid_retention_period CHECK (retention_period_days > 0)
);

-- Indexes for GDPR processing records
CREATE INDEX IF NOT EXISTS idx_gdpr_records_tenant_subject ON gdpr_processing_records(tenant_id, data_subject_id);
CREATE INDEX IF NOT EXISTS idx_gdpr_records_purpose ON gdpr_processing_records(processing_purpose);
CREATE INDEX IF NOT EXISTS idx_gdpr_records_legal_basis ON gdpr_processing_records(legal_basis);

-- Enhanced GDPR erasure requests with tenant isolation
DROP TABLE IF EXISTS gdpr_erasure_requests;
CREATE TABLE gdpr_erasure_requests (
    request_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id VARCHAR(100) NOT NULL, -- CRITICAL: Add tenant isolation
    data_subject_id VARCHAR(255) NOT NULL,
    requester_email VARCHAR(255) NOT NULL,

    -- Request details
    request_type VARCHAR(50) NOT NULL DEFAULT 'erasure',
    request_reason TEXT,
    request_scope TEXT[] NOT NULL, -- which data categories to erase

    -- Processing status
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',

    -- Verification
    identity_verified BOOLEAN DEFAULT FALSE,
    verification_method VARCHAR(100),
    verification_date TIMESTAMP WITH TIME ZONE,

    -- Processing details
    request_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    acknowledgment_date TIMESTAMP WITH TIME ZONE,
    completion_date TIMESTAMP WITH TIME ZONE,
    response_sent_date TIMESTAMP WITH TIME ZONE,

    -- Compliance timeline (30 days max for GDPR)
    legal_deadline TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() + INTERVAL '30 days'),
    extension_granted BOOLEAN DEFAULT FALSE,
    extension_reason TEXT,

    -- Execution details
    data_locations TEXT[], -- where data was found
    erasure_method VARCHAR(100), -- soft delete, anonymization, etc.
    certification_required BOOLEAN DEFAULT FALSE,
    certification_provided BOOLEAN DEFAULT FALSE,

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    processed_by VARCHAR(100),

    -- Foreign key constraints
    CONSTRAINT fk_gdpr_erasure_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_request_type CHECK (request_type IN ('erasure', 'rectification', 'portability', 'restriction')),
    CONSTRAINT valid_status CHECK (status IN ('pending', 'in_progress', 'completed', 'rejected', 'expired')),
    CONSTRAINT valid_priority CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    CONSTRAINT completion_after_request CHECK (completion_date IS NULL OR completion_date >= request_date)
);

-- Indexes for GDPR erasure requests
CREATE INDEX IF NOT EXISTS idx_gdpr_erasure_tenant_subject ON gdpr_erasure_requests(tenant_id, data_subject_id);
CREATE INDEX IF NOT EXISTS idx_gdpr_erasure_status ON gdpr_erasure_requests(status);
CREATE INDEX IF NOT EXISTS idx_gdpr_erasure_deadline ON gdpr_erasure_requests(legal_deadline);
CREATE INDEX IF NOT EXISTS idx_gdpr_erasure_priority ON gdpr_erasure_requests(priority);

-- Enhanced data retention policies with tenant support
DROP TABLE IF EXISTS data_retention_policies;
CREATE TABLE data_retention_policies (
    policy_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id VARCHAR(100), -- NULL for global policies, specific tenant_id for tenant-specific

    -- Policy details
    policy_name VARCHAR(255) NOT NULL,
    data_category VARCHAR(100) NOT NULL,
    retention_period_days INTEGER NOT NULL,

    -- Policy rules
    applies_to_new_data BOOLEAN DEFAULT TRUE,
    applies_to_existing_data BOOLEAN DEFAULT FALSE,
    auto_delete_enabled BOOLEAN DEFAULT TRUE,
    requires_manual_review BOOLEAN DEFAULT FALSE,

    -- Legal and compliance
    legal_basis VARCHAR(255),
    compliance_framework VARCHAR(100), -- GDPR, CCPA, HIPAA, etc.
    jurisdictions TEXT[], -- applicable jurisdictions

    -- Policy lifecycle
    effective_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expiry_date TIMESTAMP WITH TIME ZONE,
    policy_status VARCHAR(50) NOT NULL DEFAULT 'active',

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) NOT NULL,
    approved_by VARCHAR(100),
    approval_date TIMESTAMP WITH TIME ZONE,

    -- Foreign key constraints (nullable for global policies)
    CONSTRAINT fk_retention_policy_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_retention_period CHECK (retention_period_days > 0),
    CONSTRAINT valid_policy_status CHECK (policy_status IN ('draft', 'active', 'suspended', 'expired')),
    CONSTRAINT valid_compliance_framework CHECK (compliance_framework IN ('GDPR', 'CCPA', 'HIPAA', 'SOX', 'PCI_DSS', 'CUSTOM'))
);

-- Indexes for retention policies
CREATE INDEX IF NOT EXISTS idx_retention_policies_tenant ON data_retention_policies(tenant_id);
CREATE INDEX IF NOT EXISTS idx_retention_policies_category ON data_retention_policies(data_category);
CREATE INDEX IF NOT EXISTS idx_retention_policies_status ON data_retention_policies(policy_status);

-- Tenant-specific rate limiting configurations
CREATE TABLE IF NOT EXISTS tenant_rate_limits (
    limit_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id VARCHAR(100) NOT NULL,

    -- Rate limit definition
    endpoint_pattern VARCHAR(255) NOT NULL, -- regex pattern for endpoints
    limit_type VARCHAR(50) NOT NULL, -- per_minute, per_hour, per_day
    limit_value INTEGER NOT NULL,
    burst_limit INTEGER DEFAULT NULL,

    -- Configuration
    algorithm VARCHAR(50) NOT NULL DEFAULT 'sliding_window',
    reset_time_hours INTEGER DEFAULT 0, -- 0 for continuous, >0 for daily reset

    -- Override settings
    override_global_limits BOOLEAN DEFAULT FALSE,
    priority INTEGER DEFAULT 100, -- higher priority = evaluated first

    -- Conditional rules
    applies_to_roles TEXT[], -- which user roles this applies to
    exclude_endpoints TEXT[], -- endpoints to exclude from this rule

    -- Status and lifecycle
    is_active BOOLEAN DEFAULT TRUE,
    effective_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expiry_date TIMESTAMP WITH TIME ZONE,

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100) NOT NULL,

    -- Foreign key constraints
    CONSTRAINT fk_rate_limit_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_limit_type CHECK (limit_type IN ('per_minute', 'per_hour', 'per_day', 'per_month')),
    CONSTRAINT valid_algorithm CHECK (algorithm IN ('sliding_window', 'fixed_window', 'token_bucket')),
    CONSTRAINT positive_limits CHECK (limit_value > 0 AND (burst_limit IS NULL OR burst_limit > 0))
);

-- Indexes for rate limits
CREATE INDEX IF NOT EXISTS idx_rate_limits_tenant ON tenant_rate_limits(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rate_limits_pattern ON tenant_rate_limits(endpoint_pattern);
CREATE INDEX IF NOT EXISTS idx_rate_limits_active ON tenant_rate_limits(is_active);
CREATE INDEX IF NOT EXISTS idx_rate_limits_priority ON tenant_rate_limits(priority DESC);

-- Tenant configuration history for audit trail
CREATE TABLE IF NOT EXISTS tenant_config_history (
    history_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id VARCHAR(100) NOT NULL,

    -- Change details
    change_type VARCHAR(50) NOT NULL, -- create, update, delete
    config_section VARCHAR(100), -- which section was changed
    previous_value JSONB,
    new_value JSONB,
    change_description TEXT,

    -- Change metadata
    changed_by VARCHAR(100) NOT NULL,
    change_reason VARCHAR(255),
    change_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Rollback support
    can_rollback BOOLEAN DEFAULT TRUE,
    rollback_deadline TIMESTAMP WITH TIME ZONE,

    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Foreign key constraints
    CONSTRAINT fk_config_history_tenant FOREIGN KEY (tenant_id) REFERENCES tenant_metadata(tenant_id) ON DELETE CASCADE,

    -- Constraints
    CONSTRAINT valid_change_type CHECK (change_type IN ('create', 'update', 'delete', 'rollback'))
);

-- Indexes for configuration history
CREATE INDEX IF NOT EXISTS idx_config_history_tenant_date ON tenant_config_history(tenant_id, change_date DESC);
CREATE INDEX IF NOT EXISTS idx_config_history_changed_by ON tenant_config_history(changed_by);
CREATE INDEX IF NOT EXISTS idx_config_history_section ON tenant_config_history(config_section);

-- Row Level Security (RLS) for PostgreSQL
-- Enable RLS on all tenant-aware tables

ALTER TABLE tenant_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_resource_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE gdpr_processing_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE gdpr_erasure_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_config_history ENABLE ROW LEVEL SECURITY;

-- RLS policies for tenant isolation
-- These policies ensure users can only access data for their authorized tenants

-- Tenant metadata access policy
CREATE POLICY tenant_metadata_isolation ON tenant_metadata
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Resource usage access policy
CREATE POLICY tenant_usage_isolation ON tenant_resource_usage
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- GDPR processing records access policy
CREATE POLICY gdpr_records_isolation ON gdpr_processing_records
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- GDPR erasure requests access policy
CREATE POLICY gdpr_erasure_isolation ON gdpr_erasure_requests
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Rate limits access policy
CREATE POLICY rate_limits_isolation ON tenant_rate_limits
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Configuration history access policy
CREATE POLICY config_history_isolation ON tenant_config_history
    FOR ALL
    TO application_role
    USING (
        tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );

-- Create application role for RLS
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'application_role') THEN
        CREATE ROLE application_role;
    END IF;
END
$$;

-- Grant necessary permissions to application role
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO application_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO application_role;

-- Functions for tenant context management
CREATE OR REPLACE FUNCTION set_tenant_context(user_tenant_ids TEXT, user_role TEXT)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.user_tenant_ids', user_tenant_ids, true);
    PERFORM set_config('app.user_role', user_role, true);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to validate tenant access
CREATE OR REPLACE FUNCTION validate_tenant_access(check_tenant_id TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN (
        check_tenant_id = ANY(string_to_array(current_setting('app.user_tenant_ids', true), ','))
        OR current_setting('app.user_role', true) = 'system_admin'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Insert default global retention policies
INSERT INTO data_retention_policies (
    tenant_id, policy_name, data_category, retention_period_days,
    legal_basis, compliance_framework, created_by
) VALUES
(NULL, 'Global Call Recordings Retention', 'call_recordings', 90, 'Legal compliance and quality assurance', 'GDPR', 'system'),
(NULL, 'Global Personal Data Retention', 'personal_data', 730, 'Customer relationship management', 'GDPR', 'system'),
(NULL, 'Global Analytics Data Retention', 'analytics', 1095, 'Business intelligence and service improvement', 'GDPR', 'system'),
(NULL, 'Global Log Data Retention', 'logs', 365, 'Security monitoring and system maintenance', 'GDPR', 'system')
ON CONFLICT DO NOTHING;

-- Create indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_tenant_metadata_metadata_gin ON tenant_metadata USING GIN (metadata);
CREATE INDEX IF NOT EXISTS idx_chain_properties_config_gin ON chain_properties USING GIN (config_overrides);
CREATE INDEX IF NOT EXISTS idx_tenant_usage_period_partial ON tenant_resource_usage(tenant_id, period_start) WHERE period_type = 'daily';

-- Comments for documentation
COMMENT ON TABLE tenant_metadata IS 'Complete tenant metadata and configuration with enterprise features';
COMMENT ON TABLE hotel_chains IS 'Hotel chain hierarchy management for multi-property organizations';
COMMENT ON TABLE chain_properties IS 'Individual properties within hotel chains with inheritance support';
COMMENT ON TABLE tenant_resource_usage IS 'Resource usage tracking for quota enforcement and billing';
COMMENT ON TABLE gdpr_processing_records IS 'GDPR processing records with proper tenant isolation';
COMMENT ON TABLE gdpr_erasure_requests IS 'GDPR erasure requests with tenant-aware processing';
COMMENT ON TABLE data_retention_policies IS 'Data retention policies supporting tenant-specific and global rules';
COMMENT ON TABLE tenant_rate_limits IS 'Tenant-specific rate limiting configurations';
COMMENT ON TABLE tenant_config_history IS 'Audit trail for tenant configuration changes';

COMMENT ON FUNCTION set_tenant_context IS 'Set tenant context for RLS policies';
COMMENT ON FUNCTION validate_tenant_access IS 'Validate if current user has access to specified tenant';

-- Create a view for easy tenant overview
CREATE OR REPLACE VIEW tenant_overview AS
SELECT
    tm.tenant_id,
    tm.tenant_name,
    tm.organization_name,
    tm.tenant_tier,
    tm.tenant_status,
    tm.contact_email,
    tm.subscription_started,
    tm.subscription_expires,
    tm.trial_ends,

    -- Chain information
    hc.chain_name,
    cp.property_level,

    -- Current usage (latest daily record)
    tru.calls_count as daily_calls,
    tru.calls_duration_minutes as daily_duration,
    tru.storage_used_mb,
    tru.estimated_cost as daily_cost,

    -- Account health
    CASE
        WHEN tm.tenant_status = 'trial' AND tm.trial_ends < NOW() THEN 'Trial Expired'
        WHEN tm.subscription_expires IS NOT NULL AND tm.subscription_expires < NOW() THEN 'Subscription Expired'
        WHEN tm.tenant_status = 'suspended' THEN 'Suspended'
        WHEN tm.tenant_status = 'deactivated' THEN 'Deactivated'
        ELSE 'Active'
    END as account_health,

    tm.created_at,
    tm.updated_at

FROM tenant_metadata tm
LEFT JOIN chain_properties cp ON tm.tenant_id = cp.property_id
LEFT JOIN hotel_chains hc ON cp.chain_id = hc.chain_id
LEFT JOIN LATERAL (
    SELECT calls_count, calls_duration_minutes, storage_used_mb, estimated_cost
    FROM tenant_resource_usage
    WHERE tenant_id = tm.tenant_id
      AND period_type = 'daily'
    ORDER BY period_start DESC
    LIMIT 1
) tru ON true
ORDER BY tm.tenant_name;

COMMENT ON VIEW tenant_overview IS 'Comprehensive tenant overview with usage and chain information';