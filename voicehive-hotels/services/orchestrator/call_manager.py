"""
Call Manager for VoiceHive Hotels
Manages call state, coordinates between LiveKit, ASR, TTS, and LLM services
"""

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import uuid4
import json
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict
import redis.asyncio as redis
from tenacity import retry, stop_after_attempt, wait_random_exponential
from openai import AzureOpenAI

from connectors import ConnectorFactory
from services.orchestrator.utils import PIIRedactor
from services.orchestrator.tts_client import TTSClient, TTSSynthesisResponse
from services.orchestrator.enhanced_intent_detection_service import EnhancedIntentDetectionService
from services.orchestrator.conversation_flow_manager import ConversationFlowManager
from services.orchestrator.models import (
    EnhancedCallContext, ConversationTurn, MultiIntentDetectionResult,
    DetectedIntent, ConversationState, IntentType
)
from services.orchestrator.enhanced_hotel_functions import get_enhanced_hotel_functions
from services.orchestrator.logging_adapter import get_safe_logger

# Use safe logger adapter
logger = get_safe_logger(__name__)
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


# Note: CallContext is now replaced by EnhancedCallContext from models.py
# which provides multi-intent support, conversation flow, and slot filling


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
        tts_url: str = "http://tts-router:9000",
        llm_url: str = "http://llm-service:8000"
    ):
        self.redis = redis_client
        self.connector_factory = connector_factory
        self.asr_url = asr_url
        self.tts_url = tts_url
        self.llm_url = llm_url
        
        # Initialize TTS client
        self.tts_client = TTSClient(tts_url=self.tts_url)

        # Initialize Enhanced Intent Detection Service
        self.intent_service = EnhancedIntentDetectionService()

        # Initialize Conversation Flow Manager
        self.flow_manager = ConversationFlowManager()

        # Initialize Azure OpenAI client
        self.openai_client = AzureOpenAI(
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2025-02-01-preview"
        )
        self.deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4-turbo")

        # Track active calls (now using EnhancedCallContext)
        self.active_calls: Dict[str, EnhancedCallContext] = {}
        
    async def handle_event(self, event: CallEvent) -> Dict[str, Any]:
        """Handle events from LiveKit agent"""
        logger.info("handling_event", event=event.event, room=event.room_name)
        
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
            logger.warning("unknown_event_type", event=event.event)
            return {"status": "unknown_event"}
            
    async def _handle_agent_ready(self, event: CallEvent) -> Dict[str, Any]:
        """Handle agent ready event"""
        # Create enhanced call context
        context = EnhancedCallContext(
            room_name=event.room_name,
            hotel_id=event.hotel_id,
            call_sid=event.call_sid,
            call_state="connecting",  # Using string instead of CallState enum
            conversation_state=ConversationState.GREETING
        )

        # Store in Redis with TTL
        await self.redis.setex(
            f"call:{context.call_id}",
            3600,  # 1 hour TTL
            context.model_dump_json()
        )

        # Store in memory
        self.active_calls[context.call_id] = context

        logger.info("call_initialized", call_id=context.call_id)
        return {
            "status": "ready",
            "call_id": context.call_id
        }
        
    async def _handle_call_started(self, event: CallEvent) -> Dict[str, Any]:
        """Handle call started event"""
        # Find call by room name
        context = await self._get_call_by_room(event.room_name)
        if not context:
            logger.error("call_not_found", room=event.room_name)
            return {"status": "error", "message": "call_not_found"}

        # Update context
        context.call_state = "active"
        context.participant_sid = event.participant_sid
        context.participant_identity = event.participant_identity

        # Save updated context
        await self._save_context(context)

        # Load hotel configuration if available
        if context.hotel_id:
            await self._load_hotel_config(context)

        # Send initial greeting
        greeting = await self._generate_greeting(context)

        # Create greeting conversation turn
        greeting_turn = ConversationTurn(
            role="assistant",
            content=greeting["text"],
            language=greeting["language"],
            turn_type="text"
        )
        context.add_conversation_turn(greeting_turn)

        # Synthesize greeting
        tts_result = await self._synthesize_response(
            greeting["text"],
            greeting["language"]
        )

        # Save updated context with greeting turn
        await self._save_context(context)

        return {
            "status": "started",
            "call_id": context.call_id,
            "action": "speak",
            "text": greeting["text"],
            "language": greeting["language"],
            "audio_data": tts_result.audio_data if tts_result else None,
            "audio_format": "mp3",
            "metadata": {
                "tts_engine": tts_result.engine_used if tts_result else None,
                "tts_cached": tts_result.cached if tts_result else False,
                "tts_duration_ms": tts_result.duration_ms if tts_result else None
            }
        }
        
    async def _handle_call_ended(self, event: CallEvent) -> Dict[str, Any]:
        """Handle call ended event"""
        context = await self._get_call_by_room(event.room_name)
        if not context:
            return {"status": "error", "message": "call_not_found"}

        # Update state
        context.call_state = "ended"
        context.conversation_state = ConversationState.CLOSING
        context.ended_at = datetime.now(timezone.utc)

        # Save final state
        await self._save_context(context)

        # Calculate metrics
        duration_seconds = (context.ended_at - context.started_at).total_seconds()

        # Log call summary with PII redacted
        logger.info(
            "call_ended",
            call_id=context.call_id,
            duration_seconds=duration_seconds,
            turns=len(context.conversation_turns),
            language=context.detected_language,
            hotel_id=context.hotel_id,
            conversation_state=context.conversation_state.value,
            total_intents_detected=len(context.intent_history)
        )

        # Clean up
        self.active_calls.pop(context.call_id, None)

        return {
            "status": "ended",
            "call_id": context.call_id,
            "duration_seconds": duration_seconds
        }
        
    async def _handle_transcription(self, event: CallEvent) -> Dict[str, Any]:
        """Handle transcription results from ASR with enhanced multi-intent processing"""
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

        # Perform multi-intent detection
        detection_result = await self.intent_service.detect_multiple_intents(
            utterance=text,
            language=context.detected_language,
            conversation_context=context.conversation_context
        )

        # Create user conversation turn with detection result
        user_turn = ConversationTurn(
            role="user",
            content=text,
            language=transcription.get("language", context.detected_language),
            turn_type="text",
            detection_result=detection_result
        )

        # Add turn to context (this also updates intent history)
        context.add_conversation_turn(user_turn)

        # Update intent detection latency
        context.intent_detection_latency_ms = detection_result.processing_time_ms

        # Determine conversation flow based on multi-intent results
        flow_decision = await self.flow_manager.determine_next_conversation_state(
            current_state=context.conversation_state,
            detected_intents=detection_result.detected_intents,
            conversation_context=context,
            recent_turns=context.get_recent_turns(3)
        )

        # Update conversation state
        context.conversation_state = flow_decision.next_state

        # Process user input with enhanced AI
        response = await self._process_enhanced_user_input(context, text, detection_result, flow_decision)

        # Create assistant conversation turn
        assistant_turn = ConversationTurn(
            role="assistant",
            content=response["text"],
            language=response["language"],
            turn_type="text",
            response_metadata=response.get("metadata", {})
        )

        # Add assistant turn
        context.add_conversation_turn(assistant_turn)

        # Synthesize speech
        tts_result = await self._synthesize_response(
            response["text"],
            response["language"]
        )

        # Update TTS latency metric
        if tts_result:
            context.tts_latency_ms = tts_result.processing_time_ms

        # Save updated context
        await self._save_context(context)

        return {
            "status": "response_ready",
            "call_id": context.call_id,
            "action": "speak",
            "text": response["text"],
            "language": response["language"],
            "audio_data": tts_result.audio_data if tts_result else None,
            "audio_format": "mp3",
            "metadata": {
                **response.get("metadata", {}),
                "tts_engine": tts_result.engine_used if tts_result else None,
                "tts_cached": tts_result.cached if tts_result else False,
                "tts_duration_ms": tts_result.duration_ms if tts_result else None,
                "detected_intents": [intent.intent.value for intent in detection_result.detected_intents],
                "primary_intent": detection_result.primary_intent.intent.value if detection_result.primary_intent else None,
                "conversation_state": context.conversation_state.value,
                "flow_confidence": flow_decision.confidence
            }
        }
        
    async def _handle_dtmf(self, event: CallEvent) -> Dict[str, Any]:
        """Handle DTMF tones"""
        context = await self._get_call_by_room(event.room_name)
        if not context:
            return {"status": "error", "message": "call_not_found"}
        
        digit = event.data.get("digit")
        logger.info("dtmf_received", digit=digit, call_id=context.call_id)
        
        # Implement DTMF menu logic based on current context
        response_text = ""
        language = context.detected_language
        
        # Main menu navigation with enhanced intent support
        intent_type = None
        if digit == "1":
            response_text = self._get_localized_text("reservations_menu", language)
            intent_type = IntentType.BOOKING_INQUIRY
        elif digit == "2":
            response_text = self._get_localized_text("hotel_info_menu", language)
            intent_type = IntentType.REQUEST_INFO
        elif digit == "3":
            response_text = self._get_localized_text("concierge_menu", language)
            intent_type = IntentType.CONCIERGE_SERVICES
        elif digit == "4":
            response_text = self._get_localized_text("spa_restaurant_menu", language)
            intent_type = IntentType.SPA_BOOKING
        elif digit == "0":
            response_text = self._get_localized_text("operator_transfer", language)
            intent_type = IntentType.TRANSFER_TO_OPERATOR
        elif digit == "*":
            response_text = self._get_localized_text("main_menu", language)
            intent_type = IntentType.GREETING
        elif digit == "#":
            response_text = self._get_localized_text("repeat_options", language)
        else:
            response_text = self._get_localized_text("invalid_option", language)

        # Create DTMF user turn
        dtmf_user_turn = ConversationTurn(
            role="user",
            content=f"DTMF: {digit}",
            turn_type="dtmf"
        )

        # Add detected intent if applicable
        if intent_type:
            detected_intent = DetectedIntent(
                intent=intent_type,
                confidence=1.0,  # DTMF selections are definitive
                parameters={"dtmf_digit": digit},
                source_detector="dtmf_handler"
            )
            context.current_intents = [detected_intent]

        context.add_conversation_turn(dtmf_user_turn)

        # Create DTMF response turn
        dtmf_response_turn = ConversationTurn(
            role="assistant",
            content=response_text,
            turn_type="dtmf_response"
        )
        context.add_conversation_turn(dtmf_response_turn)
        
        # Save updated context
        await self._save_context(context)
        
        # Synthesize response
        tts_result = await self._synthesize_response(response_text, language)
        
        primary_intent = context.get_primary_intent()
        return {
            "status": "dtmf_processed",
            "digit": digit,
            "intent": primary_intent.intent.value if primary_intent else None,
            "action": "speak",
            "text": response_text,
            "language": language,
            "audio_data": tts_result.audio_data if tts_result else None,
            "audio_format": "mp3",
            "metadata": {
                "tts_engine": tts_result.engine_used if tts_result else None,
                "tts_cached": tts_result.cached if tts_result else False,
                "tts_duration_ms": tts_result.duration_ms if tts_result else None,
                "conversation_state": context.conversation_state.value
            }
        }
    
    def _get_localized_text(self, key: str, language: str) -> str:
        """Get localized text for DTMF responses"""
        texts = {
            "en": {
                "reservations_menu": "You've selected reservations. Please tell me your confirmation number or say 'new reservation' to make a booking.",
                "hotel_info_menu": "You've selected hotel information. I can help with amenities, hours, policies, or directions. What would you like to know?",
                "concierge_menu": "You've selected concierge services. I can help with restaurant recommendations, local attractions, or transportation. How may I assist?",
                "spa_restaurant_menu": "You've selected spa and dining. I can help with reservations, hours, or menu information. What interests you?",
                "operator_transfer": "Please hold while I transfer you to our front desk operator.",
                "main_menu": "Main menu: Press 1 for reservations, 2 for hotel information, 3 for concierge, 4 for spa and dining, or 0 for operator.",
                "repeat_options": "Let me repeat the options: Press 1 for reservations, 2 for hotel information, 3 for concierge, 4 for spa and dining, or 0 for operator.",
                "invalid_option": "I didn't recognize that option. Press * to hear the main menu or 0 to speak with an operator."
            },
            "de": {
                "reservations_menu": "Sie haben Reservierungen gewählt. Bitte nennen Sie mir Ihre Bestätigungsnummer oder sagen Sie 'neue Reservierung'.",
                "hotel_info_menu": "Sie haben Hotelinformationen gewählt. Ich kann bei Ausstattung, Öffnungszeiten, Richtlinien oder Wegbeschreibungen helfen.",
                "concierge_menu": "Sie haben Concierge-Services gewählt. Ich kann bei Restaurantempfehlungen, lokalen Attraktionen oder Transport helfen.",
                "spa_restaurant_menu": "Sie haben Spa und Restaurant gewählt. Ich kann bei Reservierungen, Öffnungszeiten oder Menüinformationen helfen.",
                "operator_transfer": "Bitte warten Sie, während ich Sie zu unserem Empfang verbinde.",
                "main_menu": "Hauptmenü: Drücken Sie 1 für Reservierungen, 2 für Hotelinformationen, 3 für Concierge, 4 für Spa und Restaurant, oder 0 für den Empfang.",
                "repeat_options": "Ich wiederhole die Optionen: Drücken Sie 1 für Reservierungen, 2 für Hotelinformationen, 3 für Concierge, 4 für Spa und Restaurant, oder 0 für den Empfang.",
                "invalid_option": "Diese Option habe ich nicht erkannt. Drücken Sie * für das Hauptmenü oder 0 um mit einem Mitarbeiter zu sprechen."
            },
            "es": {
                "reservations_menu": "Ha seleccionado reservas. Por favor, dígame su número de confirmación o diga 'nueva reserva'.",
                "hotel_info_menu": "Ha seleccionado información del hotel. Puedo ayudar con servicios, horarios, políticas o direcciones.",
                "concierge_menu": "Ha seleccionado servicios de conserjería. Puedo ayudar con recomendaciones de restaurantes, atracciones locales o transporte.",
                "spa_restaurant_menu": "Ha seleccionado spa y restaurante. Puedo ayudar con reservas, horarios o información del menú.",
                "operator_transfer": "Por favor espere mientras le transfiero con nuestro operador de recepción.",
                "main_menu": "Menú principal: Presione 1 para reservas, 2 para información del hotel, 3 para conserjería, 4 para spa y restaurante, o 0 para operador.",
                "repeat_options": "Repito las opciones: Presione 1 para reservas, 2 para información del hotel, 3 para conserjería, 4 para spa y restaurante, o 0 para operador.",
                "invalid_option": "No reconocí esa opción. Presione * para el menú principal o 0 para hablar con un operador."
            },
            "fr": {
                "reservations_menu": "Vous avez sélectionné les réservations. Veuillez me donner votre numéro de confirmation ou dire 'nouvelle réservation'.",
                "hotel_info_menu": "Vous avez sélectionné les informations de l'hôtel. Je peux aider avec les équipements, horaires, politiques ou directions.",
                "concierge_menu": "Vous avez sélectionné les services de conciergerie. Je peux aider avec les recommandations de restaurants, attractions locales ou transport.",
                "spa_restaurant_menu": "Vous avez sélectionné spa et restaurant. Je peux aider avec les réservations, horaires ou informations du menu.",
                "operator_transfer": "Veuillez patienter pendant que je vous transfère vers notre opérateur de réception.",
                "main_menu": "Menu principal: Appuyez sur 1 pour les réservations, 2 pour les informations de l'hôtel, 3 pour la conciergerie, 4 pour le spa et restaurant, ou 0 pour l'opérateur.",
                "repeat_options": "Je répète les options: Appuyez sur 1 pour les réservations, 2 pour les informations de l'hôtel, 3 pour la conciergerie, 4 pour le spa et restaurant, ou 0 pour l'opérateur.",
                "invalid_option": "Je n'ai pas reconnu cette option. Appuyez sur * pour le menu principal ou 0 pour parler à un opérateur."
            }
        }
        
        # Get language-specific texts, fallback to English
        lang_texts = texts.get(language, texts.get("en", texts["en"]))
        return lang_texts.get(key, texts["en"].get(key, ""))
        
    async def _get_call_by_room(self, room_name: str) -> Optional[EnhancedCallContext]:
        """Retrieve enhanced call context by room name"""
        # Check memory cache first
        for call_id, context in self.active_calls.items():
            if context.room_name == room_name:
                return context

        # Check Redis if not in memory
        # This would require maintaining a room->call_id mapping
        return None

    async def _save_context(self, context: EnhancedCallContext):
        """Save enhanced call context to Redis"""
        await self.redis.setex(
            f"call:{context.call_id}",
            3600,
            context.model_dump_json()
        )
        
    async def _load_hotel_config(self, context: EnhancedCallContext):
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
            logger.error("failed_to_load_hotel_config", error=str(e))
            
    async def _generate_greeting(self, context: EnhancedCallContext) -> Dict[str, str]:
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

    async def _process_enhanced_user_input(
        self,
        context: EnhancedCallContext,
        text: str,
        detection_result: MultiIntentDetectionResult,
        flow_decision
    ) -> Dict[str, Any]:
        """Process user input with enhanced multi-intent AI and conversation flow"""
        try:
            # Build conversation messages for LLM
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"You are a helpful hotel receptionist AI at {context.pms_data.get('hotel_name', 'our hotel')}. "
                        f"Be concise, friendly, and professional. The caller speaks {context.detected_language}. "
                        f"Current conversation state: {context.conversation_state.value}. "
                        f"Detected intents: {[intent.intent.value for intent in detection_result.detected_intents]}. "
                        "Use the available functions to help guests with their requests. "
                        "Keep responses brief and natural for phone conversations. "
                        f"Follow the conversation flow guidance: {flow_decision.reasoning}"
                    )
                }
            ]

            # Add recent conversation history (using new conversation turns)
            for turn in context.get_recent_turns(3):
                if turn.role in ["user", "assistant"]:
                    messages.append({
                        "role": turn.role,
                        "content": turn.content
                    })

            # Add current user input
            messages.append({"role": "user", "content": text})

            # Get enhanced hotel functions
            tools = get_enhanced_hotel_functions()

            # Make OpenAI API call with enhanced function support
            response = await self._call_openai_with_enhanced_functions(
                messages, tools, context, detection_result
            )

            return {
                "text": response,
                "language": context.detected_language,
                "detected_intents": [intent.intent.value for intent in detection_result.detected_intents],
                "conversation_state": context.conversation_state.value,
                "metadata": {
                    "llm_latency_ms": context.llm_latency_ms,
                    "flow_confidence": flow_decision.confidence,
                    "requires_clarification": detection_result.requires_clarification
                }
            }

        except Exception as e:
            logger.error(f"Enhanced LLM processing failed: {e}")
            # Fallback to enhanced template response
            return await self._get_enhanced_fallback_response(context, text, detection_result)

    async def _call_openai_with_enhanced_functions(
        self,
        messages: List[Dict],
        tools: List[Dict],
        context: EnhancedCallContext,
        detection_result: MultiIntentDetectionResult
    ) -> str:
        """Call OpenAI with enhanced function calling support"""
        start_time = datetime.now(timezone.utc)

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
                    max_tokens=200
                )
            )

            response_message = response.choices[0].message

            # Handle function calls
            if response_message.tool_calls:
                messages.append(response_message)

                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    # Execute enhanced hotel function
                    function_response = await self._execute_enhanced_hotel_function(
                        function_name, function_args, context
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

            # Record latency in context
            context.llm_latency_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            return result

        except Exception as e:
            logger.error("enhanced_openai_api_call_failed", error=str(e))
            raise
    
    async def _execute_enhanced_hotel_function(
        self,
        function_name: str,
        args: Dict[str, Any],
        context: EnhancedCallContext
    ) -> Dict[str, Any]:
        """Execute enhanced hotel-related function calls with PMS integration"""
        logger.info("executing_enhanced_function", function_name=function_name, args=args)

        # Get PMS connector if hotel_id is available
        connector = None
        if context.hotel_id:
            try:
                connector = self.connector_factory.get_connector(context.hotel_id)
            except Exception as e:
                logger.error("failed_to_get_pms_connector", error=str(e))

        # Handle enhanced hotel functions
        if function_name == "create_reservation":
            return await self._handle_create_reservation(args, connector)
        elif function_name == "modify_reservation":
            return await self._handle_modify_reservation(args, connector)
        elif function_name == "cancel_reservation":
            return await self._handle_cancel_reservation(args, connector)
        elif function_name == "check_availability":
            return await self._handle_check_availability(args, connector)
        elif function_name == "get_reservation":
            return await self._handle_get_reservation(args, connector)
        elif function_name == "get_upselling_options":
            return await self._handle_get_upselling_options(args, connector, context)
        elif function_name == "process_upsell":
            return await self._handle_process_upsell(args, connector, context)
        elif function_name == "book_restaurant":
            return await self._handle_book_restaurant(args, connector)
        elif function_name == "book_spa_service":
            return await self._handle_book_spa_service(args, connector)
        elif function_name == "request_room_service":
            return await self._handle_request_room_service(args, connector)
        elif function_name == "handle_complaint":
            return await self._handle_complaint(args, connector, context)
        elif function_name == "get_concierge_recommendations":
            return await self._handle_concierge_recommendations(args, context)
        elif function_name == "transfer_to_human":
            return await self._handle_transfer_to_human(args, context)
        elif function_name == "get_hotel_info":
            return await self._handle_get_hotel_info(args, connector)
        elif function_name == "process_payment":
            return await self._handle_process_payment(args, connector)
        else:
            return {"error": f"Unknown function: {function_name}", "success": False}
    
# Note: Old _call_openai_with_functions method replaced by _call_openai_with_enhanced_functions
    
# Note: Old _execute_hotel_function method replaced by _execute_enhanced_hotel_function

    # Enhanced function handlers (placeholder implementations for now)
    async def _handle_create_reservation(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle reservation creation - would integrate with PMS connector"""
        return {"success": True, "confirmation_number": "VH" + str(int(datetime.now().timestamp()))}

    async def _handle_modify_reservation(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle reservation modification"""
        return {"success": True, "message": "Reservation modified successfully"}

    async def _handle_cancel_reservation(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle reservation cancellation"""
        return {"success": True, "message": "Reservation cancelled successfully"}

    async def _handle_check_availability(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle availability check with enhanced options"""
        return {
            "available": True,
            "room_types": [
                {"type": "Standard", "rate": 150, "available": 5},
                {"type": "Deluxe", "rate": 250, "available": 2},
                {"type": "Suite", "rate": 400, "available": 1}
            ],
            "check_in": args.get("check_in"),
            "check_out": args.get("check_out")
        }

    async def _handle_get_reservation(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle reservation retrieval"""
        if args.get("confirmation_number") == "12345":
            return {
                "found": True,
                "guest_name": "Smith",
                "check_in": "2024-12-25",
                "check_out": "2024-12-28",
                "room_type": "Deluxe",
                "status": "confirmed"
            }
        return {"found": False}

    async def _handle_get_upselling_options(self, args: Dict[str, Any], connector, context: EnhancedCallContext) -> Dict[str, Any]:
        """Handle upselling options retrieval"""
        return {
            "options": [
                {"type": "room_upgrade", "description": "Upgrade to Suite", "price": 150},
                {"type": "spa_package", "description": "Spa relaxation package", "price": 200},
                {"type": "dining_package", "description": "Gourmet dining experience", "price": 100}
            ]
        }

    async def _handle_process_upsell(self, args: Dict[str, Any], connector, context: EnhancedCallContext) -> Dict[str, Any]:
        """Handle upselling processing"""
        return {"success": True, "message": "Upsell added to reservation"}

    async def _handle_book_restaurant(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle restaurant booking"""
        return {"success": True, "confirmation": "REST" + str(int(datetime.now().timestamp()))}

    async def _handle_book_spa_service(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle spa service booking"""
        return {"success": True, "confirmation": "SPA" + str(int(datetime.now().timestamp()))}

    async def _handle_request_room_service(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle room service request"""
        return {"success": True, "estimated_delivery": "30-45 minutes"}

    async def _handle_complaint(self, args: Dict[str, Any], connector, context: EnhancedCallContext) -> Dict[str, Any]:
        """Handle guest complaint"""
        context.escalation_reasons.append(f"Complaint: {args.get('issue_type', 'general')}")
        return {"success": True, "ticket_number": "COMP" + str(int(datetime.now().timestamp()))}

    async def _handle_concierge_recommendations(self, args: Dict[str, Any], context: EnhancedCallContext) -> Dict[str, Any]:
        """Handle concierge recommendations"""
        return {"recommendations": ["Local museum", "Popular restaurant", "Tourist attraction"]}

    async def _handle_transfer_to_human(self, args: Dict[str, Any], context: EnhancedCallContext) -> Dict[str, Any]:
        """Handle transfer to human operator"""
        context.escalation_reasons.append(f"Transfer requested: {args.get('reason', 'general assistance')}")
        return {"success": True, "message": "Transferring to human operator"}

    async def _handle_get_hotel_info(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle hotel information requests"""
        info_type = args.get("info_type")
        info_map = {
            "amenities": "We offer a spa, fitness center, outdoor pool, business center, and concierge services.",
            "hours": "Check-in is at 3 PM and check-out is at 11 AM. Gym is 24/7, spa 9 AM-9 PM.",
            "policies": "We have a 24-hour cancellation policy. Pets are welcome with a small fee.",
            "restaurant": "Our restaurant serves breakfast from 6-10 AM and dinner from 6-10 PM.",
            "spa": "The spa is open daily from 9 AM to 9 PM. Reservations recommended."
        }
        return {"info": info_map.get(info_type, "Information not available.")}

    async def _handle_process_payment(self, args: Dict[str, Any], connector) -> Dict[str, Any]:
        """Handle payment processing with Apaleo Pay integration"""
        return {"success": True, "transaction_id": "TXN" + str(int(datetime.now().timestamp()))}
    
    async def _get_enhanced_fallback_response(
        self,
        context: EnhancedCallContext,
        text: str,
        detection_result: MultiIntentDetectionResult
    ) -> Dict[str, Any]:
        """Get enhanced fallback response when LLM fails"""
        primary_intent = detection_result.primary_intent

        templates = {
            "greeting": "Hello! How may I assist you today?",
            "question": "I'd be happy to help. Could you please provide more details?",
            "request_info": "Let me check that information for you.",
            "booking_inquiry": "I can help you with your reservation. What dates are you interested in?",
            "existing_reservation_modify": "I can help you modify your reservation. Please provide your confirmation number.",
            "upselling_opportunity": "I'd be happy to tell you about our additional services and upgrades.",
            "concierge_services": "Our concierge is here to help. What can I assist you with?",
            "restaurant_booking": "I can help you make a restaurant reservation. What time would you prefer?",
            "spa_booking": "I can help you book spa services. What treatment interests you?",
            "complaint_feedback": "I'm sorry to hear about your concern. Let me help resolve this for you.",
            "transfer_to_operator": "I'll connect you with one of our team members right away.",
            "end_call": "Thank you for calling. Have a wonderful day!",
            "unknown": "I'd be happy to help. Could you please rephrase your question?"
        }

        intent_key = primary_intent.intent.value if primary_intent else "unknown"
        response_text = templates.get(intent_key, templates["unknown"])

        return {
            "text": response_text,
            "language": context.detected_language,
            "detected_intents": [intent.intent.value for intent in detection_result.detected_intents],
            "conversation_state": context.conversation_state.value,
            "metadata": {
                "fallback_used": True,
                "primary_intent": intent_key
            }
        }
        
    async def _synthesize_response(
        self,
        text: str,
        language: str
    ) -> Optional[TTSSynthesisResponse]:
        """Synthesize text to speech using TTS Router"""
        try:
            # Map language codes if needed
            tts_language = self._map_language_code(language)
            
            # Synthesize with TTS client
            result = await self.tts_client.synthesize(
                text=text,
                language=tts_language,
                speed=1.0,
                format="mp3",
                sample_rate=24000
            )
            
            logger.info(
                "tts_synthesis_successful",
                language=language,
                engine_used=result.engine_used,
                duration_ms=result.duration_ms,
                cached=result.cached
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "tts_synthesis_failed",
                error=str(e),
                language=language
            )
            # Return None to indicate synthesis failed
            # The orchestrator can still send text-only response
            return None
            
    def _map_language_code(self, language: str) -> str:
        """Map language codes to TTS-compatible format"""
        # Common mappings
        language_map = {
            "en": "en-US",
            "de": "de-DE",
            "es": "es-ES",
            "fr": "fr-FR",
            "it": "it-IT",
            "nl": "nl-NL",
            "pt": "pt-PT",
            "pl": "pl-PL",
            "ru": "ru-RU",
            "ja": "ja-JP",
            "zh": "zh-CN"
        }
        
        # If already in full format (e.g., en-US), return as is
        if len(language) > 2 and '-' in language:
            return language
            
        # Otherwise map to default regional variant
        return language_map.get(language, "en-US")

# Note: Old _detect_intent method replaced by enhanced multi-intent detection in _handle_transcription
