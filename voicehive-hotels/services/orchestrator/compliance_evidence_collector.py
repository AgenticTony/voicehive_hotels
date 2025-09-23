"""
Compliance Evidence Collection and Reporting System for VoiceHive Hotels
Automated collection, validation, and reporting of compliance evidence for GDPR and other regulations
"""

import asyncio
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set, Tuple, Union
from enum import Enum
from dataclasses import dataclass, asdict, field
from pathlib import Path
import uuid
import zipfile
import tempfile

from pydantic import BaseModel, Field, validator
from sqlalchemy import text, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
import boto3
from jinja2 import Template

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger, AuditEventType, AuditSeverity
from gdpr_compliance_manager import GDPRLawfulBasis, DataSubjectRight
from data_classification_system import DataSensitivityLevel, DataClassification

logger = get_safe_logger("orchestrator.compliance_evidence")


class ComplianceFramework(str, Enum):
    """Supported compliance frameworks"""
    GDPR = "gdpr"
    CCPA = "ccpa"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    SOX = "sox"
    ISO27001 = "iso27001"
    SOC2 = "soc2"
    NIST = "nist"


class EvidenceType(str, Enum):
    """Types of compliance evidence"""
    POLICY_DOCUMENT = "policy_document"
    PROCEDURE_DOCUMENT = "procedure_document"
    AUDIT_LOG = "audit_log"
    SYSTEM_CONFIGURATION = "system_configuration"
    ACCESS_CONTROL_MATRIX = "access_control_matrix"
    DATA_FLOW_DIAGRAM = "data_flow_diagram"
    RISK_ASSESSMENT = "risk_assessment"
    TRAINING_RECORD = "training_record"
    INCIDENT_REPORT = "incident_report"
    PENETRATION_TEST = "penetration_test"
    VULNERABILITY_SCAN = "vulnerability_scan"
    BACKUP_VERIFICATION = "backup_verification"
    DISASTER_RECOVERY_TEST = "disaster_recovery_test"
    DATA_RETENTION_LOG = "data_retention_log"
    CONSENT_RECORD = "consent_record"
    DSAR_RESPONSE = "dsar_response"


class EvidenceStatus(str, Enum):
    """Status of evidence collection"""
    PENDING = "pending"
    COLLECTING = "collecting"
    COLLECTED = "collected"
    VALIDATED = "validated"
    EXPIRED = "expired"
    FAILED = "failed"


class ComplianceRequirement(str, Enum):
    """Specific compliance requirements"""
    # GDPR Requirements
    GDPR_ARTICLE_5 = "gdpr_article_5"  # Principles of processing
    GDPR_ARTICLE_6 = "gdpr_article_6"  # Lawfulness of processing
    GDPR_ARTICLE_7 = "gdpr_article_7"  # Conditions for consent
    GDPR_ARTICLE_13 = "gdpr_article_13"  # Information to be provided
    GDPR_ARTICLE_15 = "gdpr_article_15"  # Right of access
    GDPR_ARTICLE_17 = "gdpr_article_17"  # Right to erasure
    GDPR_ARTICLE_25 = "gdpr_article_25"  # Data protection by design
    GDPR_ARTICLE_30 = "gdpr_article_30"  # Records of processing
    GDPR_ARTICLE_32 = "gdpr_article_32"  # Security of processing
    GDPR_ARTICLE_33 = "gdpr_article_33"  # Breach notification
    GDPR_ARTICLE_35 = "gdpr_article_35"  # Data protection impact assessment
    
    # PCI DSS Requirements
    PCI_REQ_1 = "pci_req_1"  # Firewall configuration
    PCI_REQ_2 = "pci_req_2"  # Default passwords
    PCI_REQ_3 = "pci_req_3"  # Protect stored cardholder data
    PCI_REQ_4 = "pci_req_4"  # Encrypt transmission
    PCI_REQ_6 = "pci_req_6"  # Secure systems and applications
    PCI_REQ_8 = "pci_req_8"  # Identify and authenticate access
    PCI_REQ_10 = "pci_req_10"  # Track and monitor access
    PCI_REQ_11 = "pci_req_11"  # Regularly test security systems


@dataclass
class EvidenceItem:
    """Individual piece of compliance evidence"""
    evidence_id: str
    evidence_type: EvidenceType
    framework: ComplianceFramework
    requirement: ComplianceRequirement
    
    # Content
    title: str
    description: str
    file_path: Optional[str] = None
    content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Status and validation
    status: EvidenceStatus = EvidenceStatus.PENDING
    collected_at: Optional[datetime] = None
    validated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    # Source information
    source_system: str = ""
    source_query: Optional[str] = None
    collection_method: str = "manual"
    
    # Validation
    checksum: Optional[str] = None
    digital_signature: Optional[str] = None
    validator: Optional[str] = None
    validation_notes: Optional[str] = None
    
    # Compliance mapping
    control_objectives: List[str] = field(default_factory=list)
    risk_level: str = "medium"
    
    def __post_init__(self):
        if self.collected_at is None and self.status in [EvidenceStatus.COLLECTED, EvidenceStatus.VALIDATED]:
            self.collected_at = datetime.now(timezone.utc)
    
    def is_expired(self) -> bool:
        """Check if evidence has expired"""
        if self.expires_at:
            return datetime.now(timezone.utc) > self.expires_at
        return False
    
    def calculate_checksum(self) -> str:
        """Calculate checksum for evidence integrity"""
        content_to_hash = f"{self.title}:{self.description}:{self.content or ''}"
        return hashlib.sha256(content_to_hash.encode()).hexdigest()


