"""
Call Manager for VoiceHive Hotels
Manages call state, coordinates between LiveKit, ASR, TTS, and LLM services
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import uuid4
import json
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict
import redis.asyncio as redis
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import AzureOpenAI

from connectors import ConnectorFactory
from config.security.pii_redactor import PIIRedactor

# Configure logging with PII redaction
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
pii_redactor = PIIRedactor()


class CallState(str, Enum):
    """Enumeration of call states"""
    INITIALIZING = "initializing"
    CONNECTING = "connecting"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    TRANSFERRING = "transferring"
    ENDING = "ending"
    ENDED = "ended"
    FAILED = "failed"


class CallEvent(BaseModel):
    """Model for call events from LiveKit agent"""
    event: str
    room_name: str
    timestamp: float
    call_sid: Optional[str] = None
    hotel_id: Optional[str] = None
    participant_sid: Optional[str] = None
    participant_identity: Optional[str] = None
    is_sip: Optional[bool] = None
    reason: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class CallContext(BaseModel):
    """Complete call context stored in Redis"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    call_id: str = Field(default_factory=lambda: str(uuid4()))
    room_name: str
    hotel_id: Optional[str] = None
    call_sid: Optional[str] = None
    participant_sid: Optional[str] = None
    participant_identity: Optional[str] = None
    
    # State
    state: CallState = CallState.INITIALIZING
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    
    # Language and intent
    detected_language: str = "en"
    confidence: float = 0.0
    current_intent: Optional[str] = None
    
    # Conversation history
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Metrics
    asr_latency_ms: Optional[float] = None
    tts_latency_ms: Optional[float] = None
    llm_latency_ms: Optional[float] = None
    
    # PMS data cache
    pms_data: Optional[Dict[str, Any]] = None
    
    def to_redis(self) -> str:
        """Serialize to JSON for Redis storage"""
        return json.dumps(self.model_dump(mode='json'))
    
    @classmethod
    def from_redis(cls, data: str) -> "CallContext":
        """Deserialize from Redis JSON"""
        return cls(**json.loads(data))


class TranscriptionRequest(BaseModel):
    """Request model for ASR transcription"""
    call_id: str
    audio_chunk: str  # Base64 encoded
    language_hint: Optional[str] = None
    is_final: bool = False


class TranscriptionResult(BaseModel):
    """Result model from ASR"""
    transcript: str
    is_final: bool
    confidence: float
    language: str
    alternatives: Optional[List[Dict[str, Any]]] = None


class TTSRequest(BaseModel):
    """Request model for TTS synthesis"""
    call_id: str
    text: str
    language: str = "en"
    voice_id: Optional[str] = None
    emotion: Optional[str] = None  # For advanced TTS
    speed: float = 1.0


class TTSResult(BaseModel):
    """Result model from TTS"""
    audio_data: str  # Base64 encoded
    duration_ms: float
    voice_id: str


