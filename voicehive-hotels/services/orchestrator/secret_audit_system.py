"""
Secret Access Auditing and Anomaly Detection System
Comprehensive monitoring and analysis of secret access patterns
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict, deque
import statistics
import ipaddress

import hvac
from prometheus_client import Counter, Histogram, Gauge

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger
from secrets_manager import SecretsManager, SecretType

# Configure logging
logger = get_safe_logger("orchestrator.secret_audit")
audit_logger = AuditLogger("secret_audit")

# Metrics
secret_access_attempts = Counter('voicehive_secret_access_attempts_total', 
                                'Total secret access attempts', ['secret_type', 'status', 'source'])
secret_access_anomalies = Counter('voicehive_secret_access_anomalies_total',
                                'Secret access anomalies detected', ['anomaly_type', 'severity'])
secret_access_patterns = Histogram('voicehive_secret_access_patterns',
                                 'Secret access pattern analysis', ['pattern_type'])
active_secret_sessions = Gauge('voicehive_active_secret_sessions',
                              'Currently active secret access sessions', ['secret_type'])


class AnomalyType(str, Enum):
    """Types of access anomalies"""
    UNUSUAL_TIME = "unusual_time"
    UNUSUAL_LOCATION = "unusual_location"
    EXCESSIVE_ACCESS = "excessive_access"
    FAILED_ATTEMPTS = "failed_attempts"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    CONCURRENT_ACCESS = "concurrent_access"
    GEOGRAPHIC_VIOLATION = "geographic_violation"
    SUSPICIOUS_PATTERN = "suspicious_pattern"


class SeverityLevel(str, Enum):
    """Severity levels for anomalies"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AccessPattern(str, Enum):
    """Access pattern types"""
    NORMAL = "normal"
    BURST = "burst"
    PERIODIC = "periodic"
    RANDOM = "random"
    SUSPICIOUS = "suspicious"


@dataclass
class AccessEvent:
    """Represents a secret access event"""
    event_id: str
    secret_id: str
    secret_type: SecretType
    accessor_id: str
    accessor_type: str  # user, service, system
    access_time: datetime
    source_ip: str
    user_agent: Optional[str]
    access_method: str  # api, vault_direct, cli
    success: bool
    failure_reason: Optional[str]
    session_id: Optional[str]
    geographic_location: Optional[str]
    metadata: Dict[str, Any]


@dataclass
class AccessAnomaly:
    """Represents detected access anomaly"""
    anomaly_id: str
    anomaly_type: AnomalyType
    severity: SeverityLevel
    detected_at: datetime
    secret_id: str
    accessor_id: str
    description: str
    evidence: Dict[str, Any]
    risk_score: float
    recommended_actions: List[str]
    acknowledged: bool
    resolved: bool


@dataclass
class AccessSession:
    """Represents an access session"""
    session_id: str
    secret_id: str
    accessor_id: str
    start_time: datetime
    last_access: datetime
    access_count: int
    source_ips: Set[str]
    user_agents: Set[str]
    active: bool


