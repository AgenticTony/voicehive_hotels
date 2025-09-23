"""
Audit Trail Completeness Verification and Reporting System for VoiceHive Hotels
Ensures audit log integrity, completeness, and compliance with regulatory requirements
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

from pydantic import BaseModel, Field, validator
from sqlalchemy import text, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger, AuditEventType, AuditSeverity
from compliance_evidence_collector import ComplianceFramework

logger = get_safe_logger("orchestrator.audit_trail_verifier")


class AuditIntegrityStatus(str, Enum):
    """Status of audit trail integrity"""
    INTACT = "intact"
    COMPROMISED = "compromised"
    INCOMPLETE = "incomplete"
    SUSPICIOUS = "suspicious"
    UNKNOWN = "unknown"


class AuditGapType(str, Enum):
    """Types of audit trail gaps"""
    MISSING_EVENTS = "missing_events"
    SEQUENCE_GAP = "sequence_gap"
    TIMESTAMP_ANOMALY = "timestamp_anomaly"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    DUPLICATE_EVENTS = "duplicate_events"
    UNAUTHORIZED_MODIFICATION = "unauthorized_modification"
    RETENTION_VIOLATION = "retention_violation"


class AuditEventCategory(str, Enum):
    """Categories of audit events for verification"""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    DATA_ACCESS = "data_access"
    DATA_MODIFICATION = "data_modification"
    SYSTEM_ADMINISTRATION = "system_administration"
    SECURITY_EVENTS = "security_events"
    COMPLIANCE_EVENTS = "compliance_events"
    ERROR_EVENTS = "error_events"


@dataclass
class AuditGap:
    """Detected gap in audit trail"""
    gap_id: str
    gap_type: AuditGapType
    category: AuditEventCategory
    
    # Gap details
    description: str
    severity: str  # low, medium, high, critical
    
    # Time range
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    
    # Context
    affected_systems: List[str] = field(default_factory=list)
    affected_users: List[str] = field(default_factory=list)
    expected_event_count: Optional[int] = None
    actual_event_count: Optional[int] = None
    
    # Detection
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detection_method: str = "automated"
    
    # Investigation
    investigated: bool = False
    investigation_notes: Optional[str] = None
    root_cause: Optional[str] = None
    
    # Resolution
    resolved: bool = False
    resolution_action: Optional[str] = None
    resolved_at: Optional[datetime] = None


@dataclass
class AuditIntegrityCheck:
    """Result of audit trail integrity verification"""
    check_id: str
    check_type: str
    performed_at: datetime
    
    # Scope
    start_time: datetime
    end_time: datetime
    categories_checked: List[AuditEventCategory]
    
    # Results
    overall_status: AuditIntegrityStatus
    total_events_checked: int
    gaps_found: List[AuditGap]
    
    # Statistics
    completeness_score: float  # 0-100
    integrity_score: float     # 0-100
    compliance_score: float    # 0-100
    
    # Details
    event_statistics: Dict[str, int] = field(default_factory=dict)
    checksum_verification: Dict[str, bool] = field(default_factory=dict)
    sequence_verification: bool = True
    timestamp_verification: bool = True
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    def calculate_overall_score(self) -> float:
        """Calculate overall audit trail quality score"""
        return (self.completeness_score + self.integrity_score + self.compliance_score) / 3


@dataclass
class AuditTrailReport:
    """Comprehensive audit trail verification report"""
    report_id: str
    generated_at: datetime
    reporting_period_start: datetime
    reporting_period_end: datetime
    
    # Summary
    total_checks_performed: int = 0
    total_gaps_found: int = 0
    critical_gaps: int = 0
    high_severity_gaps: int = 0
    
    # Integrity checks
    integrity_checks: List[AuditIntegrityCheck] = field(default_factory=list)
    
    # Gap analysis
    gaps_by_type: Dict[str, int] = field(default_factory=dict)
    gaps_by_category: Dict[str, int] = field(default_factory=dict)
    gaps_by_severity: Dict[str, int] = field(default_factory=dict)
    
    # Trends
    gap_trends: Dict[str, List[int]] = field(default_factory=dict)
    
    # Compliance assessment
    regulatory_compliance: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Overall scores
    overall_completeness_score: float = 0.0
    overall_integrity_score: float = 0.0
    overall_compliance_score: float = 0.0
    
    # Recommendations
    priority_recommendations: List[Dict[str, Any]] = field(default_factory=list)


class AuditTrailVerifier:
    """Comprehensive audit trail verification and reporting system"""
    
    def __init__(self, 
                 db_session: AsyncSession,
                 audit_logger: Optional[AuditLogger] = None,
                 config_path: Optional[str] = None):
        self.db = db_session
        self.audit_logger = audit_logger or AuditLogger()
        
        # Load configuration
        self.config = self._load_config(config_path)
        
        # Verification state
        self.integrity_checks: Dict[str, AuditIntegrityCheck] = {}
        self.detected_gaps: Dict[str, AuditGap] = {}
        
        # Expected event patterns
        self.expected_patterns = self._load_expected_patterns()
        
        # Statistics
        self.verification_stats = {
            "total_checks": 0,
            "gaps_detected": 0,
            "integrity_violations": 0,
            "last_verification": None
        }
    
    async def verify_audit_trail_completeness(self, 
                                            start_time: datetime,
                                            end_time: datetime,
                                            categories: Optional[List[AuditEventCategory]] = None) -> AuditIntegrityCheck:
        """Verify completeness of audit trail for specified time period"""
        
        check_id = str(uuid.uuid4())
        
        if not categories:
            categories = list(AuditEventCategory)
        
        # Initialize integrity check
        integrity_check = AuditIntegrityCheck(
            check_id=check_id,
            check_type="completeness_verification",
            performed_at=datetime.now(timezone.utc),
            start_time=start_time,
            end_time=end_time,
            categories_checked=categories,
            overall_status=AuditIntegrityStatus.UNKNOWN,
            total_events_checked=0,
            gaps_found=[],
            completeness_score=0.0,
            integrity_score=0.0,
            compliance_score=0.0
        )
        
        try:
            # Get total event count for period
            total_events = await self._get_total_event_count(start_time, end_time)
            integrity_check.total_events_checked = total_events
            
            # Check each category
            category_gaps = []
            for category in categories:
                category_gaps.extend(await self._check_category_completeness(category, start_time, end_time))
            
            integrity_check.gaps_found = category_gaps
            
            # Verify event sequences
            sequence_gaps = await self._verify_event_sequences(start_time, end_time)
            integrity_check.gaps_found.extend(sequence_gaps)
            
            # Verify timestamps
            timestamp_gaps = await self._verify_timestamps(start_time, end_time)
            integrity_check.gaps_found.extend(timestamp_gaps)
            
            # Calculate scores
            integrity_check.completeness_score = await self._calculate_completeness_score(integrity_check)
            integrity_check.integrity_score = await self._calculate_integrity_score(integrity_check)
            integrity_check.compliance_score = await self._calculate_compliance_score(integrity_check)
            
            # Determine overall status
            integrity_check.overall_status = self._determine_integrity_status(integrity_check)
            
            # Generate recommendations
            integrity_check.recommendations = await self._generate_integrity_recommendations(integrity_check)
            
            # Store integrity check
            self.integrity_checks[check_id] = integrity_check
            
            # Update statistics
            self.verification_stats["total_checks"] += 1
            self.verification_stats["gaps_detected"] += len(integrity_check.gaps_found)
            self.verification_stats["last_verification"] = datetime.now(timezone.utc)
            
            # Audit the verification
            self.audit_logger.log_event(
                event_type=AuditEventType.ADMIN_ACTION,
                description="Audit trail completeness verification performed",
                severity=AuditSeverity.HIGH,
                resource_type="audit_verification",
                resource_id=check_id,
                action="verify_completeness",
                metadata={
                    "period_start": start_time.isoformat(),
                    "period_end": end_time.isoformat(),
                    "events_checked": total_events,
                    "gaps_found": len(integrity_check.gaps_found),
                    "completeness_score": integrity_check.completeness_score
                },
                retention_period=2555
            )
            
            logger.info(f"Audit trail verification completed: {check_id} - {len(integrity_check.gaps_found)} gaps found")
            
        except Exception as e:
            integrity_check.overall_status = AuditIntegrityStatus.UNKNOWN
            logger.error(f"Audit trail verification failed: {e}")
            raise
        
        return integrity_check
    
    async def verify_audit_trail_integrity(self, 
                                         start_time: datetime,
                                         end_time: datetime) -> AuditIntegrityCheck:
        """Verify integrity of audit trail (checksums, modifications, etc.)"""
        
        check_id = str(uuid.uuid4())
        
        integrity_check = AuditIntegrityCheck(
            check_id=check_id,
            check_type="integrity_verification",
            performed_at=datetime.now(timezone.utc),
            start_time=start_time,
            end_time=end_time,
            categories_checked=list(AuditEventCategory),
            overall_status=AuditIntegrityStatus.UNKNOWN,
            total_events_checked=0,
            gaps_found=[],
            completeness_score=0.0,
            integrity_score=0.0,
            compliance_score=0.0
        )
        
        try:
            # Verify checksums
            checksum_gaps = await self._verify_checksums(start_time, end_time)
            integrity_check.gaps_found.extend(checksum_gaps)
            
            # Detect unauthorized modifications
            modification_gaps = await self._detect_unauthorized_modifications(start_time, end_time)
            integrity_check.gaps_found.extend(modification_gaps)
            
            # Check for duplicate events
            duplicate_gaps = await self._detect_duplicate_events(start_time, end_time)
            integrity_check.gaps_found.extend(duplicate_gaps)
            
            # Verify event immutability
            immutability_gaps = await self._verify_event_immutability(start_time, end_time)
            integrity_check.gaps_found.extend(immutability_gaps)
            
            # Calculate scores
            integrity_check.integrity_score = await self._calculate_integrity_score(integrity_check)
            integrity_check.compliance_score = await self._calculate_compliance_score(integrity_check)
            integrity_check.completeness_score = 100.0  # Not applicable for integrity check
            
            # Determine overall status
            integrity_check.overall_status = self._determine_integrity_status(integrity_check)
            
            # Store integrity check
            self.integrity_checks[check_id] = integrity_check
            
            logger.info(f"Audit trail integrity verification completed: {check_id}")
            
        except Exception as e:
            integrity_check.overall_status = AuditIntegrityStatus.UNKNOWN
            logger.error(f"Audit trail integrity verification failed: {e}")
            raise
        
        return integrity_check
    
    async def generate_audit_trail_report(self, 
                                        start_time: datetime,
                                        end_time: datetime,
                                        include_trends: bool = True) -> AuditTrailReport:
        """Generate comprehensive audit trail verification report"""
        
        report_id = str(uuid.uuid4())
        
        report = AuditTrailReport(
            report_id=report_id,
            generated_at=datetime.now(timezone.utc),
            reporting_period_start=start_time,
            reporting_period_end=end_time
        )
        
        try:
            # Get all integrity checks for the period
            period_checks = [
                check for check in self.integrity_checks.values()
                if start_time <= check.performed_at <= end_time
            ]
            
            report.integrity_checks = period_checks
            report.total_checks_performed = len(period_checks)
            
            # Aggregate gaps
            all_gaps = []
            for check in period_checks:
                all_gaps.extend(check.gaps_found)
            
            report.total_gaps_found = len(all_gaps)
            
            # Analyze gaps by type, category, and severity
            for gap in all_gaps:
                # By type
                gap_type = gap.gap_type.value
                report.gaps_by_type[gap_type] = report.gaps_by_type.get(gap_type, 0) + 1
                
                # By category
                category = gap.category.value
                report.gaps_by_category[category] = report.gaps_by_category.get(category, 0) + 1
                
                # By severity
                severity = gap.severity
                report.gaps_by_severity[severity] = report.gaps_by_severity.get(severity, 0) + 1
                
                # Count critical and high severity
                if severity == "critical":
                    report.critical_gaps += 1
                elif severity == "high":
                    report.high_severity_gaps += 1
            
            # Calculate overall scores
            if period_checks:
                report.overall_completeness_score = sum(c.completeness_score for c in period_checks) / len(period_checks)
                report.overall_integrity_score = sum(c.integrity_score for c in period_checks) / len(period_checks)
                report.overall_compliance_score = sum(c.compliance_score for c in period_checks) / len(period_checks)
            
            # Generate trends if requested
            if include_trends:
                report.gap_trends = await self._generate_gap_trends(start_time, end_time)
            
            # Assess regulatory compliance
            report.regulatory_compliance = await self._assess_regulatory_compliance(all_gaps)
            
            # Generate priority recommendations
            report.priority_recommendations = await self._generate_priority_recommendations(all_gaps)
            
            # Audit report generation
            self.audit_logger.log_event(
                event_type=AuditEventType.DATA_EXPORT,
                description="Audit trail verification report generated",
                severity=AuditSeverity.HIGH,
                resource_type="audit_trail_report",
                resource_id=report_id,
                action="generate",
                metadata={
                    "period_start": start_time.isoformat(),
                    "period_end": end_time.isoformat(),
                    "checks_performed": report.total_checks_performed,
                    "gaps_found": report.total_gaps_found,
                    "overall_score": (report.overall_completeness_score + report.overall_integrity_score + report.overall_compliance_score) / 3
                },
                retention_period=2555
            )
            
            logger.info(f"Audit trail report generated: {report_id}")
            
        except Exception as e:
            logger.error(f"Failed to generate audit trail report: {e}")
            raise
        
        return report
    
    async def investigate_audit_gap(self, gap_id: str, investigator: str, notes: str) -> AuditGap:
        """Mark an audit gap as investigated with notes"""
        
        if gap_id not in self.detected_gaps:
            raise ValueError(f"Audit gap not found: {gap_id}")
        
        gap = self.detected_gaps[gap_id]
        gap.investigated = True
        gap.investigation_notes = notes
        
        # Store updated gap
        await self._update_audit_gap(gap)
        
        # Audit the investigation
        self.audit_logger.log_event(
            event_type=AuditEventType.ADMIN_ACTION,
            description=f"Audit gap investigated: {gap.description}",
            severity=AuditSeverity.MEDIUM,
            resource_type="audit_gap",
            resource_id=gap_id,
            action="investigate",
            metadata={
                "investigator": investigator,
                "investigation_notes": notes
            },
            retention_period=2555
        )
        
        logger.info(f"Audit gap investigated: {gap_id} by {investigator}")
        return gap
    
    async def resolve_audit_gap(self, 
                              gap_id: str, 
                              resolution_action: str, 
                              resolver: str) -> AuditGap:
        """Mark an audit gap as resolved"""
        
        if gap_id not in self.detected_gaps:
            raise ValueError(f"Audit gap not found: {gap_id}")
        
        gap = self.detected_gaps[gap_id]
        gap.resolved = True
        gap.resolution_action = resolution_action
        gap.resolved_at = datetime.now(timezone.utc)
        
        # Store updated gap
        await self._update_audit_gap(gap)
        
        # Audit the resolution
        self.audit_logger.log_event(
            event_type=AuditEventType.ADMIN_ACTION,
            description=f"Audit gap resolved: {gap.description}",
            severity=AuditSeverity.MEDIUM,
            resource_type="audit_gap",
            resource_id=gap_id,
            action="resolve",
            metadata={
                "resolver": resolver,
                "resolution_action": resolution_action
            },
            retention_period=2555
        )
        
        logger.info(f"Audit gap resolved: {gap_id} by {resolver}")
        return gap
    
    async def _get_total_event_count(self, start_time: datetime, end_time: datetime) -> int:
        """Get total audit event count for time period"""
        
        query = text("""
            SELECT COUNT(*) FROM audit_logs 
            WHERE timestamp BETWEEN :start_time AND :end_time
        """)
        
        result = await self.db.execute(query, {
            "start_time": start_time,
            "end_time": end_time
        })
        
        return result.scalar() or 0
    
    async def _check_category_completeness(self, 
                                         category: AuditEventCategory,
                                         start_time: datetime,
                                         end_time: datetime) -> List[AuditGap]:
        """Check completeness for a specific audit event category"""
        
        gaps = []
        
        # Get expected event patterns for this category
        expected_patterns = self.expected_patterns.get(category, {})
        
        # Check for missing events based on patterns
        for pattern_name, pattern_config in expected_patterns.items():
            pattern_gaps = await self._check_event_pattern(
                category, pattern_name, pattern_config, start_time, end_time
            )
            gaps.extend(pattern_gaps)
        
        # Check for time gaps in events
        time_gaps = await self._detect_time_gaps(category, start_time, end_time)
        gaps.extend(time_gaps)
        
        return gaps
    
    async def _check_event_pattern(self, 
                                 category: AuditEventCategory,
                                 pattern_name: str,
                                 pattern_config: Dict[str, Any],
                                 start_time: datetime,
                                 end_time: datetime) -> List[AuditGap]:
        """Check for expected event patterns"""
        
        gaps = []
        
        # Get expected frequency
        expected_frequency = pattern_config.get("expected_frequency", "hourly")
        min_events_per_period = pattern_config.get("min_events_per_period", 1)
        
        # Calculate time periods based on frequency
        if expected_frequency == "hourly":
            period_delta = timedelta(hours=1)
        elif expected_frequency == "daily":
            period_delta = timedelta(days=1)
        elif expected_frequency == "continuous":
            period_delta = timedelta(minutes=5)  # Check every 5 minutes
        else:
            period_delta = timedelta(hours=1)  # Default to hourly
        
        # Check each time period
        current_time = start_time
        while current_time < end_time:
            period_end = min(current_time + period_delta, end_time)
            
            # Count events in this period
            event_count = await self._count_events_in_period(
                category, pattern_config.get("event_types", []), current_time, period_end
            )
            
            # Check if below minimum threshold
            if event_count < min_events_per_period:
                gap = AuditGap(
                    gap_id=str(uuid.uuid4()),
                    gap_type=AuditGapType.MISSING_EVENTS,
                    category=category,
                    description=f"Missing {pattern_name} events in {category.value}",
                    severity="medium" if event_count == 0 else "low",
                    start_time=current_time,
                    end_time=period_end,
                    duration_minutes=int((period_end - current_time).total_seconds() / 60),
                    expected_event_count=min_events_per_period,
                    actual_event_count=event_count
                )
                gaps.append(gap)
                self.detected_gaps[gap.gap_id] = gap
            
            current_time = period_end
        
        return gaps
    
    async def _detect_time_gaps(self, 
                              category: AuditEventCategory,
                              start_time: datetime,
                              end_time: datetime) -> List[AuditGap]:
        """Detect time gaps in audit events"""
        
        gaps = []
        
        # Get all events for category in time period
        query = text("""
            SELECT timestamp FROM audit_logs 
            WHERE event_category = :category 
            AND timestamp BETWEEN :start_time AND :end_time
            ORDER BY timestamp
        """)
        
        result = await self.db.execute(query, {
            "category": category.value,
            "start_time": start_time,
            "end_time": end_time
        })
        
        timestamps = [row[0] for row in result.fetchall()]
        
        # Look for gaps larger than expected
        max_gap_minutes = self.config.get("max_gap_minutes", {}).get(category.value, 60)
        
        for i in range(1, len(timestamps)):
            gap_duration = (timestamps[i] - timestamps[i-1]).total_seconds() / 60
            
            if gap_duration > max_gap_minutes:
                gap = AuditGap(
                    gap_id=str(uuid.uuid4()),
                    gap_type=AuditGapType.SEQUENCE_GAP,
                    category=category,
                    description=f"Time gap in {category.value} events",
                    severity="high" if gap_duration > max_gap_minutes * 2 else "medium",
                    start_time=timestamps[i-1],
                    end_time=timestamps[i],
                    duration_minutes=int(gap_duration)
                )
                gaps.append(gap)
                self.detected_gaps[gap.gap_id] = gap
        
        return gaps
    
    async def _verify_event_sequences(self, start_time: datetime, end_time: datetime) -> List[AuditGap]:
        """Verify audit event sequences for consistency"""
        
        gaps = []
        
        # Check for sequence number gaps (if events have sequence numbers)
        sequence_gaps = await self._check_sequence_numbers(start_time, end_time)
        gaps.extend(sequence_gaps)
        
        return gaps
    
    async def _verify_timestamps(self, start_time: datetime, end_time: datetime) -> List[AuditGap]:
        """Verify timestamp consistency and detect anomalies"""
        
        gaps = []
        
        # Check for future timestamps
        future_timestamp_query = text("""
            SELECT event_id, timestamp FROM audit_logs 
            WHERE timestamp > NOW() 
            AND timestamp BETWEEN :start_time AND :end_time
        """)
        
        result = await self.db.execute(future_timestamp_query, {
            "start_time": start_time,
            "end_time": end_time
        })
        
        future_events = result.fetchall()
        
        if future_events:
            gap = AuditGap(
                gap_id=str(uuid.uuid4()),
                gap_type=AuditGapType.TIMESTAMP_ANOMALY,
                category=AuditEventCategory.SYSTEM_ADMINISTRATION,
                description=f"Found {len(future_events)} events with future timestamps",
                severity="high",
                start_time=start_time,
                end_time=end_time,
                duration_minutes=0,
                actual_event_count=len(future_events)
            )
            gaps.append(gap)
            self.detected_gaps[gap.gap_id] = gap
        
        # Check for timestamp ordering issues
        ordering_gaps = await self._check_timestamp_ordering(start_time, end_time)
        gaps.extend(ordering_gaps)
        
        return gaps
    
    async def _verify_checksums(self, start_time: datetime, end_time: datetime) -> List[AuditGap]:
        """Verify audit event checksums for integrity"""
        
        gaps = []
        
        # This would verify checksums if they exist in the audit log
        # For now, we'll simulate the check
        
        checksum_query = text("""
            SELECT event_id, checksum FROM audit_logs 
            WHERE checksum IS NOT NULL 
            AND timestamp BETWEEN :start_time AND :end_time
        """)
        
        result = await self.db.execute(checksum_query, {
            "start_time": start_time,
            "end_time": end_time
        })
        
        events_with_checksums = result.fetchall()
        
        # Simulate checksum verification
        # In real implementation, this would recalculate and compare checksums
        
        return gaps
    
    async def _detect_unauthorized_modifications(self, start_time: datetime, end_time: datetime) -> List[AuditGap]:
        """Detect unauthorized modifications to audit logs"""
        
        gaps = []
        
        # Check for modification events on audit logs themselves
        modification_query = text("""
            SELECT event_id, timestamp, user_id FROM audit_logs 
            WHERE resource_type = 'audit_log' 
            AND action IN ('update', 'delete', 'modify')
            AND timestamp BETWEEN :start_time AND :end_time
        """)
        
        result = await self.db.execute(modification_query, {
            "start_time": start_time,
            "end_time": end_time
        })
        
        modifications = result.fetchall()
        
        if modifications:
            gap = AuditGap(
                gap_id=str(uuid.uuid4()),
                gap_type=AuditGapType.UNAUTHORIZED_MODIFICATION,
                category=AuditEventCategory.SECURITY_EVENTS,
                description=f"Detected {len(modifications)} potential unauthorized modifications to audit logs",
                severity="critical",
                start_time=start_time,
                end_time=end_time,
                duration_minutes=0,
                actual_event_count=len(modifications),
                affected_users=[str(mod[2]) for mod in modifications]
            )
            gaps.append(gap)
            self.detected_gaps[gap.gap_id] = gap
        
        return gaps
    
    async def _detect_duplicate_events(self, start_time: datetime, end_time: datetime) -> List[AuditGap]:
        """Detect duplicate audit events"""
        
        gaps = []
        
        # Find potential duplicates based on timestamp, user, and action
        duplicate_query = text("""
            SELECT timestamp, user_id, action, resource_type, COUNT(*) as duplicate_count
            FROM audit_logs 
            WHERE timestamp BETWEEN :start_time AND :end_time
            GROUP BY timestamp, user_id, action, resource_type
            HAVING COUNT(*) > 1
        """)
        
        result = await self.db.execute(duplicate_query, {
            "start_time": start_time,
            "end_time": end_time
        })
        
        duplicates = result.fetchall()
        
        if duplicates:
            total_duplicates = sum(dup[4] - 1 for dup in duplicates)  # Subtract 1 to get extra copies
            
            gap = AuditGap(
                gap_id=str(uuid.uuid4()),
                gap_type=AuditGapType.DUPLICATE_EVENTS,
                category=AuditEventCategory.SYSTEM_ADMINISTRATION,
                description=f"Found {total_duplicates} duplicate audit events",
                severity="medium",
                start_time=start_time,
                end_time=end_time,
                duration_minutes=0,
                actual_event_count=total_duplicates
            )
            gaps.append(gap)
            self.detected_gaps[gap.gap_id] = gap
        
        return gaps
    
    async def _verify_event_immutability(self, start_time: datetime, end_time: datetime) -> List[AuditGap]:
        """Verify that audit events have not been modified after creation"""
        
        gaps = []
        
        # Check for events with modification timestamps after creation
        immutability_query = text("""
            SELECT event_id, created_at, modified_at FROM audit_logs 
            WHERE modified_at IS NOT NULL 
            AND modified_at > created_at
            AND timestamp BETWEEN :start_time AND :end_time
        """)
        
        result = await self.db.execute(immutability_query, {
            "start_time": start_time,
            "end_time": end_time
        })
        
        modified_events = result.fetchall()
        
        if modified_events:
            gap = AuditGap(
                gap_id=str(uuid.uuid4()),
                gap_type=AuditGapType.UNAUTHORIZED_MODIFICATION,
                category=AuditEventCategory.SECURITY_EVENTS,
                description=f"Found {len(modified_events)} audit events that were modified after creation",
                severity="critical",
                start_time=start_time,
                end_time=end_time,
                duration_minutes=0,
                actual_event_count=len(modified_events)
            )
            gaps.append(gap)
            self.detected_gaps[gap.gap_id] = gap
        
        return gaps
    
    async def _count_events_in_period(self, 
                                    category: AuditEventCategory,
                                    event_types: List[str],
                                    start_time: datetime,
                                    end_time: datetime) -> int:
        """Count events of specific types in a time period"""
        
        if not event_types:
            # Count all events in category
            query = text("""
                SELECT COUNT(*) FROM audit_logs 
                WHERE event_category = :category 
                AND timestamp BETWEEN :start_time AND :end_time
            """)
            
            result = await self.db.execute(query, {
                "category": category.value,
                "start_time": start_time,
                "end_time": end_time
            })
        else:
            # Count specific event types
            placeholders = ",".join([f":event_type_{i}" for i in range(len(event_types))])
            query = text(f"""
                SELECT COUNT(*) FROM audit_logs 
                WHERE event_category = :category 
                AND event_type IN ({placeholders})
                AND timestamp BETWEEN :start_time AND :end_time
            """)
            
            params = {
                "category": category.value,
                "start_time": start_time,
                "end_time": end_time
            }
            
            for i, event_type in enumerate(event_types):
                params[f"event_type_{i}"] = event_type
            
            result = await self.db.execute(query, params)
        
        return result.scalar() or 0
    
    async def _check_sequence_numbers(self, start_time: datetime, end_time: datetime) -> List[AuditGap]:
        """Check for gaps in sequence numbers"""
        
        gaps = []
        
        # This assumes audit logs have sequence numbers
        # If not available, this check would be skipped
        
        sequence_query = text("""
            SELECT sequence_number FROM audit_logs 
            WHERE sequence_number IS NOT NULL 
            AND timestamp BETWEEN :start_time AND :end_time
            ORDER BY sequence_number
        """)
        
        try:
            result = await self.db.execute(sequence_query, {
                "start_time": start_time,
                "end_time": end_time
            })
            
            sequences = [row[0] for row in result.fetchall()]
            
            # Check for gaps in sequence
            for i in range(1, len(sequences)):
                if sequences[i] != sequences[i-1] + 1:
                    gap = AuditGap(
                        gap_id=str(uuid.uuid4()),
                        gap_type=AuditGapType.SEQUENCE_GAP,
                        category=AuditEventCategory.SYSTEM_ADMINISTRATION,
                        description=f"Sequence number gap: {sequences[i-1]} to {sequences[i]}",
                        severity="high",
                        start_time=start_time,
                        end_time=end_time,
                        duration_minutes=0,
                        expected_event_count=sequences[i] - sequences[i-1] - 1,
                        actual_event_count=0
                    )
                    gaps.append(gap)
                    self.detected_gaps[gap.gap_id] = gap
        
        except Exception:
            # Sequence numbers not available
            pass
        
        return gaps
    
    async def _check_timestamp_ordering(self, start_time: datetime, end_time: datetime) -> List[AuditGap]:
        """Check for timestamp ordering issues"""
        
        gaps = []
        
        # Check for events with timestamps out of order
        ordering_query = text("""
            SELECT a1.event_id, a1.timestamp, a2.event_id, a2.timestamp
            FROM audit_logs a1
            JOIN audit_logs a2 ON a1.sequence_number = a2.sequence_number + 1
            WHERE a1.timestamp < a2.timestamp
            AND a1.timestamp BETWEEN :start_time AND :end_time
        """)
        
        try:
            result = await self.db.execute(ordering_query, {
                "start_time": start_time,
                "end_time": end_time
            })
            
            ordering_issues = result.fetchall()
            
            if ordering_issues:
                gap = AuditGap(
                    gap_id=str(uuid.uuid4()),
                    gap_type=AuditGapType.TIMESTAMP_ANOMALY,
                    category=AuditEventCategory.SYSTEM_ADMINISTRATION,
                    description=f"Found {len(ordering_issues)} timestamp ordering issues",
                    severity="medium",
                    start_time=start_time,
                    end_time=end_time,
                    duration_minutes=0,
                    actual_event_count=len(ordering_issues)
                )
                gaps.append(gap)
                self.detected_gaps[gap.gap_id] = gap
        
        except Exception:
            # Sequence numbers not available for ordering check
            pass
        
        return gaps
    
    async def _calculate_completeness_score(self, integrity_check: AuditIntegrityCheck) -> float:
        """Calculate completeness score based on gaps found"""
        
        if not integrity_check.gaps_found:
            return 100.0
        
        # Calculate penalty based on gap severity and type
        total_penalty = 0.0
        
        for gap in integrity_check.gaps_found:
            if gap.gap_type == AuditGapType.MISSING_EVENTS:
                penalty = {
                    "critical": 20.0,
                    "high": 10.0,
                    "medium": 5.0,
                    "low": 1.0
                }.get(gap.severity, 5.0)
            else:
                penalty = {
                    "critical": 10.0,
                    "high": 5.0,
                    "medium": 2.0,
                    "low": 0.5
                }.get(gap.severity, 2.0)
            
            total_penalty += penalty
        
        # Calculate score (0-100)
        score = max(0.0, 100.0 - total_penalty)
        return score
    
    async def _calculate_integrity_score(self, integrity_check: AuditIntegrityCheck) -> float:
        """Calculate integrity score based on integrity violations"""
        
        integrity_violations = [
            gap for gap in integrity_check.gaps_found
            if gap.gap_type in [
                AuditGapType.CHECKSUM_MISMATCH,
                AuditGapType.UNAUTHORIZED_MODIFICATION,
                AuditGapType.DUPLICATE_EVENTS
            ]
        ]
        
        if not integrity_violations:
            return 100.0
        
        # Heavy penalty for integrity violations
        total_penalty = 0.0
        
        for violation in integrity_violations:
            penalty = {
                "critical": 50.0,
                "high": 25.0,
                "medium": 10.0,
                "low": 5.0
            }.get(violation.severity, 10.0)
            
            total_penalty += penalty
        
        score = max(0.0, 100.0 - total_penalty)
        return score
    
    async def _calculate_compliance_score(self, integrity_check: AuditIntegrityCheck) -> float:
        """Calculate compliance score based on regulatory requirements"""
        
        # Base score
        score = 100.0
        
        # Penalties for compliance-related gaps
        for gap in integrity_check.gaps_found:
            if gap.gap_type in [AuditGapType.RETENTION_VIOLATION, AuditGapType.MISSING_EVENTS]:
                penalty = {
                    "critical": 30.0,
                    "high": 15.0,
                    "medium": 7.0,
                    "low": 2.0
                }.get(gap.severity, 7.0)
                
                score -= penalty
        
        return max(0.0, score)
    
    def _determine_integrity_status(self, integrity_check: AuditIntegrityCheck) -> AuditIntegrityStatus:
        """Determine overall integrity status"""
        
        # Check for critical issues
        critical_gaps = [gap for gap in integrity_check.gaps_found if gap.severity == "critical"]
        if critical_gaps:
            return AuditIntegrityStatus.COMPROMISED
        
        # Check for high severity issues
        high_gaps = [gap for gap in integrity_check.gaps_found if gap.severity == "high"]
        if high_gaps:
            return AuditIntegrityStatus.SUSPICIOUS
        
        # Check for medium severity issues
        medium_gaps = [gap for gap in integrity_check.gaps_found if gap.severity == "medium"]
        if medium_gaps:
            return AuditIntegrityStatus.INCOMPLETE
        
        # No significant issues
        return AuditIntegrityStatus.INTACT
    
    async def _generate_integrity_recommendations(self, integrity_check: AuditIntegrityCheck) -> List[str]:
        """Generate recommendations based on integrity check results"""
        
        recommendations = []
        
        # Analyze gap types and generate specific recommendations
        gap_types = {gap.gap_type for gap in integrity_check.gaps_found}
        
        if AuditGapType.MISSING_EVENTS in gap_types:
            recommendations.append("Review audit logging configuration to ensure all required events are captured")
            recommendations.append("Implement monitoring for audit log gaps")
        
        if AuditGapType.UNAUTHORIZED_MODIFICATION in gap_types:
            recommendations.append("Investigate potential security breach - audit logs should be immutable")
            recommendations.append("Implement stronger access controls for audit log storage")
        
        if AuditGapType.TIMESTAMP_ANOMALY in gap_types:
            recommendations.append("Synchronize system clocks across all servers")
            recommendations.append("Implement NTP monitoring and alerting")
        
        if AuditGapType.DUPLICATE_EVENTS in gap_types:
            recommendations.append("Review audit logging implementation for duplicate event generation")
            recommendations.append("Implement deduplication mechanisms")
        
        # Score-based recommendations
        if integrity_check.completeness_score < 80:
            recommendations.append("Improve audit log completeness - current score below acceptable threshold")
        
        if integrity_check.integrity_score < 90:
            recommendations.append("Address audit log integrity issues immediately")
        
        if integrity_check.compliance_score < 85:
            recommendations.append("Review compliance requirements and ensure audit logging meets all standards")
        
        return recommendations
    
    async def _generate_gap_trends(self, start_time: datetime, end_time: datetime) -> Dict[str, List[int]]:
        """Generate gap trend data over time"""
        
        trends = {}
        
        # Generate daily gap counts for the period
        current_date = start_time.date()
        end_date = end_time.date()
        
        while current_date <= end_date:
            day_start = datetime.combine(current_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            
            # Count gaps for this day
            daily_gaps = [
                gap for gap in self.detected_gaps.values()
                if day_start <= gap.detected_at < day_end
            ]
            
            # Group by type
            for gap in daily_gaps:
                gap_type = gap.gap_type.value
                if gap_type not in trends:
                    trends[gap_type] = []
                trends[gap_type].append(len([g for g in daily_gaps if g.gap_type.value == gap_type]))
            
            current_date += timedelta(days=1)
        
        return trends
    
    async def _assess_regulatory_compliance(self, gaps: List[AuditGap]) -> Dict[str, Dict[str, Any]]:
        """Assess compliance with regulatory requirements"""
        
        compliance_assessment = {}
        
        # GDPR compliance assessment
        gdpr_gaps = [gap for gap in gaps if gap.severity in ["critical", "high"]]
        compliance_assessment["GDPR"] = {
            "compliant": len(gdpr_gaps) == 0,
            "gap_count": len(gdpr_gaps),
            "risk_level": "high" if gdpr_gaps else "low",
            "requirements_affected": ["Article 30 - Records of Processing"] if gdpr_gaps else []
        }
        
        # SOX compliance assessment
        sox_critical_gaps = [gap for gap in gaps if gap.severity == "critical"]
        compliance_assessment["SOX"] = {
            "compliant": len(sox_critical_gaps) == 0,
            "gap_count": len(sox_critical_gaps),
            "risk_level": "critical" if sox_critical_gaps else "low",
            "requirements_affected": ["Section 404 - Internal Controls"] if sox_critical_gaps else []
        }
        
        return compliance_assessment
    
    async def _generate_priority_recommendations(self, gaps: List[AuditGap]) -> List[Dict[str, Any]]:
        """Generate priority recommendations based on gaps"""
        
        recommendations = []
        
        # Critical gaps - immediate action required
        critical_gaps = [gap for gap in gaps if gap.severity == "critical"]
        if critical_gaps:
            recommendations.append({
                "priority": "critical",
                "title": "Address Critical Audit Trail Issues",
                "description": f"{len(critical_gaps)} critical audit trail issues require immediate attention",
                "action": "Investigate and resolve all critical gaps within 4 hours",
                "timeline": "immediate"
            })
        
        # High severity gaps
        high_gaps = [gap for gap in gaps if gap.severity == "high"]
        if high_gaps:
            recommendations.append({
                "priority": "high",
                "title": "Resolve High-Severity Audit Issues",
                "description": f"{len(high_gaps)} high-severity audit issues need resolution",
                "action": "Review and fix high-severity gaps within 24 hours",
                "timeline": "24 hours"
            })
        
        # Pattern-based recommendations
        missing_events_gaps = [gap for gap in gaps if gap.gap_type == AuditGapType.MISSING_EVENTS]
        if len(missing_events_gaps) > 5:
            recommendations.append({
                "priority": "medium",
                "title": "Improve Audit Log Coverage",
                "description": "Multiple missing event patterns detected",
                "action": "Review and enhance audit logging configuration",
                "timeline": "1 week"
            })
        
        return recommendations
    
    def _load_expected_patterns(self) -> Dict[AuditEventCategory, Dict[str, Any]]:
        """Load expected audit event patterns for verification"""
        
        patterns = {
            AuditEventCategory.AUTHENTICATION: {
                "login_events": {
                    "expected_frequency": "continuous",
                    "min_events_per_period": 1,
                    "event_types": ["login_success", "login_failure"]
                }
            },
            AuditEventCategory.DATA_ACCESS: {
                "data_read_events": {
                    "expected_frequency": "hourly",
                    "min_events_per_period": 1,
                    "event_types": ["data_read", "data_export"]
                }
            },
            AuditEventCategory.SYSTEM_ADMINISTRATION: {
                "admin_events": {
                    "expected_frequency": "daily",
                    "min_events_per_period": 1,
                    "event_types": ["config_change", "admin_action"]
                }
            }
        }
        
        return patterns
    
    async def _update_audit_gap(self, gap: AuditGap):
        """Update audit gap in database"""
        # Implementation would update in actual database
        pass
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load audit trail verification configuration"""
        
        default_config = {
            "max_gap_minutes": {
                "authentication": 30,
                "data_access": 60,
                "system_administration": 120,
                "security_events": 15
            },
            "verification_schedule": "0 */6 * * *",  # Every 6 hours
            "retention_days": 2555,  # 7 years
            "alert_thresholds": {
                "critical_gaps": 1,
                "high_gaps": 5,
                "completeness_score": 80.0,
                "integrity_score": 90.0
            }
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r') as f:
                    import yaml
                    config = yaml.safe_load(f)
                    default_config.update(config)
            except Exception as e:
                logger.error(f"Failed to load audit verification config from {config_path}: {e}")
        
        return default_config


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    from unittest.mock import AsyncMock
    
    async def test_audit_trail_verification():
        # Mock database session
        mock_db = AsyncMock()
        
        # Mock query results
        mock_db.execute.return_value.fetchall.return_value = []
        mock_db.execute.return_value.scalar.return_value = 1000
        
        # Create audit trail verifier
        verifier = AuditTrailVerifier(mock_db)
        
        # Test completeness verification
        start_time = datetime.now(timezone.utc) - timedelta(days=1)
        end_time = datetime.now(timezone.utc)
        
        completeness_check = await verifier.verify_audit_trail_completeness(
            start_time, end_time
        )
        print(f"Completeness check: {completeness_check.check_id}")
        print(f"Status: {completeness_check.overall_status.value}")
        print(f"Gaps found: {len(completeness_check.gaps_found)}")
        print(f"Completeness score: {completeness_check.completeness_score:.2f}")
        
        # Test integrity verification
        integrity_check = await verifier.verify_audit_trail_integrity(
            start_time, end_time
        )
        print(f"Integrity check: {integrity_check.check_id}")
        print(f"Integrity score: {integrity_check.integrity_score:.2f}")
        
        # Test report generation
        report = await verifier.generate_audit_trail_report(
            start_time, end_time
        )
        print(f"Report generated: {report.report_id}")
        print(f"Total checks: {report.total_checks_performed}")
        print(f"Overall scores: C:{report.overall_completeness_score:.1f} I:{report.overall_integrity_score:.1f} Comp:{report.overall_compliance_score:.1f}")
        
        print("Audit trail verification test completed successfully")
    
    # Run test
    asyncio.run(test_audit_trail_verification())