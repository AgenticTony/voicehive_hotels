# VoiceHive Hotels Security Incident Response Procedures

## Overview

This document outlines the procedures for detecting, responding to, and recovering from security incidents in the VoiceHive Hotels system. It provides clear escalation paths, containment strategies, and recovery procedures to minimize impact and ensure compliance with security standards.

## Incident Classification

### Severity Levels

#### Critical (P0)

- **Impact**: Customer data breach, system compromise, regulatory violation
- **Response Time**: Immediate (< 15 minutes)
- **Examples**:
  - Unauthorized access to customer PII
  - Ransomware attack
  - Complete system compromise
  - Data exfiltration detected

#### High (P1)

- **Impact**: Potential data exposure, service disruption, security control failure
- **Response Time**: < 1 hour
- **Examples**:
  - Failed authentication attempts spike
  - Suspicious admin activity
  - Vulnerability exploitation attempts
  - Unauthorized API access

#### Medium (P2)

- **Impact**: Security policy violation, minor vulnerability
- **Response Time**: < 4 hours
- **Examples**:
  - Policy violations
  - Non-critical vulnerability discovery
  - Suspicious but contained activity

#### Low (P3)

- **Impact**: Security awareness, informational
- **Response Time**: < 24 hours
- **Examples**:
  - Security scan findings
  - Policy updates needed
  - Training requirements

## Incident Response Team

### Core Team Members

| Role                   | Primary       | Backup       | Contact     |
| ---------------------- | ------------- | ------------ | ----------- |
| **Incident Commander** | John Smith    | Jane Doe     | +1-555-0100 |
| **Security Lead**      | Alice Johnson | Bob Wilson   | +1-555-0101 |
| **Engineering Lead**   | Charlie Brown | Diana Prince | +1-555-0102 |
| **DevOps Lead**        | Eve Adams     | Frank Miller | +1-555-0103 |
| **Legal Counsel**      | Grace Lee     | Henry Ford   | +1-555-0104 |
| **Communications**     | Ivy Chen      | Jack Ryan    | +1-555-0105 |

### Escalation Matrix

```
P0 (Critical) → Incident Commander + Security Lead + Engineering Lead
P1 (High)     → Security Lead + Engineering Lead
P2 (Medium)   → Security Lead + On-Call Engineer
P3 (Low)      → Security Team
```

## Detection and Alerting

### Automated Detection

#### Security Monitoring Alerts

1. **Authentication Anomalies**

   ```bash
   # Failed login attempts > 10 in 5 minutes
   rate(auth_failed_attempts_total[5m]) > 2

   # Multiple failed logins from same IP
   count by (source_ip) (rate(auth_failed_attempts_total[5m])) > 5
   ```

2. **Suspicious API Activity**

   ```bash
   # Unusual API usage patterns
   rate(http_requests_total{status=~"4.."}[5m]) > 0.1

   # Unauthorized endpoint access
   increase(http_requests_total{status="403"}[5m]) > 50
   ```

3. **Data Access Anomalies**

   ```bash
   # Large data exports
   increase(data_export_bytes_total[5m]) > 100000000

   # PII access outside business hours
   pii_access_total and on() hour() < 8 or hour() > 18
   ```

4. **Infrastructure Anomalies**

   ```bash
   # Unexpected privilege escalation
   increase(privilege_escalation_total[5m]) > 0

   # Suspicious network connections
   increase(network_connections_total{destination!~"internal.*"}[5m]) > 1000
   ```

### Manual Detection Sources

- Security team monitoring
- Customer reports
- Partner notifications
- Vulnerability scanners
- Penetration testing results
- Audit findings

## Incident Response Procedures

### Phase 1: Detection and Analysis (0-15 minutes)

#### 1.1 Initial Alert Triage

**Automated Response:**

```bash
# Security alert webhook triggers
curl -X POST https://api.voicehive.com/security/alert \
  -H "Content-Type: application/json" \
  -d '{
    "alert_type": "authentication_anomaly",
    "severity": "high",
    "source_ip": "1.2.3.4",
    "timestamp": "2025-01-22T10:30:00Z",
    "details": {...}
  }'
```

**Manual Steps:**

1. **Acknowledge Alert**

   ```bash
   # Update incident status
   kubectl patch incident security-001 \
     --type merge -p '{"status":"acknowledged","assignee":"security-team"}'
   ```

2. **Initial Assessment**

   - Review alert details and context
   - Check for related alerts or patterns
   - Determine if incident is ongoing
   - Assess potential impact scope

3. **Severity Classification**
   - Apply severity matrix
   - Consider data sensitivity
   - Evaluate business impact
   - Determine escalation needs

#### 1.2 Evidence Collection

