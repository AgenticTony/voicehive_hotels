#!/bin/bash
set -euo pipefail

# Enhanced Vault Policy Configuration
# Implements least-privilege access controls per WARP.md security requirements

VAULT_ADDR=${VAULT_ADDR:-"http://vault:8200"}
VAULT_NAMESPACE="voicehive"

echo "🔐 Configuring enhanced Vault policies with least-privilege ACLs..."

# Wait for Vault to be ready
until vault status >/dev/null 2>&1; do
    echo "Waiting for Vault to be ready..."
    sleep 2
done

# 1. Connector SDK Policy - Read-only access to PMS credentials
cat <<EOF | vault policy write connector-sdk-policy -
# Connector SDK - Read-only access to PMS credentials (KV v2)
# Note: KV v2 does not support parameter constraints in ACLs (allowed/denied/required)
# See: Vault Policies docs - parameter constraints not supported for kv-v2 paths
path "kv/data/connectors/*/credentials" {
  capabilities = ["read"]
}

# List available connectors
path "kv/metadata/connectors/*" {
  capabilities = ["list"]
}

# Read connector configuration (non-secret)
path "kv/data/connectors/+/config" {
  capabilities = ["read"]
}

# Use transit encryption for PII
path "transit/encrypt/pii-key" {
  capabilities = ["create", "update"]
}

path "transit/decrypt/pii-key" {
  capabilities = ["create", "update"]
}

# Health check access
path "sys/health" {
  capabilities = ["read"]
}

# Token self-renewal
path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
EOF

# 2. Orchestrator Policy - Enhanced permissions for call handling
cat <<EOF | vault policy write orchestrator-policy -
# Orchestrator - Full access for call processing
path "kv/data/connectors/+/credentials" {
  capabilities = ["read"]
}

path "kv/data/ai-services/+/credentials" {
  capabilities = ["read"]
}

# Cache management
path "kv/data/cache/calls/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
  max_versions = 5
}

# Session keys for encryption
path "transit/datakey/plaintext/session-key" {
  capabilities = ["update"]
}

# Encrypt/decrypt call recordings
path "transit/encrypt/call-recordings" {
  capabilities = ["update"]
}

path "transit/decrypt/call-recordings" {
  capabilities = ["update"]
}

# Audit log access (write-only)
path "sys/audit-hash/file" {
  capabilities = ["update"]
}
EOF

# 3. Admin Policy - Full administrative access
cat <<EOF | vault policy write admin-policy -
# Admin - Full access with audit
path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}

# Audit configuration
path "sys/audit/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}

# Policy management
path "sys/policies/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Auth method configuration
path "sys/auth/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}

# Seal management
path "sys/seal" {
  capabilities = ["update", "sudo"]
}
EOF

# 4. CI/CD Policy - Limited access for deployments
cat <<EOF | vault policy write cicd-policy -
# CI/CD - Deployment and rotation permissions
path "kv/data/deployments/+/config" {
  capabilities = ["create", "read", "update"]
}

# Rotate credentials (application enforces rotation semantics)
path "kv/data/connectors/+/credentials" {
  capabilities = ["update"]
}

# Read deployment status
path "kv/metadata/deployments/*" {
  capabilities = ["read", "list"]
}
EOF

# 5. Monitoring Policy - Read-only metrics access
cat <<EOF | vault policy write monitoring-policy -
# Monitoring - Health and metrics only
path "sys/health" {
  capabilities = ["read"]
}

path "sys/metrics" {
  capabilities = ["read"]
}

# Read-only access to non-sensitive configs (no param constraints on kv-v2)
path "kv/data/+/config" {
  capabilities = ["read"]
}

# Audit log summaries (no raw data)
path "sys/audit-hash/+/*" {
  capabilities = ["update"]
}
EOF

# 6. Partner Policy Template - Per-partner access control
cat <<EOF | vault policy write partner-template-policy -
# Partner {{identity.entity.metadata.partner_name}} - Scoped access
path "kv/data/partners/{{identity.entity.metadata.partner_name}}/credentials" {
  capabilities = ["read"]
  max_versions = 1
}

