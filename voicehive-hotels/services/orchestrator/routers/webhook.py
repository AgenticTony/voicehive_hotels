"""
Webhook router for VoiceHive Hotels
Handles LiveKit webhooks and call events
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse

from ..call_manager import CallEvent
from ..logging_adapter import get_safe_logger
from ..metrics import call_events_total

# Use safe logger
logger = get_safe_logger("orchestrator.webhook")

# Create router
router = APIRouter(tags=["webhooks"])


# LiveKit webhook endpoints
@router.post("/v1/livekit/webhook", include_in_schema=False)
async def handle_livekit_webhook(request: Request):
    """Handle LiveKit agent callbacks for call events"""
    try:
        # Parse the event payload
        event_data = await request.json()
        event_type = event_data.get("event_type")
        call_sid = event_data.get("call_sid")
        
        if not event_type or not call_sid:
            logger.error("invalid_livekit_webhook", event_data=event_data)
            raise HTTPException(status_code=400, detail="Missing event_type or call_sid")
        
        # Map LiveKit events to our internal event types
        event_mapping = {
            "agent_ready": "agent_ready",
            "call_started": "call_started",
            "transcription": "transcription",
            "intent_detected": "intent_detected",
            "response_generated": "response_generated",
            "tts_completed": "tts_completed",
            "call_ended": "call_ended",
            "error": "error"
        }
        
        internal_event_type = event_mapping.get(event_type)
        if not internal_event_type:
            logger.warning("unknown_livekit_event", event_type=event_type)
            return {"status": "ignored", "reason": "unknown event type"}
        
        # Create internal event with correct field names and types
        event = CallEvent(
            event=internal_event_type,
            room_name=event_data.get("room_name") or event_data.get("room") or call_sid,
            call_sid=call_sid,
            timestamp=datetime.now(timezone.utc).timestamp(),
            data=event_data.get("data", {})
        )
        
        # Handle the event if call manager is available
        call_manager = request.app.state.call_manager if hasattr(request.app.state, 'call_manager') else None
        if call_manager:
            result = await call_manager.handle_event(event)
            logger.info(
                "livekit_webhook_processed",
                event_type=event_type,
                call_sid=call_sid,
                result=result
            )
            return {"status": "processed", "event_type": event_type, "call_sid": call_sid}
        else:
            logger.info("livekit_webhook_accepted_no_manager", event_type=event_type, call_sid=call_sid)
            return JSONResponse({"status": "accepted", "event_type": event_type, "call_sid": call_sid}, status_code=202)
        
    except Exception as e:
        logger.error("livekit_webhook_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal error processing webhook")


@router.post("/v1/livekit/transcription", include_in_schema=False)
async def handle_transcription(
    call_sid: str,
    text: str,
    language: str,
    confidence: float,
    is_final: bool,
    request: Request
):
    """Handle transcription updates from LiveKit agent"""
    event = CallEvent(
        event="transcription",
        room_name=call_sid,
        call_sid=call_sid,
        timestamp=datetime.now(timezone.utc).timestamp(),
        data={
            "transcription": {
                "text": text,
                "language": language,
                "confidence": confidence,
                "is_final": is_final
            }
        }
    )

    call_manager = request.app.state.call_manager if hasattr(request.app.state, 'call_manager') else None
    if call_manager:
        result = await call_manager.handle_event(event)
        return {
            "status": "processed",
            "call_sid": call_sid,
            "intent_detected": (result or {}).get("intent")
        }
    else:
        logger.info("transcription_accepted_no_manager", call_sid=call_sid)
        return JSONResponse({"status": "accepted", "call_sid": call_sid}, status_code=202)


# Call event webhook endpoint (from LiveKit agent)
@router.post("/call/event", include_in_schema=False)
async def handle_call_event(
    request: Request,
    authorization: str = Header(None)
):
    """Handle call events from LiveKit agent with webhook authentication"""
    try:
        # Validate webhook authorization
        expected_key = os.getenv("LIVEKIT_WEBHOOK_KEY")
        if not authorization or not authorization.startswith("Bearer "):
            logger.warning("missing_webhook_auth")
            raise HTTPException(status_code=401, detail="Missing authorization")
        
        provided_key = authorization.replace("Bearer ", "")
        if provided_key != expected_key:
            logger.warning("invalid_webhook_auth")
            raise HTTPException(status_code=401, detail="Invalid webhook key")
        
        # Parse event
        event_data = await request.json()
        event_type = event_data.get("event")
        room_name = event_data.get("room_name")
        
        # Log with PII redaction
        logger.info(
            "call_event_received",
            event_type=event_type,
            room_name=room_name,
            # Don't log full payload to avoid PII
        )
        
        # Route to call manager if available
        if hasattr(request.app.state, "call_manager"):
            # Convert to internal event format
            internal_event = CallEvent(
                event=event_type,  # Use 'event' field, not 'event_type'
                room_name=room_name,  # Include room_name field  
                call_sid=room_name,
                timestamp=datetime.now(timezone.utc).timestamp(),  # Use float timestamp
                data=event_data
            )
            await request.app.state.call_manager.handle_event(internal_event)
        
        # Update metrics
        call_events_total.labels(event_type=event_type).inc()
        
        return {"status": "processed", "event": event_type}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("call_event_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal error")