**Immediate Data Preservation:**

```bash
# Capture system state
kubectl get pods,services,ingress -n voicehive -o yaml > incident-state-$(date +%Y%m%d-%H%M%S).yaml

# Export relevant logs
kubectl logs deployment/orchestrator -n voicehive --since=1h > orchestrator-logs-$(date +%Y%m%d-%H%M%S).log

# Capture network traffic (if applicable)
tcpdump -i eth0 -w incident-traffic-$(date +%Y%m%d-%H%M%S).pcap
```

**Database Forensics:**

```bash
# Capture audit logs
kubectl exec -n voicehive deployment/orchestrator -- \
  psql $DATABASE_URL -c "
  SELECT * FROM audit_log
  WHERE created_at >= NOW() - INTERVAL '2 hours'
  ORDER BY created_at DESC;" > audit-logs-$(date +%Y%m%d-%H%M%S).csv

# Export user activity
kubectl exec -n voicehive deployment/orchestrator -- \
  psql $DATABASE_URL -c "
  SELECT user_id, action, ip_address, timestamp
  FROM user_activity
  WHERE timestamp >= NOW() - INTERVAL '2 hours';" > user-activity-$(date +%Y%m%d-%H%M%S).csv
```

### Phase 2: Containment (15-60 minutes)

#### 2.1 Immediate Containment

**Block Suspicious IPs:**

```bash
# Add IP to blocklist
kubectl patch configmap security-config -n voicehive \
  --type merge -p '{"data":{"blocked_ips":"1.2.3.4,5.6.7.8"}}'

# Apply network policy
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: block-suspicious-ips
  namespace: voicehive
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 1.2.3.4/32
        - 5.6.7.8/32
EOF
```

**Disable Compromised Accounts:**

```bash
# Disable user account
kubectl exec -n voicehive deployment/orchestrator -- \
  python -c "
from auth_models import User
user = User.get_by_id('compromised_user_id')
user.disable()
user.save()
"

# Revoke all sessions
kubectl exec -n voicehive deployment/orchestrator -- \
  redis-cli -h redis.voicehive.com DEL "session:compromised_user_id:*"
```

**Rotate Compromised Credentials:**

```bash
# Rotate API keys
kubectl exec -n voicehive deployment/orchestrator -- \
  vault kv delete secret/api-keys/compromised_key

# Generate new JWT secret
NEW_SECRET=$(openssl rand -base64 32)
kubectl create secret generic jwt-secret \
  --from-literal=secret=$NEW_SECRET \
  --dry-run=client -o yaml | kubectl apply -f -

# Force re-authentication for all users
kubectl exec -n voicehive deployment/orchestrator -- \
  redis-cli -h redis.voicehive.com FLUSHDB
```

#### 2.2 System Isolation

**Isolate Affected Services:**

```bash
# Scale down compromised services
kubectl scale deployment/compromised-service --replicas=0 -n voicehive

# Redirect traffic to clean instances
kubectl patch service voicehive-service -n voicehive \
  --type='json' \
  -p='[{"op": "replace", "path": "/spec/selector/version", "value": "clean"}]'
```

**Enable Enhanced Monitoring:**

```bash
# Increase logging verbosity
kubectl set env deployment/orchestrator LOG_LEVEL=DEBUG -n voicehive
kubectl set env deployment/orchestrator AUDIT_LOGGING=enhanced -n voicehive

# Enable real-time monitoring
kubectl apply -f infra/k8s/monitoring/enhanced-security-monitoring.yaml
```

### Phase 3: Eradication (1-4 hours)

#### 3.1 Root Cause Analysis

**System Analysis:**

```bash
# Check for malware or unauthorized files
kubectl exec -n voicehive deployment/orchestrator -- \
  find /app -type f -newer /tmp/incident_start_time -ls

# Verify system integrity
kubectl exec -n voicehive deployment/orchestrator -- \
  sha256sum /app/*.py > current-checksums.txt
diff baseline-checksums.txt current-checksums.txt
```

**Vulnerability Assessment:**

```bash
# Run security scan
kubectl exec -n voicehive deployment/orchestrator -- \
  python -m safety check

# Check for known vulnerabilities
kubectl exec -n voicehive deployment/orchestrator -- \
  pip-audit --format=json > vulnerability-report.json
```

#### 3.2 Threat Removal

**Clean Compromised Systems:**

```bash
# Rebuild compromised containers
docker build -t voicehive/orchestrator:clean .
kubectl set image deployment/orchestrator orchestrator=voicehive/orchestrator:clean -n voicehive

# Update base images
kubectl apply -f infra/k8s/base/deployment-orchestrator.yaml
```

**Patch Vulnerabilities:**