class CallManager:
    """Manages call lifecycle and coordination between services"""
    
    def __init__(
        self,
        redis_client: redis.Redis,
        connector_factory: ConnectorFactory,
        asr_url: str = "http://riva-proxy:8000",
        tts_url: str = "http://tts-router:8000",
        llm_url: str = "http://llm-service:8000"
    ):
        self.redis = redis_client
        self.connector_factory = connector_factory
        self.asr_url = asr_url
        self.tts_url = tts_url
        self.llm_url = llm_url
        
        # Initialize Azure OpenAI client
        self.openai_client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2025-02-01-preview"
        )
        self.deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4-turbo")
        
        # Track active calls
        self.active_calls: Dict[str, CallContext] = {}
        
    async def handle_event(self, event: CallEvent) -> Dict[str, Any]:
        """Handle events from LiveKit agent"""
        logger.info(f"Handling event: {event.event} for room: {event.room_name}")
        
        # Route based on event type
        if event.event == "agent_ready":
            return await self._handle_agent_ready(event)
        elif event.event == "call_started":
            return await self._handle_call_started(event)
        elif event.event == "call_ended":
            return await self._handle_call_ended(event)
        elif event.event == "transcription":
            return await self._handle_transcription(event)
        elif event.event == "dtmf":
            return await self._handle_dtmf(event)
        else:
            logger.warning(f"Unknown event type: {event.event}")
            return {"status": "unknown_event"}
            
    async def _handle_agent_ready(self, event: CallEvent) -> Dict[str, Any]:
        """Handle agent ready event"""
        # Create call context
        context = CallContext(
            room_name=event.room_name,
            hotel_id=event.hotel_id,
            call_sid=event.call_sid,
            state=CallState.CONNECTING
        )
        
        # Store in Redis with TTL
        await self.redis.setex(
            f"call:{context.call_id}",
            3600,  # 1 hour TTL
            context.to_redis()
        )
        
        # Store in memory
        self.active_calls[context.call_id] = context
        
        logger.info(f"Call initialized: {context.call_id}")
        return {
            "status": "ready",
            "call_id": context.call_id
        }
        
    async def _handle_call_started(self, event: CallEvent) -> Dict[str, Any]:
        """Handle call started event"""
        # Find call by room name
        context = await self._get_call_by_room(event.room_name)
        if not context:
            logger.error(f"Call not found for room: {event.room_name}")
            return {"status": "error", "message": "call_not_found"}
            
        # Update context
        context.state = CallState.ACTIVE
        context.participant_sid = event.participant_sid
        context.participant_identity = event.participant_identity
        
        # Save updated context
        await self._save_context(context)
        
        # Load hotel configuration if available
        if context.hotel_id:
            await self._load_hotel_config(context)
            
        # Send initial greeting
        greeting = await self._generate_greeting(context)
        
        return {
            "status": "started",
            "call_id": context.call_id,
            "action": "speak",
            "text": greeting["text"],
            "language": greeting["language"]
        }
        
    async def _handle_call_ended(self, event: CallEvent) -> Dict[str, Any]:
        """Handle call ended event"""
        context = await self._get_call_by_room(event.room_name)
        if not context:
            return {"status": "error", "message": "call_not_found"}
            
        # Update state
        context.state = CallState.ENDED
        context.ended_at = datetime.now(timezone.utc)
        
        # Save final state
        await self._save_context(context)
        
        # Calculate metrics
        duration_seconds = (context.ended_at - context.started_at).total_seconds()
        
        # Log call summary with PII redacted
        logger.info(
            f"Call ended: {context.call_id}",
            extra={
                "duration_seconds": duration_seconds,
                "turns": len(context.conversation_history),
                "language": context.detected_language,
                "hotel_id": context.hotel_id
            }
        )
        
        # Clean up
        self.active_calls.pop(context.call_id, None)
        
        return {
            "status": "ended",
            "call_id": context.call_id,
            "duration_seconds": duration_seconds
        }
        
    async def _handle_transcription(self, event: CallEvent) -> Dict[str, Any]:
        """Handle transcription results from ASR"""
        context = await self._get_call_by_room(event.room_name)
        if not context:
            return {"status": "error", "message": "call_not_found"}
            
        # Extract transcription data
        transcription = event.data.get("transcription", {})
        text = transcription.get("text", "")
        is_final = transcription.get("is_final", False)
        
        if not is_final:
            # Handle partial results if needed
            return {"status": "partial"}
            
        # Add to conversation history
        context.conversation_history.append({
            "role": "user",
            "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "language": transcription.get("language", context.detected_language)
        })
        
        # Process intent and generate response
        response = await self._process_user_input(context, text)
        
        # Add response to history
        context.conversation_history.append({
            "role": "assistant",
            "content": response["text"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "language": response["language"]
        })
        
        # Save updated context
        await self._save_context(context)
        
        return {
            "status": "response_ready",
            "call_id": context.call_id,
            "action": "speak",
            "text": response["text"],
            "language": response["language"],
            "metadata": response.get("metadata", {})
        }
        
    async def _handle_dtmf(self, event: CallEvent) -> Dict[str, Any]:
        """Handle DTMF tones"""
        # Implement DTMF handling for menu navigation
        digit = event.data.get("digit")
        logger.info(f"DTMF received: {digit}")
        
        # TODO: Implement DTMF menu logic
        return {"status": "dtmf_received", "digit": digit}
        
    async def _get_call_by_room(self, room_name: str) -> Optional[CallContext]:
        """Retrieve call context by room name"""
        # Check memory cache first
        for call_id, context in self.active_calls.items():
            if context.room_name == room_name:
                return context
                
        # Check Redis if not in memory
        # This would require maintaining a room->call_id mapping
        return None
        
    async def _save_context(self, context: CallContext):
        """Save call context to Redis"""
        await self.redis.setex(
            f"call:{context.call_id}",
            3600,
            context.to_redis()
        )
        
    async def _load_hotel_config(self, context: CallContext):
        """Load hotel-specific configuration and data"""
        try:
            # Get PMS connector for hotel
            connector = self.connector_factory.get_connector(context.hotel_id)
            
            # Cache some basic hotel info
            context.pms_data = {
                "hotel_name": "VoiceHive Demo Hotel",  # Would come from PMS
                "check_in_time": "3:00 PM",
                "check_out_time": "11:00 AM",
                "features": ["spa", "restaurant", "gym", "pool"]
            }
            
        except Exception as e:
            logger.error(f"Failed to load hotel config: {e}")
            
    async def _generate_greeting(self, context: CallContext) -> Dict[str, str]:
        """Generate appropriate greeting based on context"""
        # Determine language and greeting
        if context.detected_language == "de":
            text = "Guten Tag! Willkommen im VoiceHive Hotel. Wie kann ich Ihnen helfen?"
        elif context.detected_language == "es":
            text = "¡Buenos días! Bienvenido a VoiceHive Hotel. ¿En qué puedo ayudarle?"
        elif context.detected_language == "fr":
            text = "Bonjour! Bienvenue à l'hôtel VoiceHive. Comment puis-je vous aider?"
        else:
            text = "Good day! Welcome to VoiceHive Hotel. How may I assist you?"
            
        return {
            "text": text,
            "language": context.detected_language
        }
        
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def _process_user_input(self, context: CallContext, text: str) -> Dict[str, Any]:
        """Process user input with Azure OpenAI and function calling"""
        try:
            # Detect intent first
            intent = self._detect_intent(text)
            context.current_intent = intent
            
            # Build conversation messages for LLM
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"You are a helpful hotel receptionist AI at {context.pms_data.get('hotel_name', 'our hotel')}. "
                        f"Be concise, friendly, and professional. The caller speaks {context.detected_language}. "
                        "Only use the functions you have been provided with. "
                        "Keep responses brief and natural for phone conversations."
                    )
                }
            ]
            
            # Add recent conversation history
            for msg in context.conversation_history[-3:]:
                if msg.get("role") in ["user", "assistant"]:
                    messages.append({
                        "role": msg["role"],
                        "content": msg.get("content", "")
                    })
            
            # Add current user input
            messages.append({"role": "user", "content": text})
            
            # Define available functions
            tools = self._get_hotel_functions()
            
            # Make OpenAI API call
            response = await self._call_openai_with_functions(messages, tools)
            
            return {
                "text": response,
                "language": context.detected_language,
                "intent": intent,
                "metadata": {
                    "llm_latency_ms": context.llm_latency_ms
                }
            }
            
        except Exception as e:
            logger.error(f"LLM processing failed: {e}")
            # Fallback to template response
            return self._get_fallback_response(context, text)
    
    def _get_hotel_functions(self) -> List[Dict[str, Any]]:
        """Define available functions for hotel operations"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "check_availability",
                    "description": "Check room availability for given dates",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "check_in": {
                                "type": "string",
                                "description": "Check-in date (YYYY-MM-DD)"
                            },
                            "check_out": {
                                "type": "string",
                                "description": "Check-out date (YYYY-MM-DD)"
                            },
                            "room_type": {
                                "type": "string",
                                "description": "Type of room (optional)"
                            }
                        },
                        "required": ["check_in", "check_out"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_reservation",
                    "description": "Retrieve reservation details",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "confirmation_number": {
                                "type": "string",
                                "description": "Reservation confirmation number"
                            },
                            "guest_name": {
                                "type": "string",
                                "description": "Guest last name"
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_hotel_info",
                    "description": "Get general hotel information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "info_type": {
                                "type": "string",
                                "enum": ["amenities", "hours", "policies", "restaurant", "spa"],
                                "description": "Type of information requested"
                            }
                        },
                        "required": ["info_type"]
                    }
                }
            }
        ]
    
    async def _call_openai_with_functions(self, messages: List[Dict], tools: List[Dict]) -> str:
        """Call OpenAI with function calling support"""
        start_time = datetime.utcnow()
        
        try:
            # First API call
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.openai_client.chat.completions.create(
                    model=self.deployment_name,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=150
                )
            )
            
            response_message = response.choices[0].message
            
            # Handle function calls
            if response_message.tool_calls:
                messages.append(response_message)
                
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    # Execute function
                    function_response = await self._execute_hotel_function(
                        function_name, function_args
                    )
                    
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps(function_response),
                    })
                
                # Second API call for final response
                final_response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.openai_client.chat.completions.create(
                        model=self.deployment_name,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=150
                    )
                )
                
                result = final_response.choices[0].message.content
            else:
                result = response_message.content
            
            # Record latency
            self.llm_latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return result
            
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise
    
    async def _execute_hotel_function(self, function_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute hotel-related function calls"""
        logger.info(f"Executing function: {function_name}", args=args)
        
        if function_name == "check_availability":
            # Mock response - would call PMS connector
            return {
                "available": True,
                "room_types": [
                    {"type": "Standard", "rate": 150, "available": 5},
                    {"type": "Deluxe", "rate": 250, "available": 2}
                ],
                "check_in": args.get("check_in"),
                "check_out": args.get("check_out")
            }
            
        elif function_name == "get_reservation":
            # Mock response - would call PMS connector
            if args.get("confirmation_number") == "12345":
                return {
                    "found": True,
                    "guest_name": "Smith",
                    "check_in": "2024-12-25",
                    "check_out": "2024-12-28",
                    "room_type": "Deluxe",
                    "status": "confirmed"
                }
            else:
                return {"found": False}
                
        elif function_name == "get_hotel_info":
            info_type = args.get("info_type")
            info_map = {
                "amenities": "We offer a spa, fitness center, outdoor pool, and business center.",
                "hours": "Check-in is at 3 PM and check-out is at 11 AM.",
                "policies": "We have a 24-hour cancellation policy. Pets are welcome with a small fee.",
                "restaurant": "Our restaurant serves breakfast from 6-10 AM and dinner from 6-10 PM.",
                "spa": "The spa is open daily from 9 AM to 9 PM. Reservations recommended."
            }
            return {"info": info_map.get(info_type, "Information not available.")}
        
        return {"error": "Unknown function"}
    
    def _get_fallback_response(self, context: CallContext, text: str) -> Dict[str, Any]:
        """Get fallback response when LLM fails"""
        intent = self._detect_intent(text)
        
        templates = {
            "greeting": "Hello! How may I assist you today?",
            "question": "I'd be happy to help. Could you please provide more details?",
            "request_info": "Let me check that information for you.",
            "reservation": "I can help you with your reservation. What dates are you interested in?",
            "end_call": "Thank you for calling. Have a wonderful day!",
            "unknown": "I'd be happy to help. Could you please rephrase your question?"
        }
        
        return {
            "text": templates.get(intent, templates["unknown"]),
            "language": context.detected_language,
            "intent": intent
        }
