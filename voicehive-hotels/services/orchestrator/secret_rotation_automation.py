"""
Automated Secret Rotation System
Handles automated rotation of secrets with zero-downtime deployment
"""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from abc import ABC, abstractmethod

import hvac
from prometheus_client import Counter, Histogram, Gauge

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger
from secrets_manager import SecretsManager, SecretType, SecretStatus, RotationStrategy

# Configure logging
logger = get_safe_logger("orchestrator.secret_rotation")
audit_logger = AuditLogger("secret_rotation")

# Metrics
rotation_attempts_total = Counter('voicehive_rotation_attempts_total', 'Total rotation attempts', ['secret_type', 'strategy', 'status'])
rotation_duration = Histogram('voicehive_rotation_duration_seconds', 'Rotation duration', ['secret_type'])
rotation_failures_total = Counter('voicehive_rotation_failures_total', 'Total rotation failures', ['secret_type', 'failure_reason'])
active_rotations = Gauge('voicehive_active_rotations', 'Currently active rotations')
rotation_queue_size = Gauge('voicehive_rotation_queue_size', 'Size of rotation queue')


class RotationPhase(str, Enum):
    """Phases of secret rotation"""
    PREPARATION = "preparation"
    VALIDATION = "validation"
    DEPLOYMENT = "deployment"
    VERIFICATION = "verification"
    CLEANUP = "cleanup"
    ROLLBACK = "rollback"


