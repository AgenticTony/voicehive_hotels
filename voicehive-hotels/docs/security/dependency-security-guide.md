# Dependency Security & Vulnerability Management Guide

This guide covers the comprehensive dependency security and vulnerability management system implemented for VoiceHive Hotels.

## Overview

The dependency security system provides:

- **Automated vulnerability scanning** with safety and pip-audit
- **Dependency pinning** with hash verification for supply chain security
- **License compliance checking** and reporting
- **Automated security patch management** workflow
- **Security advisory monitoring** and alerting
- **Comprehensive security dashboards** and reporting

## Quick Start

### 1. Setup Security Tools

```bash
# Install security tools
make security-setup

# Or manually install
pip install -r scripts/security/requirements-security-tools.txt
```

### 2. Run Security Scan

```bash
# Scan all services
make security-scan-deps

# Scan specific service
make security-scan-service SERVICE=orchestrator

# Full security analysis with dashboard
make security-full
```

### 3. Check License Compliance

```bash
# Check license compliance
make license-check

# View results
cat license-compliance-report.json
```

## Core Components

### 1. Dependency Security Manager

The main script `scripts/security/dependency-security-manager.py` provides:

```bash
# Vulnerability scanning
python scripts/security/dependency-security-manager.py scan --service all

# Security updates
python scripts/security/dependency-security-manager.py update --security-only

# Dependency pinning with hashes
python scripts/security/dependency-security-manager.py pin --with-hashes

# Security audit (fails on critical vulnerabilities)
python scripts/security/dependency-security-manager.py audit
```

### 2. License Compliance Checker

The `scripts/security/check-license-compliance.py` script:

```bash
# Check license compliance
python scripts/security/check-license-compliance.py \
  --config config/security/dependency-security-config.yaml \
  --reports license-report-*.json \
  --output compliance-report.json
```

### 3. Security Dashboard Generator

The `scripts/security/generate-security-dashboard.py` creates comprehensive dashboards:

```bash
# Generate HTML dashboard
python scripts/security/generate-security-dashboard.py \
  --vulnerability-reports "vulnerability-*.json" \
  --license-reports "license-*.json" \
  --output security-dashboard.html
```

## Configuration

### Security Configuration File

The main configuration is in `config/security/dependency-security-config.yaml`:

```yaml
vulnerability_scanners:
  safety:
    enabled: true
    severity_threshold: "medium"
  pip_audit:
    enabled: true
    severity_threshold: "medium"

license_compliance:
  allowed_licenses:
    - "MIT"
    - "Apache-2.0"
    - "BSD-3-Clause"
  forbidden_licenses:
    - "GPL-3.0"
    - "AGPL-3.0"

update_policy:
  auto_update_security: true
  auto_update_minor: false
  test_before_update: true

hash_verification:
  enabled: true
  require_hashes: true

notifications:
  severity_threshold: "high"
  channels:
    critical: ["slack", "email", "github_issue"]
    high: ["slack", "email"]
```

### Environment Variables

Set these environment variables for enhanced functionality:

```bash
# Safety API key for enhanced vulnerability data
export SAFETY_API_KEY="your-safety-api-key"

# Slack webhook for notifications
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."

# GitHub token for issue creation
export GITHUB_TOKEN="your-github-token"
```

## Automated Workflows

### GitHub Actions Integration

The system includes comprehensive GitHub Actions workflows:

#### 1. Dependency Security Workflow (`.github/workflows/dependency-security.yml`)

Runs on:

- Every push and PR
- Daily scheduled scans
- Manual triggers

Features:

- Vulnerability scanning for all services
- License compliance auditing
- Automated security updates via PR
- SARIF report generation for GitHub Security tab
- Security dashboard generation

#### 2. Pre-commit Hooks

Configured in `.pre-commit-config.yaml`:

```yaml
# Dependency vulnerability scanning
- repo: https://github.com/pyupio/safety
  hooks:
    - id: safety

# Alternative scanner
- repo: https://github.com/pypa/pip-audit
  hooks:
    - id: pip-audit

# License compliance
- repo: local
  hooks:
    - id: license-check
```

### Makefile Targets

