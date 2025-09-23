"""
GDPR Compliance Manager for VoiceHive Hotels
Implements comprehensive GDPR right-to-erasure automation and compliance monitoring
"""

import asyncio
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set, Union, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from pathlib import Path
import uuid

from pydantic import BaseModel, Field, validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger, AuditEventType, AuditSeverity, AuditContext
from enhanced_pii_redactor import EnhancedPIIRedactor, PIICategory

logger = get_safe_logger("orchestrator.gdpr_compliance")


class GDPRLawfulBasis(str, Enum):
    """GDPR Article 6 lawful bases for processing"""
    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"
    LEGITIMATE_INTERESTS = "legitimate_interests"


class DataSubjectRight(str, Enum):
    """GDPR Data Subject Rights (Chapter III)"""
    ACCESS = "access"                    # Article 15
    RECTIFICATION = "rectification"      # Article 16
    ERASURE = "erasure"                 # Article 17 (Right to be forgotten)
    RESTRICT_PROCESSING = "restrict"     # Article 18
    DATA_PORTABILITY = "portability"     # Article 20
    OBJECT = "object"                   # Article 21
    WITHDRAW_CONSENT = "withdraw"        # Article 7(3)


class ProcessingStatus(str, Enum):
    """Status of data processing operations"""
    ACTIVE = "active"
    RESTRICTED = "restricted"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"
    ARCHIVED = "archived"


class ComplianceStatus(str, Enum):
    """Compliance verification status"""
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PENDING_REVIEW = "pending_review"
    REMEDIATION_REQUIRED = "remediation_required"


@dataclass
class DataSubject:
    """GDPR Data Subject representation"""
    subject_id: str
    email: Optional[str] = None
    phone: Optional[str] = None
    name: Optional[str] = None
    hotel_guest_id: Optional[str] = None
    created_at: datetime = None
    last_updated: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.last_updated is None:
            self.last_updated = datetime.now(timezone.utc)


@dataclass
class ProcessingRecord:
    """Record of Processing Activities (ROPA) entry"""
    record_id: str
    data_subject_id: str
    processing_purpose: str
    lawful_basis: GDPRLawfulBasis
    data_categories: List[str]
    recipients: List[str]
    retention_period: int  # days
    processing_status: ProcessingStatus
    created_at: datetime
    expires_at: Optional[datetime] = None
    consent_id: Optional[str] = None
    
    def is_expired(self) -> bool:
        """Check if processing record has expired"""
        if self.expires_at:
            return datetime.now(timezone.utc) > self.expires_at
        return False


@dataclass
class ErasureRequest:
    """GDPR Article 17 Right to Erasure request"""
    request_id: str
    data_subject_id: str
    requested_at: datetime
    requested_by: str  # email or user ID
    reason: str
    scope: List[str]  # data categories to erase
    status: str = "pending"
    completed_at: Optional[datetime] = None
    verification_token: Optional[str] = None
    verification_expires: Optional[datetime] = None
    
    def generate_verification_token(self) -> str:
        """Generate verification token for erasure request"""
        token_data = f"{self.request_id}:{self.data_subject_id}:{self.requested_at.isoformat()}"
        self.verification_token = hashlib.sha256(token_data.encode()).hexdigest()[:16]
        self.verification_expires = datetime.now(timezone.utc) + timedelta(hours=24)
        return self.verification_token