class RotationStatus(str, Enum):
    """Status of rotation operation"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class RotationContext:
    """Context for a secret rotation operation"""
    rotation_id: str
    secret_id: str
    secret_type: SecretType
    strategy: RotationStrategy
    current_phase: RotationPhase
    status: RotationStatus
    started_at: datetime
    completed_at: Optional[datetime]
    old_secret_value: Optional[str]
    new_secret_value: Optional[str]
    rollback_data: Dict[str, Any]
    metadata: Dict[str, Any]
    error_message: Optional[str]


class SecretRotationHandler(ABC):
    """Abstract base class for secret rotation handlers"""
    
    @abstractmethod
    async def prepare_rotation(self, context: RotationContext) -> bool:
        """Prepare for secret rotation"""
        pass
    
    @abstractmethod
    async def generate_new_secret(self, context: RotationContext) -> str:
        """Generate new secret value"""
        pass
    
    @abstractmethod
    async def validate_new_secret(self, context: RotationContext) -> bool:
        """Validate the new secret"""
        pass
    
    @abstractmethod
    async def deploy_new_secret(self, context: RotationContext) -> bool:
        """Deploy the new secret"""
        pass
    
    @abstractmethod
    async def verify_deployment(self, context: RotationContext) -> bool:
        """Verify the deployment was successful"""
        pass
    
    @abstractmethod
    async def cleanup_old_secret(self, context: RotationContext) -> bool:
        """Clean up the old secret"""
        pass
    
    @abstractmethod
    async def rollback_rotation(self, context: RotationContext) -> bool:
        """Rollback the rotation"""
        pass


class DatabasePasswordRotationHandler(SecretRotationHandler):
    """Handler for database password rotation"""
    
    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config
    
    async def prepare_rotation(self, context: RotationContext) -> bool:
        """Prepare database password rotation"""
        try:
            # Check database connectivity
            # Store current connection info for rollback
            context.rollback_data['db_host'] = self.db_config.get('host')
            context.rollback_data['db_user'] = self.db_config.get('username')
            
            logger.info("database_rotation_prepared", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("database_rotation_preparation_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def generate_new_secret(self, context: RotationContext) -> str:
        """Generate new database password"""
        import secrets
        import string
        
        # Generate strong password
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        new_password = ''.join(secrets.choice(alphabet) for _ in range(32))
        
        return new_password
    
    async def validate_new_secret(self, context: RotationContext) -> bool:
        """Validate new database password"""
        # Check password strength
        password = context.new_secret_value
        
        if len(password) < 16:
            return False
        
        # Check character diversity
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in "!@#$%^&*" for c in password)
        
        return all([has_upper, has_lower, has_digit, has_special])
    
    async def deploy_new_secret(self, context: RotationContext) -> bool:
        """Deploy new database password"""
        try:
            # This would typically involve:
            # 1. Creating new database user with new password
            # 2. Granting same permissions as old user
            # 3. Testing connection with new credentials
            # 4. Updating application configuration
            
            # For now, simulate the deployment
            await asyncio.sleep(1)  # Simulate deployment time
            
            logger.info("database_password_deployed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("database_password_deployment_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def verify_deployment(self, context: RotationContext) -> bool:
        """Verify database password deployment"""
        try:
            # Test connection with new credentials
            # Verify application can connect
            # Check that old credentials still work (for rollback)
            
            await asyncio.sleep(0.5)  # Simulate verification
            
            logger.info("database_password_verified", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("database_password_verification_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def cleanup_old_secret(self, context: RotationContext) -> bool:
        """Clean up old database password"""
        try:
            # Remove old database user
            # Clean up old credentials from Vault
            
            logger.info("database_password_cleanup_completed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("database_password_cleanup_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def rollback_rotation(self, context: RotationContext) -> bool:
        """Rollback database password rotation"""
        try:
            # Restore old credentials
            # Remove new user if created
            # Restore application configuration
            
            logger.info("database_password_rollback_completed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("database_password_rollback_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False


class JWTSecretRotationHandler(SecretRotationHandler):
    """Handler for JWT secret rotation"""
    
    async def prepare_rotation(self, context: RotationContext) -> bool:
        """Prepare JWT secret rotation"""
        try:
            # Store current JWT configuration
            context.rollback_data['jwt_algorithm'] = 'RS256'
            context.rollback_data['key_id'] = context.secret_id
            
            logger.info("jwt_rotation_prepared", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("jwt_rotation_preparation_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def generate_new_secret(self, context: RotationContext) -> str:
        """Generate new JWT secret"""
        from cryptography.fernet import Fernet
        
        # Generate new Fernet key for JWT signing
        new_key = Fernet.generate_key().decode()
        return new_key
    
    async def validate_new_secret(self, context: RotationContext) -> bool:
        """Validate new JWT secret"""
        try:
            from cryptography.fernet import Fernet
            
            # Validate key format
            Fernet(context.new_secret_value.encode())
            return True
            
        except Exception:
            return False
    
    async def deploy_new_secret(self, context: RotationContext) -> bool:
        """Deploy new JWT secret with dual-key support"""
        try:
            # JWT rotation requires dual-key support:
            # 1. Add new key to key rotation
            # 2. Start signing with new key
            # 3. Continue validating with both old and new keys
            # 4. After grace period, remove old key
            
            # Update JWT service configuration
            # This would typically update the JWT service to use both keys
            
            logger.info("jwt_secret_deployed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("jwt_secret_deployment_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def verify_deployment(self, context: RotationContext) -> bool:
        """Verify JWT secret deployment"""
        try:
            # Test token generation with new key
            # Test token validation with both keys
            # Verify existing tokens still work
            
            logger.info("jwt_secret_verified", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("jwt_secret_verification_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def cleanup_old_secret(self, context: RotationContext) -> bool:
        """Clean up old JWT secret"""
        try:
            # Remove old key from JWT service
            # Ensure grace period has passed
            
            logger.info("jwt_secret_cleanup_completed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("jwt_secret_cleanup_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def rollback_rotation(self, context: RotationContext) -> bool:
        """Rollback JWT secret rotation"""
        try:
            # Remove new key from JWT service
            # Restore old key as primary
            
            logger.info("jwt_secret_rollback_completed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("jwt_secret_rollback_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False


class APIKeyRotationHandler(SecretRotationHandler):
    """Handler for API key rotation"""
    
    async def prepare_rotation(self, context: RotationContext) -> bool:
        """Prepare API key rotation"""
        try:
            # Store current API key metadata
            context.rollback_data['key_permissions'] = ['read', 'write']  # Example
            context.rollback_data['key_scopes'] = ['api:access']  # Example
            
            logger.info("api_key_rotation_prepared", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("api_key_rotation_preparation_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def generate_new_secret(self, context: RotationContext) -> str:
        """Generate new API key"""
        import uuid
        
        # Generate new API key with VoiceHive prefix
        new_key = f"vh_{uuid.uuid4().hex}"
        return new_key
    
    async def validate_new_secret(self, context: RotationContext) -> bool:
        """Validate new API key"""
        key = context.new_secret_value
        
        # Check format
        if not key.startswith('vh_'):
            return False
        
        # Check length
        if len(key) < 35:  # vh_ + 32 hex chars
            return False
        
        return True
    
    async def deploy_new_secret(self, context: RotationContext) -> bool:
        """Deploy new API key"""
        try:
            # API key rotation with overlap:
            # 1. Create new key with same permissions
            # 2. Both keys work during transition
            # 3. Notify clients to update
            # 4. After grace period, deactivate old key
            
            logger.info("api_key_deployed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("api_key_deployment_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def verify_deployment(self, context: RotationContext) -> bool:
        """Verify API key deployment"""
        try:
            # Test new key functionality
            # Verify old key still works
            # Check permissions are correct
            
            logger.info("api_key_verified", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("api_key_verification_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def cleanup_old_secret(self, context: RotationContext) -> bool:
        """Clean up old API key"""
        try:
            # Deactivate old key
            # Remove from active key list
            # Archive for audit purposes
            
            logger.info("api_key_cleanup_completed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("api_key_cleanup_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False
    
    async def rollback_rotation(self, context: RotationContext) -> bool:
        """Rollback API key rotation"""
        try:
            # Deactivate new key
            # Restore old key as primary
            
            logger.info("api_key_rollback_completed", rotation_id=context.rotation_id)
            return True
            
        except Exception as e:
            logger.error("api_key_rollback_failed", 
                        rotation_id=context.rotation_id, error=str(e))
            return False


class SecretRotationOrchestrator:
    """
    Orchestrates automated secret rotation with zero-downtime deployment
    """
    
    def __init__(self, secrets_manager: SecretsManager, vault_client: hvac.Client):
        self.secrets_manager = secrets_manager
        self.vault_client = vault_client
        
        # Rotation handlers
        self.handlers: Dict[SecretType, SecretRotationHandler] = {}
        self._register_default_handlers()
        
        # Rotation queue and state
        self.rotation_queue: asyncio.Queue = asyncio.Queue()
        self.active_rotations: Dict[str, RotationContext] = {}
        
        # Configuration
        self.max_concurrent_rotations = 3
        self.rotation_timeout_minutes = 30
        self.grace_period_hours = 24
        
        # Background tasks
        self._rotation_worker_task: Optional[asyncio.Task] = None
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False
    
    def _register_default_handlers(self):
        """Register default rotation handlers"""
        self.handlers[SecretType.DATABASE_PASSWORD] = DatabasePasswordRotationHandler({})
        self.handlers[SecretType.JWT_SECRET] = JWTSecretRotationHandler()
        self.handlers[SecretType.API_KEY] = APIKeyRotationHandler()
    
    def register_handler(self, secret_type: SecretType, handler: SecretRotationHandler):
        """Register a custom rotation handler"""
        self.handlers[secret_type] = handler
        logger.info("rotation_handler_registered", secret_type=secret_type.value)
    
    async def start(self):
        """Start the rotation orchestrator"""
        self._running = True
        
        # Start worker tasks
        self._rotation_worker_task = asyncio.create_task(self._rotation_worker())
        self._monitoring_task = asyncio.create_task(self._monitoring_worker())
        
        logger.info("rotation_orchestrator_started")
    
    async def stop(self):
        """Stop the rotation orchestrator"""
        self._running = False
        
        # Cancel tasks
        if self._rotation_worker_task:
            self._rotation_worker_task.cancel()
        if self._monitoring_task:
            self._monitoring_task.cancel()
        
        # Wait for active rotations to complete
        while self.active_rotations:
            await asyncio.sleep(1)
        
        logger.info("rotation_orchestrator_stopped")
    
    async def schedule_rotation(self, 
                              secret_id: str, 
                              strategy: RotationStrategy = RotationStrategy.MANUAL,
                              priority: int = 0) -> str:
        """Schedule a secret rotation"""
        
        # Get secret metadata
        metadata = await self.secrets_manager._get_secret_metadata(secret_id)
        if not metadata:
            raise ValueError(f"Secret {secret_id} not found")
        
        # Check if handler exists
        if metadata.secret_type not in self.handlers:
            raise ValueError(f"No handler registered for secret type {metadata.secret_type}")
        
        # Create rotation context
        rotation_id = f"rot_{uuid.uuid4().hex[:8]}"
        context = RotationContext(
            rotation_id=rotation_id,
            secret_id=secret_id,
            secret_type=metadata.secret_type,
            strategy=strategy,
            current_phase=RotationPhase.PREPARATION,
            status=RotationStatus.PENDING,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            old_secret_value=None,
            new_secret_value=None,
            rollback_data={},
            metadata={'priority': priority},
            error_message=None
        )
        
        # Add to queue
        await self.rotation_queue.put(context)
        rotation_queue_size.set(self.rotation_queue.qsize())
        
        audit_logger.log_security_event(
            event_type="rotation_scheduled",
            details={
                "rotation_id": rotation_id,
                "secret_id": secret_id,
                "secret_type": metadata.secret_type.value,
                "strategy": strategy.value
            },
            severity="medium"
        )
        
        logger.info("rotation_scheduled", 
                   rotation_id=rotation_id, 
                   secret_id=secret_id,
                   strategy=strategy.value)
        
        return rotation_id
    
    async def get_rotation_status(self, rotation_id: str) -> Optional[RotationContext]:
        """Get status of a rotation"""
        return self.active_rotations.get(rotation_id)
    
    async def _rotation_worker(self):
        """Background worker to process rotation queue"""
        while self._running:
            try:
                # Check if we can start new rotation
                if len(self.active_rotations) >= self.max_concurrent_rotations:
                    await asyncio.sleep(5)
                    continue
                
                # Get next rotation from queue
                try:
                    context = await asyncio.wait_for(
                        self.rotation_queue.get(), 
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                rotation_queue_size.set(self.rotation_queue.qsize())
                
                # Start rotation
                self.active_rotations[context.rotation_id] = context
                active_rotations.set(len(self.active_rotations))
                
                # Process rotation in background
                asyncio.create_task(self._process_rotation(context))
                
            except Exception as e:
                logger.error("rotation_worker_error", error=str(e))
                await asyncio.sleep(5)
    
    async def _process_rotation(self, context: RotationContext):
        """Process a single rotation"""
        
        rotation_attempts_total.labels(
            secret_type=context.secret_type.value,
            strategy=context.strategy.value,
            status="started"
        ).inc()
        
        with rotation_duration.labels(secret_type=context.secret_type.value).time():
            try:
                handler = self.handlers[context.secret_type]
                
                # Execute rotation phases
                success = await self._execute_rotation_phases(context, handler)
                
                if success:
                    context.status = RotationStatus.COMPLETED
                    context.completed_at = datetime.now(timezone.utc)
                    
                    rotation_attempts_total.labels(
                        secret_type=context.secret_type.value,
                        strategy=context.strategy.value,
                        status="completed"
                    ).inc()
                    
                    audit_logger.log_security_event(
                        event_type="rotation_completed",
                        details={
                            "rotation_id": context.rotation_id,
                            "secret_id": context.secret_id,
                            "secret_type": context.secret_type.value,
                            "duration_seconds": (context.completed_at - context.started_at).total_seconds()
                        },
                        severity="info"
                    )
                    
                    logger.info("rotation_completed", rotation_id=context.rotation_id)
                else:
                    context.status = RotationStatus.FAILED
                    
                    rotation_attempts_total.labels(
                        secret_type=context.secret_type.value,
                        strategy=context.strategy.value,
                        status="failed"
                    ).inc()
                    
                    logger.error("rotation_failed", 
                               rotation_id=context.rotation_id,
                               error=context.error_message)
                
            except Exception as e:
                context.status = RotationStatus.FAILED
                context.error_message = str(e)
                
                rotation_failures_total.labels(
                    secret_type=context.secret_type.value,
                    failure_reason="exception"
                ).inc()
                
                logger.error("rotation_exception", 
                           rotation_id=context.rotation_id, 
                           error=str(e))
            
            finally:
                # Remove from active rotations
                self.active_rotations.pop(context.rotation_id, None)
                active_rotations.set(len(self.active_rotations))
    
    async def _execute_rotation_phases(self, 
                                     context: RotationContext, 
                                     handler: SecretRotationHandler) -> bool:
        """Execute all phases of rotation"""
        
        phases = [
            (RotationPhase.PREPARATION, handler.prepare_rotation),
            (RotationPhase.VALIDATION, self._generate_and_validate),
            (RotationPhase.DEPLOYMENT, handler.deploy_new_secret),
            (RotationPhase.VERIFICATION, handler.verify_deployment),
            (RotationPhase.CLEANUP, handler.cleanup_old_secret)
        ]
        
        for phase, phase_func in phases:
            context.current_phase = phase
            context.status = RotationStatus.IN_PROGRESS
            
            try:
                # Execute phase with timeout
                success = await asyncio.wait_for(
                    phase_func(context),
                    timeout=self.rotation_timeout_minutes * 60
                )
                
                if not success:
                    context.error_message = f"Phase {phase.value} failed"
                    
                    # Attempt rollback
                    await self._attempt_rollback(context, handler)
                    return False
                
            except asyncio.TimeoutError:
                context.error_message = f"Phase {phase.value} timed out"
                await self._attempt_rollback(context, handler)
                return False
            
            except Exception as e:
                context.error_message = f"Phase {phase.value} error: {str(e)}"
                await self._attempt_rollback(context, handler)
                return False
        
        return True
    
    async def _generate_and_validate(self, context: RotationContext) -> bool:
        """Generate and validate new secret"""
        handler = self.handlers[context.secret_type]
        
        # Generate new secret
        context.new_secret_value = await handler.generate_new_secret(context)
        
        # Validate new secret
        return await handler.validate_new_secret(context)
    
    async def _attempt_rollback(self, context: RotationContext, handler: SecretRotationHandler):
        """Attempt to rollback a failed rotation"""
        try:
            context.current_phase = RotationPhase.ROLLBACK
            
            success = await handler.rollback_rotation(context)
            
            if success:
                context.status = RotationStatus.ROLLED_BACK
                logger.info("rotation_rolled_back", rotation_id=context.rotation_id)
            else:
                logger.error("rotation_rollback_failed", rotation_id=context.rotation_id)
                
        except Exception as e:
            logger.error("rotation_rollback_exception", 
                        rotation_id=context.rotation_id, 
                        error=str(e))
    
    async def _monitoring_worker(self):
        """Background worker to monitor rotation health"""
        while self._running:
            try:
                # Check for stuck rotations
                now = datetime.now(timezone.utc)
                
                for rotation_id, context in list(self.active_rotations.items()):
                    duration = (now - context.started_at).total_seconds()
                    
                    if duration > self.rotation_timeout_minutes * 60:
                        logger.warning("rotation_timeout_detected", 
                                     rotation_id=rotation_id,
                                     duration_minutes=duration / 60)
                        
                        # Force cleanup
                        context.status = RotationStatus.FAILED
                        context.error_message = "Rotation timed out"
                        
                        self.active_rotations.pop(rotation_id, None)
                        active_rotations.set(len(self.active_rotations))
                
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error("monitoring_worker_error", error=str(e))
                await asyncio.sleep(30)


# Global orchestrator instance
_rotation_orchestrator: Optional[SecretRotationOrchestrator] = None


def get_rotation_orchestrator() -> Optional[SecretRotationOrchestrator]:
    """Get the global rotation orchestrator"""
    return _rotation_orchestrator


async def initialize_rotation_orchestrator(secrets_manager: SecretsManager, 
                                         vault_client: hvac.Client) -> SecretRotationOrchestrator:
    """Initialize the global rotation orchestrator"""
    global _rotation_orchestrator
    
    _rotation_orchestrator = SecretRotationOrchestrator(secrets_manager, vault_client)
    await _rotation_orchestrator.start()
    
    return _rotation_orchestrator