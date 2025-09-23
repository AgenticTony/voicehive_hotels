#!/bin/bash

# Network Security Validation Script for VoiceHive Hotels
# Validates zero-trust network security implementation
# Checks network policies, service mesh configuration, and security controls

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
NAMESPACE="${NAMESPACE:-voicehive}"
MESH_TYPE="${MESH_TYPE:-auto}"  # auto, istio, linkerd, none
VERBOSE="${VERBOSE:-false}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_TOTAL=0

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((TESTS_PASSED++))
    ((TESTS_TOTAL++))
}

log_failure() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((TESTS_FAILED++))
    ((TESTS_TOTAL++))
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_verbose() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${BLUE}[DEBUG]${NC} $1"
    fi
}

# Detect service mesh type
detect_service_mesh() {
    if [[ "$MESH_TYPE" == "auto" ]]; then
        if kubectl get namespace istio-system &>/dev/null && kubectl get pods -n istio-system -l app=istiod &>/dev/null; then
            MESH_TYPE="istio"
            log_info "Detected Istio service mesh"
        elif kubectl get namespace linkerd &>/dev/null && kubectl get pods -n linkerd -l linkerd.io/control-plane-component=controller &>/dev/null; then
            MESH_TYPE="linkerd"
            log_info "Detected Linkerd service mesh"
        else
            MESH_TYPE="none"
            log_info "No service mesh detected"
        fi
    fi
}

# Test 1: Verify namespace exists and is properly labeled
test_namespace_configuration() {
    log_info "Testing namespace configuration..."
    
    if kubectl get namespace "$NAMESPACE" &>/dev/null; then
        log_success "Namespace $NAMESPACE exists"
        
        # Check service mesh injection labels
        case "$MESH_TYPE" in
            "istio")
                if kubectl get namespace "$NAMESPACE" -o jsonpath='{.metadata.labels.istio-injection}' | grep -q "enabled"; then
                    log_success "Istio sidecar injection enabled for namespace $NAMESPACE"
                else
                    log_failure "Istio sidecar injection not enabled for namespace $NAMESPACE"
                fi
                ;;
            "linkerd")
                if kubectl get namespace "$NAMESPACE" -o jsonpath='{.metadata.annotations.linkerd\.io/inject}' | grep -q "enabled"; then
                    log_success "Linkerd proxy injection enabled for namespace $NAMESPACE"
                else
                    log_failure "Linkerd proxy injection not enabled for namespace $NAMESPACE"
                fi
                ;;
        esac
    else
        log_failure "Namespace $NAMESPACE does not exist"
    fi
}

# Test 2: Verify network policies are applied
test_network_policies() {
    log_info "Testing network policies..."
    
    # Check if network policies exist
    POLICIES=$(kubectl get networkpolicies -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l)
    if [[ $POLICIES -gt 0 ]]; then
        log_success "Found $POLICIES network policies in namespace $NAMESPACE"
        
        # Check for default deny policy
        if kubectl get networkpolicy default-deny-all -n "$NAMESPACE" &>/dev/null; then
            log_success "Default deny-all network policy exists"
        else
            log_failure "Default deny-all network policy missing"
        fi
        
        # Check for DNS policy
        if kubectl get networkpolicy allow-dns -n "$NAMESPACE" &>/dev/null; then
            log_success "DNS access network policy exists"
        else
            log_failure "DNS access network policy missing"
        fi
        
        # Check service-specific policies
        SERVICES=("orchestrator" "livekit-agent" "tts-router" "riva-asr-proxy")
        for service in "${SERVICES[@]}"; do
            if kubectl get networkpolicy "${service}-policy" -n "$NAMESPACE" &>/dev/null; then
                log_success "Network policy exists for $service"
            else
                log_failure "Network policy missing for $service"
            fi
        done
    else
        log_failure "No network policies found in namespace $NAMESPACE"
    fi
}

