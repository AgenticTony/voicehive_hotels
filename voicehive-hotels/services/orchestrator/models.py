"""
Pydantic models for VoiceHive Hotels Orchestrator Service
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
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


# Sprint 3 Enhanced AI & Intent Detection Models

class IntentType(str, Enum):
    """Enhanced intent types for Sprint 3"""
    # Original intent types
    GREETING = "greeting"
    QUESTION = "question"
    REQUEST_INFO = "request_info"
    BOOKING_INQUIRY = "booking_inquiry"
    END_CALL = "end_call"
    UNKNOWN = "unknown"

    # Sprint 3 new hotel-specific intents
    EXISTING_RESERVATION_MODIFY = "existing_reservation_modify"
    EXISTING_RESERVATION_CANCEL = "existing_reservation_cancel"
    UPSELLING_OPPORTUNITY = "upselling_opportunity"
    CONCIERGE_SERVICES = "concierge_services"
    RESTAURANT_BOOKING = "restaurant_booking"
    SPA_BOOKING = "spa_booking"
    ROOM_SERVICE = "room_service"
    COMPLAINT_FEEDBACK = "complaint_feedback"
    TRANSFER_TO_OPERATOR = "transfer_to_operator"
    FALLBACK_TO_HUMAN = "fallback_to_human"


class ConfidenceLevel(str, Enum):
    """Confidence levels for intent detection"""
    VERY_HIGH = "very_high"    # > 0.9
    HIGH = "high"              # 0.8 - 0.9
    MEDIUM = "medium"          # 0.6 - 0.8
    LOW = "low"                # 0.4 - 0.6
    VERY_LOW = "very_low"      # < 0.4


class DetectedIntent(BaseModel):
    """Individual detected intent with confidence and parameters"""
    intent: IntentType
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    parameters: Dict[str, Any] = Field(default_factory=dict)
    source_detector: str = Field(..., description="Which detector found this intent")
    detected_at: datetime = Field(default_factory=datetime.utcnow)

    def __init__(self, **data):
        super().__init__(**data)
        # Auto-calculate confidence level
        if self.confidence > 0.9:
            self.confidence_level = ConfidenceLevel.VERY_HIGH
        elif self.confidence >= 0.8:
            self.confidence_level = ConfidenceLevel.HIGH
        elif self.confidence >= 0.6:
            self.confidence_level = ConfidenceLevel.MEDIUM
        elif self.confidence >= 0.4:
            self.confidence_level = ConfidenceLevel.LOW
        else:
            self.confidence_level = ConfidenceLevel.VERY_LOW


class ConversationSlot(BaseModel):
    """Slot for storing conversation parameters"""
    name: str
    value: Any
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: str = Field(..., description="How this slot was filled")
    filled_at: datetime = Field(default_factory=datetime.utcnow)
    confirmed: bool = False


class ConversationState(str, Enum):
    """Advanced conversation states for multi-turn dialogs"""
    GREETING = "greeting"
    INFORMATION_GATHERING = "information_gathering"
    SLOT_FILLING = "slot_filling"
    CONFIRMATION = "confirmation"
    EXECUTION = "execution"
    CLARIFICATION = "clarification"
    UPSELLING = "upselling"
    PROBLEM_SOLVING = "problem_solving"
    CLOSING = "closing"
    ESCALATION = "escalation"


class MultiIntentDetectionResult(BaseModel):
    """Result of multi-intent detection for a single utterance"""
    utterance: str
    detected_intents: List[DetectedIntent] = Field(default_factory=list)
    primary_intent: Optional[DetectedIntent] = None
    language: str = "en"
    processing_time_ms: float = 0.0
    ambiguous: bool = False
    requires_clarification: bool = False
    clarification_message: Optional[str] = None

    def get_highest_confidence_intent(self) -> Optional[DetectedIntent]:
        """Get the intent with highest confidence"""
        if not self.detected_intents:
            return None
        return max(self.detected_intents, key=lambda x: x.confidence)

    def get_intents_above_threshold(self, threshold: float = 0.6) -> List[DetectedIntent]:
        """Get all intents above confidence threshold"""
        return [intent for intent in self.detected_intents if intent.confidence >= threshold]

    def has_high_confidence_intent(self, threshold: float = 0.8) -> bool:
        """Check if any intent has high confidence"""
        return any(intent.confidence >= threshold for intent in self.detected_intents)


class ConversationTurn(BaseModel):
    """Enhanced conversation turn with multi-intent support"""
    role: str = Field(..., description="user|assistant")
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    language: str = "en"
    turn_type: str = Field(default="text", description="text|dtmf|dtmf_response")

    # Multi-intent detection results
    detection_result: Optional[MultiIntentDetectionResult] = None

    # Extracted slots
    slots: List[ConversationSlot] = Field(default_factory=list)

    # Function calls triggered
    function_calls: List[Dict[str, Any]] = Field(default_factory=list)

    # Response generation metadata
    response_metadata: Dict[str, Any] = Field(default_factory=dict)


class EnhancedCallContext(BaseModel):
    """Enhanced call context with multi-intent and conversation flow support"""
    model_config = {"arbitrary_types_allowed": True}

    # Basic call information
    call_id: str
    room_name: str
    hotel_id: Optional[str] = None
    call_sid: Optional[str] = None
    participant_sid: Optional[str] = None
    participant_identity: Optional[str] = None

    # Enhanced state management
    call_state: str = "initializing"  # CallState from call_manager
    conversation_state: ConversationState = ConversationState.GREETING
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None

    # Enhanced language and intent support
    detected_language: str = "en"

    # Multi-intent support (Sprint 3 enhancement)
    current_intents: List[DetectedIntent] = Field(default_factory=list)
    intent_history: List[MultiIntentDetectionResult] = Field(default_factory=list)

    # Conversation slots for parameter extraction
    active_slots: Dict[str, ConversationSlot] = Field(default_factory=dict)
    completed_slots: Dict[str, ConversationSlot] = Field(default_factory=dict)

    # Enhanced conversation history
    conversation_turns: List[ConversationTurn] = Field(default_factory=list)

    # Context management
    conversation_context: Dict[str, Any] = Field(default_factory=dict)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    session_metadata: Dict[str, Any] = Field(default_factory=dict)

    # Metrics
    asr_latency_ms: Optional[float] = None
    tts_latency_ms: Optional[float] = None
    llm_latency_ms: Optional[float] = None
    intent_detection_latency_ms: Optional[float] = None

    # PMS data cache
    pms_data: Optional[Dict[str, Any]] = None

    # Conversation flow management
    pending_clarifications: List[str] = Field(default_factory=list)
    upselling_opportunities: List[Dict[str, Any]] = Field(default_factory=list)
    escalation_reasons: List[str] = Field(default_factory=list)

    def add_conversation_turn(self, turn: ConversationTurn):
        """Add a new conversation turn"""
        self.conversation_turns.append(turn)

        # Update intent history if detection result exists
        if turn.detection_result:
            self.intent_history.append(turn.detection_result)

            # Update current intents with high confidence intents
            high_conf_intents = turn.detection_result.get_intents_above_threshold(0.6)
            if high_conf_intents:
                self.current_intents = high_conf_intents

        # Extract and store slots
        for slot in turn.slots:
            if slot.confidence >= 0.6:
                self.active_slots[slot.name] = slot

    def get_recent_turns(self, limit: int = 5) -> List[ConversationTurn]:
        """Get recent conversation turns"""
        return self.conversation_turns[-limit:] if self.conversation_turns else []

    def get_primary_intent(self) -> Optional[DetectedIntent]:
        """Get the current primary intent"""
        if not self.current_intents:
            return None
        return max(self.current_intents, key=lambda x: x.confidence)

    def has_slot(self, slot_name: str) -> bool:
        """Check if a slot is filled"""
        return slot_name in self.active_slots or slot_name in self.completed_slots

    def get_slot_value(self, slot_name: str) -> Any:
        """Get value of a filled slot"""
        if slot_name in self.active_slots:
            return self.active_slots[slot_name].value
        elif slot_name in self.completed_slots:
            return self.completed_slots[slot_name].value
        return None

    def complete_slot(self, slot_name: str):
        """Mark a slot as completed"""
        if slot_name in self.active_slots:
            self.completed_slots[slot_name] = self.active_slots.pop(slot_name)

    def needs_clarification(self) -> bool:
        """Check if conversation needs clarification"""
        return len(self.pending_clarifications) > 0

    def has_upselling_opportunity(self) -> bool:
        """Check if there are upselling opportunities"""
        return len(self.upselling_opportunities) > 0

    def should_escalate(self) -> bool:
        """Check if conversation should be escalated to human"""
        return len(self.escalation_reasons) > 0


class SlotFillingRequest(BaseModel):
    """Request for slot filling from conversation"""
    utterance: str
    required_slots: List[str]
    optional_slots: List[str] = Field(default_factory=list)
    conversation_context: Dict[str, Any] = Field(default_factory=dict)
    language: str = "en"


class SlotFillingResult(BaseModel):
    """Result of slot filling operation"""
    filled_slots: List[ConversationSlot] = Field(default_factory=list)
    missing_slots: List[str] = Field(default_factory=list)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    requires_clarification: bool = False
    clarification_questions: List[str] = Field(default_factory=list)


class FunctionCallResult(BaseModel):
    """Result of a function call execution"""
    function_name: str
    parameters: Dict[str, Any]
    result: Any
    success: bool
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    confidence: float = Field(..., ge=0.0, le=1.0)


class ConversationFlowDecision(BaseModel):
    """Decision about conversation flow direction"""
    next_state: ConversationState
    actions: List[str] = Field(default_factory=list)
    required_slots: List[str] = Field(default_factory=list)
    suggested_responses: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = ""