class GDPRComplianceManager:
    """Comprehensive GDPR compliance management system"""
    
    def __init__(self, 
                 db_session: AsyncSession,
                 audit_logger: Optional[AuditLogger] = None,
                 pii_redactor: Optional[EnhancedPIIRedactor] = None,
                 config_path: Optional[str] = None):
        self.db = db_session
        self.audit_logger = audit_logger or AuditLogger()
        self.pii_redactor = pii_redactor or EnhancedPIIRedactor()
        
        # Load configuration
        self.config = self._load_config(config_path)
        
        # Initialize data stores
        self.processing_records: Dict[str, ProcessingRecord] = {}
        self.erasure_requests: Dict[str, ErasureRequest] = {}
        self.data_subjects: Dict[str, DataSubject] = {}
        
        # Compliance monitoring
        self.compliance_violations: List[Dict[str, Any]] = []
        self.last_compliance_check: Optional[datetime] = None
    
    async def register_data_subject(self, 
                                  subject_id: str,
                                  email: Optional[str] = None,
                                  phone: Optional[str] = None,
                                  name: Optional[str] = None,
                                  hotel_guest_id: Optional[str] = None) -> DataSubject:
        """Register a new data subject"""
        
        data_subject = DataSubject(
            subject_id=subject_id,
            email=email,
            phone=phone,
            name=name,
            hotel_guest_id=hotel_guest_id
        )
        
        self.data_subjects[subject_id] = data_subject
        
        # Audit the registration
        self.audit_logger.log_event(
            event_type=AuditEventType.DATA_CREATE,
            description=f"Data subject registered: {subject_id}",
            severity=AuditSeverity.MEDIUM,
            resource_type="data_subject",
            resource_id=subject_id,
            action="register",
            gdpr_lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS.value,
            data_subject_id=subject_id,
            retention_period=2555  # 7 years
        )
        
        logger.info(f"Data subject registered: {subject_id}")
        return data_subject
    
    async def create_processing_record(self,
                                     data_subject_id: str,
                                     processing_purpose: str,
                                     lawful_basis: GDPRLawfulBasis,
                                     data_categories: List[str],
                                     recipients: List[str],
                                     retention_period: int,
                                     consent_id: Optional[str] = None) -> ProcessingRecord:
        """Create a new processing record (ROPA entry)"""
        
        record_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(days=retention_period)
        
        record = ProcessingRecord(
            record_id=record_id,
            data_subject_id=data_subject_id,
            processing_purpose=processing_purpose,
            lawful_basis=lawful_basis,
            data_categories=data_categories,
            recipients=recipients,
            retention_period=retention_period,
            processing_status=ProcessingStatus.ACTIVE,
            created_at=created_at,
            expires_at=expires_at,
            consent_id=consent_id
        )
        
        self.processing_records[record_id] = record
        
        # Store in database
        await self._store_processing_record(record)
        
        # Audit the creation
        self.audit_logger.log_event(
            event_type=AuditEventType.DATA_CREATE,
            description=f"Processing record created: {processing_purpose}",
            severity=AuditSeverity.MEDIUM,
            resource_type="processing_record",
            resource_id=record_id,
            action="create",
            metadata={
                "purpose": processing_purpose,
                "lawful_basis": lawful_basis.value,
                "data_categories": data_categories,
                "retention_days": retention_period
            },
            gdpr_lawful_basis=lawful_basis.value,
            data_subject_id=data_subject_id,
            retention_period=2555
        )
        
        logger.info(f"Processing record created: {record_id} for subject {data_subject_id}")
        return record
    
    async def submit_erasure_request(self,
                                   data_subject_id: str,
                                   requested_by: str,
                                   reason: str,
                                   scope: List[str],
                                   verification_required: bool = True) -> ErasureRequest:
        """Submit GDPR Article 17 Right to Erasure request"""
        
        request_id = str(uuid.uuid4())
        request = ErasureRequest(
            request_id=request_id,
            data_subject_id=data_subject_id,
            requested_at=datetime.now(timezone.utc),
            requested_by=requested_by,
            reason=reason,
            scope=scope
        )
        
        # Generate verification token if required
        if verification_required:
            request.generate_verification_token()
        
        self.erasure_requests[request_id] = request
        
        # Store in database
        await self._store_erasure_request(request)
        
        # Audit the request
        self.audit_logger.log_event(
            event_type=AuditEventType.PII_RETENTION,
            description=f"Erasure request submitted: {reason}",
            severity=AuditSeverity.HIGH,
            resource_type="erasure_request",
            resource_id=request_id,
            action="submit",
            metadata={
                "reason": reason,
                "scope": scope,
                "verification_required": verification_required
            },
            gdpr_lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS.value,
            data_subject_id=data_subject_id,
            retention_period=2555
        )
        
        logger.info(f"Erasure request submitted: {request_id} for subject {data_subject_id}")
        return request
    
    async def verify_erasure_request(self, request_id: str, verification_token: str) -> bool:
        """Verify erasure request with token"""
        
        request = self.erasure_requests.get(request_id)
        if not request:
            logger.warning(f"Erasure request not found: {request_id}")
            return False
        
        # Check token validity
        if (request.verification_token != verification_token or
            not request.verification_expires or
            datetime.now(timezone.utc) > request.verification_expires):
            
            self.audit_logger.log_security_event(
                description=f"Invalid erasure verification attempt: {request_id}",
                severity=AuditSeverity.HIGH,
                metadata={"request_id": request_id, "provided_token": verification_token[:8] + "..."}
            )
            return False
        
        # Mark as verified and ready for processing
        request.status = "verified"
        await self._update_erasure_request(request)
        
        # Audit verification
        self.audit_logger.log_event(
            event_type=AuditEventType.PII_RETENTION,
            description=f"Erasure request verified: {request_id}",
            severity=AuditSeverity.HIGH,
            resource_type="erasure_request",
            resource_id=request_id,
            action="verify",
            gdpr_lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS.value,
            data_subject_id=request.data_subject_id
        )
        
        logger.info(f"Erasure request verified: {request_id}")
        return True
    
    async def execute_erasure_request(self, request_id: str) -> Dict[str, Any]:
        """Execute verified erasure request (Article 17)"""
        
        request = self.erasure_requests.get(request_id)
        if not request or request.status != "verified":
            raise ValueError(f"Invalid or unverified erasure request: {request_id}")
        
        request.status = "processing"
        await self._update_erasure_request(request)
        
        erasure_results = {
            "request_id": request_id,
            "data_subject_id": request.data_subject_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "scope": request.scope,
            "results": {}
        }
        
        try:
            # Get all processing records for the data subject
            subject_records = [
                record for record in self.processing_records.values()
                if record.data_subject_id == request.data_subject_id
            ]
            
            # Execute erasure for each data category in scope
            for category in request.scope:
                category_results = await self._erase_data_category(
                    request.data_subject_id, category, subject_records
                )
                erasure_results["results"][category] = category_results
            
            # Update processing records status
            for record in subject_records:
                if any(cat in request.scope for cat in record.data_categories):
                    record.processing_status = ProcessingStatus.DELETED
                    await self._update_processing_record(record)
            
            # Mark request as completed
            request.status = "completed"
            request.completed_at = datetime.now(timezone.utc)
            await self._update_erasure_request(request)
            
            erasure_results["completed_at"] = request.completed_at.isoformat()
            erasure_results["status"] = "success"
            
            # Audit successful erasure
            self.audit_logger.log_event(
                event_type=AuditEventType.DATA_DELETE,
                description=f"Erasure request executed successfully: {request_id}",
                severity=AuditSeverity.CRITICAL,
                resource_type="erasure_request",
                resource_id=request_id,
                action="execute",
                success=True,
                metadata=erasure_results,
                gdpr_lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS.value,
                data_subject_id=request.data_subject_id,
                retention_period=2555
            )
            
            logger.info(f"Erasure request executed successfully: {request_id}")
            
        except Exception as e:
            request.status = "failed"
            await self._update_erasure_request(request)
            
            erasure_results["status"] = "failed"
            erasure_results["error"] = str(e)
            
            # Audit failed erasure
            self.audit_logger.log_event(
                event_type=AuditEventType.DATA_DELETE,
                description=f"Erasure request failed: {request_id}",
                severity=AuditSeverity.CRITICAL,
                resource_type="erasure_request",
                resource_id=request_id,
                action="execute",
                success=False,
                error_message=str(e),
                metadata=erasure_results,
                gdpr_lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS.value,
                data_subject_id=request.data_subject_id
            )
            
            logger.error(f"Erasure request failed: {request_id} - {e}")
            raise
        
        return erasure_results
    
    async def enforce_data_retention(self) -> Dict[str, Any]:
        """Enforce data retention policies automatically"""
        
        enforcement_results = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "records_processed": 0,
            "records_expired": 0,
            "records_deleted": 0,
            "errors": []
        }
        
        current_time = datetime.now(timezone.utc)
        
        try:
            # Check all processing records for expiration
            for record_id, record in self.processing_records.items():
                enforcement_results["records_processed"] += 1
                
                if record.is_expired():
                    enforcement_results["records_expired"] += 1
                    
                    try:
                        # Execute automatic deletion for expired records
                        await self._delete_expired_data(record)
                        
                        # Update record status
                        record.processing_status = ProcessingStatus.DELETED
                        await self._update_processing_record(record)
                        
                        enforcement_results["records_deleted"] += 1
                        
                        # Audit automatic deletion
                        self.audit_logger.log_event(
                            event_type=AuditEventType.DATA_DELETE,
                            description=f"Automatic data deletion due to retention policy: {record_id}",
                            severity=AuditSeverity.HIGH,
                            resource_type="processing_record",
                            resource_id=record_id,
                            action="auto_delete",
                            metadata={
                                "retention_period": record.retention_period,
                                "expired_at": record.expires_at.isoformat() if record.expires_at else None
                            },
                            gdpr_lawful_basis=record.lawful_basis.value,
                            data_subject_id=record.data_subject_id
                        )
                        
                    except Exception as e:
                        error_msg = f"Failed to delete expired record {record_id}: {e}"
                        enforcement_results["errors"].append(error_msg)
                        logger.error(error_msg)
            
            enforcement_results["completed_at"] = datetime.now(timezone.utc).isoformat()
            enforcement_results["status"] = "success"
            
            logger.info(f"Data retention enforcement completed: {enforcement_results['records_deleted']} records deleted")
            
        except Exception as e:
            enforcement_results["status"] = "failed"
            enforcement_results["error"] = str(e)
            logger.error(f"Data retention enforcement failed: {e}")
            raise
        
        return enforcement_results
    
    async def generate_compliance_report(self) -> Dict[str, Any]:
        """Generate comprehensive GDPR compliance report"""
        
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_id": str(uuid.uuid4()),
            "compliance_status": ComplianceStatus.COMPLIANT.value,
            "summary": {
                "total_data_subjects": len(self.data_subjects),
                "active_processing_records": len([r for r in self.processing_records.values() 
                                                if r.processing_status == ProcessingStatus.ACTIVE]),
                "pending_erasure_requests": len([r for r in self.erasure_requests.values() 
                                               if r.status in ["pending", "verified"]]),
                "compliance_violations": len(self.compliance_violations)
            },
            "data_processing": {},
            "retention_compliance": {},
            "erasure_requests": {},
            "violations": self.compliance_violations,
            "recommendations": []
        }
        
        # Analyze data processing compliance
        report["data_processing"] = await self._analyze_processing_compliance()
        
        # Analyze retention compliance
        report["retention_compliance"] = await self._analyze_retention_compliance()
        
        # Analyze erasure requests
        report["erasure_requests"] = await self._analyze_erasure_requests()
        
        # Generate recommendations
        report["recommendations"] = await self._generate_compliance_recommendations()
        
        # Determine overall compliance status
        if report["summary"]["compliance_violations"] > 0:
            report["compliance_status"] = ComplianceStatus.NON_COMPLIANT.value
        elif len(report["recommendations"]) > 0:
            report["compliance_status"] = ComplianceStatus.PENDING_REVIEW.value
        
        # Audit report generation
        self.audit_logger.log_event(
            event_type=AuditEventType.DATA_EXPORT,
            description="GDPR compliance report generated",
            severity=AuditSeverity.HIGH,
            resource_type="compliance_report",
            resource_id=report["report_id"],
            action="generate",
            metadata={
                "total_subjects": report["summary"]["total_data_subjects"],
                "compliance_status": report["compliance_status"]
            },
            gdpr_lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS.value,
            retention_period=2555
        )
        
        logger.info(f"GDPR compliance report generated: {report['report_id']}")
        return report
    
    async def _erase_data_category(self, 
                                 data_subject_id: str, 
                                 category: str, 
                                 processing_records: List[ProcessingRecord]) -> Dict[str, Any]:
        """Erase data for a specific category"""
        
        category_results = {
            "category": category,
            "records_affected": 0,
            "databases_updated": [],
            "files_deleted": [],
            "external_services_notified": [],
            "errors": []
        }
        
        try:
            # Database erasure
            if category in ["call_recordings", "transcripts", "metadata"]:
                affected_rows = await self._erase_database_data(data_subject_id, category)
                category_results["records_affected"] = affected_rows
                category_results["databases_updated"].append(f"main_db_{category}")
            
            # File system erasure
            if category in ["call_recordings", "audio_files"]:
                deleted_files = await self._erase_file_data(data_subject_id, category)
                category_results["files_deleted"] = deleted_files
            
            # External service notification
            if category in ["voice_profiles", "ai_models"]:
                notified_services = await self._notify_external_services_erasure(data_subject_id, category)
                category_results["external_services_notified"] = notified_services
            
        except Exception as e:
            error_msg = f"Failed to erase {category} for subject {data_subject_id}: {e}"
            category_results["errors"].append(error_msg)
            logger.error(error_msg)
        
        return category_results
    
    async def _erase_database_data(self, data_subject_id: str, category: str) -> int:
        """Erase data from database tables"""
        
        table_mappings = {
            "call_recordings": ["call_recordings", "call_metadata"],
            "transcripts": ["call_transcripts", "transcript_segments"],
            "metadata": ["guest_preferences", "call_history"],
            "pii_data": ["guest_profiles", "contact_information"]
        }
        
        total_affected = 0
        tables = table_mappings.get(category, [])
        
        for table in tables:
            try:
                # Use parameterized query to prevent SQL injection
                query = text(f"DELETE FROM {table} WHERE data_subject_id = :subject_id")
                result = await self.db.execute(query, {"subject_id": data_subject_id})
                affected_rows = result.rowcount
                total_affected += affected_rows
                
                logger.info(f"Deleted {affected_rows} rows from {table} for subject {data_subject_id}")
                
            except Exception as e:
                logger.error(f"Failed to delete from {table}: {e}")
                raise
        
        await self.db.commit()
        return total_affected
    
    async def _erase_file_data(self, data_subject_id: str, category: str) -> List[str]:
        """Erase files from storage"""
        
        deleted_files = []
        
        # This would integrate with actual file storage (S3, local filesystem, etc.)
        # For now, we'll simulate the process
        
        file_patterns = {
            "call_recordings": [f"recordings/{data_subject_id}/*.wav", f"recordings/{data_subject_id}/*.mp3"],
            "audio_files": [f"audio/{data_subject_id}/*"],
            "documents": [f"documents/{data_subject_id}/*"]
        }
        
        patterns = file_patterns.get(category, [])
        
        for pattern in patterns:
            # Simulate file deletion
            # In real implementation, this would use boto3 for S3, os.remove for local files, etc.
            deleted_files.append(pattern)
            logger.info(f"Deleted files matching pattern: {pattern}")
        
        return deleted_files
    
    async def _notify_external_services_erasure(self, data_subject_id: str, category: str) -> List[str]:
        """Notify external services about data erasure"""
        
        notified_services = []
        
        service_mappings = {
            "voice_profiles": ["elevenlabs", "azure_speech"],
            "ai_models": ["openai", "anthropic"],
            "analytics": ["mixpanel", "amplitude"]
        }
        
        services = service_mappings.get(category, [])
        
        for service in services:
            try:
                # This would make actual API calls to external services
                # For now, we'll simulate the notification
                
                logger.info(f"Notified {service} about erasure for subject {data_subject_id}")
                notified_services.append(service)
                
            except Exception as e:
                logger.error(f"Failed to notify {service}: {e}")
                # Don't raise here, continue with other services
        
        return notified_services
    
    async def _delete_expired_data(self, record: ProcessingRecord):
        """Delete data for expired processing record"""
        
        for category in record.data_categories:
            await self._erase_data_category(record.data_subject_id, category, [record])
    
    async def _analyze_processing_compliance(self) -> Dict[str, Any]:
        """Analyze processing records for compliance"""
        
        analysis = {
            "total_records": len(self.processing_records),
            "by_lawful_basis": {},
            "by_status": {},
            "expired_records": 0,
            "missing_consent": []
        }
        
        for record in self.processing_records.values():
            # Count by lawful basis
            basis = record.lawful_basis.value
            analysis["by_lawful_basis"][basis] = analysis["by_lawful_basis"].get(basis, 0) + 1
            
            # Count by status
            status = record.processing_status.value
            analysis["by_status"][status] = analysis["by_status"].get(status, 0) + 1
            
            # Check for expired records
            if record.is_expired():
                analysis["expired_records"] += 1
            
            # Check for missing consent
            if record.lawful_basis == GDPRLawfulBasis.CONSENT and not record.consent_id:
                analysis["missing_consent"].append(record.record_id)
        
        return analysis
    
    async def _analyze_retention_compliance(self) -> Dict[str, Any]:
        """Analyze data retention compliance"""
        
        analysis = {
            "total_records": len(self.processing_records),
            "expired_not_deleted": 0,
            "expiring_soon": 0,
            "retention_violations": []
        }
        
        current_time = datetime.now(timezone.utc)
        warning_threshold = current_time + timedelta(days=30)  # 30 days warning
        
        for record in self.processing_records.values():
            if record.expires_at:
                if record.is_expired() and record.processing_status != ProcessingStatus.DELETED:
                    analysis["expired_not_deleted"] += 1
                    analysis["retention_violations"].append({
                        "record_id": record.record_id,
                        "expired_at": record.expires_at.isoformat(),
                        "days_overdue": (current_time - record.expires_at).days
                    })
                elif record.expires_at <= warning_threshold:
                    analysis["expiring_soon"] += 1
        
        return analysis
    
    async def _analyze_erasure_requests(self) -> Dict[str, Any]:
        """Analyze erasure requests status"""
        
        analysis = {
            "total_requests": len(self.erasure_requests),
            "by_status": {},
            "overdue_requests": [],
            "average_processing_time": None
        }
        
        processing_times = []
        current_time = datetime.now(timezone.utc)
        
        for request in self.erasure_requests.values():
            # Count by status
            status = request.status
            analysis["by_status"][status] = analysis["by_status"].get(status, 0) + 1
            
            # Check for overdue requests (>30 days as per GDPR)
            days_since_request = (current_time - request.requested_at).days
            if days_since_request > 30 and request.status not in ["completed", "failed"]:
                analysis["overdue_requests"].append({
                    "request_id": request.request_id,
                    "days_overdue": days_since_request - 30,
                    "requested_at": request.requested_at.isoformat()
                })
            
            # Calculate processing time for completed requests
            if request.completed_at:
                processing_time = (request.completed_at - request.requested_at).total_seconds() / 3600  # hours
                processing_times.append(processing_time)
        
        if processing_times:
            analysis["average_processing_time"] = sum(processing_times) / len(processing_times)
        
        return analysis
    
    async def _generate_compliance_recommendations(self) -> List[Dict[str, Any]]:
        """Generate compliance recommendations"""
        
        recommendations = []
        
        # Check for expired records
        expired_count = len([r for r in self.processing_records.values() 
                           if r.is_expired() and r.processing_status != ProcessingStatus.DELETED])
        
        if expired_count > 0:
            recommendations.append({
                "priority": "high",
                "category": "data_retention",
                "title": "Delete expired data",
                "description": f"{expired_count} processing records have expired and should be deleted",
                "action": "Run data retention enforcement"
            })
        
        # Check for overdue erasure requests
        overdue_requests = [r for r in self.erasure_requests.values() 
                          if (datetime.now(timezone.utc) - r.requested_at).days > 30 
                          and r.status not in ["completed", "failed"]]
        
        if overdue_requests:
            recommendations.append({
                "priority": "critical",
                "category": "erasure_requests",
                "title": "Process overdue erasure requests",
                "description": f"{len(overdue_requests)} erasure requests are overdue (>30 days)",
                "action": "Review and process pending erasure requests"
            })
        
        # Check for missing consent records
        consent_missing = [r for r in self.processing_records.values() 
                         if r.lawful_basis == GDPRLawfulBasis.CONSENT and not r.consent_id]
        
        if consent_missing:
            recommendations.append({
                "priority": "medium",
                "category": "consent_management",
                "title": "Link consent records",
                "description": f"{len(consent_missing)} processing records based on consent are missing consent IDs",
                "action": "Update processing records with proper consent references"
            })
        
        return recommendations
    
    async def _store_processing_record(self, record: ProcessingRecord):
        """Store processing record in database"""
        try:
            query = text("""
                INSERT INTO gdpr_processing_records 
                (record_id, data_subject_id, processing_purpose, lawful_basis, 
                 data_categories, recipients, retention_period, processing_status, 
                 created_at, expires_at, consent_id)
                VALUES (:record_id, :data_subject_id, :processing_purpose, :lawful_basis,
                        :data_categories, :recipients, :retention_period, :processing_status,
                        :created_at, :expires_at, :consent_id)
            """)
            
            await self.db.execute(query, {
                "record_id": record.record_id,
                "data_subject_id": record.data_subject_id,
                "processing_purpose": record.processing_purpose,
                "lawful_basis": record.lawful_basis.value,
                "data_categories": json.dumps(record.data_categories),
                "recipients": json.dumps(record.recipients),
                "retention_period": record.retention_period,
                "processing_status": record.processing_status.value,
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "consent_id": record.consent_id
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to store processing record {record.record_id}: {e}")
            await self.db.rollback()
            raise
    
    async def _update_processing_record(self, record: ProcessingRecord):
        """Update processing record in database"""
        try:
            query = text("""
                UPDATE gdpr_processing_records 
                SET processing_status = :processing_status,
                    expires_at = :expires_at,
                    updated_at = :updated_at
                WHERE record_id = :record_id
            """)
            
            await self.db.execute(query, {
                "record_id": record.record_id,
                "processing_status": record.processing_status.value,
                "expires_at": record.expires_at,
                "updated_at": datetime.now(timezone.utc)
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to update processing record {record.record_id}: {e}")
            await self.db.rollback()
            raise
    
    async def _store_erasure_request(self, request: ErasureRequest):
        """Store erasure request in database"""
        try:
            query = text("""
                INSERT INTO gdpr_erasure_requests 
                (request_id, data_subject_id, requested_at, requested_by, reason, 
                 scope, status, verification_token, verification_expires)
                VALUES (:request_id, :data_subject_id, :requested_at, :requested_by,
                        :reason, :scope, :status, :verification_token, :verification_expires)
            """)
            
            await self.db.execute(query, {
                "request_id": request.request_id,
                "data_subject_id": request.data_subject_id,
                "requested_at": request.requested_at,
                "requested_by": request.requested_by,
                "reason": request.reason,
                "scope": json.dumps(request.scope),
                "status": request.status,
                "verification_token": request.verification_token,
                "verification_expires": request.verification_expires
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to store erasure request {request.request_id}: {e}")
            await self.db.rollback()
            raise
    
    async def _update_erasure_request(self, request: ErasureRequest):
        """Update erasure request in database"""
        try:
            query = text("""
                UPDATE gdpr_erasure_requests 
                SET status = :status,
                    completed_at = :completed_at,
                    updated_at = :updated_at
                WHERE request_id = :request_id
            """)
            
            await self.db.execute(query, {
                "request_id": request.request_id,
                "status": request.status,
                "completed_at": request.completed_at,
                "updated_at": datetime.now(timezone.utc)
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to update erasure request {request.request_id}: {e}")
            await self.db.rollback()
            raise
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load GDPR configuration"""
        
        default_config = {
            "retention_periods": {
                "call_recordings": 30,
                "transcripts": 90,
                "metadata": 365,
                "audit_logs": 2555
            },
            "erasure_verification_required": True,
            "automatic_retention_enforcement": True,
            "compliance_check_frequency": "daily"
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r') as f:
                    import yaml
                    config = yaml.safe_load(f)
                    default_config.update(config)
            except Exception as e:
                logger.error(f"Failed to load GDPR config from {config_path}: {e}")
        
        return default_config


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    from unittest.mock import AsyncMock
    
    async def test_gdpr_compliance():
        # Mock database session
        mock_db = AsyncMock()
        
        # Create compliance manager
        manager = GDPRComplianceManager(mock_db)
        
        # Test data subject registration
        subject = await manager.register_data_subject(
            subject_id="guest_123",
            email="john.doe@example.com",
            name="John Doe",
            hotel_guest_id="HTL_456"
        )
        print(f"Registered data subject: {subject.subject_id}")
        
        # Test processing record creation
        record = await manager.create_processing_record(
            data_subject_id="guest_123",
            processing_purpose="Call handling and customer service",
            lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS,
            data_categories=["call_recordings", "transcripts", "metadata"],
            recipients=["VoiceHive Hotels", "PMS Provider"],
            retention_period=90
        )
        print(f"Created processing record: {record.record_id}")
        
        # Test erasure request
        erasure_req = await manager.submit_erasure_request(
            data_subject_id="guest_123",
            requested_by="john.doe@example.com",
            reason="No longer a customer",
            scope=["call_recordings", "transcripts"]
        )
        print(f"Submitted erasure request: {erasure_req.request_id}")
        
        # Test compliance report
        report = await manager.generate_compliance_report()
        print(f"Generated compliance report: {report['report_id']}")
        print(f"Compliance status: {report['compliance_status']}")
        
        print("GDPR compliance test completed successfully")
    
    # Run test
    asyncio.run(test_gdpr_compliance())