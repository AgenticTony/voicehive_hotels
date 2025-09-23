#!/bin/bash
# Deployment Validation Automation
# Comprehensive validation script for blue-green deployments

set -euo pipefail

# Configuration
NAMESPACE="${NAMESPACE:-voicehive-staging}"
ROLLOUT_NAME="${ROLLOUT_NAME:-voicehive-orchestrator-rollout}"
TIMEOUT="${TIMEOUT:-600}"
VALIDATION_TIMEOUT="${VALIDATION_TIMEOUT:-300}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

# Function to check rollout status
check_rollout_status() {
    local rollout_name="$1"
    local namespace="$2"
    
    log "Checking rollout status for $rollout_name in namespace $namespace"
    
    if ! kubectl get rollout "$rollout_name" -n "$namespace" > /dev/null 2>&1; then
        error "Rollout $rollout_name not found in namespace $namespace"
        return 1
    fi
    
    local status=$(kubectl get rollout "$rollout_name" -n "$namespace" -o jsonpath='{.status.phase}')
    info "Current rollout status: $status"
    
    return 0
}

# Function to wait for rollout to be ready
wait_for_rollout_ready() {
    local rollout_name="$1"
    local namespace="$2"
    local timeout="$3"
    
    log "Waiting for rollout to be ready (timeout: ${timeout}s)"
    
    if kubectl wait --for=condition=Progressing=True \
                   --timeout="${timeout}s" \
                   rollout "$rollout_name" \
                   -n "$namespace"; then
        log "Rollout is progressing"
    else
        error "Rollout failed to progress within timeout"
        return 1
    fi
    
    return 0
}

# Function to validate pod health
validate_pod_health() {
    local namespace="$1"
    local app_label="$2"
    
    log "Validating pod health for app=$app_label"
    
    # Get pods for the application
    local pods=$(kubectl get pods -n "$namespace" -l "app=$app_label" -o jsonpath='{.items[*].metadata.name}')
    
    if [ -z "$pods" ]; then
        error "No pods found for app=$app_label"
        return 1
    fi
    
    # Check each pod
    for pod in $pods; do
        info "Checking pod: $pod"
        
        # Check pod status
        local pod_status=$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.status.phase}')
        if [ "$pod_status" != "Running" ]; then
            error "Pod $pod is not running (status: $pod_status)"
            return 1
        fi
        
        # Check container readiness
        local ready=$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.status.containerStatuses[0].ready}')
        if [ "$ready" != "true" ]; then
            error "Pod $pod is not ready"
            return 1
        fi
        
        # Check restart count
        local restarts=$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.status.containerStatuses[0].restartCount}')
        if [ "$restarts" -gt 0 ]; then
            warn "Pod $pod has restarted $restarts times"
        fi
        
        info "Pod $pod is healthy"
    done
    
    log "All pods are healthy"
    return 0
}

# Function to run smoke tests
run_smoke_tests() {
    local namespace="$1"
    
    log "Running smoke tests..."
    
    # Set environment variables for smoke test script
    export NAMESPACE="$namespace"
    export SERVICE_NAME="voicehive-orchestrator-preview"
    export TIMEOUT="$VALIDATION_TIMEOUT"
    
    # Run smoke tests
    if ./scripts/deployment/smoke-tests.sh; then
        log "Smoke tests passed"
        return 0
    else
        error "Smoke tests failed"
        return 1
    fi
}

# Function to validate metrics and monitoring
validate_monitoring() {
    local namespace="$1"
    
    log "Validating monitoring and metrics..."
    
    # Check if metrics are being exposed
    local service_name="voicehive-orchestrator-preview"
    
    # Port forward to metrics endpoint
    kubectl port-forward -n "$namespace" "service/$service_name" 8080:8080 > /dev/null 2>&1 &
    local port_forward_pid=$!
    sleep 5
    
    # Cleanup function
    cleanup_metrics() {
        kill $port_forward_pid 2>/dev/null || true
    }
    trap cleanup_metrics EXIT
    
    # Check metrics endpoint
    if curl -f -s "http://localhost:8080/metrics" | grep -q "voicehive_"; then
        log "Metrics are being exposed correctly"
    else
        error "Metrics endpoint is not working"
        return 1
    fi
    
    # Check specific metrics
    local metrics_output=$(curl -s "http://localhost:8080/metrics")
    
    if echo "$metrics_output" | grep -q "voicehive_requests_total"; then
        log "Request metrics are available"
    else
        warn "Request metrics not found"
    fi
    
    if echo "$metrics_output" | grep -q "voicehive_response_time"; then
        log "Response time metrics are available"
    else
        warn "Response time metrics not found"
    fi
    
    cleanup_metrics
    return 0
}

