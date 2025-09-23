# Secure Configuration Management System

This document describes the new secure configuration management system implemented for VoiceHive Hotels Orchestrator.

## Overview

The secure configuration management system provides:

- **Strict validation** with schema enforcement
- **Configuration drift detection** and alerting
- **Immutable configuration** management with versioning
- **Environment-specific validation** for compliance
- **Configuration change approval** workflow
- **Audit logging** for all configuration changes
- **No production fallback** configurations for security

## Key Features

### 1. Strict Configuration Validation

All configuration must be explicitly provided via environment variables. No fallback values are allowed in production.

```python
from config import get_config, load_config

# Load configuration with strict validation
config = load_config()

# Access configuration values
database_host = config.database.host
redis_url = f"redis://{config.redis.host}:{config.redis.port}"
```

### 2. Environment Variables

Configuration is loaded from environment variables with the `VOICEHIVE_` prefix:

```bash
# Core configuration
export VOICEHIVE_SERVICE_NAME="voicehive-orchestrator"
export VOICEHIVE_ENVIRONMENT="production"
export VOICEHIVE_REGION="eu-west-1"

# Database configuration
export VOICEHIVE_DATABASE__HOST="prod-db.voicehive.internal"
export VOICEHIVE_DATABASE__PORT="5432"
export VOICEHIVE_DATABASE__DATABASE="voicehive_production"
export VOICEHIVE_DATABASE__USERNAME="app_user"
export VOICEHIVE_DATABASE__PASSWORD="secure_password_from_vault"
export VOICEHIVE_DATABASE__SSL_MODE="require"

# Redis configuration
export VOICEHIVE_REDIS__HOST="prod-redis.voicehive.internal"
export VOICEHIVE_REDIS__PORT="6379"
export VOICEHIVE_REDIS__PASSWORD="secure_redis_password"
export VOICEHIVE_REDIS__SSL="true"

# Authentication configuration
export VOICEHIVE_AUTH__JWT_SECRET_KEY="cryptographically_secure_jwt_secret_key"
export VOICEHIVE_AUTH__JWT_ALGORITHM="RS256"
export VOICEHIVE_AUTH__JWT_EXPIRATION_MINUTES="15"

# Security configuration
export VOICEHIVE_SECURITY__ENCRYPTION_KEY="secure_encryption_key_32_chars_min"
export VOICEHIVE_SECURITY__WEBHOOK_SIGNATURE_SECRET="webhook_signature_secret"
export VOICEHIVE_SECURITY__CORS_ALLOWED_ORIGINS='["https://app.voicehive-hotels.eu"]'

# External services
export VOICEHIVE_EXTERNAL_SERVICES__LIVEKIT_URL="wss://livekit.voicehive-hotels.eu"
export VOICEHIVE_EXTERNAL_SERVICES__VAULT_URL="https://vault.voicehive-hotels.eu"
```

### 3. Configuration Drift Detection

The system automatically monitors for configuration changes and detects unauthorized modifications:

```python
from config_drift_monitor import initialize_drift_monitoring, start_drift_monitoring

# Initialize drift monitoring
await initialize_drift_monitoring(
    environment="production",
    config=config,
    approved_by="system_admin"
)

# Start continuous monitoring
await start_drift_monitoring()
```

### 4. Configuration Approval Workflow

All configuration changes require approval:

```python
from config_approval_workflow import (
    create_config_change_request, approve_config_change,
    ApproverRole, ConfigurationChange
)

# Create approval request
changes = [
    ConfigurationChange(
        field_path="auth.jwt_expiration_minutes",
        old_value=15,
        new_value=30,
        change_type="modify",
        justification="Improve user experience",
        impact_assessment="Low impact change",
        rollback_plan="Revert to 15 minutes if issues"
    )
]

request = await create_config_change_request(
    environment=EnvironmentType.PRODUCTION,
    requester="developer",
    requester_role="developer",
    changes=changes,
    justification="Improve UX",
    impact_assessment="Low impact",
    rollback_plan="Simple revert"
)

# Approve the request
await approve_config_change(
    request_id=request.request_id,
    approver="security_admin",
    approver_role=ApproverRole.SECURITY_ADMIN,
    approval_comments="Approved for production"
)
```

### 5. Immutable Configuration Versions

All configuration changes create immutable versions:

```python
from immutable_config_manager import create_config_version, rollback_config

# Create new version
version = await create_config_version(
    config=config,
    created_by="admin_user",
    change_description="Updated JWT expiration",
    tags=["security", "jwt"]
)

# Rollback if needed
rollback = await rollback_config(
    environment=EnvironmentType.PRODUCTION,
    target_version_id=previous_version_id,
    initiated_by="admin_user",
    reason=RollbackReason.SECURITY_INCIDENT,
    rollback_description="Security incident response"
)
```

