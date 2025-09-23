# VoiceHive Hotels Production Deployment Runbook

## Overview

This runbook provides step-by-step procedures for deploying VoiceHive Hotels to production environments. It covers pre-deployment checks, deployment procedures, post-deployment validation, and rollback procedures.

## Prerequisites

### Required Access

- [ ] AWS CLI configured with appropriate permissions
- [ ] kubectl configured for target EKS cluster
- [ ] Docker registry access (ECR)
- [ ] HashiCorp Vault access
- [ ] Monitoring system access (Grafana, Prometheus)
- [ ] PagerDuty access for alerting

### Required Tools

```bash
# Install required tools
aws --version          # AWS CLI v2.x
kubectl version        # Kubernetes CLI v1.28+
docker --version       # Docker v20.x+
helm version          # Helm v3.x+
terraform --version   # Terraform v1.x+
```

### Environment Variables

```bash
export AWS_REGION="us-west-2"
export CLUSTER_NAME="voicehive-production"
export NAMESPACE="voicehive"
export IMAGE_TAG="v1.0.0"
export VAULT_ADDR="https://vault.voicehive.com"
```

## Pre-Deployment Checklist

### 1. Code Quality Checks

```bash
# Run all tests
cd voicehive-hotels
make test-all

# Security scan
make security-scan

# Performance tests
make load-test

# Integration tests
make integration-test
```

**Acceptance Criteria:**

- [ ] All unit tests pass (100% success rate)
- [ ] Integration tests pass (100% success rate)
- [ ] Load tests meet performance SLAs
- [ ] Security scan shows no critical vulnerabilities
- [ ] Code coverage > 80%

### 2. Infrastructure Readiness

```bash
# Verify EKS cluster health
kubectl get nodes
kubectl get pods -n kube-system

# Check resource availability
kubectl top nodes
kubectl describe nodes

# Verify persistent volumes
kubectl get pv,pvc -n $NAMESPACE
```

**Acceptance Criteria:**

- [ ] All nodes are Ready
- [ ] CPU usage < 70% on all nodes
- [ ] Memory usage < 80% on all nodes
- [ ] Disk usage < 80% on all nodes
- [ ] All system pods are Running

### 3. External Dependencies

```bash
# Test database connectivity
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  python -c "import asyncpg; print('DB connection test')"

# Test Redis connectivity
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  redis-cli -h redis.voicehive.com ping

# Test Vault connectivity
vault status

# Test LiveKit connectivity
curl -f https://livekit.voicehive.com/health
```

**Acceptance Criteria:**

- [ ] Database is accessible and healthy
- [ ] Redis is accessible and responsive
- [ ] Vault is unsealed and accessible
- [ ] LiveKit service is healthy
- [ ] External APIs are responsive

### 4. Configuration Validation

```bash
# Validate Kubernetes manifests
kubectl apply --dry-run=client -f infra/k8s/base/

# Validate Helm charts
helm template voicehive infra/helm/voicehive/ --values infra/helm/voicehive/values.yaml

# Check secrets and configmaps
kubectl get secrets,configmaps -n $NAMESPACE
```

**Acceptance Criteria:**

- [ ] All Kubernetes manifests are valid
- [ ] Helm chart renders without errors
- [ ] All required secrets exist
- [ ] Configuration values are correct

## Deployment Procedures

### 1. Build and Push Images

```bash
# Build all service images
make build-images TAG=$IMAGE_TAG

# Push to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $ECR_REGISTRY

make push-images TAG=$IMAGE_TAG REGISTRY=$ECR_REGISTRY
```

**Verification:**

```bash
# Verify images exist in registry
aws ecr describe-images --repository-name voicehive/orchestrator --image-ids imageTag=$IMAGE_TAG
aws ecr describe-images --repository-name voicehive/livekit-agent --image-ids imageTag=$IMAGE_TAG
aws ecr describe-images --repository-name voicehive/tts-router --image-ids imageTag=$IMAGE_TAG
```

### 2. Database Migrations

```bash
# Backup current database
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  pg_dump $DATABASE_URL > backup-$(date +%Y%m%d-%H%M%S).sql

# Run migrations
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  alembic upgrade head

# Verify migration success
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  alembic current
```

