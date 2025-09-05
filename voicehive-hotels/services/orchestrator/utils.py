"""
Utility modules for the orchestrator service.
"""

import re


# PII Redaction utility (moved from app.py to avoid circular imports)
class PIIRedactor:
    def __init__(self):
        # In production, patterns would be loaded from GDPR config
        self.patterns = {
            "high_sensitivity": ["credit_card", "ssn", "passport"],
            "medium_sensitivity": ["email", "phone", "address"], 
            "low_sensitivity": ["name", "date_of_birth"]
        }
        
    def redact(self, text: str, category: str = "medium") -> str:
        """Redact PII from text based on sensitivity category"""
        # This is a simplified version - in production, use Presidio
        redacted = text
        categories = self.patterns.get(f"{category}_sensitivity", [])
        
        for pattern in categories:
            if pattern == "credit_card":
                # Simple credit card pattern
                redacted = re.sub(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '****', redacted)
            elif pattern == "email":
                redacted = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '***@***.**', redacted)
            # Add more patterns as needed
            
        # Track redactions in metrics if counter is available
        try:
            from services.orchestrator.metrics import pii_redactions_total
            pii_redactions_total.labels(category=category).inc()
        except ImportError:
            pass  # Metrics not available during testing
            
        return redacted
