# 🌍 WARP.md — VoiceHive Hotels (Multilingual AI Receptionist)

## 🤖 Direct Instructions for Warp AI Agent

You MUST read this document fully before executing any task. Your primary goal is to assist in developing and maintaining this production-grade, partner-ready codebase according to the standards below.

**🔥 CURRENT SPRINT: Sprint 1 (Day 1/5) - Core Voice Pipeline**  
📄 Status: `docs/sprints/sprint-1-status.md` | 📋 Plan: `docs/sprints/sprint-1-plan.md` | 🔧 Commands: `make sprint-status`

---

## How to Interact

- **Context is Key**: Before adding or editing code, search the repo with `rg` (ripgrep) to find existing patterns.
- **Think Step-by-Step**: Before coding, outline the steps, files, and how changes fit the architecture.
- **Partner-First**: Always consider PMS integration patterns - use the connector contracts.
- **Propose, Don't Assume**: If a request is unclear, propose 1–3 options with trade-offs.
- **Lint & Format**: After generating code, remind the user to run the linting/formatting commands.

---

## Absolute Rules

- ❌ **Never** commit secrets or PII. Use env vars + HashiCorp Vault.
- ❌ **Never** break the 80/20 rule: 80% reusable core, 20% vendor adapters.
- ❌ **Never** put vendor-specific logic in the orchestrator.
- ✅ **Always** implement new PMS connectors against the golden contract tests.
- ✅ **Always** validate EU region compliance for data processing.
- ✅ **CRITICAL**: Use `rg` for searches — grep/find are forbidden.

---

## Agent Persona

You are a senior distributed systems architect with expertise in:
- **Real-time Media**: LiveKit, SIP/PSTN, WebRTC, barge-in/endpointing
- **Speech AI**: NVIDIA Riva, ElevenLabs, Azure Speech Services
- **Partner Integrations**: OAuth2, REST/SOAP APIs, webhook normalization
- **Production Systems**: Kubernetes, observability, multi-tenancy, GDPR
- **Backend**: Python (FastAPI), Go, TypeScript, circuit breakers, event sourcing

Priorities: **Security → Reliability → Partner Compatibility → Performance → Simplicity**

---