Convenient make targets for common operations:

```bash
# Security scanning
make security-scan-deps          # Scan all dependencies
make security-scan-service SERVICE=orchestrator  # Scan specific service

# Updates and maintenance
make security-update             # Apply security updates
make security-pin-deps          # Pin with hashes
make security-audit             # Audit (fails on critical)

# License compliance
make license-check              # Check license compliance

# Comprehensive analysis
make security-full              # Full security analysis + dashboard
```

## Vulnerability Management

### Severity Levels

The system categorizes vulnerabilities by severity:

- **Critical**: Immediate action required (fix within 24 hours)
- **High**: Fix within 7 days
- **Medium**: Fix within 30 days
- **Low**: Fix in next maintenance cycle

### Automated Response

Based on configuration, the system can:

1. **Automatically create GitHub issues** for critical vulnerabilities
2. **Generate pull requests** with security updates
3. **Send notifications** via Slack/email
4. **Fail CI/CD builds** on critical vulnerabilities
5. **Update security dashboards** with latest status

### Manual Response Workflow

For vulnerabilities requiring manual intervention:

1. **Review the vulnerability report**

   ```bash
   make security-scan-service SERVICE=orchestrator
   ```

2. **Check for available fixes**

   - Review the vulnerability details
   - Check if fixed versions are available
   - Assess compatibility impact

3. **Apply updates**

   ```bash
   # For security-only updates
   make security-update-service SERVICE=orchestrator

   # For manual updates
   # Edit requirements.txt and update specific packages
   pip-compile requirements.in
   ```

4. **Test the updates**

   ```bash
   # Run tests to ensure compatibility
   make test-service SERVICE=orchestrator
   ```

5. **Deploy and verify**

   ```bash
   # Deploy to staging first
   make deploy ENV=staging

   # Verify security scan shows fixes
   make security-audit
   ```

## License Compliance

### Allowed Licenses

The system allows these licenses by default:

- MIT
- Apache-2.0
- BSD-3-Clause
- BSD-2-Clause
- ISC
- Python Software Foundation License
- Mozilla Public License 2.0 (MPL 2.0)

### Forbidden Licenses

These licenses are forbidden due to copyleft restrictions:

- GPL-3.0
- GPL-2.0
- AGPL-3.0
- LGPL-3.0
- LGPL-2.1

### License Violation Response

When forbidden licenses are detected:

1. **Immediate notification** sent to security team
2. **CI/CD build fails** (if configured)
3. **GitHub issue created** automatically
4. **Alternative packages** must be found

### License Review Process

For unknown licenses:

1. **Research the license** terms and compatibility
2. **Consult legal team** if necessary
3. **Update configuration** to allow or forbid
4. **Document the decision** in compliance records

## Supply Chain Security

### Hash Verification

The system implements hash verification for supply chain security:

```bash
# Pin dependencies with hashes
make security-pin-deps

# This generates requirements files like:
# package==1.2.3 \
#     --hash=sha256:abc123... \
#     --hash=sha256:def456...
```

### Trusted Sources

Only install packages from trusted sources:

- pypi.org (official Python Package Index)
- files.pythonhosted.org (official PyPI CDN)

### SBOM Generation

Software Bill of Materials (SBOM) is generated for:

- Container images (via Syft in CI/CD)
- Python dependencies (via pip-licenses)
- License compliance tracking

## Security Dashboards

### HTML Dashboard

The security dashboard provides:

- **Executive summary** with overall security posture
- **Service-level details** with vulnerability counts
- **Trend analysis** (when historical data available)
- **Actionable recommendations** prioritized by risk
- **License compliance status** with violation details

### Metrics and KPIs

Key security metrics tracked:

- **Security Score** (0-100, higher is better)
- **Compliance Score** (0-100, higher is better)
- **Critical Vulnerabilities** (should be 0)
- **Mean Time to Fix** (MTTF) for vulnerabilities
- **Dependency Freshness** (% of up-to-date packages)
- **License Compliance Rate** (% compliant packages)

### Integration with Monitoring

The dashboard integrates with:

- **Prometheus** for metrics collection
- **Grafana** for visualization
- **Slack** for notifications
- **GitHub Security** tab for vulnerability tracking

