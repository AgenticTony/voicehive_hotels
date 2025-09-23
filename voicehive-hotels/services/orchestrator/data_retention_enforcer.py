"""
Data Retention Enforcement System for VoiceHive Hotels
Automated enforcement of data retention policies with configurable rules and monitoring
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Set, Callable, Tuple
from enum import Enum
from dataclasses import dataclass, asdict
from pathlib import Path
import uuid
import crontab

from pydantic import BaseModel, Field, validator
from sqlalchemy import text, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
import boto3
from botocore.exceptions import ClientError

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger, AuditEventType, AuditSeverity
from gdpr_compliance_manager import GDPRLawfulBasis, ProcessingStatus

logger = get_safe_logger("orchestrator.data_retention")


class RetentionAction(str, Enum):
    """Actions to take when data retention period expires"""
    DELETE = "delete"
    ARCHIVE = "archive"
    ANONYMIZE = "anonymize"
    NOTIFY = "notify"
    QUARANTINE = "quarantine"


class DataCategory(str, Enum):
    """Categories of data for retention policies"""
    CALL_RECORDINGS = "call_recordings"
    TRANSCRIPTS = "transcripts"
    METADATA = "metadata"
    PII_DATA = "pii_data"
    AUDIT_LOGS = "audit_logs"
    SYSTEM_LOGS = "system_logs"
    BUSINESS_DATA = "business_data"
    ANALYTICS_DATA = "analytics_data"


class RetentionStatus(str, Enum):
    """Status of retention enforcement"""
    ACTIVE = "active"
    EXPIRED = "expired"
    PROCESSING = "processing"
    ARCHIVED = "archived"
    DELETED = "deleted"
    FAILED = "failed"


@dataclass
class RetentionPolicy:
    """Data retention policy configuration"""
    policy_id: str
    name: str
    description: str
    data_category: DataCategory
    retention_period_days: int
    action: RetentionAction
    lawful_basis: GDPRLawfulBasis
    
    # Storage configuration
    storage_locations: List[str]
    archive_location: Optional[str] = None
    
    # Conditions
    conditions: Dict[str, Any] = None
    exceptions: List[str] = None
    
    # Scheduling
    enforcement_schedule: str = "0 2 * * *"  # Daily at 2 AM
    batch_size: int = 1000
    
    # Notifications
    notify_before_days: int = 7
    notification_recipients: List[str] = None
    
    # Compliance
    regulatory_requirements: List[str] = None
    audit_required: bool = True
    
    created_at: datetime = None
    updated_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.updated_at is None:
            self.updated_at = datetime.now(timezone.utc)
        if self.conditions is None:
            self.conditions = {}
        if self.exceptions is None:
            self.exceptions = []
        if self.notification_recipients is None:
            self.notification_recipients = []
        if self.regulatory_requirements is None:
            self.regulatory_requirements = []


@dataclass
class RetentionRecord:
    """Individual data record subject to retention policy"""
    record_id: str
    data_subject_id: Optional[str]
    data_category: DataCategory
    policy_id: str
    
    # Timestamps
    created_at: datetime
    expires_at: datetime
    last_accessed: Optional[datetime] = None
    
    # Status
    status: RetentionStatus = RetentionStatus.ACTIVE
    
    # Storage information
    storage_location: str = ""
    file_paths: List[str] = None
    database_tables: List[str] = None
    
    # Metadata
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None
    encryption_key_id: Optional[str] = None
    
    # Processing
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.file_paths is None:
            self.file_paths = []
        if self.database_tables is None:
            self.database_tables = []
    
    def is_expired(self) -> bool:
        """Check if record has expired"""
        return datetime.now(timezone.utc) > self.expires_at
    
    def days_until_expiry(self) -> int:
        """Calculate days until expiry"""
        delta = self.expires_at - datetime.now(timezone.utc)
        return max(0, delta.days)


class DataRetentionEnforcer:
    """Automated data retention enforcement system"""
    
    def __init__(self, 
                 db_session: AsyncSession,
                 audit_logger: Optional[AuditLogger] = None,
                 config_path: Optional[str] = None):
        self.db = db_session
        self.audit_logger = audit_logger or AuditLogger()
        
        # Load configuration
        self.config = self._load_config(config_path)
        
        # Initialize storage clients
        self.s3_client = self._init_s3_client()
        
        # Policy and record storage
        self.policies: Dict[str, RetentionPolicy] = {}
        self.records: Dict[str, RetentionRecord] = {}
        
        # Statistics
        self.enforcement_stats = {
            "last_run": None,
            "records_processed": 0,
            "records_deleted": 0,
            "records_archived": 0,
            "errors": 0
        }
        
        # Load default policies
        self._load_default_policies()
    
    async def create_retention_policy(self, policy: RetentionPolicy) -> RetentionPolicy:
        """Create a new data retention policy"""
        
        self.policies[policy.policy_id] = policy
        
        # Store in database
        await self._store_retention_policy(policy)
        
        # Audit policy creation
        self.audit_logger.log_event(
            event_type=AuditEventType.CONFIG_CHANGE,
            description=f"Retention policy created: {policy.name}",
            severity=AuditSeverity.MEDIUM,
            resource_type="retention_policy",
            resource_id=policy.policy_id,
            action="create",
            metadata={
                "policy_name": policy.name,
                "data_category": policy.data_category.value,
                "retention_days": policy.retention_period_days,
                "action": policy.action.value
            },
            gdpr_lawful_basis=policy.lawful_basis.value,
            retention_period=2555
        )
        
        logger.info(f"Retention policy created: {policy.policy_id} - {policy.name}")
        return policy
    
    async def register_data_record(self,
                                 record_id: str,
                                 data_category: DataCategory,
                                 policy_id: str,
                                 data_subject_id: Optional[str] = None,
                                 storage_location: str = "",
                                 file_paths: List[str] = None,
                                 database_tables: List[str] = None) -> RetentionRecord:
        """Register a data record for retention tracking"""
        
        # Get policy
        policy = self.policies.get(policy_id)
        if not policy:
            raise ValueError(f"Retention policy not found: {policy_id}")
        
        # Calculate expiry date
        created_at = datetime.now(timezone.utc)
        expires_at = created_at + timedelta(days=policy.retention_period_days)
        
        # Create retention record
        record = RetentionRecord(
            record_id=record_id,
            data_subject_id=data_subject_id,
            data_category=data_category,
            policy_id=policy_id,
            created_at=created_at,
            expires_at=expires_at,
            storage_location=storage_location,
            file_paths=file_paths or [],
            database_tables=database_tables or []
        )
        
        self.records[record_id] = record
        
        # Store in database
        await self._store_retention_record(record)
        
        # Audit record registration
        self.audit_logger.log_event(
            event_type=AuditEventType.DATA_CREATE,
            description=f"Data record registered for retention: {record_id}",
            severity=AuditSeverity.LOW,
            resource_type="retention_record",
            resource_id=record_id,
            action="register",
            metadata={
                "data_category": data_category.value,
                "policy_id": policy_id,
                "expires_at": expires_at.isoformat()
            },
            gdpr_lawful_basis=policy.lawful_basis.value,
            data_subject_id=data_subject_id,
            retention_period=policy.retention_period_days
        )
        
        logger.info(f"Data record registered: {record_id} (expires: {expires_at})")
        return record
    
    async def enforce_retention_policies(self, 
                                       policy_ids: Optional[List[str]] = None,
                                       dry_run: bool = False) -> Dict[str, Any]:
        """Enforce retention policies for expired data"""
        
        enforcement_start = datetime.now(timezone.utc)
        
        results = {
            "started_at": enforcement_start.isoformat(),
            "dry_run": dry_run,
            "policies_processed": 0,
            "records_processed": 0,
            "actions_taken": {
                "deleted": 0,
                "archived": 0,
                "anonymized": 0,
                "quarantined": 0
            },
            "errors": [],
            "notifications_sent": 0
        }
        
        try:
            # Get policies to process
            policies_to_process = []
            if policy_ids:
                policies_to_process = [self.policies[pid] for pid in policy_ids if pid in self.policies]
            else:
                policies_to_process = list(self.policies.values())
            
            results["policies_processed"] = len(policies_to_process)
            
            # Process each policy
            for policy in policies_to_process:
                try:
                    policy_results = await self._enforce_policy(policy, dry_run)
                    
                    # Aggregate results
                    results["records_processed"] += policy_results["records_processed"]
                    for action, count in policy_results["actions_taken"].items():
                        results["actions_taken"][action] += count
                    results["notifications_sent"] += policy_results["notifications_sent"]
                    results["errors"].extend(policy_results["errors"])
                    
                except Exception as e:
                    error_msg = f"Failed to enforce policy {policy.policy_id}: {e}"
                    results["errors"].append(error_msg)
                    logger.error(error_msg)
            
            results["completed_at"] = datetime.now(timezone.utc).isoformat()
            results["duration_seconds"] = (datetime.now(timezone.utc) - enforcement_start).total_seconds()
            results["status"] = "success" if not results["errors"] else "partial_success"
            
            # Update statistics
            if not dry_run:
                self.enforcement_stats.update({
                    "last_run": enforcement_start,
                    "records_processed": self.enforcement_stats["records_processed"] + results["records_processed"],
                    "records_deleted": self.enforcement_stats["records_deleted"] + results["actions_taken"]["deleted"],
                    "records_archived": self.enforcement_stats["records_archived"] + results["actions_taken"]["archived"],
                    "errors": self.enforcement_stats["errors"] + len(results["errors"])
                })
            
            # Audit enforcement run
            self.audit_logger.log_event(
                event_type=AuditEventType.ADMIN_ACTION,
                description=f"Data retention enforcement {'(dry run)' if dry_run else 'completed'}",
                severity=AuditSeverity.HIGH,
                resource_type="retention_enforcement",
                action="enforce",
                success=results["status"] == "success",
                metadata=results,
                gdpr_lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS.value,
                retention_period=2555
            )
            
            logger.info(f"Retention enforcement completed: {results['records_processed']} records processed")
            
        except Exception as e:
            results["status"] = "failed"
            results["error"] = str(e)
            results["completed_at"] = datetime.now(timezone.utc).isoformat()
            
            logger.error(f"Retention enforcement failed: {e}")
            raise
        
        return results
    
    async def check_expiring_data(self, days_ahead: int = 7) -> Dict[str, Any]:
        """Check for data that will expire within specified days"""
        
        cutoff_date = datetime.now(timezone.utc) + timedelta(days=days_ahead)
        
        expiring_records = []
        for record in self.records.values():
            if (record.status == RetentionStatus.ACTIVE and 
                record.expires_at <= cutoff_date and 
                not record.is_expired()):
                
                expiring_records.append({
                    "record_id": record.record_id,
                    "data_category": record.data_category.value,
                    "expires_at": record.expires_at.isoformat(),
                    "days_until_expiry": record.days_until_expiry(),
                    "policy_id": record.policy_id,
                    "data_subject_id": record.data_subject_id
                })
        
        # Group by policy for notification
        by_policy = {}
        for record in expiring_records:
            policy_id = record["policy_id"]
            if policy_id not in by_policy:
                by_policy[policy_id] = []
            by_policy[policy_id].append(record)
        
        results = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "days_ahead": days_ahead,
            "total_expiring": len(expiring_records),
            "by_policy": by_policy,
            "expiring_records": expiring_records
        }
        
        # Send notifications if configured
        notifications_sent = 0
        for policy_id, records in by_policy.items():
            policy = self.policies.get(policy_id)
            if policy and policy.notification_recipients:
                try:
                    await self._send_expiry_notification(policy, records)
                    notifications_sent += 1
                except Exception as e:
                    logger.error(f"Failed to send expiry notification for policy {policy_id}: {e}")
        
        results["notifications_sent"] = notifications_sent
        
        logger.info(f"Expiry check completed: {len(expiring_records)} records expiring in {days_ahead} days")
        return results
    
    async def get_retention_statistics(self) -> Dict[str, Any]:
        """Get comprehensive retention statistics"""
        
        stats = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_policies": len(self.policies),
            "total_records": len(self.records),
            "enforcement_stats": self.enforcement_stats.copy(),
            "by_status": {},
            "by_category": {},
            "by_policy": {},
            "expired_records": 0,
            "expiring_soon": 0  # Within 30 days
        }
        
        cutoff_date = datetime.now(timezone.utc) + timedelta(days=30)
        
        for record in self.records.values():
            # Count by status
            status = record.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
            
            # Count by category
            category = record.data_category.value
            stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
            
            # Count by policy
            policy_id = record.policy_id
            stats["by_policy"][policy_id] = stats["by_policy"].get(policy_id, 0) + 1
            
            # Count expired and expiring
            if record.is_expired():
                stats["expired_records"] += 1
            elif record.expires_at <= cutoff_date:
                stats["expiring_soon"] += 1
        
        # Add policy details
        stats["policies"] = {}
        for policy_id, policy in self.policies.items():
            stats["policies"][policy_id] = {
                "name": policy.name,
                "data_category": policy.data_category.value,
                "retention_days": policy.retention_period_days,
                "action": policy.action.value,
                "record_count": stats["by_policy"].get(policy_id, 0)
            }
        
        return stats
    
    async def _enforce_policy(self, policy: RetentionPolicy, dry_run: bool = False) -> Dict[str, Any]:
        """Enforce a specific retention policy"""
        
        policy_results = {
            "policy_id": policy.policy_id,
            "policy_name": policy.name,
            "records_processed": 0,
            "actions_taken": {
                "deleted": 0,
                "archived": 0,
                "anonymized": 0,
                "quarantined": 0
            },
            "errors": [],
            "notifications_sent": 0
        }
        
        # Get expired records for this policy
        expired_records = [
            record for record in self.records.values()
            if (record.policy_id == policy.policy_id and 
                record.is_expired() and 
                record.status == RetentionStatus.ACTIVE)
        ]
        
        policy_results["records_processed"] = len(expired_records)
        
        # Process records in batches
        batch_size = policy.batch_size
        for i in range(0, len(expired_records), batch_size):
            batch = expired_records[i:i + batch_size]
            
            for record in batch:
                try:
                    if not dry_run:
                        record.status = RetentionStatus.PROCESSING
                        record.processing_started_at = datetime.now(timezone.utc)
                        await self._update_retention_record(record)
                    
                    # Execute retention action
                    action_result = await self._execute_retention_action(policy, record, dry_run)
                    
                    if action_result["success"]:
                        policy_results["actions_taken"][policy.action.value] += 1
                        
                        if not dry_run:
                            record.status = getattr(RetentionStatus, policy.action.value.upper(), RetentionStatus.DELETED)
                            record.processing_completed_at = datetime.now(timezone.utc)
                            await self._update_retention_record(record)
                    else:
                        policy_results["errors"].append(action_result["error"])
                        
                        if not dry_run:
                            record.status = RetentionStatus.FAILED
                            record.error_message = action_result["error"]
                            await self._update_retention_record(record)
                
                except Exception as e:
                    error_msg = f"Failed to process record {record.record_id}: {e}"
                    policy_results["errors"].append(error_msg)
                    logger.error(error_msg)
        
        return policy_results
    
    async def _execute_retention_action(self, 
                                      policy: RetentionPolicy, 
                                      record: RetentionRecord, 
                                      dry_run: bool = False) -> Dict[str, Any]:
        """Execute the retention action for a specific record"""
        
        result = {"success": False, "error": None, "details": {}}
        
        try:
            if policy.action == RetentionAction.DELETE:
                result = await self._delete_record_data(record, dry_run)
            
            elif policy.action == RetentionAction.ARCHIVE:
                result = await self._archive_record_data(record, policy.archive_location, dry_run)
            
            elif policy.action == RetentionAction.ANONYMIZE:
                result = await self._anonymize_record_data(record, dry_run)
            
            elif policy.action == RetentionAction.QUARANTINE:
                result = await self._quarantine_record_data(record, dry_run)
            
            elif policy.action == RetentionAction.NOTIFY:
                result = await self._notify_record_expiry(record, policy, dry_run)
            
            else:
                result["error"] = f"Unknown retention action: {policy.action}"
            
            # Audit the action
            if not dry_run and result["success"]:
                self.audit_logger.log_event(
                    event_type=AuditEventType.DATA_DELETE if policy.action == RetentionAction.DELETE else AuditEventType.ADMIN_ACTION,
                    description=f"Retention action executed: {policy.action.value} on {record.record_id}",
                    severity=AuditSeverity.HIGH,
                    resource_type="retention_record",
                    resource_id=record.record_id,
                    action=policy.action.value,
                    success=result["success"],
                    metadata={
                        "policy_id": policy.policy_id,
                        "data_category": record.data_category.value,
                        "action_details": result["details"]
                    },
                    gdpr_lawful_basis=policy.lawful_basis.value,
                    data_subject_id=record.data_subject_id
                )
        
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Retention action failed for record {record.record_id}: {e}")
        
        return result
    
    async def _delete_record_data(self, record: RetentionRecord, dry_run: bool = False) -> Dict[str, Any]:
        """Delete data for a retention record"""
        
        result = {"success": True, "error": None, "details": {"files_deleted": [], "tables_updated": []}}
        
        try:
            # Delete files from storage
            for file_path in record.file_paths:
                if dry_run:
                    result["details"]["files_deleted"].append(f"[DRY RUN] {file_path}")
                else:
                    if file_path.startswith("s3://"):
                        # S3 deletion
                        bucket, key = self._parse_s3_path(file_path)
                        self.s3_client.delete_object(Bucket=bucket, Key=key)
                        result["details"]["files_deleted"].append(file_path)
                    else:
                        # Local file deletion
                        Path(file_path).unlink(missing_ok=True)
                        result["details"]["files_deleted"].append(file_path)
            
            # Delete from database tables
            for table in record.database_tables:
                if dry_run:
                    result["details"]["tables_updated"].append(f"[DRY RUN] DELETE FROM {table}")
                else:
                    query = text(f"DELETE FROM {table} WHERE record_id = :record_id")
                    await self.db.execute(query, {"record_id": record.record_id})
                    result["details"]["tables_updated"].append(table)
            
            if not dry_run:
                await self.db.commit()
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
        
        return result
    
    async def _archive_record_data(self, 
                                 record: RetentionRecord, 
                                 archive_location: Optional[str], 
                                 dry_run: bool = False) -> Dict[str, Any]:
        """Archive data for a retention record"""
        
        result = {"success": True, "error": None, "details": {"files_archived": [], "archive_location": archive_location}}
        
        if not archive_location:
            result["error"] = "No archive location specified"
            result["success"] = False
            return result
        
        try:
            # Archive files
            for file_path in record.file_paths:
                if dry_run:
                    archive_path = f"{archive_location}/{record.record_id}/{Path(file_path).name}"
                    result["details"]["files_archived"].append(f"[DRY RUN] {file_path} -> {archive_path}")
                else:
                    # Move to archive location (implementation depends on storage type)
                    archive_path = await self._move_to_archive(file_path, archive_location, record.record_id)
                    result["details"]["files_archived"].append(f"{file_path} -> {archive_path}")
            
            # Update database records to mark as archived
            if not dry_run:
                for table in record.database_tables:
                    query = text(f"UPDATE {table} SET archived = true, archived_at = :archived_at WHERE record_id = :record_id")
                    await self.db.execute(query, {
                        "record_id": record.record_id,
                        "archived_at": datetime.now(timezone.utc)
                    })
                
                await self.db.commit()
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
        
        return result
    
    async def _anonymize_record_data(self, record: RetentionRecord, dry_run: bool = False) -> Dict[str, Any]:
        """Anonymize data for a retention record"""
        
        result = {"success": True, "error": None, "details": {"tables_anonymized": [], "fields_anonymized": []}}
        
        try:
            # Anonymization mapping for different data types
            anonymization_fields = {
                "email": "anonymized_email_" + str(uuid.uuid4())[:8] + "@anonymized.local",
                "phone": "+1-XXX-XXX-XXXX",
                "name": "Anonymized User",
                "ip_address": "0.0.0.0",
                "user_agent": "Anonymized Browser"
            }
            
            # Anonymize database records
            for table in record.database_tables:
                if dry_run:
                    result["details"]["tables_anonymized"].append(f"[DRY RUN] {table}")
                else:
                    # Update PII fields with anonymized values
                    for field, anon_value in anonymization_fields.items():
                        try:
                            query = text(f"UPDATE {table} SET {field} = :anon_value WHERE record_id = :record_id")
                            await self.db.execute(query, {
                                "record_id": record.record_id,
                                "anon_value": anon_value
                            })
                            result["details"]["fields_anonymized"].append(f"{table}.{field}")
                        except Exception:
                            # Field might not exist in this table, continue
                            pass
                    
                    result["details"]["tables_anonymized"].append(table)
            
            if not dry_run:
                await self.db.commit()
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
        
        return result
    
    async def _quarantine_record_data(self, record: RetentionRecord, dry_run: bool = False) -> Dict[str, Any]:
        """Quarantine data for manual review"""
        
        result = {"success": True, "error": None, "details": {"quarantine_location": "", "files_quarantined": []}}
        
        quarantine_location = f"quarantine/{record.data_category.value}/{record.record_id}"
        result["details"]["quarantine_location"] = quarantine_location
        
        try:
            # Move files to quarantine
            for file_path in record.file_paths:
                if dry_run:
                    quarantine_path = f"{quarantine_location}/{Path(file_path).name}"
                    result["details"]["files_quarantined"].append(f"[DRY RUN] {file_path} -> {quarantine_path}")
                else:
                    quarantine_path = await self._move_to_quarantine(file_path, quarantine_location)
                    result["details"]["files_quarantined"].append(f"{file_path} -> {quarantine_path}")
            
            # Mark database records as quarantined
            if not dry_run:
                for table in record.database_tables:
                    query = text(f"UPDATE {table} SET quarantined = true, quarantined_at = :quarantined_at WHERE record_id = :record_id")
                    await self.db.execute(query, {
                        "record_id": record.record_id,
                        "quarantined_at": datetime.now(timezone.utc)
                    })
                
                await self.db.commit()
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
        
        return result
    
    async def _notify_record_expiry(self, 
                                  record: RetentionRecord, 
                                  policy: RetentionPolicy, 
                                  dry_run: bool = False) -> Dict[str, Any]:
        """Send notification about record expiry"""
        
        result = {"success": True, "error": None, "details": {"notifications_sent": []}}
        
        try:
            notification_data = {
                "record_id": record.record_id,
                "data_category": record.data_category.value,
                "policy_name": policy.name,
                "expired_at": record.expires_at.isoformat(),
                "data_subject_id": record.data_subject_id
            }
            
            for recipient in policy.notification_recipients:
                if dry_run:
                    result["details"]["notifications_sent"].append(f"[DRY RUN] {recipient}")
                else:
                    # Send notification (email, webhook, etc.)
                    await self._send_notification(recipient, "Data Retention Expiry", notification_data)
                    result["details"]["notifications_sent"].append(recipient)
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
        
        return result
    
    def _load_default_policies(self):
        """Load default retention policies"""
        
        default_policies = [
            RetentionPolicy(
                policy_id="call_recordings_30d",
                name="Call Recordings - 30 Days",
                description="Standard retention for call recordings",
                data_category=DataCategory.CALL_RECORDINGS,
                retention_period_days=30,
                action=RetentionAction.DELETE,
                lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS,
                storage_locations=["s3://voicehive-recordings/", "/var/data/recordings/"],
                archive_location="s3://voicehive-archive/recordings/",
                regulatory_requirements=["GDPR", "CCPA"]
            ),
            
            RetentionPolicy(
                policy_id="transcripts_90d",
                name="Call Transcripts - 90 Days",
                description="Extended retention for call transcripts",
                data_category=DataCategory.TRANSCRIPTS,
                retention_period_days=90,
                action=RetentionAction.ANONYMIZE,
                lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS,
                storage_locations=["database"],
                regulatory_requirements=["GDPR"]
            ),
            
            RetentionPolicy(
                policy_id="audit_logs_7y",
                name="Audit Logs - 7 Years",
                description="Long-term retention for audit logs",
                data_category=DataCategory.AUDIT_LOGS,
                retention_period_days=2555,  # 7 years
                action=RetentionAction.ARCHIVE,
                lawful_basis=GDPRLawfulBasis.LEGAL_OBLIGATION,
                storage_locations=["database", "s3://voicehive-audit-logs/"],
                archive_location="s3://voicehive-archive/audit/",
                regulatory_requirements=["GDPR", "SOX", "PCI-DSS"]
            ),
            
            RetentionPolicy(
                policy_id="pii_data_1y",
                name="PII Data - 1 Year",
                description="Personal data retention",
                data_category=DataCategory.PII_DATA,
                retention_period_days=365,
                action=RetentionAction.DELETE,
                lawful_basis=GDPRLawfulBasis.CONSENT,
                storage_locations=["database"],
                notify_before_days=30,
                regulatory_requirements=["GDPR", "CCPA"]
            )
        ]
        
        for policy in default_policies:
            self.policies[policy.policy_id] = policy
    
    def _init_s3_client(self):
        """Initialize S3 client for file operations"""
        try:
            return boto3.client('s3')
        except Exception as e:
            logger.warning(f"Failed to initialize S3 client: {e}")
            return None
    
    def _parse_s3_path(self, s3_path: str) -> Tuple[str, str]:
        """Parse S3 path into bucket and key"""
        if not s3_path.startswith("s3://"):
            raise ValueError(f"Invalid S3 path: {s3_path}")
        
        path_parts = s3_path[5:].split("/", 1)
        bucket = path_parts[0]
        key = path_parts[1] if len(path_parts) > 1 else ""
        
        return bucket, key
    
    async def _move_to_archive(self, file_path: str, archive_location: str, record_id: str) -> str:
        """Move file to archive location"""
        # Implementation depends on storage type (S3, local filesystem, etc.)
        # This is a placeholder
        archive_path = f"{archive_location}/{record_id}/{Path(file_path).name}"
        return archive_path
    
    async def _move_to_quarantine(self, file_path: str, quarantine_location: str) -> str:
        """Move file to quarantine location"""
        # Implementation depends on storage type
        # This is a placeholder
        quarantine_path = f"{quarantine_location}/{Path(file_path).name}"
        return quarantine_path
    
    async def _send_notification(self, recipient: str, subject: str, data: Dict[str, Any]):
        """Send notification to recipient"""
        # Implementation would send actual notifications (email, webhook, etc.)
        logger.info(f"Notification sent to {recipient}: {subject}")
    
    async def _send_expiry_notification(self, policy: RetentionPolicy, expiring_records: List[Dict[str, Any]]):
        """Send notification about expiring records"""
        # Implementation would send actual notifications
        logger.info(f"Expiry notification sent for policy {policy.policy_id}: {len(expiring_records)} records")
    
    async def _store_retention_policy(self, policy: RetentionPolicy):
        """Store retention policy in database"""
        try:
            query = text("""
                INSERT INTO data_retention_policies 
                (policy_id, name, description, data_category, retention_period_days, 
                 action, lawful_basis, storage_locations, archive_location, 
                 conditions, exceptions, enforcement_schedule, batch_size, 
                 notify_before_days, notification_recipients, regulatory_requirements, 
                 audit_required, created_at, updated_at)
                VALUES (:policy_id, :name, :description, :data_category, :retention_period_days,
                        :action, :lawful_basis, :storage_locations, :archive_location,
                        :conditions, :exceptions, :enforcement_schedule, :batch_size,
                        :notify_before_days, :notification_recipients, :regulatory_requirements,
                        :audit_required, :created_at, :updated_at)
            """)
            
            await self.db.execute(query, {
                "policy_id": policy.policy_id,
                "name": policy.name,
                "description": policy.description,
                "data_category": policy.data_category.value,
                "retention_period_days": policy.retention_period_days,
                "action": policy.action.value,
                "lawful_basis": policy.lawful_basis.value,
                "storage_locations": json.dumps(policy.storage_locations),
                "archive_location": policy.archive_location,
                "conditions": json.dumps(policy.conditions),
                "exceptions": json.dumps(policy.exceptions),
                "enforcement_schedule": policy.enforcement_schedule,
                "batch_size": policy.batch_size,
                "notify_before_days": policy.notify_before_days,
                "notification_recipients": json.dumps(policy.notification_recipients),
                "regulatory_requirements": json.dumps(policy.regulatory_requirements),
                "audit_required": policy.audit_required,
                "created_at": policy.created_at,
                "updated_at": policy.updated_at
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to store retention policy {policy.policy_id}: {e}")
            await self.db.rollback()
            raise
    
    async def _store_retention_record(self, record: RetentionRecord):
        """Store retention record in database"""
        try:
            query = text("""
                INSERT INTO data_retention_records 
                (record_id, data_subject_id, data_category, policy_id, created_at, 
                 expires_at, last_accessed, status, storage_location, file_paths, 
                 database_tables, size_bytes, checksum, encryption_key_id)
                VALUES (:record_id, :data_subject_id, :data_category, :policy_id, :created_at,
                        :expires_at, :last_accessed, :status, :storage_location, :file_paths,
                        :database_tables, :size_bytes, :checksum, :encryption_key_id)
            """)
            
            await self.db.execute(query, {
                "record_id": record.record_id,
                "data_subject_id": record.data_subject_id,
                "data_category": record.data_category.value,
                "policy_id": record.policy_id,
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "last_accessed": record.last_accessed,
                "status": record.status.value,
                "storage_location": record.storage_location,
                "file_paths": json.dumps(record.file_paths),
                "database_tables": json.dumps(record.database_tables),
                "size_bytes": record.size_bytes,
                "checksum": record.checksum,
                "encryption_key_id": record.encryption_key_id
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to store retention record {record.record_id}: {e}")
            await self.db.rollback()
            raise
    
    async def _update_retention_record(self, record: RetentionRecord):
        """Update retention record in database"""
        try:
            query = text("""
                UPDATE data_retention_records 
                SET status = :status,
                    last_accessed = :last_accessed,
                    processing_started_at = :processing_started_at,
                    processing_completed_at = :processing_completed_at,
                    error_message = :error_message,
                    updated_at = :updated_at
                WHERE record_id = :record_id
            """)
            
            await self.db.execute(query, {
                "record_id": record.record_id,
                "status": record.status.value,
                "last_accessed": record.last_accessed,
                "processing_started_at": record.processing_started_at,
                "processing_completed_at": record.processing_completed_at,
                "error_message": record.error_message,
                "updated_at": datetime.now(timezone.utc)
            })
            
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to update retention record {record.record_id}: {e}")
            await self.db.rollback()
            raise
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load retention configuration"""
        
        default_config = {
            "enforcement_schedule": "0 2 * * *",  # Daily at 2 AM
            "batch_size": 1000,
            "notification_settings": {
                "smtp_server": "localhost",
                "from_address": "noreply@voicehive.com"
            },
            "storage_settings": {
                "s3_bucket": "voicehive-data",
                "archive_bucket": "voicehive-archive"
            }
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r') as f:
                    import yaml
                    config = yaml.safe_load(f)
                    default_config.update(config)
            except Exception as e:
                logger.error(f"Failed to load retention config from {config_path}: {e}")
        
        return default_config


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    from unittest.mock import AsyncMock
    
    async def test_data_retention():
        # Mock database session
        mock_db = AsyncMock()
        
        # Create retention enforcer
        enforcer = DataRetentionEnforcer(mock_db)
        
        # Test policy creation
        policy = RetentionPolicy(
            policy_id="test_policy",
            name="Test Policy",
            description="Test retention policy",
            data_category=DataCategory.CALL_RECORDINGS,
            retention_period_days=30,
            action=RetentionAction.DELETE,
            lawful_basis=GDPRLawfulBasis.LEGITIMATE_INTERESTS,
            storage_locations=["s3://test-bucket/"]
        )
        
        created_policy = await enforcer.create_retention_policy(policy)
        print(f"Created policy: {created_policy.policy_id}")
        
        # Test record registration
        record = await enforcer.register_data_record(
            record_id="test_record_123",
            data_category=DataCategory.CALL_RECORDINGS,
            policy_id="test_policy",
            data_subject_id="guest_456",
            storage_location="s3://test-bucket/recordings/",
            file_paths=["s3://test-bucket/recordings/call_123.wav"]
        )
        print(f"Registered record: {record.record_id}")
        
        # Test expiry check
        expiry_results = await enforcer.check_expiring_data(days_ahead=30)
        print(f"Expiry check: {expiry_results['total_expiring']} records expiring")
        
        # Test enforcement (dry run)
        enforcement_results = await enforcer.enforce_retention_policies(dry_run=True)
        print(f"Enforcement (dry run): {enforcement_results['records_processed']} records processed")
        
        # Test statistics
        stats = await enforcer.get_retention_statistics()
        print(f"Statistics: {stats['total_records']} total records")
        
        print("Data retention test completed successfully")
    
    # Run test
    asyncio.run(test_data_retention())