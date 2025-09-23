# Network Security & Zero-Trust Implementation

This directory contains the comprehensive network security and zero-trust implementation for VoiceHive Hotels. The implementation follows production-grade security best practices and official Kubernetes and service mesh documentation.

## Overview

The network security implementation provides:

- **Zero-Trust Network Architecture**: Default deny-all policies with explicit allow rules
- **Service Mesh mTLS**: Mutual TLS encryption for all inter-service communication
- **Network Segmentation**: Micro-segmentation policies for fine-grained access control
- **Network Monitoring**: Comprehensive observability and anomaly detection
- **Incident Response**: Automated detection and response procedures

## Architecture Components

### 1. Network Policies (`network-policies.yaml`)

Implements Kubernetes Network Policies for zero-trust networking:

- **Default Deny All**: Foundation policy that blocks all traffic by default
- **DNS Access**: Allows DNS resolution for service discovery
- **Service-Specific Policies**: Granular policies for each service
- **Monitoring Access**: Allows Prometheus scraping
- **External Access**: Controlled access to external services
- **Emergency Break-Glass**: Emergency policy for incident response (disabled by default)

### 2. Service Mesh Configuration

#### Istio Configuration (`../service-mesh/istio-config.yaml`)

- **Strict mTLS**: Mesh-wide and namespace-specific mTLS enforcement
- **Authorization Policies**: Identity-based access control
- **Destination Rules**: Traffic policies and circuit breaking
- **Gateway Configuration**: Secure external traffic ingress
- **Virtual Services**: Traffic routing and security headers

#### Linkerd Configuration (`../service-mesh/linkerd-config.yaml`)

- **Server Policies**: Service-specific access control
- **Authorization Policies**: Identity-based traffic authorization
- **Service Profiles**: Performance optimization and retry policies
- **Traffic Policies**: Circuit breaking and load balancing

### 3. Network Segmentation (`network-segmentation.yaml`)

Implements micro-segmentation policies:

- **Namespace Isolation**: Cross-namespace traffic control
- **Tier-Based Segmentation**: Core vs. media services separation
- **Database Access Control**: Restricted database connectivity
- **External API Segmentation**: Controlled external service access
- **Secrets Management Access**: Vault connectivity restrictions
- **Environment-Specific Policies**: Different rules for dev/staging/production

### 4. Network Monitoring (`../monitoring/network-monitoring.yaml`)

Comprehensive network observability:

- **Cilium Network Policies**: Advanced CNI-based monitoring
- **Falco Security Rules**: Runtime network anomaly detection
- **Prometheus Metrics**: Network traffic and security metrics
- **Grafana Dashboards**: Network security visualization
- **AlertManager Rules**: Automated incident detection

## Deployment

### Prerequisites

1. **Kubernetes Cluster**: Version 1.24+ with network policy support
2. **CNI Plugin**: Calico, Cilium, or other network policy-capable CNI
3. **Service Mesh**: Istio 1.19+ or Linkerd 2.14+
4. **Monitoring Stack**: Prometheus, Grafana, AlertManager

### Installation

1. **Deploy Service Mesh**:

   ```bash
   # For Istio
   ./scripts/deployment/deploy-service-mesh.sh --mesh-type istio --environment production

   # For Linkerd
   ./scripts/deployment/deploy-service-mesh.sh --mesh-type linkerd --environment production
   ```

2. **Apply Network Policies**:

   ```bash
   kubectl apply -f infra/k8s/security/network-policies.yaml
   kubectl apply -f infra/k8s/security/network-segmentation.yaml
   ```

3. **Setup Monitoring**:

   ```bash
   kubectl apply -f infra/k8s/monitoring/network-monitoring.yaml
   ```

4. **Validate Deployment**:
   ```bash
   ./scripts/security/validate-network-security.sh --namespace voicehive --verbose
   ```

### Dry Run Testing

Test the configuration without applying changes:

```bash
# Dry run service mesh deployment
./scripts/deployment/deploy-service-mesh.sh --dry-run

# Validate network policies
kubectl apply --dry-run=client -f infra/k8s/security/network-policies.yaml
```

## Configuration

### Service Labels

Services must be labeled for proper network segmentation:

```yaml
metadata:
  labels:
    tier: core|media # Service tier for segmentation
    database-access: "allowed" # Database connectivity permission
    vault-access: "allowed" # Vault access permission
    external-api-access: "allowed" # External API access permission
    compliance-logging: "required" # Audit logging requirement
```

### Network Policy Customization

Modify policies in `network-policies.yaml`:

1. **Add New Services**: Create service-specific policies
2. **External IPs**: Update allowed external IP ranges
3. **Ports**: Modify allowed port ranges
4. **Namespaces**: Add cross-namespace communication rules

### Service Mesh Customization

#### Istio Customization

1. **mTLS Mode**: Modify `PeerAuthentication` policies
2. **Authorization**: Update `AuthorizationPolicy` rules
3. **Traffic Management**: Adjust `DestinationRule` settings

#### Linkerd Customization

1. **Server Policies**: Modify `Server` configurations
2. **Authorization**: Update `ServerAuthorization` rules
3. **Traffic Policies**: Adjust `HTTPRoute` settings

