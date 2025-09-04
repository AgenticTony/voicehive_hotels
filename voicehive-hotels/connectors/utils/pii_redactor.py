"""
PII Redaction Utility for VoiceHive Hotels
Uses Microsoft Presidio for GDPR-compliant PII detection and redaction
"""

import logging
import re
from typing import Dict, List, Any, Optional
from functools import lru_cache
import json

try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import RecognizerResult

    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False
    logging.warning("Presidio not installed. PII redaction will be limited.")

logger = logging.getLogger(__name__)


class PIIRedactor:
    """
    PII Redactor for GDPR compliance

    Detects and redacts:
    - Names
    - Email addresses
    - Phone numbers
    - Room numbers
    - Credit card numbers
    - Passport/ID numbers
    - IP addresses
    - Dates of birth
    """

    # Custom patterns for hotel-specific PII
    ROOM_NUMBER_PATTERN = (
        r"\b(room|suite|rm|zimmer|chambre)\s*#?\s*(\d{1,4}[A-Za-z]?)\b"
    )
    CONFIRMATION_NUMBER_PATTERN = (
        r"\b(confirmation|conf|booking|res)\s*#?\s*([A-Z0-9]{6,12})\b"
    )
    GUEST_ID_PATTERN = r"\b(guest|member|loyalty)\s*#?\s*([A-Z0-9]{8,16})\b"

    def __init__(
        self,
        languages: List[str] = None,
        custom_redact_char: str = "▓",
        enable_custom_patterns: bool = True,
    ):
        """
        Initialize PII Redactor

        Args:
            languages: List of language codes to support (default: ["en", "de", "es", "fr", "it"])
            custom_redact_char: Character to use for redaction
            enable_custom_patterns: Enable hotel-specific pattern detection
        """
        self.languages = languages or ["en", "de", "es", "fr", "it"]
        self.redact_char = custom_redact_char
        self.enable_custom = enable_custom_patterns

        if PRESIDIO_AVAILABLE:
            # Initialize Presidio engines
            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()
        else:
            # Fallback to basic pattern matching
            self.analyzer = None
            self.anonymizer = None

    @lru_cache(maxsize=1000)
    def redact_text(self, text: str, language: str = "en") -> str:
        """
        Redact PII from text

        Args:
            text: Text to redact
            language: Language code for better detection

        Returns:
            Redacted text with PII replaced
        """
        if not text:
            return text

        redacted = text

        # Use Presidio if available
        if PRESIDIO_AVAILABLE and self.analyzer:
            try:
                # Analyze text for PII
                results = self.analyzer.analyze(
                    text=text,
                    language=language if language in self.languages else "en",
                    entities=None,  # Detect all entity types
                )

                # Sort results by start position (descending) to avoid offset issues
                results = sorted(results, key=lambda x: x.start, reverse=True)

                # Apply redaction
                for result in results:
                    redacted = self._apply_redaction(redacted, result.start, result.end)

            except Exception as e:
                logger.error(f"Presidio analysis failed: {e}. Using fallback patterns.")
                redacted = self._fallback_redact(text)
        else:
            redacted = self._fallback_redact(text)

        # Apply custom hotel-specific patterns
        if self.enable_custom:
            redacted = self._redact_custom_patterns(redacted)

        return redacted

    def redact_dict(
        self, data: Dict[str, Any], sensitive_keys: List[str] = None
    ) -> Dict[str, Any]:
        """
        Redact PII from dictionary values

        Args:
            data: Dictionary to redact
            sensitive_keys: Additional keys to fully redact

        Returns:
            Dictionary with redacted values
        """
        sensitive_keys = sensitive_keys or []
        default_sensitive = [
            "email",
            "phone",
            "password",
            "credit_card",
            "card_number",
            "cvv",
            "ssn",
            "passport",
            "id_number",
            "api_key",
            "secret",
        ]
        all_sensitive = set(default_sensitive + sensitive_keys)

        def _redact_value(key: str, value: Any) -> Any:
            # Check if key is sensitive
            if any(s in key.lower() for s in all_sensitive):
                if isinstance(value, str):
                    return self.redact_char * len(value)
                else:
                    return f"<REDACTED_{key.upper()}>"

            # Recursively handle nested structures
            if isinstance(value, dict):
                return self.redact_dict(value, sensitive_keys)
            elif isinstance(value, list):
                return [_redact_value(key, item) for item in value]
            elif isinstance(value, str):
                return self.redact_text(value)
            else:
                return value

        return {k: _redact_value(k, v) for k, v in data.items()}

    def redact_log_record(self, record: logging.LogRecord) -> logging.LogRecord:
        """
        Redact PII from log record

        Args:
            record: Log record to redact

        Returns:
            Redacted log record
        """
        # Redact the main message
        if hasattr(record, "msg"):
            record.msg = self.redact_text(str(record.msg))

        # Redact any args
        if hasattr(record, "args") and record.args:
            if isinstance(record.args, dict):
                record.args = self.redact_dict(record.args)
            else:
                record.args = tuple(self.redact_text(str(arg)) for arg in record.args)

        return record

    def _apply_redaction(self, text: str, start: int, end: int) -> str:
        """Apply redaction to a specific range in text"""
        # Keep first and last char for context (e.g., j***n@e****l.com)
        if end - start > 2:
            return (
                text[: start + 1]
                + self.redact_char * (end - start - 2)
                + text[end - 1 :]
            )
        else:
            return text[:start] + self.redact_char * (end - start) + text[end:]

    def _fallback_redact(self, text: str) -> str:
        """Fallback PII redaction using regex patterns"""
        patterns = {
            # Email addresses
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b": "<EMAIL>",
            # Phone numbers (various formats)
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b": "<PHONE>",
            r"\b\+?[0-9]{1,3}[-.\s]?[0-9]{1,4}[-.\s]?[0-9]{1,4}[-.\s]?[0-9]{1,9}\b": "<PHONE>",
            # Credit card numbers
            r"\b(?:\d[ -]*?){13,19}\b": "<CREDIT_CARD>",
            # IP addresses
            r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b": "<IP_ADDRESS>",
            # Social Security Numbers
            r"\b\d{3}-\d{2}-\d{4}\b": "<SSN>",
        }

        redacted = text
        for pattern, replacement in patterns.items():
            redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)

        return redacted

    def _redact_custom_patterns(self, text: str) -> str:
        """Apply hotel-specific redaction patterns"""
        # Room numbers
        text = re.sub(
            self.ROOM_NUMBER_PATTERN, r"\1 <ROOM_NUMBER>", text, flags=re.IGNORECASE
        )

        # Confirmation numbers
        text = re.sub(
            self.CONFIRMATION_NUMBER_PATTERN,
            r"\1 <CONFIRMATION>",
            text,
            flags=re.IGNORECASE,
        )

        # Guest/Member IDs
        text = re.sub(
            self.GUEST_ID_PATTERN, r"\1 <GUEST_ID>", text, flags=re.IGNORECASE
        )

        return text


