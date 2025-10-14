"""
Intent Detection Service for VoiceHive Hotels
Provides multilingual intent classification with multiple detection strategies
"""

import asyncio
import json
import re
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Union, Tuple
from enum import Enum
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_random_exponential

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.intent_detection")


class IntentType(str, Enum):
    """Supported intent types for hotel voice assistant"""
    GREETING = "greeting"
    QUESTION = "question"
    REQUEST_INFO = "request_info"
    BOOKING_INQUIRY = "booking_inquiry"
    END_CALL = "end_call"
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    """Intent detection confidence levels"""
    HIGH = "high"      # >0.8
    MEDIUM = "medium"  # 0.5-0.8
    LOW = "low"        # 0.2-0.5
    VERY_LOW = "very_low"  # <0.2


@dataclass
class IntentDetectionResult:
    """Result of intent detection analysis"""
    intent: IntentType
    confidence: float
    confidence_level: ConfidenceLevel
    detected_language: str
    detection_method: str
    processing_time_ms: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IntentDetector(ABC):
    """Abstract base class for intent detection strategies"""

    @abstractmethod
    async def detect_intent(self, text: str, context: Optional[Dict[str, Any]] = None) -> IntentDetectionResult:
        """Detect intent from text"""
        pass

    @abstractmethod
    def get_supported_languages(self) -> List[str]:
        """Get list of supported language codes"""
        pass


