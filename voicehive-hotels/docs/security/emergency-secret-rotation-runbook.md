# Emergency Secret Rotation Runbook

## Overview

This runbook provides step-by-step procedures for emergency secret rotation in response to security incidents, suspected compromises, or other urgent situations requiring immediate credential changes.

## When to Use Emergency Rotation

### Immediate Rotation Required

- **Confirmed Security Breach**: Evidence of unauthorized access to systems
- **Credential Exposure**: Secrets accidentally committed to public repositories
- **Insider Threat**: Suspected malicious activity by authorized personnel
- **Third-Party Compromise**: Partner or vendor security incident affecting shared credentials
- **Compliance Violation**: Regulatory requirement for immediate credential changes

### Precautionary Rotation

- **Suspicious Activity**: Unusual access patterns or failed authentication attempts
- **Employee Departure**: Immediate termination or resignation of personnel with access
- **System Compromise**: Potential but unconfirmed security incident
- **Audit Findings**: Discovery of weak or non-compliant credentials

## Emergency Contacts

### Primary Response Team

- **Security Team Lead**: +44-XXX-XXXX-XXXX (24/7)
- **DevOps Lead**: +44-XXX-XXXX-XXXX (24/7)
- **CTO**: +44-XXX-XXXX-XXXX
- **Compliance Officer**: +44-XXX-XXXX-XXXX

### Escalation Chain

1. Security Team Lead
2. DevOps Lead
3. CTO
4. CEO (for major incidents)

### External Contacts

- **Vault Support**: HashiCorp Enterprise Support
- **Cloud Provider**: AWS/Azure/GCP Security Team
- **Legal Counsel**: External security law firm

## Pre-Emergency Preparation

### Required Access

Ensure the following personnel have emergency access:

- [ ] Vault root tokens (break-glass access)
- [ ] Cloud provider admin access
- [ ] Database admin credentials
- [ ] Kubernetes cluster admin access
- [ ] Monitoring system access

### Required Tools

- [ ] VoiceHive Secret Scanner
- [ ] Vault CLI tools
- [ ] Kubernetes kubectl
- [ ] Cloud provider CLI tools
- [ ] Secure communication channels (encrypted chat/calls)

## Emergency Rotation Procedures

### Phase 1: Immediate Assessment (0-15 minutes)

#### 1.1 Incident Triage

```bash
# Document incident details
INCIDENT_ID="INC-$(date +%Y%m%d-%H%M%S)"
echo "Incident ID: $INCIDENT_ID"
echo "Reported by: [NAME]"
echo "Time: $(date -u)"
echo "Severity: [CRITICAL/HIGH/MEDIUM]"
echo "Description: [BRIEF DESCRIPTION]"
```

#### 1.2 Identify Affected Secrets

```bash
# List potentially compromised secrets
AFFECTED_SECRETS=(
    "database_password"
    "jwt_secret"
    "api_keys"
    "vault_tokens"
    "cloud_credentials"
)

# Log affected systems
for secret in "${AFFECTED_SECRETS[@]}"; do
    echo "Affected: $secret"
done
```

#### 1.3 Activate Emergency Response

```bash
# Notify emergency response team
./scripts/security/notify-emergency-team.sh "$INCIDENT_ID" "CRITICAL"

# Enable emergency mode
kubectl patch configmap emergency-config \
    -p '{"data":{"emergency_mode":"true","incident_id":"'$INCIDENT_ID'"}}'
```

### Phase 2: Immediate Containment (15-30 minutes)

#### 2.1 Disable Compromised Credentials

```bash
# Disable all API keys immediately
python3 scripts/security/emergency-disable-keys.py \
    --incident-id "$INCIDENT_ID" \
    --disable-all-api-keys

# Revoke Vault tokens
vault auth -method=userpass username=emergency-user
vault token revoke -mode=orphan -prefix=auth/

# Disable database users
python3 scripts/security/emergency-db-lockdown.py \
    --incident-id "$INCIDENT_ID"
```

#### 2.2 Enable Enhanced Monitoring

```bash
# Increase audit logging
kubectl patch configmap audit-config \
    -p '{"data":{"log_level":"DEBUG","audit_all_requests":"true"}}'

# Enable real-time alerting
python3 scripts/monitoring/enable-emergency-alerts.py \
    --incident-id "$INCIDENT_ID"
```

#### 2.3 Isolate Affected Systems

```bash
# Apply emergency network policies
kubectl apply -f infra/k8s/security/emergency-network-isolation.yaml

# Enable WAF strict mode
aws wafv2 update-web-acl \
    --scope CLOUDFRONT \
    --id "$WAF_ACL_ID" \
    --default-action Block={}
```

### Phase 3: Emergency Rotation (30-60 minutes)

#### 3.1 Automated Emergency Rotation