## 🏗️ Architecture Overview

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   Caller (PSTN)    │────▶│   Media Layer      │────▶│   AI Layer         │
│                    │     │ - LiveKit Cloud    │     │ - NVIDIA Riva ASR  │
└─────────────────────┘     │ - SIP/WebRTC       │     │ - Azure OpenAI     │
                           └─────────────────────┘     │ - TTS Router       │
                                      │                │   (ElevenLabs/Azure)│
                                      ▼                └─────────────────────┘
                           ┌─────────────────────┐              │
                           │   Orchestrator      │◀──────────────┘
                           │ - Call Flow Logic   │
                           │ - Intent Routing    │
                           │ - Function Calling  │
                           └─────────────────────┘
                                      │
                    ┌─────────────────┴────────────────────┐
                    ▼                                   ▼
         ┌─────────────────────┐           ┌─────────────────────┐
         │  PMS Connector SDK  │           │   Compliance Layer  │
         │ - Universal Contract│           │ - GDPR Engine       │
         │ - Capability Matrix │           │ - Consent Manager   │
         │ - Golden Tests      │           │ - PII Redactor      │
         └─────────────────────┘           └─────────────────────┘
                    │
     ┌──────────────│──────────────┬──────────────┬──────────────┐
     ▼              ▼              ▼              ▼              ▼
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
│ Apaleo  │   │  Mews   │   │Cloudbeds│   │  Opera  │   │SiteMinder│
│ Adapter │   │ Adapter │   │ Adapter │   │ Adapter │   │ Adapter │
└─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘
```

---

## 📂 Project Structure

```
voicehive-hotels/
├── WARP.md                      # This file - source of truth
├── LICENSE                      # Proprietary license
├── Makefile                     # Common dev/deploy tasks
├── .gitignore                   # VCS exclusions
├── .pre-commit-config.yaml      # Code quality hooks
├── .github/
│   └── workflows/
│       └── ci.yml               # CI/CD pipeline with security scanning
├── docs/
│   ├── architecture/
│   │   ├── decisions/           # ADRs (001-008 completed)
│   │   └── diagrams/
│   ├── sprints/                 # Sprint plans and retrospectives
│   ├── partners/                # Partner onboarding docs
│   ├── compliance/              # GDPR, security policies
│   │   ├── gdpr-dpia.md         # Data Protection Impact Assessment
│   │   ├── gdpr-ropa.md         # Record of Processing Activities
│   │   ├── gdpr-lia.md          # Legitimate Interest Assessment
│   │   └── gdpr-dpa-template.md # Data Processing Agreement
│   ├── security/
│   │   └── partner-security-handout.md  # Security overview for partners
│   ├── api/                     # External API documentation
│   └── operations/
│       ├── runbooks/            # Operational procedures
│       └── deployment/          # Production deployment guide
├── config/
│   ├── __init__.py              # Module marker
│   ├── security/
│   │   ├── __init__.py          # Module marker
│   │   ├── gdpr-config.yaml     # GDPR compliance settings
│   │   └── pii_redactor.py      # PII redaction utilities
│   └── environments/            # Environment-specific configs
├── connectors/                  # PMS Integration SDK
│   ├── contracts.py             # Universal interface
│   ├── capability_matrix.yaml   # Vendor feature matrix
│   ├── factory.py               # Dynamic connector selection
│   ├── adapters/                # Vendor-specific 20%
│   │   ├── apaleo/
│   │   ├── mews/
│   │   ├── cloudbeds/
│   │   ├── opera/
│   │   └── siteminder/
│   └── tests/
│       ├── golden_contract/     # Universal behavior tests
│       └── vendor_tck/          # Vendor-specific tests
├── services/
│   ├── orchestrator/            # Core call logic
│   │   ├── Dockerfile           # Container definition
│   │   ├── requirements.txt     # Python dependencies
│   │   ├── app.py               # Main FastAPI application
│   │   ├── call_manager.py      # Call state management
│   │   ├── health.py            # Health & metrics endpoints
│   │   ├── utils.py             # Utilities (PIIRedactor)
│   │   └── tests/               # Test suite
│   │       └── test_prometheus_counter_simple.py
│   ├── media/                   # LiveKit agents
│   │   └── livekit-agent/       # LiveKit integration
│   ├── asr/                     # Speech recognition
│   │   └── riva-proxy/          # NVIDIA Riva proxy service
│   ├── tts/                     # Text-to-speech
│   │   └── tts-router/          # TTS routing service
│   └── compliance/              # GDPR services
├── infra/
│   ├── terraform/               # Cloud infrastructure as code
│   │   ├── main.tf              # Core infrastructure
│   │   ├── variables.tf         # EU-region validated vars
│   │   ├── eks.tf               # Kubernetes cluster
│   │   ├── rds.tf               # Encrypted database
│   │   ├── s3.tf                # Compliant storage
│   │   └── vault.tf             # Secrets management
│   ├── k8s/                     # Kubernetes manifests
│   │   ├── base/
│   │   │   ├── deployment-orchestrator.yaml
│   │   │   ├── configmap.yaml
│   │   │   └── hpa.yaml
│   │   ├── gatekeeper/          # Security policies
│   │   │   ├── constraint-templates/
│   │   │   └── constraints/
│   │   ├── vault/               # HashiCorp Vault configs
│   │   │   ├── deployment.yaml
│   │   │   ├── policies/
│   │   │   └── setup-scripts/
│   │   └── helm/
│   │       └── voicehive/       # Helm charts
│   │           ├── Chart.yaml
│   │           ├── values.yaml
│   │           └── templates/
│   └── docker/
│       ├── docker-compose.yml   # Local development stack
│       └── .env.example         # Environment template
└── tools/
    ├── compliance/
    │   └── evidence-collector.sh # Automated audit evidence
    ├── marketplace-generator/   # Auto-generate partner docs
    └── cert-validator/          # Validate PMS compliance
