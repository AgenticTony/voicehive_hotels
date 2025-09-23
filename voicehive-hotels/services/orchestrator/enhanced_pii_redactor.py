"""
Enhanced PII Redaction System for VoiceHive Hotels
Extends the existing PII redactor with configurable rules and advanced features
"""

import re
import json
import yaml
from typing import Dict, List, Any, Optional, Set, Callable, Pattern
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.enhanced_pii")


class RedactionLevel(str, Enum):
    """Levels of PII redaction"""
    NONE = "none"           # No redaction
    PARTIAL = "partial"     # Partial redaction (e.g., j***n@e***l.com)
    FULL = "full"          # Full redaction (e.g., <EMAIL>)
    HASH = "hash"          # Hash the value (e.g., sha256:abc123...)
    REMOVE = "remove"      # Remove the field entirely


class PIICategory(str, Enum):
    """Categories of PII data"""
    IDENTITY = "identity"           # Names, IDs
    CONTACT = "contact"            # Email, phone, address
    FINANCIAL = "financial"        # Credit cards, bank accounts
    BIOMETRIC = "biometric"        # Fingerprints, photos
    LOCATION = "location"          # GPS, addresses
    BEHAVIORAL = "behavioral"      # Browsing history, preferences
    HEALTH = "health"             # Medical information
    HOTEL_SPECIFIC = "hotel"      # Room numbers, confirmation codes