```bash
# Apply security patches
kubectl apply -f security-patches/

# Update dependencies
kubectl exec -n voicehive deployment/orchestrator -- \
  pip install --upgrade -r requirements.txt
```

### Phase 4: Recovery (4-24 hours)

#### 4.1 System Restoration

**Gradual Service Restoration:**

```bash
# Restore services incrementally
kubectl scale deployment/orchestrator --replicas=1 -n voicehive
# Monitor for 15 minutes
kubectl scale deployment/orchestrator --replicas=3 -n voicehive
# Monitor for 30 minutes
kubectl scale deployment/orchestrator --replicas=5 -n voicehive
```

**Validate Security Controls:**

```bash
# Test authentication
python tests/security/test_auth_system.py

# Verify access controls
python tests/security/test_rbac.py

# Check audit logging
python tests/security/test_audit_logging.py
```

#### 4.2 Monitoring Enhancement

**Deploy Additional Monitoring:**

```bash
# Enhanced security monitoring
kubectl apply -f infra/k8s/monitoring/security-enhanced.yaml

# Deploy SIEM integration
kubectl apply -f infra/k8s/monitoring/siem-connector.yaml
```

### Phase 5: Post-Incident Activities (24-72 hours)

#### 5.1 Forensic Analysis

**Detailed Investigation:**

```bash
# Generate comprehensive incident report
python scripts/generate_incident_report.py \
  --incident-id security-001 \
  --start-time "2025-01-22T10:00:00Z" \
  --end-time "2025-01-22T14:00:00Z"

# Analyze attack vectors
python scripts/analyze_attack_vectors.py \
  --log-files "orchestrator-logs-*.log" \
  --audit-logs "audit-logs-*.csv"
```

#### 5.2 Lessons Learned

**Post-Incident Review Meeting:**

- Timeline reconstruction
- Response effectiveness analysis
- Process improvement identification
- Tool and training needs assessment

## Communication Procedures

### Internal Communication

#### Incident Declaration

```
🚨 SECURITY INCIDENT DECLARED
Incident ID: SEC-2025-001
Severity: P1 (High)
Type: Unauthorized Access Attempt
Status: Containment in Progress
Incident Commander: John Smith
Next Update: 30 minutes
```

#### Status Updates

```
📊 INCIDENT UPDATE - SEC-2025-001
Time: 11:30 AM EST
Status: Contained
Actions Taken:
- Blocked suspicious IP addresses
- Disabled compromised accounts
- Enhanced monitoring deployed
Next Steps:
- Root cause analysis
- System hardening
Next Update: 1 hour
```

### External Communication

#### Customer Notification (if required)

```
Subject: Security Incident Notification - VoiceHive Hotels

Dear Valued Customer,

We are writing to inform you of a security incident that occurred on [DATE].
We detected and contained unauthorized access attempts to our system.

What Happened:
[Brief description of incident]

What Information Was Involved:
[Specific data types affected]

What We Are Doing:
[Response actions taken]

What You Can Do:
[Recommended customer actions]

Contact Information:
security@voicehive.com
+1-555-SECURITY

We sincerely apologize for any inconvenience this may cause.

VoiceHive Security Team
```

#### Regulatory Notification

**GDPR Breach Notification (if applicable):**

- Must be reported within 72 hours
- Include nature of breach, categories of data, number of affected individuals
- Submit to relevant supervisory authority

**Industry Notifications:**

- Partner notifications if their data is affected
- Vendor notifications if supply chain is compromised

## Compliance and Legal Considerations

### Evidence Preservation

**Chain of Custody:**

```bash
# Create evidence package
tar -czf evidence-SEC-2025-001-$(date +%Y%m%d).tar.gz \
  incident-state-*.yaml \
  orchestrator-logs-*.log \
  audit-logs-*.csv \
  user-activity-*.csv

# Generate hash for integrity
sha256sum evidence-SEC-2025-001-*.tar.gz > evidence-hash.txt

# Store securely
aws s3 cp evidence-SEC-2025-001-*.tar.gz \
  s3://voicehive-security-evidence/ \
  --server-side-encryption AES256
```

### Regulatory Requirements

#### Data Breach Notifications

- **GDPR**: 72 hours to supervisory authority, without undue delay to individuals
- **CCPA**: Without unreasonable delay
- **HIPAA**: 60 days (if healthcare data involved)

#### Documentation Requirements

- Incident timeline
- Impact assessment
- Response actions
- Lessons learned
- Process improvements

## Recovery and Business Continuity

### Service Restoration Priorities

1. **Critical Services** (RTO: 1 hour)

   - Authentication system
   - Core API endpoints
   - Database access

2. **Important Services** (RTO: 4 hours)

   - Call management
   - PMS integration
   - Monitoring systems