```bash
# Start emergency rotation for all critical secrets
python3 services/orchestrator/emergency_rotation_cli.py \
    --incident-id "$INCIDENT_ID" \
    --rotate-all-critical \
    --force \
    --parallel-limit 5

# Monitor rotation progress
python3 services/orchestrator/rotation_monitor.py \
    --incident-id "$INCIDENT_ID" \
    --watch
```

#### 3.2 Manual Database Rotation

```bash
# Generate new database password
NEW_DB_PASSWORD=$(python3 -c "
import secrets, string
chars = string.ascii_letters + string.digits + '!@#$%^&*'
print(''.join(secrets.choice(chars) for _ in range(32)))
")

# Update database password
psql -h "$DB_HOST" -U postgres -c "
ALTER USER voicehive_app PASSWORD '$NEW_DB_PASSWORD';
"

# Update Vault with new password
vault kv put voicehive/database/credentials \
    username=voicehive_app \
    password="$NEW_DB_PASSWORD"
```

#### 3.3 JWT Secret Rotation

```bash
# Generate new JWT signing key
NEW_JWT_SECRET=$(python3 -c "
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
")

# Update JWT service with dual-key support
kubectl patch secret jwt-secrets \
    -p '{"data":{"new_key":"'$(echo -n "$NEW_JWT_SECRET" | base64)'"}}'

# Restart JWT service with new configuration
kubectl rollout restart deployment/orchestrator
```

#### 3.4 API Key Mass Rotation

```bash
# Rotate all API keys
python3 services/orchestrator/api_key_rotation.py \
    --incident-id "$INCIDENT_ID" \
    --rotate-all \
    --notify-clients \
    --grace-period-hours 1
```

### Phase 4: Verification (60-90 minutes)

#### 4.1 Test New Credentials

```bash
# Test database connectivity
python3 scripts/security/test-db-connection.py \
    --use-new-credentials

# Test API functionality
python3 scripts/security/test-api-endpoints.py \
    --use-new-keys \
    --comprehensive

# Test JWT token generation/validation
python3 scripts/security/test-jwt-functionality.py \
    --test-signing \
    --test-validation
```

#### 4.2 Verify System Health

```bash
# Check all services are healthy
kubectl get pods -A | grep -v Running

# Verify monitoring is functional
curl -s http://prometheus:9090/api/v1/query?query=up | jq '.data.result'

# Check application metrics
python3 scripts/monitoring/health-check.py \
    --post-rotation-verification
```

#### 4.3 Validate Security Controls

```bash
# Verify old credentials are disabled
python3 scripts/security/verify-credential-revocation.py \
    --incident-id "$INCIDENT_ID"

# Test access controls
python3 scripts/security/test-access-controls.py \
    --comprehensive

# Scan for any remaining old credentials
python3 scripts/security/secret-scanner.py \
    --scan-all \
    --check-for-old-secrets
```

### Phase 5: Communication (Throughout)

#### 5.1 Internal Communication

```bash
# Update incident status
python3 scripts/incident/update-status.py \
    --incident-id "$INCIDENT_ID" \
    --status "ROTATION_IN_PROGRESS" \
    --details "Emergency rotation initiated"

# Notify stakeholders
./scripts/communication/notify-stakeholders.sh \
    "$INCIDENT_ID" \
    "Emergency secret rotation in progress"
```

#### 5.2 Client Communication

```bash
# Prepare client notification
cat > /tmp/client_notification.md << EOF
# Emergency Security Update

We are currently performing an emergency security update that requires
rotation of API credentials.

## Action Required:
- Update to new API keys (sent separately)
- Verify connectivity after $(date -d '+2 hours' '+%H:%M UTC')

## Timeline:
- Rotation started: $(date -u)
- Expected completion: $(date -d '+2 hours' -u)
- Old keys disabled: $(date -d '+24 hours' -u)

Contact support@voicehive.com for assistance.
EOF

# Send notifications
python3 scripts/communication/send-client-notifications.py \
    --template /tmp/client_notification.md \
    --incident-id "$INCIDENT_ID"
```

## Post-Emergency Procedures

### Immediate Post-Rotation (0-2 hours)

#### Monitor System Stability

```bash
# Watch for errors
kubectl logs -f deployment/orchestrator | grep -i error

# Monitor authentication failures
python3 scripts/monitoring/auth-failure-monitor.py \
    --incident-id "$INCIDENT_ID" \
    --duration 2h
```

#### Validate Client Connectivity

```bash
# Check client API usage
python3 scripts/monitoring/client-connectivity-check.py \
    --post-rotation \
    --alert-on-failures
```

### 24-Hour Follow-up

#### Disable Old Credentials

```bash
# After grace period, fully disable old credentials
python3 services/orchestrator/cleanup_old_credentials.py \
    --incident-id "$INCIDENT_ID" \
    --confirm-disable-old
```