# Test 3: Verify service mesh mTLS configuration
test_service_mesh_mtls() {
    log_info "Testing service mesh mTLS configuration..."
    
    case "$MESH_TYPE" in
        "istio")
            # Check PeerAuthentication policies
            if kubectl get peerauthentication default-strict-mtls -n istio-system &>/dev/null; then
                log_success "Mesh-wide strict mTLS policy exists"
            else
                log_failure "Mesh-wide strict mTLS policy missing"
            fi
            
            if kubectl get peerauthentication voicehive-strict-mtls -n "$NAMESPACE" &>/dev/null; then
                log_success "Namespace-specific mTLS policy exists"
            else
                log_failure "Namespace-specific mTLS policy missing"
            fi
            
            # Check DestinationRules
            SERVICES=("orchestrator" "livekit-agent" "tts-router" "riva-asr-proxy")
            for service in "${SERVICES[@]}"; do
                if kubectl get destinationrule "${service}-mtls" -n "$NAMESPACE" &>/dev/null; then
                    log_success "mTLS DestinationRule exists for $service"
                else
                    log_failure "mTLS DestinationRule missing for $service"
                fi
            done
            ;;
        "linkerd")
            # Check Server policies
            SERVICES=("orchestrator" "livekit-agent" "tts-router" "riva-asr-proxy")
            for service in "${SERVICES[@]}"; do
                if kubectl get server "${service}-server" -n "$NAMESPACE" &>/dev/null; then
                    log_success "Linkerd Server policy exists for $service"
                else
                    log_failure "Linkerd Server policy missing for $service"
                fi
            done
            ;;
        "none")
            log_warning "No service mesh detected - mTLS tests skipped"
            ;;
    esac
}

# Test 4: Verify authorization policies
test_authorization_policies() {
    log_info "Testing authorization policies..."
    
    case "$MESH_TYPE" in
        "istio")
            # Check default deny policy
            if kubectl get authorizationpolicy default-deny -n "$NAMESPACE" &>/dev/null; then
                log_success "Default deny authorization policy exists"
            else
                log_failure "Default deny authorization policy missing"
            fi
            
            # Check service-specific authorization policies
            SERVICES=("orchestrator" "livekit-agent" "tts-router" "riva-asr-proxy")
            for service in "${SERVICES[@]}"; do
                if kubectl get authorizationpolicy "${service}-authz" -n "$NAMESPACE" &>/dev/null; then
                    log_success "Authorization policy exists for $service"
                else
                    log_failure "Authorization policy missing for $service"
                fi
            done
            ;;
        "linkerd")
            # Check ServerAuthorization policies
            SERVICES=("orchestrator" "livekit-agent" "tts-router" "riva-asr-proxy")
            for service in "${SERVICES[@]}"; do
                if kubectl get serverauthorization "${service}-authz" -n "$NAMESPACE" &>/dev/null; then
                    log_success "ServerAuthorization policy exists for $service"
                else
                    log_failure "ServerAuthorization policy missing for $service"
                fi
            done
            ;;
        "none")
            log_warning "No service mesh detected - authorization policy tests skipped"
            ;;
    esac
}

# Test 5: Verify service mesh sidecars are injected
test_sidecar_injection() {
    log_info "Testing service mesh sidecar injection..."
    
    if [[ "$MESH_TYPE" == "none" ]]; then
        log_warning "No service mesh detected - sidecar injection tests skipped"
        return
    fi
    
    DEPLOYMENTS=$(kubectl get deployments -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}')
    
    for deployment in $DEPLOYMENTS; do
        PODS=$(kubectl get pods -n "$NAMESPACE" -l app="$deployment" --no-headers 2>/dev/null | awk '{print $1}')
        
        for pod in $PODS; do
            case "$MESH_TYPE" in
                "istio")
                    CONTAINERS=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.spec.containers[*].name}')
                    if echo "$CONTAINERS" | grep -q "istio-proxy"; then
                        log_success "Istio sidecar injected in pod $pod"
                    else
                        log_failure "Istio sidecar missing in pod $pod"
                    fi
                    ;;
                "linkerd")
                    CONTAINERS=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.spec.containers[*].name}')
                    if echo "$CONTAINERS" | grep -q "linkerd-proxy"; then
                        log_success "Linkerd proxy injected in pod $pod"
                    else
                        log_failure "Linkerd proxy missing in pod $pod"
                    fi
                    ;;
            esac
        done
    done
}

