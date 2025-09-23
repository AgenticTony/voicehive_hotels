-- GDPR Compliance Database Schema
-- Tables for comprehensive GDPR compliance and audit readiness

-- GDPR Processing Records (Article 30 - Records of Processing Activities)
CREATE TABLE IF NOT EXISTS gdpr_processing_records (
    record_id VARCHAR(36) PRIMARY KEY,
    data_subject_id VARCHAR(255),
    processing_purpose TEXT NOT NULL,
    lawful_basis VARCHAR(50) NOT NULL,
    data_categories JSONB NOT NULL,
    recipients JSONB NOT NULL,
    retention_period INTEGER NOT NULL,
    processing_status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    consent_id VARCHAR(36),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    INDEX idx_gdpr_processing_data_subject (data_subject_id),
    INDEX idx_gdpr_processing_status (processing_status),
    INDEX idx_gdpr_processing_expires (expires_at),
    INDEX idx_gdpr_processing_lawful_basis (lawful_basis)
);

-- GDPR Erasure Requests (Article 17 - Right to Erasure)
CREATE TABLE IF NOT EXISTS gdpr_erasure_requests (
    request_id VARCHAR(36) PRIMARY KEY,
    data_subject_id VARCHAR(255) NOT NULL,
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    requested_by VARCHAR(255) NOT NULL,
    reason TEXT NOT NULL,
    scope JSONB NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    verification_token VARCHAR(255),
    verification_expires TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    INDEX idx_gdpr_erasure_data_subject (data_subject_id),
    INDEX idx_gdpr_erasure_status (status),
    INDEX idx_gdpr_erasure_requested_at (requested_at)
);

-- Data Retention Policies
CREATE TABLE IF NOT EXISTS data_retention_policies (
    policy_id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    data_category VARCHAR(100) NOT NULL,
    retention_period_days INTEGER NOT NULL,
    action VARCHAR(50) NOT NULL,
    lawful_basis VARCHAR(50) NOT NULL,
    storage_locations JSONB,
    archive_location VARCHAR(500),
    conditions JSONB,
    exceptions JSONB,
    enforcement_schedule VARCHAR(100) DEFAULT '0 2 * * *',
    batch_size INTEGER DEFAULT 1000,
    notify_before_days INTEGER DEFAULT 7,
    notification_recipients JSONB,
    regulatory_requirements JSONB,
    audit_required BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    INDEX idx_retention_policy_category (data_category),
    INDEX idx_retention_policy_action (action)
);

-- Data Retention Records
CREATE TABLE IF NOT EXISTS data_retention_records (
    record_id VARCHAR(36) PRIMARY KEY,
    data_subject_id VARCHAR(255),
    data_category VARCHAR(100) NOT NULL,
    policy_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_accessed TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    storage_location VARCHAR(500),
    file_paths JSONB,
    database_tables JSONB,
    size_bytes BIGINT,
    checksum VARCHAR(255),
    encryption_key_id VARCHAR(255),
    processing_started_at TIMESTAMP WITH TIME ZONE,
    processing_completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    FOREIGN KEY (policy_id) REFERENCES data_retention_policies(policy_id),
    INDEX idx_retention_record_subject (data_subject_id),
    INDEX idx_retention_record_policy (policy_id),
    INDEX idx_retention_record_expires (expires_at),
    INDEX idx_retention_record_status (status)
);

-- Compliance Monitoring Rules
CREATE TABLE IF NOT EXISTS compliance_monitoring_rules (
    rule_id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    framework VARCHAR(50) NOT NULL,
    requirement VARCHAR(100) NOT NULL,
    violation_type VARCHAR(100) NOT NULL,
    condition_query TEXT NOT NULL,
    threshold_value DECIMAL(10,2),
    threshold_operator VARCHAR(10) DEFAULT '>',
    check_interval_minutes INTEGER DEFAULT 60,
    enabled BOOLEAN DEFAULT true,
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',
    alert_channels JSONB,
    alert_recipients JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_checked TIMESTAMP WITH TIME ZONE,
    last_violation TIMESTAMP WITH TIME ZONE,
    tags JSONB,
    remediation_steps JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    INDEX idx_monitoring_rule_framework (framework),
    INDEX idx_monitoring_rule_enabled (enabled),
    INDEX idx_monitoring_rule_severity (severity)
);

