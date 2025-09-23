"""
Comprehensive Test Suite for Compliance Integration System
Tests all compliance components and their integration
"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import json
import uuid

# Import compliance components
from compliance_integration import ComplianceIntegrationManager, ComplianceStatus
from gdpr_compliance_manager import GDPRComplianceManager, GDPRLawfulBasis, DataSubjectRight
from data_retention_enforcer import DataRetentionEnforcer, RetentionAction, DataCategory
from data_classification_system import DataClassificationEngine, DataSensitivityLevel
from compliance_evidence_collector import ComplianceEvidenceCollector, ComplianceFramework
from compliance_monitoring_system import ComplianceMonitoringSystem, ViolationType, ViolationSeverity
from audit_trail_verifier import AuditTrailVerifier, AuditIntegrityStatus


class TestComplianceIntegration:
    """Test compliance integration functionality"""
    
    @pytest.fixture
    async def mock_db_session(self):
        """Mock database session"""
        mock_db = AsyncMock()
        mock_db.execute.return_value.fetchall.return_value = []
        mock_db.execute.return_value.scalar.return_value = 0
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        return mock_db
    
    @pytest.fixture
    async def compliance_manager(self, mock_db_session):
        """Create compliance integration manager"""
        return ComplianceIntegrationManager(mock_db_session)
    
    @pytest.mark.asyncio
    async def test_full_compliance_assessment(self, compliance_manager):
        """Test full compliance assessment"""
        
        # Mock component responses
        with patch.object(compliance_manager.gdpr_manager, 'generate_compliance_report') as mock_gdpr:
            mock_gdpr.return_value = {
                "compliance_status": "compliant",
                "summary": {
                    "total_data_subjects": 100,
                    "active_processing_records": 50,
                    "pending_erasure_requests": 0,
                    "compliance_violations": 0
                }
            }
            
            with patch.object(compliance_manager.retention_enforcer, 'get_retention_statistics') as mock_retention:
                mock_retention.return_value = {
                    "total_records": 1000,
                    "expired_records": 0,
                    "expiring_soon": 5,
                    "total_policies": 10
                }
                
                with patch.object(compliance_manager.audit_verifier, 'verify_audit_trail_completeness') as mock_audit:
                    mock_audit_result = MagicMock()
                    mock_audit_result.overall_status = AuditIntegrityStatus.INTACT
                    mock_audit_result.calculate_overall_score.return_value = 95.0
                    mock_audit_result.completeness_score = 95.0
                    mock_audit_result.integrity_score = 95.0
                    mock_audit_result.compliance_score = 95.0
                    mock_audit.return_value = mock_audit_result
                    
                    with patch.object(compliance_manager.evidence_collector, 'generate_compliance_report') as mock_evidence:
                        mock_evidence_result = MagicMock()
                        mock_evidence_result.overall_compliance_score = 90.0
                        mock_evidence_result.total_evidence_items = 25
                        mock_evidence_result.gaps_identified = []
                        mock_evidence.return_value = mock_evidence_result
                        
                        with patch.object(compliance_manager.monitoring_system, 'generate_monitoring_dashboard') as mock_monitoring:
                            mock_dashboard = MagicMock()
                            mock_dashboard.open_violations = 2
                            mock_dashboard.critical_violations = 0
                            mock_dashboard.total_violations = 5
                            mock_monitoring.return_value = mock_dashboard
                            
                            # Execute assessment
                            status = await compliance_manager.perform_full_compliance_assessment()
                            
                            # Verify results
                            assert isinstance(status, ComplianceStatus)
                            assert status.overall_score > 80.0
                            assert status.gdpr_compliant is True
                            assert status.data_retention_compliant is True
                            assert status.audit_trail_compliant is True
                            assert status.violations_count == 2
                            assert status.critical_violations == 0
                            assert len(status.recommendations) >= 0
    
    @pytest.mark.asyncio
    async def test_right_to_erasure_execution(self, compliance_manager):
        """Test comprehensive right to erasure execution"""
        
        data_subject_id = "test-subject-123"
        requested_by = "test@example.com"
        reason = "User requested account deletion"
        scope = ["call_recordings", "transcripts", "metadata"]
        
        # Mock GDPR manager responses
        mock_request = MagicMock()
        mock_request.request_id = str(uuid.uuid4())
        
        with patch.object(compliance_manager.gdpr_manager, 'submit_erasure_request') as mock_submit:
            mock_submit.return_value = mock_request
            
            with patch.object(compliance_manager.gdpr_manager, 'execute_erasure_request') as mock_execute:
                mock_execute.return_value = {
                    "request_id": mock_request.request_id,
                    "status": "success",
                    "results": {
                        "call_recordings": {"records_affected": 10, "files_deleted": ["file1.wav"]},
                        "transcripts": {"records_affected": 10, "files_deleted": []},
                        "metadata": {"records_affected": 5, "files_deleted": []}
                    }
                }
                
                # Execute erasure
                result = await compliance_manager.execute_right_to_erasure(
                    data_subject_id, requested_by, reason, scope
                )
                
                # Verify results
                assert result["status"] == "completed"
                assert result["data_subject_id"] == data_subject_id
                assert result["scope"] == scope
                assert "classification_results" in result
                assert "erasure_results" in result
                assert "verification_results" in result
                assert "certificate" in result
    
    @pytest.mark.asyncio
    async def test_data_retention_enforcement(self, compliance_manager):
        """Test comprehensive data retention enforcement"""
        
        # Mock retention enforcer response
        with patch.object(compliance_manager.retention_enforcer, 'enforce_retention_policies') as mock_enforce:
            mock_enforce.return_value = {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "records_processed": 100,
                "actions_taken": {
                    "deleted": 10,
                    "archived": 5,
                    "anonymized": 2,
                    "quarantined": 0
                },
                "errors": [],
                "status": "success"
            }
            
            with patch.object(compliance_manager.audit_verifier, 'verify_audit_trail_completeness') as mock_audit:
                mock_audit_result = MagicMock()
                mock_audit_result.overall_status = AuditIntegrityStatus.INTACT
                mock_audit_result.completeness_score = 98.0
                mock_audit.return_value = mock_audit_result
                
                # Execute retention enforcement
                result = await compliance_manager.enforce_data_retention_policies()
                
                # Verify results
                assert result["status"] == "success"
                assert result["records_processed"] == 100
                assert result["actions_taken"]["deleted"] == 10
                assert "audit_verification" in result
                assert result["audit_verification"]["status"] == "intact"
                assert "compliance_report" in result
    
    @pytest.mark.asyncio
    async def test_compliance_evidence_collection(self, compliance_manager):
        """Test comprehensive compliance evidence collection"""
        
        framework = ComplianceFramework.GDPR
        
        # Mock evidence collector responses
        with patch.object(compliance_manager.evidence_collector, 'collect_evidence_for_framework') as mock_collect:
            mock_collect.return_value = {
                "framework": framework.value,
                "evidence_collected": 15,
                "evidence_validated": 14,
                "errors": []
            }
            
            with patch.object(compliance_manager.evidence_collector, 'validate_evidence_integrity') as mock_validate:
                mock_validate.return_value = {
                    "total_items": 15,
                    "valid_items": 14,
                    "invalid_items": 1,
                    "integrity_issues": []
                }
                
                with patch.object(compliance_manager.evidence_collector, 'generate_compliance_report') as mock_report:
                    mock_report_result = MagicMock()
                    mock_report_result.report_id = str(uuid.uuid4())
                    mock_report_result.overall_compliance_score = 92.0
                    mock_report_result.total_evidence_items = 15
                    mock_report_result.gaps_identified = []
                    mock_report.return_value = mock_report_result
                    
                    with patch.object(compliance_manager.audit_verifier, 'verify_audit_trail_completeness') as mock_audit:
                        mock_audit_result = MagicMock()
                        mock_audit_result.overall_status = AuditIntegrityStatus.INTACT
                        mock_audit_result.completeness_score = 95.0
                        mock_audit.return_value = mock_audit_result
                        
                        # Execute evidence collection
                        result = await compliance_manager.collect_compliance_evidence(framework)
                        
                        # Verify results
                        assert result["framework"] == framework.value
                        assert result["collection_results"]["evidence_collected"] == 15
                        assert result["validation_results"]["valid_items"] == 14
                        assert result["compliance_report"]["overall_score"] == 92.0
                        assert result["audit_verification"]["status"] == "intact"
    
    @pytest.mark.asyncio
    async def test_comprehensive_compliance_report(self, compliance_manager):
        """Test comprehensive compliance report generation"""
        
        # Set up mock compliance status
        compliance_manager.compliance_status = ComplianceStatus(
            overall_score=88.5,
            gdpr_compliant=True,
            data_retention_compliant=True,
            audit_trail_compliant=True,
            evidence_complete=True,
            violations_count=3,
            critical_violations=0,
            last_assessment=datetime.now(timezone.utc),
            next_assessment=datetime.now(timezone.utc) + timedelta(days=30),
            recommendations=["Review open violations", "Update retention policies"]
        )
        
        compliance_manager.last_full_assessment = datetime.now(timezone.utc)
        
        # Mock component reports
        with patch.object(compliance_manager.gdpr_manager, 'generate_compliance_report') as mock_gdpr:
            mock_gdpr.return_value = {
                "compliance_status": "compliant",
                "summary": {
                    "total_data_subjects": 150,
                    "active_processing_records": 75,
                    "pending_erasure_requests": 1
                }
            }
            
            with patch.object(compliance_manager.retention_enforcer, 'get_retention_statistics') as mock_retention:
                mock_retention.return_value = {
                    "total_records": 2000,
                    "expired_records": 5,
                    "expiring_soon": 20,
                    "total_policies": 12
                }
                
                with patch.object(compliance_manager.monitoring_system, 'generate_monitoring_dashboard') as mock_monitoring:
                    mock_dashboard = MagicMock()
                    mock_dashboard.total_violations = 8
                    mock_dashboard.open_violations = 3
                    mock_dashboard.critical_violations = 0
                    mock_dashboard.active_rules = 25
                    mock_monitoring.return_value = mock_dashboard
                    
                    with patch.object(compliance_manager.audit_verifier, 'generate_audit_trail_report') as mock_audit:
                        mock_audit_result = MagicMock()
                        mock_audit_result.overall_completeness_score = 92.0
                        mock_audit_result.overall_integrity_score = 89.0
                        mock_audit_result.total_gaps_found = 2
                        mock_audit_result.critical_gaps = 0
                        mock_audit.return_value = mock_audit_result
                        
                        with patch.object(compliance_manager.evidence_collector, 'generate_compliance_report') as mock_evidence:
                            mock_evidence_result = MagicMock()
                            mock_evidence_result.overall_compliance_score = 87.0
                            mock_evidence_result.total_evidence_items = 30
                            mock_evidence_result.gaps_identified = ["Missing policy document"]
                            mock_evidence.return_value = mock_evidence_result
                            
                            # Generate comprehensive report
                            report = await compliance_manager.generate_comprehensive_compliance_report()
                            
                            # Verify report structure
                            assert "report_id" in report
                            assert "generated_at" in report
                            assert "overall_compliance" in report
                            assert "gdpr_compliance" in report
                            assert "data_retention" in report
                            assert "monitoring" in report
                            assert "audit_trail" in report
                            assert "evidence" in report
                            assert "recommendations" in report
                            assert "executive_summary" in report
                            
                            # Verify specific values
                            assert report["overall_compliance"]["score"] == 88.5
                            assert report["gdpr_compliance"]["data_subjects"] == 150
                            assert report["monitoring"]["open_violations"] == 3
                            assert report["audit_trail"]["gaps_found"] == 2
                            assert len(report["recommendations"]) == 2


class TestGDPRComplianceManager:
    """Test GDPR compliance manager functionality"""
    
    @pytest.fixture
    async def mock_db_session(self):
        """Mock database session"""
        mock_db = AsyncMock()
        mock_db.execute.return_value.fetchall.return_value = []
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        return mock_db
    
    @pytest.fixture
    async def gdpr_manager(self, mock_db_session):
        """Create GDPR compliance manager"""
        return GDPRComplianceManager(mock_db_session)
    
    @pytest.mark.asyncio
    async def test_data_subject_registration(self, gdpr_manager):
        """Test data subject registration"""
        
        subject_id = "test-subject-456"
        email = "test@example.com"
        name = "Test User"
        
        # Register data subject
        data_subject = await gdpr_manager.register_data_subject(
            subject_id, email=email, name=name
        )
        
        # Verify registration
        assert data_subject.subject_id == subject_id
        assert data_subject.email == email
        assert data_subject.name == name
        assert data_subject.created_at is not None
    
    @pytest.mark.asyncio
    async def test_processing_record_creation(self, gdpr_manager):
        """Test processing record creation"""
        
        data_subject_id = "test-subject-789"
        processing_purpose = "Customer service call handling"
        lawful_basis = GDPRLawfulBasis.LEGITIMATE_INTERESTS
        data_categories = ["call_recordings", "transcripts"]
        recipients = ["customer_service_team"]
        retention_period = 365
        
        # Create processing record
        record = await gdpr_manager.create_processing_record(
            data_subject_id, processing_purpose, lawful_basis,
            data_categories, recipients, retention_period
        )
        
        # Verify record
        assert record.data_subject_id == data_subject_id
        assert record.processing_purpose == processing_purpose
        assert record.lawful_basis == lawful_basis
        assert record.data_categories == data_categories
        assert record.retention_period == retention_period
        assert record.record_id is not None
    
    @pytest.mark.asyncio
    async def test_erasure_request_submission(self, gdpr_manager):
        """Test erasure request submission"""
        
        data_subject_id = "test-subject-101"
        requested_by = "user@example.com"
        reason = "Account deletion request"
        scope = ["all_data"]
        
        # Submit erasure request
        request = await gdpr_manager.submit_erasure_request(
            data_subject_id, requested_by, reason, scope
        )
        
        # Verify request
        assert request.data_subject_id == data_subject_id
        assert request.requested_by == requested_by
        assert request.reason == reason
        assert request.scope == scope
        assert request.status == "pending"
        assert request.verification_token is not None


class TestDataRetentionEnforcer:
    """Test data retention enforcer functionality"""
    
    @pytest.fixture
    async def mock_db_session(self):
        """Mock database session"""
        mock_db = AsyncMock()
        mock_db.execute.return_value.fetchall.return_value = []
        mock_db.commit = AsyncMock()
        return mock_db
    
    @pytest.fixture
    async def retention_enforcer(self, mock_db_session):
        """Create data retention enforcer"""
        return DataRetentionEnforcer(mock_db_session)
    
    @pytest.mark.asyncio
    async def test_retention_policy_creation(self, retention_enforcer):
        """Test retention policy creation"""
        
        from data_retention_enforcer import RetentionPolicy
        
        policy = RetentionPolicy(
            policy_id=str(uuid.uuid4()),
            name="Call Recording Retention",
            description="Retain call recordings for 7 years",
            data_category=DataCategory.CALL_RECORDINGS,
            retention_period_days=2555,
            action=RetentionAction.DELETE,
            lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS,
            storage_locations=["s3://call-recordings/"]
        )
        
        # Create policy
        created_policy = await retention_enforcer.create_retention_policy(policy)
        
        # Verify policy
        assert created_policy.policy_id == policy.policy_id
        assert created_policy.name == policy.name
        assert created_policy.retention_period_days == 2555
        assert created_policy.action == RetentionAction.DELETE
    
    @pytest.mark.asyncio
    async def test_data_record_registration(self, retention_enforcer):
        """Test data record registration"""
        
        # First create a policy
        from data_retention_enforcer import RetentionPolicy
        
        policy = RetentionPolicy(
            policy_id=str(uuid.uuid4()),
            name="Test Policy",
            description="Test retention policy",
            data_category=DataCategory.CALL_RECORDINGS,
            retention_period_days=365,
            action=RetentionAction.DELETE,
            lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS,
            storage_locations=["local"]
        )
        
        await retention_enforcer.create_retention_policy(policy)
        
        # Register data record
        record = await retention_enforcer.register_data_record(
            record_id="test-record-123",
            data_category=DataCategory.CALL_RECORDINGS,
            policy_id=policy.policy_id,
            data_subject_id="test-subject-456",
            storage_location="s3://bucket/path/",
            file_paths=["recording1.wav", "recording2.wav"]
        )
        
        # Verify record
        assert record.record_id == "test-record-123"
        assert record.data_category == DataCategory.CALL_RECORDINGS
        assert record.policy_id == policy.policy_id
        assert len(record.file_paths) == 2


class TestComplianceMonitoringSystem:
    """Test compliance monitoring system functionality"""
    
    @pytest.fixture
    async def mock_db_session(self):
        """Mock database session"""
        mock_db = AsyncMock()
        mock_db.execute.return_value.fetchall.return_value = [(5,)]  # Mock violation count
        mock_db.commit = AsyncMock()
        return mock_db
    
    @pytest.fixture
    async def monitoring_system(self, mock_db_session):
        """Create compliance monitoring system"""
        return ComplianceMonitoringSystem(mock_db_session)
    
    @pytest.mark.asyncio
    async def test_monitoring_rule_creation(self, monitoring_system):
        """Test monitoring rule creation"""
        
        from compliance_monitoring_system import ComplianceRule, ComplianceRequirement
        
        rule = ComplianceRule(
            rule_id=str(uuid.uuid4()),
            name="Data Retention Violation Check",
            description="Check for expired data not deleted",
            framework=ComplianceFramework.GDPR,
            requirement=ComplianceRequirement.GDPR_ARTICLE_5,
            violation_type=ViolationType.DATA_RETENTION_EXCEEDED,
            condition_query="SELECT COUNT(*) FROM data_records WHERE expires_at < NOW()",
            threshold_value=0.0,
            threshold_operator=">",
            severity=ViolationSeverity.HIGH
        )
        
        # Add monitoring rule
        created_rule = await monitoring_system.add_monitoring_rule(rule)
        
        # Verify rule
        assert created_rule.rule_id == rule.rule_id
        assert created_rule.name == rule.name
        assert created_rule.violation_type == ViolationType.DATA_RETENTION_EXCEEDED
        assert created_rule.severity == ViolationSeverity.HIGH
    
    @pytest.mark.asyncio
    async def test_rule_execution(self, monitoring_system):
        """Test monitoring rule execution"""
        
        from compliance_monitoring_system import ComplianceRule, ComplianceRequirement
        
        # Create and add a rule
        rule = ComplianceRule(
            rule_id=str(uuid.uuid4()),
            name="Test Rule",
            description="Test monitoring rule",
            framework=ComplianceFramework.GDPR,
            requirement=ComplianceRequirement.GDPR_ARTICLE_5,
            violation_type=ViolationType.DATA_RETENTION_EXCEEDED,
            condition_query="SELECT COUNT(*) FROM test_table",
            threshold_value=0.0,
            threshold_operator=">",
            severity=ViolationSeverity.MEDIUM
        )
        
        await monitoring_system.add_monitoring_rule(rule)
        
        # Execute rule check
        violation = await monitoring_system.execute_rule_check(rule.rule_id)
        
        # Verify violation was detected (based on mock returning 5)
        assert violation is not None
        assert violation.rule_id == rule.rule_id
        assert violation.violation_type == ViolationType.DATA_RETENTION_EXCEEDED
        assert violation.threshold_exceeded == 5.0


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])