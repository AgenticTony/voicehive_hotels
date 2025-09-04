# LiveKit Cloud Setup Guide

This guide walks through setting up LiveKit Cloud for VoiceHive Hotels with EU region compliance.

## Prerequisites

- LiveKit Cloud account (or ability to create one)
- Access to HashiCorp Vault for credential storage
- Permission to configure SIP trunks

## Setup Steps

### 1. Create LiveKit Cloud Account

1. Go to [cloud.livekit.io](https://cloud.livekit.io)
2. Sign up for a new account or log in
3. Choose "Enterprise" plan for production features

### 2. Select EU Region

**IMPORTANT**: For GDPR compliance, you MUST select an EU region.

1. In LiveKit Cloud dashboard, go to **Projects**
2. Click **Create New Project**
3. Project settings:
   - **Name**: `voicehive-hotels-prod`
   - **Region**: Select either:
     - `eu-central-1` (Frankfurt) - Recommended for lowest latency
     - `eu-west-1` (Amsterdam) - Alternative EU option
   - **Enable SIP**: Yes

### 3. Generate API Keys and Secrets

1. In your project, go to **Settings** → **API Keys**
2. Click **Create New Key**
3. Key settings:
   - **Name**: `voicehive-prod-key`
   - **Permissions**: Full access (for now, restrict later)
4. **SAVE THESE SECURELY**:
   - API Key: `API...`
   - API Secret: `SK...`
   - Project URL: `wss://<project>.livekit.cloud`

### 4. Store Credentials in Vault

```bash
# Connect to Vault
export VAULT_ADDR=https://vault.voicehive-hotels.eu
vault login

# Store LiveKit credentials
vault kv put secret/livekit/prod \
  api_key="API..." \
  api_secret="SK..." \
  project_url="wss://<project>.livekit.cloud" \
  sip_subdomain="<sip-subdomain>"

# Verify storage
vault kv get secret/livekit/prod
```

### 5. Configure SIP Trunk Settings

1. In LiveKit Cloud, go to **SIP** → **Configuration**
2. Note your SIP trunk details:
   - **SIP URI**: `{sip_subdomain}.{region}.sip.livekit.cloud`
   - **Transport**: UDP/TCP/TLS (recommend TLS)
   - **Authentication**: IP-based or credentials

3. Configure inbound routing:
```yaml
inbound_rules:
  - match:
      called_number: "+49*"  # German numbers
    action:
      type: dispatch_to_room
      room_prefix: "hotel_de_"
  
  - match:
      called_number: "+44*"  # UK numbers
    action:
      type: dispatch_to_room
      room_prefix: "hotel_uk_"
```

4. Configure your SIP provider (e.g., Twilio) to route to LiveKit:
   - **Destination**: `sip:{sip_subdomain}.eu-central-1.sip.livekit.cloud`
   - **Port**: 5060 (UDP) or 5061 (TLS)

## Environment Configuration

Update your environment files:

### `.env.production`
```bash
# LiveKit Configuration
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=<fetch-from-vault>
LIVEKIT_API_SECRET=<fetch-from-vault>
LIVEKIT_WEBHOOK_KEY=<generate-random>

# SIP Configuration
LIVEKIT_SIP_URI={sip_subdomain}.eu-central-1.sip.livekit.cloud
LIVEKIT_SIP_TRANSPORT=tls
```

### `services/media/livekit-agent/config.yaml`
```yaml
livekit:
  url: ${LIVEKIT_URL}
  api_key: ${LIVEKIT_API_KEY}
  api_secret: ${LIVEKIT_API_SECRET}
  
sip:
  region: eu-central-1
  enable_recording: true
  codec_preference:
    - opus
    - pcmu
```

## Verification Steps

1. **Test API Connection**:
```bash
# Install LiveKit CLI
brew install livekit-cli

# Test connection
livekit-cli room list \
  --url $LIVEKIT_URL \
  --api-key $LIVEKIT_API_KEY \
  --api-secret $LIVEKIT_API_SECRET
```

2. **Test SIP Registration**:
```bash
# Use a SIP testing tool
sipvicious_svmap {sip_subdomain}.eu-central-1.sip.livekit.cloud
```

3. **Create Test Room**:
```python
from livekit import api

client = api.LiveKitAPI(
    url=os.getenv("LIVEKIT_URL"),
    api_key=os.getenv("LIVEKIT_API_KEY"),
    api_secret=os.getenv("LIVEKIT_API_SECRET"),
)

# Create a test room
room = await client.room.create_room(
    api.CreateRoomRequest(name="test-hotel-call")
)
print(f"Room created: {room.name}")
```

## Security Checklist

- [ ] API keys stored in Vault, not in code
- [ ] Webhook secret is unique and strong
- [ ] SIP uses TLS transport
- [ ] IP allowlisting configured if available
- [ ] Rate limiting enabled
- [ ] Audit logging enabled

## Troubleshooting

### Connection Issues
- Verify region selection matches your configuration
- Check firewall rules allow SIP/RTP ports
- Ensure DNS resolves correctly for SIP subdomain

### Authentication Failures
- Regenerate API keys if compromised
- Check Vault connectivity
- Verify environment variable loading

## Next Steps

Once LiveKit Cloud is configured:
1. Update Kubernetes secrets with new credentials
2. Deploy LiveKit agent with production configuration
3. Test end-to-end call flow
4. Configure monitoring alerts
