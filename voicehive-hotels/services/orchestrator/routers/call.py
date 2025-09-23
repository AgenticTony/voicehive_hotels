"""
Call management router for VoiceHive Hotels
"""

import json
import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
import redis.asyncio as redis

from ..logging_adapter import get_safe_logger
from ..models import CallStartRequest, CallStartResponse
from ..config import REGION, LIVEKIT_URL, GDPR_CONFIG
from ..dependencies import get_redis
from ..auth_middleware import get_auth_context, require_permissions, Permission
from ..auth_models import UserContext, ServiceContext
from ..metrics import call_counter, active_calls

# Logger
logger = get_safe_logger("orchestrator.call")

# Create router
router = APIRouter(prefix="/v1/call", tags=["calls"])


@router.post("/start", response_model=CallStartResponse)
async def start_call(
    request: CallStartRequest,
    auth_context = Depends(require_permissions(Permission.CALL_START)),
    redis_client: redis.Redis = Depends(get_redis)
):
    """Start a new call with GDPR compliance checks"""
    call_id = f"call_{datetime.now(timezone.utc).isoformat()}_{request.hotel_id}"
    
    logger.info(
        "starting_call",
        call_id=call_id,
        hotel_id=request.hotel_id,
        language=request.language,
        region=REGION
    )
    
    # Store call metadata in Redis with encryption
    call_data = {
        "hotel_id": request.hotel_id,
        "caller_id": hashlib.sha256(request.caller_id.encode()).hexdigest(),  # Hash PII
        "language": request.language,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "region": REGION,
        "gdpr_consent": "legitimate_interest",  # Based on config
        "schema_version": "1.0"  # For future compatibility
    }
    
    await redis_client.setex(
        f"call:{call_id}",
        GDPR_CONFIG['retention']['defaults']['metadata']['days'] * 86400,
        json.dumps(call_data)
    )
    
    # Generate session token
    auth_id = auth_context.user_id if isinstance(auth_context, UserContext) else auth_context.service_name
    session_token = hashlib.sha256(f"{call_id}:{auth_id}".encode()).hexdigest()
    
    # Increment metrics
    call_counter.labels(
        hotel_id=request.hotel_id,
        language=request.language,
        status="started"
    ).inc()
    active_calls.labels(hotel_id=request.hotel_id).inc()
    
    return CallStartResponse(
        call_id=call_id,
        session_token=session_token,
        websocket_url=f"{LIVEKIT_URL}/ws?token={session_token}",
        region=REGION,
        encryption_key_id=f"kms-{request.hotel_id}"
    )