-- Compliance Violations
CREATE TABLE IF NOT EXISTS compliance_violations (
    violation_id VARCHAR(36) PRIMARY KEY,
    rule_id VARCHAR(36) NOT NULL,
    violation_type VARCHAR(100) NOT NULL,
    framework VARCHAR(50) NOT NULL,
    requirement VARCHAR(100) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    severity VARCHAR(20) NOT NULL,
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    detection_query TEXT,
    detection_result JSONB,
    threshold_exceeded DECIMAL(10,2),
    affected_resources JSONB,
    data_subjects_affected JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    assigned_to VARCHAR(255),
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution_notes TEXT,
    risk_score DECIMAL(3,1) DEFAULT 0.0,
    business_impact VARCHAR(20) DEFAULT 'medium',
    regulatory_impact VARCHAR(20) DEFAULT 'medium',
    remediation_steps JSONB,
    remediation_deadline TIMESTAMP WITH TIME ZONE,
    escalation_level INTEGER DEFAULT 0,
    notifications_sent JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    FOREIGN KEY (rule_id) REFERENCES compliance_monitoring_rules(rule_id),
    INDEX idx_violation_rule (rule_id),
    INDEX idx_violation_framework (framework),
    INDEX idx_violation_status (status),
    INDEX idx_violation_severity (severity),
    INDEX idx_violation_detected (detected_at)
);

-- Compliance Evidence Items
CREATE TABLE IF NOT EXISTS compliance_evidence_items (
    evidence_id VARCHAR(36) PRIMARY KEY,
    evidence_type VARCHAR(100) NOT NULL,
    framework VARCHAR(50) NOT NULL,
    requirement VARCHAR(100) NOT NULL,
    title VARCHAR(500) NOT NULL,
    description TEXT,
    file_path VARCHAR(1000),
    content TEXT,
    metadata JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    collected_at TIMESTAMP WITH TIME ZONE,
    validated_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    source_system VARCHAR(255),
    source_query TEXT,
    collection_method VARCHAR(100) DEFAULT 'manual',
    checksum VARCHAR(255),
    digital_signature VARCHAR(500),
    validator VARCHAR(255),
    validation_notes TEXT,
    control_objectives JSONB,
    risk_level VARCHAR(20) DEFAULT 'medium',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    INDEX idx_evidence_framework (framework),
    INDEX idx_evidence_type (evidence_type),
    INDEX idx_evidence_status (status),
    INDEX idx_evidence_expires (expires_at)
);

-- Audit Trail Gaps
CREATE TABLE IF NOT EXISTS audit_trail_gaps (
    gap_id VARCHAR(36) PRIMARY KEY,
    gap_type VARCHAR(100) NOT NULL,
    category VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    severity VARCHAR(20) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    duration_minutes INTEGER NOT NULL,
    affected_systems JSONB,
    affected_users JSONB,
    expected_event_count INTEGER,
    actual_event_count INTEGER,
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    detection_method VARCHAR(100) DEFAULT 'automated',
    investigated BOOLEAN DEFAULT false,
    investigation_notes TEXT,
    root_cause TEXT,
    resolved BOOLEAN DEFAULT false,
    resolution_action TEXT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    
    INDEX idx_audit_gap_type (gap_type),
    INDEX idx_audit_gap_category (category),
    INDEX idx_audit_gap_severity (severity),
    INDEX idx_audit_gap_detected (detected_at),
    INDEX idx_audit_gap_resolved (resolved)
);

