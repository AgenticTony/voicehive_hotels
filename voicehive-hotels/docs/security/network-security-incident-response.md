# Network Security Incident Response Procedures

## Overview

This document outlines the procedures for responding to network security incidents in the VoiceHive Hotels production environment. It covers detection, analysis, containment, eradication, recovery, and lessons learned phases of incident response.

## Incident Classification

### Severity Levels

#### Critical (P0)

- Active network intrusion or compromise
- DNS tunneling or data exfiltration attempts
- Unauthorized access to production services
- Service mesh mTLS failures affecting multiple services
- Network policy violations allowing unauthorized access

#### High (P1)

- Suspicious network connections to external IPs
- Unauthorized inter-service communication
- Network anomalies indicating potential attack
- Failed authentication attempts from unknown sources

#### Medium (P2)

- Network policy configuration drift
- Unusual traffic patterns
- Performance degradation due to network issues
- Non-critical security rule violations

#### Low (P3)

- Informational security events
- Network monitoring alerts requiring investigation
- Configuration warnings

## Detection and Alerting

### Automated Detection Sources

1. **Falco Runtime Security**

   - Network policy violations
   - Suspicious network connections
   - DNS tunneling attempts
   - Unauthorized service communication

2. **Istio/Linkerd Service Mesh**

   - mTLS connection failures
   - Authorization policy violations
   - Traffic anomalies

3. **Prometheus Monitoring**

   - Network traffic volume anomalies
   - Connection failure rates
   - Service mesh metrics

4. **Cilium Hubble (if applicable)**
   - Network flow analysis
   - Policy enforcement monitoring
   - L7 protocol violations

### Alert Channels

- **PagerDuty**: Critical and High severity incidents
- **Slack**: All severity levels to #security-alerts channel
- **Email**: Security team distribution list
- **SIEM**: All events for correlation and analysis

## Incident Response Procedures

### Phase 1: Detection and Analysis (0-15 minutes)

#### Immediate Actions

1. **Acknowledge the Alert**

   ```bash
   # Check alert details in monitoring dashboard
   kubectl get events -n voicehive --sort-by='.lastTimestamp'

   # Review Falco alerts
   kubectl logs -n falco-system -l app=falco --tail=100

   # Check service mesh status
   istioctl proxy-status
   # OR for Linkerd
   linkerd check
   ```

2. **Initial Assessment**

   - Determine affected services and scope
   - Identify source and destination of suspicious traffic
   - Check if incident is ongoing or historical
   - Assess potential impact on business operations

3. **Gather Evidence**

   ```bash
   # Capture network flows (if using Cilium)
   hubble observe --namespace voicehive --follow

   # Check network policies
   kubectl get networkpolicies -n voicehive -o yaml

   # Review service mesh policies
   kubectl get peerauthentication,authorizationpolicy -n voicehive

   # Capture pod logs for affected services
   kubectl logs -n voicehive -l app=orchestrator --tail=1000
   ```

#### Decision Points

- **Is this a false positive?** → Document and tune alerting rules
- **Is this an active attack?** → Proceed to containment
- **Is this a policy misconfiguration?** → Proceed to remediation
- **Requires escalation?** → Notify security team lead

### Phase 2: Containment (15-30 minutes)

#### Immediate Containment

1. **Isolate Affected Services**

   ```bash
   # Apply emergency network policy to isolate service
   kubectl apply -f - <<EOF
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: emergency-isolation-$(date +%s)
     namespace: voicehive
   spec:
     podSelector:
       matchLabels:
         app: AFFECTED_SERVICE
     policyTypes:
     - Ingress
     - Egress
     # Deny all traffic (empty rules)
   EOF
   ```

2. **Block Suspicious External IPs**

   ```bash
   # Add IP to network policy deny list
   kubectl patch networkpolicy external-api-segmentation -n voicehive --type='json' \
     -p='[{"op": "add", "path": "/spec/egress/0/to/0/ipBlock/except/-", "value": "SUSPICIOUS_IP/32"}]'
   ```

3. **Disable Compromised Service Accounts**
   ```bash
   # Disable service account if compromised
   kubectl patch serviceaccount COMPROMISED_SA -n voicehive \
     -p '{"metadata":{"annotations":{"security.voicehive.io/disabled":"true"}}}'
   ```

#### Service Mesh Containment

1. **Istio Containment**

   ```bash
   # Apply strict authorization policy
   kubectl apply -f - <<EOF
   apiVersion: security.istio.io/v1beta1
   kind: AuthorizationPolicy
   metadata:
     name: emergency-deny-$(date +%s)
     namespace: voicehive
   spec:
     selector:
       matchLabels:
         app: AFFECTED_SERVICE
     # Empty rules = deny all
   EOF
   ```