#### Security Assessment

```bash
# Comprehensive security scan
python3 scripts/security/post-incident-scan.py \
    --incident-id "$INCIDENT_ID" \
    --full-assessment
```

### 7-Day Review

#### Incident Analysis

```bash
# Generate incident report
python3 scripts/incident/generate-report.py \
    --incident-id "$INCIDENT_ID" \
    --include-timeline \
    --include-metrics
```

#### Process Improvement

- Review response time metrics
- Identify automation gaps
- Update procedures based on lessons learned
- Conduct team retrospective

## Emergency Rotation Scripts

### Emergency Disable Script

```bash
#!/bin/bash
# scripts/security/emergency-disable-keys.py

import sys
import argparse
from datetime import datetime, timezone
from services.orchestrator.vault_client import VaultClient
from services.orchestrator.audit_logging import AuditLogger

def emergency_disable_all_keys(incident_id: str):
    """Disable all API keys immediately"""

    vault_client = VaultClient(os.getenv('VAULT_ADDR'))
    audit_logger = AuditLogger("emergency_rotation")

    try:
        # Get all active API keys
        api_keys = vault_client.list_api_keys()

        disabled_count = 0
        for key_data in api_keys:
            if key_data.get('active', False):
                # Disable the key
                vault_client.revoke_api_key(key_data['api_key_id'])
                disabled_count += 1

                # Audit log
                audit_logger.log_security_event(
                    event_type="emergency_key_disabled",
                    details={
                        "incident_id": incident_id,
                        "api_key_id": key_data['api_key_id'],
                        "service_name": key_data.get('service_name'),
                        "disabled_at": datetime.now(timezone.utc).isoformat()
                    },
                    severity="high"
                )

        print(f"Emergency disable completed: {disabled_count} keys disabled")
        return True

    except Exception as e:
        print(f"Emergency disable failed: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--disable-all-api-keys", action="store_true")

    args = parser.parse_args()

    if args.disable_all_api_keys:
        success = emergency_disable_all_keys(args.incident_id)
        sys.exit(0 if success else 1)
```

### Rotation Monitor Script

```bash
#!/bin/bash
# services/orchestrator/rotation_monitor.py

import asyncio
import argparse
from datetime import datetime, timezone
from services.orchestrator.secret_rotation_automation import get_rotation_orchestrator

async def monitor_rotations(incident_id: str, watch: bool = False):
    """Monitor rotation progress"""

    orchestrator = get_rotation_orchestrator()
    if not orchestrator:
        print("Rotation orchestrator not available")
        return

    while True:
        # Get active rotations
        active = orchestrator.active_rotations

        print(f"\n=== Rotation Status ({datetime.now(timezone.utc)}) ===")
        print(f"Active rotations: {len(active)}")

        for rotation_id, context in active.items():
            print(f"  {rotation_id}: {context.status.value} ({context.current_phase.value})")
            if context.error_message:
                print(f"    Error: {context.error_message}")

        if not watch:
            break

        await asyncio.sleep(10)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--watch", action="store_true")

    args = parser.parse_args()

    asyncio.run(monitor_rotations(args.incident_id, args.watch))
```

## Testing Emergency Procedures

### Monthly Drill Schedule

- **First Monday**: Database credential rotation drill
- **Second Monday**: API key rotation drill
- **Third Monday**: JWT secret rotation drill
- **Fourth Monday**: Full emergency simulation

### Drill Execution

```bash
# Start emergency drill
./scripts/security/emergency-drill.sh \
    --type "database_rotation" \
    --simulate \
    --notify-team

# Measure response times
python3 scripts/security/measure-drill-performance.py \
    --drill-type "database_rotation"
```

## Compliance and Documentation

### Required Documentation

- [ ] Incident timeline
- [ ] Actions taken log
- [ ] Communication records
- [ ] System impact assessment
- [ ] Lessons learned report

### Regulatory Notifications

- **GDPR**: Notify within 72 hours if personal data affected
- **PCI DSS**: Immediate notification for payment data exposure
- **SOC 2**: Document all security incidents

### Audit Trail

All emergency actions are automatically logged to:

- Vault audit logs
- Application audit logs
- Infrastructure change logs
- Communication records

## Recovery and Lessons Learned

### Post-Incident Review Checklist

- [ ] Timeline accuracy verification
- [ ] Response time analysis
- [ ] Communication effectiveness review
- [ ] Technical procedure validation
- [ ] Process improvement identification
- [ ] Training needs assessment

### Continuous Improvement

- Update procedures based on drill results
- Enhance automation capabilities
- Improve monitoring and alerting
- Strengthen team training and preparedness

---

**Document Version**: 1.0  
**Last Updated**: $(date -u)  
**Next Review**: $(date -d '+3 months' -u)  
**Owner**: Security Team  
**Approved By**: CTO, CISO