## Monitoring and Alerting

### Key Metrics

- **Network Policy Violations**: `falco_events_total{rule_name="Network Policy Violation"}`
- **mTLS Connection Failures**: `istio_requests_total{security_policy!="mutual_tls"}`
- **Suspicious Connections**: `falco_events_total{rule_name=~"Suspicious.*Connection"}`
- **DNS Anomalies**: `coredns_dns_requests_total`

### Dashboards

Access monitoring dashboards:

```bash
# Grafana (if using port-forward)
kubectl port-forward -n monitoring svc/grafana 3000:3000

# Istio Kiali
kubectl port-forward -n istio-system svc/kiali 20001:20001

# Linkerd Viz
linkerd viz dashboard
```

### Alerts

Critical alerts are configured for:

- Network policy violations (immediate)
- Unauthorized service communication (immediate)
- DNS tunneling attempts (immediate)
- mTLS connection failures (2-minute delay)
- High network traffic anomalies (5-minute delay)

## Security Considerations

### Zero-Trust Principles

1. **Never Trust, Always Verify**: All traffic is authenticated and authorized
2. **Least Privilege Access**: Minimal required permissions only
3. **Assume Breach**: Monitor and detect anomalous behavior
4. **Verify Explicitly**: Identity-based access control

### Compliance

The implementation supports:

- **GDPR**: Data protection and privacy controls
- **SOC 2**: Security and availability controls
- **PCI DSS**: Payment data protection (if applicable)
- **ISO 27001**: Information security management

### Security Boundaries

1. **Network Layer**: Kubernetes Network Policies
2. **Transport Layer**: Service mesh mTLS
3. **Application Layer**: Service mesh authorization policies
4. **Identity Layer**: Service account-based access control

## Troubleshooting

### Common Issues

1. **Network Policy Blocking Traffic**:

   ```bash
   # Check network policies
   kubectl get networkpolicies -n voicehive
   kubectl describe networkpolicy POLICY_NAME -n voicehive

   # Test connectivity
   kubectl exec -n voicehive POD_NAME -- curl -v SERVICE_URL
   ```

2. **Service Mesh mTLS Issues**:

   ```bash
   # Istio troubleshooting
   istioctl proxy-status
   istioctl proxy-config cluster POD_NAME.voicehive

   # Linkerd troubleshooting
   linkerd check
   linkerd diagnostics proxy-metrics POD_NAME
   ```

3. **Authorization Policy Denials**:
   ```bash
   # Check authorization policies
   kubectl get authorizationpolicy -n voicehive
   kubectl logs -n istio-system -l app=istiod | grep "denied"
   ```

### Emergency Procedures

1. **Disable Network Policies** (Emergency Only):

   ```bash
   kubectl delete networkpolicy --all -n voicehive
   ```

2. **Enable Break-Glass Policy**:

   ```bash
   kubectl patch networkpolicy emergency-break-glass -n voicehive \
     --type='json' -p='[{"op": "replace", "path": "/metadata/labels/security.voicehive.io~1enabled", "value": "true"}]'
   ```

3. **Bypass Service Mesh Authorization** (Emergency Only):
   ```bash
   kubectl delete authorizationpolicy --all -n voicehive
   ```

### Validation Commands

```bash
# Validate network policies
kubectl auth can-i create networkpolicies --namespace voicehive

# Check service mesh status
istioctl analyze -n voicehive
# OR
linkerd check

# Test service connectivity
kubectl exec -n voicehive deploy/orchestrator -- curl -s http://tts-router/healthz

# Check security events
kubectl get events -n voicehive --field-selector type=Warning
```

## Performance Impact

### Resource Overhead

- **Istio Proxy**: ~50-100MB memory, ~0.1-0.2 CPU cores per pod
- **Linkerd Proxy**: ~20-50MB memory, ~0.05-0.1 CPU cores per pod
- **Network Policies**: Minimal overhead, depends on CNI implementation

### Latency Impact

- **Service Mesh mTLS**: ~1-2ms additional latency
- **Network Policy Enforcement**: <1ms additional latency
- **Authorization Checks**: ~0.5-1ms additional latency

### Optimization Tips

1. **Resource Limits**: Set appropriate proxy resource limits
2. **Connection Pooling**: Configure connection reuse
3. **Circuit Breaking**: Prevent cascade failures
4. **Monitoring**: Use efficient metric collection

## References

- [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [Istio Security](https://istio.io/latest/docs/concepts/security/)
- [Linkerd Security](https://linkerd.io/2.14/features/automatic-mtls/)
- [CNCF Zero Trust Networking](https://github.com/cncf/tag-security/blob/main/security-whitepaper/v2/CNCF_cloud-native-security-whitepaper-May2022-v2.pdf)
- [Falco Rules](https://falco.org/docs/rules/)

## Support

For issues and questions:

1. Check the troubleshooting section above
2. Review the incident response procedures in `docs/security/network-security-incident-response.md`
3. Contact the security team via the established escalation procedures
4. Create an issue in the project repository with detailed logs and configuration
