"""
PII Redactor module for GDPR compliance.
Simplified version for test compatibility.
"""

import re
from typing import Dict, List, Any


class PIIRedactor:
    """Redact PII from text based on sensitivity category"""
    
    def __init__(self, patterns: Dict[str, List[str]] = None):
        """Initialize with optional custom patterns"""
        self.patterns = patterns or self._default_patterns()
        
    def _default_patterns(self) -> Dict[str, List[str]]:
        """Default PII patterns by category"""
        return {
            "high_sensitivity": ["credit_card", "ssn", "passport"],
            "medium_sensitivity": ["email", "phone", "address"],
            "low_sensitivity": ["name", "date_of_birth"]
        }
    
    def redact(self, text: str, category: str = "medium") -> str:
        """
        Redact PII from text based on sensitivity category.
        
        Args:
            text: Text to redact
            category: Sensitivity level (high, medium, low)
            
        Returns:
            Redacted text
        """
        if not text:
            return text
            
        redacted = text
        category_key = f"{category}_sensitivity"
        patterns = self.patterns.get(category_key, [])
        
        for pattern_type in patterns:
            if pattern_type == "credit_card":
                # Simple credit card pattern (4 groups of 4 digits)
                redacted = re.sub(
                    r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b',
                    '[CREDIT_CARD_REDACTED]',
                    redacted
                )
            elif pattern_type == "email":
                # Email pattern
                redacted = re.sub(
                    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                    '[EMAIL_REDACTED]',
                    redacted
                )
            elif pattern_type == "phone":
                # Phone number patterns (various formats)
                redacted = re.sub(
                    r'(\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}',
                    '[PHONE_REDACTED]',
                    redacted
                )
            elif pattern_type == "ssn":
                # SSN pattern (XXX-XX-XXXX)
                redacted = re.sub(
                    r'\b\d{3}-\d{2}-\d{4}\b',
                    '[SSN_REDACTED]',
                    redacted
                )
        
        return redacted
    
    def redact_dict(self, data: Dict[str, Any], category: str = "medium") -> Dict[str, Any]:
        """Redact PII from dictionary values recursively"""
        if not isinstance(data, dict):
            return data
            
        redacted_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                redacted_data[key] = self.redact(value, category)
            elif isinstance(value, dict):
                redacted_data[key] = self.redact_dict(value, category)
            elif isinstance(value, list):
                redacted_data[key] = [
                    self.redact(item, category) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                redacted_data[key] = value
                
        return redacted_data
