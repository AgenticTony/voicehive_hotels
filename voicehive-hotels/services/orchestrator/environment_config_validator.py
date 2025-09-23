"""
Environment-Specific Configuration Validation System
Validates configuration against environment-specific security and compliance requirements
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
from pydantic import ValidationError
from prometheus_client import Counter, Gauge

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger
from config import VoiceHiveConfig, EnvironmentType, RegionType

logger = get_safe_logger("orchestrator.env_config_validator")
audit_logger = AuditLogger("env_config_validation")

# Metrics
config_validations = Counter('voicehive_config_validations_total', 'Configuration validations performed', ['environment', 'status'])
config_violations = Counter('voicehive_config_violations_total', 'Configuration violations detected', ['environment', 'rule', 'severity'])
config_compliance_score = Gauge('voicehive_config_compliance_score', 'Configuration compliance score (0-100)', ['environment'])


class ValidationSeverity(str, Enum):
    """Configuration validation severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ComplianceFramework(str, Enum):
    """Supported compliance frameworks"""
    GDPR = "gdpr"
    SOC2 = "soc2"
    ISO27001 = "iso27001"
    PCI_DSS = "pci_dss"
    HIPAA = "hipaa"


@dataclass
class ValidationRule:
    """Configuration validation rule"""
    
    rule_id: str
    name: str
    description: str
    severity: ValidationSeverity
    compliance_frameworks: List[ComplianceFramework]
    environments: List[EnvironmentType]
    field_path: str
    validation_function: str  # Name of validation function
    expected_value: Optional[Any] = None
    allowed_values: Optional[List[Any]] = None
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    pattern: Optional[str] = None
    custom_validator: Optional[str] = None
    
    def applies_to_environment(self, environment: EnvironmentType) -> bool:
        """Check if rule applies to the given environment"""
        return environment in self.environments or EnvironmentType.PRODUCTION in self.environments


@dataclass
class ValidationViolation:
    """Configuration validation violation"""
    
    rule_id: str
    rule_name: str
    field_path: str
    severity: ValidationSeverity
    message: str
    current_value: Any
    expected_value: Optional[Any] = None
    compliance_frameworks: List[ComplianceFramework] = None
    remediation_guidance: str = ""
    
    def __post_init__(self):
        if self.compliance_frameworks is None:
            self.compliance_frameworks = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'rule_id': self.rule_id,
            'rule_name': self.rule_name,
            'field_path': self.field_path,
            'severity': self.severity.value,
            'message': self.message,
            'current_value': self._redact_sensitive(self.current_value),
            'expected_value': self._redact_sensitive(self.expected_value),
            'compliance_frameworks': [f.value for f in self.compliance_frameworks],
            'remediation_guidance': self.remediation_guidance
        }
    
    def _redact_sensitive(self, value: Any) -> str:
        """Redact sensitive values for logging"""
        if isinstance(value, str) and len(value) > 8:
            sensitive_keywords = ['password', 'secret', 'key', 'token']
            if any(keyword in self.field_path.lower() for keyword in sensitive_keywords):
                return f"{value[:4]}***{value[-4:]}"
        return str(value) if value is not None else None


@dataclass
class ValidationReport:
    """Configuration validation report"""
    
    environment: EnvironmentType
    config_hash: str
    validated_at: datetime
    violations: List[ValidationViolation]
    compliance_score: float
    total_rules_checked: int
    
    def get_violations_by_severity(self) -> Dict[ValidationSeverity, List[ValidationViolation]]:
        """Group violations by severity"""
        grouped = {severity: [] for severity in ValidationSeverity}
        
        for violation in self.violations:
            grouped[violation.severity].append(violation)
        
        return grouped
    
    def get_violations_by_framework(self) -> Dict[ComplianceFramework, List[ValidationViolation]]:
        """Group violations by compliance framework"""
        grouped = {}
        
        for violation in self.violations:
            for framework in violation.compliance_frameworks:
                if framework not in grouped:
                    grouped[framework] = []
                grouped[framework].append(violation)
        
        return grouped
    
    def is_compliant(self) -> bool:
        """Check if configuration is compliant (no critical or error violations)"""
        for violation in self.violations:
            if violation.severity in [ValidationSeverity.CRITICAL, ValidationSeverity.ERROR]:
                return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'environment': self.environment.value,
            'config_hash': self.config_hash,
            'validated_at': self.validated_at.isoformat(),
            'violations': [v.to_dict() for v in self.violations],
            'compliance_score': self.compliance_score,
            'total_rules_checked': self.total_rules_checked,
            'is_compliant': self.is_compliant(),
            'violations_by_severity': {
                severity.value: len(violations) 
                for severity, violations in self.get_violations_by_severity().items()
            }
        }


