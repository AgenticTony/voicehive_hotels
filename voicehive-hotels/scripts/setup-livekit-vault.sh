#!/bin/bash
# Script to store LiveKit credentials in HashiCorp Vault

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "LiveKit Cloud Vault Setup Script"
echo "================================"

# Check if Vault is configured
if [ -z "$VAULT_ADDR" ]; then
    echo -e "${YELLOW}VAULT_ADDR not set. Using default: http://localhost:8200${NC}"
    export VAULT_ADDR="http://localhost:8200"
fi

# Check Vault status
if ! vault status &> /dev/null; then
    echo -e "${RED}Error: Unable to connect to Vault at $VAULT_ADDR${NC}"
    echo "Please ensure Vault is running and accessible."
    exit 1
fi

# Login to Vault if not authenticated
if ! vault token lookup &> /dev/null; then
    echo -e "${YELLOW}Not authenticated to Vault. Please login:${NC}"
    vault login
fi

echo -e "${GREEN}Connected to Vault successfully${NC}"

# Prompt for LiveKit credentials
echo ""
echo "Enter your LiveKit Cloud credentials:"
echo "(These can be found in your LiveKit Cloud dashboard)"
echo ""

read -p "LiveKit API Key (starts with API): " LIVEKIT_API_KEY
read -s -p "LiveKit API Secret (starts with SK): " LIVEKIT_API_SECRET
echo ""
read -p "LiveKit Project URL (wss://xxx.livekit.cloud): " LIVEKIT_URL
read -p "SIP Subdomain (from SIP configuration): " LIVEKIT_SIP_SUBDOMAIN
read -p "Environment (prod/staging/dev): " ENVIRONMENT

# Generate webhook key if not provided
WEBHOOK_KEY=$(openssl rand -hex 32)
echo -e "${GREEN}Generated webhook key: ${WEBHOOK_KEY:0:8}...${NC}"

# Store in Vault
echo -e "${YELLOW}Storing credentials in Vault...${NC}"

vault kv put secret/livekit/${ENVIRONMENT} \
    api_key="$LIVEKIT_API_KEY" \
    api_secret="$LIVEKIT_API_SECRET" \
    project_url="$LIVEKIT_URL" \
    sip_subdomain="$LIVEKIT_SIP_SUBDOMAIN" \
    webhook_key="$WEBHOOK_KEY" \
    region="eu-central-1" \
    created_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Credentials stored successfully in Vault${NC}"
    echo ""
    echo "Path: secret/livekit/${ENVIRONMENT}"
    echo ""
    echo "To verify:"
    echo "  vault kv get secret/livekit/${ENVIRONMENT}"
    echo ""
    echo "To use in your application:"
    echo "  export LIVEKIT_API_KEY=\$(vault kv get -field=api_key secret/livekit/${ENVIRONMENT})"
    echo "  export LIVEKIT_API_SECRET=\$(vault kv get -field=api_secret secret/livekit/${ENVIRONMENT})"
else
    echo -e "${RED}Failed to store credentials in Vault${NC}"
    exit 1
fi

# Create Kubernetes secret manifest (optional)
read -p "Generate Kubernetes secret manifest? (y/n): " GEN_K8S

if [[ "$GEN_K8S" =~ ^[Yy]$ ]]; then
    cat > livekit-secret-${ENVIRONMENT}.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: livekit-credentials
  namespace: voicehive-${ENVIRONMENT}
type: Opaque
data:
  api_key: $(echo -n "$LIVEKIT_API_KEY" | base64)
  api_secret: $(echo -n "$LIVEKIT_API_SECRET" | base64)
  project_url: $(echo -n "$LIVEKIT_URL" | base64)
  webhook_key: $(echo -n "$WEBHOOK_KEY" | base64)
  sip_subdomain: $(echo -n "$LIVEKIT_SIP_SUBDOMAIN" | base64)
EOF
    
    echo -e "${GREEN}✓ Kubernetes secret manifest created: livekit-secret-${ENVIRONMENT}.yaml${NC}"
    echo "Apply with: kubectl apply -f livekit-secret-${ENVIRONMENT}.yaml"
fi

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Update your .env.${ENVIRONMENT} file with Vault paths"
echo "2. Configure SIP routing in LiveKit Cloud dashboard"
echo "3. Test the connection using livekit-cli"
echo "4. Deploy the LiveKit agent with new credentials"
