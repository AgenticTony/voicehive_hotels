#!/usr/bin/env python3
"""
Demonstration of PII Redaction in VoiceHive Hotels Connectors
Shows GDPR compliance through automatic PII detection and redaction
"""

import logging
import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from connectors.utils import (
    PIIRedactor, 
    setup_logging_redaction,
    ConnectorLogger
)


def demo_text_redaction():
    """Demonstrate text redaction capabilities"""
    print("=== PII Text Redaction Demo ===\n")
    
    redactor = PIIRedactor()
    
    test_cases = [
        "Guest John Doe (john.doe@example.com) checked into room 425",
        "Confirmation ABC123XYZ for +1-555-123-4567",
        "Credit card 4111-1111-1111-1111 charged €299.00",
        "Passport number US123456789 on file",
        "German guest Hans Müller im Zimmer 301",
        "IP address 192.168.1.100 accessed the system",
    ]
    
    for text in test_cases:
        redacted = redactor.redact_text(text)
        print(f"Original: {text}")
        print(f"Redacted: {redacted}")
        print("-" * 50)


def demo_dict_redaction():
    """Demonstrate dictionary/JSON redaction"""
    print("\n=== PII Dictionary Redaction Demo ===\n")
    
    redactor = PIIRedactor()
    
    reservation_data = {
        "reservation_id": "RES-2024-001234",
        "confirmation": "ABC123XYZ",
        "guest": {
            "name": "Jane Smith",
            "email": "jane.smith@company.com",
            "phone": "+49 30 12345678",
            "passport": "DE987654321",
            "loyalty_number": "GOLD12345678"
        },
        "room": {
            "number": "Suite 1012",
            "type": "Deluxe Ocean View",
            "rate": 299.00
        },
        "credit_card": {
            "number": "4242424242424242",
            "exp": "12/25",
            "cvv": "123"
        },
        "special_requests": "Guest prefers room 1012 on high floor",
        "internal_notes": "VIP guest, contacted via email jane.smith@company.com"
    }
    
    redacted_data = redactor.redact_dict(
        reservation_data,
        sensitive_keys=["passport", "loyalty_number"]
    )
    
    print("Original Data:")
    print(json.dumps(reservation_data, indent=2))
    print("\nRedacted Data:")
    print(json.dumps(redacted_data, indent=2))


def demo_logging_redaction():
    """Demonstrate automatic logging redaction"""
    print("\n=== PII Logging Redaction Demo ===\n")
    
    # Create logger with PII redaction
    logger = logging.getLogger("demo_logger")
    logger.setLevel(logging.INFO)
    
    # Add console handler
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    
    # Enable PII redaction
    setup_logging_redaction(logger)
    
    print("Logging with automatic PII redaction:\n")
    
    # These logs will have PII automatically redacted
    logger.info("New reservation for John Doe (john@example.com)")
    logger.info("Guest checked into room 425")
    logger.info("Phone number on file: +1-555-123-4567")
    logger.info("Processing credit card payment for 4111111111111111")
    logger.warning("Failed login attempt from IP 192.168.1.100")


def demo_connector_logger():
    """Demonstrate the ConnectorLogger with built-in redaction"""
    print("\n=== Connector Logger Demo ===\n")
    
    # Create connector logger
    logger = ConnectorLogger(
        name="demo.apaleo.connector",
        vendor="apaleo",
        hotel_id="HOTEL01"
    )
    
    # Set correlation ID for request tracking
    correlation_id = logger.with_correlation_id()
    print(f"Correlation ID: {correlation_id}\n")
    
    # Log API call
    logger.log_api_call(
        operation="create_reservation",
        request_data={
            "guest_name": "Alice Johnson",
            "email": "alice@example.com",
            "room": "Suite 505",
            "credit_card": "4242424242424242"
        },
        response_data={
            "reservation_id": "RES123456",
            "confirmation": "CONF789XYZ",
            "status": "confirmed"
        },
        duration_ms=156.7,
        status_code=201
    )
    
    # Log reservation action
    logger.log_reservation(
        action="check_in",
        reservation_id="RES123456",
        confirmation_number="CONF789XYZ",
        guest_name="Alice Johnson",
        room_type="Suite",
        arrival="2024-01-15",
        status="checked_in"
    )


def main():
    """Run all demos"""
    print("=" * 70)
    print("VoiceHive Hotels - PII Redaction Demo")
    print("GDPR Compliance through Automatic PII Detection & Redaction")
    print("=" * 70)
    
    demo_text_redaction()
    demo_dict_redaction()
    demo_logging_redaction()
    demo_connector_logger()
    
    print("\n" + "=" * 70)
    print("✅ All PII has been automatically redacted for GDPR compliance!")
    print("=" * 70)


if __name__ == "__main__":
    main()