```

---

## 📊 Current Sprint Status (Sprint 1 - Day 1/5)

**Quick Status Check:**
- ✅ Check `docs/sprints/sprint-1-status.md` for detailed progress
- ✅ Use `make sprint-status` for a quick update  
- ✅ Reference `docs/sprints/sprint-1-plan.md` for sprint objectives
- ✅ Run `make verify-all` to check component status

**Sprint 1 Progress: 65% Complete** 🚀
- ✅ LiveKit Agent (100%) - SIP handling, webhook integration
- ✅ Riva ASR Proxy (100%) - NVIDIA client, streaming/offline transcription
- ✅ Orchestrator AI (95%) - Azure OpenAI GPT-4 with function calling, metrics
- ✅ TTS Router Service (100%) - Complete microservice ready for deployment
- ✅ Testing Infrastructure (100%) - Prometheus metrics tests passing
- ⏳ GPU Deployment (0%) - Pending Riva server deployment
- ⏳ Integration Testing (0%) - Next priority

**Major Sprint 1 Achievements:**
- Real NVIDIA Riva ASR integration with streaming WebSocket support
- Azure OpenAI GPT-4 function calling for PMS operations
- Complete TTS router service with ElevenLabs integration
- All services updated to production standards
- Comprehensive Prometheus metrics with test coverage
- Fixed all circular imports and duplicate methods

---

## 🏃 Sprint Plan

### Sprint 0: Foundation & Partner SDK (Week 1)
**Goal**: Production infrastructure + PMS connector framework

- [ ] Set up AWS/Azure accounts with EU regions
- [ ] Deploy base Kubernetes clusters (EKS/AKS)
- [ ] Implement PMS connector contracts
- [ ] Build golden contract test suite
- [ ] Create Apaleo connector (quick win)
- [ ] Set up CI/CD with security scanning
- [ ] Configure HashiCorp Vault for secrets

**Definition of Done**: Apaleo connector passes all golden tests

### Sprint 1: Core Voice Pipeline (Week 2)
**Goal**: End-to-end call flow with real AI services

- [ ] LiveKit Cloud setup with EU pinning
- [ ] NVIDIA Riva deployment on GPU nodes
- [ ] Orchestrator with PMS connector integration
- [ ] Multi-language intent detection
- [ ] ElevenLabs TTS with voice cloning
- [ ] Basic call routing and barge-in
- [ ] Prometheus/Grafana monitoring

**Definition of Done**: Successful multilingual call with PMS lookup

### Sprint 2: Partner Expansion (Week 3)
**Goal**: Multi-PMS support + compliance framework

- [ ] Mews connector implementation
- [ ] Oracle OPERA (OHIP) connector
- [ ] GDPR compliance engine
- [ ] Consent management service
- [ ] PII redaction with Presidio
- [ ] Partner security pack generator
- [ ] Multi-tenant configuration

**Definition of Done**: 3 PMS connectors certified, GDPR compliant

### Sprint 3: Production Hardening (Week 4)
**Goal**: Scale, reliability, and hotel pilot

- [ ] Cloudbeds connector
- [ ] SiteMinder connector
- [ ] Blue-green deployments
- [ ] Chaos engineering tests
- [ ] Load testing (100 concurrent calls)
- [ ] SLA monitoring and alerts
- [ ] First hotel pilot preparation

**Definition of Done**: System handles 100 concurrent calls, 99.9% uptime

---

## 🔧 Development Workflows

### Adding a New PMS Connector

```bash
# 1. Generate connector scaffold
python tools/generate-connector.py --vendor opera --api-type rest

# 2. Implement the adapter
cd connectors/adapters/opera
# Edit connector.py following the PMSConnector protocol

# 3. Run golden contract tests
pytest connectors/tests/golden_contract -k opera

# 4. Add vendor-specific tests
pytest connectors/tests/vendor_tck/opera

# 5. Generate partner documentation
python tools/marketplace-generator/generate.py --vendor opera

# 6. Update capability matrix
# Edit connectors/capability_matrix.yaml
```

### Local Development

```bash
# Start local stack with mock PMS
docker compose -f infra/docker/docker-compose.yml up -d

# Run connector tests
pytest connectors/tests -v

# Test call flow
python tools/call-simulator/simulate.py \
  --pms apaleo \
  --language de \
  --scenario reservation_inquiry
```

### Production Deployment

```bash
# Deploy to staging
kubectl apply -k infra/k8s/overlays/staging

# Run integration tests
pytest tests/integration --env staging

# Blue-green to production
kubectl apply -k infra/k8s/overlays/production
kubectl patch service voicehive -p '{"spec":{"selector":{"version":"blue"}}}'
```

### Security & Compliance Setup

```bash
# 1. Initialize HashiCorp Vault
helm install vault hashicorp/vault \
  --namespace vault \
  --values infra/k8s/vault/values-ha.yaml

# 2. Configure Vault policies and secrets
./infra/k8s/vault/setup-scripts/init-vault.sh
./infra/k8s/vault/setup-scripts/configure-policies.sh

# 3. Apply Kubernetes security policies
kubectl apply -f infra/k8s/gatekeeper/constraint-templates/
kubectl apply -f infra/k8s/gatekeeper/constraints/

# 4. Validate security compliance
kubectl get constraints -A
kubectl describe k8srequiredsecuritycontrols -n voicehive
```

### Partner Security Audit

```bash
# Generate compliance evidence package
./tools/compliance/evidence-collector.sh