-- Data Classification Results
CREATE TABLE IF NOT EXISTS data_classification_results (
    content_id VARCHAR(36) PRIMARY KEY,
    content_type VARCHAR(100) NOT NULL,
    analyzed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    overall_sensitivity VARCHAR(50) NOT NULL,
    overall_classification VARCHAR(100) NOT NULL,
    pii_count INTEGER DEFAULT 0,
    confidence_score DECIMAL(5,2) DEFAULT 0.0,
    processing_time_ms INTEGER DEFAULT 0,
    recommended_retention_days INTEGER DEFAULT 365,
    recommended_access_controls JSONB,
    compliance_requirements JSONB,
    analyzer_version VARCHAR(50) DEFAULT '1.0',
    model_versions JSONB,
    
    INDEX idx_classification_type (content_type),
    INDEX idx_classification_sensitivity (overall_sensitivity),
    INDEX idx_classification_analyzed (analyzed_at)
);

-- PII Detections
CREATE TABLE IF NOT EXISTS pii_detections (
    detection_id VARCHAR(36) PRIMARY KEY,
    content_id VARCHAR(36) NOT NULL,
    pii_type VARCHAR(100) NOT NULL,
    value_hash VARCHAR(255), -- Hashed value for privacy
    confidence DECIMAL(5,2) NOT NULL,
    start_position INTEGER NOT NULL,
    end_position INTEGER NOT NULL,
    context VARCHAR(500),
    detection_method VARCHAR(100) NOT NULL,
    sensitivity_level VARCHAR(50) NOT NULL,
    data_classification VARCHAR(100) NOT NULL,
    recommended_action VARCHAR(50) NOT NULL,
    retention_period INTEGER,
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    detector_version VARCHAR(50) DEFAULT '1.0',
    
    FOREIGN KEY (content_id) REFERENCES data_classification_results(content_id),
    INDEX idx_pii_content (content_id),
    INDEX idx_pii_type (pii_type),
    INDEX idx_pii_sensitivity (sensitivity_level),
    INDEX idx_pii_detected (detected_at)
);

-- Create views for compliance reporting
CREATE OR REPLACE VIEW compliance_dashboard_summary AS
SELECT 
    'gdpr_processing' as metric_type,
    COUNT(*) as total_count,
    COUNT(CASE WHEN processing_status = 'active' THEN 1 END) as active_count,
    COUNT(CASE WHEN expires_at < NOW() AND processing_status = 'active' THEN 1 END) as expired_count
FROM gdpr_processing_records
UNION ALL
SELECT 
    'erasure_requests' as metric_type,
    COUNT(*) as total_count,
    COUNT(CASE WHEN status = 'pending' THEN 1 END) as active_count,
    COUNT(CASE WHEN requested_at < NOW() - INTERVAL '30 days' AND status = 'pending' THEN 1 END) as expired_count
FROM gdpr_erasure_requests
UNION ALL
SELECT 
    'compliance_violations' as metric_type,
    COUNT(*) as total_count,
    COUNT(CASE WHEN status = 'open' THEN 1 END) as active_count,
    COUNT(CASE WHEN severity = 'critical' AND status = 'open' THEN 1 END) as expired_count
FROM compliance_violations;

-- Create indexes for performance
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_logs_gdpr_search 
ON audit_logs (timestamp, event_type, data_subject_id) 
WHERE data_subject_id IS NOT NULL;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_logs_retention_search 
ON audit_logs (timestamp, resource_type, action) 
WHERE action IN ('create', 'update', 'delete');

-- Add triggers for automatic timestamp updates
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply update triggers to all tables with updated_at columns
DO $$
DECLARE
    table_name text;
    tables_with_updated_at text[] := ARRAY[
        'gdpr_processing_records',
        'gdpr_erasure_requests', 
        'data_retention_policies',
        'data_retention_records',
        'compliance_monitoring_rules',
        'compliance_violations',
        'compliance_evidence_items'
    ];
BEGIN
    FOREACH table_name IN ARRAY tables_with_updated_at
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS update_%s_updated_at ON %s;
            CREATE TRIGGER update_%s_updated_at 
                BEFORE UPDATE ON %s 
                FOR EACH ROW 
                EXECUTE FUNCTION update_updated_at_column();
        ', table_name, table_name, table_name, table_name);
    END LOOP;
END $$;