class KeywordBasedDetector(IntentDetector):
    """Simple, fast keyword-based intent detection"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.patterns = self._load_patterns()
        self.supported_languages = ["en", "de", "es", "fr", "it"]

    async def detect_intent(self, text: str, context: Optional[Dict[str, Any]] = None) -> IntentDetectionResult:
        """Detect intent using keyword matching"""
        start_time = datetime.now(timezone.utc)

        if not text or not text.strip():
            return self._create_result(IntentType.UNKNOWN, 0.0, "empty_text", start_time)

        # Normalize text
        normalized_text = text.lower().strip()

        # Detect language (simple heuristic)
        detected_language = self._detect_language(normalized_text)

        # Score each intent
        intent_scores = {}
        for intent_type in IntentType:
            if intent_type == IntentType.UNKNOWN:
                continue
            score = self._calculate_intent_score(normalized_text, intent_type, detected_language)
            intent_scores[intent_type] = score

        # Determine best intent
        if intent_scores:
            best_intent = max(intent_scores, key=intent_scores.get)
            confidence = intent_scores[best_intent]

            # Apply confidence threshold
            if confidence >= 0.1:
                return self._create_result(
                    best_intent, confidence, "keyword_matching", start_time,
                    {"scores": {k.value: v for k, v in intent_scores.items()}},
                    detected_language
                )

        return self._create_result(IntentType.UNKNOWN, 0.0, "no_match", start_time,
                                 {"scores": {k.value: v for k, v in intent_scores.items()}}, detected_language)

    def get_supported_languages(self) -> List[str]:
        return self.supported_languages.copy()

    def _load_patterns(self) -> Dict[str, Dict[str, List[str]]]:
        """Load intent patterns for different languages"""
        return {
            "greeting": {
                "en": [
                    r'\b(hello|hi|hey|good\s+(morning|afternoon|evening|day)|greetings)\b',
                    r'\b(how\s+are\s+you|nice\s+to\s+meet|pleasure\s+to\s+speak)\b'
                ],
                "de": [
                    r'\b(hallo|guten\s+(tag|morgen|abend)|servus|moin)\b',
                    r'\b(wie\s+geht\s+es|freut\s+mich)\b'
                ],
                "es": [
                    r'\b(hola|buenos?\s+(días?|tardes?|noches?)|buenas)\b',
                    r'\b(cómo\s+está|mucho\s+gusto)\b'
                ],
                "fr": [
                    r'\b(bonjour|bonsoir|salut|allô)\b',
                    r'\b(comment\s+allez\s+vous|enchanté)\b'
                ],
                "it": [
                    r'\b(ciao|buongiorno|buonasera|salve)\b',
                    r'\b(come\s+sta|piacere)\b'
                ]
            },

            "end_call": {
                "en": [
                    r'\b(goodbye|bye|thank\s+you|thanks|have\s+a\s+nice\s+day|see\s+you|farewell)\b',
                    r'\b(that\'?s\s+all|i\'?m\s+done|we\'?re\s+done|end\s+call|hang\s+up|no\s+more\s+questions)\b'
                ],
                "de": [
                    r'\b(auf\s+wiedersehen|tschüss|danke|vielen\s+dank|bis\s+bald|ende)\b',
                    r'\b(das\s+war\'?s|ich\s+bin\s+fertig|auflegen)\b'
                ],
                "es": [
                    r'\b(adiós|hasta\s+luego|gracias|muchas\s+gracias|chao|fin)\b',
                    r'\b(eso\s+es\s+todo|he\s+terminado|colgar)\b'
                ],
                "fr": [
                    r'\b(au\s+revoir|à\s+bientôt|merci|merci\s+beaucoup|salut|fin)\b',
                    r'\b(c\'?est\s+tout|j\'?ai\s+fini|raccrocher)\b'
                ],
                "it": [
                    r'\b(arrivederci|ciao|grazie|tante\s+grazie|basta\s+così)\b',
                    r'\b(è\s+tutto|ho\s+finito|riagganciare)\b'
                ]
            },

            "booking_inquiry": {
                "en": [
                    r'\b(book|booking|reservation|reserve|room|availability|available)\b',
                    r'\b(check\s+in|check\s+out|stay|night|hotel|suite|vacancy)\b',
                    r'\b(rates?|price|cost|how\s+much|quote|tariff)\b'
                ],
                "de": [
                    r'\b(buchen|buchung|reservierung|zimmer|verfügbar|übernachtung)\b',
                    r'\b(preise?|kosten|wie\s+viel|angebot|tarif)\b'
                ],
                "es": [
                    r'\b(reserv|habitación|disponible|estancia|noche|precio|tarifa)\b',
                    r'\b(cuánto\s+cuesta|cotización)\b'
                ],
                "fr": [
                    r'\b(réserv|chambre|disponible|séjour|nuit|tarif|prix)\b',
                    r'\b(combien|devis)\b'
                ],
                "it": [
                    r'\b(prenotare|prenotazione|camera|disponibile|soggiorno|prezzo|tariffa)\b',
                    r'\b(quanto\s+costa|preventivo)\b'
                ]
            },

            "request_info": {
                "en": [
                    r'\b(information|info|tell\s+me|what|when|where|how|which|can\s+you)\b',
                    r'\b(hours?|time|schedule|open|close|location|address|amenities)\b',
                    r'\b(restaurant|spa|gym|pool|wifi|parking|services)\b'
                ],
                "de": [
                    r'\b(information|info|öffnungszeiten|wann|wo|wie|können\s+sie)\b',
                    r'\b(restaurant|wellness|fitness|schwimmbad|wifi|parkplatz)\b'
                ],
                "es": [
                    r'\b(información|info|horario|cuándo|dónde|cómo|pueden)\b',
                    r'\b(restaurante|spa|gimnasio|piscina|wifi|aparcamiento)\b'
                ],
                "fr": [
                    r'\b(information|info|horaires?|quand|où|comment|pouvez)\b',
                    r'\b(restaurant|spa|salle\s+de\s+sport|piscine|wifi|parking)\b'
                ],
                "it": [
                    r'\b(informazioni|info|orari|quando|dove|come|potete)\b',
                    r'\b(ristorante|spa|palestra|piscina|wifi|parcheggio)\b'
                ]
            },

            "question": {
                "en": [
                    r'^(what|when|where|why|how|which|who|can|could|would|will|is|are|do|does)\b',
                    r'\?'  # Questions typically end with question marks
                ],
                "de": [
                    r'^(was|wann|wo|warum|wie|welche|wer|können|würden|ist|sind)\b',
                    r'\?'
                ],
                "es": [
                    r'^(qué|cuándo|dónde|por\s+qué|cómo|cuál|quién|pueden|es|son)\b',
                    r'\?'
                ],
                "fr": [
                    r'^(que|quand|où|pourquoi|comment|quel|qui|pouvez|est|sont)\b',
                    r'\?'
                ],
                "it": [
                    r'^(cosa|quando|dove|perché|come|quale|chi|potete|è|sono)\b',
                    r'\?'
                ]
            }
        }

    def _detect_language(self, text: str) -> str:
        """Simple language detection based on common words"""
        # Language-specific common words
        language_indicators = {
            "de": ["ich", "ist", "das", "der", "die", "und", "oder", "haben", "sein", "können"],
            "es": ["el", "la", "es", "de", "que", "en", "un", "se", "con", "para"],
            "fr": ["le", "de", "et", "un", "il", "être", "et", "en", "avoir", "que"],
            "it": ["il", "di", "che", "è", "per", "un", "in", "con", "del", "la"]
        }

        words = text.lower().split()
        language_scores = {"en": 0}  # Default to English

        for lang, indicators in language_indicators.items():
            score = sum(1 for word in words if word in indicators)
            if score > 0:
                language_scores[lang] = score / len(words)

        return max(language_scores, key=language_scores.get)

    def _calculate_intent_score(self, text: str, intent_type: IntentType, language: str) -> float:
        """Calculate score for a specific intent"""
        patterns = self.patterns.get(intent_type.value, {})
        lang_patterns = patterns.get(language, patterns.get("en", []))

        if not lang_patterns:
            return 0.0

        total_score = 0.0
        text_length = len(text.split())

        for pattern in lang_patterns:
            matches = len(re.findall(pattern, text, re.IGNORECASE))
            if matches > 0:
                # Score based on number of matches, normalized by text length
                pattern_score = (matches * 2) / max(text_length, 1)
                total_score += pattern_score

        # Cap the score at 1.0
        return min(total_score, 1.0)

    def _create_result(self, intent: IntentType, confidence: float, method: str,
                      start_time: datetime, metadata: Optional[Dict] = None,
                      language: str = "en") -> IntentDetectionResult:
        """Helper to create IntentDetectionResult"""

        # Determine confidence level
        if confidence >= 0.8:
            confidence_level = ConfidenceLevel.HIGH
        elif confidence >= 0.5:
            confidence_level = ConfidenceLevel.MEDIUM
        elif confidence >= 0.2:
            confidence_level = ConfidenceLevel.LOW
        else:
            confidence_level = ConfidenceLevel.VERY_LOW

        processing_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        return IntentDetectionResult(
            intent=intent,
            confidence=confidence,
            confidence_level=confidence_level,
            detected_language=language,
            detection_method=method,
            processing_time_ms=int(processing_time),
            metadata=metadata or {}
        )


class IntentDetectionService:
    """Main intent detection service with configurable detection strategies"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or self._get_default_config()
        self.detectors: Dict[str, IntentDetector] = {}
        self.primary_detector_name = self.config.get("primary_detector", "keyword")

        # Initialize detectors
        self._initialize_detectors()

        # Statistics
        self.stats = {
            "total_detections": 0,
            "by_intent": {},
            "by_confidence": {},
            "by_detector": {},
            "by_language": {}
        }

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            "primary_detector": "keyword",
            "fallback_detectors": ["keyword"],
            "confidence_threshold": 0.1,
            "enable_fallback": True,
            "log_all_detections": True,
            "cache_results": False
        }

    def _initialize_detectors(self):
        """Initialize available intent detectors"""
        # Always available: keyword-based detector
        self.detectors["keyword"] = KeywordBasedDetector(self.config.get("keyword_config", {}))

        # TODO: Add spaCy detector when spacy is available
        # TODO: Add Azure OpenAI detector when configured

        logger.info(f"Initialized intent detectors: {list(self.detectors.keys())}")

    async def detect_intent(self, text: str, context: Optional[Dict[str, Any]] = None) -> IntentDetectionResult:
        """
        Detect intent from text using the configured detection strategy

        Args:
            text: User input text to analyze
            context: Optional context information (call state, conversation history, etc.)

        Returns:
            IntentDetectionResult with detected intent and confidence
        """
        if not text or not text.strip():
            return IntentDetectionResult(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                confidence_level=ConfidenceLevel.VERY_LOW,
                detected_language="en",
                detection_method="empty_input",
                processing_time_ms=0,
                metadata={"reason": "empty_or_none_input"}
            )

        # Use primary detector
        primary_detector = self.detectors.get(self.primary_detector_name)
        if not primary_detector:
            logger.error(f"Primary detector '{self.primary_detector_name}' not available")
            return self._create_unknown_result("detector_not_available")

        try:
            result = await primary_detector.detect_intent(text, context)

            # Check if we need fallback detection
            if (result.confidence < self.config["confidence_threshold"] and
                self.config.get("enable_fallback", False)):
                result = await self._try_fallback_detection(text, context, result)

            # Update statistics
            self._update_stats(result)

            # Log if configured
            if self.config.get("log_all_detections", False):
                logger.info(
                    "intent_detected",
                    intent=result.intent.value,
                    confidence=result.confidence,
                    confidence_level=result.confidence_level.value,
                    language=result.detected_language,
                    method=result.detection_method,
                    processing_time_ms=result.processing_time_ms
                )

            return result

        except Exception as e:
            logger.error(f"Intent detection failed: {e}")
            return self._create_unknown_result("detection_error", {"error": str(e)})

    async def _try_fallback_detection(self, text: str, context: Optional[Dict[str, Any]],
                                    primary_result: IntentDetectionResult) -> IntentDetectionResult:
        """Try fallback detection methods"""

        fallback_detectors = self.config.get("fallback_detectors", [])
        best_result = primary_result

        for detector_name in fallback_detectors:
            if detector_name == self.primary_detector_name:
                continue  # Skip primary detector

            detector = self.detectors.get(detector_name)
            if not detector:
                continue

            try:
                result = await detector.detect_intent(text, context)
                if result.confidence > best_result.confidence:
                    best_result = result
                    best_result.metadata["fallback_used"] = True
                    best_result.metadata["primary_method"] = primary_result.detection_method

            except Exception as e:
                logger.warning(f"Fallback detector {detector_name} failed: {e}")

        return best_result

    def _create_unknown_result(self, reason: str, metadata: Optional[Dict] = None) -> IntentDetectionResult:
        """Create an unknown intent result"""
        return IntentDetectionResult(
            intent=IntentType.UNKNOWN,
            confidence=0.0,
            confidence_level=ConfidenceLevel.VERY_LOW,
            detected_language="en",
            detection_method="error_fallback",
            processing_time_ms=0,
            metadata={"reason": reason, **(metadata or {})}
        )

    def _update_stats(self, result: IntentDetectionResult):
        """Update detection statistics"""
        self.stats["total_detections"] += 1

        # By intent
        intent_key = result.intent.value
        self.stats["by_intent"][intent_key] = self.stats["by_intent"].get(intent_key, 0) + 1

        # By confidence level
        conf_key = result.confidence_level.value
        self.stats["by_confidence"][conf_key] = self.stats["by_confidence"].get(conf_key, 0) + 1

        # By detector
        method_key = result.detection_method
        self.stats["by_detector"][method_key] = self.stats["by_detector"].get(method_key, 0) + 1

        # By language
        lang_key = result.detected_language
        self.stats["by_language"][lang_key] = self.stats["by_language"].get(lang_key, 0) + 1

    def get_statistics(self) -> Dict[str, Any]:
        """Get detection statistics"""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "config": self.config,
            "available_detectors": list(self.detectors.keys()),
            "primary_detector": self.primary_detector_name,
            "statistics": self.stats.copy()
        }

    def get_supported_languages(self) -> List[str]:
        """Get all supported languages from all detectors"""
        all_languages = set()
        for detector in self.detectors.values():
            all_languages.update(detector.get_supported_languages())
        return sorted(list(all_languages))


