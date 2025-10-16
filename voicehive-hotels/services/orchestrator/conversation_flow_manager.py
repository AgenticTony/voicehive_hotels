"""
Conversation Flow Manager for Sprint 3
Manages advanced conversation states, slot filling, and multi-turn dialogs
"""

import time
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta

from .logging_adapter import get_safe_logger
from .models import (
    ConversationState,
    ConversationFlowDecision,
    ConversationSlot,
    SlotFillingRequest,
    SlotFillingResult,
    EnhancedCallContext,
    DetectedIntent,
    IntentType,
    ConversationTurn,
    MultiIntentDetectionResult
)

logger = get_safe_logger("orchestrator.conversation_flow_manager")


class ConversationFlowManager:
    """Manages conversation flow and state transitions for enhanced AI interactions"""

    def __init__(self):
        # Define slot requirements for each intent type
        self.intent_slot_requirements = {
            IntentType.BOOKING_INQUIRY: {
                "required": ["check_in_date", "check_out_date", "guest_count"],
                "optional": ["room_type", "special_requests", "budget_range"]
            },
            IntentType.EXISTING_RESERVATION_MODIFY: {
                "required": ["confirmation_number"],
                "optional": ["new_check_in", "new_check_out", "new_room_type", "modification_type"]
            },
            IntentType.EXISTING_RESERVATION_CANCEL: {
                "required": ["confirmation_number"],
                "optional": ["cancellation_reason"]
            },
            IntentType.RESTAURANT_BOOKING: {
                "required": ["date", "time", "party_size"],
                "optional": ["special_requests", "seating_preference"]
            },
            IntentType.SPA_BOOKING: {
                "required": ["service_type", "date", "time"],
                "optional": ["duration", "therapist_preference", "special_requests"]
            },
            IntentType.ROOM_SERVICE: {
                "required": ["room_number"],
                "optional": ["items", "delivery_time", "special_instructions"]
            },
            IntentType.UPSELLING_OPPORTUNITY: {
                "required": ["current_reservation"],
                "optional": ["upgrade_type", "budget_range", "special_occasion"]
            },
            IntentType.CONCIERGE_SERVICES: {
                "required": ["service_type"],
                "optional": ["date", "time", "location", "budget_range"]
            }
        }

        # Define state transition rules
        self.state_transitions = {
            ConversationState.GREETING: {
                "allowed_next": [
                    ConversationState.INFORMATION_GATHERING,
                    ConversationState.SLOT_FILLING,
                    ConversationState.EXECUTION,
                    ConversationState.CLOSING
                ]
            },
            ConversationState.INFORMATION_GATHERING: {
                "allowed_next": [
                    ConversationState.SLOT_FILLING,
                    ConversationState.CONFIRMATION,
                    ConversationState.CLARIFICATION,
                    ConversationState.EXECUTION
                ]
            },
            ConversationState.SLOT_FILLING: {
                "allowed_next": [
                    ConversationState.SLOT_FILLING,  # Continue filling
                    ConversationState.CONFIRMATION,
                    ConversationState.CLARIFICATION,
                    ConversationState.EXECUTION
                ]
            },
            ConversationState.CONFIRMATION: {
                "allowed_next": [
                    ConversationState.EXECUTION,
                    ConversationState.SLOT_FILLING,  # If user wants to change
                    ConversationState.CLARIFICATION
                ]
            },
            ConversationState.EXECUTION: {
                "allowed_next": [
                    ConversationState.UPSELLING,
                    ConversationState.CLOSING,
                    ConversationState.PROBLEM_SOLVING,
                    ConversationState.INFORMATION_GATHERING  # For follow-up requests
                ]
            },
            ConversationState.CLARIFICATION: {
                "allowed_next": [
                    ConversationState.INFORMATION_GATHERING,
                    ConversationState.SLOT_FILLING,
                    ConversationState.ESCALATION
                ]
            },
            ConversationState.UPSELLING: {
                "allowed_next": [
                    ConversationState.SLOT_FILLING,  # For upsell details
                    ConversationState.CONFIRMATION,
                    ConversationState.CLOSING,
                    ConversationState.EXECUTION
                ]
            },
            ConversationState.PROBLEM_SOLVING: {
                "allowed_next": [
                    ConversationState.EXECUTION,
                    ConversationState.ESCALATION,
                    ConversationState.CLOSING
                ]
            },
            ConversationState.ESCALATION: {
                "allowed_next": [
                    ConversationState.CLOSING  # After transfer
                ]
            },
            ConversationState.CLOSING: {
                "allowed_next": []  # Terminal state
            }
        }

    def determine_next_conversation_state(
        self,
        current_context: EnhancedCallContext,
        detection_result: MultiIntentDetectionResult
    ) -> ConversationFlowDecision:
        """
        Determine the next conversation state based on current context and detected intents

        Args:
            current_context: Current conversation context
            detection_result: Latest intent detection result

        Returns:
            ConversationFlowDecision with next state and actions
        """
        try:
            current_state = current_context.conversation_state
            primary_intent = detection_result.get_highest_confidence_intent()

            logger.info(
                "determining_conversation_flow",
                current_state=current_state.value,
                primary_intent=primary_intent.intent.value if primary_intent else None,
                primary_confidence=primary_intent.confidence if primary_intent else 0.0,
                ambiguous=detection_result.ambiguous
            )

            # Handle clarification needed scenarios
            if detection_result.requires_clarification or detection_result.ambiguous:
                return self._handle_clarification_needed(current_context, detection_result)

            # Handle transfer/escalation intents
            if primary_intent and primary_intent.intent in [
                IntentType.TRANSFER_TO_OPERATOR,
                IntentType.FALLBACK_TO_HUMAN
            ]:
                return self._handle_escalation(current_context, primary_intent)

            # Handle end call intent
            if primary_intent and primary_intent.intent == IntentType.END_CALL:
                return self._handle_call_ending(current_context, primary_intent)

            # Handle complaint/feedback
            if primary_intent and primary_intent.intent == IntentType.COMPLAINT_FEEDBACK:
                return self._handle_complaint(current_context, primary_intent)

            # Main conversation flow logic
            return self._determine_main_flow(current_context, detection_result, primary_intent)

        except Exception as e:
            logger.error("conversation_flow_determination_error", error=str(e))

            # Fallback decision
            return ConversationFlowDecision(
                next_state=ConversationState.CLARIFICATION,
                actions=["ask_clarification"],
                required_slots=[],
                suggested_responses=["I'm sorry, I didn't understand. Could you please rephrase?"],
                confidence=0.3,
                reasoning="Error in flow determination, falling back to clarification"
            )

    def _determine_main_flow(
        self,
        current_context: EnhancedCallContext,
        detection_result: MultiIntentDetectionResult,
        primary_intent: Optional[DetectedIntent]
    ) -> ConversationFlowDecision:
        """Determine main conversation flow based on current state and intent"""

        current_state = current_context.conversation_state

        if not primary_intent:
            return self._handle_no_intent(current_context)

        # State-specific logic
        if current_state == ConversationState.GREETING:
            return self._handle_greeting_state(current_context, primary_intent)

        elif current_state == ConversationState.INFORMATION_GATHERING:
            return self._handle_information_gathering(current_context, primary_intent)

        elif current_state == ConversationState.SLOT_FILLING:
            return self._handle_slot_filling_state(current_context, primary_intent)

        elif current_state == ConversationState.CONFIRMATION:
            return self._handle_confirmation_state(current_context, primary_intent)

        elif current_state == ConversationState.EXECUTION:
            return self._handle_execution_state(current_context, primary_intent)

        elif current_state == ConversationState.UPSELLING:
            return self._handle_upselling_state(current_context, primary_intent)

        else:
            # Default fallback
            return self._transition_to_information_gathering(primary_intent)

    def _handle_greeting_state(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle conversation flow from greeting state"""

        if primary_intent.intent == IntentType.GREETING:
            return ConversationFlowDecision(
                next_state=ConversationState.INFORMATION_GATHERING,
                actions=["respond_greeting", "ask_how_can_help"],
                required_slots=[],
                suggested_responses=[
                    "Hello! Welcome to our hotel. How can I assist you today?",
                    "Good day! I'm here to help with your hotel needs. What can I do for you?"
                ],
                confidence=0.9,
                reasoning="Greeting detected, transitioning to information gathering"
            )

        elif primary_intent.intent in [
            IntentType.BOOKING_INQUIRY,
            IntentType.EXISTING_RESERVATION_MODIFY,
            IntentType.EXISTING_RESERVATION_CANCEL,
            IntentType.RESTAURANT_BOOKING,
            IntentType.SPA_BOOKING,
            IntentType.ROOM_SERVICE
        ]:
            return self._transition_to_slot_filling(primary_intent)

        else:
            return self._transition_to_information_gathering(primary_intent)

    def _handle_information_gathering(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle information gathering state"""

        # Check if this intent requires slot filling
        if primary_intent.intent in self.intent_slot_requirements:
            return self._transition_to_slot_filling(primary_intent)

        # For simple requests, go to execution
        if primary_intent.intent in [IntentType.REQUEST_INFO, IntentType.QUESTION]:
            return ConversationFlowDecision(
                next_state=ConversationState.EXECUTION,
                actions=["execute_info_request"],
                required_slots=[],
                suggested_responses=[],
                confidence=0.8,
                reasoning="Information request detected, executing directly"
            )

        # Check for upselling opportunity
        if primary_intent.intent == IntentType.UPSELLING_OPPORTUNITY:
            return ConversationFlowDecision(
                next_state=ConversationState.UPSELLING,
                actions=["identify_upselling_options"],
                required_slots=["current_reservation"],
                suggested_responses=[
                    "I'd be happy to help you explore upgrade options. May I have your confirmation number?",
                    "Let me check what premium options are available for your stay."
                ],
                confidence=0.8,
                reasoning="Upselling opportunity detected"
            )

        return self._transition_to_slot_filling(primary_intent)

    def _handle_slot_filling_state(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle slot filling state"""

        intent_requirements = self.intent_slot_requirements.get(primary_intent.intent, {})
        required_slots = intent_requirements.get("required", [])
        optional_slots = intent_requirements.get("optional", [])

        # Check which slots are still missing
        missing_required_slots = [
            slot for slot in required_slots
            if not current_context.has_slot(slot)
        ]

        if not missing_required_slots:
            # All required slots filled, move to confirmation
            return ConversationFlowDecision(
                next_state=ConversationState.CONFIRMATION,
                actions=["summarize_request", "ask_confirmation"],
                required_slots=[],
                suggested_responses=self._generate_confirmation_summary(current_context, primary_intent),
                confidence=0.9,
                reasoning="All required slots filled, requesting confirmation"
            )

        else:
            # Continue slot filling
            next_slot = missing_required_slots[0]
            return ConversationFlowDecision(
                next_state=ConversationState.SLOT_FILLING,
                actions=["ask_for_slot"],
                required_slots=[next_slot],
                suggested_responses=self._generate_slot_question(next_slot, primary_intent.intent),
                confidence=0.8,
                reasoning=f"Continuing slot filling, asking for {next_slot}"
            )

    def _handle_confirmation_state(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle confirmation state"""

        # Check for affirmative/negative responses
        affirmative_patterns = ['yes', 'yeah', 'correct', 'right', 'confirm', 'proceed']
        negative_patterns = ['no', 'nope', 'wrong', 'incorrect', 'change']

        utterance = current_context.get_recent_turns(1)[0].content.lower() if current_context.conversation_turns else ""

        if any(pattern in utterance for pattern in affirmative_patterns):
            return ConversationFlowDecision(
                next_state=ConversationState.EXECUTION,
                actions=["execute_confirmed_request"],
                required_slots=[],
                suggested_responses=["Perfect! Let me process that for you."],
                confidence=0.9,
                reasoning="User confirmed request, proceeding to execution"
            )

        elif any(pattern in utterance for pattern in negative_patterns):
            return ConversationFlowDecision(
                next_state=ConversationState.SLOT_FILLING,
                actions=["ask_what_to_change"],
                required_slots=[],
                suggested_responses=["What would you like to change?", "Which detail should I update?"],
                confidence=0.8,
                reasoning="User wants to change something, returning to slot filling"
            )

        else:
            # Unclear response, ask for clarification
            return ConversationFlowDecision(
                next_state=ConversationState.CLARIFICATION,
                actions=["ask_yes_no_clarification"],
                required_slots=[],
                suggested_responses=["Would you like me to proceed with this request? Please say yes or no."],
                confidence=0.6,
                reasoning="Unclear confirmation response, asking for clarification"
            )

    def _handle_execution_state(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle execution state"""

        # Check if there are upselling opportunities
        if current_context.has_upselling_opportunity():
            return ConversationFlowDecision(
                next_state=ConversationState.UPSELLING,
                actions=["present_upselling_options"],
                required_slots=[],
                suggested_responses=[
                    "Great! I've processed your request. I also noticed some special offers that might interest you."
                ],
                confidence=0.7,
                reasoning="Execution complete with upselling opportunities available"
            )

        # Check for follow-up intents
        if primary_intent.intent in [
            IntentType.BOOKING_INQUIRY,
            IntentType.RESTAURANT_BOOKING,
            IntentType.SPA_BOOKING
        ]:
            return ConversationFlowDecision(
                next_state=ConversationState.CLOSING,
                actions=["provide_confirmation_details", "ask_anything_else"],
                required_slots=[],
                suggested_responses=[
                    "All set! You'll receive a confirmation shortly. Is there anything else I can help you with?",
                    "Perfect! Your request has been processed. Can I assist with anything else today?"
                ],
                confidence=0.8,
                reasoning="Primary request executed, offering additional assistance"
            )

        else:
            return ConversationFlowDecision(
                next_state=ConversationState.INFORMATION_GATHERING,
                actions=["ask_anything_else"],
                required_slots=[],
                suggested_responses=["Is there anything else I can help you with?"],
                confidence=0.7,
                reasoning="Request completed, ready for additional requests"
            )

    def _handle_upselling_state(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle upselling state"""

        utterance = current_context.get_recent_turns(1)[0].content.lower() if current_context.conversation_turns else ""

        # Check for interest in upselling
        interested_patterns = ['yes', 'interested', 'tell me more', 'sounds good', 'upgrade']
        not_interested_patterns = ['no', 'not interested', 'no thanks', 'just basic']

        if any(pattern in utterance for pattern in interested_patterns):
            return ConversationFlowDecision(
                next_state=ConversationState.SLOT_FILLING,
                actions=["gather_upselling_preferences"],
                required_slots=["upgrade_type"],
                suggested_responses=[
                    "Wonderful! What type of upgrade interests you most?",
                    "Great! Let me get some details to find the perfect upgrade for you."
                ],
                confidence=0.8,
                reasoning="User interested in upselling, collecting preferences"
            )

        elif any(pattern in utterance for pattern in not_interested_patterns):
            return ConversationFlowDecision(
                next_state=ConversationState.CLOSING,
                actions=["acknowledge_no_upselling", "ask_anything_else"],
                required_slots=[],
                suggested_responses=[
                    "No problem at all! Is there anything else I can help you with today?",
                    "That's perfectly fine. Can I assist with anything else?"
                ],
                confidence=0.9,
                reasoning="User not interested in upselling, moving to close"
            )

        else:
            return ConversationFlowDecision(
                next_state=ConversationState.CLARIFICATION,
                actions=["clarify_upselling_interest"],
                required_slots=[],
                suggested_responses=[
                    "Would you be interested in hearing about upgrade options? Just say yes or no.",
                    "Are you interested in these upgrade options?"
                ],
                confidence=0.6,
                reasoning="Unclear response to upselling, asking for clarification"
            )

    def _transition_to_slot_filling(self, primary_intent: DetectedIntent) -> ConversationFlowDecision:
        """Transition to slot filling state"""

        intent_requirements = self.intent_slot_requirements.get(primary_intent.intent, {})
        required_slots = intent_requirements.get("required", [])

        if not required_slots:
            # No slots needed, go directly to execution
            return ConversationFlowDecision(
                next_state=ConversationState.EXECUTION,
                actions=["execute_request"],
                required_slots=[],
                suggested_responses=["Let me take care of that for you."],
                confidence=0.8,
                reasoning="No slots required for this intent, executing directly"
            )

        first_slot = required_slots[0]
        return ConversationFlowDecision(
            next_state=ConversationState.SLOT_FILLING,
            actions=["start_slot_filling"],
            required_slots=[first_slot],
            suggested_responses=self._generate_slot_question(first_slot, primary_intent.intent),
            confidence=0.8,
            reasoning=f"Starting slot filling for {primary_intent.intent.value}"
        )

    def _transition_to_information_gathering(self, primary_intent: DetectedIntent) -> ConversationFlowDecision:
        """Transition to information gathering state"""

        return ConversationFlowDecision(
            next_state=ConversationState.INFORMATION_GATHERING,
            actions=["gather_information"],
            required_slots=[],
            suggested_responses=[
                "I'd be happy to help with that. Could you provide more details?",
                "Sure! What specific information do you need?"
            ],
            confidence=0.7,
            reasoning="Need more information to process request"
        )

    def _handle_clarification_needed(
        self,
        current_context: EnhancedCallContext,
        detection_result: MultiIntentDetectionResult
    ) -> ConversationFlowDecision:
        """Handle scenarios where clarification is needed"""

        if detection_result.clarification_message:
            suggested_responses = [detection_result.clarification_message]
        else:
            suggested_responses = [
                "I'm not sure I understood that correctly. Could you please rephrase?",
                "Could you help me understand what you'd like to do?"
            ]

        return ConversationFlowDecision(
            next_state=ConversationState.CLARIFICATION,
            actions=["request_clarification"],
            required_slots=[],
            suggested_responses=suggested_responses,
            confidence=0.6,
            reasoning="Intent unclear or ambiguous, requesting clarification"
        )

    def _handle_escalation(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle escalation to human operator"""

        return ConversationFlowDecision(
            next_state=ConversationState.ESCALATION,
            actions=["initiate_transfer"],
            required_slots=[],
            suggested_responses=[
                "I'll connect you with one of our representatives right away. Please hold for a moment.",
                "Let me transfer you to a human agent who can better assist you."
            ],
            confidence=0.9,
            reasoning="User requested human assistance"
        )

    def _handle_call_ending(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle call ending"""

        return ConversationFlowDecision(
            next_state=ConversationState.CLOSING,
            actions=["end_call_gracefully"],
            required_slots=[],
            suggested_responses=[
                "Thank you for calling! Have a wonderful day.",
                "It was my pleasure to assist you. Goodbye!"
            ],
            confidence=0.9,
            reasoning="User indicated end of call"
        )

    def _handle_complaint(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> ConversationFlowDecision:
        """Handle complaints and feedback"""

        return ConversationFlowDecision(
            next_state=ConversationState.PROBLEM_SOLVING,
            actions=["acknowledge_concern", "gather_complaint_details"],
            required_slots=["complaint_details"],
            suggested_responses=[
                "I'm sorry to hear about this issue. Could you please tell me more details so I can help resolve it?",
                "I understand your concern. Let me get more information so I can assist you properly."
            ],
            confidence=0.8,
            reasoning="Complaint detected, moving to problem-solving mode"
        )

    def _handle_no_intent(self, current_context: EnhancedCallContext) -> ConversationFlowDecision:
        """Handle when no intent is detected"""

        return ConversationFlowDecision(
            next_state=ConversationState.CLARIFICATION,
            actions=["ask_general_help"],
            required_slots=[],
            suggested_responses=[
                "I'm here to help! What can I assist you with today?",
                "How may I help you with your hotel needs?"
            ],
            confidence=0.5,
            reasoning="No clear intent detected, asking for general guidance"
        )

    def _generate_slot_question(self, slot_name: str, intent: IntentType) -> List[str]:
        """Generate appropriate question for a specific slot"""

        slot_questions = {
            "check_in_date": [
                "When would you like to check in?",
                "What's your arrival date?"
            ],
            "check_out_date": [
                "When will you be checking out?",
                "What's your departure date?"
            ],
            "guest_count": [
                "How many guests will be staying?",
                "For how many people?"
            ],
            "room_type": [
                "What type of room would you prefer?",
                "Are you looking for a specific room category?"
            ],
            "confirmation_number": [
                "Could you provide your confirmation number?",
                "What's your reservation confirmation number?"
            ],
            "date": [
                "What date would you prefer?",
                "Which date works best for you?"
            ],
            "time": [
                "What time would you like?",
                "What time works for you?"
            ],
            "party_size": [
                "How many people will be dining?",
                "For how many guests?"
            ],
            "service_type": [
                "What type of service are you interested in?",
                "Which service would you like?"
            ],
            "room_number": [
                "What's your room number?",
                "Which room should I deliver to?"
            ]
        }

        return slot_questions.get(slot_name, [f"Could you provide the {slot_name.replace('_', ' ')}?"])

    def _generate_confirmation_summary(
        self,
        current_context: EnhancedCallContext,
        primary_intent: DetectedIntent
    ) -> List[str]:
        """Generate confirmation summary based on filled slots"""

        intent_type = primary_intent.intent

        if intent_type == IntentType.BOOKING_INQUIRY:
            check_in = current_context.get_slot_value("check_in_date")
            check_out = current_context.get_slot_value("check_out_date")
            guests = current_context.get_slot_value("guest_count")
            return [
                f"Let me confirm: you'd like to book a room for {guests} guests, checking in on {check_in} and checking out on {check_out}. Is this correct?"
            ]

        elif intent_type == IntentType.RESTAURANT_BOOKING:
            date = current_context.get_slot_value("date")
            time = current_context.get_slot_value("time")
            party_size = current_context.get_slot_value("party_size")
            return [
                f"I have a table for {party_size} people on {date} at {time}. Shall I confirm this reservation?"
            ]

        elif intent_type == IntentType.SPA_BOOKING:
            service = current_context.get_slot_value("service_type")
            date = current_context.get_slot_value("date")
            time = current_context.get_slot_value("time")
            return [
                f"Perfect! I have a {service} appointment on {date} at {time}. Should I book this for you?"
            ]

        else:
            return ["Let me confirm these details with you. Is everything correct?"]

    def extract_slots_from_utterance(
        self,
        utterance: str,
        required_slots: List[str],
        optional_slots: List[str] = None,
        conversation_context: Dict[str, Any] = None
    ) -> SlotFillingResult:
        """
        Extract slots from user utterance

        Args:
            utterance: User's text input
            required_slots: List of required slot names
            optional_slots: List of optional slot names
            conversation_context: Current conversation context

        Returns:
            SlotFillingResult with extracted slots
        """
        if optional_slots is None:
            optional_slots = []

        filled_slots = []
        missing_slots = []

        # Use regex patterns to extract common slot types
        slot_extractors = {
            "check_in_date": self._extract_date,
            "check_out_date": self._extract_date,
            "date": self._extract_date,
            "time": self._extract_time,
            "guest_count": self._extract_number,
            "party_size": self._extract_number,
            "room_number": self._extract_room_number,
            "confirmation_number": self._extract_confirmation_number,
            "room_type": self._extract_room_type,
            "service_type": self._extract_service_type
        }

        all_slots = required_slots + optional_slots

        for slot_name in all_slots:
            if slot_name in slot_extractors:
                value = slot_extractors[slot_name](utterance)
                if value:
                    slot = ConversationSlot(
                        name=slot_name,
                        value=value,
                        confidence=0.8,  # Default confidence for regex extraction
                        source="regex_extractor"
                    )
                    filled_slots.append(slot)
                elif slot_name in required_slots:
                    missing_slots.append(slot_name)

        # Calculate overall confidence
        confidence_score = len(filled_slots) / len(all_slots) if all_slots else 1.0

        # Determine if clarification is needed
        requires_clarification = len(missing_slots) > 0

        # Generate clarification questions
        clarification_questions = []
        if requires_clarification:
            for slot in missing_slots[:2]:  # Ask for up to 2 slots at once
                questions = self._generate_slot_question(slot, IntentType.UNKNOWN)
                clarification_questions.extend(questions[:1])  # Take first question

        return SlotFillingResult(
            filled_slots=filled_slots,
            missing_slots=missing_slots,
            confidence_score=confidence_score,
            requires_clarification=requires_clarification,
            clarification_questions=clarification_questions
        )

    def _extract_date(self, utterance: str) -> Optional[str]:
        """Extract date from utterance"""
        import re

        # Common date patterns
        patterns = [
            r'\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b',  # MM/DD or MM/DD/YYYY
            r'\b(\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december))\b',
            r'\b(today|tomorrow|next\s+week)\b',
            r'\b(\d{1,2}(?:st|nd|rd|th)\s+(?:january|february|march|april|may|june|july|august|september|october|november|december))\b'
        ]

        for pattern in patterns:
            match = re.search(pattern, utterance.lower())
            if match:
                return match.group(1)

        return None

    def _extract_time(self, utterance: str) -> Optional[str]:
        """Extract time from utterance"""
        import re

        patterns = [
            r'\b(\d{1,2}:\d{2}(?:\s?[ap]m)?)\b',
            r'\b(\d{1,2}\s?[ap]m)\b',
            r'\b(morning|afternoon|evening|noon|midnight)\b'
        ]

        for pattern in patterns:
            match = re.search(pattern, utterance.lower())
            if match:
                return match.group(1)

        return None

    def _extract_number(self, utterance: str) -> Optional[int]:
        """Extract number from utterance"""
        import re

        # Look for numbers in context
        patterns = [
            r'\b(\d+)\s+(?:people|person|guest|pax)\b',
            r'\bfor\s+(\d+)\b',
            r'\b(\d+)\b'
        ]

        for pattern in patterns:
            match = re.search(pattern, utterance.lower())
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue

        return None

    def _extract_room_number(self, utterance: str) -> Optional[str]:
        """Extract room number from utterance"""
        import re

        patterns = [
            r'\broom\s+(\d+[a-z]?)\b',
            r'\b(\d{3,4}[a-z]?)\b',  # 3-4 digit room numbers
            r'\broom\s+number\s+(\d+[a-z]?)\b'
        ]

        for pattern in patterns:
            match = re.search(pattern, utterance.lower())
            if match:
                return match.group(1)

        return None

    def _extract_confirmation_number(self, utterance: str) -> Optional[str]:
        """Extract confirmation number from utterance"""
        import re

        patterns = [
            r'\b([A-Z0-9]{6,})\b',  # Alphanumeric codes
            r'\bconfirmation\s+(?:number\s+)?([A-Z0-9-]{6,})\b',
            r'\breservation\s+(?:number\s+)?([A-Z0-9-]{6,})\b'
        ]

        for pattern in patterns:
            match = re.search(pattern, utterance)
            if match:
                return match.group(1)

        return None

    def _extract_room_type(self, utterance: str) -> Optional[str]:
        """Extract room type from utterance"""
        room_types = [
            'single', 'double', 'twin', 'suite', 'deluxe', 'standard',
            'executive', 'premium', 'luxury', 'junior suite', 'presidential'
        ]

        utterance_lower = utterance.lower()
        for room_type in room_types:
            if room_type in utterance_lower:
                return room_type

        return None

    def _extract_service_type(self, utterance: str) -> Optional[str]:
        """Extract service type from utterance"""
        service_types = [
            'massage', 'facial', 'manicure', 'pedicure', 'therapy',
            'restaurant', 'spa', 'concierge', 'room service', 'housekeeping'
        ]

        utterance_lower = utterance.lower()
        for service_type in service_types:
            if service_type in utterance_lower:
                return service_type

        return None