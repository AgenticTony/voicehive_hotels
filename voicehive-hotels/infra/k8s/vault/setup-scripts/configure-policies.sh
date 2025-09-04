#!/bin/bash
# VoiceHive Hotels - Vault Policies Configuration
# Sets up fine-grained policies for all VoiceHive services

set -euo pipefail

# Configuration
NAMESPACE="vault"
VAULT_POD="vault-0"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Configuring Vault Policies for VoiceHive Hotels${NC}"
echo "==============================================="

# Get root token from latest init secret
ROOT_TOKEN_SECRET=$(kubectl get secrets -n ${NAMESPACE} | grep vault-init | tail -1 | awk '{print $1}')
if [ -z "$ROOT_TOKEN_SECRET" ]; then
    echo "Error: No vault-init secret found. Run init-vault.sh first."
    exit 1
fi

ROOT_TOKEN=$(kubectl get secret -n ${NAMESPACE} ${ROOT_TOKEN_SECRET} -o jsonpath='{.data.root-token}' | base64 -d)

# Function to create a policy
create_policy() {
    local policy_name=$1
    local policy_content=$2
    
    echo -n "Creating policy: ${policy_name}... "
    
    kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
        export VAULT_TOKEN='${ROOT_TOKEN}'
        cat <<'EOL' | vault policy write ${policy_name} -
${policy_content}
EOL
    " >/dev/null 2>&1
    
    echo -e "${GREEN}✓${NC}"
}

# Admin Policy - Full access (use sparingly)
create_policy "admin" '
path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}'

# Orchestrator Service Policy
create_policy "orchestrator" '
# Read PMS credentials
path "voicehive/data/pms/*" {
  capabilities = ["read"]
}

# Read AI service credentials
path "voicehive/data/ai-services/*" {
  capabilities = ["read"]
}

# Encrypt/decrypt PII
path "transit/encrypt/pii" {
  capabilities = ["update"]
}

path "transit/decrypt/pii" {
  capabilities = ["update"]
}

# Generate database credentials
path "database/creds/orchestrator" {
  capabilities = ["read"]
}

# Read own service configuration
path "voicehive/data/orchestrator/*" {
  capabilities = ["read"]
}
'

# Connector Service Policy
create_policy "connector-service" '
# Read PMS API credentials
path "voicehive/data/pms/*/api-credentials" {
  capabilities = ["read"]
}

# Read connector configuration
path "voicehive/data/connectors/*" {
  capabilities = ["read"]
}

# Encrypt sensitive data
path "transit/encrypt/connector-data" {
  capabilities = ["update"]
}

path "transit/decrypt/connector-data" {
  capabilities = ["update"]
}
'

# Media Service Policy (LiveKit)
create_policy "media-service" '
# Read LiveKit credentials
path "voicehive/data/livekit/*" {
  capabilities = ["read"]
}

# Read Twilio SIP credentials
path "voicehive/data/twilio/*" {
  capabilities = ["read"]
}

# Generate temporary recording encryption keys
path "transit/datakey/plaintext/recordings" {
  capabilities = ["update"]
}
'

# AI Services Policy
create_policy "ai-services" '
# Read AI provider credentials
path "voicehive/data/ai-services/nvidia/*" {
  capabilities = ["read"]
}

path "voicehive/data/ai-services/elevenlabs/*" {
  capabilities = ["read"]
}

path "voicehive/data/ai-services/azure/*" {
  capabilities = ["read"]
}

# Encrypt model responses
path "transit/encrypt/ai-responses" {
  capabilities = ["update"]
}
'

# Compliance Service Policy
create_policy "compliance-service" '
# Full access to compliance data
path "voicehive/data/compliance/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

# Read all encryption keys for audit
path "transit/keys/*" {
  capabilities = ["read"]
}

# Generate audit reports
path "sys/audit" {
  capabilities = ["read", "list"]
}

# Access to PII encryption for redaction
path "transit/encrypt/pii" {
  capabilities = ["update"]
}

path "transit/decrypt/pii" {
  capabilities = ["update"]
}
'

# Monitoring Service Policy
create_policy "monitoring" '
# Read metrics and health data
path "sys/metrics" {
  capabilities = ["read"]
}