2. **Linkerd Containment**
   ```bash
   # Apply server authorization to block traffic
   kubectl apply -f - <<EOF
   apiVersion: policy.linkerd.io/v1beta1
   kind: ServerAuthorization
   metadata:
     name: emergency-block-$(date +%s)
     namespace: voicehive
   spec:
     server:
       name: AFFECTED_SERVICE-server
     # No client rules = deny all
   EOF
   ```

### Phase 3: Eradication (30-60 minutes)

#### Root Cause Analysis

1. **Analyze Network Flows**

   ```bash
   # Review historical network data
   kubectl exec -n monitoring prometheus-0 -- \
     promtool query instant 'rate(istio_tcp_received_bytes_total[5m])'

   # Check DNS queries
   kubectl logs -n kube-system -l k8s-app=kube-dns --since=1h | grep SUSPICIOUS_DOMAIN
   ```

2. **Review Configuration Changes**

   ```bash
   # Check recent network policy changes
   kubectl get events -n voicehive --field-selector reason=NetworkPolicyUpdated

   # Review service mesh configuration changes
   kubectl get events -n istio-system --sort-by='.lastTimestamp'
   ```

3. **Vulnerability Assessment**
   - Check for known CVEs in network components
   - Review service mesh version and security patches
   - Assess network policy completeness

#### Remediation Actions

1. **Update Network Policies**

   ```bash
   # Apply corrected network policies
   kubectl apply -f infra/k8s/security/network-policies.yaml

   # Verify policy enforcement
   kubectl describe networkpolicy -n voicehive
   ```

2. **Patch Vulnerabilities**

   ```bash
   # Update service mesh components
   istioctl upgrade --set values.pilot.image=istio/pilot:PATCHED_VERSION

   # Update CNI if applicable
   kubectl set image daemonset/cilium -n kube-system cilium-agent=cilium/cilium:PATCHED_VERSION
   ```

3. **Rotate Compromised Credentials**

   ```bash
   # Rotate service mesh certificates
   istioctl proxy-config secret AFFECTED_POD.voicehive

   # Update service account tokens
   kubectl delete secret $(kubectl get sa AFFECTED_SA -o jsonpath='{.secrets[0].name}') -n voicehive
   ```

### Phase 4: Recovery (60-120 minutes)

#### Service Restoration

1. **Gradual Traffic Restoration**

   ```bash
   # Remove emergency isolation policies
   kubectl delete networkpolicy emergency-isolation-* -n voicehive

   # Restore normal authorization policies
   kubectl delete authorizationpolicy emergency-deny-* -n voicehive
   ```

2. **Verify Service Health**

   ```bash
   # Check service mesh status
   istioctl analyze -n voicehive

   # Verify mTLS is working
   istioctl authn tls-check orchestrator.voicehive.svc.cluster.local

   # Test service connectivity
   kubectl exec -n voicehive deploy/orchestrator -- curl -s http://tts-router/healthz
   ```

3. **Monitor for Anomalies**

   ```bash
   # Watch for new security events
   kubectl logs -n falco-system -l app=falco --follow

   # Monitor service mesh metrics
   kubectl port-forward -n istio-system svc/grafana 3000:3000
   ```

#### Validation Steps

- [ ] All services are healthy and responding
- [ ] mTLS is enforced across all service communications
- [ ] Network policies are correctly applied and enforced
- [ ] No suspicious network activity detected
- [ ] Monitoring and alerting are functioning normally

### Phase 5: Lessons Learned (Post-Incident)

#### Documentation Requirements

1. **Incident Report Template**

   ```markdown
   # Network Security Incident Report

   **Incident ID**: NSI-YYYY-MM-DD-XXX
   **Date/Time**:
   **Severity**:
   **Duration**:
   **Affected Services**:

   ## Summary

   Brief description of the incident

   ## Timeline

   - Detection:
   - Containment:
   - Resolution:

   ## Root Cause

   Technical details of what caused the incident

   ## Impact Assessment

   - Business impact
   - Technical impact
   - Security implications

   ## Response Actions

   - What worked well
   - What could be improved

   ## Preventive Measures

   - Configuration changes
   - Process improvements
   - Monitoring enhancements
   ```

2. **Action Items**
   - Update network policies based on lessons learned
   - Enhance monitoring and alerting rules
   - Improve incident response procedures
   - Conduct security training if needed

## Runbook Automation

