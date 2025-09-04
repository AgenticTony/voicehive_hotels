#!/bin/bash
# VoiceHive Hotels - Configure PMS Credentials in Vault
# This script sets up sample PMS API credentials in Vault

set -euo pipefail

# Configuration
NAMESPACE="vault"
VAULT_POD="vault-0"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Configuring PMS Credentials in Vault${NC}"
echo "======================================"

# Get root token from latest init secret
ROOT_TOKEN_SECRET=$(kubectl get secrets -n ${NAMESPACE} | grep vault-init | tail -1 | awk '{print $1}')
if [ -z "$ROOT_TOKEN_SECRET" ]; then
    echo -e "${RED}Error: No vault-init secret found. Run init-vault.sh first.${NC}"
    exit 1
fi

ROOT_TOKEN=$(kubectl get secret -n ${NAMESPACE} ${ROOT_TOKEN_SECRET} -o jsonpath='{.data.root-token}' | base64 -d)

# Function to create a PMS credential
create_pms_credential() {
    local vendor=$1
    local hotel_id=$2
    local credentials=$3
    
    echo -n "Creating credentials for ${vendor}/${hotel_id}... "
    
    kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
        export VAULT_TOKEN='${ROOT_TOKEN}'
        vault kv put -mount=voicehive pms/${vendor}/${hotel_id}/api-credentials ${credentials}
    " >/dev/null 2>&1
    
    echo -e "${GREEN}✓${NC}"
}

# Enable KV v2 secrets engine at voicehive path if not exists
echo -n "Enabling KV v2 secrets engine... "
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    vault secrets enable -path=voicehive kv-v2 2>/dev/null || echo 'Already enabled'
" >/dev/null

echo -e "${GREEN}✓${NC}"

# Enable transit engine for encryption
echo -n "Enabling transit engine... "
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    vault secrets enable -path=transit transit 2>/dev/null || echo 'Already enabled'
" >/dev/null

echo -e "${GREEN}✓${NC}"

# Create encryption keys
echo -n "Creating encryption keys... "
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    vault write -f transit/keys/connector-data 2>/dev/null || echo 'Key exists'
    vault write -f transit/keys/pii 2>/dev/null || echo 'Key exists'
" >/dev/null

echo -e "${GREEN}✓${NC}"

echo ""
echo "Creating PMS Credentials:"
echo "========================"

# Apaleo credentials
create_pms_credential "apaleo" "default" \
    "client_id=voicehive-demo \
     client_secret=demo-secret-change-in-prod \
     base_url=https://api.apaleo.com"

create_pms_credential "apaleo" "HOTEL01" \
    "client_id=hotel01-apaleo-client \
     client_secret=hotel01-secret-change-in-prod \
     base_url=https://api.apaleo.com \
     property_id=HOTEL01"

# Mews credentials
create_pms_credential "mews" "default" \
    "client_token=demo-mews-token \
     access_token=demo-access-token \
     base_url=https://api.mews.com"

create_pms_credential "mews" "HOTEL02" \
    "client_token=hotel02-mews-token \
     access_token=hotel02-access-token \
     base_url=https://api.mews.com \
     property_id=hotel02-property-id"

# Cloudbeds credentials
create_pms_credential "cloudbeds" "default" \
    "api_key=demo-cloudbeds-key \
     property_id=demo-property \
     base_url=https://api.cloudbeds.com/api/v1.1"

# Opera (OHIP) credentials
create_pms_credential "opera" "default" \
    "client_id=voicehive-opera \
     client_secret=opera-secret-change-in-prod \
     base_url=https://api.oracle.com/opera/v1 \
     hotel_code=DEMO"

# SiteMinder credentials
create_pms_credential "siteminder" "default" \
    "username=voicehive-demo \
     password=demo-password-change-in-prod \
     hotel_code=DEMO001 \
     base_url=https://api.siteminder.com"

echo ""
echo "Creating generic connector settings:"
echo "==================================="

# Create generic connector configuration
echo -n "Creating connector configuration... "
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    vault kv put -mount=voicehive connectors/config \
        rate_limit_enabled=true \
        cache_ttl=300 \
        timeout_seconds=30 \
        retry_max_attempts=3 \
        circuit_breaker_threshold=5
" >/dev/null 2>&1

echo -e "${GREEN}✓${NC}"

# Create AI service credentials
echo ""
echo "Creating AI service credentials:"
echo "================================"

echo -n "Creating Azure OpenAI credentials... "
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    vault kv put -mount=voicehive ai-services/azure/openai \
        api_key=demo-azure-key \
        endpoint=https://voicehive.openai.azure.com \
        deployment_name=gpt-4o
" >/dev/null 2>&1

echo -e "${GREEN}✓${NC}"

echo -n "Creating ElevenLabs credentials... "
kubectl exec -n ${NAMESPACE} ${VAULT_POD} -- sh -c "
    export VAULT_TOKEN='${ROOT_TOKEN}'
    vault kv put -mount=voicehive ai-services/elevenlabs/tts \
        api_key=demo-elevenlabs-key \
        voice_id=demo-voice-id
" >/dev/null 2>&1

echo -e "${GREEN}✓${NC}"

echo ""
echo -e "${GREEN}✓ PMS credentials successfully configured in Vault!${NC}"
echo ""
echo "To verify credentials:"
echo "  export VAULT_TOKEN='${ROOT_TOKEN}'"
echo "  vault kv get -mount=voicehive pms/apaleo/default/api-credentials"
echo ""
echo "WARNING: These are demo credentials. Replace with real credentials in production!"
