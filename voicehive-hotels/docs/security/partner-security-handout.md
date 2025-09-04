# VoiceHive Hotels Security Overview
## Partner Integration Security Handout

### Executive Summary
VoiceHive Hotels provides a GDPR-compliant, production-grade AI receptionist system designed with security and privacy at its core. All data processing occurs within EU borders, with enterprise-grade encryption and strict access controls.

### Data Residency & GDPR Compliance

#### 🔒 **100% EU Data Processing**
- **Voice Processing**: NVIDIA Riva hosted in EU-WEST-1 (Ireland)
- **Call Routing**: LiveKit Cloud pinned to EU regions only
- **AI Processing**: Azure OpenAI Service in West Europe (Netherlands)
- **Text-to-Speech**: ElevenLabs with Zero Retention Mode enabled

#### 📋 **GDPR Compliance Features**
- **Lawful Basis**: Legitimate interests for call handling, explicit consent for voice cloning
- **Data Retention**: 30-day audio, 90-day transcripts (configurable per hotel)
- **PII Protection**: Automatic redaction of credit cards, passport numbers, personal details
- **Subject Rights**: Automated DSAR handling within 30 days

### Security Architecture

#### 🛡️ **Encryption Standards**
- **At Rest**: AES-256-GCM with AWS KMS key management
- **In Transit**: TLS 1.2+ minimum, modern cipher suites only
- **Per-Tenant**: Separate encryption keys for each hotel

#### 🔐 **Access Control**
- **Zero Trust**: No standing access to production systems
- **MFA Required**: All administrative access requires multi-factor authentication
- **Audit Logging**: Immutable logs of all data access for 7 years
- **Role-Based**: Granular permissions per hotel staff role

### PMS Integration Security

#### 🔗 **Secure API Connectivity**
- **OAuth 2.0**: Industry-standard authentication for all PMS connections
- **Least Privilege**: Only requested scopes (reservations, availability)
- **Circuit Breakers**: Automatic failover if PMS is unavailable
- **No Data Storage**: PMS data is queried in real-time, not cached

#### 🏨 **Supported PMS Partners**
- Oracle OPERA Cloud (via OHIP)
- Mews (Certified Connector)
- Cloudbeds (Partner Program)
- Apaleo (Open APIs)
- SiteMinder Exchange

### Data Flow Diagram

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Caller    │────▶│   Twilio    │────▶│  LiveKit    │
│   (PSTN)    │ EU  │  (EU Edge)  │ EU  │ (EU-WEST-1) │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    Hotel    │◀────│ Orchestrator│◀────│ NVIDIA Riva │
│     PMS     │ API │ (EU-WEST-1) │ EU  │ (EU-WEST-1) │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │Azure OpenAI │
                    │(West Europe)│
                    └─────────────┘
```

### Compliance Certifications
- **ISO 27001**: Information Security Management (in progress)
- **SOC 2 Type II**: Security, Availability, Confidentiality
- **PCI DSS Level 1**: For payment card data handling
- **GDPR**: Full compliance with EU data protection regulations

### Data Subprocessors
| Service | Purpose | Location | DPA Available |
|---------|---------|----------|---------------|
| AWS | Infrastructure | EU (Ireland/Frankfurt) | ✓ |
| Twilio | Telephony | EU Edge Locations | ✓ |
| LiveKit | Media Server | EU-WEST-1 | ✓ |
| Microsoft | Azure OpenAI | West Europe | ✓ |
| ElevenLabs | Text-to-Speech | EU API | ✓ |

### Security Contacts
- **Security Team**: security@voicehive-hotels.com
- **DPO**: dpo@voicehive-hotels.com
- **24/7 SOC**: +44 20 XXXX XXXX
- **Partner Support**: partners@voicehive-hotels.com

### Incident Response
- **Response Time**: < 4 hours for critical incidents
- **Breach Notification**: Within 72 hours to authorities
- **Communication**: Direct notification to affected hotels
- **Post-Incident**: Full RCA within 5 business days

### Technical Requirements for Hotels
1. **Network**: Stable internet (minimum 10 Mbps symmetric)
2. **Firewall**: Allow outbound HTTPS (443) and SIP (5060/5061)
3. **PMS**: API access with read permissions for reservations/availability
4. **Phone System**: SIP trunk or forwarding capability

### Getting Started
1. **Security Review**: Schedule technical review call
2. **DPA Signing**: Execute Data Processing Agreement
3. **API Setup**: Configure PMS integration credentials
4. **Testing**: Validate in sandbox environment
5. **Go Live**: Gradual rollout with monitoring

---
*Last Updated: January 2024*
*Version: 1.0*