**Rollback Plan:**

```bash
# If migrations fail, rollback
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  alembic downgrade -1

# Restore from backup if needed
kubectl exec -i -n $NAMESPACE deployment/orchestrator -- \
  psql $DATABASE_URL < backup-YYYYMMDD-HHMMSS.sql
```

### 3. Blue-Green Deployment

#### Step 1: Deploy Green Environment

```bash
# Create green namespace
kubectl create namespace $NAMESPACE-green

# Deploy to green environment
helm upgrade --install voicehive-green infra/helm/voicehive/ \
  --namespace $NAMESPACE-green \
  --values infra/helm/voicehive/values.yaml \
  --set image.tag=$IMAGE_TAG \
  --set environment=green

# Wait for deployment to be ready
kubectl rollout status deployment/orchestrator -n $NAMESPACE-green
kubectl rollout status deployment/livekit-agent -n $NAMESPACE-green
kubectl rollout status deployment/tts-router -n $NAMESPACE-green
```

#### Step 2: Validate Green Environment

```bash
# Health checks
kubectl exec -n $NAMESPACE-green deployment/orchestrator -- \
  curl -f http://localhost:8000/health

# Smoke tests
kubectl exec -n $NAMESPACE-green deployment/orchestrator -- \
  python -m pytest tests/smoke/ -v

# Load balancer readiness
kubectl get ingress -n $NAMESPACE-green
```

#### Step 3: Switch Traffic

```bash
# Update ingress to point to green environment
kubectl patch ingress voicehive-ingress -n $NAMESPACE-green \
  --type='json' \
  -p='[{"op": "replace", "path": "/spec/rules/0/http/paths/0/backend/service/name", "value": "voicehive-green"}]'

# Verify traffic switch
curl -H "Host: api.voicehive.com" https://api.voicehive.com/health
```

#### Step 4: Monitor and Validate

```bash
# Monitor error rates
kubectl logs -f deployment/orchestrator -n $NAMESPACE-green

# Check metrics
curl -s https://prometheus.voicehive.com/api/v1/query?query=rate\(http_requests_total\[5m\]\)

# Validate business metrics
curl -s https://api.voicehive.com/metrics | grep voicehive_calls_total
```

### 4. Configuration Updates

```bash
# Update ConfigMaps
kubectl apply -f infra/k8s/base/configmap-gdpr.yaml

# Update Secrets (if needed)
kubectl create secret generic voicehive-secrets \
  --from-env-file=.env.production \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart deployments to pick up new config
kubectl rollout restart deployment/orchestrator -n $NAMESPACE-green
```

## Post-Deployment Validation

### 1. Health Checks

```bash
# System health
curl -f https://api.voicehive.com/health

# Service-specific health checks
curl -f https://api.voicehive.com/v1/calls/health
curl -f https://livekit.voicehive.com/health
curl -f https://tts.voicehive.com/health
```

**Expected Results:**

- [ ] All health endpoints return 200 OK
- [ ] All services report "healthy" status
- [ ] Database connectivity confirmed
- [ ] External service connectivity confirmed

### 2. Functional Testing

```bash
# Authentication test
TOKEN=$(curl -s -X POST https://api.voicehive.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@voicehive.com","password":"test123"}' \
  | jq -r '.access_token')

# API functionality test
curl -H "Authorization: Bearer $TOKEN" \
  https://api.voicehive.com/v1/calls

# Webhook test
curl -X POST https://api.voicehive.com/v1/webhooks/call-events \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"test","data":{}}'
```

**Expected Results:**

- [ ] Authentication succeeds
- [ ] API endpoints respond correctly
- [ ] Webhooks process successfully
- [ ] Rate limiting works as expected

### 3. Performance Validation

```bash
# Response time check
curl -w "@curl-format.txt" -o /dev/null -s https://api.voicehive.com/health

# Load test (light)
ab -n 100 -c 10 https://api.voicehive.com/health

# Memory and CPU usage
kubectl top pods -n $NAMESPACE-green
```

**Acceptance Criteria:**

- [ ] Response times < 200ms for health checks
- [ ] Response times < 500ms for API calls
- [ ] CPU usage < 50% under normal load
- [ ] Memory usage < 70% under normal load
- [ ] No memory leaks detected

