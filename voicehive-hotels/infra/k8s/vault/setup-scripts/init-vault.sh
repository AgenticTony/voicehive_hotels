#!/bin/bash
# VoiceHive Hotels - HashiCorp Vault Initialization Script
# Initializes Vault, configures auto-unsealing, and stores recovery keys securely

set -euo pipefail

# Configuration
NAMESPACE="vault"
VAULT_POD="vault-0"
AWS_REGION=${AWS_REGION:-eu-west-1}
S3_BUCKET=${VAULT_RECOVERY_BUCKET:-voicehive-vault-recovery-eu}

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}VoiceHive Hotels - Vault Initialization${NC}"
echo "========================================"

# Function to check if Vault is initialized
check_initialized() {
    kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- vault status -format=json 2>/dev/null | jq -r '.initialized' || echo "false"
}

# Function to check if Vault is sealed
check_sealed() {
    kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- vault status -format=json 2>/dev/null | jq -r '.sealed' || echo "true"
}

# Wait for Vault pod to be ready
echo -n "Waiting for Vault pod to be ready..."
kubectl wait --for=condition=ready pod/${VAULT_POD} -n ${NAMESPACE} --timeout=300s
echo -e " ${GREEN}✓${NC}"

# Check if already initialized
if [ "$(check_initialized)" == "true" ]; then
    echo -e "${YELLOW}Vault is already initialized${NC}"
    
    if [ "$(check_sealed)" == "true" ]; then
        echo "Vault is sealed. With auto-unseal configured, it should unseal automatically."
        echo "If not, check the AWS KMS key permissions."
    else
        echo -e "${GREEN}Vault is initialized and unsealed${NC}"
    fi
    
    exit 0
fi

# Initialize Vault
echo "Initializing Vault..."
INIT_OUTPUT=$(kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- vault operator init -format=json \
    -recovery-shares=5 \
    -recovery-threshold=3)

# Extract recovery keys and root token
RECOVERY_KEYS=$(echo "$INIT_OUTPUT" | jq -r '.recovery_keys_b64[]')
ROOT_TOKEN=$(echo "$INIT_OUTPUT" | jq -r '.root_token')

# Create timestamp for this initialization
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Store recovery keys securely in S3 with encryption
echo "Storing recovery keys securely..."

# Create a JSON file with the recovery information
cat > /tmp/vault-recovery-${TIMESTAMP}.json <<EOF
{
  "initialized_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "vault_cluster": "${NAMESPACE}",
  "recovery_shares": 5,
  "recovery_threshold": 3,
  "recovery_keys_b64": $(echo "$INIT_OUTPUT" | jq '.recovery_keys_b64'),
  "recovery_keys_hex": $(echo "$INIT_OUTPUT" | jq '.recovery_keys_hex')
}
EOF

# Upload to S3 with server-side encryption
aws s3 cp /tmp/vault-recovery-${TIMESTAMP}.json \
    s3://${S3_BUCKET}/vault-recovery-${TIMESTAMP}.json \
    --server-side-encryption AES256 \
    --region ${AWS_REGION}

# Clean up local file
shred -vfz -n 3 /tmp/vault-recovery-${TIMESTAMP}.json

echo -e "${GREEN}Recovery keys stored securely in S3${NC}"

# Store root token in Kubernetes secret (will be revoked after initial setup)
kubectl create secret generic vault-init-${TIMESTAMP} \
    -n ${NAMESPACE} \
    --from-literal=root-token="${ROOT_TOKEN}" \
    --from-literal=recovery-bucket="${S3_BUCKET}" \
    --from-literal=recovery-file="vault-recovery-${TIMESTAMP}.json"

echo -e "${GREEN}Initial root token stored in Kubernetes secret: vault-init-${TIMESTAMP}${NC}"

# Wait for auto-unseal
echo -n "Waiting for Vault to auto-unseal..."
for i in {1..30}; do
    if [ "$(check_sealed)" == "false" ]; then
        echo -e " ${GREEN}✓${NC}"
        break
    fi
    sleep 2
    echo -n "."
done

if [ "$(check_sealed)" == "true" ]; then
    echo -e " ${RED}✗${NC}"
    echo "Vault did not auto-unseal. Check AWS KMS key permissions."
    exit 1
fi

# Configure audit logging
echo "Configuring audit logging..."
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    vault audit enable file file_path=/vault/audit/audit.log
"

# Enable required auth methods
echo "Enabling auth methods..."
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    
    # Enable Kubernetes auth
    vault auth enable kubernetes
    
    # Configure Kubernetes auth
    vault write auth/kubernetes/config \
        kubernetes_host=\"https://\$KUBERNETES_PORT_443_TCP_ADDR:443\" \
        token_reviewer_jwt=@/var/run/secrets/kubernetes.io/serviceaccount/token \
        kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
"

# Enable secrets engines
echo "Enabling secrets engines..."
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    
    # KV v2 for application secrets
    vault secrets enable -path=voicehive kv-v2
    
    # Transit for encryption as a service
    vault secrets enable transit
    
    # Database secrets engine
    vault secrets enable -path=database database
    
    # AWS secrets engine for dynamic credentials
    vault secrets enable -path=aws aws
"

echo -e "${GREEN}✓ Vault initialization complete!${NC}"
echo
echo "Important information:"
echo "1. Recovery keys are stored in: s3://${S3_BUCKET}/vault-recovery-${TIMESTAMP}.json"
echo "2. Root token is in secret: vault-init-${TIMESTAMP}"
echo "3. Root token should be revoked after creating admin policies"
echo
echo "Next steps:"
echo "1. Run ./configure-policies.sh to set up Vault policies"
echo "2. Create service-specific credentials"
echo "3. Revoke the root token"
echo "4. Test auto-unseal by restarting Vault pods"
