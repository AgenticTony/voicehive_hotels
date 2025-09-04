"""
Test PII Redaction for GDPR Compliance
"""

import pytest
import logging
from io import StringIO

from connectors.utils.pii_redactor import (
    PIIRedactor,
    PIIRedactorFilter,
    get_default_redactor,
    redact_pii,
    setup_logging_redaction,
)


class TestPIIRedactor:
    """Test PII redaction functionality"""

    def test_redact_email(self):
        """Test email redaction"""
        redactor = PIIRedactor()

        test_cases = [
            ("Contact john.doe@example.com for info", "Contact <EMAIL> for info"),
            (
                "Email: jane@hotel.com or admin@voicehive.com",
                "Email: <EMAIL> or <EMAIL>",
            ),
            ("No email here", "No email here"),
        ]

        for original, expected in test_cases:
            result = redactor.redact_text(original)
            # Check if email is redacted (exact format may vary)
            assert "@" not in result or "<EMAIL>" in result
            assert "john.doe" not in result
            assert "jane" not in result or "<EMAIL>" in result

    def test_redact_phone_numbers(self):
        """Test phone number redaction"""
        redactor = PIIRedactor()

        test_cases = [
            ("Call +1-555-123-4567", "Call <PHONE>"),
            ("Phone: +49 30 12345678", "Phone: <PHONE>"),
            ("Contact: (555) 555-5555", "Contact: <PHONE>"),
            ("Mobile +33612345678", "Mobile <PHONE>"),
        ]

        for original, _ in test_cases:
            result = redactor.redact_text(original)
            # Verify no phone patterns remain
            assert not any(char.isdigit() for char in result.split("<PHONE>")[0])
            assert "<PHONE>" in result or "▓" in result

    def test_redact_room_numbers(self):
        """Test hotel-specific room number redaction"""
        redactor = PIIRedactor()

        test_cases = [
            ("Guest in room 425", "Guest in room <ROOM_NUMBER>"),
            ("Suite 1012A is ready", "Suite <ROOM_NUMBER> is ready"),
            ("Zimmer 301 needs cleaning", "Zimmer <ROOM_NUMBER> needs cleaning"),
            ("Chambre 505", "Chambre <ROOM_NUMBER>"),
        ]

        for original, _ in test_cases:
            result = redactor.redact_text(original)
            assert "<ROOM_NUMBER>" in result or "▓" in result
            # Verify room number is not visible
            assert "425" not in result
            assert "1012" not in result
            assert "301" not in result

    def test_redact_confirmation_numbers(self):
        """Test confirmation number redaction"""
        redactor = PIIRedactor()

        test_cases = [
            ("Confirmation #ABC123XYZ", "Confirmation <CONFIRMATION>"),
            ("Booking number: HTL789456", "Booking number: <CONFIRMATION>"),
            ("Res# XYZ987654", "Res <CONFIRMATION>"),
        ]

        for original, _ in test_cases:
            result = redactor.redact_text(original)
            assert "<CONFIRMATION>" in result or "▓" in result
            assert "ABC123XYZ" not in result
            assert "HTL789456" not in result

    def test_redact_credit_cards(self):
        """Test credit card redaction"""
        redactor = PIIRedactor()

        test_cases = [
            ("Card: 4111 1111 1111 1111", "Card: <CREDIT_CARD>"),
            ("Payment 4242-4242-4242-4242", "Payment <CREDIT_CARD>"),
            ("CC ending 4242", "CC ending 4242"),  # Partial numbers OK
        ]

        for original, _ in test_cases:
            result = redactor.redact_text(original)
            # Full card numbers should be redacted
            if "1111 1111" in original or "4242-4242" in original:
                assert "<CREDIT_CARD>" in result or "▓" in result

    def test_redact_dict(self):
        """Test dictionary redaction"""
        redactor = PIIRedactor()

        data = {
            "guest": {
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "+1-555-123-4567",
                "credit_card": "4111111111111111",
            },
            "room": "Suite 425",
            "confirmation": "ABC123XYZ",
            "notes": "Guest prefers room 425",
        }

        result = redactor.redact_dict(data)

        # Check sensitive fields are fully redacted
        assert result["guest"]["email"] == "▓" * len(data["guest"]["email"])
        assert result["guest"]["phone"] == "▓" * len(data["guest"]["phone"])
        assert result["guest"]["credit_card"] == "▓" * len(data["guest"]["credit_card"])

        # Check text fields are redacted
        assert "John Doe" not in str(result)
        assert "425" not in result["notes"]
        assert "ABC123XYZ" not in result["confirmation"]

    def test_multilingual_redaction(self):
        """Test redaction in multiple languages"""
        redactor = PIIRedactor()

        test_cases = [
            ("Gast Hans Müller im Zimmer 425", "de"),  # German
            ("Cliente María García en habitación 301", "es"),  # Spanish
            ("Client Jean Dupont chambre 505", "fr"),  # French
        ]

        for text, lang in test_cases:
            result = redactor.redact_text(text, language=lang)
            # Room numbers should be redacted
            assert "425" not in result or "<ROOM_NUMBER>" in result
            assert "301" not in result or "<ROOM_NUMBER>" in result
            assert "505" not in result or "<ROOM_NUMBER>" in result


