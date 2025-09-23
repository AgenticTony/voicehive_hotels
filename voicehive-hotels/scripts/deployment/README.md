# VoiceHive Production Deployment System

This directory contains the complete production deployment automation system for VoiceHive Hotels, implementing blue-green deployment strategy with comprehensive validation, monitoring, and rollback capabilities.

## Overview

The deployment system provides:

- **Blue-Green Deployments**: Zero-downtime deployments with automatic traffic switching
- **Comprehensive Validation**: Automated smoke tests and health checks
- **Automatic Rollback**: Emergency rollback procedures with monitoring integration
- **Environment Management**: Configuration management for staging and production
- **Monitoring Integration**: Production alerting and dashboard configuration

## Components

### Core Scripts

| Script                   | Purpose                    | Usage                                     |
| ------------------------ | -------------------------- | ----------------------------------------- |
| `deploy-production.sh`   | Main deployment automation | `./deploy-production.sh --tag v1.2.3`     |
| `validate-deployment.sh` | Deployment validation      | `./validate-deployment.sh`                |
| `smoke-tests.sh`         | Smoke testing suite        | `./smoke-tests.sh`                        |
| `rollback-procedures.sh` | Emergency rollback         | `./rollback-procedures.sh --emergency`    |
| `config-manager.sh`      | Configuration management   | `./config-manager.sh generate production` |

### Configuration Files

| File                                                    | Purpose                              |
| ------------------------------------------------------- | ------------------------------------ |
| `config/environments/staging.yaml`                      | Staging environment configuration    |
| `config/environments/production.yaml`                   | Production environment configuration |
| `infra/k8s/overlays/staging/blue-green-deployment.yaml` | Blue-green deployment manifests      |
| `infra/k8s/monitoring/production-alerting-rules.yaml`   | Production alerting rules            |

## Quick Start

### 1. Deploy to Staging

```bash
# Deploy to staging with validation
./scripts/deployment/deploy-production.sh \
  --environment staging \
  --tag v1.2.3 \
  --auto-promote

# Dry run deployment
./scripts/deployment/deploy-production.sh \
  --environment staging \
  --tag v1.2.3 \
  --dry-run
```

### 2. Deploy to Production

```bash
# Production deployment with manual promotion
./scripts/deployment/deploy-production.sh \
  --tag v1.2.3 \
  --slack-webhook https://hooks.slack.com/services/...

# Production deployment with auto-promotion (use with caution)
./scripts/deployment/deploy-production.sh \
  --tag v1.2.3 \
  --auto-promote
```

### 3. Emergency Rollback

```bash
# Emergency rollback
./scripts/deployment/rollback-procedures.sh \
  --emergency \
  --namespace voicehive-production

# Standard rollback
./scripts/deployment/rollback-procedures.sh \
  --namespace voicehive-production
```

## Deployment Process

### 1. Prerequisites Validation

The system validates:

- Required tools (kubectl, helm, yq, curl, jq)
- Kubernetes cluster connectivity
- Namespace existence
- Environment configuration
- Argo Rollouts installation

### 2. Deployment Preparation

- Generates environment-specific configuration
- Applies ConfigMaps and secrets templates
- Creates backup of current state
- Validates deployment readiness

### 3. Blue-Green Deployment

- Updates rollout with new image tag
- Deploys to "green" environment
- Monitors deployment progress
- Maintains "blue" environment for rollback

### 4. Validation & Testing

- **Health Checks**: Startup, liveness, and readiness probes
- **API Testing**: Authentication, rate limiting, metrics endpoints
- **Security Testing**: Security headers, authentication enforcement
- **Performance Testing**: Response times, concurrent request handling

### 5. Promotion or Rollback

- **Manual Promotion**: Requires explicit approval
- **Auto Promotion**: Automatic after successful validation
- **Automatic Rollback**: Triggered on validation failure

## Configuration Management

### Environment-Specific Settings

Each environment has its own configuration file with settings for:

- **Application Configuration**: Logging, security, performance
- **Database Settings**: Connection pools, SSL, timeouts
- **External Services**: PMS connectors, TTS/ASR services
- **Rate Limiting**: Per-environment limits and policies
- **Monitoring**: Metrics, alerting, tracing configuration
- **Security Policies**: Network policies, pod security, service mesh

