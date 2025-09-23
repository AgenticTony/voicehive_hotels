# Disaster Recovery Runbook

## VoiceHive Hotels - Operational Procedures

### Quick Reference

- **Emergency Hotline**: +1-555-DR-VOICE
- **Incident Commander**: Platform Engineering Lead
- **War Room**: #incident-response (Slack)
- **Status Page**: https://status.voicehive-hotels.com

---

## Pre-Incident Preparation

### Daily Readiness Checklist

- [ ] Verify backup completion status
- [ ] Check cross-region replication health
- [ ] Validate monitoring system status
- [ ] Confirm on-call engineer availability
- [ ] Review weather/infrastructure alerts

### Weekly Readiness Checklist

- [ ] Execute backup restore test
- [ ] Validate failover procedures
- [ ] Update emergency contact information
- [ ] Review and update runbook procedures
- [ ] Conduct team readiness assessment

---

## Incident Detection & Classification

### Automated Detection Triggers

#### Critical (P1) - Immediate Response Required

```bash
# Service completely unavailable
curl -f https://api.voicehive-hotels.com/health || echo "CRITICAL: API Down"

# Database connectivity failure
psql -h $DB_HOST -U $DB_USER -c "SELECT 1" || echo "CRITICAL: Database Down"

# Redis connectivity failure
redis-cli -h $REDIS_HOST ping || echo "CRITICAL: Redis Down"
```

#### High (P2) - Response Within 15 Minutes

```bash
# High error rate (>5%)
curl -s https://api.voicehive-hotels.com/metrics | grep error_rate

# High response time (>5s)
curl -w "%{time_total}" https://api.voicehive-hotels.com/health

# Regional health degradation
aws health describe-events --filter eventTypeCategories=issue
```

### Manual Detection Indicators

- Customer reports of service unavailability
- Partner integration failures
- Monitoring alert fatigue (multiple related alerts)
- Unusual traffic patterns or performance degradation

---

## Regional Failover Procedures

### Scenario: Complete Regional Outage

#### Phase 1: Detection & Assessment (0-5 minutes)

1. **Verify Regional Outage**

```bash
# Check AWS Service Health
aws health describe-events --region eu-west-1

# Verify multi-AZ impact
aws ec2 describe-availability-zones --region eu-west-1

# Check external monitoring
curl -f https://status.aws.amazon.com/
```

2. **Activate Incident Response**

```bash
# Send initial alert
curl -X POST $SLACK_WEBHOOK -d '{
  "text": "🚨 REGIONAL OUTAGE DETECTED - Activating DR Procedures",
  "channel": "#incident-response"
}'

# Page incident commander
curl -X POST $PAGERDUTY_WEBHOOK -d '{
  "incident_key": "regional-outage-'$(date +%s)'",
  "event_type": "trigger",
  "description": "Regional outage detected in eu-west-1"
}'
```

#### Phase 2: Database Failover (5-15 minutes)

1. **Promote Read Replica**

```bash
# Promote RDS read replica
aws rds promote-read-replica \
  --db-instance-identifier voicehive-db-replica-eu-central-1 \
  --region eu-central-1

# Wait for promotion to complete
aws rds wait db-instance-available \
  --db-instance-identifier voicehive-db-replica-eu-central-1 \
  --region eu-central-1
```

2. **Update Database Connections**

```bash
# Update Kubernetes secrets
kubectl patch secret postgres-secret \
  -p '{"data":{"host":"'$(echo -n $NEW_DB_HOST | base64)'"}}' \
  -n voicehive-production

# Restart applications to pick up new connection
kubectl rollout restart deployment/orchestrator -n voicehive-production
```

3. **Verify Database Connectivity**

```bash
# Test database connection
psql -h $NEW_DB_HOST -U $DB_USER -c "SELECT version();"

# Verify data integrity
psql -h $NEW_DB_HOST -U $DB_USER -c "SELECT COUNT(*) FROM hotels;"
```

#### Phase 3: Application Failover (15-25 minutes)

1. **Scale DR Region Infrastructure**

```bash
# Scale up EKS cluster
aws eks update-nodegroup-config \
  --cluster-name voicehive-dr \
  --nodegroup-name primary \
  --scaling-config minSize=3,maxSize=20,desiredSize=6 \
  --region eu-central-1

# Deploy applications
helm upgrade voicehive ./helm/voicehive \
  --namespace voicehive-production \
  --set image.tag=$CURRENT_VERSION \
  --set region=eu-central-1
```

2. **Update Load Balancer Configuration**