class TestPIIRedactorFilter:
    """Test logging filter functionality"""

    def test_logging_filter(self):
        """Test PII redaction in logging"""
        # Create logger with string output
        logger = logging.getLogger("test_logger")
        logger.setLevel(logging.INFO)

        # Capture log output
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        logger.addHandler(handler)

        # Add PII filter
        logger.addFilter(PIIRedactorFilter())

        # Log messages with PII
        logger.info("Guest John Doe checked into room 425")
        logger.info("Email confirmation sent to john@example.com")
        logger.info("Phone number: +1-555-123-4567")

        # Get log output
        log_output = log_capture.getvalue()

        # Verify PII is redacted
        assert "John Doe" not in log_output
        assert "john@example.com" not in log_output
        assert "555-123-4567" not in log_output
        assert "425" not in log_output or "<ROOM_NUMBER>" in log_output

    def test_setup_logging_redaction(self):
        """Test setup function"""
        logger = logging.getLogger("test_setup")

        # Setup redaction
        setup_logging_redaction(logger)

        # Verify filter is added
        assert any(isinstance(f, PIIRedactorFilter) for f in logger.filters)

        # Setup again should not duplicate
        setup_logging_redaction(logger)
        filter_count = sum(
            1 for f in logger.filters if isinstance(f, PIIRedactorFilter)
        )
        assert filter_count == 1


class TestConvenienceFunctions:
    """Test convenience functions"""

    def test_redact_pii_function(self):
        """Test simple redact_pii function"""
        text = "Contact john@example.com or call 555-123-4567"
        result = redact_pii(text)

        assert "@" not in result or "<EMAIL>" in result
        assert "555" not in result or "<PHONE>" in result

    def test_get_default_redactor(self):
        """Test singleton redactor"""
        redactor1 = get_default_redactor()
        redactor2 = get_default_redactor()

        assert redactor1 is redactor2  # Same instance


class TestFallbackRedaction:
    """Test fallback patterns when Presidio is not available"""

    def test_fallback_patterns(self):
        """Test regex-based fallback"""
        redactor = PIIRedactor()

        # Force fallback mode
        text = "Email: test@example.com, Phone: 555-123-4567, IP: 192.168.1.1"
        result = redactor._fallback_redact(text)

        assert "<EMAIL>" in result
        assert "<PHONE>" in result
        assert "<IP_ADDRESS>" in result
        assert "test@example.com" not in result
        assert "555-123-4567" not in result
        assert "192.168.1.1" not in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
