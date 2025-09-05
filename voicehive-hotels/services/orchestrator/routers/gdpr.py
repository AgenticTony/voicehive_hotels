"""
GDPR router for VoiceHive Hotels
Handles GDPR consent and data management endpoints
"""

import json
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
import redis.asyncio as redis

from ..logging_adapter import get_safe_logger
from ..dependencies import verify_api_key, get_redis

# Use safe logger
logger = get_safe_logger("orchestrator.gdpr")

# Create router
router = APIRouter(prefix="/v1/gdpr", tags=["gdpr"])


@router.post("/consent")
async def record_consent(
    hotel_id: str,
    purpose: str,
    consent: bool,
    api_key: str = Depends(verify_api_key),
    redis_client: redis.Redis = Depends(get_redis)
):
    """Record GDPR consent for voice processing"""
    consent_record = {
        "hotel_id": hotel_id,
        "purpose": purpose,
        "consent": consent,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ip_address": "redacted",  # Would get from request in production
        "version": "1.0",
        "schema_version": "1.0"  # For future compatibility
    }
    
    await redis_client.setex(
        f"consent:{hotel_id}:{purpose}",
        365 * 86400,  # 1 year
        json.dumps(consent_record)
    )
    
    logger.info("consent_recorded", hotel_id=hotel_id, purpose=purpose, consent=consent)
    return {"status": "recorded", "consent_id": f"{hotel_id}:{purpose}"}


@router.post("/deletion-request")
async def request_deletion(
    hotel_id: str,
    caller_id: str,
    api_key: str = Depends(verify_api_key)
):
    """Handle GDPR deletion requests"""
    # In production, this would trigger an async workflow
    deletion_id = f"del_{datetime.now(timezone.utc).isoformat()}"
    
    logger.info(
        "deletion_requested",
        deletion_id=deletion_id,
        hotel_id=hotel_id,
        caller_id_hash=hashlib.sha256(caller_id.encode()).hexdigest()
    )
    
    return {
        "deletion_id": deletion_id,
        "status": "pending",
        "estimated_completion": "30 days"
    }