```bash
# Update ALB target groups
aws elbv2 modify-target-group \
  --target-group-arn $DR_TARGET_GROUP_ARN \
  --health-check-enabled \
  --region eu-central-1

# Register new targets
aws elbv2 register-targets \
  --target-group-arn $DR_TARGET_GROUP_ARN \
  --targets Id=$DR_INSTANCE_1 Id=$DR_INSTANCE_2 \
  --region eu-central-1
```

#### Phase 4: DNS & Traffic Routing (25-30 minutes)

1. **Update Route 53 Records**

```bash
# Update primary A record
aws route53 change-resource-record-sets \
  --hosted-zone-id $HOSTED_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api.voicehive-hotels.com",
        "Type": "A",
        "AliasTarget": {
          "DNSName": "'$DR_ALB_DNS_NAME'",
          "EvaluateTargetHealth": true,
          "HostedZoneId": "'$DR_ALB_ZONE_ID'"
        }
      }
    }]
  }'

# Verify DNS propagation
dig api.voicehive-hotels.com
```

2. **Validate Service Restoration**

```bash
# Health check
curl -f https://api.voicehive-hotels.com/health

# Functional test
curl -X POST https://api.voicehive-hotels.com/api/v1/calls/test \
  -H "Authorization: Bearer $TEST_TOKEN"

# Performance test
curl -w "%{time_total}" https://api.voicehive-hotels.com/health
```

---

## Database Recovery Procedures

### Scenario: Database Corruption

#### Phase 1: Immediate Response (0-5 minutes)

1. **Stop Write Operations**

```bash
# Put application in read-only mode
kubectl patch configmap app-config \
  -p '{"data":{"READ_ONLY_MODE":"true"}}' \
  -n voicehive-production

# Restart applications
kubectl rollout restart deployment/orchestrator -n voicehive-production
```

2. **Assess Corruption Scope**

```bash
# Check database integrity
psql -h $DB_HOST -U $DB_USER -c "
  SELECT schemaname, tablename,
         pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
  FROM pg_tables
  WHERE schemaname = 'public'
  ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"

# Run integrity checks
psql -h $DB_HOST -U $DB_USER -c "
  DO \$\$
  DECLARE
    r RECORD;
  BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
      EXECUTE 'SELECT COUNT(*) FROM ' || r.tablename;
      RAISE NOTICE 'Table % is accessible', r.tablename;
    END LOOP;
  END
  \$\$;
"
```

#### Phase 2: Recovery Planning (5-15 minutes)

1. **Identify Recovery Point**

```bash
# List available backups
aws rds describe-db-snapshots \
  --db-instance-identifier voicehive-db \
  --snapshot-type automated \
  --query 'DBSnapshots[*].[DBSnapshotIdentifier,SnapshotCreateTime]' \
  --output table

# Check point-in-time recovery options
aws rds describe-db-instances \
  --db-instance-identifier voicehive-db \
  --query 'DBInstances[0].EarliestRestorableTime'
```

2. **Calculate Data Loss**

```bash
# Get last known good transaction
psql -h $DB_HOST -U $DB_USER -c "
  SELECT pg_current_wal_lsn(),
         extract(epoch from now()) as current_timestamp;
"

# Estimate data loss window
echo "Data loss window: $(date -d @$CORRUPTION_TIME) to $(date)"
```

#### Phase 3: Database Restoration (15-45 minutes)

1. **Restore from Backup**

```bash
# Restore RDS instance from snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier voicehive-db-restored \
  --db-snapshot-identifier $SELECTED_SNAPSHOT \
  --db-instance-class db.r5.xlarge \
  --multi-az

# Wait for restoration to complete
aws rds wait db-instance-available \
  --db-instance-identifier voicehive-db-restored
```

2. **Apply Transaction Logs (if available)**

```bash
# Point-in-time recovery (alternative to snapshot)
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier voicehive-db \
  --target-db-instance-identifier voicehive-db-pitr \
  --restore-time $RECOVERY_TIME
```

#### Phase 4: Validation & Service Restoration (45-60 minutes)

1. **Verify Data Integrity**