@dataclass
class RedactionRule:
    """Configuration for a specific PII redaction rule"""
    
    name: str
    category: PIICategory
    pattern: str                    # Regex pattern
    redaction_level: RedactionLevel
    replacement: Optional[str] = None  # Custom replacement text
    confidence_threshold: float = 0.8  # Confidence threshold for ML detection
    enabled: bool = True
    description: str = ""
    
    # Compiled pattern (set after initialization)
    compiled_pattern: Optional[Pattern] = field(init=False, default=None)
    
    def __post_init__(self):
        """Compile regex pattern after initialization"""
        try:
            self.compiled_pattern = re.compile(self.pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as e:
            logger.error(f"Invalid regex pattern in rule '{self.name}': {e}")
            self.enabled = False


@dataclass
class RedactionConfig:
    """Configuration for PII redaction system"""
    
    # Global settings
    default_redaction_level: RedactionLevel = RedactionLevel.PARTIAL
    enable_ml_detection: bool = True
    enable_context_analysis: bool = True
    
    # Performance settings
    max_text_length: int = 100000
    cache_size: int = 1000
    
    # Logging settings
    log_redactions: bool = True
    log_level: str = "INFO"
    
    # Environment-specific settings
    environment_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Rules configuration
    rules: List[RedactionRule] = field(default_factory=list)
    
    # Field-specific configurations
    field_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Whitelist patterns (never redact)
    whitelist_patterns: List[str] = field(default_factory=list)
    
    # Context-aware redaction
    context_rules: Dict[str, List[str]] = field(default_factory=dict)


class EnhancedPIIRedactor:
    """Enhanced PII redactor with configurable rules and advanced features"""
    
    def __init__(self, config: Optional[RedactionConfig] = None, config_file: Optional[str] = None):
        self.config = config or self._load_config(config_file)
        self.whitelist_patterns = [
            re.compile(pattern, re.IGNORECASE) 
            for pattern in self.config.whitelist_patterns
        ]
        
        # Initialize cache
        self._cache: Dict[str, str] = {}
        
        # Load ML models if enabled
        if self.config.enable_ml_detection:
            self._init_ml_detection()
        
        # Initialize default rules if none provided
        if not self.config.rules:
            self._init_default_rules()
    
    def redact_text(self, text: str, context: Optional[str] = None) -> str:
        """
        Redact PII from text with configurable rules
        
        Args:
            text: Text to redact
            context: Context information for context-aware redaction
            
        Returns:
            Redacted text
        """
        if not text or len(text) > self.config.max_text_length:
            return text
        
        # Check cache
        cache_key = f"{hash(text)}:{context or 'default'}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Check whitelist first
        if self._is_whitelisted(text):
            return text
        
        redacted_text = text
        redactions_applied = []
        
        # Apply each enabled rule
        for rule in self.config.rules:
            if not rule.enabled or not rule.compiled_pattern:
                continue
            
            # Check context-specific rules
            if context and not self._should_apply_rule_in_context(rule, context):
                continue
            
            # Apply redaction rule
            matches = list(rule.compiled_pattern.finditer(redacted_text))
            if matches:
                for match in reversed(matches):  # Reverse to maintain positions
                    redacted_value = self._apply_redaction(
                        match.group(), rule, match.start(), match.end()
                    )
                    redacted_text = (
                        redacted_text[:match.start()] + 
                        redacted_value + 
                        redacted_text[match.end():]
                    )
                    
                    redactions_applied.append({
                        "rule": rule.name,
                        "category": rule.category.value,
                        "original_length": len(match.group()),
                        "redacted_length": len(redacted_value)
                    })
        
        # Apply ML detection if enabled
        if self.config.enable_ml_detection:
            redacted_text, ml_redactions = self._apply_ml_redaction(redacted_text, context)
            redactions_applied.extend(ml_redactions)
        
        # Log redactions if enabled
        if self.config.log_redactions and redactions_applied:
            logger.info(
                "pii_redactions_applied",
                context=context,
                redactions_count=len(redactions_applied),
                redactions=redactions_applied
            )
        
        # Cache result
        if len(self._cache) < self.config.cache_size:
            self._cache[cache_key] = redacted_text
        
        return redacted_text
    
    def redact_dict(self, data: Dict[str, Any], context: Optional[str] = None) -> Dict[str, Any]:
        """
        Redact PII from dictionary with field-specific configurations
        
        Args:
            data: Dictionary to redact
            context: Context information
            
        Returns:
            Dictionary with redacted values
        """
        if not isinstance(data, dict):
            return data
        
        redacted_data = {}
        
        for key, value in data.items():
            # Check field-specific configuration
            field_config = self.config.field_configs.get(key, {})
            field_redaction_level = field_config.get("redaction_level")
            
            # Handle different value types
            if isinstance(value, str):
                if field_redaction_level == RedactionLevel.REMOVE:
                    continue  # Skip this field entirely
                elif field_redaction_level == RedactionLevel.NONE:
                    redacted_data[key] = value
                else:
                    redacted_data[key] = self.redact_text(value, context or key)
            elif isinstance(value, dict):
                redacted_data[key] = self.redact_dict(value, context)
            elif isinstance(value, list):
                redacted_data[key] = [
                    self.redact_dict(item, context) if isinstance(item, dict)
                    else self.redact_text(str(item), context) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                # For non-string values, apply field-specific rules
                if field_redaction_level == RedactionLevel.REMOVE:
                    continue
                elif field_redaction_level in [RedactionLevel.FULL, RedactionLevel.HASH]:
                    redacted_data[key] = self._apply_field_redaction(value, field_redaction_level)
                else:
                    redacted_data[key] = value
        
        return redacted_data
    
    def add_custom_rule(self, rule: RedactionRule):
        """Add a custom redaction rule"""
        self.config.rules.append(rule)
        logger.info(f"Added custom PII redaction rule: {rule.name}")
    
    def update_field_config(self, field_name: str, config: Dict[str, Any]):
        """Update configuration for a specific field"""
        self.config.field_configs[field_name] = config
        logger.info(f"Updated field configuration for: {field_name}")
    
    def get_redaction_stats(self) -> Dict[str, Any]:
        """Get statistics about redactions performed"""
        return {
            "cache_size": len(self._cache),
            "rules_count": len(self.config.rules),
            "enabled_rules": len([r for r in self.config.rules if r.enabled]),
            "field_configs": len(self.config.field_configs),
            "whitelist_patterns": len(self.whitelist_patterns)
        }
    
    def _load_config(self, config_file: Optional[str] = None) -> RedactionConfig:
        """Load configuration from file or create default"""
        
        if config_file and Path(config_file).exists():
            try:
                with open(config_file, 'r') as f:
                    if config_file.endswith('.yaml') or config_file.endswith('.yml'):
                        config_data = yaml.safe_load(f)
                    else:
                        config_data = json.load(f)
                
                # Convert rules data to RedactionRule objects
                rules = []
                for rule_data in config_data.get('rules', []):
                    rule = RedactionRule(**rule_data)
                    rules.append(rule)
                
                config_data['rules'] = rules
                return RedactionConfig(**config_data)
                
            except Exception as e:
                logger.error(f"Failed to load PII config from {config_file}: {e}")
        
        return RedactionConfig()
    
    def _init_default_rules(self):
        """Initialize default PII redaction rules"""
        
        default_rules = [
            # Email addresses
            RedactionRule(
                name="email_addresses",
                category=PIICategory.CONTACT,
                pattern=r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
                redaction_level=RedactionLevel.PARTIAL,
                description="Email addresses"
            ),
            
            # Phone numbers (international format)
            RedactionRule(
                name="phone_numbers",
                category=PIICategory.CONTACT,
                pattern=r'\b(?:\+?[1-9]\d{0,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{2,8}\b',
                redaction_level=RedactionLevel.PARTIAL,
                description="Phone numbers (international)"
            ),
            
            # Credit card numbers
            RedactionRule(
                name="credit_cards",
                category=PIICategory.FINANCIAL,
                pattern=r'\b(?:\d[ -]*?){13,19}\b',
                redaction_level=RedactionLevel.FULL,
                replacement="<CREDIT_CARD>",
                description="Credit card numbers"
            ),
            
            # Social Security Numbers
            RedactionRule(
                name="ssn",
                category=PIICategory.IDENTITY,
                pattern=r'\b\d{3}-\d{2}-\d{4}\b',
                redaction_level=RedactionLevel.FULL,
                replacement="<SSN>",
                description="Social Security Numbers"
            ),
            
            # IP Addresses
            RedactionRule(
                name="ip_addresses",
                category=PIICategory.LOCATION,
                pattern=r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',
                redaction_level=RedactionLevel.PARTIAL,
                description="IP addresses"
            ),
            
            # Hotel room numbers
            RedactionRule(
                name="room_numbers",
                category=PIICategory.HOTEL_SPECIFIC,
                pattern=r'\b(?:room|suite|rm)\s*#?\s*(\d{1,4}[A-Za-z]?)\b',
                redaction_level=RedactionLevel.PARTIAL,
                description="Hotel room numbers"
            ),
            
            # Confirmation numbers
            RedactionRule(
                name="confirmation_numbers",
                category=PIICategory.HOTEL_SPECIFIC,
                pattern=r'\b(?:confirmation|conf|booking|res)\s*#?\s*([A-Z0-9]{6,12})\b',
                redaction_level=RedactionLevel.PARTIAL,
                description="Booking confirmation numbers"
            ),
            
            # Names (basic pattern - would be enhanced with ML)
            RedactionRule(
                name="person_names",
                category=PIICategory.IDENTITY,
                pattern=r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',
                redaction_level=RedactionLevel.PARTIAL,
                description="Person names (basic pattern)"
            ),
            
            # Passport numbers (basic pattern)
            RedactionRule(
                name="passport_numbers",
                category=PIICategory.IDENTITY,
                pattern=r'\b[A-Z]{2}\d{6,9}\b',
                redaction_level=RedactionLevel.FULL,
                replacement="<PASSPORT>",
                description="Passport numbers"
            ),
        ]
        
        self.config.rules.extend(default_rules)
    
    def _init_ml_detection(self):
        """Initialize ML-based PII detection (placeholder for actual ML integration)"""
        # This would integrate with libraries like spaCy, transformers, or Presidio
        # For now, we'll use a placeholder
        logger.info("ML-based PII detection initialized (placeholder)")
    
    def _is_whitelisted(self, text: str) -> bool:
        """Check if text matches any whitelist pattern"""
        for pattern in self.whitelist_patterns:
            if pattern.search(text):
                return True
        return False
    
    def _should_apply_rule_in_context(self, rule: RedactionRule, context: str) -> bool:
        """Check if rule should be applied in given context"""
        context_rules = self.config.context_rules.get(context, [])
        
        # If no context rules defined, apply all rules
        if not context_rules:
            return True
        
        # Check if rule is allowed in this context
        return rule.name in context_rules or rule.category.value in context_rules
    
    def _apply_redaction(self, text: str, rule: RedactionRule, start: int, end: int) -> str:
        """Apply redaction based on rule configuration"""
        
        if rule.redaction_level == RedactionLevel.NONE:
            return text
        
        elif rule.redaction_level == RedactionLevel.FULL:
            return rule.replacement or f"<{rule.category.value.upper()}>"
        
        elif rule.redaction_level == RedactionLevel.PARTIAL:
            if len(text) <= 2:
                return "▓" * len(text)
            elif len(text) <= 4:
                return text[0] + "▓" * (len(text) - 2) + text[-1]
            else:
                # Keep first and last character, redact middle
                middle_length = len(text) - 2
                return text[0] + "▓" * middle_length + text[-1]
        
        elif rule.redaction_level == RedactionLevel.HASH:
            import hashlib
            hash_value = hashlib.sha256(text.encode()).hexdigest()[:8]
            return f"<HASH:{hash_value}>"
        
        elif rule.redaction_level == RedactionLevel.REMOVE:
            return ""
        
        return text
    
    def _apply_ml_redaction(self, text: str, context: Optional[str] = None) -> tuple[str, List[Dict]]:
        """Apply ML-based PII detection and redaction (placeholder)"""
        # This would use actual ML models for PII detection
        # For now, return unchanged text with empty redactions list
        return text, []
    
    def _apply_field_redaction(self, value: Any, redaction_level: RedactionLevel) -> Any:
        """Apply redaction to non-string field values"""
        
        if redaction_level == RedactionLevel.FULL:
            return f"<REDACTED_{type(value).__name__.upper()}>"
        elif redaction_level == RedactionLevel.HASH:
            import hashlib
            hash_value = hashlib.sha256(str(value).encode()).hexdigest()[:8]
            return f"<HASH:{hash_value}>"
        else:
            return value


# Configuration builder helpers
def create_gdpr_compliant_config() -> RedactionConfig:
    """Create GDPR-compliant PII redaction configuration"""
    
    config = RedactionConfig(
        default_redaction_level=RedactionLevel.FULL,
        enable_ml_detection=True,
        enable_context_analysis=True,
        log_redactions=True
    )
    
    # GDPR-specific field configurations
    config.field_configs = {
        # Personal identifiers - full redaction
        "email": {"redaction_level": RedactionLevel.FULL},
        "phone": {"redaction_level": RedactionLevel.FULL},
        "ssn": {"redaction_level": RedactionLevel.FULL},
        "passport": {"redaction_level": RedactionLevel.FULL},
        "id_number": {"redaction_level": RedactionLevel.FULL},
        
        # Financial data - full redaction
        "credit_card": {"redaction_level": RedactionLevel.FULL},
        "bank_account": {"redaction_level": RedactionLevel.FULL},
        "payment_info": {"redaction_level": RedactionLevel.FULL},
        
        # Sensitive personal data - remove entirely
        "biometric_data": {"redaction_level": RedactionLevel.REMOVE},
        "health_data": {"redaction_level": RedactionLevel.REMOVE},
        "political_opinion": {"redaction_level": RedactionLevel.REMOVE},
        
        # Business data - partial redaction
        "room_number": {"redaction_level": RedactionLevel.PARTIAL},
        "confirmation_code": {"redaction_level": RedactionLevel.PARTIAL},
        
        # Technical data - hash
        "ip_address": {"redaction_level": RedactionLevel.HASH},
        "session_id": {"redaction_level": RedactionLevel.HASH},
    }
    
    # Context-specific rules
    config.context_rules = {
        "audit_log": ["email", "phone", "ip_addresses", "confirmation_numbers"],
        "error_log": ["ip_addresses", "session_id"],
        "business_log": ["room_numbers", "confirmation_numbers"],
        "security_log": ["ip_addresses", "person_names", "email"]
    }
    
    return config


# Example usage
if __name__ == "__main__":
    # Test enhanced PII redactor
    config = create_gdpr_compliant_config()
    redactor = EnhancedPIIRedactor(config)
    
    # Test cases
    test_cases = [
        "Guest John Doe (john.doe@example.com) in room 425",
        "Credit card 4111-1111-1111-1111 for confirmation ABC123XYZ",
        "Phone +1-555-123-4567, IP 192.168.1.1",
        {
            "guest_email": "jane@hotel.com",
            "room_number": "Suite 1012",
            "credit_card": "4242424242424242",
            "ip_address": "10.0.0.1"
        }
    ]
    
    for i, test in enumerate(test_cases):
        print(f"\nTest {i+1}:")
        if isinstance(test, str):
            print(f"Original: {test}")
            print(f"Redacted: {redactor.redact_text(test)}")
        else:
            print(f"Original: {json.dumps(test, indent=2)}")
            print(f"Redacted: {json.dumps(redactor.redact_dict(test), indent=2)}")
    
    print(f"\nRedaction stats: {redactor.get_redaction_stats()}")