class PIIRedactorFilter(logging.Filter):
    """
    Logging filter that automatically redacts PII from all log messages

    Usage:
        logger = logging.getLogger(__name__)
        logger.addFilter(PIIRedactorFilter())
    """

    def __init__(self, redactor: Optional[PIIRedactor] = None):
        super().__init__()
        self.redactor = redactor or PIIRedactor()

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter method called by logging framework"""
        self.redactor.redact_log_record(record)
        return True


# Singleton instance for convenience
_default_redactor = None


def get_default_redactor() -> PIIRedactor:
    """Get or create the default PII redactor instance"""
    global _default_redactor
    if _default_redactor is None:
        _default_redactor = PIIRedactor()
    return _default_redactor


def redact_pii(text: str, language: str = "en") -> str:
    """Convenience function to redact PII from text"""
    return get_default_redactor().redact_text(text, language)


def setup_logging_redaction(logger: Optional[logging.Logger] = None):
    """
    Set up PII redaction for logging

    Args:
        logger: Logger to configure (None for root logger)
    """
    target_logger = logger or logging.getLogger()

    # Check if filter already added
    for filter in target_logger.filters:
        if isinstance(filter, PIIRedactorFilter):
            return

    # Add PII redaction filter
    target_logger.addFilter(PIIRedactorFilter())

    # Also set up for all handlers
    for handler in target_logger.handlers:
        handler.addFilter(PIIRedactorFilter())


# Example usage for testing
if __name__ == "__main__":
    redactor = PIIRedactor()

    # Test cases
    test_cases = [
        "Guest John Doe in room 425 has email john.doe@example.com",
        "Confirmation number ABC123XYZ for phone +1-555-123-4567",
        "Credit card ending in 4242, guest ID GOLD12345678",
        "IP address 192.168.1.1 accessed the system",
        {
            "guest": {
                "name": "Jane Smith",
                "email": "jane@hotel.com",
                "phone": "+49 30 12345678",
                "room": "Suite 1012",
                "credit_card": "4111 1111 1111 1111",
            }
        },
    ]

    for test in test_cases:
        if isinstance(test, str):
            print(f"Original: {test}")
            print(f"Redacted: {redactor.redact_text(test)}")
        else:
            print(f"Original: {json.dumps(test, indent=2)}")
            print(f"Redacted: {json.dumps(redactor.redact_dict(test), indent=2)}")
        print("-" * 50)