### 4. Monitoring and Alerting

```bash
# Verify metrics collection
curl -s https://prometheus.voicehive.com/api/v1/label/__name__/values | \
  grep voicehive

# Check alert rules
curl -s https://prometheus.voicehive.com/api/v1/rules | \
  jq '.data.groups[].rules[] | select(.type=="alerting")'

# Test alerting (optional)
kubectl scale deployment/orchestrator --replicas=0 -n $NAMESPACE-green
# Wait for alert, then scale back up
kubectl scale deployment/orchestrator --replicas=3 -n $NAMESPACE-green
```

**Expected Results:**

- [ ] All metrics are being collected
- [ ] Alert rules are active
- [ ] Dashboards show current data
- [ ] Alerts fire when expected

## Rollback Procedures

### 1. Immediate Rollback (Traffic Switch)

```bash
# Switch traffic back to blue environment
kubectl patch ingress voicehive-ingress -n $NAMESPACE \
  --type='json' \
  -p='[{"op": "replace", "path": "/spec/rules/0/http/paths/0/backend/service/name", "value": "voicehive"}]'

# Verify rollback
curl -H "Host: api.voicehive.com" https://api.voicehive.com/health
```

**Timeline:** < 2 minutes

### 2. Application Rollback

```bash
# Rollback to previous Helm release
helm rollback voicehive -n $NAMESPACE

# Verify rollback status
helm status voicehive -n $NAMESPACE
kubectl rollout status deployment/orchestrator -n $NAMESPACE
```

**Timeline:** 5-10 minutes

### 3. Database Rollback

```bash
# Rollback database migrations
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  alembic downgrade $PREVIOUS_REVISION

# Or restore from backup
kubectl exec -i -n $NAMESPACE deployment/orchestrator -- \
  psql $DATABASE_URL < backup-YYYYMMDD-HHMMSS.sql
```

**Timeline:** 10-30 minutes (depending on data size)

### 4. Full Infrastructure Rollback

```bash
# Rollback Terraform changes
cd infra/terraform
terraform plan -target=module.eks
terraform apply -target=module.eks

# Rollback Kubernetes manifests
git checkout $PREVIOUS_COMMIT -- infra/k8s/
kubectl apply -f infra/k8s/base/
```

**Timeline:** 30-60 minutes

## Emergency Procedures

### 1. Service Outage

```bash
# Scale up replicas
kubectl scale deployment/orchestrator --replicas=10 -n $NAMESPACE

# Check resource constraints
kubectl describe nodes
kubectl get events --sort-by=.metadata.creationTimestamp

# Emergency traffic routing
kubectl patch service voicehive-service -n $NAMESPACE \
  --type='json' \
  -p='[{"op": "replace", "path": "/spec/selector/app", "value": "voicehive-emergency"}]'
```

### 2. Database Issues

```bash
# Check database connections
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  python -c "import asyncpg; print('Testing DB...')"

# Scale down to reduce load
kubectl scale deployment/orchestrator --replicas=1 -n $NAMESPACE

# Enable read-only mode
kubectl set env deployment/orchestrator READ_ONLY_MODE=true -n $NAMESPACE
```

### 3. External Service Failures

```bash
# Enable circuit breakers
kubectl set env deployment/orchestrator CIRCUIT_BREAKER_ENABLED=true -n $NAMESPACE

# Increase timeouts temporarily
kubectl set env deployment/orchestrator HTTP_TIMEOUT=30 -n $NAMESPACE

# Enable fallback responses
kubectl set env deployment/orchestrator FALLBACK_MODE=true -n $NAMESPACE
```

## Monitoring During Deployment

### Key Metrics to Watch

1. **Error Rates**

   ```bash
   # HTTP error rate
   rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])
   ```

2. **Response Times**

   ```bash
   # 95th percentile response time
   histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
   ```

3. **Resource Usage**

   ```bash
   # CPU usage
   rate(container_cpu_usage_seconds_total[5m])

   # Memory usage
   container_memory_usage_bytes / container_spec_memory_limit_bytes
   ```