# Test 6: Verify monitoring and observability
test_monitoring_setup() {
    log_info "Testing monitoring and observability setup..."
    
    # Check ServiceMonitor
    if kubectl get servicemonitor voicehive-network-metrics -n monitoring &>/dev/null; then
        log_success "Network metrics ServiceMonitor exists"
    else
        log_failure "Network metrics ServiceMonitor missing"
    fi
    
    # Check PrometheusRule
    if kubectl get prometheusrule voicehive-network-alerts -n monitoring &>/dev/null; then
        log_success "Network security PrometheusRule exists"
    else
        log_failure "Network security PrometheusRule missing"
    fi
    
    # Check Falco rules (if Falco is installed)
    if kubectl get configmap falco-network-rules -n falco-system &>/dev/null; then
        log_success "Falco network security rules exist"
    else
        log_warning "Falco network security rules not found (Falco may not be installed)"
    fi
}

# Test 7: Verify service connectivity with mTLS
test_service_connectivity() {
    log_info "Testing service connectivity with mTLS..."
    
    # Get a pod from orchestrator deployment
    ORCHESTRATOR_POD=$(kubectl get pods -n "$NAMESPACE" -l app=orchestrator --no-headers 2>/dev/null | head -1 | awk '{print $1}')
    
    if [[ -n "$ORCHESTRATOR_POD" ]]; then
        # Test internal service connectivity
        SERVICES=("tts-router" "riva-asr-proxy")
        for service in "${SERVICES[@]}"; do
            if kubectl exec -n "$NAMESPACE" "$ORCHESTRATOR_POD" -- curl -s -o /dev/null -w "%{http_code}" "http://$service/healthz" 2>/dev/null | grep -q "200"; then
                log_success "Service connectivity test passed for $service"
            else
                log_failure "Service connectivity test failed for $service"
            fi
        done
    else
        log_warning "No orchestrator pod found - service connectivity tests skipped"
    fi
}

# Test 8: Verify external access restrictions
test_external_access_restrictions() {
    log_info "Testing external access restrictions..."
    
    # Get a pod to test from
    TEST_POD=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | head -1 | awk '{print $1}')
    
    if [[ -n "$TEST_POD" ]]; then
        # Test that unauthorized external access is blocked
        # This should fail (which is good)
        if kubectl exec -n "$NAMESPACE" "$TEST_POD" -- timeout 5 curl -s "http://example.com" &>/dev/null; then
            log_failure "Unauthorized external HTTP access is allowed (should be blocked)"
        else
            log_success "Unauthorized external HTTP access is properly blocked"
        fi
        
        # Test that HTTPS access is allowed (for legitimate external APIs)
        if kubectl exec -n "$NAMESPACE" "$TEST_POD" -- timeout 5 curl -s -k "https://api.github.com" &>/dev/null; then
            log_success "Authorized external HTTPS access is allowed"
        else
            log_warning "External HTTPS access may be blocked (check if this is intended)"
        fi
    else
        log_warning "No pods found - external access tests skipped"
    fi
}

