"""
SQLAlchemy models for user management and authentication
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, ForeignKey,
    Table, Integer, JSON, CheckConstraint, UniqueConstraint, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, validates
from sqlalchemy.dialects.postgresql import UUID, ARRAY
import bcrypt

from auth_models import UserRole, Permission

Base = declarative_base()

# Association table for user roles (many-to-many)
user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id'), primary_key=True),
    Column('role_id', UUID(as_uuid=True), ForeignKey('roles.id'), primary_key=True),
    Column('created_at', DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    Column('created_by', UUID(as_uuid=True), ForeignKey('users.id')),
)

# Association table for user hotels (many-to-many)
user_hotels = Table(
    'user_hotels',
    Base.metadata,
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id'), primary_key=True),
    Column('hotel_id', String(255), primary_key=True),  # External hotel ID from PMS
    Column('created_at', DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)),
    Column('created_by', UUID(as_uuid=True), ForeignKey('users.id')),
)


class User(Base):
    """User model for authentication and authorization"""

    __tablename__ = 'users'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # User identification
    email = Column(String(255), unique=True, nullable=False, index=True)

    # Authentication
    password_hash = Column(String(255), nullable=False)

    # Profile information
    first_name = Column(String(100))
    last_name = Column(String(100))

    # Status fields
    active = Column(Boolean, default=True, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    last_login_at = Column(DateTime(timezone=True))
    password_changed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Security fields
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True))

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    updated_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))

    # Relationships
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    hotels = relationship("Hotel", secondary=user_hotels, back_populates="users")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")

    # Self-referential relationships for audit
    created_by_user = relationship("User", foreign_keys=[created_by], remote_side=[id])
    updated_by_user = relationship("User", foreign_keys=[updated_by], remote_side=[id])

    # Constraints
    __table_args__ = (
        CheckConstraint('failed_login_attempts >= 0', name='check_failed_attempts_positive'),
        CheckConstraint('email_verified IN (true, false)', name='check_email_verified_boolean'),
        CheckConstraint('active IN (true, false)', name='check_active_boolean'),
        CheckConstraint(
            r'email ~ \'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$\'',
            name='check_email_format'
        ),
    )

    @validates('email')
    def validate_email(self, key, email):
        """Validate email format"""
        if not email or '@' not in email:
            raise ValueError("Invalid email format")
        return email.lower().strip()

    def set_password(self, password: str) -> None:
        """Hash and set password"""
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters long")

        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        self.password_changed_at = datetime.now(timezone.utc)

    def verify_password(self, password: str) -> bool:
        """Verify password against hash"""
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def is_locked(self) -> bool:
        """Check if user account is locked"""
        if not self.locked_until:
            return False
        return datetime.now(timezone.utc) < self.locked_until

    def can_login(self) -> bool:
        """Check if user can log in"""
        return self.active and self.email_verified and not self.is_locked()

    def get_permissions(self) -> List[Permission]:
        """Get all permissions from user roles"""
        permissions = set()
        for role in self.roles:
            permissions.update(role.permissions)
        return list(permissions)

    def has_permission(self, permission: Permission) -> bool:
        """Check if user has specific permission"""
        return permission in self.get_permissions()

    def has_role(self, role_name: UserRole) -> bool:
        """Check if user has specific role"""
        return any(role.name == role_name for role in self.roles)

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, active={self.active})>"


class Role(Base):
    """Role model for role-based access control"""

    __tablename__ = 'roles'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Role information
    name = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    description = Column(Text)

    # Permissions (stored as JSON array)
    permissions = Column(ARRAY(String), nullable=False, default=list)

    # Status
    active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    updated_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))

    # Relationships
    users = relationship("User", secondary=user_roles, back_populates="roles")

    @validates('name')
    def validate_role_name(self, key, name):
        """Validate role name is a valid UserRole enum"""
        if name not in [role.value for role in UserRole]:
            raise ValueError(f"Invalid role name: {name}")
        return name

    @validates('permissions')
    def validate_permissions(self, key, permissions):
        """Validate permissions are valid Permission enum values"""
        if not permissions:
            return []

        valid_permissions = [perm.value for perm in Permission]
        for permission in permissions:
            if permission not in valid_permissions:
                raise ValueError(f"Invalid permission: {permission}")
        return permissions

    def __repr__(self):
        return f"<Role(id={self.id}, name={self.name}, active={self.active})>"


class Hotel(Base):
    """Hotel model for multi-tenant hotel management"""

    __tablename__ = 'hotels'

    # Primary key (external hotel ID from PMS)
    id = Column(String(255), primary_key=True)  # PMS hotel ID

    # Hotel information
    name = Column(String(255), nullable=False)
    brand = Column(String(100))

    # Location
    country = Column(String(2))  # ISO country code
    city = Column(String(100))
    address = Column(Text)

    # PMS Integration
    pms_type = Column(String(50), nullable=False)  # apaleo, mews, opera, etc.
    pms_config = Column(JSON)  # PMS-specific configuration

    # Status
    active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    users = relationship("User", secondary=user_hotels, back_populates="hotels")

    __table_args__ = (
        CheckConstraint('active IN (true, false)', name='check_hotel_active_boolean'),
        CheckConstraint('LENGTH(country) = 2', name='check_country_iso_code'),
    )

    def __repr__(self):
        return f"<Hotel(id={self.id}, name={self.name}, pms_type={self.pms_type})>"


class UserSession(Base):
    """User session model for session management"""

    __tablename__ = 'user_sessions'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # Session information
    session_id = Column(String(255), unique=True, nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    # JWT information
    access_token_jti = Column(String(255), unique=True, nullable=False, index=True)
    refresh_token_jti = Column(String(255), unique=True, index=True)

    # Session metadata
    ip_address = Column(String(45))  # IPv6 compatible
    user_agent = Column(Text)
    device_fingerprint = Column(String(255))

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    accessed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    # Status
    active = Column(Boolean, default=True, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    revoke_reason = Column(String(100))

    # Relationships
    user = relationship("User", back_populates="sessions")

    __table_args__ = (
        CheckConstraint('active IN (true, false)', name='check_session_active_boolean'),
        CheckConstraint('revoked IN (true, false)', name='check_session_revoked_boolean'),
        UniqueConstraint('user_id', 'session_id', name='unique_user_session'),
    )

    def is_valid(self) -> bool:
        """Check if session is valid and not expired"""
        now = datetime.now(timezone.utc)
        return (
            self.active and
            not self.revoked and
            self.expires_at > now
        )

    def revoke(self, reason: str = "manual_revocation") -> None:
        """Revoke the session"""
        self.revoked = True
        self.revoked_at = datetime.now(timezone.utc)
        self.revoke_reason = reason

    def touch(self) -> None:
        """Update last accessed time"""
        self.accessed_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f"<UserSession(id={self.id}, user_id={self.user_id}, active={self.active})>"


class UserMFA(Base):
    """User Multi-Factor Authentication settings and secrets"""

    __tablename__ = 'user_mfa'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # User reference
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, unique=True)

    # MFA Configuration
    enabled = Column(Boolean, default=False, nullable=False)
    totp_secret = Column(String(255))  # Encrypted TOTP secret
    backup_codes_hash = Column(Text)  # Hashed backup codes (JSON array)

    # Enrollment tracking
    enrolled_at = Column(DateTime(timezone=True))
    enrolled_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))
    last_verified_at = Column(DateTime(timezone=True))

    # Recovery information
    recovery_codes_generated_at = Column(DateTime(timezone=True))
    recovery_codes_used_count = Column(Integer, default=0, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="mfa_settings")
    enrolled_by_user = relationship("User", foreign_keys=[enrolled_by])

    __table_args__ = (
        CheckConstraint('enabled IN (true, false)', name='check_mfa_enabled_boolean'),
        CheckConstraint('recovery_codes_used_count >= 0', name='check_recovery_codes_used_positive'),
        Index('idx_user_mfa_user_id', 'user_id'),
        Index('idx_user_mfa_enabled', 'enabled'),
    )

    def is_enrolled(self) -> bool:
        """Check if MFA is properly enrolled and enabled"""
        return self.enabled and self.totp_secret is not None

    def can_use_recovery_codes(self) -> bool:
        """Check if user has unused recovery codes"""
        return (
            self.backup_codes_hash is not None and
            self.recovery_codes_used_count < 10  # Assuming 10 recovery codes
        )

    def __repr__(self):
        return f"<UserMFA(id={self.id}, user_id={self.user_id}, enabled={self.enabled})>"


class MFAAuditLog(Base):
    """Audit log for MFA-related events"""

    __tablename__ = 'mfa_audit_log'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # User and event information
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    event_type = Column(String(50), nullable=False)  # enrollment, verification, recovery, etc.
    event_result = Column(String(20), nullable=False)  # success, failure, error

    # Event details
    verification_method = Column(String(20))  # totp, recovery_code, backup
    ip_address = Column(String(45))  # IPv6 compatible
    user_agent = Column(Text)
    session_id = Column(String(255))

    # Additional context
    metadata = Column(JSON)  # Additional event-specific data

    # Timestamp
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    user = relationship("User", backref="mfa_audit_logs")

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('enrollment', 'verification', 'recovery_code_used', 'recovery_code_generated', 'disabled', 'secret_regenerated')",
            name='check_mfa_event_type'
        ),
        CheckConstraint(
            "event_result IN ('success', 'failure', 'error')",
            name='check_mfa_event_result'
        ),
        CheckConstraint(
            "verification_method IS NULL OR verification_method IN ('totp', 'recovery_code', 'backup')",
            name='check_mfa_verification_method'
        ),
        Index('idx_mfa_audit_user_id', 'user_id'),
        Index('idx_mfa_audit_created_at', 'created_at'),
        Index('idx_mfa_audit_event_type', 'event_type'),
        Index('idx_mfa_audit_user_event', 'user_id', 'event_type'),
    )

    def __repr__(self):
        return f"<MFAAuditLog(id={self.id}, user_id={self.user_id}, event_type={self.event_type}, result={self.event_result})>"


class MFARecoveryCode(Base):
    """Individual MFA recovery codes for users"""

    __tablename__ = 'mfa_recovery_codes'

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)

    # User reference
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)

    # Recovery code information
    code_hash = Column(String(255), nullable=False)  # Hashed recovery code
    used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime(timezone=True))
    used_ip_address = Column(String(45))

    # Generation information
    generated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    generated_by = Column(UUID(as_uuid=True), ForeignKey('users.id'))

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    generated_by_user = relationship("User", foreign_keys=[generated_by])

    __table_args__ = (
        CheckConstraint('used IN (true, false)', name='check_recovery_code_used_boolean'),
        Index('idx_recovery_codes_user_id', 'user_id'),
        Index('idx_recovery_codes_used', 'used'),
        Index('idx_recovery_codes_user_unused', 'user_id', 'used'),
        UniqueConstraint('user_id', 'code_hash', name='unique_user_recovery_code'),
    )

    def mark_used(self, ip_address: str = None) -> None:
        """Mark recovery code as used"""
        self.used = True
        self.used_at = datetime.now(timezone.utc)
        self.used_ip_address = ip_address

    def __repr__(self):
        return f"<MFARecoveryCode(id={self.id}, user_id={self.user_id}, used={self.used})>"