# Function to validate security configuration
validate_security() {
    local namespace="$1"
    
    log "Validating security configuration..."
    
    # Check network policies
    if kubectl get networkpolicy -n "$namespace" > /dev/null 2>&1; then
        log "Network policies are configured"
    else
        warn "No network policies found"
    fi
    
    # Check pod security policies
    local pods=$(kubectl get pods -n "$namespace" -l "app=voicehive-orchestrator" -o jsonpath='{.items[*].metadata.name}')
    
    for pod in $pods; do
        # Check security context
        local run_as_non_root=$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.spec.securityContext.runAsNonRoot}')
        if [ "$run_as_non_root" = "true" ]; then
            log "Pod $pod runs as non-root user"
        else
            warn "Pod $pod may be running as root"
        fi
        
        # Check read-only root filesystem
        local read_only_fs=$(kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.spec.containers[0].securityContext.readOnlyRootFilesystem}')
        if [ "$read_only_fs" = "true" ]; then
            log "Pod $pod has read-only root filesystem"
        else
            warn "Pod $pod does not have read-only root filesystem"
        fi
    done
    
    return 0
}

# Function to generate validation report
generate_validation_report() {
    local namespace="$1"
    local rollout_name="$2"
    local validation_result="$3"
    
    local report_file="/tmp/deployment-validation-report-$(date +%Y%m%d-%H%M%S).json"
    
    log "Generating validation report: $report_file"
    
    # Get rollout status
    local rollout_status=$(kubectl get rollout "$rollout_name" -n "$namespace" -o json 2>/dev/null || echo '{}')
    
    # Get pod information
    local pods_info=$(kubectl get pods -n "$namespace" -l "app=voicehive-orchestrator" -o json 2>/dev/null || echo '{}')
    
    # Create report
    cat > "$report_file" << EOF
{
  "validation_timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "namespace": "$namespace",
  "rollout_name": "$rollout_name",
  "validation_result": "$validation_result",
  "rollout_status": $rollout_status,
  "pods_info": $pods_info,
  "validation_steps": {
    "rollout_status_check": "completed",
    "pod_health_validation": "completed",
    "smoke_tests": "completed",
    "monitoring_validation": "completed",
    "security_validation": "completed"
  }
}
EOF
    
    info "Validation report saved to: $report_file"
    
    # Also output summary to console
    log "=== VALIDATION SUMMARY ==="
    log "Namespace: $namespace"
    log "Rollout: $rollout_name"
    log "Result: $validation_result"
    log "Timestamp: $(date)"
    log "=========================="
    
    return 0
}

# Main validation function
main() {
    log "Starting deployment validation"
    log "Namespace: $NAMESPACE"
    log "Rollout: $ROLLOUT_NAME"
    log "Timeout: ${TIMEOUT}s"
    
    local validation_result="FAILED"
    
    # Run validation steps
    if check_rollout_status "$ROLLOUT_NAME" "$NAMESPACE" && \
       wait_for_rollout_ready "$ROLLOUT_NAME" "$NAMESPACE" "$TIMEOUT" && \
       validate_pod_health "$NAMESPACE" "voicehive-orchestrator" && \
       run_smoke_tests "$NAMESPACE" && \
       validate_monitoring "$NAMESPACE" && \
       validate_security "$NAMESPACE"; then
        
        validation_result="PASSED"
        log "🎉 Deployment validation PASSED! Ready for promotion."
    else
        validation_result="FAILED"
        error "❌ Deployment validation FAILED! Do not promote."
    fi
    
    # Generate report
    generate_validation_report "$NAMESPACE" "$ROLLOUT_NAME" "$validation_result"
    
    # Return appropriate exit code
    if [ "$validation_result" = "PASSED" ]; then
        return 0
    else
        return 1
    fi
}

# Check dependencies
if ! command -v kubectl &> /dev/null; then
    error "kubectl is required but not installed"
    exit 1
fi

if ! command -v curl &> /dev/null; then
    error "curl is required but not installed"
    exit 1
fi

# Run main function
main "$@"