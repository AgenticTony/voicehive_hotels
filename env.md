 🔐 Required API Keys & Credentials

  1. Apaleo PMS Connector (PRIMARY INTEGRATION)

  # Apaleo OAuth2 Credentials
  APALEO_CLIENT_ID="your_apaleo_client_id"
  APALEO_CLIENT_SECRET="your_apaleo_client_secret"
  APALEO_BASE_URL="https://api.apaleo.com"  # Default
  APALEO_PROPERTY_ID="your_property_id"

  2. Enhanced Alerting System

  # Slack Integration
  SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"

  # PagerDuty Integration  
  PAGERDUTY_INTEGRATION_KEY="your_pagerduty_integration_key"

  3. Infrastructure & Monitoring

  # HashiCorp Vault (for secrets management)
  VAULT_URL="https://your-vault-instance.com"
  VAULT_TOKEN="your_vault_token"  # Or use Kubernetes auth

  # Database Connections
  DATABASE_PASSWORD="your_postgres_password"
  REDIS_PASSWORD="your_redis_password"

  # Prometheus/Monitoring (if external)
  PROMETHEUS_PUSHGATEWAY_URL="http://your-prometheus:9091"  # Optional

  4. Security & Authentication

  # JWT Configuration
  JWT_SECRET_KEY="your_super_secure_jwt_secret_key_32_chars+"
  JWT_ALGORITHM="RS256"  # Recommended for production

  # Webhook Security
  WEBHOOK_SIGNATURE_SECRET="your_webhook_signature_secret"

  # Encryption
  ENCRYPTION_KEY="your_32_character_encryption_key_here"

  5. External Services (Referenced in codebase)

  # LiveKit (for voice/video)
  LIVEKIT_URL="https://your-livekit-instance.com"
  LIVEKIT_API_KEY="your_livekit_api_key"
  LIVEKIT_API_SECRET="your_livekit_api_secret"

  📝 How to Obtain These Keys:

  Apaleo (CRITICAL - Main PMS Integration):

  1. Register at https://developer.apaleo.com
  2. Create an application to get client_id and client_secret
  3. Get your property_id from your Apaleo dashboard

  Slack (For Alerts):

  1. Go to your Slack workspace settings
  2. Create an "Incoming Webhooks" app
  3. Generate webhook URL for your desired channel

  PagerDuty (For Incident Management):

  1. Login to PagerDuty
  2. Go to Services → Create New Service
  3. Copy the "Integration Key" from the service

  Vault (Production Secrets Management):

  1. Set up HashiCorp Vault instance
  2. Configure Kubernetes authentication or use tokens
  3. Store all other secrets in Vault

  🚨 Security Recommendations:

  1. Never commit these to git - Use .env files or Kubernetes secrets
  2. Use Vault in production for centralized secret management
  3. Rotate credentials regularly especially JWT secrets
  4. Use strong, unique passwords (32+ characters)
  5. Enable 2FA on all external service accounts

  📄 Sample .env File Structure:

  # Copy to .env and fill in your values
  # Apaleo PMS
  APALEO_CLIENT_ID=
  APALEO_CLIENT_SECRET=
  APALEO_PROPERTY_ID=

  # Alerting
  SLACK_WEBHOOK_URL=
  PAGERDUTY_INTEGRATION_KEY=

  # Security
  JWT_SECRET_KEY=
  WEBHOOK_SIGNATURE_SECRET=
  ENCRYPTION_KEY=

  # Infrastructure  
  DATABASE_PASSWORD=
  REDIS_PASSWORD=
  VAULT_URL=
  VAULT_TOKEN=

  # External Services
  LIVEKIT_URL=
  LIVEKIT_API_KEY=
  LIVEKIT_API_SECRET=

  Priority Order for Setup:
  1. Apaleo credentials (essential for PMS functionality)
  2. JWT & encryption keys (essential for security)
  3. Database passwords (essential for data persistence)
  4. Alerting keys (important for monitoring)
  5. External service keys (for advanced features)