# Test 9: Verify security labels and annotations
test_security_labels() {
    log_info "Testing security labels and annotations..."
    
    # Check deployments have proper security labels
    DEPLOYMENTS=$(kubectl get deployments -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}')
    
    for deployment in $DEPLOYMENTS; do
        # Check for security context
        SECURITY_CONTEXT=$(kubectl get deployment "$deployment" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.securityContext}')
        if [[ -n "$SECURITY_CONTEXT" ]]; then
            log_success "Security context configured for deployment $deployment"
        else
            log_failure "Security context missing for deployment $deployment"
        fi
        
        # Check for non-root user
        RUN_AS_NON_ROOT=$(kubectl get deployment "$deployment" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.securityContext.runAsNonRoot}')
        if [[ "$RUN_AS_NON_ROOT" == "true" ]]; then
            log_success "Non-root user configured for deployment $deployment"
        else
            log_failure "Non-root user not configured for deployment $deployment"
        fi
    done
}

# Test 10: Performance and resource validation
test_performance_configuration() {
    log_info "Testing performance and resource configuration..."
    
    case "$MESH_TYPE" in
        "istio")
            # Check Istio proxy resource limits
            PODS=$(kubectl get pods -n "$NAMESPACE" --no-headers | awk '{print $1}')
            for pod in $PODS; do
                PROXY_RESOURCES=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.spec.containers[?(@.name=="istio-proxy")].resources}')
                if [[ -n "$PROXY_RESOURCES" ]]; then
                    log_success "Istio proxy resources configured for pod $pod"
                else
                    log_warning "Istio proxy resources not configured for pod $pod"
                fi
            done
            ;;
        "linkerd")
            # Check Linkerd proxy resource limits
            PODS=$(kubectl get pods -n "$NAMESPACE" --no-headers | awk '{print $1}')
            for pod in $PODS; do
                PROXY_RESOURCES=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.spec.containers[?(@.name=="linkerd-proxy")].resources}')
                if [[ -n "$PROXY_RESOURCES" ]]; then
                    log_success "Linkerd proxy resources configured for pod $pod"
                else
                    log_warning "Linkerd proxy resources not configured for pod $pod"
                fi
            done
            ;;
    esac
}

# Generate summary report
generate_summary() {
    echo
    echo "=================================="
    echo "Network Security Validation Summary"
    echo "=================================="
    echo "Namespace: $NAMESPACE"
    echo "Service Mesh: $MESH_TYPE"
    echo "Total Tests: $TESTS_TOTAL"
    echo "Passed: $TESTS_PASSED"
    echo "Failed: $TESTS_FAILED"
    echo "Success Rate: $(( TESTS_PASSED * 100 / TESTS_TOTAL ))%"
    echo
    
    if [[ $TESTS_FAILED -eq 0 ]]; then
        log_success "All network security tests passed!"
        return 0
    else
        log_failure "$TESTS_FAILED tests failed. Please review and fix the issues."
        return 1
    fi
}

# Main function
main() {
    log_info "Starting network security validation for VoiceHive Hotels"
    log_info "Namespace: $NAMESPACE"
    
    # Detect service mesh
    detect_service_mesh
    
    # Run all tests
    test_namespace_configuration
    test_network_policies
    test_service_mesh_mtls
    test_authorization_policies
    test_sidecar_injection
    test_monitoring_setup
    test_service_connectivity
    test_external_access_restrictions
    test_security_labels
    test_performance_configuration
    
    # Generate summary
    generate_summary
}

# Help function
show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Validate network security implementation for VoiceHive Hotels.

OPTIONS:
    -n, --namespace NS       Kubernetes namespace [default: voicehive]
    -m, --mesh-type TYPE     Service mesh type (auto|istio|linkerd|none) [default: auto]
    -v, --verbose           Enable verbose output
    -h, --help              Show this help message

EXAMPLES:
    # Validate with auto-detection
    $0

    # Validate specific namespace and mesh type
    $0 --namespace voicehive-prod --mesh-type istio

    # Verbose validation
    $0 --verbose

ENVIRONMENT VARIABLES:
    NAMESPACE               Kubernetes namespace (overridden by --namespace)
    MESH_TYPE               Service mesh type (overridden by --mesh-type)
    VERBOSE                 Enable verbose output (overridden by --verbose)

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -m|--mesh-type)
            MESH_TYPE="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE="true"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Run main function
main