class EnvironmentConfigurationValidator:
    """
    Environment-specific configuration validator with compliance framework support
    """
    
    def __init__(self, rules_config_path: Optional[str] = None):
        
        self.rules_config_path = rules_config_path or "/etc/voicehive/validation-rules.json"
        
        # Load validation rules
        self.validation_rules = self._load_validation_rules()
        
        # Validation functions registry
        self.validation_functions = {
            'equals': self._validate_equals,
            'in_list': self._validate_in_list,
            'min_value': self._validate_min_value,
            'max_value': self._validate_max_value,
            'pattern_match': self._validate_pattern_match,
            'ssl_required': self._validate_ssl_required,
            'secure_algorithm': self._validate_secure_algorithm,
            'eu_region_only': self._validate_eu_region_only,
            'no_debug_in_production': self._validate_no_debug_in_production,
            'strong_password': self._validate_strong_password,
            'secure_cors': self._validate_secure_cors,
            'jwt_security': self._validate_jwt_security,
            'session_timeout': self._validate_session_timeout,
            'encryption_required': self._validate_encryption_required
        }
    
    def _load_validation_rules(self) -> List[ValidationRule]:
        """Load validation rules from configuration"""
        
        # Default validation rules
        default_rules = self._get_default_validation_rules()
        
        # Try to load custom rules from file
        if Path(self.rules_config_path).exists():
            try:
                with open(self.rules_config_path, 'r') as f:
                    custom_rules_data = json.load(f)
                
                custom_rules = []
                for rule_data in custom_rules_data.get('rules', []):
                    rule = ValidationRule(
                        rule_id=rule_data['rule_id'],
                        name=rule_data['name'],
                        description=rule_data['description'],
                        severity=ValidationSeverity(rule_data['severity']),
                        compliance_frameworks=[ComplianceFramework(f) for f in rule_data['compliance_frameworks']],
                        environments=[EnvironmentType(e) for e in rule_data['environments']],
                        field_path=rule_data['field_path'],
                        validation_function=rule_data['validation_function'],
                        expected_value=rule_data.get('expected_value'),
                        allowed_values=rule_data.get('allowed_values'),
                        min_value=rule_data.get('min_value'),
                        max_value=rule_data.get('max_value'),
                        pattern=rule_data.get('pattern'),
                        custom_validator=rule_data.get('custom_validator')
                    )
                    custom_rules.append(rule)
                
                logger.info(
                    "loaded_custom_validation_rules",
                    rules_count=len(custom_rules),
                    rules_file=self.rules_config_path
                )
                
                # Merge with default rules
                return default_rules + custom_rules
                
            except Exception as e:
                logger.error(
                    "failed_to_load_custom_validation_rules",
                    rules_file=self.rules_config_path,
                    error=str(e)
                )
        
        return default_rules
    
    def _get_default_validation_rules(self) -> List[ValidationRule]:
        """Get default validation rules"""
        
        return [
            # GDPR Compliance Rules
            ValidationRule(
                rule_id="GDPR_001",
                name="EU Region Requirement",
                description="Data must be processed in EU regions only for GDPR compliance",
                severity=ValidationSeverity.CRITICAL,
                compliance_frameworks=[ComplianceFramework.GDPR],
                environments=[EnvironmentType.PRODUCTION, EnvironmentType.STAGING],
                field_path="region",
                validation_function="eu_region_only"
            ),
            
            ValidationRule(
                rule_id="GDPR_002",
                name="Encryption at Rest Required",
                description="Encryption must be enabled for data at rest",
                severity=ValidationSeverity.CRITICAL,
                compliance_frameworks=[ComplianceFramework.GDPR, ComplianceFramework.ISO27001],
                environments=[EnvironmentType.PRODUCTION],
                field_path="security.encryption_key",
                validation_function="encryption_required"
            ),
            
            # Security Rules
            ValidationRule(
                rule_id="SEC_001",
                name="Database SSL Required",
                description="Database connections must use SSL in production",
                severity=ValidationSeverity.CRITICAL,
                compliance_frameworks=[ComplianceFramework.SOC2, ComplianceFramework.ISO27001],
                environments=[EnvironmentType.PRODUCTION],
                field_path="database.ssl_mode",
                validation_function="ssl_required",
                allowed_values=["require", "verify-ca", "verify-full"]
            ),
            
            ValidationRule(
                rule_id="SEC_002",
                name="Redis SSL Required",
                description="Redis connections must use SSL in production",
                severity=ValidationSeverity.CRITICAL,
                compliance_frameworks=[ComplianceFramework.SOC2, ComplianceFramework.ISO27001],
                environments=[EnvironmentType.PRODUCTION],
                field_path="redis.ssl",
                validation_function="equals",
                expected_value=True
            ),
            
            ValidationRule(
                rule_id="SEC_003",
                name="Secure JWT Algorithm",
                description="JWT must use secure algorithms (RS256, RS384, RS512, ES256, ES384, ES512)",
                severity=ValidationSeverity.CRITICAL,
                compliance_frameworks=[ComplianceFramework.SOC2, ComplianceFramework.ISO27001],
                environments=[EnvironmentType.PRODUCTION, EnvironmentType.STAGING],
                field_path="auth.jwt_algorithm",
                validation_function="secure_algorithm",
                allowed_values=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
            ),
            
            ValidationRule(
                rule_id="SEC_004",
                name="JWT Expiration Limit",
                description="JWT tokens should not expire longer than 30 minutes in production",
                severity=ValidationSeverity.WARNING,
                compliance_frameworks=[ComplianceFramework.SOC2],
                environments=[EnvironmentType.PRODUCTION],
                field_path="auth.jwt_expiration_minutes",
                validation_function="max_value",
                max_value=30
            ),
            
            ValidationRule(
                rule_id="SEC_005",
                name="Strong JWT Secret",
                description="JWT secret key must be at least 32 characters",
                severity=ValidationSeverity.CRITICAL,
                compliance_frameworks=[ComplianceFramework.SOC2, ComplianceFramework.ISO27001],
                environments=[EnvironmentType.PRODUCTION, EnvironmentType.STAGING],
                field_path="auth.jwt_secret_key",
                validation_function="strong_password",
                min_value=32
            ),
            
            ValidationRule(
                rule_id="SEC_006",
                name="Secure CORS Configuration",
                description="CORS should not allow wildcard origins in production",
                severity=ValidationSeverity.ERROR,
                compliance_frameworks=[ComplianceFramework.SOC2],
                environments=[EnvironmentType.PRODUCTION],
                field_path="security.cors_allowed_origins",
                validation_function="secure_cors"
            ),
            
            ValidationRule(
                rule_id="SEC_007",
                name="Session Timeout Limit",
                description="Session timeout should not exceed 2 hours in production",
                severity=ValidationSeverity.WARNING,
                compliance_frameworks=[ComplianceFramework.SOC2],
                environments=[EnvironmentType.PRODUCTION],
                field_path="security.session_timeout_minutes",
                validation_function="max_value",
                max_value=120
            ),
            
            # Operational Security Rules
            ValidationRule(
                rule_id="OPS_001",
                name="No Debug Logging in Production",
                description="Debug logging should not be enabled in production",
                severity=ValidationSeverity.WARNING,
                compliance_frameworks=[ComplianceFramework.SOC2],
                environments=[EnvironmentType.PRODUCTION],
                field_path="log_level",
                validation_function="no_debug_in_production"
            ),
            
            ValidationRule(
                rule_id="OPS_002",
                name="Secure External Service URLs",
                description="External service URLs must use HTTPS/WSS protocols",
                severity=ValidationSeverity.ERROR,
                compliance_frameworks=[ComplianceFramework.SOC2, ComplianceFramework.ISO27001],
                environments=[EnvironmentType.PRODUCTION, EnvironmentType.STAGING],
                field_path="external_services.livekit_url",
                validation_function="pattern_match",
                pattern=r"^(https://|wss://)"
            ),
            
            ValidationRule(
                rule_id="OPS_003",
                name="Vault URL Security",
                description="Vault URL must use HTTPS protocol",
                severity=ValidationSeverity.CRITICAL,
                compliance_frameworks=[ComplianceFramework.SOC2, ComplianceFramework.ISO27001],
                environments=[EnvironmentType.PRODUCTION, EnvironmentType.STAGING],
                field_path="external_services.vault_url",
                validation_function="pattern_match",
                pattern=r"^https://"
            ),
            
            # Database Security Rules
            ValidationRule(
                rule_id="DB_001",
                name="Database Password Strength",
                description="Database password must be at least 12 characters in production",
                severity=ValidationSeverity.ERROR,
                compliance_frameworks=[ComplianceFramework.SOC2, ComplianceFramework.ISO27001],
                environments=[EnvironmentType.PRODUCTION],
                field_path="database.password",
                validation_function="strong_password",
                min_value=12
            ),
            
            ValidationRule(
                rule_id="DB_002",
                name="Redis Password Required",
                description="Redis password must be set in production",
                severity=ValidationSeverity.ERROR,
                compliance_frameworks=[ComplianceFramework.SOC2],
                environments=[EnvironmentType.PRODUCTION],
                field_path="redis.password",
                validation_function="encryption_required"
            ),
            
            # Rate Limiting Rules
            ValidationRule(
                rule_id="RATE_001",
                name="Rate Limiting Configuration",
                description="Rate limiting should be appropriately configured for production",
                severity=ValidationSeverity.WARNING,
                compliance_frameworks=[ComplianceFramework.SOC2],
                environments=[EnvironmentType.PRODUCTION],
                field_path="security.rate_limit_per_minute",
                validation_function="min_value",
                min_value=10
            )
        ]
    
    async def validate_configuration(self, config: VoiceHiveConfig) -> ValidationReport:
        """
        Validate configuration against environment-specific rules
        
        Args:
            config: Configuration to validate
            
        Returns:
            Validation report with violations and compliance score
        """
        
        violations = []
        rules_checked = 0
        
        # Get configuration as dictionary for field path access
        config_dict = config.model_dump()
        
        # Apply validation rules
        for rule in self.validation_rules:
            if not rule.applies_to_environment(config.environment):
                continue
            
            rules_checked += 1
            
            try:
                # Get field value using dot notation
                field_value = self._get_field_value(config_dict, rule.field_path)
                
                # Apply validation function
                validation_func = self.validation_functions.get(rule.validation_function)
                if not validation_func:
                    logger.warning(
                        "unknown_validation_function",
                        rule_id=rule.rule_id,
                        function=rule.validation_function
                    )
                    continue
                
                is_valid, error_message = validation_func(field_value, rule)
                
                if not is_valid:
                    violation = ValidationViolation(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        field_path=rule.field_path,
                        severity=rule.severity,
                        message=error_message,
                        current_value=field_value,
                        expected_value=rule.expected_value,
                        compliance_frameworks=rule.compliance_frameworks,
                        remediation_guidance=self._get_remediation_guidance(rule)
                    )
                    
                    violations.append(violation)
                    
                    # Update metrics
                    config_violations.labels(
                        environment=config.environment.value,
                        rule=rule.rule_id,
                        severity=rule.severity.value
                    ).inc()
                
            except Exception as e:
                logger.error(
                    "validation_rule_execution_failed",
                    rule_id=rule.rule_id,
                    field_path=rule.field_path,
                    error=str(e)
                )
        
        # Calculate compliance score
        compliance_score = self._calculate_compliance_score(violations, rules_checked)
        
        # Create validation report
        report = ValidationReport(
            environment=config.environment,
            config_hash=config.calculate_config_hash(),
            validated_at=datetime.now(timezone.utc),
            violations=violations,
            compliance_score=compliance_score,
            total_rules_checked=rules_checked
        )
        
        # Update metrics
        status = "passed" if report.is_compliant() else "failed"
        config_validations.labels(
            environment=config.environment.value,
            status=status
        ).inc()
        
        config_compliance_score.labels(
            environment=config.environment.value
        ).set(compliance_score)
        
        # Audit log
        severity = "error" if not report.is_compliant() else "info"
        audit_logger.log_security_event(
            event_type="configuration_validation_completed",
            details={
                "environment": config.environment.value,
                "config_hash": config.calculate_config_hash()[:16],
                "violations_count": len(violations),
                "compliance_score": compliance_score,
                "is_compliant": report.is_compliant(),
                "critical_violations": len([v for v in violations if v.severity == ValidationSeverity.CRITICAL]),
                "error_violations": len([v for v in violations if v.severity == ValidationSeverity.ERROR])
            },
            severity=severity
        )
        
        logger.info(
            "configuration_validation_completed",
            environment=config.environment.value,
            violations_count=len(violations),
            compliance_score=compliance_score,
            is_compliant=report.is_compliant()
        )
        
        return report
    
    def _get_field_value(self, config_dict: Dict[str, Any], field_path: str) -> Any:
        """Get field value using dot notation path"""
        
        keys = field_path.split('.')
        value = config_dict
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        
        return value
    
    def _calculate_compliance_score(self, violations: List[ValidationViolation], total_rules: int) -> float:
        """Calculate compliance score based on violations"""
        
        if total_rules == 0:
            return 100.0
        
        # Weight violations by severity
        severity_weights = {
            ValidationSeverity.CRITICAL: 10,
            ValidationSeverity.ERROR: 5,
            ValidationSeverity.WARNING: 2,
            ValidationSeverity.INFO: 1
        }
        
        total_penalty = sum(severity_weights.get(v.severity, 1) for v in violations)
        max_possible_penalty = total_rules * severity_weights[ValidationSeverity.CRITICAL]
        
        if max_possible_penalty == 0:
            return 100.0
        
        score = max(0, 100 - (total_penalty / max_possible_penalty * 100))
        return round(score, 2)
    
    def _get_remediation_guidance(self, rule: ValidationRule) -> str:
        """Get remediation guidance for a validation rule"""
        
        guidance_map = {
            "GDPR_001": "Configure the service to use only EU regions (eu-west-1, eu-central-1, etc.)",
            "GDPR_002": "Ensure encryption_key is properly configured and not empty",
            "SEC_001": "Set database.ssl_mode to 'require', 'verify-ca', or 'verify-full'",
            "SEC_002": "Set redis.ssl to true for production environments",
            "SEC_003": "Use secure JWT algorithms: RS256, RS384, RS512, ES256, ES384, or ES512",
            "SEC_004": "Set auth.jwt_expiration_minutes to 30 or less for production",
            "SEC_005": "Use a JWT secret key with at least 32 characters",
            "SEC_006": "Remove wildcard (*) from security.cors_allowed_origins",
            "SEC_007": "Set security.session_timeout_minutes to 120 or less",
            "OPS_001": "Set log_level to INFO, WARNING, ERROR, or CRITICAL in production",
            "OPS_002": "Use HTTPS or WSS protocol for external_services.livekit_url",
            "OPS_003": "Use HTTPS protocol for external_services.vault_url",
            "DB_001": "Use a database password with at least 12 characters",
            "DB_002": "Configure a password for Redis in production environments",
            "RATE_001": "Set security.rate_limit_per_minute to at least 10"
        }
        
        return guidance_map.get(rule.rule_id, "Review configuration according to security best practices")
    
    # Validation Functions
    
    def _validate_equals(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate that value equals expected value"""
        if value == rule.expected_value:
            return True, ""
        return False, f"Expected '{rule.expected_value}', got '{value}'"
    
    def _validate_in_list(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate that value is in allowed list"""
        if rule.allowed_values and value in rule.allowed_values:
            return True, ""
        return False, f"Value '{value}' not in allowed values: {rule.allowed_values}"
    
    def _validate_min_value(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate minimum value"""
        try:
            if isinstance(value, (int, float)) and value >= rule.min_value:
                return True, ""
            if isinstance(value, str) and len(value) >= rule.min_value:
                return True, ""
        except (TypeError, ValueError):
            pass
        return False, f"Value must be at least {rule.min_value}"
    
    def _validate_max_value(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate maximum value"""
        try:
            if isinstance(value, (int, float)) and value <= rule.max_value:
                return True, ""
            if isinstance(value, str) and len(value) <= rule.max_value:
                return True, ""
        except (TypeError, ValueError):
            pass
        return False, f"Value must be at most {rule.max_value}"
    
    def _validate_pattern_match(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate pattern match"""
        import re
        if isinstance(value, str) and rule.pattern:
            if re.match(rule.pattern, value):
                return True, ""
        return False, f"Value does not match required pattern: {rule.pattern}"
    
    def _validate_ssl_required(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate SSL is required"""
        if rule.allowed_values and value in rule.allowed_values:
            return True, ""
        return False, f"SSL must be enabled. Use one of: {rule.allowed_values}"
    
    def _validate_secure_algorithm(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate secure algorithm"""
        if rule.allowed_values and value in rule.allowed_values:
            return True, ""
        return False, f"Use secure algorithm. Allowed: {rule.allowed_values}"
    
    def _validate_eu_region_only(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate EU region only"""
        eu_regions = [r.value for r in RegionType]
        if value in eu_regions:
            return True, ""
        return False, f"Must use EU region. Allowed: {eu_regions}"
    
    def _validate_no_debug_in_production(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate no debug logging in production"""
        if isinstance(value, str) and value.upper() != "DEBUG":
            return True, ""
        return False, "Debug logging not allowed in production"
    
    def _validate_strong_password(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate strong password"""
        if not isinstance(value, str):
            return False, "Password must be a string"
        
        min_length = rule.min_value or 8
        if len(value) < min_length:
            return False, f"Password must be at least {min_length} characters"
        
        # Check for weak passwords
        weak_passwords = ['password', '123456', 'admin', 'secret', 'default']
        if value.lower() in weak_passwords:
            return False, "Password is too weak"
        
        return True, ""
    
    def _validate_secure_cors(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate secure CORS configuration"""
        if isinstance(value, list):
            if '*' in value:
                return False, "Wildcard CORS origins not allowed in production"
            return True, ""
        return False, "CORS origins must be a list"
    
    def _validate_jwt_security(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate JWT security settings"""
        # This would implement JWT-specific security checks
        return True, ""
    
    def _validate_session_timeout(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate session timeout"""
        if isinstance(value, (int, float)) and value <= rule.max_value:
            return True, ""
        return False, f"Session timeout must be at most {rule.max_value} minutes"
    
    def _validate_encryption_required(self, value: Any, rule: ValidationRule) -> Tuple[bool, str]:
        """Validate encryption is required"""
        if value is None or (isinstance(value, str) and len(value.strip()) == 0):
            return False, "Encryption key/password is required"
        return True, ""


# Global environment configuration validator instance
env_config_validator = EnvironmentConfigurationValidator()


async def validate_environment_config(config: VoiceHiveConfig) -> ValidationReport:
    """Validate configuration against environment-specific rules"""
    return await env_config_validator.validate_configuration(config)


def get_validation_rules_for_environment(environment: EnvironmentType) -> List[ValidationRule]:
    """Get validation rules applicable to an environment"""
    return [rule for rule in env_config_validator.validation_rules 
            if rule.applies_to_environment(environment)]


def get_compliance_requirements(framework: ComplianceFramework) -> List[ValidationRule]:
    """Get validation rules for a specific compliance framework"""
    return [rule for rule in env_config_validator.validation_rules 
            if framework in rule.compliance_frameworks]