```bash
# Connect to restored database
export RESTORED_DB_HOST=$(aws rds describe-db-instances \
  --db-instance-identifier voicehive-db-restored \
  --query 'DBInstances[0].Endpoint.Address' \
  --output text)

# Run data validation queries
psql -h $RESTORED_DB_HOST -U $DB_USER -c "
  SELECT
    'hotels' as table_name, COUNT(*) as row_count
  FROM hotels
  UNION ALL
  SELECT
    'calls' as table_name, COUNT(*) as row_count
  FROM calls
  UNION ALL
  SELECT
    'users' as table_name, COUNT(*) as row_count
  FROM users;
"

# Check referential integrity
psql -h $RESTORED_DB_HOST -U $DB_USER -c "
  SELECT conname, conrelid::regclass, confrelid::regclass
  FROM pg_constraint
  WHERE contype = 'f'
  AND NOT EXISTS (
    SELECT 1 FROM pg_constraint c2
    WHERE c2.conname = pg_constraint.conname
    AND c2.connamespace = pg_constraint.connamespace
  );
"
```

2. **Switch to Restored Database**

```bash
# Update application configuration
kubectl patch secret postgres-secret \
  -p '{"data":{"host":"'$(echo -n $RESTORED_DB_HOST | base64)'"}}' \
  -n voicehive-production

# Disable read-only mode
kubectl patch configmap app-config \
  -p '{"data":{"READ_ONLY_MODE":"false"}}' \
  -n voicehive-production

# Restart applications
kubectl rollout restart deployment/orchestrator -n voicehive-production
```

---

## Application Recovery Procedures

### Scenario: Application Failure

#### Phase 1: Assessment (0-5 minutes)

1. **Check Application Health**

```bash
# Kubernetes pod status
kubectl get pods -n voicehive-production -o wide

# Application logs
kubectl logs -f deployment/orchestrator -n voicehive-production --tail=100

# Resource utilization
kubectl top pods -n voicehive-production
```

2. **Identify Failed Components**

```bash
# Check service endpoints
kubectl get endpoints -n voicehive-production

# Test internal connectivity
kubectl exec -it deployment/orchestrator -n voicehive-production -- \
  curl -f http://redis-service:6379/ping

kubectl exec -it deployment/orchestrator -n voicehive-production -- \
  pg_isready -h postgres-service -p 5432
```

#### Phase 2: Service Recovery (5-15 minutes)

1. **Restart Failed Services**

```bash
# Rolling restart
kubectl rollout restart deployment/orchestrator -n voicehive-production
kubectl rollout restart deployment/livekit-agent -n voicehive-production
kubectl rollout restart deployment/tts-router -n voicehive-production

# Check rollout status
kubectl rollout status deployment/orchestrator -n voicehive-production
```

2. **Scale Resources if Needed**

```bash
# Scale up if resource constrained
kubectl scale deployment/orchestrator --replicas=6 -n voicehive-production

# Check HPA status
kubectl get hpa -n voicehive-production
```

#### Phase 3: Validation (15-20 minutes)

1. **Health Checks**

```bash
# Application health endpoints
curl -f https://api.voicehive-hotels.com/health
curl -f https://api.voicehive-hotels.com/health/ready

# Database connectivity
curl -f https://api.voicehive-hotels.com/health/db

# Redis connectivity
curl -f https://api.voicehive-hotels.com/health/redis
```

2. **Functional Testing**

```bash
# Authentication test
curl -X POST https://api.voicehive-hotels.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"test"}'

# API functionality test
curl -X GET https://api.voicehive-hotels.com/api/v1/hotels \
  -H "Authorization: Bearer $TEST_TOKEN"
```

---

## Communication Procedures

### Internal Notifications

#### Immediate Alert (0-2 minutes)

```bash
# Slack notification
curl -X POST $SLACK_WEBHOOK -d '{
  "text": "🚨 INCIDENT: '${INCIDENT_TYPE}' detected at '$(date)'",
  "channel": "#incident-response",
  "attachments": [{
    "color": "danger",
    "fields": [
      {"title": "Severity", "value": "'${SEVERITY}'", "short": true},
      {"title": "Affected Services", "value": "'${AFFECTED_SERVICES}'", "short": true},
      {"title": "Incident Commander", "value": "'${INCIDENT_COMMANDER}'", "short": true}
    ]
  }]
}'

# PagerDuty alert
curl -X POST https://events.pagerduty.com/v2/enqueue \
  -H "Content-Type: application/json" \
  -d '{
    "routing_key": "'$PAGERDUTY_ROUTING_KEY'",
    "event_action": "trigger",
    "payload": {
      "summary": "'${INCIDENT_TYPE}' - '${SEVERITY}'",
      "source": "voicehive-monitoring",
      "severity": "'${SEVERITY}'",
      "custom_details": {
        "affected_services": "'${AFFECTED_SERVICES}'",
        "detection_time": "'$(date -Iseconds)'"
      }
    }
  }'
```

