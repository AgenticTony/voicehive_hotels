# Production Deployment Guide

## Prerequisites

- AWS account with appropriate IAM permissions
- kubectl configured for production cluster
- HashiCorp Vault access
- Domain names configured
- SSL certificates provisioned

## Pre-Deployment Checklist

- [ ] All tests passing (unit, integration, e2e)
- [ ] Security scan completed (no high/critical issues)
- [ ] Performance testing completed
- [ ] Database migrations tested
- [ ] Rollback plan documented
- [ ] Monitoring alerts configured
- [ ] On-call schedule updated

## Deployment Steps

### 1. Prepare Release

```bash
# Tag the release
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0

# Build and push Docker images
make ci-build VERSION=1.0.0
make ci-push VERSION=1.0.0
```

### 2. Update Secrets

```bash
# Update API keys in Vault
vault kv put secret/voicehive/production/api-keys \
  twilio_account_sid=XXX \
  elevenlabs_api_key=XXX \
  azure_openai_key=XXX

# Update PMS credentials
vault kv put secret/voicehive/production/pms/apaleo \
  client_id=XXX \
  client_secret=XXX
```

### 3. Deploy Infrastructure

```bash
# Apply Terraform changes
cd infra/terraform/production
terraform plan -out=tfplan
terraform apply tfplan

# Verify infrastructure
aws eks describe-cluster --name voicehive-production
```

### 4. Deploy Application

```bash
# Update Kubernetes manifests
kubectl apply -k infra/k8s/overlays/production

# Monitor rollout
kubectl rollout status deployment/orchestrator -n voicehive
kubectl rollout status deployment/connectors -n voicehive
kubectl rollout status deployment/media-agent -n voicehive
```

### 5. Verify Deployment

```bash
# Check pod status
kubectl get pods -n voicehive

# Check logs
kubectl logs -n voicehive -l app=orchestrator --tail=100

# Run smoke tests
make test-production

# Check metrics
open https://grafana.voicehive-hotels.eu
```

### 6. Configure Load Balancer

```bash
# Update DNS records
aws route53 change-resource-record-sets \
  --hosted-zone-id Z123456 \
  --change-batch file://dns-update.json

# Verify SSL certificates
curl -v https://api.voicehive-hotels.eu/healthz
```

## Blue-Green Deployment

### Deploy to Green Environment

```bash
# Deploy new version to green
kubectl apply -f infra/k8s/overlays/production/green/

# Run tests against green
export API_URL=https://api-green.voicehive-hotels.eu
make test-integration

# Switch traffic to green
kubectl patch service voicehive-api \
  -p '{"spec":{"selector":{"version":"green"}}}'
```

### Rollback if Needed

```bash
# Switch back to blue
kubectl patch service voicehive-api \
  -p '{"spec":{"selector":{"version":"blue"}}}'

# Remove failed green deployment
kubectl delete -f infra/k8s/overlays/production/green/
```

## Post-Deployment

### 1. Monitor Key Metrics

- P95 latency < 500ms
- Error rate < 0.1%
- CPU usage < 70%
- Memory usage < 80%
- Active calls count
- PMS API success rate

### 2. Update Documentation

```bash
# Update changelog
echo "## v1.0.0 - $(date +%Y-%m-%d)" >> CHANGELOG.md
echo "- Feature: Initial production release" >> CHANGELOG.md

# Update API docs
make generate-api-docs
```

### 3. Notify Stakeholders

- Send deployment notification to #deploys Slack channel
- Update status page
- Email customer success team

## Troubleshooting

### High Latency

```bash
# Check ASR performance
kubectl logs -n voicehive -l app=riva-proxy --tail=1000 | grep "latency"

# Check TTS performance  
kubectl logs -n voicehive -l app=tts-router --tail=1000 | grep "ttfb"

# Scale if needed
kubectl scale deployment orchestrator --replicas=5 -n voicehive
```

### PMS Connection Issues

```bash
# Check connector logs
kubectl logs -n voicehive -l app=connectors --tail=1000 | grep "ERROR"

# Restart connector pod
kubectl rollout restart deployment/connectors -n voicehive

# Check Vault connectivity
kubectl exec -it deployment/orchestrator -n voicehive -- \
  vault kv get secret/voicehive/production/pms/apaleo
```

### Memory Leaks

```bash
# Get memory usage
kubectl top pods -n voicehive

# Get heap dump
kubectl exec -it <pod-name> -n voicehive -- \
  python -m py_spy dump --pid 1 --duration 30

# Restart affected pods
kubectl delete pod <pod-name> -n voicehive
```

## Disaster Recovery

### Backup Critical Data

```bash
# Backup database
make db-backup ENV=production

# Backup call recordings
aws s3 sync s3://voicehive-recordings-prod \
  s3://voicehive-recordings-backup --storage-class GLACIER

# Export Vault secrets
vault kv get -format=json secret/voicehive/production > vault-backup.json
```

### Restore from Backup

```bash
# Restore database
psql -h db.voicehive-hotels.eu -U postgres < backup.sql

# Restore Vault
vault kv put secret/voicehive/production @vault-backup.json

# Restore recordings
aws s3 sync s3://voicehive-recordings-backup \
  s3://voicehive-recordings-prod
```

## Security Considerations

- All deployments must pass security scan
- Rotate API keys monthly
- Monitor for suspicious activity
- Enable AWS GuardDuty
- Review IAM permissions quarterly

## Compliance

- Ensure EU region deployment only
- Verify GDPR settings are active
- Check data retention policies
- Audit PII handling

---
**Last Updated**: January 2024
**Maintained by**: Platform Team
