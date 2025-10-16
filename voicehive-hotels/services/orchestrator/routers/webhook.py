"""
Webhook router for VoiceHive Hotels
Handles LiveKit webhooks and call events
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..call_manager import CallEvent
from ..logging_adapter import get_safe_logger
from ..metrics import call_events_total
from ..security.webhook_security import WebhookSecurityManager, create_apaleo_webhook_source

# Use safe logger
logger = get_safe_logger("orchestrator.webhook")

# Create router
router = APIRouter(tags=["webhooks"])

# Apaleo webhook models
class ApaleoWebhookEvent(BaseModel):
    """Apaleo webhook event payload model"""
    id: str = Field(..., description="Event ID")
    topic: str = Field(..., description="Event topic (e.g., 'Reservation', 'system')")
    type: str = Field(..., description="Event type (e.g., 'created', 'changed', 'canceled', 'healthcheck')")
    accountId: str = Field(..., description="Apaleo account ID")
    propertyId: Optional[str] = Field(None, description="Property ID (for property-specific events)")
    propertyIds: Optional[list[str]] = Field(None, description="Property IDs (for account-level events)")
    timestamp: int = Field(..., description="Event timestamp (Unix milliseconds)")
    clientId: Optional[str] = Field(None, description="Client ID that triggered the event")
    subjectId: Optional[str] = Field(None, description="Subject ID")
    data: Optional[Dict[str, Any]] = Field(None, description="Event-specific data")


class ReservationEventData(BaseModel):
    """Reservation event data model"""
    entityId: str = Field(..., description="Reservation entity ID")


# Initialize webhook security manager
webhook_security = None

def get_webhook_security() -> WebhookSecurityManager:
    """Get or create webhook security manager"""
    global webhook_security
    if webhook_security is None:
        from ..security.webhook_security import WebhookConfig, WebhookSecurityManager

        config = WebhookConfig()
        webhook_security = WebhookSecurityManager(config)

        # Register Apaleo webhook source
        apaleo_secret = os.getenv("APALEO_WEBHOOK_SECRET")
        if apaleo_secret:
            apaleo_source = create_apaleo_webhook_source("apaleo", apaleo_secret)
            webhook_security.register_webhook_source(apaleo_source)
            logger.info("apaleo_webhook_source_registered")
        else:
            logger.warning("apaleo_webhook_secret_not_configured")

    return webhook_security


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


# Apaleo webhook endpoints
@router.post("/v1/apaleo/webhook", include_in_schema=False)
async def handle_apaleo_webhook(
    request: Request,
    security_manager: WebhookSecurityManager = Depends(get_webhook_security)
):
    """Handle Apaleo webhook events with security verification"""
    try:
        # Read request payload
        payload = await request.body()

        # Verify webhook security (signature, IP whitelist, etc.)
        security_manager.verify_webhook(request, "apaleo", payload)

        # Parse event data
        event_data = await request.json()
        event = ApaleoWebhookEvent(**event_data)

        logger.info(
            "apaleo_webhook_received",
            event_id=event.id,
            topic=event.topic,
            event_type=event.type,
            account_id=event.accountId,
            property_id=event.propertyId,
            timestamp=event.timestamp
        )

        # Handle different event types
        if event.topic == "system" and event.type == "healthcheck":
            return await handle_apaleo_healthcheck(event)
        elif event.topic == "Reservation":
            return await handle_apaleo_reservation_event(event, request)
        else:
            logger.info(
                "apaleo_webhook_ignored",
                topic=event.topic,
                event_type=event.type,
                reason="Event type not handled"
            )
            return {"status": "ignored", "reason": f"Event type {event.topic}/{event.type} not handled"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("apaleo_webhook_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal error processing Apaleo webhook")


async def handle_apaleo_healthcheck(event: ApaleoWebhookEvent) -> Dict[str, Any]:
    """Handle Apaleo health check events"""
    logger.info(
        "apaleo_healthcheck_received",
        event_id=event.id,
        account_id=event.accountId,
        property_ids=event.propertyIds
    )

    return {
        "status": "healthy",
        "event_id": event.id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "voicehive-hotels"
    }


async def handle_apaleo_reservation_event(event: ApaleoWebhookEvent, request: Request) -> Dict[str, Any]:
    """Handle Apaleo reservation events (created, changed, canceled)"""
    try:
        # Extract reservation ID from event data
        reservation_id = None
        if event.data and "entityId" in event.data:
            reservation_id = event.data["entityId"]

        logger.info(
            "apaleo_reservation_event",
            event_type=event.type,
            reservation_id=reservation_id,
            property_id=event.propertyId,
            account_id=event.accountId
        )

        # Process different reservation event types
        if event.type == "created":
            await process_reservation_created(event, reservation_id, request)
        elif event.type == "changed":
            await process_reservation_modified(event, reservation_id, request)
        elif event.type == "canceled":
            await process_reservation_canceled(event, reservation_id, request)
        else:
            logger.warning(
                "unknown_reservation_event_type",
                event_type=event.type,
                reservation_id=reservation_id
            )

        return {
            "status": "processed",
            "event_type": event.type,
            "reservation_id": reservation_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(
            "apaleo_reservation_event_error",
            event_type=event.type,
            error=str(e)
        )
        raise


async def process_reservation_created(event: ApaleoWebhookEvent, reservation_id: str, request: Request):
    """Process new reservation creation"""
    logger.info(
        "processing_reservation_created",
        reservation_id=reservation_id,
        property_id=event.propertyId
    )

    # TODO: Integrate with hotel management system
    # - Fetch full reservation details from Apaleo
    # - Update local reservation cache
    # - Trigger welcome message workflows
    # - Schedule check-in reminders

    # For now, just log the event
    logger.info(
        "reservation_created_logged",
        reservation_id=reservation_id,
        property_id=event.propertyId,
        account_id=event.accountId
    )


async def process_reservation_modified(event: ApaleoWebhookEvent, reservation_id: str, request: Request):
    """Process reservation modifications"""
    logger.info(
        "processing_reservation_modified",
        reservation_id=reservation_id,
        property_id=event.propertyId
    )

    # TODO: Integrate with hotel management system
    # - Fetch updated reservation details from Apaleo
    # - Update local reservation cache
    # - Notify guest of changes
    # - Update room assignments if needed

    # For now, just log the event
    logger.info(
        "reservation_modified_logged",
        reservation_id=reservation_id,
        property_id=event.propertyId,
        account_id=event.accountId
    )


async def process_reservation_canceled(event: ApaleoWebhookEvent, reservation_id: str, request: Request):
    """Process reservation cancellations"""
    logger.info(
        "processing_reservation_canceled",
        reservation_id=reservation_id,
        property_id=event.propertyId
    )

    # TODO: Integrate with hotel management system
    # - Update local reservation cache (mark as canceled)
    # - Cancel automated workflows (reminders, welcome messages)
    # - Process refunds if applicable
    # - Update room availability

    # For now, just log the event
    logger.info(
        "reservation_canceled_logged",
        reservation_id=reservation_id,
        property_id=event.propertyId,
        account_id=event.accountId
    )