# Review generated artifacts
ls -la compliance-evidence-*
tree compliance-evidence-*/

# Validate Terraform compliance
terraform plan -var-file=environments/production.tfvars
terraform validate

# Check GDPR configuration
yq eval '.gdpr_compliance' config/security/gdpr-config.yaml
```

---

## 📋 Coding Standards

### Python
- Type hints required (mypy strict mode)
- Async-first design
- Pydantic for all API models
- Black + isort for formatting
- 100% test coverage for connectors

### Error Handling
- Use domain-specific exceptions
- Implement circuit breakers for external calls
- Structured logging with correlation IDs
- Graceful degradation when PMS unavailable

### Security
- All PII must be redacted in logs
- Secrets only via Vault/environment
- API keys must have minimal scopes
- Regular security scans (Snyk, Trivy)

---

## 🔐 Security & Compliance Requirements

### Infrastructure Security
- **Kubernetes Policies**: Enforced via Gatekeeper/OPA
  - Required security contexts (non-root, read-only root filesystem)
  - Resource limits and requests mandatory
  - Network policies for pod-to-pod communication
  - Service mesh with mTLS (Istio/Linkerd)
- **Secrets Management**: HashiCorp Vault only
  - Auto-unsealing with AWS KMS
  - Dynamic secret rotation (30-day max TTL)
  - Audit logging to CloudWatch/Azure Monitor
- **Container Security**: 
  - Base images scanned with Trivy (no HIGH/CRITICAL)
  - Distroless images preferred
  - SBOM generated for all deployments

### GDPR Compliance
- **Documentation Required**:
  - Data Protection Impact Assessment (DPIA)
  - Record of Processing Activities (RoPA)
  - Legitimate Interest Assessment (LIA)
  - Data Processing Agreement (DPA) per partner
- **Technical Controls**:
  - PII redaction in logs (Presidio integration)
  - Consent tracking with immutable audit trail
  - Data retention: 30 days audio, 90 days transcripts
  - Right to erasure API (< 72 hours SLA)
- **Data Residency**:
  - EU-only regions enforced in Terraform
  - No data transfer outside EU
  - Encrypted at rest (AES-256) and in transit (TLS 1.3)

### Partner Security Requirements
- **Integration Security**:
  - OAuth 2.0/API keys with minimal scopes
  - Webhook signatures mandatory
  - Rate limiting per partner (1000 req/min default)
  - IP allowlisting available
- **Audit & Evidence**:
  - Automated evidence collection script
  - Security questionnaire responses
  - Penetration test results (annual)
  - SOC 2 Type II attestation (in progress)

## 🎯 Key Metrics

### Technical SLOs
- P95 round-trip latency: ≤ 500ms
- Barge-in response: ≤ 100ms
- PMS API response: ≤ 200ms (cached)
- Availability: 99.95%

### Business KPIs
- Connector certification time: < 3 days
- New PMS integration: < 1 week
- Call containment rate: > 80%
- Guest satisfaction: > 4.5/5

---

## 🚀 Quick Commands

```bash
# Validate a connector
make validate-connector VENDOR=mews

# Generate partner docs
make generate-docs VENDOR=opera

# Run load tests
make load-test CALLS=100 DURATION=5m

# Check GDPR compliance
make gdpr-audit TENANT=hotel_xyz

# Deploy hotfix
make deploy-hotfix VERSION=1.2.3 COMPONENT=orchestrator

# Security & Compliance
make security-scan                  # Run Trivy, Snyk, SAST scans
make compliance-evidence            # Generate audit evidence package
make vault-rotate-secrets           # Rotate all secrets in Vault
make gatekeeper-validate            # Check K8s security policies

# Infrastructure
make terraform-plan ENV=production  # Plan infrastructure changes
make terraform-compliance           # Validate EU region compliance
make k8s-security-audit            # Run kube-bench security checks

# Development
make local-up                      # Start local development stack
make local-logs                    # Tail all service logs
make test-integration              # Run integration test suite
make pre-commit                    # Run all pre-commit hooks
```

---

## ⚠️ Important Notes

- **Partner First**: Every feature must consider PMS integration impact
- **EU Compliance**: All data must stay in EU regions
- **Connector Contracts**: Never bypass the universal interface
- **Golden Tests**: New connectors must pass 100% before merge
- **Security Reviews**: All partner integrations need security sign-off

---

This is a **living document**. Update it whenever patterns change or new partners are added.

**Last Updated**: August 2025
**Version**: 3.0 - Production-Ready with Full Security & Compliance