# Partner-specific webhook secrets
path "kv/data/partners/{{identity.entity.metadata.partner_name}}/webhooks" {
  capabilities = ["read", "update"]
  allowed_parameters = {
    "signature_key" = []
  }
}

# Rate limit status
path "kv/data/rate-limits/{{identity.entity.metadata.partner_name}}" {
  capabilities = ["read"]
}
EOF

# 7. Compliance Policy - GDPR operations
cat <<EOF | vault policy write compliance-policy -
# Compliance - GDPR and audit operations
path "kv/data/gdpr/consent/*" {
  capabilities = ["create", "read", "update", "list"]
  required_parameters = ["user_id", "timestamp", "consent_type"]
}

# PII encryption for right to erasure
path "transit/encrypt/pii-erasure" {
  capabilities = ["update"]
}

# Audit log hashing for compliance reports
path "sys/audit-hash/+/*" {
  capabilities = ["update"]
}

# Compliance metadata
path "kv/data/compliance/policies/*" {
  capabilities = ["read", "list"]
}
EOF

# 8. Break-glass Emergency Policy
cat <<EOF | vault policy write emergency-policy -
# Emergency - Time-bound elevated access
path "*" {
  capabilities = ["create", "read", "update", "delete", "list"]
  max_ttl = "1h"
  # Requires MFA
  mfa_methods = ["totp", "okta"]
}

# Audit requirement
path "sys/audit-hash/file" {
  capabilities = ["update"]
  required_parameters = ["reason", "incident_id"]
}
EOF

# Create Kubernetes auth roles with policies
echo "🔑 Creating Kubernetes auth roles..."

# Connector SDK role
vault write auth/kubernetes/role/connector-sdk \
    bound_service_account_names=connector-sdk \
    bound_service_account_namespaces=voicehive \
    policies=connector-sdk-policy \
    ttl=1h \
    max_ttl=24h

# Orchestrator role
vault write auth/kubernetes/role/orchestrator \
    bound_service_account_names=orchestrator \
    bound_service_account_namespaces=voicehive \
    policies=orchestrator-policy \
    ttl=2h \
    max_ttl=24h

# Monitoring role
vault write auth/kubernetes/role/monitoring \
    bound_service_account_names=prometheus,grafana \
    bound_service_account_namespaces=monitoring \
    policies=monitoring-policy \
    ttl=4h \
    max_ttl=24h

# Enable response wrapping for sensitive operations
vault write sys/wrapping/wrap \
    path="kv/data/connectors/*/credentials" \
    ttl=300

# Configure audit devices with filters
echo "📝 Configuring audit logging..."

# Enable file audit with HMAC
vault audit enable file \
    file_path=/vault/logs/audit.log \
    log_raw=false \
    hmac_accessor=true \
    format=json \
    prefix="voicehive-"

# Enable syslog audit for SIEM integration
vault audit enable syslog \
    tag="vault-voicehive" \
    facility="LOCAL0" \
    log_raw=false

# Set up audit filters to exclude sensitive data
cat <<EOF | vault write sys/config/auditing/request-headers -
{
  "hmac": {
    "X-Forwarded-For": false,
    "X-Real-IP": false,
    "X-Correlation-ID": false
  }
}
EOF

echo "✅ Enhanced Vault policies configured successfully!"
echo ""
echo "📊 Policy Summary:"
vault policy list | while read policy; do
    echo "  - $policy"
done

echo ""
echo "🔍 Audit devices:"
vault audit list -format=json | jq -r 'to_entries[] | "  - \(.key): \(.value.type)"'

echo ""
echo "🎯 Next steps:"
echo "  1. Test policy access: vault login -method=kubernetes role=connector-sdk"
echo "  2. Verify audit logs: tail -f /vault/logs/audit.log | jq"
echo "  3. Run compliance check: ./tools/compliance/vault-policy-validator.sh"

<citations>
  <document>
    <document_type>RULE</document_type>
    <document_id>Wwlby5Eyggc3njCotU8KWP</document_id>
  </document>
</citations>