4. **Business Metrics**
   ```bash
   # Call success rate
   rate(voicehive_calls_total{status="completed"}[5m]) / rate(voicehive_calls_total[5m])
   ```

### Alert Thresholds

- Error rate > 1%: Warning
- Error rate > 5%: Critical
- Response time > 1s: Warning
- Response time > 5s: Critical
- CPU usage > 80%: Warning
- Memory usage > 90%: Critical

## Communication Plan

### Stakeholders

1. **Engineering Team**: Technical updates via Slack #engineering
2. **Operations Team**: Status updates via Slack #ops
3. **Management**: High-level updates via email
4. **Customers**: Status page updates for user-facing issues

### Communication Templates

#### Deployment Start

```
🚀 DEPLOYMENT STARTED
Service: VoiceHive Hotels
Version: v1.0.0
Environment: Production
ETA: 30 minutes
Status Page: https://status.voicehive.com
```

#### Deployment Complete

```
✅ DEPLOYMENT COMPLETE
Service: VoiceHive Hotels
Version: v1.0.0
Environment: Production
Duration: 25 minutes
All systems operational
```

#### Rollback Initiated

```
⚠️ ROLLBACK INITIATED
Service: VoiceHive Hotels
Reason: High error rate detected
ETA: 10 minutes
Investigating: [Brief description]
```

## Post-Deployment Tasks

### 1. Clean Up

```bash
# Remove old green environment after successful deployment
kubectl delete namespace $NAMESPACE-green

# Clean up old Docker images
docker image prune -f

# Clean up old Helm releases
helm list --all-namespaces | grep -E "(FAILED|SUPERSEDED)"
```

### 2. Documentation Updates

- [ ] Update deployment logs
- [ ] Update configuration documentation
- [ ] Update monitoring dashboards
- [ ] Update incident response procedures

### 3. Performance Baseline

```bash
# Capture new performance baseline
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  python -m pytest tests/performance/ --benchmark-save=baseline-$IMAGE_TAG
```

### 4. Security Validation

```bash
# Run security scan on deployed services
kubectl exec -n $NAMESPACE deployment/orchestrator -- \
  python -m pytest tests/security/ -v

# Verify SSL certificates
curl -vI https://api.voicehive.com 2>&1 | grep -E "(SSL|TLS)"
```

## Troubleshooting Common Issues

### Deployment Stuck

```bash
# Check pod status
kubectl get pods -n $NAMESPACE-green -o wide

# Check events
kubectl get events -n $NAMESPACE-green --sort-by=.metadata.creationTimestamp

# Check logs
kubectl logs -f deployment/orchestrator -n $NAMESPACE-green
```

### Image Pull Errors

```bash
# Check image exists
aws ecr describe-images --repository-name voicehive/orchestrator --image-ids imageTag=$IMAGE_TAG

# Check pull secrets
kubectl get secrets -n $NAMESPACE-green | grep regcred

# Recreate pull secret
kubectl create secret docker-registry regcred \
  --docker-server=$ECR_REGISTRY \
  --docker-username=AWS \
  --docker-password=$(aws ecr get-login-password) \
  -n $NAMESPACE-green
```

### Configuration Issues

```bash
# Check ConfigMap
kubectl describe configmap voicehive-config -n $NAMESPACE-green

# Check Secrets
kubectl get secrets -n $NAMESPACE-green

# Validate environment variables
kubectl exec -n $NAMESPACE-green deployment/orchestrator -- env | grep VOICEHIVE
```

## Success Criteria

Deployment is considered successful when:

- [ ] All health checks pass
- [ ] Error rate < 0.1%
- [ ] Response times within SLA
- [ ] All business metrics normal
- [ ] No critical alerts firing
- [ ] Customer-facing functionality working
- [ ] Monitoring and alerting operational

## Contacts

- **On-Call Engineer**: +1-555-0123
- **DevOps Lead**: devops-lead@voicehive.com
- **Engineering Manager**: eng-manager@voicehive.com
- **Incident Commander**: incident-commander@voicehive.com

## References

- [Infrastructure Documentation](../architecture/)
- [Monitoring Runbook](../operations/runbook.md)
- [Security Procedures](../security/)
- [API Documentation](../api/)