## Incident Response

### Critical Vulnerability Response

When critical vulnerabilities are detected:

1. **Immediate notification** (within 15 minutes)
2. **Incident ticket** created automatically
3. **Security team** paged if outside business hours
4. **Emergency patch** process initiated
5. **Status page** updated if customer-facing impact

### Response Timeline

- **Critical**: 24 hours maximum
- **High**: 7 days maximum
- **Medium**: 30 days maximum
- **Low**: Next maintenance window

### Communication Plan

- **Internal**: Slack notifications, email alerts
- **External**: Status page updates for customer impact
- **Compliance**: Audit trail maintained for all actions

## Best Practices

### Development Workflow

1. **Use pinned dependencies** with hash verification
2. **Run security scans** before committing
3. **Review dependency updates** carefully
4. **Test thoroughly** after security updates
5. **Monitor security advisories** for used packages

### Dependency Management

1. **Minimize dependencies** - only add what's necessary
2. **Regular updates** - keep dependencies current
3. **Security-first** - prioritize security over features
4. **License awareness** - understand license implications
5. **Supply chain verification** - verify package integrity

### Monitoring and Alerting

1. **Continuous monitoring** - daily automated scans
2. **Proactive alerting** - notify before issues become critical
3. **Trend analysis** - track security posture over time
4. **Regular reviews** - monthly security reviews
5. **Incident learning** - improve processes from incidents

## Troubleshooting

### Common Issues

#### 1. Safety API Rate Limits

```bash
# Use API key to increase rate limits
export SAFETY_API_KEY="your-api-key"

# Or add delays between requests
python scripts/security/dependency-security-manager.py scan --service orchestrator
sleep 10
python scripts/security/dependency-security-manager.py scan --service connectors
```

#### 2. False Positive Vulnerabilities

```bash
# Add to ignore list in config
vulnerability_scanners:
  safety:
    ignore_ids: ["12345", "67890"]
  pip_audit:
    ignore_vulns: ["PYSEC-2023-123"]
```

#### 3. License Detection Issues

```bash
# Manual license verification
pip show package-name

# Update license mappings in check-license-compliance.py
# Add to license normalization mappings
```

#### 4. Hash Verification Failures

```bash
# Regenerate hashes
pip-compile --generate-hashes requirements.in

# Or disable temporarily (not recommended)
pip install --trusted-host pypi.org package-name
```

### Getting Help

1. **Check logs** in GitHub Actions workflow runs
2. **Review configuration** in `config/security/dependency-security-config.yaml`
3. **Run with verbose output** using `--verbose` flag
4. **Consult documentation** in `docs/security/`
5. **Contact security team** for critical issues

## Integration Examples

### CI/CD Pipeline Integration

```yaml
# .github/workflows/security.yml
- name: Security Scan
  run: |
    python scripts/security/dependency-security-manager.py audit
    if [ $? -ne 0 ]; then
      echo "Critical vulnerabilities found!"
      exit 1
    fi
```

### Pre-deployment Checks

```bash
#!/bin/bash
# scripts/pre-deploy-security-check.sh

echo "Running pre-deployment security checks..."

# Check for critical vulnerabilities
python scripts/security/dependency-security-manager.py audit
if [ $? -ne 0 ]; then
  echo "❌ Critical vulnerabilities found. Deployment blocked."
  exit 1
fi

# Check license compliance
make license-check
if grep -q "forbidden" license-compliance-report.json; then
  echo "❌ License violations found. Deployment blocked."
  exit 1
fi

echo "✅ Security checks passed. Deployment approved."
```

### Monitoring Integration

```python
# Example Prometheus metrics
from prometheus_client import Counter, Gauge

vulnerability_counter = Counter('vulnerabilities_total', 'Total vulnerabilities', ['severity', 'service'])
security_score_gauge = Gauge('security_score', 'Security score', ['service'])
license_compliance_gauge = Gauge('license_compliance_rate', 'License compliance rate')
```

This comprehensive dependency security system ensures that VoiceHive Hotels maintains a strong security posture while enabling rapid development and deployment.
