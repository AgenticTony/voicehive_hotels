"""
Configuration Change Approval Workflow System
Implements secure approval workflow for configuration changes with audit trails
"""

import os
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Set
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
# import aiofiles  # Not available, using standard file operations
from prometheus_client import Counter, Gauge, Histogram

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger
from config import VoiceHiveConfig, EnvironmentType

logger = get_safe_logger("orchestrator.config_approval")
audit_logger = AuditLogger("config_approval")

# Metrics
config_change_requests = Counter('voicehive_config_change_requests_total', 'Configuration change requests', ['environment', 'status'])
config_approvals = Counter('voicehive_config_approvals_total', 'Configuration approvals', ['environment', 'approver_role'])
config_rejections = Counter('voicehive_config_rejections_total', 'Configuration rejections', ['environment', 'reason'])
config_approval_duration = Histogram('voicehive_config_approval_duration_seconds', 'Configuration approval duration')
pending_approvals = Gauge('voicehive_pending_config_approvals', 'Pending configuration approvals', ['environment'])


class ApprovalStatus(str, Enum):
    """Configuration change approval status"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalPriority(str, Enum):
    """Configuration change priority levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class ApproverRole(str, Enum):
    """Roles that can approve configuration changes"""
    SECURITY_ADMIN = "security_admin"
    PLATFORM_ADMIN = "platform_admin"
    DEVOPS_LEAD = "devops_lead"
    SYSTEM_ADMIN = "system_admin"
    EMERGENCY_RESPONDER = "emergency_responder"


@dataclass
class ConfigurationChange:
    """Represents a configuration change"""
    
    field_path: str
    old_value: Any
    new_value: Any
    change_type: str  # 'add', 'modify', 'remove'
    justification: str
    impact_assessment: str
    rollback_plan: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'field_path': self.field_path,
            'old_value': self._redact_sensitive(self.old_value),
            'new_value': self._redact_sensitive(self.new_value),
            'change_type': self.change_type,
            'justification': self.justification,
            'impact_assessment': self.impact_assessment,
            'rollback_plan': self.rollback_plan
        }
    
    def _redact_sensitive(self, value: Any) -> str:
        """Redact sensitive values for logging"""
        if isinstance(value, str) and len(value) > 8:
            sensitive_keywords = ['password', 'secret', 'key', 'token']
            if any(keyword in self.field_path.lower() for keyword in sensitive_keywords):
                return f"{value[:4]}***{value[-4:]}"
        return str(value)


@dataclass
class ApprovalRequest:
    """Configuration change approval request"""
    
    request_id: str
    environment: EnvironmentType
    requester: str
    requester_role: str
    changes: List[ConfigurationChange]
    priority: ApprovalPriority
    status: ApprovalStatus
    created_at: datetime
    expires_at: datetime
    justification: str
    impact_assessment: str
    rollback_plan: str
    
    # Approval tracking
    required_approvers: List[ApproverRole]
    approvals: List[Dict[str, Any]]  # List of approval records
    rejections: List[Dict[str, Any]]  # List of rejection records
    
    # Metadata
    config_hash_before: Optional[str] = None
    config_hash_after: Optional[str] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        data['expires_at'] = self.expires_at.isoformat()
        if self.approved_at:
            data['approved_at'] = self.approved_at.isoformat()
        if self.rejected_at:
            data['rejected_at'] = self.rejected_at.isoformat()
        data['changes'] = [change.to_dict() for change in self.changes]
        data['required_approvers'] = [role.value for role in self.required_approvers]
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ApprovalRequest':
        """Create from dictionary"""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        if data.get('approved_at'):
            data['approved_at'] = datetime.fromisoformat(data['approved_at'])
        if data.get('rejected_at'):
            data['rejected_at'] = datetime.fromisoformat(data['rejected_at'])
        
        # Convert changes
        changes = []
        for change_data in data['changes']:
            changes.append(ConfigurationChange(
                field_path=change_data['field_path'],
                old_value=change_data['old_value'],
                new_value=change_data['new_value'],
                change_type=change_data['change_type'],
                justification=change_data['justification'],
                impact_assessment=change_data['impact_assessment'],
                rollback_plan=change_data['rollback_plan']
            ))
        data['changes'] = changes
        
        # Convert required approvers
        data['required_approvers'] = [ApproverRole(role) for role in data['required_approvers']]
        
        return cls(**data)
    
    def is_expired(self) -> bool:
        """Check if approval request has expired"""
        return datetime.now(timezone.utc) > self.expires_at
    
    def get_approval_progress(self) -> Dict[str, Any]:
        """Get approval progress information"""
        total_required = len(self.required_approvers)
        approved_roles = set()
        
        for approval in self.approvals:
            approved_roles.add(approval['approver_role'])
        
        remaining_roles = [role for role in self.required_approvers if role not in approved_roles]
        
        return {
            'total_required': total_required,
            'approved_count': len(approved_roles),
            'remaining_count': len(remaining_roles),
            'approved_roles': list(approved_roles),
            'remaining_roles': [role.value for role in remaining_roles],
            'completion_percentage': (len(approved_roles) / total_required) * 100 if total_required > 0 else 0
        }
    
    def is_fully_approved(self) -> bool:
        """Check if all required approvals have been received"""
        approved_roles = set()
        for approval in self.approvals:
            approved_roles.add(ApproverRole(approval['approver_role']))
        
        return all(role in approved_roles for role in self.required_approvers)