### 6. Environment-Specific Validation

Configuration is validated against environment-specific rules:

```python
from environment_config_validator import validate_environment_config

# Validate configuration
report = await validate_environment_config(config)

if not report.is_compliant():
    print(f"Configuration compliance failed: {report.compliance_score}%")
    for violation in report.violations:
        print(f"- {violation.rule_name}: {violation.message}")
```

## Security Requirements

### Production Environment

- **SSL/TLS Required**: All database and Redis connections must use SSL
- **Secure JWT Algorithms**: Only RS256, RS384, RS512, ES256, ES384, ES512 allowed
- **Strong Passwords**: Minimum 12 characters for production passwords
- **EU Regions Only**: GDPR compliance requires EU regions only
- **No Debug Logging**: Debug logging disabled in production
- **Secure URLs**: All external service URLs must use HTTPS/WSS
- **No Wildcard CORS**: Wildcard CORS origins not allowed

### Configuration Validation Rules

The system enforces these validation rules:

1. **GDPR_001**: EU Region Requirement (Critical)
2. **GDPR_002**: Encryption at Rest Required (Critical)
3. **SEC_001**: Database SSL Required (Critical)
4. **SEC_002**: Redis SSL Required (Critical)
5. **SEC_003**: Secure JWT Algorithm (Critical)
6. **SEC_004**: JWT Expiration Limit (Warning)
7. **SEC_005**: Strong JWT Secret (Critical)
8. **SEC_006**: Secure CORS Configuration (Error)
9. **OPS_001**: No Debug Logging in Production (Warning)
10. **DB_001**: Database Password Strength (Error)

## Monitoring and Alerting

The system provides comprehensive monitoring:

- **Configuration drift detection** with real-time alerts
- **Compliance score monitoring** with thresholds
- **Configuration change audit logs** for security
- **Integrity verification** for all configuration versions
- **Performance metrics** for configuration operations

## Emergency Procedures

### Emergency Configuration Changes

For critical security incidents:

```python
from config_approval_workflow import emergency_approve_config_change

# Emergency approval (bypasses normal workflow)
await emergency_approve_config_change(
    request_id=request_id,
    emergency_approver="security_admin",
    emergency_role=ApproverRole.EMERGENCY_RESPONDER,
    emergency_justification="Critical security incident response"
)
```

### Configuration Rollback

For immediate rollback:

```python
# Emergency rollback
await rollback_config(
    environment=EnvironmentType.PRODUCTION,
    target_version_id=last_known_good_version,
    initiated_by="incident_commander",
    reason=RollbackReason.EMERGENCY_RESPONSE,
    emergency=True
)
```

## Best Practices

1. **Use Secure Sources**: Load all secrets from HashiCorp Vault or secure key management
2. **Regular Validation**: Run configuration validation regularly
3. **Monitor Drift**: Enable continuous drift monitoring
4. **Document Changes**: Always provide clear justification for changes
5. **Test Changes**: Validate changes in staging before production
6. **Audit Regularly**: Review configuration audit logs regularly
7. **Rotate Secrets**: Implement regular secret rotation
8. **Backup Configurations**: Maintain secure backups of configuration versions

## Troubleshooting

### Configuration Load Failures

```bash
# Check environment variables
env | grep VOICEHIVE_

# Validate configuration manually
python -c "from config import load_config; config = load_config(); print('Config loaded successfully')"
```

### Validation Errors

```python
# Get detailed validation report
from environment_config_validator import validate_environment_config
report = await validate_environment_config(config)
print(report.to_dict())
```

### Drift Detection Issues

```bash
# Check drift monitoring logs
tail -f /var/log/voicehive/config-drift.log

# Verify baseline exists
ls -la /var/lib/voicehive/config-baselines/
```

## Migration from Legacy Configuration

To migrate from the legacy configuration system:

1. **Set Environment Variables**: Configure all required VOICEHIVE\_\* environment variables
2. **Remove Fallbacks**: Ensure no fallback values are used in production
3. **Test Validation**: Run configuration validation tests
4. **Create Baseline**: Create initial configuration baseline
5. **Enable Monitoring**: Start drift monitoring
6. **Update Deployment**: Update deployment scripts to use new configuration

## Compliance and Audit

The secure configuration system ensures:

- **GDPR Compliance**: EU region enforcement and data protection
- **SOC 2 Compliance**: Security controls and audit logging
- **ISO 27001 Compliance**: Information security management
- **Audit Trail**: Complete audit trail for all configuration changes
- **Evidence Collection**: Automated compliance evidence collection

For questions or issues, contact the Security Team or Platform Engineering Team.
