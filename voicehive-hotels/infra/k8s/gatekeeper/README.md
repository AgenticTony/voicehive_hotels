# VoiceHive Hotels - Kubernetes Security Policies

This directory contains Gatekeeper (OPA) policies that enforce security and compliance requirements for all VoiceHive Hotels workloads.

## Overview

We use [Gatekeeper](https://open-policy-agent.github.io/gatekeeper/) to enforce security policies at the Kubernetes admission control level. This ensures that non-compliant resources are rejected before they can be created.

## Policy Categories

### 1. Security Controls (`K8sRequiredSecurityControls`)
Enforces fundamental security requirements:
- **Non-root containers**: All containers must run as non-root users
- **Read-only root filesystem**: Prevents runtime modifications
- **No privilege escalation**: `allowPrivilegeEscalation: false`
- **Drop all capabilities**: Containers must drop ALL capabilities by default
- **Security contexts required**: Every pod and container must define security contexts

Exceptions:
- Vault containers can add `IPC_LOCK` capability
- Services binding to ports <1024 can add `NET_BIND_SERVICE`

### 2. Resource Requirements (`K8sRequiredResources`)
Ensures proper resource management:
- All containers must specify CPU and memory requests
- All containers must specify CPU and memory limits
- Prevents resource starvation and enables proper scheduling

### 3. EU Region Compliance (`K8sEURegionOnly`)
Enforces GDPR data residency requirements:
- Workloads can only be scheduled in EU regions
- Validates nodeSelector and nodeAffinity settings
- Allowed regions: eu-west-1, eu-central-1, eu-north-1, eu-south-1, eu-west-2, eu-west-3

### 4. Required Labels (`K8sRequiredLabels`)
Enforces labeling standards for operations and compliance:
- `app.kubernetes.io/name`: Application name
- `app.kubernetes.io/version`: Version identifier
- `app.kubernetes.io/managed-by`: Deployment tool (helm/kustomize/terraform/kubectl)
- `voicehive.com/data-classification`: Data sensitivity (public/internal/confidential/restricted)
- `voicehive.com/compliance-scope`: Compliance requirements (gdpr/pci/none)

## Installation

### Prerequisites
1. Install Gatekeeper in your cluster:
```bash
kubectl apply -f https://raw.githubusercontent.com/open-policy-agent/gatekeeper/v3.14.0/deploy/gatekeeper.yaml
```

2. Wait for Gatekeeper to be ready:
```bash
kubectl -n gatekeeper-system wait --for=condition=Ready pod -l control-plane=controller-manager --timeout=300s
```

### Deploy Policies

1. Apply constraint templates:
```bash
kubectl apply -f constraint-templates/
```

2. Apply constraints:
```bash
kubectl apply -f constraints/
```

3. Verify policies are active:
```bash
kubectl get constrainttemplates
kubectl get constraints
```

## Testing Policies

### Test Security Controls
```bash
# This should fail - running as root
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-root-pod
  namespace: voicehive-staging
spec:
  containers:
  - name: test
    image: nginx
    securityContext:
      runAsUser: 0
EOF

# This should succeed - proper security context
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-secure-pod
  namespace: voicehive-staging
  labels:
    app.kubernetes.io/name: test
    app.kubernetes.io/version: "1.0"
    app.kubernetes.io/managed-by: kubectl
    voicehive.com/data-classification: internal
    voicehive.com/compliance-scope: none
spec:
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    runAsNonRoot: true
  containers:
  - name: test
    image: nginx
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      capabilities:
        drop:
        - ALL
    resources:
      requests:
        memory: "64Mi"
        cpu: "50m"
      limits:
        memory: "128Mi"
        cpu: "100m"
    volumeMounts:
    - name: tmp
      mountPath: /tmp
    - name: var-cache
      mountPath: /var/cache/nginx
    - name: var-run
      mountPath: /var/run
  volumes:
  - name: tmp
    emptyDir: {}
  - name: var-cache
    emptyDir: {}
  - name: var-run
    emptyDir: {}
EOF
```

### Test Resource Requirements
```bash
# This should fail - missing resources
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-no-resources
  namespace: voicehive-staging
spec:
  containers:
  - name: test
    image: nginx
EOF
```

### Test EU Region Compliance
```bash
# This should fail - non-EU region
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-us-region
  namespace: voicehive-production
spec:
  nodeSelector:
    topology.kubernetes.io/region: us-east-1
  containers:
  - name: test
    image: nginx
EOF
```

## Monitoring Violations

View policy violations:
```bash
# Get violation events
kubectl get events --field-selector reason=FailedAdmission -A

# Check Gatekeeper logs
kubectl logs -n gatekeeper-system deployment/gatekeeper-controller-manager

# Get constraint status
kubectl describe k8srequiredsecuritycontrols voicehive-security-controls
```

## Exemptions

To exempt specific workloads from policies:

1. **Namespace exemption**: Add namespace to `excludedNamespaces` in the constraint
2. **Temporary disable**: Set `enforcementAction: dryrun` on specific constraints
3. **Permanent exemption**: Use labels and update constraint matching rules

## Troubleshooting

### Common Issues

1. **"missing required label" errors**
   - Ensure all workloads have the required labels
   - Use `kubectl label` to add missing labels

2. **"container is missing securityContext" errors**
   - Add proper security context to pod/container specs
   - See examples above for correct configuration

3. **"not in allowed EU regions" errors**
   - Ensure node affinity/selector uses EU regions only
   - Valid regions: eu-west-1, eu-central-1, eu-north-1, etc.

### Debug Commands
```bash
# Check if Gatekeeper is running
kubectl get pods -n gatekeeper-system

# View constraint template details
kubectl describe constrainttemplate k8srequiredsecuritycontrols

# Check specific constraint violations
kubectl get k8srequiredsecuritycontrols.constraints.gatekeeper.sh voicehive-security-controls -o yaml
```

## Best Practices

1. **Test in staging first**: Always deploy new policies to staging before production
2. **Use dryrun mode**: Set `enforcementAction: dryrun` initially to see violations without blocking
3. **Monitor violations**: Set up alerts for policy violations
4. **Document exemptions**: Keep a record of why certain workloads are exempted
5. **Regular audits**: Review constraint violations and exemptions quarterly

## References

- [Gatekeeper Documentation](https://open-policy-agent.github.io/gatekeeper/)
- [OPA Rego Language](https://www.openpolicyagent.org/docs/latest/policy-language/)
- [Kubernetes Security Best Practices](https://kubernetes.io/docs/concepts/security/)