### Configuration Commands

```bash
# Validate configuration
./scripts/deployment/config-manager.sh validate production

# Generate Kubernetes manifests
./scripts/deployment/config-manager.sh generate production

# Apply configuration to cluster
./scripts/deployment/config-manager.sh apply production

# Compare configurations
./scripts/deployment/config-manager.sh compare staging production

# Backup current configuration
./scripts/deployment/config-manager.sh backup production
```

## Monitoring & Alerting

### Production Alerting Rules

The system includes comprehensive alerting for:

- **Application Health**: Service availability, error rates, latency
- **Security**: Authentication failures, rate limit violations, security incidents
- **Performance**: CPU/memory usage, connection pool exhaustion
- **Dependencies**: Database, Redis, PMS connector health
- **Business Metrics**: Call success rates, volume monitoring

### Dashboards

Production overview dashboard includes:

- Service health status
- Request rates and error rates
- Response time percentiles
- Active calls and success rates
- Resource usage (CPU/memory)
- Database connection pools
- Circuit breaker status
- PMS connector performance

### Notification Channels

- **Slack**: Real-time notifications with severity-based routing
- **Email**: Critical alerts and deployment status
- **PagerDuty**: Critical incidents requiring immediate attention

## Security Features

### Deployment Security

- **Configuration Validation**: Ensures security settings are enabled
- **Secret Management**: Secure handling of credentials and keys
- **Network Policies**: Default-deny network policies
- **Pod Security**: Non-root execution, read-only filesystems
- **Service Mesh**: mTLS encryption for service communication

### Runtime Security

- **Authentication**: JWT and API key validation
- **Authorization**: Role-based access control
- **Input Validation**: Comprehensive input sanitization
- **Audit Logging**: Complete audit trail for sensitive operations
- **PII Redaction**: Automatic PII removal from logs

## Troubleshooting

### Common Issues

1. **Deployment Stuck in Progressing State**

   ```bash
   # Check rollout status
   kubectl argo rollouts status voicehive-orchestrator-rollout -n voicehive-production

   # Check pod logs
   kubectl logs -n voicehive-production -l app=voicehive-orchestrator --tail=100
   ```

2. **Validation Failures**

   ```bash
   # Run validation manually
   ./scripts/deployment/validate-deployment.sh

   # Check specific smoke tests
   ./scripts/deployment/smoke-tests.sh
   ```

3. **Rollback Issues**

   ```bash
   # Check rollout history
   kubectl argo rollouts history voicehive-orchestrator-rollout -n voicehive-production

   # Manual rollback
   kubectl argo rollouts undo voicehive-orchestrator-rollout -n voicehive-production
   ```

### Debug Mode

Enable debug logging by setting environment variables:

```bash
export DEBUG=true
export LOG_LEVEL=DEBUG
./scripts/deployment/deploy-production.sh --tag v1.2.3
```

## Best Practices

### Deployment Guidelines

1. **Always test in staging first**
2. **Use semantic versioning for image tags**
3. **Monitor deployment progress actively**
4. **Have rollback plan ready**
5. **Validate configuration changes**

### Security Guidelines

1. **Never commit secrets to version control**
2. **Use least-privilege access**
3. **Enable all security features in production**
4. **Regularly rotate credentials**
5. **Monitor security alerts actively**

### Performance Guidelines

1. **Monitor resource usage during deployment**
2. **Validate performance benchmarks**
3. **Use appropriate resource limits**
4. **Monitor connection pool usage**
5. **Test under load before promotion**

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Review deployment logs and reports
3. Check monitoring dashboards and alerts
4. Consult the runbook documentation
5. Contact the platform team for assistance

## Dependencies

### Required Tools

- `kubectl` (v1.20+)
- `helm` (v3.0+)
- `yq` (v4.0+)
- `curl`
- `jq`
- `bc`

### Kubernetes Resources

- Argo Rollouts (for blue-green deployments)
- Prometheus (for monitoring)
- Grafana (for dashboards)
- AlertManager (for alerting)
- Istio (for service mesh, optional)

### External Services

- HashiCorp Vault (for secrets management)
- Slack (for notifications)
- PagerDuty (for critical alerts)
- Email service (for notifications)