# Example usage and testing
if __name__ == "__main__":
    import asyncio

    async def test_intent_detection():
        # Create intent detection service
        service = IntentDetectionService()

        # Test cases
        test_cases = [
            ("Hello, good morning!", IntentType.GREETING),
            ("I'd like to book a room for tonight", IntentType.BOOKING_INQUIRY),
            ("What time does the restaurant open?", IntentType.REQUEST_INFO),
            ("Can you tell me about your spa services?", IntentType.QUESTION),
            ("Thank you, goodbye!", IntentType.END_CALL),
            ("Guten Tag, ich möchte ein Zimmer buchen", IntentType.BOOKING_INQUIRY),  # German
            ("¿Cuánto cuesta una habitación?", IntentType.QUESTION),  # Spanish
            ("", IntentType.UNKNOWN)
        ]

        print("Testing Intent Detection Service")
        print("=" * 50)

        for text, expected_intent in test_cases:
            result = await service.detect_intent(text)

            print(f"Text: '{text}'")
            print(f"Expected: {expected_intent.value}")
            print(f"Detected: {result.intent.value}")
            print(f"Confidence: {result.confidence:.3f} ({result.confidence_level.value})")
            print(f"Language: {result.detected_language}")
            print(f"Method: {result.detection_method}")
            print(f"Processing: {result.processing_time_ms}ms")

            if result.intent == expected_intent:
                print("✅ PASS")
            else:
                print("❌ FAIL")
            print("-" * 30)

        # Print statistics
        stats = service.get_statistics()
        print(f"Total detections: {stats['statistics']['total_detections']}")
        print(f"Supported languages: {service.get_supported_languages()}")

        print("Intent detection test completed successfully")

    # Run test
    asyncio.run(test_intent_detection())