3. **Standard Services** (RTO: 24 hours)
   - Reporting systems
   - Administrative interfaces
   - Non-critical integrations

### Backup and Recovery

**Data Recovery:**

```bash
# Restore from clean backup
kubectl exec -n voicehive deployment/postgresql -- \
  pg_restore -d voicehive /backups/clean-backup-$(date -d "yesterday" +%Y%m%d).sql

# Verify data integrity
kubectl exec -n voicehive deployment/orchestrator -- \
  python scripts/verify_data_integrity.py
```

**Configuration Recovery:**

```bash
# Restore known-good configuration
kubectl apply -f config-backups/clean-config-$(date -d "yesterday" +%Y%m%d)/

# Verify configuration
kubectl get configmaps,secrets -n voicehive
```

## Prevention and Hardening

### Immediate Hardening Actions

**Security Controls Enhancement:**

```bash
# Enable additional security features
kubectl set env deployment/orchestrator SECURITY_ENHANCED=true -n voicehive
kubectl set env deployment/orchestrator MFA_REQUIRED=true -n voicehive

# Deploy additional monitoring
kubectl apply -f infra/k8s/security/enhanced-monitoring.yaml

# Update security policies
kubectl apply -f infra/k8s/security/strict-network-policies.yaml
```

### Long-term Improvements

1. **Security Architecture Review**

   - Zero-trust implementation
   - Micro-segmentation
   - Enhanced monitoring

2. **Process Improvements**

   - Automated incident response
   - Enhanced training programs
   - Regular security assessments

3. **Technology Upgrades**
   - Advanced threat detection
   - Behavioral analytics
   - Automated remediation

## Testing and Validation

### Incident Response Testing

**Tabletop Exercises:**

```bash
# Schedule quarterly tabletop exercises
python scripts/schedule_tabletop_exercise.py \
  --scenario "data_breach" \
  --participants "security-team,engineering-team,legal"
```

**Simulation Testing:**

```bash
# Run incident response simulation
python scripts/incident_simulation.py \
  --scenario "unauthorized_access" \
  --duration "2h" \
  --validate-response
```

### Security Validation

**Penetration Testing:**

- Quarterly external penetration tests
- Monthly internal security assessments
- Continuous vulnerability scanning

**Red Team Exercises:**

- Annual red team engagements
- Simulated attack scenarios
- Response capability validation

## Metrics and Reporting

### Key Performance Indicators

1. **Detection Time**: Time from incident occurrence to detection
2. **Response Time**: Time from detection to initial response
3. **Containment Time**: Time from response to containment
4. **Recovery Time**: Time from containment to full recovery

### Incident Metrics Dashboard

```bash
# Deploy incident metrics dashboard
kubectl apply -f infra/k8s/monitoring/incident-metrics-dashboard.yaml

# View current metrics
curl -s https://grafana.voicehive.com/api/dashboards/db/security-incidents
```

### Reporting Schedule

- **Daily**: Security operations summary
- **Weekly**: Incident trend analysis
- **Monthly**: Security posture report
- **Quarterly**: Incident response effectiveness review
- **Annually**: Comprehensive security assessment

## Contact Information

### Emergency Contacts

- **Security Hotline**: +1-555-SECURITY (24/7)
- **Incident Commander**: +1-555-0100
- **Legal Counsel**: +1-555-0104
- **Executive Team**: +1-555-EXEC

### External Contacts

- **Law Enforcement**: FBI Cyber Division +1-855-292-3937
- **CERT**: US-CERT +1-888-282-0870
- **Legal Counsel**: External counsel +1-555-LAW-FIRM

### Vendor Contacts

- **Cloud Provider**: AWS Support (Enterprise)
- **Security Vendor**: CrowdStrike Support
- **Monitoring Vendor**: Datadog Support

## Appendices

### Appendix A: Incident Classification Matrix

| Impact | Confidentiality  | Integrity         | Availability       | Severity |
| ------ | ---------------- | ----------------- | ------------------ | -------- |
| High   | Data Breach      | Data Corruption   | Service Down       | P0       |
| Medium | Data Exposure    | Data Modification | Service Degraded   | P1       |
| Low    | Policy Violation | Minor Changes     | Performance Impact | P2       |

### Appendix B: Communication Templates

Available in `/docs/security/templates/`:

- Incident declaration template
- Status update template
- Customer notification template
- Regulatory notification template
- Post-incident report template

### Appendix C: Legal and Regulatory Requirements

- GDPR compliance checklist
- CCPA notification requirements
- Industry-specific regulations
- Contractual obligations

### Appendix D: Technical Procedures

- Evidence collection scripts
- Containment automation
- Recovery procedures
- Validation checklists