### Emergency Response Scripts

1. **Network Isolation Script**

   ```bash
   #!/bin/bash
   # emergency-isolate.sh

   SERVICE_NAME=$1
   NAMESPACE=${2:-voicehive}
   TIMESTAMP=$(date +%s)

   if [ -z "$SERVICE_NAME" ]; then
     echo "Usage: $0 <service-name> [namespace]"
     exit 1
   fi

   echo "Isolating service: $SERVICE_NAME in namespace: $NAMESPACE"

   kubectl apply -f - <<EOF
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: emergency-isolation-$TIMESTAMP
     namespace: $NAMESPACE
     labels:
       emergency: "true"
       created-by: "incident-response"
   spec:
     podSelector:
       matchLabels:
         app: $SERVICE_NAME
     policyTypes:
     - Ingress
     - Egress
   EOF

   echo "Service $SERVICE_NAME isolated. Policy: emergency-isolation-$TIMESTAMP"
   ```

2. **Service Mesh Status Check**

   ```bash
   #!/bin/bash
   # check-mesh-status.sh

   echo "=== Service Mesh Status Check ==="

   # Check Istio status
   if command -v istioctl &> /dev/null; then
     echo "Istio Status:"
     istioctl proxy-status
     echo ""
     istioctl analyze -n voicehive
   fi

   # Check Linkerd status
   if command -v linkerd &> /dev/null; then
     echo "Linkerd Status:"
     linkerd check
   fi

   echo "=== Network Policies ==="
   kubectl get networkpolicies -n voicehive

   echo "=== Recent Security Events ==="
   kubectl get events -n voicehive --field-selector type=Warning --sort-by='.lastTimestamp' | tail -10
   ```

### Monitoring Integration

1. **PagerDuty Integration**
   ```yaml
   # pagerduty-network-security.yaml
   apiVersion: v1
   kind: Secret
   metadata:
     name: pagerduty-network-security
     namespace: monitoring
   data:
     routing_key: <base64-encoded-routing-key>
   ---
   apiVersion: monitoring.coreos.com/v1alpha1
   kind: AlertmanagerConfig
   metadata:
     name: network-security-pagerduty
     namespace: monitoring
   spec:
     route:
       groupBy: ["alertname", "severity"]
       groupWait: 10s
       groupInterval: 10s
       repeatInterval: 1h
       receiver: "network-security-pagerduty"
       matchers:
         - name: component
           value: network-security
     receivers:
       - name: "network-security-pagerduty"
         pagerdutyConfigs:
           - routingKey:
               key: routing_key
               name: pagerduty-network-security
             description: "Network Security Alert: {{ .GroupLabels.alertname }}"
             severity: "{{ .GroupLabels.severity }}"
   ```

## Contact Information

### Escalation Matrix

| Role              | Primary        | Secondary    | Contact Method    |
| ----------------- | -------------- | ------------ | ----------------- |
| Security Engineer | John Doe       | Jane Smith   | PagerDuty + Slack |
| Network Engineer  | Bob Johnson    | Alice Brown  | PagerDuty + Phone |
| Platform Engineer | Charlie Wilson | Diana Davis  | Slack + Email     |
| Security Manager  | Eve Anderson   | Frank Miller | Phone + Email     |

### External Contacts

- **Cloud Provider Support**: Available 24/7 via support portal
- **Security Vendor Support**: Check vendor-specific escalation procedures
- **Legal/Compliance**: Contact during business hours for data breach notifications

## Testing and Validation

### Regular Drills

1. **Monthly Network Security Drill**

   - Simulate network policy violation
   - Test incident response procedures
   - Validate containment mechanisms
   - Review and update procedures

2. **Quarterly Tabletop Exercise**
   - Multi-team coordination exercise
   - Complex attack scenario simulation
   - Communication and escalation testing
   - Process improvement identification

### Metrics and KPIs

- **Mean Time to Detection (MTTD)**: Target < 5 minutes
- **Mean Time to Containment (MTTC)**: Target < 15 minutes
- **Mean Time to Recovery (MTTR)**: Target < 2 hours
- **False Positive Rate**: Target < 5%

## Compliance and Reporting

### Regulatory Requirements

- **GDPR**: Report data breaches within 72 hours if applicable
- **PCI DSS**: Follow incident response requirements for payment data
- **SOC 2**: Document all security incidents and response actions

### Internal Reporting

- **Executive Summary**: Within 24 hours for P0/P1 incidents
- **Detailed Report**: Within 1 week of incident resolution
- **Quarterly Security Review**: Include network security incidents and trends
