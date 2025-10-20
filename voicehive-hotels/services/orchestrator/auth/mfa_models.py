"""
Pydantic models for MFA (Multi-Factor Authentication) API requests and responses
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator


class MFAEnrollmentRequest(BaseModel):
    """Request to start MFA enrollment"""
    pass  # No additional fields needed, user comes from auth context


class MFAEnrollmentResponse(BaseModel):
    """Response for MFA enrollment start"""
    provisioning_uri: str = Field(..., description="URI for QR code generation")
    qr_code: str = Field(..., description="Base64-encoded QR code image")
    backup_instructions: str = Field(
        default="Save this QR code or manually enter the secret into your authenticator app",
        description="Instructions for setting up MFA"
    )


class MFAEnrollmentVerificationRequest(BaseModel):
    """Request to complete MFA enrollment with verification code"""
    verification_code: str = Field(..., min_length=6, max_length=6, description="6-digit TOTP code")

    @validator('verification_code')
    def validate_verification_code(cls, v):
        if not v.isdigit():
            raise ValueError('Verification code must contain only digits')
        return v


class MFAEnrollmentVerificationResponse(BaseModel):
    """Response for MFA enrollment completion"""
    success: bool = Field(..., description="Whether enrollment was successful")
    recovery_codes: List[str] = Field(..., description="One-time recovery codes")
    message: str = Field(
        default="MFA has been successfully enabled. Save these recovery codes in a secure location.",
        description="Success message with instructions"
    )


class MFAVerificationRequest(BaseModel):
    """Request to verify MFA code"""
    code: str = Field(..., min_length=6, max_length=8, description="TOTP code or recovery code")

    @validator('code')
    def validate_code(cls, v):
        # Allow both 6-digit TOTP codes and 8-character recovery codes
        if len(v) == 6 and not v.isdigit():
            raise ValueError('6-character codes must contain only digits')
        elif len(v) == 8 and not v.isalnum():
            raise ValueError('8-character codes must be alphanumeric')
        elif len(v) not in [6, 8]:
            raise ValueError('Code must be 6 digits (TOTP) or 8 characters (recovery)')
        return v.upper()  # Normalize recovery codes to uppercase


class MFAVerificationResponse(BaseModel):
    """Response for MFA verification"""
    success: bool = Field(..., description="Whether verification was successful")
    verification_method: str = Field(..., description="Method used (totp or recovery_code)")
    message: str = Field(..., description="Verification result message")
    remaining_recovery_codes: Optional[int] = Field(None, description="Number of remaining recovery codes")


class MFAStatusResponse(BaseModel):
    """Response for MFA status check"""
    enabled: bool = Field(..., description="Whether MFA is enabled")
    enrolled: bool = Field(..., description="Whether MFA is properly enrolled")
    enrolled_at: Optional[datetime] = Field(None, description="When MFA was enrolled")
    last_verified_at: Optional[datetime] = Field(None, description="Last successful MFA verification")
    recovery_codes_available: int = Field(..., description="Number of unused recovery codes")
    recovery_codes_used: int = Field(..., description="Number of used recovery codes")


class MFADisableRequest(BaseModel):
    """Request to disable MFA"""
    confirmation: bool = Field(..., description="Confirmation that user wants to disable MFA")
    current_password: str = Field(..., min_length=8, description="User's current password for security")

    @validator('confirmation')
    def validate_confirmation(cls, v):
        if not v:
            raise ValueError('You must confirm that you want to disable MFA')
        return v


class MFADisableResponse(BaseModel):
    """Response for MFA disable"""
    success: bool = Field(..., description="Whether MFA was successfully disabled")
    message: str = Field(
        default="Multi-factor authentication has been disabled",
        description="Disable confirmation message"
    )


class MFARecoveryCodesRegenerateRequest(BaseModel):
    """Request to regenerate recovery codes"""
    current_password: str = Field(..., min_length=8, description="User's current password for security")


class MFARecoveryCodesRegenerateResponse(BaseModel):
    """Response for recovery codes regeneration"""
    recovery_codes: List[str] = Field(..., description="New recovery codes")
    message: str = Field(
        default="New recovery codes have been generated. Save them in a secure location.",
        description="Instructions for new recovery codes"
    )


class MFABackupCodeVerificationRequest(BaseModel):
    """Request for emergency MFA bypass with backup code"""
    backup_code: str = Field(..., min_length=8, max_length=8, description="8-character backup code")
    reason: str = Field(..., min_length=10, description="Reason for using backup code")

    @validator('backup_code')
    def validate_backup_code(cls, v):
        if not v.isalnum():
            raise ValueError('Backup code must be alphanumeric')
        return v.upper()


class MFAAuditLogEntry(BaseModel):
    """MFA audit log entry"""
    event_type: str = Field(..., description="Type of MFA event")
    event_result: str = Field(..., description="Result of the event")
    verification_method: Optional[str] = Field(None, description="Verification method used")
    ip_address: Optional[str] = Field(None, description="Client IP address")
    user_agent: Optional[str] = Field(None, description="Client user agent")
    created_at: datetime = Field(..., description="When the event occurred")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional event data")


class MFAAuditLogResponse(BaseModel):
    """Response for MFA audit log"""
    events: List[MFAAuditLogEntry] = Field(..., description="List of MFA events")
    total_count: int = Field(..., description="Total number of events")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Number of events per page")


class MFAAdminStatusResponse(BaseModel):
    """Admin response for user MFA status"""
    user_id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    mfa_enabled: bool = Field(..., description="Whether MFA is enabled")
    enrolled_at: Optional[datetime] = Field(None, description="When MFA was enrolled")
    last_verified_at: Optional[datetime] = Field(None, description="Last MFA verification")
    recovery_codes_available: int = Field(..., description="Available recovery codes")
    failed_attempts_today: int = Field(..., description="Failed MFA attempts today")


class MFAConfigurationRequest(BaseModel):
    """Request to update MFA configuration"""
    require_mfa_for_admin: bool = Field(
        default=True,
        description="Whether to require MFA for admin operations"
    )
    mfa_session_timeout_minutes: int = Field(
        default=15,
        ge=5,
        le=60,
        description="How long MFA verification lasts (5-60 minutes)"
    )
    max_recovery_codes: int = Field(
        default=10,
        ge=5,
        le=20,
        description="Maximum number of recovery codes (5-20)"
    )


class MFAConfigurationResponse(BaseModel):
    """Response for MFA configuration"""
    require_mfa_for_admin: bool = Field(..., description="Whether MFA is required for admin operations")
    mfa_session_timeout_minutes: int = Field(..., description="MFA session timeout in minutes")
    max_recovery_codes: int = Field(..., description="Maximum number of recovery codes")
    updated_at: datetime = Field(..., description="When configuration was last updated")
    updated_by: str = Field(..., description="Who updated the configuration")