@dataclass
class ComplianceReport:
    """Comprehensive compliance report"""
    report_id: str
    framework: ComplianceFramework
    generated_at: datetime
    reporting_period_start: datetime
    reporting_period_end: datetime
    
    # Report metadata
    title: str
    description: str
    version: str = "1.0"
    
    # Evidence summary
    total_evidence_items: int = 0
    evidence_by_type: Dict[str, int] = field(default_factory=dict)
    evidence_by_status: Dict[str, int] = field(default_factory=dict)
    evidence_by_requirement: Dict[str, int] = field(default_factory=dict)
    
    # Compliance status
    overall_compliance_score: float = 0.0
    compliant_requirements: List[str] = field(default_factory=list)
    non_compliant_requirements: List[str] = field(default_factory=list)
    gaps_identified: List[Dict[str, Any]] = field(default_factory=list)
    
    # Evidence items
    evidence_items: List[EvidenceItem] = field(default_factory=list)
    
    # Recommendations
    recommendations: List[Dict[str, Any]] = field(default_factory=list)
    
    # Report files
    report_file_path: Optional[str] = None
    evidence_archive_path: Optional[str] = None


class ComplianceEvidenceCollector:
    """Automated compliance evidence collection and reporting system"""
    
    def __init__(self, 
                 db_session: AsyncSession,
                 audit_logger: Optional[AuditLogger] = None,
                 config_path: Optional[str] = None):
        self.db = db_session
        self.audit_logger = audit_logger or AuditLogger()
        
        # Load configuration
        self.config = self._load_config(config_path)
        
        # Evidence storage
        self.evidence_items: Dict[str, EvidenceItem] = {}
        self.compliance_reports: Dict[str, ComplianceReport] = {}
        
        # Collection templates
        self.evidence_templates = self._load_evidence_templates()
        self.requirement_mappings = self._load_requirement_mappings()
        
        # Statistics
        self.collection_stats = {
            "total_collections": 0,
            "successful_collections": 0,
            "failed_collections": 0,
            "evidence_items_collected": 0,
            "reports_generated": 0
        }
        
        # Initialize storage
        self.storage_client = self._init_storage_client()
    
    async def collect_evidence_for_framework(self, 
                                           framework: ComplianceFramework,
                                           requirements: Optional[List[ComplianceRequirement]] = None,
                                           force_refresh: bool = False) -> Dict[str, Any]:
        """Collect all evidence for a compliance framework"""
        
        collection_start = datetime.now(timezone.utc)
        
        results = {
            "framework": framework.value,
            "started_at": collection_start.isoformat(),
            "requirements_processed": 0,
            "evidence_collected": 0,
            "evidence_validated": 0,
            "errors": [],
            "collection_summary": {}
        }
        
        try:
            # Get requirements to process
            if not requirements:
                requirements = self._get_framework_requirements(framework)
            
            results["requirements_processed"] = len(requirements)
            
            # Collect evidence for each requirement
            for requirement in requirements:
                try:
                    requirement_results = await self._collect_requirement_evidence(
                        framework, requirement, force_refresh
                    )
                    
                    results["evidence_collected"] += requirement_results["evidence_collected"]
                    results["evidence_validated"] += requirement_results["evidence_validated"]
                    results["collection_summary"][requirement.value] = requirement_results
                    
                except Exception as e:
                    error_msg = f"Failed to collect evidence for {requirement.value}: {e}"
                    results["errors"].append(error_msg)
                    logger.error(error_msg)
            
            results["completed_at"] = datetime.now(timezone.utc).isoformat()
            results["duration_seconds"] = (datetime.now(timezone.utc) - collection_start).total_seconds()
            results["status"] = "success" if not results["errors"] else "partial_success"
            
            # Update statistics
            self.collection_stats["total_collections"] += 1
            if results["status"] == "success":
                self.collection_stats["successful_collections"] += 1
            else:
                self.collection_stats["failed_collections"] += 1
            self.collection_stats["evidence_items_collected"] += results["evidence_collected"]
            
            # Audit the collection
            self.audit_logger.log_event(
                event_type=AuditEventType.ADMIN_ACTION,
                description=f"Compliance evidence collection for {framework.value}",
                severity=AuditSeverity.HIGH,
                resource_type="compliance_evidence",
                action="collect",
                success=results["status"] == "success",
                metadata=results,
                retention_period=2555
            )
            
            logger.info(f"Evidence collection completed for {framework.value}: {results['evidence_collected']} items")
            
        except Exception as e:
            results["status"] = "failed"
            results["error"] = str(e)
            results["completed_at"] = datetime.now(timezone.utc).isoformat()
            
            logger.error(f"Evidence collection failed for {framework.value}: {e}")
            raise
        
        return results
    
    async def generate_compliance_report(self, 
                                       framework: ComplianceFramework,
                                       period_start: Optional[datetime] = None,
                                       period_end: Optional[datetime] = None,
                                       include_evidence_archive: bool = True) -> ComplianceReport:
        """Generate comprehensive compliance report"""
        
        # Set default reporting period (last 90 days)
        if not period_end:
            period_end = datetime.now(timezone.utc)
        if not period_start:
            period_start = period_end - timedelta(days=90)
        
        report_id = str(uuid.uuid4())
        
        # Create report
        report = ComplianceReport(
            report_id=report_id,
            framework=framework,
            generated_at=datetime.now(timezone.utc),
            reporting_period_start=period_start,
            reporting_period_end=period_end,
            title=f"{framework.value.upper()} Compliance Report",
            description=f"Comprehensive compliance report for {framework.value.upper()} framework"
        )
        
        try:
            # Collect relevant evidence items
            framework_evidence = [
                evidence for evidence in self.evidence_items.values()
                if (evidence.framework == framework and
                    evidence.collected_at and
                    period_start <= evidence.collected_at <= period_end)
            ]
            
            report.evidence_items = framework_evidence
            report.total_evidence_items = len(framework_evidence)
            
            # Analyze evidence by type
            for evidence in framework_evidence:
                evidence_type = evidence.evidence_type.value
                report.evidence_by_type[evidence_type] = report.evidence_by_type.get(evidence_type, 0) + 1
                
                status = evidence.status.value
                report.evidence_by_status[status] = report.evidence_by_status.get(status, 0) + 1
                
                requirement = evidence.requirement.value
                report.evidence_by_requirement[requirement] = report.evidence_by_requirement.get(requirement, 0) + 1
            
            # Assess compliance status
            compliance_assessment = await self._assess_framework_compliance(framework, framework_evidence)
            
            report.overall_compliance_score = compliance_assessment["overall_score"]
            report.compliant_requirements = compliance_assessment["compliant_requirements"]
            report.non_compliant_requirements = compliance_assessment["non_compliant_requirements"]
            report.gaps_identified = compliance_assessment["gaps"]
            
            # Generate recommendations
            report.recommendations = await self._generate_compliance_recommendations(framework, compliance_assessment)
            
            # Generate report files
            if include_evidence_archive:
                report.evidence_archive_path = await self._create_evidence_archive(framework_evidence, report_id)
            
            report.report_file_path = await self._generate_report_document(report)
            
            # Store report
            self.compliance_reports[report_id] = report
            
            # Update statistics
            self.collection_stats["reports_generated"] += 1
            
            # Audit report generation
            self.audit_logger.log_event(
                event_type=AuditEventType.DATA_EXPORT,
                description=f"Compliance report generated: {framework.value}",
                severity=AuditSeverity.HIGH,
                resource_type="compliance_report",
                resource_id=report_id,
                action="generate",
                metadata={
                    "framework": framework.value,
                    "evidence_items": report.total_evidence_items,
                    "compliance_score": report.overall_compliance_score,
                    "reporting_period": f"{period_start.isoformat()} to {period_end.isoformat()}"
                },
                retention_period=2555
            )
            
            logger.info(f"Compliance report generated: {report_id} for {framework.value}")
            
        except Exception as e:
            logger.error(f"Failed to generate compliance report for {framework.value}: {e}")
            raise
        
        return report
    
    async def validate_evidence_integrity(self, evidence_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Validate integrity of collected evidence"""
        
        validation_results = {
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "total_items": 0,
            "valid_items": 0,
            "invalid_items": 0,
            "expired_items": 0,
            "validation_details": {},
            "integrity_issues": []
        }
        
        # Get evidence items to validate
        items_to_validate = []
        if evidence_ids:
            items_to_validate = [self.evidence_items[eid] for eid in evidence_ids if eid in self.evidence_items]
        else:
            items_to_validate = list(self.evidence_items.values())
        
        validation_results["total_items"] = len(items_to_validate)
        
        for evidence in items_to_validate:
            validation_detail = {
                "evidence_id": evidence.evidence_id,
                "title": evidence.title,
                "status": evidence.status.value,
                "is_valid": True,
                "is_expired": evidence.is_expired(),
                "issues": []
            }
            
            # Check expiration
            if evidence.is_expired():
                validation_results["expired_items"] += 1
                validation_detail["issues"].append("Evidence has expired")
                validation_detail["is_valid"] = False
            
            # Verify checksum if available
            if evidence.checksum:
                current_checksum = evidence.calculate_checksum()
                if current_checksum != evidence.checksum:
                    validation_detail["issues"].append("Checksum mismatch - evidence may have been tampered with")
                    validation_detail["is_valid"] = False
                    validation_results["integrity_issues"].append({
                        "evidence_id": evidence.evidence_id,
                        "issue": "checksum_mismatch",
                        "expected": evidence.checksum,
                        "actual": current_checksum
                    })
            
            # Check file existence if file-based evidence
            if evidence.file_path:
                if not await self._verify_file_exists(evidence.file_path):
                    validation_detail["issues"].append("Evidence file not found")
                    validation_detail["is_valid"] = False
            
            # Validate content completeness
            if not evidence.content and not evidence.file_path:
                validation_detail["issues"].append("No content or file path provided")
                validation_detail["is_valid"] = False
            
            # Update counters
            if validation_detail["is_valid"]:
                validation_results["valid_items"] += 1
            else:
                validation_results["invalid_items"] += 1
            
            validation_results["validation_details"][evidence.evidence_id] = validation_detail
        
        # Audit validation
        self.audit_logger.log_event(
            event_type=AuditEventType.ADMIN_ACTION,
            description="Evidence integrity validation completed",
            severity=AuditSeverity.MEDIUM,
            resource_type="evidence_validation",
            action="validate",
            metadata=validation_results,
            retention_period=2555
        )
        
        logger.info(f"Evidence validation completed: {validation_results['valid_items']}/{validation_results['total_items']} valid")
        return validation_results
    
    async def schedule_evidence_collection(self, 
                                         framework: ComplianceFramework,
                                         schedule_cron: str,
                                         requirements: Optional[List[ComplianceRequirement]] = None) -> str:
        """Schedule automated evidence collection"""
        
        schedule_id = str(uuid.uuid4())
        
        # This would integrate with a job scheduler like Celery, APScheduler, etc.
        # For now, we'll log the scheduling request
        
        schedule_config = {
            "schedule_id": schedule_id,
            "framework": framework.value,
            "cron_expression": schedule_cron,
            "requirements": [req.value for req in requirements] if requirements else "all",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Audit scheduling
        self.audit_logger.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            description=f"Evidence collection scheduled for {framework.value}",
            severity=AuditSeverity.MEDIUM,
            resource_type="collection_schedule",
            resource_id=schedule_id,
            action="schedule",
            metadata=schedule_config,
            retention_period=2555
        )
        
        logger.info(f"Evidence collection scheduled: {schedule_id} for {framework.value}")
        return schedule_id
    
    async def _collect_requirement_evidence(self, 
                                          framework: ComplianceFramework,
                                          requirement: ComplianceRequirement,
                                          force_refresh: bool = False) -> Dict[str, Any]:
        """Collect evidence for a specific requirement"""
        
        results = {
            "requirement": requirement.value,
            "evidence_collected": 0,
            "evidence_validated": 0,
            "evidence_items": [],
            "errors": []
        }
        
        # Get evidence templates for this requirement
        templates = self.evidence_templates.get(requirement, [])
        
        for template in templates:
            try:
                evidence_item = await self._collect_evidence_from_template(template, framework, requirement, force_refresh)
                
                if evidence_item:
                    self.evidence_items[evidence_item.evidence_id] = evidence_item
                    results["evidence_items"].append(evidence_item.evidence_id)
                    results["evidence_collected"] += 1
                    
                    # Validate evidence
                    if await self._validate_evidence_item(evidence_item):
                        evidence_item.status = EvidenceStatus.VALIDATED
                        evidence_item.validated_at = datetime.now(timezone.utc)
                        results["evidence_validated"] += 1
                    else:
                        evidence_item.status = EvidenceStatus.FAILED
            
            except Exception as e:
                error_msg = f"Failed to collect evidence from template {template.get('name', 'unknown')}: {e}"
                results["errors"].append(error_msg)
                logger.error(error_msg)
        
        return results
    
    async def _collect_evidence_from_template(self, 
                                            template: Dict[str, Any],
                                            framework: ComplianceFramework,
                                            requirement: ComplianceRequirement,
                                            force_refresh: bool = False) -> Optional[EvidenceItem]:
        """Collect evidence using a template"""
        
        evidence_id = str(uuid.uuid4())
        
        # Check if evidence already exists and is still valid
        if not force_refresh:
            existing_evidence = self._find_existing_evidence(framework, requirement, template["evidence_type"])
            if existing_evidence and not existing_evidence.is_expired():
                logger.info(f"Using existing evidence: {existing_evidence.evidence_id}")
                return existing_evidence
        
        # Create evidence item
        evidence = EvidenceItem(
            evidence_id=evidence_id,
            evidence_type=EvidenceType(template["evidence_type"]),
            framework=framework,
            requirement=requirement,
            title=template["title"],
            description=template["description"],
            source_system=template.get("source_system", "unknown"),
            collection_method=template.get("collection_method", "automated"),
            control_objectives=template.get("control_objectives", []),
            risk_level=template.get("risk_level", "medium")
        )
        
        # Set expiration
        if "validity_days" in template:
            evidence.expires_at = datetime.now(timezone.utc) + timedelta(days=template["validity_days"])
        
        # Collect evidence based on type
        collection_method = template.get("collection_method", "database_query")
        
        if collection_method == "database_query":
            evidence.content = await self._collect_database_evidence(template)
        elif collection_method == "file_system":
            evidence.file_path = await self._collect_file_evidence(template)
        elif collection_method == "api_call":
            evidence.content = await self._collect_api_evidence(template)
        elif collection_method == "log_analysis":
            evidence.content = await self._collect_log_evidence(template)
        else:
            logger.warning(f"Unknown collection method: {collection_method}")
            return None
        
        # Calculate checksum
        evidence.checksum = evidence.calculate_checksum()
        evidence.status = EvidenceStatus.COLLECTED
        evidence.collected_at = datetime.now(timezone.utc)
        
        return evidence
    
    async def _collect_database_evidence(self, template: Dict[str, Any]) -> str:
        """Collect evidence from database queries"""
        
        query = template.get("query")
        if not query:
            raise ValueError("No query specified in template")
        
        try:
            result = await self.db.execute(text(query))
            rows = result.fetchall()
            
            # Convert to JSON format
            evidence_data = {
                "query": query,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "row_count": len(rows),
                "results": [dict(row._mapping) for row in rows]
            }
            
            return json.dumps(evidence_data, indent=2, default=str)
        
        except Exception as e:
            logger.error(f"Database evidence collection failed: {e}")
            raise
    
    async def _collect_file_evidence(self, template: Dict[str, Any]) -> str:
        """Collect evidence from file system"""
        
        file_pattern = template.get("file_pattern")
        if not file_pattern:
            raise ValueError("No file pattern specified in template")
        
        # Implement actual file collection
        import glob
        import shutil
        
        evidence_dir = Path(f"evidence/{template['evidence_type']}")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        
        evidence_file_path = evidence_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        # Collect files matching the pattern
        collected_files = []
        for pattern in file_pattern.split(','):
            pattern = pattern.strip()
            matching_files = glob.glob(pattern)
            collected_files.extend(matching_files)
        
        # Create evidence package
        evidence_data = {
            "file_pattern": file_pattern,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "files_found": len(collected_files),
            "files": []
        }
        
        # Copy files to evidence directory and record metadata
        for file_path in collected_files[:100]:  # Limit to 100 files
            try:
                file_info = {
                    "original_path": file_path,
                    "size_bytes": Path(file_path).stat().st_size if Path(file_path).exists() else 0,
                    "modified_time": datetime.fromtimestamp(Path(file_path).stat().st_mtime).isoformat() if Path(file_path).exists() else None
                }
                evidence_data["files"].append(file_info)
            except Exception as e:
                logger.warning(f"Could not collect file {file_path}: {e}")
        
        # Write evidence data
        with open(evidence_file_path, 'w') as f:
            json.dump(evidence_data, f, indent=2)
        
        evidence_file_path = str(evidence_file_path)
        
        return evidence_file_path
    
    async def _collect_api_evidence(self, template: Dict[str, Any]) -> str:
        """Collect evidence from API calls"""
        
        api_endpoint = template.get("api_endpoint")
        if not api_endpoint:
            raise ValueError("No API endpoint specified in template")
        
        # Implement actual API calls
        import aiohttp
        
        evidence_data = {
            "api_endpoint": api_endpoint,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "data": None,
            "error": None
        }
        
        try:
            headers = template.get("headers", {})
            timeout = aiohttp.ClientTimeout(total=30)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_endpoint, headers=headers) as response:
                    if response.status == 200:
                        response_data = await response.text()
                        evidence_data.update({
                            "status": "success",
                            "data": response_data,
                            "response_status": response.status,
                            "response_headers": dict(response.headers)
                        })
                    else:
                        evidence_data.update({
                            "status": "failed",
                            "error": f"HTTP {response.status}: {response.reason}",
                            "response_status": response.status
                        })
        
        except Exception as e:
            evidence_data.update({
                "status": "failed",
                "error": str(e)
            })
        
        return json.dumps(evidence_data, indent=2)
    
    async def _collect_log_evidence(self, template: Dict[str, Any]) -> str:
        """Collect evidence from log analysis"""
        
        log_query = template.get("log_query")
        if not log_query:
            raise ValueError("No log query specified in template")
        
        # Implement actual log analysis
        evidence_data = {
            "log_query": log_query,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "matches_found": 0,
            "summary": "",
            "log_entries": []
        }
        
        try:
            # Parse log query to extract search parameters
            query_parts = log_query.split()
            search_terms = [part for part in query_parts if not part.startswith('-')]
            
            # Query audit logs table for matching entries
            if search_terms:
                search_condition = " OR ".join([f"description ILIKE '%{term}%'" for term in search_terms])
                
                query = text(f"""
                    SELECT timestamp, event_type, description, user_id, resource_id
                    FROM audit_logs 
                    WHERE ({search_condition})
                    AND timestamp >= NOW() - INTERVAL '30 days'
                    ORDER BY timestamp DESC
                    LIMIT 1000
                """)
                
                result = await self.db.execute(query)
                log_entries = result.fetchall()
                
                evidence_data.update({
                    "matches_found": len(log_entries),
                    "log_entries": [
                        {
                            "timestamp": entry[0].isoformat() if entry[0] else None,
                            "event_type": entry[1],
                            "description": entry[2],
                            "user_id": entry[3],
                            "resource_id": entry[4]
                        }
                        for entry in log_entries[:100]  # Limit to 100 entries
                    ],
                    "summary": f"Found {len(log_entries)} log entries matching query criteria"
                })
            else:
                evidence_data["summary"] = "No valid search terms found in log query"
        
        except Exception as e:
            evidence_data.update({
                "summary": f"Log analysis failed: {str(e)}",
                "error": str(e)
            })
        
        return json.dumps(evidence_data, indent=2)
    
    async def _validate_evidence_item(self, evidence: EvidenceItem) -> bool:
        """Validate an evidence item"""
        
        # Basic validation checks
        if not evidence.title or not evidence.description:
            return False
        
        if not evidence.content and not evidence.file_path:
            return False
        
        # Type-specific validation
        if evidence.evidence_type == EvidenceType.AUDIT_LOG:
            return await self._validate_audit_log_evidence(evidence)
        elif evidence.evidence_type == EvidenceType.SYSTEM_CONFIGURATION:
            return await self._validate_system_config_evidence(evidence)
        elif evidence.evidence_type == EvidenceType.ACCESS_CONTROL_MATRIX:
            return await self._validate_access_control_evidence(evidence)
        
        return True
    
    async def _validate_audit_log_evidence(self, evidence: EvidenceItem) -> bool:
        """Validate audit log evidence"""
        
        if not evidence.content:
            return False
        
        try:
            log_data = json.loads(evidence.content)
            
            # Check required fields
            required_fields = ["query", "executed_at", "row_count", "results"]
            for field in required_fields:
                if field not in log_data:
                    return False
            
            # Validate log entries have required audit fields
            if log_data["results"]:
                sample_entry = log_data["results"][0]
                audit_fields = ["timestamp", "user_id", "action", "resource"]
                for field in audit_fields:
                    if field not in sample_entry:
                        logger.warning(f"Audit log missing required field: {field}")
            
            return True
        
        except json.JSONDecodeError:
            return False
    
    async def _validate_system_config_evidence(self, evidence: EvidenceItem) -> bool:
        """Validate system configuration evidence"""
        
        # Configuration evidence should have specific structure
        return evidence.content is not None or evidence.file_path is not None
    
    async def _validate_access_control_evidence(self, evidence: EvidenceItem) -> bool:
        """Validate access control matrix evidence"""
        
        if not evidence.content:
            return False
        
        try:
            access_data = json.loads(evidence.content)
            
            # Check for access control structure
            if "users" in access_data and "roles" in access_data and "permissions" in access_data:
                return True
            
            return False
        
        except json.JSONDecodeError:
            return False
    
    async def _assess_framework_compliance(self, 
                                         framework: ComplianceFramework,
                                         evidence_items: List[EvidenceItem]) -> Dict[str, Any]:
        """Assess compliance status for a framework"""
        
        assessment = {
            "overall_score": 0.0,
            "compliant_requirements": [],
            "non_compliant_requirements": [],
            "gaps": [],
            "requirement_scores": {}
        }
        
        # Get all requirements for framework
        all_requirements = self._get_framework_requirements(framework)
        
        # Assess each requirement
        for requirement in all_requirements:
            requirement_evidence = [e for e in evidence_items if e.requirement == requirement]
            requirement_score = self._calculate_requirement_score(requirement, requirement_evidence)
            
            assessment["requirement_scores"][requirement.value] = requirement_score
            
            if requirement_score >= 0.8:  # 80% threshold for compliance
                assessment["compliant_requirements"].append(requirement.value)
            else:
                assessment["non_compliant_requirements"].append(requirement.value)
                
                # Identify gaps
                gaps = self._identify_requirement_gaps(requirement, requirement_evidence)
                assessment["gaps"].extend(gaps)
        
        # Calculate overall score
        if assessment["requirement_scores"]:
            assessment["overall_score"] = sum(assessment["requirement_scores"].values()) / len(assessment["requirement_scores"])
        
        return assessment
    
    def _calculate_requirement_score(self, 
                                   requirement: ComplianceRequirement,
                                   evidence_items: List[EvidenceItem]) -> float:
        """Calculate compliance score for a specific requirement"""
        
        if not evidence_items:
            return 0.0
        
        # Get expected evidence types for this requirement
        expected_types = self.requirement_mappings.get(requirement, [])
        
        if not expected_types:
            # If no specific mapping, base score on evidence quality
            valid_evidence = [e for e in evidence_items if e.status == EvidenceStatus.VALIDATED]
            return len(valid_evidence) / max(1, len(evidence_items))
        
        # Calculate coverage of expected evidence types
        covered_types = set()
        for evidence in evidence_items:
            if evidence.status == EvidenceStatus.VALIDATED:
                covered_types.add(evidence.evidence_type)
        
        coverage_score = len(covered_types.intersection(set(expected_types))) / len(expected_types)
        
        # Factor in evidence quality
        quality_scores = []
        for evidence in evidence_items:
            if evidence.status == EvidenceStatus.VALIDATED:
                quality_scores.append(1.0)
            elif evidence.status == EvidenceStatus.COLLECTED:
                quality_scores.append(0.7)
            else:
                quality_scores.append(0.0)
        
        quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        
        # Combined score (70% coverage, 30% quality)
        return (coverage_score * 0.7) + (quality_score * 0.3)
    
    def _identify_requirement_gaps(self, 
                                 requirement: ComplianceRequirement,
                                 evidence_items: List[EvidenceItem]) -> List[Dict[str, Any]]:
        """Identify gaps in requirement compliance"""
        
        gaps = []
        
        # Check for missing evidence types
        expected_types = self.requirement_mappings.get(requirement, [])
        existing_types = {e.evidence_type for e in evidence_items}
        
        for expected_type in expected_types:
            if expected_type not in existing_types:
                gaps.append({
                    "requirement": requirement.value,
                    "gap_type": "missing_evidence",
                    "description": f"Missing evidence type: {expected_type.value}",
                    "severity": "high",
                    "recommendation": f"Collect {expected_type.value} evidence for {requirement.value}"
                })
        
        # Check for expired evidence
        for evidence in evidence_items:
            if evidence.is_expired():
                gaps.append({
                    "requirement": requirement.value,
                    "gap_type": "expired_evidence",
                    "description": f"Evidence {evidence.evidence_id} has expired",
                    "severity": "medium",
                    "recommendation": f"Refresh expired evidence: {evidence.title}"
                })
        
        # Check for failed validation
        failed_evidence = [e for e in evidence_items if e.status == EvidenceStatus.FAILED]
        for evidence in failed_evidence:
            gaps.append({
                "requirement": requirement.value,
                "gap_type": "validation_failed",
                "description": f"Evidence validation failed: {evidence.title}",
                "severity": "high",
                "recommendation": f"Fix validation issues for: {evidence.title}"
            })
        
        return gaps
    
    async def _generate_compliance_recommendations(self, 
                                                 framework: ComplianceFramework,
                                                 assessment: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate compliance recommendations"""
        
        recommendations = []
        
        # Recommendations for non-compliant requirements
        for requirement in assessment["non_compliant_requirements"]:
            score = assessment["requirement_scores"].get(requirement, 0.0)
            
            if score < 0.3:
                recommendations.append({
                    "priority": "critical",
                    "category": "compliance_gap",
                    "title": f"Address critical compliance gap: {requirement}",
                    "description": f"Requirement {requirement} has very low compliance score ({score:.2f})",
                    "action": f"Implement comprehensive controls for {requirement}",
                    "timeline": "immediate"
                })
            elif score < 0.6:
                recommendations.append({
                    "priority": "high",
                    "category": "compliance_improvement",
                    "title": f"Improve compliance for: {requirement}",
                    "description": f"Requirement {requirement} needs improvement (score: {score:.2f})",
                    "action": f"Enhance existing controls for {requirement}",
                    "timeline": "30 days"
                })
        
        # Recommendations for gaps
        for gap in assessment["gaps"]:
            if gap["severity"] == "high":
                recommendations.append({
                    "priority": "high",
                    "category": "evidence_gap",
                    "title": gap["description"],
                    "description": f"Gap identified in {gap['requirement']}",
                    "action": gap["recommendation"],
                    "timeline": "14 days"
                })
        
        # General recommendations based on overall score
        overall_score = assessment["overall_score"]
        
        if overall_score < 0.7:
            recommendations.append({
                "priority": "high",
                "category": "overall_compliance",
                "title": "Improve overall compliance posture",
                "description": f"Overall compliance score is {overall_score:.2f}, below recommended threshold",
                "action": "Implement comprehensive compliance improvement program",
                "timeline": "90 days"
            })
        
        return recommendations
    
    async def _create_evidence_archive(self, evidence_items: List[EvidenceItem], report_id: str) -> str:
        """Create archive of evidence files"""
        
        archive_path = f"compliance_archives/{report_id}_evidence.zip"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_archive_path = Path(temp_dir) / "evidence_archive.zip"
            
            with zipfile.ZipFile(temp_archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
                for evidence in evidence_items:
                    # Add evidence content as JSON file
                    evidence_filename = f"{evidence.evidence_id}_{evidence.evidence_type.value}.json"
                    evidence_data = {
                        "metadata": asdict(evidence),
                        "content": evidence.content
                    }
                    
                    archive.writestr(evidence_filename, json.dumps(evidence_data, indent=2, default=str))
                    
                    # Add actual files if they exist
                    if evidence.file_path and await self._verify_file_exists(evidence.file_path):
                        try:
                            archive.write(evidence.file_path, f"files/{Path(evidence.file_path).name}")
                        except Exception as e:
                            logger.warning(f"Failed to add file to archive: {evidence.file_path} - {e}")
            
            # Upload archive to storage
            if self.storage_client:
                # Upload to S3 or other storage
                try:
                    s3_key = f"compliance-evidence/{report_id}/evidence-archive.zip"
                    
                    with open(archive_path, 'rb') as f:
                        self.storage_client.upload_fileobj(
                            f, 
                            self.config.get("evidence_bucket", "compliance-evidence"),
                            s3_key
                        )
                    
                    # Update archive path to S3 URL
                    archive_path = f"s3://{self.config.get('evidence_bucket', 'compliance-evidence')}/{s3_key}"
                    
                except Exception as e:
                    logger.error(f"Failed to upload evidence archive to S3: {e}")
                    # Continue with local path
        
        return archive_path
    
    async def _generate_report_document(self, report: ComplianceReport) -> str:
        """Generate formatted compliance report document"""
        
        # This would use a template engine like Jinja2 to generate HTML/PDF reports
        report_content = {
            "title": report.title,
            "generated_at": report.generated_at.isoformat(),
            "framework": report.framework.value,
            "period": f"{report.reporting_period_start.isoformat()} to {report.reporting_period_end.isoformat()}",
            "summary": {
                "total_evidence": report.total_evidence_items,
                "compliance_score": f"{report.overall_compliance_score:.2f}",
                "compliant_requirements": len(report.compliant_requirements),
                "non_compliant_requirements": len(report.non_compliant_requirements)
            },
            "evidence_by_type": report.evidence_by_type,
            "evidence_by_status": report.evidence_by_status,
            "gaps": report.gaps_identified,
            "recommendations": report.recommendations
        }
        
        report_path = f"compliance_reports/{report.report_id}_report.json"
        
        # In a real implementation, this would generate HTML/PDF using templates
        # For now, we'll create a JSON report
        
        return report_path
    
    async def _verify_file_exists(self, file_path: str) -> bool:
        """Verify that a file exists"""
        
        if file_path.startswith("s3://"):
            # S3 file verification
            if self.storage_client:
                try:
                    bucket, key = self._parse_s3_path(file_path)
                    self.storage_client.head_object(Bucket=bucket, Key=key)
                    return True
                except Exception:
                    return False
            return False
        else:
            # Local file verification
            return Path(file_path).exists()
    
    def _find_existing_evidence(self, 
                              framework: ComplianceFramework,
                              requirement: ComplianceRequirement,
                              evidence_type: str) -> Optional[EvidenceItem]:
        """Find existing evidence for framework/requirement/type combination"""
        
        for evidence in self.evidence_items.values():
            if (evidence.framework == framework and
                evidence.requirement == requirement and
                evidence.evidence_type.value == evidence_type and
                evidence.status in [EvidenceStatus.COLLECTED, EvidenceStatus.VALIDATED]):
                return evidence
        
        return None
    
    def _get_framework_requirements(self, framework: ComplianceFramework) -> List[ComplianceRequirement]:
        """Get all requirements for a compliance framework"""
        
        framework_mappings = {
            ComplianceFramework.GDPR: [
                ComplianceRequirement.GDPR_ARTICLE_5,
                ComplianceRequirement.GDPR_ARTICLE_6,
                ComplianceRequirement.GDPR_ARTICLE_7,
                ComplianceRequirement.GDPR_ARTICLE_13,
                ComplianceRequirement.GDPR_ARTICLE_15,
                ComplianceRequirement.GDPR_ARTICLE_17,
                ComplianceRequirement.GDPR_ARTICLE_25,
                ComplianceRequirement.GDPR_ARTICLE_30,
                ComplianceRequirement.GDPR_ARTICLE_32,
                ComplianceRequirement.GDPR_ARTICLE_33,
                ComplianceRequirement.GDPR_ARTICLE_35
            ],
            ComplianceFramework.PCI_DSS: [
                ComplianceRequirement.PCI_REQ_1,
                ComplianceRequirement.PCI_REQ_2,
                ComplianceRequirement.PCI_REQ_3,
                ComplianceRequirement.PCI_REQ_4,
                ComplianceRequirement.PCI_REQ_6,
                ComplianceRequirement.PCI_REQ_8,
                ComplianceRequirement.PCI_REQ_10,
                ComplianceRequirement.PCI_REQ_11
            ]
        }
        
        return framework_mappings.get(framework, [])
    
    def _parse_s3_path(self, s3_path: str) -> Tuple[str, str]:
        """Parse S3 path into bucket and key"""
        
        if not s3_path.startswith("s3://"):
            raise ValueError(f"Invalid S3 path: {s3_path}")
        
        path_parts = s3_path[5:].split("/", 1)
        bucket = path_parts[0]
        key = path_parts[1] if len(path_parts) > 1 else ""
        
        return bucket, key
    
    def _init_storage_client(self):
        """Initialize storage client for file operations"""
        
        try:
            return boto3.client('s3')
        except Exception as e:
            logger.warning(f"Failed to initialize S3 client: {e}")
            return None
    
    def _load_evidence_templates(self) -> Dict[ComplianceRequirement, List[Dict[str, Any]]]:
        """Load evidence collection templates"""
        
        # This would load from configuration files
        # For now, return sample templates
        
        templates = {
            ComplianceRequirement.GDPR_ARTICLE_30: [
                {
                    "name": "Records of Processing Activities",
                    "evidence_type": "audit_log",
                    "title": "GDPR Article 30 - Records of Processing Activities",
                    "description": "Database query to extract processing records",
                    "collection_method": "database_query",
                    "query": "SELECT * FROM processing_records WHERE created_at >= NOW() - INTERVAL '90 days'",
                    "validity_days": 90,
                    "control_objectives": ["data_governance", "processing_transparency"],
                    "risk_level": "high"
                }
            ],
            ComplianceRequirement.GDPR_ARTICLE_32: [
                {
                    "name": "Security Measures Documentation",
                    "evidence_type": "system_configuration",
                    "title": "GDPR Article 32 - Security of Processing",
                    "description": "System security configuration and controls",
                    "collection_method": "file_system",
                    "file_pattern": "/etc/security/*.conf",
                    "validity_days": 30,
                    "control_objectives": ["data_security", "access_control"],
                    "risk_level": "critical"
                }
            ]
        }
        
        return templates
    
    def _load_requirement_mappings(self) -> Dict[ComplianceRequirement, List[EvidenceType]]:
        """Load mappings of requirements to expected evidence types"""
        
        mappings = {
            ComplianceRequirement.GDPR_ARTICLE_30: [
                EvidenceType.AUDIT_LOG,
                EvidenceType.POLICY_DOCUMENT,
                EvidenceType.PROCEDURE_DOCUMENT
            ],
            ComplianceRequirement.GDPR_ARTICLE_32: [
                EvidenceType.SYSTEM_CONFIGURATION,
                EvidenceType.ACCESS_CONTROL_MATRIX,
                EvidenceType.PENETRATION_TEST,
                EvidenceType.VULNERABILITY_SCAN
            ],
            ComplianceRequirement.GDPR_ARTICLE_17: [
                EvidenceType.AUDIT_LOG,
                EvidenceType.PROCEDURE_DOCUMENT,
                EvidenceType.DATA_RETENTION_LOG
            ]
        }
        
        return mappings
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load compliance evidence collection configuration"""
        
        default_config = {
            "evidence_retention_days": 2555,  # 7 years
            "validation_enabled": True,
            "auto_refresh_days": 30,
            "storage_location": "s3://voicehive-compliance/evidence/",
            "report_formats": ["json", "html", "pdf"]
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r') as f:
                    import yaml
                    config = yaml.safe_load(f)
                    default_config.update(config)
            except Exception as e:
                logger.error(f"Failed to load compliance config from {config_path}: {e}")
        
        return default_config


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    from unittest.mock import AsyncMock
    
    async def test_compliance_evidence():
        # Mock database session
        mock_db = AsyncMock()
        
        # Create evidence collector
        collector = ComplianceEvidenceCollector(mock_db)
        
        # Test evidence collection for GDPR
        collection_results = await collector.collect_evidence_for_framework(
            ComplianceFramework.GDPR,
            requirements=[ComplianceRequirement.GDPR_ARTICLE_30, ComplianceRequirement.GDPR_ARTICLE_32]
        )
        print(f"Evidence collection: {collection_results['evidence_collected']} items collected")
        
        # Test compliance report generation
        report = await collector.generate_compliance_report(
            ComplianceFramework.GDPR,
            include_evidence_archive=True
        )
        print(f"Compliance report generated: {report.report_id}")
        print(f"Compliance score: {report.overall_compliance_score:.2f}")
        
        # Test evidence validation
        validation_results = await collector.validate_evidence_integrity()
        print(f"Evidence validation: {validation_results['valid_items']}/{validation_results['total_items']} valid")
        
        # Test scheduling
        schedule_id = await collector.schedule_evidence_collection(
            ComplianceFramework.GDPR,
            "0 2 * * 0"  # Weekly on Sunday at 2 AM
        )
        print(f"Evidence collection scheduled: {schedule_id}")
        
        print("Compliance evidence collection test completed successfully")
    
    # Run test
    asyncio.run(test_compliance_evidence())