#### Status Updates (Every 15 minutes)

```bash
# Update status page
curl -X POST https://api.statuspage.io/v1/pages/$PAGE_ID/incidents \
  -H "Authorization: OAuth $STATUSPAGE_TOKEN" \
  -d '{
    "incident": {
      "name": "'${INCIDENT_TITLE}'",
      "status": "investigating",
      "impact_override": "'${IMPACT_LEVEL}'",
      "body": "'${STATUS_MESSAGE}'"
    }
  }'
```

### External Communications

#### Customer Notification Template

```bash
# Email notification
cat << EOF | mail -s "Service Status Update" customers@voicehive-hotels.com
Subject: VoiceHive Hotels Service Status Update

Dear Valued Customer,

We are currently experiencing ${INCIDENT_TYPE} affecting ${AFFECTED_SERVICES}.

Impact: ${IMPACT_DESCRIPTION}
Expected Resolution: ${ETA}
Workaround: ${WORKAROUND_INSTRUCTIONS}

We apologize for any inconvenience and will provide updates every 30 minutes.

Status Page: https://status.voicehive-hotels.com
Support: support@voicehive-hotels.com

Best regards,
VoiceHive Hotels Team
EOF
```

---

## Post-Incident Procedures

### Immediate Actions (Within 1 hour)

1. **Service Validation**

```bash
# Comprehensive health check
./scripts/health-check-comprehensive.sh

# Performance validation
./scripts/performance-test.sh

# Data integrity check
./scripts/data-integrity-check.sh
```

2. **Incident Documentation**

```bash
# Create incident report
cat << EOF > incident-report-$(date +%Y%m%d-%H%M).md
# Incident Report: ${INCIDENT_TYPE}

## Summary
- **Start Time**: ${START_TIME}
- **End Time**: ${END_TIME}
- **Duration**: ${DURATION}
- **Severity**: ${SEVERITY}

## Impact
- **Affected Services**: ${AFFECTED_SERVICES}
- **Customer Impact**: ${CUSTOMER_IMPACT}
- **Revenue Impact**: ${REVENUE_IMPACT}

## Timeline
${INCIDENT_TIMELINE}

## Root Cause
${ROOT_CAUSE}

## Resolution
${RESOLUTION_STEPS}

## Action Items
${ACTION_ITEMS}
EOF
```

### Follow-up Actions (Within 24 hours)

1. **Post-Mortem Meeting**

   - Schedule within 24 hours
   - Include all incident responders
   - Review timeline and decisions
   - Identify improvement opportunities

2. **Customer Communication**

   - Send detailed incident report
   - Explain root cause and prevention measures
   - Offer service credits if applicable

3. **Process Improvements**
   - Update runbooks based on lessons learned
   - Implement additional monitoring
   - Schedule preventive maintenance

---

## Emergency Contacts

### Internal Team

- **Incident Commander**: +1-555-0101 (Platform Lead)
- **Technical Lead**: +1-555-0102 (Senior Engineer)
- **Database Admin**: +1-555-0103 (Backend Lead)
- **Network Admin**: +1-555-0104 (DevOps Engineer)

### External Vendors

- **AWS Support**: +1-206-266-4064 (Enterprise Support)
- **Datadog Support**: +1-866-329-4466
- **PagerDuty Support**: +1-844-732-3784

### Management Escalation

- **Engineering Manager**: +1-555-0201
- **CTO**: +1-555-0301
- **CEO**: +1-555-0401

---

## Quick Reference Commands

### Health Checks

```bash
# Application health
curl -f https://api.voicehive-hotels.com/health

# Database connectivity
pg_isready -h $DB_HOST -p 5432

# Redis connectivity
redis-cli -h $REDIS_HOST ping

# Kubernetes cluster health
kubectl get nodes
kubectl get pods -A | grep -v Running
```

### Failover Commands

```bash
# Database failover
aws rds promote-read-replica --db-instance-identifier $REPLICA_ID

# DNS failover
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID --change-batch file://failover-change.json

# Application restart
kubectl rollout restart deployment/orchestrator -n voicehive-production
```

### Monitoring Commands

```bash
# Check metrics
curl -s http://localhost:9090/metrics | grep voicehive

# View logs
kubectl logs -f deployment/orchestrator -n voicehive-production

# Check alerts
curl -s http://alertmanager:9093/api/v1/alerts
```

---

**Document Version**: 1.0  
**Last Updated**: 2024-01-01  
**Next Review**: 2024-04-01