class ConfigurationApprovalWorkflow:
    """
    Configuration change approval workflow system
    """
    
    def __init__(self, 
                 approval_storage_path: str = "/var/lib/voicehive/config-approvals",
                 default_expiry_hours: int = 24):
        
        self.approval_storage_path = Path(approval_storage_path)
        self.default_expiry_hours = default_expiry_hours
        
        # Ensure approval storage directory exists
        self.approval_storage_path.mkdir(parents=True, exist_ok=True)
        
        # Approval rules by environment and field
        self._approval_rules = self._initialize_approval_rules()
        
        # Role hierarchy for emergency approvals
        self._role_hierarchy = {
            ApproverRole.EMERGENCY_RESPONDER: 5,
            ApproverRole.SECURITY_ADMIN: 4,
            ApproverRole.PLATFORM_ADMIN: 3,
            ApproverRole.SYSTEM_ADMIN: 2,
            ApproverRole.DEVOPS_LEAD: 1
        }
    
    def _initialize_approval_rules(self) -> Dict[str, Dict[str, Any]]:
        """Initialize approval rules for different configuration fields"""
        return {
            # Security-critical fields require security admin approval
            'auth.jwt_secret_key': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN, ApproverRole.PLATFORM_ADMIN],
                'priority': ApprovalPriority.CRITICAL,
                'expiry_hours': 4,  # Short expiry for critical changes
                'allow_emergency_override': False
            },
            'security.encryption_key': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN, ApproverRole.PLATFORM_ADMIN],
                'priority': ApprovalPriority.CRITICAL,
                'expiry_hours': 4,
                'allow_emergency_override': False
            },
            'security.webhook_signature_secret': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN],
                'priority': ApprovalPriority.HIGH,
                'expiry_hours': 8,
                'allow_emergency_override': False
            },
            
            # Database configuration
            'database.password': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN, ApproverRole.SYSTEM_ADMIN],
                'priority': ApprovalPriority.HIGH,
                'expiry_hours': 8,
                'allow_emergency_override': True
            },
            'database.ssl_mode': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN],
                'priority': ApprovalPriority.CRITICAL,
                'expiry_hours': 4,
                'allow_emergency_override': False
            },
            
            # Environment and region changes
            'environment': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN, ApproverRole.PLATFORM_ADMIN],
                'priority': ApprovalPriority.CRITICAL,
                'expiry_hours': 2,
                'allow_emergency_override': False
            },
            'region': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN, ApproverRole.PLATFORM_ADMIN],
                'priority': ApprovalPriority.CRITICAL,
                'expiry_hours': 2,
                'allow_emergency_override': False
            },
            
            # Authentication settings
            'auth.jwt_algorithm': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN],
                'priority': ApprovalPriority.HIGH,
                'expiry_hours': 8,
                'allow_emergency_override': False
            },
            'auth.jwt_expiration_minutes': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN],
                'priority': ApprovalPriority.MEDIUM,
                'expiry_hours': 12,
                'allow_emergency_override': True
            },
            
            # External services
            'external_services.vault_url': {
                'required_approvers': [ApproverRole.SECURITY_ADMIN, ApproverRole.SYSTEM_ADMIN],
                'priority': ApprovalPriority.HIGH,
                'expiry_hours': 8,
                'allow_emergency_override': True
            },
            
            # Default rule for unlisted fields
            '_default': {
                'required_approvers': [ApproverRole.SYSTEM_ADMIN],
                'priority': ApprovalPriority.MEDIUM,
                'expiry_hours': 24,
                'allow_emergency_override': True
            }
        }
    
    async def create_approval_request(self,
                                    environment: EnvironmentType,
                                    requester: str,
                                    requester_role: str,
                                    changes: List[ConfigurationChange],
                                    justification: str,
                                    impact_assessment: str,
                                    rollback_plan: str,
                                    priority: Optional[ApprovalPriority] = None) -> ApprovalRequest:
        """
        Create a new configuration change approval request
        
        Args:
            environment: Target environment
            requester: User requesting the change
            requester_role: Role of the requester
            changes: List of configuration changes
            justification: Justification for the changes
            impact_assessment: Assessment of change impact
            rollback_plan: Plan for rolling back changes if needed
            priority: Optional priority override
            
        Returns:
            Created approval request
        """
        
        # Determine required approvers and priority
        required_approvers = set()
        max_priority = ApprovalPriority.LOW
        min_expiry_hours = self.default_expiry_hours
        
        for change in changes:
            rule = self._approval_rules.get(change.field_path, self._approval_rules['_default'])
            required_approvers.update(rule['required_approvers'])
            
            # Use highest priority
            if self._get_priority_level(rule['priority']) > self._get_priority_level(max_priority):
                max_priority = rule['priority']
            
            # Use shortest expiry time
            if rule['expiry_hours'] < min_expiry_hours:
                min_expiry_hours = rule['expiry_hours']
        
        # Override priority if specified
        if priority and self._get_priority_level(priority) > self._get_priority_level(max_priority):
            max_priority = priority
        
        # Production environment requires additional approvals
        if environment == EnvironmentType.PRODUCTION:
            required_approvers.add(ApproverRole.PLATFORM_ADMIN)
        
        # Create approval request
        request_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=min_expiry_hours)
        
        approval_request = ApprovalRequest(
            request_id=request_id,
            environment=environment,
            requester=requester,
            requester_role=requester_role,
            changes=changes,
            priority=max_priority,
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=expires_at,
            justification=justification,
            impact_assessment=impact_assessment,
            rollback_plan=rollback_plan,
            required_approvers=list(required_approvers),
            approvals=[],
            rejections=[]
        )
        
        # Save approval request
        await self._save_approval_request(approval_request)
        
        # Update metrics
        config_change_requests.labels(
            environment=environment.value,
            status=ApprovalStatus.PENDING.value
        ).inc()
        
        pending_approvals.labels(environment=environment.value).inc()
        
        # Audit log
        audit_logger.log_security_event(
            event_type="configuration_approval_request_created",
            details={
                "request_id": request_id,
                "environment": environment.value,
                "requester": requester,
                "requester_role": requester_role,
                "changes_count": len(changes),
                "priority": max_priority.value,
                "required_approvers": [role.value for role in required_approvers],
                "expires_at": expires_at.isoformat()
            },
            severity="medium"
        )
        
        logger.info(
            "configuration_approval_request_created",
            request_id=request_id,
            environment=environment.value,
            requester=requester,
            changes_count=len(changes),
            priority=max_priority.value
        )
        
        return approval_request
    
    async def approve_request(self,
                            request_id: str,
                            approver: str,
                            approver_role: ApproverRole,
                            approval_comments: str = "") -> ApprovalRequest:
        """
        Approve a configuration change request
        
        Args:
            request_id: Request ID to approve
            approver: User approving the request
            approver_role: Role of the approver
            approval_comments: Optional approval comments
            
        Returns:
            Updated approval request
        """
        
        # Load approval request
        approval_request = await self._load_approval_request(request_id)
        if not approval_request:
            raise ValueError(f"Approval request not found: {request_id}")
        
        # Check if request is still pending
        if approval_request.status != ApprovalStatus.PENDING:
            raise ValueError(f"Request is not pending: {approval_request.status}")
        
        # Check if request has expired
        if approval_request.is_expired():
            approval_request.status = ApprovalStatus.EXPIRED
            await self._save_approval_request(approval_request)
            raise ValueError("Approval request has expired")
        
        # Check if approver role is authorized
        if approver_role not in approval_request.required_approvers:
            raise ValueError(f"Role {approver_role.value} not authorized to approve this request")
        
        # Check if this role has already approved
        for existing_approval in approval_request.approvals:
            if existing_approval['approver_role'] == approver_role.value:
                raise ValueError(f"Role {approver_role.value} has already approved this request")
        
        # Add approval
        approval_record = {
            'approver': approver,
            'approver_role': approver_role.value,
            'approved_at': datetime.now(timezone.utc).isoformat(),
            'comments': approval_comments
        }
        
        approval_request.approvals.append(approval_record)
        
        # Check if fully approved
        if approval_request.is_fully_approved():
            approval_request.status = ApprovalStatus.APPROVED
            approval_request.approved_at = datetime.now(timezone.utc)
            approval_request.approved_by = approver
            
            # Update metrics
            config_change_requests.labels(
                environment=approval_request.environment.value,
                status=ApprovalStatus.APPROVED.value
            ).inc()
            
            pending_approvals.labels(environment=approval_request.environment.value).dec()
        
        # Save updated request
        await self._save_approval_request(approval_request)
        
        # Update metrics
        config_approvals.labels(
            environment=approval_request.environment.value,
            approver_role=approver_role.value
        ).inc()
        
        # Audit log
        audit_logger.log_security_event(
            event_type="configuration_change_approved",
            details={
                "request_id": request_id,
                "approver": approver,
                "approver_role": approver_role.value,
                "approval_comments": approval_comments,
                "fully_approved": approval_request.is_fully_approved(),
                "approval_progress": approval_request.get_approval_progress()
            },
            severity="medium"
        )
        
        logger.info(
            "configuration_change_approved",
            request_id=request_id,
            approver=approver,
            approver_role=approver_role.value,
            fully_approved=approval_request.is_fully_approved()
        )
        
        return approval_request
    
    async def reject_request(self,
                           request_id: str,
                           rejector: str,
                           rejector_role: ApproverRole,
                           rejection_reason: str) -> ApprovalRequest:
        """
        Reject a configuration change request
        
        Args:
            request_id: Request ID to reject
            rejector: User rejecting the request
            rejector_role: Role of the rejector
            rejection_reason: Reason for rejection
            
        Returns:
            Updated approval request
        """
        
        # Load approval request
        approval_request = await self._load_approval_request(request_id)
        if not approval_request:
            raise ValueError(f"Approval request not found: {request_id}")
        
        # Check if request is still pending
        if approval_request.status != ApprovalStatus.PENDING:
            raise ValueError(f"Request is not pending: {approval_request.status}")
        
        # Check if rejector role is authorized
        if rejector_role not in approval_request.required_approvers:
            raise ValueError(f"Role {rejector_role.value} not authorized to reject this request")
        
        # Add rejection
        rejection_record = {
            'rejector': rejector,
            'rejector_role': rejector_role.value,
            'rejected_at': datetime.now(timezone.utc).isoformat(),
            'reason': rejection_reason
        }
        
        approval_request.rejections.append(rejection_record)
        approval_request.status = ApprovalStatus.REJECTED
        approval_request.rejected_at = datetime.now(timezone.utc)
        approval_request.rejected_by = rejector
        approval_request.rejection_reason = rejection_reason
        
        # Save updated request
        await self._save_approval_request(approval_request)
        
        # Update metrics
        config_change_requests.labels(
            environment=approval_request.environment.value,
            status=ApprovalStatus.REJECTED.value
        ).inc()
        
        config_rejections.labels(
            environment=approval_request.environment.value,
            reason="manual_rejection"
        ).inc()
        
        pending_approvals.labels(environment=approval_request.environment.value).dec()
        
        # Audit log
        audit_logger.log_security_event(
            event_type="configuration_change_rejected",
            details={
                "request_id": request_id,
                "rejector": rejector,
                "rejector_role": rejector_role.value,
                "rejection_reason": rejection_reason
            },
            severity="medium"
        )
        
        logger.info(
            "configuration_change_rejected",
            request_id=request_id,
            rejector=rejector,
            rejector_role=rejector_role.value,
            rejection_reason=rejection_reason
        )
        
        return approval_request
    
    async def emergency_approve_request(self,
                                      request_id: str,
                                      emergency_approver: str,
                                      emergency_role: ApproverRole,
                                      emergency_justification: str) -> ApprovalRequest:
        """
        Emergency approval for critical configuration changes
        
        Args:
            request_id: Request ID to approve
            emergency_approver: Emergency approver
            emergency_role: Emergency approver role
            emergency_justification: Justification for emergency approval
            
        Returns:
            Updated approval request
        """
        
        # Load approval request
        approval_request = await self._load_approval_request(request_id)
        if not approval_request:
            raise ValueError(f"Approval request not found: {request_id}")
        
        # Check if emergency approval is allowed
        emergency_allowed = False
        for change in approval_request.changes:
            rule = self._approval_rules.get(change.field_path, self._approval_rules['_default'])
            if rule.get('allow_emergency_override', False):
                emergency_allowed = True
                break
        
        if not emergency_allowed:
            raise ValueError("Emergency approval not allowed for this configuration change")
        
        # Check emergency role authorization
        if emergency_role not in [ApproverRole.EMERGENCY_RESPONDER, ApproverRole.SECURITY_ADMIN, ApproverRole.PLATFORM_ADMIN]:
            raise ValueError(f"Role {emergency_role.value} not authorized for emergency approvals")
        
        # Emergency approve
        approval_request.status = ApprovalStatus.APPROVED
        approval_request.approved_at = datetime.now(timezone.utc)
        approval_request.approved_by = emergency_approver
        
        # Add emergency approval record
        emergency_approval = {
            'approver': emergency_approver,
            'approver_role': emergency_role.value,
            'approved_at': datetime.now(timezone.utc).isoformat(),
            'comments': f"EMERGENCY APPROVAL: {emergency_justification}",
            'emergency': True
        }
        
        approval_request.approvals.append(emergency_approval)
        
        # Save updated request
        await self._save_approval_request(approval_request)
        
        # Update metrics
        config_change_requests.labels(
            environment=approval_request.environment.value,
            status=ApprovalStatus.APPROVED.value
        ).inc()
        
        pending_approvals.labels(environment=approval_request.environment.value).dec()
        
        # Audit log - HIGH SEVERITY for emergency approvals
        audit_logger.log_security_event(
            event_type="emergency_configuration_approval",
            details={
                "request_id": request_id,
                "emergency_approver": emergency_approver,
                "emergency_role": emergency_role.value,
                "emergency_justification": emergency_justification,
                "original_required_approvers": [role.value for role in approval_request.required_approvers]
            },
            severity="high"
        )
        
        logger.warning(
            "emergency_configuration_approval",
            request_id=request_id,
            emergency_approver=emergency_approver,
            emergency_role=emergency_role.value
        )
        
        return approval_request
    
    async def get_pending_requests(self, environment: Optional[EnvironmentType] = None) -> List[ApprovalRequest]:
        """Get all pending approval requests"""
        
        requests = []
        
        # List all approval request files
        for request_file in self.approval_storage_path.glob("*.json"):
            try:
                approval_request = await self._load_approval_request_from_file(request_file)
                
                if approval_request and approval_request.status == ApprovalStatus.PENDING:
                    # Check if expired
                    if approval_request.is_expired():
                        approval_request.status = ApprovalStatus.EXPIRED
                        await self._save_approval_request(approval_request)
                        continue
                    
                    # Filter by environment if specified
                    if environment is None or approval_request.environment == environment:
                        requests.append(approval_request)
                        
            except Exception as e:
                logger.error(
                    "failed_to_load_approval_request",
                    request_file=str(request_file),
                    error=str(e)
                )
        
        # Sort by priority and creation time
        requests.sort(key=lambda r: (
            -self._get_priority_level(r.priority),
            r.created_at
        ))
        
        return requests
    
    def _get_priority_level(self, priority: ApprovalPriority) -> int:
        """Get numeric priority level for sorting"""
        levels = {
            ApprovalPriority.LOW: 1,
            ApprovalPriority.MEDIUM: 2,
            ApprovalPriority.HIGH: 3,
            ApprovalPriority.CRITICAL: 4,
            ApprovalPriority.EMERGENCY: 5
        }
        return levels.get(priority, 1)
    
    async def _save_approval_request(self, approval_request: ApprovalRequest):
        """Save approval request to storage"""
        
        request_file = self.approval_storage_path / f"{approval_request.request_id}.json"
        
        try:
            with open(request_file, 'w') as f:
                f.write(json.dumps(approval_request.to_dict(), indent=2))
                
        except Exception as e:
            logger.error(
                "failed_to_save_approval_request",
                request_id=approval_request.request_id,
                error=str(e)
            )
            raise
    
    async def _load_approval_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Load approval request by ID"""
        
        request_file = self.approval_storage_path / f"{request_id}.json"
        return await self._load_approval_request_from_file(request_file)
    
    async def _load_approval_request_from_file(self, request_file: Path) -> Optional[ApprovalRequest]:
        """Load approval request from file"""
        
        if not request_file.exists():
            return None
        
        try:
            with open(request_file, 'r') as f:
                data = json.load(f)
            
            return ApprovalRequest.from_dict(data)
            
        except Exception as e:
            logger.error(
                "failed_to_load_approval_request_from_file",
                request_file=str(request_file),
                error=str(e)
            )
            return None


# Global approval workflow instance
approval_workflow = ConfigurationApprovalWorkflow()


async def create_config_change_request(environment: EnvironmentType,
                                     requester: str,
                                     requester_role: str,
                                     changes: List[ConfigurationChange],
                                     justification: str,
                                     impact_assessment: str,
                                     rollback_plan: str,
                                     priority: Optional[ApprovalPriority] = None) -> ApprovalRequest:
    """Create a configuration change approval request"""
    return await approval_workflow.create_approval_request(
        environment=environment,
        requester=requester,
        requester_role=requester_role,
        changes=changes,
        justification=justification,
        impact_assessment=impact_assessment,
        rollback_plan=rollback_plan,
        priority=priority
    )


async def approve_config_change(request_id: str,
                              approver: str,
                              approver_role: ApproverRole,
                              approval_comments: str = "") -> ApprovalRequest:
    """Approve a configuration change request"""
    return await approval_workflow.approve_request(
        request_id=request_id,
        approver=approver,
        approver_role=approver_role,
        approval_comments=approval_comments
    )


async def reject_config_change(request_id: str,
                             rejector: str,
                             rejector_role: ApproverRole,
                             rejection_reason: str) -> ApprovalRequest:
    """Reject a configuration change request"""
    return await approval_workflow.reject_request(
        request_id=request_id,
        rejector=rejector,
        rejector_role=rejector_role,
        rejection_reason=rejection_reason
    )


async def emergency_approve_config_change(request_id: str,
                                        emergency_approver: str,
                                        emergency_role: ApproverRole,
                                        emergency_justification: str) -> ApprovalRequest:
    """Emergency approve a configuration change request"""
    return await approval_workflow.emergency_approve_request(
        request_id=request_id,
        emergency_approver=emergency_approver,
        emergency_role=emergency_role,
        emergency_justification=emergency_justification
    )


async def get_pending_config_requests(environment: Optional[EnvironmentType] = None) -> List[ApprovalRequest]:
    """Get pending configuration change requests"""
    return await approval_workflow.get_pending_requests(environment)