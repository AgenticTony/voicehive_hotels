"""
Pydantic models for VoiceHive Hotels Orchestrator Service
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class CallStartRequest(BaseModel):
    """Request model for starting a new call"""
    caller_id: str = Field(..., description="Caller phone number")
    hotel_id: str = Field(..., description="Hotel identifier")
    language: Optional[str] = Field("auto", description="Language code or 'auto' for detection")
    sip_headers: Optional[Dict[str, str]] = Field(default_factory=dict)
    
    @field_validator('caller_id')
    @classmethod
    def validate_caller_id(cls, v):
        # Basic phone number validation
        if not v.startswith('+'):
            raise ValueError("Caller ID must be in E.164 format")
        return v


class CallStartResponse(BaseModel):
    """Response model for call start"""
    call_id: str
    session_token: str
    websocket_url: str
    region: str
    encryption_key_id: str


class HealthCheckResponse(BaseModel):
    """Response model for health check"""
    status: str
    region: str
    version: str
    gdpr_compliant: bool
    services: Dict[str, str]
