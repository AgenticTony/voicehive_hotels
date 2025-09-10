# VoiceHive Hotels Kubernetes Deployment

This directory contains Kubernetes manifests for deploying the VoiceHive Hotels voice AI pipeline.

## Directory Structure

```
k8s/
├── base/                         # Base manifests (shared across environments)
│   ├── deployment-orchestrator.yaml
│   ├── deployment-livekit-agent.yaml
│   ├── deployment-riva-asr-proxy.yaml
│   ├── deployment-tts-router.yaml
│   ├── configmap-gdpr.yaml
│   ├── externalsecrets.yaml
│   ├── ingress.yaml
│   └── kustomization.yaml
├── overlays/
│   ├── staging/                  # Staging-specific configurations
│   │   └── kustomization.yaml
│   └── production/              # Production-specific configurations
│       └── kustomization.yaml
└── README.md                    # This file
```

## Prerequisites

1. **Kubernetes Cluster** (EKS/AKS) with:
   - Kubernetes 1.24+
   - GPU nodes for NVIDIA Riva (g4dn.xlarge or similar)
   - External Secrets Operator installed
   - AWS ALB Ingress Controller (for EKS)
   - cert-manager for TLS certificates

2. **External Services**:
   - HashiCorp Vault for secrets management
   - Redis cluster (ElastiCache or self-managed)
   - PostgreSQL database (RDS or self-managed)
   - Container registry with built images

## Quick Start

### 1. Install Prerequisites

```bash
# Install External Secrets Operator
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets -n external-secrets-system --create-namespace

# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.12.0/cert-manager.yaml

# Install AWS Load Balancer Controller (for EKS)
helm repo add eks https://aws.github.io/eks-charts
helm install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system
```

### 2. Configure Vault Secrets

Store the following secrets in HashiCorp Vault:

```bash
# LiveKit credentials
vault kv put voicehive/livekit \
  api_key="your-livekit-api-key" \
  api_secret="your-livekit-api-secret"

# TTS service credentials  
vault kv put voicehive/elevenlabs api_key="your-elevenlabs-key"
vault kv put voicehive/azure_speech subscription_key="your-azure-speech-key"

# Azure OpenAI credentials
vault kv put voicehive/azure_openai \
  api_key="your-azure-openai-key" \
  endpoint="https://your-resource.openai.azure.com/" \
  deployment_name="gpt-4"

# Infrastructure secrets
vault kv put voicehive/infrastructure \
  redis_connection_string="redis://your-redis:6379" \
  postgres_connection_string="postgresql://user:pass@host:5432/db" \
  vault_token="your-vault-token"
```

### 3. Deploy to Staging

```bash
# Create namespace
kubectl create namespace voicehive-staging

# Deploy using Kustomize
kubectl apply -k overlays/staging/

# Check deployment status
kubectl -n voicehive-staging get pods
kubectl -n voicehive-staging get ingress
```

### 4. Deploy to Production

```bash
# Create namespace if not exists
kubectl create namespace voicehive

# Deploy using Kustomize
kubectl apply -k overlays/production/

# Check deployment status
kubectl -n voicehive get pods
kubectl -n voicehive get ingress
```

## Service Endpoints

### Internal Services
- **Orchestrator**: `http://orchestrator.voicehive.svc.cluster.local`
- **LiveKit Agent**: Internal only (metrics at port 9090)
- **Riva ASR Proxy**: `http://riva-asr-proxy.voicehive.svc.cluster.local`
- **TTS Router**: `http://tts-router.voicehive.svc.cluster.local`

### External Endpoints (via Ingress)
- **Production Webhooks**: `https://webhooks.voicehive-hotels.eu`
- **Staging Webhooks**: `https://staging-webhooks.voicehive-hotels.eu`

## Monitoring

### Prometheus Metrics
All services expose metrics on port 9090 at `/metrics` endpoint.

```bash
# Port-forward to access metrics locally
kubectl -n voicehive port-forward deployment/orchestrator 9090:9090
curl localhost:9090/metrics
```

### Service Health Checks
- Orchestrator: `/healthz`
- Riva ASR Proxy: `/health`
- TTS Router: `/health`
- LiveKit Agent: `/healthz`

## Scaling

### Manual Scaling
```bash
# Scale a deployment
kubectl -n voicehive scale deployment/orchestrator --replicas=10
```

### Autoscaling
HorizontalPodAutoscalers are configured for all services:
- CPU-based scaling (60-70% threshold)
- Memory-based scaling (70-80% threshold)
- Custom metrics (active calls, streams, etc.)

## Troubleshooting

### Check Pod Logs
```bash
# View logs for a specific pod
kubectl -n voicehive logs -f deployment/orchestrator

# View logs with timestamps
kubectl -n voicehive logs -f deployment/orchestrator --timestamps=true

# View previous container logs (if crashed)
kubectl -n voicehive logs deployment/orchestrator --previous
```

### Debug Pod Issues
```bash
# Describe pod for events and status
kubectl -n voicehive describe pod <pod-name>

# Get pod events
kubectl -n voicehive get events --field-selector involvedObject.name=<pod-name>

# Execute into pod for debugging
kubectl -n voicehive exec -it deployment/orchestrator -- /bin/sh
```

### Common Issues

1. **ExternalSecrets not syncing**
   - Check ExternalSecrets status: `kubectl -n voicehive get externalsecrets`
   - Verify Vault connectivity and permissions

2. **GPU nodes not available**
   - Check node labels: `kubectl get nodes -L node.kubernetes.io/instance-type`
   - Ensure GPU drivers are installed on nodes

3. **Ingress not accessible**
   - Verify ALB is created: `kubectl -n voicehive describe ingress`
   - Check security group rules allow traffic

4. **Pods stuck in Pending**
   - Check resource availability: `kubectl describe nodes`
   - Review PVC status if using persistent storage

## Security Considerations

1. **Network Policies**: Restrict pod-to-pod communication
2. **Pod Security**: Non-root user, read-only filesystem, dropped capabilities
3. **Secrets Management**: All secrets via ExternalSecrets/Vault
4. **TLS**: Enforced for all external endpoints
5. **GDPR Compliance**: EU region enforcement, PII redaction enabled

## Backup and Recovery

### Database Backup
Configure automated RDS snapshots or use pg_dump for self-managed PostgreSQL.

### Redis Backup
Enable Redis persistence and automated backups in ElastiCache.

### Persistent Volumes
The Riva models PVC should be backed up regularly:
```bash
kubectl -n voicehive exec deployment/riva-asr-proxy -- tar czf /tmp/models-backup.tar.gz /models
kubectl -n voicehive cp deployment/riva-asr-proxy:/tmp/models-backup.tar.gz ./models-backup.tar.gz
```

## Maintenance

### Rolling Updates
```bash
# Update image tag
kubectl -n voicehive set image deployment/orchestrator orchestrator=voicehive/orchestrator:v1.0.1

# Check rollout status
kubectl -n voicehive rollout status deployment/orchestrator
```

### Rollback
```bash
# Rollback to previous version
kubectl -n voicehive rollout undo deployment/orchestrator

# Rollback to specific revision
kubectl -n voicehive rollout undo deployment/orchestrator --to-revision=2
```

## Contact

For issues or questions, contact the VoiceHive DevOps team.
