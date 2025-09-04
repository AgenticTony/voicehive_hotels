# Sprint 0 Quick Reference Card 📋

## Completed Components ✅

### 1. PMS Connector Framework
```bash
# Location
connectors/
├── contracts.py      # Universal interface
├── factory.py        # Dynamic loading
├── capability_matrix.yaml
└── adapters/
    └── apaleo/       # First connector (100% done)

# Test it
python connectors/verify_setup.py

# Use it
from connectors import get_connector
connector = get_connector("apaleo", config)
```

### 2. Security Infrastructure
```bash
# Kubernetes Policies
infra/k8s/gatekeeper/
├── constraint-templates/  # Security rules
└── constraints/          # Applied policies

# HashiCorp Vault
infra/k8s/vault/
├── deployment.yaml       # HA setup
└── setup-scripts/       # Initialize vault

# Evidence Collection
tools/compliance/evidence-collector.sh
```

### 3. CI/CD Pipeline
```bash
# GitHub Actions
.github/workflows/ci.yml

# Features:
- Multi-stage testing
- Security scanning (Trivy, Semgrep)
- Blue-green deployment
- Infrastructure validation
```

### 4. Dockerfiles
```bash
# Production-ready containers
services/orchestrator/Dockerfile
services/connectors/Dockerfile
```

## In Progress 🔄

### Terraform Infrastructure (70%)
**Owner**: [Needs assignment]
```bash
# What's done
infra/terraform/
├── main.tf         # Basic structure
└── variables.tf    # EU regions

# TODO
- [ ] Complete EKS module
- [ ] RDS with encryption
- [ ] S3 compliance buckets
```

### PII Scanner Tool
**Owner**: [Needs assignment]
```bash
# Design ready, needs implementation
tools/pii-scanner.py  # TODO

# Will use:
- Microsoft Presidio
- Custom EU patterns
- Log scanning integration
```

## Key Files to Know 📁

### For Developers
- `WARP.md` - MUST READ before any work
- `connectors/README.md` - How to add new PMS
- `connectors/contracts.py` - Interface to implement
- `connectors/capability_matrix.yaml` - What each PMS supports

### For DevOps
- `infra/k8s/` - All Kubernetes manifests
- `infra/terraform/` - Cloud infrastructure
- `.github/workflows/ci.yml` - CI/CD pipeline

### For Security/Compliance
- `docs/compliance/` - GDPR documents
- `docs/security/partner-security-handout.md`
- `config/security/gdpr-config.yaml`
- `tools/compliance/evidence-collector.sh`

## Common Commands 🛠️

```bash
# Verify setup
make verify-all

# Test connectors
pytest connectors/tests/ -v

# Run security scan
make security-scan

# Generate compliance evidence
./tools/compliance/evidence-collector.sh

# Check what's deployed
kubectl get all -n voicehive
```

## Sprint 0 Checklist ✓

### Done ✅
- [x] PMS Connector SDK
- [x] Apaleo connector 
- [x] Capability matrix
- [x] Golden contract tests
- [x] Security policies (Gatekeeper)
- [x] Vault configuration
- [x] CI/CD pipeline
- [x] GDPR documentation
- [x] Compliance evidence script

### TODO by EOD Day 5
- [ ] Complete Terraform EKS module
- [ ] Deploy monitoring stack
- [ ] Implement PII scanner
- [ ] Run E2E integration test
- [ ] Sprint retrospective

## Key Contacts 🤝

- **Sprint Lead**: Anthony Foran
- **PMS Integrations**: [TBD]
- **Infrastructure**: [TBD]
- **Security**: [TBD]

## Next Sprint Preview 👀

**Sprint 1** - Core Voice Pipeline (Week 2)
- LiveKit Cloud setup
- NVIDIA Riva deployment
- Orchestrator + PMS integration
- First voice call!

---

**Remember**: Check `docs/sprints/sprint-0-status.md` for latest updates!