path "sys/health" {
  capabilities = ["read"]
}

# List all mounts for monitoring
path "sys/mounts" {
  capabilities = ["list"]
}

# Read monitoring credentials
path "voicehive/data/monitoring/*" {
  capabilities = ["read"]
}
'

# CI/CD Pipeline Policy
create_policy "cicd" '
# Manage service credentials
path "voicehive/data/*" {
  capabilities = ["create", "read", "update"]
}

# Rotate encryption keys
path "transit/keys/*/rotate" {
  capabilities = ["update"]
}

# Configure database connections
path "database/config/*" {
  capabilities = ["create", "read", "update"]
}

# Manage policies (restricted)
path "sys/policies/acl/*" {
  capabilities = ["read", "list"]
}
'

echo
echo "Creating Kubernetes auth roles..."

# Function to create Kubernetes auth role
create_k8s_role() {
    local role_name=$1
    local service_account=$2
    local namespace=$3
    local policies=$4
    
    echo -n "Creating k8s role: ${role_name}... "
    
    kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
        export VAULT_TOKEN='${ROOT_TOKEN}'
        vault write auth/kubernetes/role/${role_name} \
            bound_service_account_names=${service_account} \
            bound_service_account_namespaces=${namespace} \
            policies=${policies} \
            ttl=24h \
            max_ttl=720h
    " >/dev/null 2>&1
    
    echo -e "${GREEN}✓${NC}"
}

# Create Kubernetes auth roles
create_k8s_role "orchestrator" "orchestrator" "voicehive-production,voicehive-staging" "orchestrator"
create_k8s_role "connector-service" "connector-service" "voicehive-production,voicehive-staging" "connector-service"
create_k8s_role "media-service" "media-service" "voicehive-production,voicehive-staging" "media-service"
create_k8s_role "ai-services" "ai-services" "voicehive-production,voicehive-staging" "ai-services"
create_k8s_role "compliance-service" "compliance-service" "voicehive-production,voicehive-staging" "compliance-service"
create_k8s_role "monitoring" "prometheus" "monitoring" "monitoring"

echo
echo "Creating initial secrets..."

# Create encryption keys
echo -n "Creating transit encryption keys... "
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    
    # PII encryption key (auto-rotate every 30 days)
    vault write -f transit/keys/pii \
        auto_rotate_period=720h \
        exportable=false \
        allow_plaintext_backup=false
    
    # Connector data encryption
    vault write -f transit/keys/connector-data \
        auto_rotate_period=2160h \
        exportable=false
    
    # Recording encryption
    vault write -f transit/keys/recordings \
        auto_rotate_period=720h \
        exportable=false
    
    # AI response encryption
    vault write -f transit/keys/ai-responses \
        auto_rotate_period=1440h \
        exportable=false
" >/dev/null 2>&1
echo -e "${GREEN}✓${NC}"

# Create admin token with limited TTL
echo
echo "Creating admin token..."
ADMIN_TOKEN=$(kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    vault token create -policy=admin -ttl=720h -format=json | jq -r '.auth.client_token'
")

# Store admin token in secret
kubectl create secret generic vault-admin-token \
    -n ${NAMESPACE} \
    --from-literal=token="${ADMIN_TOKEN}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo -e "${GREEN}✓ Admin token created and stored in secret: vault-admin-token${NC}"

echo
echo -e "${GREEN}✓ Vault policies configuration complete!${NC}"
echo
echo "Policy Summary:"
echo "- admin: Full access (use sparingly)"
echo "- orchestrator: PMS/AI creds, PII encryption"
echo "- connector-service: PMS API creds, data encryption"
echo "- media-service: LiveKit/Twilio creds, recording encryption"
echo "- ai-services: AI provider creds, response encryption"
echo "- compliance-service: Compliance data, audit access"
echo "- monitoring: Metrics and health data"
echo "- cicd: Credential management for pipelines"
echo
echo "Next steps:"
echo "1. Revoke the root token: kubectl exec -n vault vault-0 -- vault token revoke <root-token>"
echo "2. Use admin token for future configurations"
echo "3. Test service authentication"