class SecretAuditSystem:
    """
    Comprehensive secret access auditing and anomaly detection system
    """
    
    def __init__(self, secrets_manager: SecretsManager, vault_client: hvac.Client, config: Dict[str, Any]):
        self.secrets_manager = secrets_manager
        self.vault_client = vault_client
        self.config = config
        
        # Audit storage paths
        self.access_events_path = config.get('access_events_path', 'voicehive/audit/access_events')
        self.anomalies_path = config.get('anomalies_path', 'voicehive/audit/anomalies')
        self.sessions_path = config.get('sessions_path', 'voicehive/audit/sessions')
        
        # In-memory caches for analysis
        self.recent_events: deque = deque(maxlen=10000)  # Last 10k events
        self.active_sessions: Dict[str, AccessSession] = {}
        self.access_patterns: Dict[str, List[datetime]] = defaultdict(list)
        
        # Anomaly detection configuration
        self.anomaly_thresholds = {
            AnomalyType.EXCESSIVE_ACCESS: config.get('excessive_access_threshold', 100),
            AnomalyType.FAILED_ATTEMPTS: config.get('failed_attempts_threshold', 10),
            AnomalyType.CONCURRENT_ACCESS: config.get('concurrent_access_threshold', 5)
        }
        
        # Geographic restrictions
        self.allowed_countries = config.get('allowed_countries', ['GB', 'IE', 'DE', 'FR', 'NL'])
        self.allowed_ip_ranges = [
            ipaddress.ip_network(cidr) for cidr in config.get('allowed_ip_ranges', [])
        ]
        
        # Background tasks
        self._monitoring_task: Optional[asyncio.Task] = None
        self._analysis_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Notification handlers
        self._anomaly_handlers: Dict[AnomalyType, callable] = {}
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register default anomaly handlers"""
        self._anomaly_handlers[AnomalyType.CRITICAL] = self._handle_critical_anomaly
        self._anomaly_handlers[AnomalyType.GEOGRAPHIC_VIOLATION] = self._handle_geographic_violation
        self._anomaly_handlers[AnomalyType.EXCESSIVE_ACCESS] = self._handle_excessive_access
    
    async def initialize(self) -> bool:
        """Initialize the audit system"""
        try:
            # Verify Vault connection
            if not self.vault_client.is_authenticated():
                logger.error("vault_authentication_failed")
                return False
            
            # Ensure required paths exist
            await self._ensure_vault_paths()
            
            # Load recent events for analysis
            await self._load_recent_events()
            
            # Start background tasks
            await self._start_background_tasks()
            
            audit_logger.log_security_event(
                event_type="audit_system_initialized",
                details={"config": self.config},
                severity="info"
            )
            
            logger.info("secret_audit_system_initialized")
            return True
            
        except Exception as e:
            logger.error("audit_system_initialization_failed", error=str(e))
            return False
    
    async def record_access_event(self, 
                                secret_id: str,
                                secret_type: SecretType,
                                accessor_id: str,
                                accessor_type: str,
                                source_ip: str,
                                success: bool,
                                access_method: str = "api",
                                user_agent: Optional[str] = None,
                                failure_reason: Optional[str] = None,
                                session_id: Optional[str] = None,
                                metadata: Optional[Dict[str, Any]] = None) -> str:
        """Record a secret access event"""
        
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Determine geographic location (simplified)
        geographic_location = await self._get_geographic_location(source_ip)
        
        # Create access event
        access_event = AccessEvent(
            event_id=event_id,
            secret_id=secret_id,
            secret_type=secret_type,
            accessor_id=accessor_id,
            accessor_type=accessor_type,
            access_time=now,
            source_ip=source_ip,
            user_agent=user_agent,
            access_method=access_method,
            success=success,
            failure_reason=failure_reason,
            session_id=session_id,
            geographic_location=geographic_location,
            metadata=metadata or {}
        )
        
        try:
            # Store event in Vault
            event_path = f"{self.access_events_path}/{event_id}"
            event_data = asdict(access_event)
            event_data['access_time'] = event_data['access_time'].isoformat()
            
            self.vault_client.secrets.kv.v2.create_or_update_secret(
                path=event_path,
                secret=event_data
            )
            
            # Add to in-memory cache
            self.recent_events.append(access_event)
            
            # Update session tracking
            await self._update_session_tracking(access_event)
            
            # Update metrics
            secret_access_attempts.labels(
                secret_type=secret_type.value,
                status="success" if success else "failure",
                source=accessor_type
            ).inc()
            
            # Trigger real-time anomaly detection
            await self._detect_real_time_anomalies(access_event)
            
            # Audit log
            audit_logger.log_security_event(
                event_type="secret_access_recorded",
                details={
                    "event_id": event_id,
                    "secret_id": secret_id,
                    "accessor_id": accessor_id,
                    "success": success,
                    "source_ip": source_ip,
                    "geographic_location": geographic_location
                },
                severity="info" if success else "warning"
            )
            
            logger.info("access_event_recorded", 
                       event_id=event_id,
                       secret_id=secret_id,
                       success=success)
            
            return event_id
            
        except Exception as e:
            logger.error("access_event_recording_failed", 
                        event_id=event_id, error=str(e))
            raise
    
    async def detect_anomalies(self, 
                             time_window_hours: int = 24,
                             min_risk_score: float = 0.5) -> List[AccessAnomaly]:
        """Detect access anomalies in the specified time window"""
        
        anomalies = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)
        
        # Get recent events for analysis
        recent_events = [
            event for event in self.recent_events 
            if event.access_time >= cutoff_time
        ]
        
        # Group events by accessor for pattern analysis
        accessor_events = defaultdict(list)
        for event in recent_events:
            accessor_events[event.accessor_id].append(event)
        
        # Analyze each accessor's patterns
        for accessor_id, events in accessor_events.items():
            accessor_anomalies = await self._analyze_accessor_patterns(accessor_id, events)
            anomalies.extend(accessor_anomalies)
        
        # Analyze system-wide patterns
        system_anomalies = await self._analyze_system_patterns(recent_events)
        anomalies.extend(system_anomalies)
        
        # Filter by risk score
        high_risk_anomalies = [
            anomaly for anomaly in anomalies 
            if anomaly.risk_score >= min_risk_score
        ]
        
        # Store detected anomalies
        for anomaly in high_risk_anomalies:
            await self._store_anomaly(anomaly)
        
        return high_risk_anomalies
    
    async def _analyze_accessor_patterns(self, accessor_id: str, events: List[AccessEvent]) -> List[AccessAnomaly]:
        """Analyze access patterns for a specific accessor"""
        
        anomalies = []
        
        if not events:
            return anomalies
        
        # Check for excessive access
        if len(events) > self.anomaly_thresholds[AnomalyType.EXCESSIVE_ACCESS]:
            anomaly = AccessAnomaly(
                anomaly_id=str(uuid.uuid4()),
                anomaly_type=AnomalyType.EXCESSIVE_ACCESS,
                severity=SeverityLevel.HIGH,
                detected_at=datetime.now(timezone.utc),
                secret_id=events[0].secret_id,
                accessor_id=accessor_id,
                description=f"Excessive access detected: {len(events)} accesses in analysis window",
                evidence={
                    "access_count": len(events),
                    "threshold": self.anomaly_thresholds[AnomalyType.EXCESSIVE_ACCESS],
                    "time_span_hours": (events[-1].access_time - events[0].access_time).total_seconds() / 3600
                },
                risk_score=min(1.0, len(events) / self.anomaly_thresholds[AnomalyType.EXCESSIVE_ACCESS]),
                recommended_actions=[
                    "Review accessor permissions",
                    "Investigate access necessity",
                    "Consider rate limiting"
                ],
                acknowledged=False,
                resolved=False
            )
            anomalies.append(anomaly)
        
        # Check for failed attempts pattern
        failed_events = [e for e in events if not e.success]
        if len(failed_events) > self.anomaly_thresholds[AnomalyType.FAILED_ATTEMPTS]:
            anomaly = AccessAnomaly(
                anomaly_id=str(uuid.uuid4()),
                anomaly_type=AnomalyType.FAILED_ATTEMPTS,
                severity=SeverityLevel.HIGH,
                detected_at=datetime.now(timezone.utc),
                secret_id=events[0].secret_id,
                accessor_id=accessor_id,
                description=f"Multiple failed access attempts: {len(failed_events)} failures",
                evidence={
                    "failed_attempts": len(failed_events),
                    "total_attempts": len(events),
                    "failure_rate": len(failed_events) / len(events),
                    "failure_reasons": list(set(e.failure_reason for e in failed_events if e.failure_reason))
                },
                risk_score=min(1.0, len(failed_events) / self.anomaly_thresholds[AnomalyType.FAILED_ATTEMPTS]),
                recommended_actions=[
                    "Investigate authentication issues",
                    "Check for brute force attacks",
                    "Review access credentials"
                ],
                acknowledged=False,
                resolved=False
            )
            anomalies.append(anomaly)
        
        # Check for unusual time patterns
        access_hours = [event.access_time.hour for event in events]
        if self._is_unusual_time_pattern(access_hours):
            anomaly = AccessAnomaly(
                anomaly_id=str(uuid.uuid4()),
                anomaly_type=AnomalyType.UNUSUAL_TIME,
                severity=SeverityLevel.MEDIUM,
                detected_at=datetime.now(timezone.utc),
                secret_id=events[0].secret_id,
                accessor_id=accessor_id,
                description="Unusual access time pattern detected",
                evidence={
                    "access_hours": access_hours,
                    "outside_business_hours": sum(1 for h in access_hours if h < 8 or h > 18),
                    "weekend_access": sum(1 for e in events if e.access_time.weekday() >= 5)
                },
                risk_score=0.6,
                recommended_actions=[
                    "Verify legitimate business need for off-hours access",
                    "Review access justification"
                ],
                acknowledged=False,
                resolved=False
            )
            anomalies.append(anomaly)
        
        # Check for geographic violations
        unique_locations = set(e.geographic_location for e in events if e.geographic_location)
        for location in unique_locations:
            if location and not self._is_allowed_location(location):
                anomaly = AccessAnomaly(
                    anomaly_id=str(uuid.uuid4()),
                    anomaly_type=AnomalyType.GEOGRAPHIC_VIOLATION,
                    severity=SeverityLevel.CRITICAL,
                    detected_at=datetime.now(timezone.utc),
                    secret_id=events[0].secret_id,
                    accessor_id=accessor_id,
                    description=f"Access from unauthorized geographic location: {location}",
                    evidence={
                        "unauthorized_location": location,
                        "allowed_locations": self.allowed_countries,
                        "access_count_from_location": sum(1 for e in events if e.geographic_location == location)
                    },
                    risk_score=1.0,
                    recommended_actions=[
                        "Immediately investigate unauthorized access",
                        "Consider revoking access credentials",
                        "Review geographic access policies"
                    ],
                    acknowledged=False,
                    resolved=False
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    async def _analyze_system_patterns(self, events: List[AccessEvent]) -> List[AccessAnomaly]:
        """Analyze system-wide access patterns"""
        
        anomalies = []
        
        # Check for concurrent access to same secret
        secret_concurrent_access = defaultdict(set)
        for event in events:
            if event.session_id:
                secret_concurrent_access[event.secret_id].add(event.session_id)
        
        for secret_id, sessions in secret_concurrent_access.items():
            if len(sessions) > self.anomaly_thresholds[AnomalyType.CONCURRENT_ACCESS]:
                anomaly = AccessAnomaly(
                    anomaly_id=str(uuid.uuid4()),
                    anomaly_type=AnomalyType.CONCURRENT_ACCESS,
                    severity=SeverityLevel.MEDIUM,
                    detected_at=datetime.now(timezone.utc),
                    secret_id=secret_id,
                    accessor_id="system",
                    description=f"Excessive concurrent access to secret: {len(sessions)} sessions",
                    evidence={
                        "concurrent_sessions": len(sessions),
                        "threshold": self.anomaly_thresholds[AnomalyType.CONCURRENT_ACCESS],
                        "session_ids": list(sessions)
                    },
                    risk_score=min(1.0, len(sessions) / self.anomaly_thresholds[AnomalyType.CONCURRENT_ACCESS]),
                    recommended_actions=[
                        "Review session management",
                        "Check for session leaks",
                        "Implement session limits"
                    ],
                    acknowledged=False,
                    resolved=False
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _is_unusual_time_pattern(self, access_hours: List[int]) -> bool:
        """Determine if access time pattern is unusual"""
        
        if not access_hours:
            return False
        
        # Check if majority of access is outside business hours (8 AM - 6 PM)
        outside_hours = sum(1 for hour in access_hours if hour < 8 or hour > 18)
        return outside_hours / len(access_hours) > 0.7
    
    def _is_allowed_location(self, location: str) -> bool:
        """Check if geographic location is allowed"""
        
        # Extract country code from location (simplified)
        country_code = location.split(',')[-1].strip().upper()
        return country_code in self.allowed_countries
    
    async def _get_geographic_location(self, ip_address: str) -> Optional[str]:
        """Get geographic location from IP address"""
        
        try:
            # Check if IP is in allowed ranges
            ip = ipaddress.ip_address(ip_address)
            
            for allowed_range in self.allowed_ip_ranges:
                if ip in allowed_range:
                    return "INTERNAL"
            
            # For external IPs, this would use a geolocation service
            # For now, return a placeholder
            return "EXTERNAL,UNKNOWN"
            
        except ValueError:
            return None
    
    async def _update_session_tracking(self, event: AccessEvent):
        """Update session tracking information"""
        
        if not event.session_id:
            return
        
        session = self.active_sessions.get(event.session_id)
        
        if session:
            # Update existing session
            session.last_access = event.access_time
            session.access_count += 1
            session.source_ips.add(event.source_ip)
            if event.user_agent:
                session.user_agents.add(event.user_agent)
        else:
            # Create new session
            session = AccessSession(
                session_id=event.session_id,
                secret_id=event.secret_id,
                accessor_id=event.accessor_id,
                start_time=event.access_time,
                last_access=event.access_time,
                access_count=1,
                source_ips={event.source_ip},
                user_agents={event.user_agent} if event.user_agent else set(),
                active=True
            )
            self.active_sessions[event.session_id] = session
        
        # Update metrics
        active_secret_sessions.labels(secret_type=event.secret_type.value).set(
            len([s for s in self.active_sessions.values() if s.active])
        )
    
    async def _detect_real_time_anomalies(self, event: AccessEvent):
        """Detect anomalies in real-time as events occur"""
        
        # Check for immediate geographic violations
        if event.geographic_location and not self._is_allowed_location(event.geographic_location):
            await self._handle_geographic_violation(event)
        
        # Check for rapid successive failures
        recent_failures = [
            e for e in list(self.recent_events)[-50:]  # Last 50 events
            if (e.accessor_id == event.accessor_id and 
                not e.success and 
                (event.access_time - e.access_time).total_seconds() < 300)  # 5 minutes
        ]
        
        if len(recent_failures) >= 5:
            await self._handle_rapid_failures(event, recent_failures)
    
    async def _handle_geographic_violation(self, event: AccessEvent):
        """Handle geographic access violation"""
        
        logger.critical("geographic_violation_detected",
                       accessor_id=event.accessor_id,
                       location=event.geographic_location,
                       secret_id=event.secret_id)
        
        # This would trigger immediate security response
        # - Disable the accessor's credentials
        # - Send emergency alerts
        # - Log security incident
        
        audit_logger.log_security_event(
            event_type="geographic_violation",
            details={
                "accessor_id": event.accessor_id,
                "unauthorized_location": event.geographic_location,
                "secret_id": event.secret_id,
                "source_ip": event.source_ip
            },
            severity="critical"
        )
    
    async def _handle_rapid_failures(self, event: AccessEvent, failures: List[AccessEvent]):
        """Handle rapid successive access failures"""
        
        logger.warning("rapid_access_failures_detected",
                      accessor_id=event.accessor_id,
                      failure_count=len(failures))
        
        # This would trigger rate limiting or temporary lockout
        
        audit_logger.log_security_event(
            event_type="rapid_access_failures",
            details={
                "accessor_id": event.accessor_id,
                "failure_count": len(failures),
                "time_window_seconds": 300
            },
            severity="high"
        )
    
    async def generate_audit_report(self, 
                                  start_time: datetime,
                                  end_time: datetime,
                                  include_anomalies: bool = True) -> Dict[str, Any]:
        """Generate comprehensive audit report"""
        
        report = {
            "report_period": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            },
            "summary": {
                "total_access_events": 0,
                "successful_accesses": 0,
                "failed_accesses": 0,
                "unique_accessors": 0,
                "unique_secrets": 0,
                "anomalies_detected": 0
            },
            "access_patterns": {},
            "top_accessors": [],
            "top_secrets": [],
            "geographic_distribution": {},
            "time_distribution": {},
            "anomalies": [] if include_anomalies else None,
            "recommendations": []
        }
        
        try:
            # Get events in time range
            events = await self._get_events_in_range(start_time, end_time)
            
            # Calculate summary statistics
            report["summary"]["total_access_events"] = len(events)
            report["summary"]["successful_accesses"] = sum(1 for e in events if e.success)
            report["summary"]["failed_accesses"] = sum(1 for e in events if not e.success)
            report["summary"]["unique_accessors"] = len(set(e.accessor_id for e in events))
            report["summary"]["unique_secrets"] = len(set(e.secret_id for e in events))
            
            # Analyze access patterns
            accessor_counts = defaultdict(int)
            secret_counts = defaultdict(int)
            geo_counts = defaultdict(int)
            hour_counts = defaultdict(int)
            
            for event in events:
                accessor_counts[event.accessor_id] += 1
                secret_counts[event.secret_id] += 1
                if event.geographic_location:
                    geo_counts[event.geographic_location] += 1
                hour_counts[event.access_time.hour] += 1
            
            # Top accessors and secrets
            report["top_accessors"] = [
                {"accessor_id": k, "access_count": v}
                for k, v in sorted(accessor_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ]
            
            report["top_secrets"] = [
                {"secret_id": k, "access_count": v}
                for k, v in sorted(secret_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ]
            
            # Geographic and time distribution
            report["geographic_distribution"] = dict(geo_counts)
            report["time_distribution"] = dict(hour_counts)
            
            # Include anomalies if requested
            if include_anomalies:
                anomalies = await self._get_anomalies_in_range(start_time, end_time)
                report["anomalies"] = [asdict(anomaly) for anomaly in anomalies]
                report["summary"]["anomalies_detected"] = len(anomalies)
            
            # Generate recommendations
            report["recommendations"] = self._generate_audit_recommendations(report)
            
            return report
            
        except Exception as e:
            logger.error("audit_report_generation_failed", error=str(e))
            report["error"] = str(e)
            return report
    
    def _generate_audit_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on audit report"""
        
        recommendations = []
        
        # Check failure rate
        total = report["summary"]["total_access_events"]
        failures = report["summary"]["failed_accesses"]
        
        if total > 0:
            failure_rate = failures / total
            if failure_rate > 0.1:  # 10% failure rate
                recommendations.append(
                    f"High failure rate detected ({failure_rate:.1%}). "
                    "Review authentication mechanisms and user training."
                )
        
        # Check for geographic diversity
        geo_locations = len(report["geographic_distribution"])
        if geo_locations > 5:
            recommendations.append(
                f"Access from {geo_locations} different locations detected. "
                "Review geographic access policies."
            )
        
        # Check for off-hours access
        time_dist = report["time_distribution"]
        off_hours_access = sum(count for hour, count in time_dist.items() if hour < 8 or hour > 18)
        total_access = sum(time_dist.values())
        
        if total_access > 0 and off_hours_access / total_access > 0.3:
            recommendations.append(
                "Significant off-hours access detected. "
                "Consider implementing time-based access controls."
            )
        
        return recommendations
    
    async def _start_background_tasks(self):
        """Start background monitoring tasks"""
        self._running = True
        
        self._monitoring_task = asyncio.create_task(self._monitoring_worker())
        self._analysis_task = asyncio.create_task(self._analysis_worker())
        self._cleanup_task = asyncio.create_task(self._cleanup_worker())
    
    async def _monitoring_worker(self):
        """Background worker for continuous monitoring"""
        while self._running:
            try:
                # Detect anomalies in recent events
                anomalies = await self.detect_anomalies(time_window_hours=1)
                
                # Handle critical anomalies immediately
                for anomaly in anomalies:
                    if anomaly.severity == SeverityLevel.CRITICAL:
                        await self._handle_critical_anomaly(anomaly)
                
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error("monitoring_worker_error", error=str(e))
                await asyncio.sleep(60)
    
    async def _analysis_worker(self):
        """Background worker for pattern analysis"""
        while self._running:
            try:
                # Perform deeper pattern analysis
                await self._analyze_long_term_patterns()
                
                await asyncio.sleep(3600)  # Analyze every hour
                
            except Exception as e:
                logger.error("analysis_worker_error", error=str(e))
                await asyncio.sleep(300)
    
    async def _cleanup_worker(self):
        """Background worker for cleanup tasks"""
        while self._running:
            try:
                # Clean up old sessions
                await self._cleanup_old_sessions()
                
                # Archive old events
                await self._archive_old_events()
                
                await asyncio.sleep(86400)  # Daily cleanup
                
            except Exception as e:
                logger.error("cleanup_worker_error", error=str(e))
                await asyncio.sleep(3600)
    
    async def shutdown(self):
        """Shutdown the audit system"""
        self._running = False
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
        if self._analysis_task:
            self._analysis_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        
        logger.info("secret_audit_system_shutdown")


# Global audit system instance
_audit_system: Optional[SecretAuditSystem] = None


def get_audit_system() -> Optional[SecretAuditSystem]:
    """Get the global audit system instance"""
    return _audit_system


async def initialize_audit_system(secrets_manager: SecretsManager, 
                                vault_client: hvac.Client, 
                                config: Dict[str, Any]) -> SecretAuditSystem:
    """Initialize the global audit system"""
    global _audit_system
    
    _audit_system = SecretAuditSystem(secrets_manager, vault_client, config)
    
    if await _audit_system.initialize():
        return _audit_system
    else:
        raise RuntimeError("Failed to initialize secret audit system")