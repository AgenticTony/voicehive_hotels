#!/bin/bash
# Emergency Rollback Procedures
# Automated rollback system for blue-green deployments

set -euo pipefail

# Configuration
NAMESPACE="${NAMESPACE:-voicehive-staging}"
ROLLOUT_NAME="${ROLLOUT_NAME:-voicehive-orchestrator-rollout}"
EMERGENCY_MODE="${EMERGENCY_MODE:-false}"
ROLLBACK_TIMEOUT="${ROLLBACK_TIMEOUT:-120}"
NOTIFICATION_WEBHOOK="${NOTIFICATION_WEBHOOK:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
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

emergency() {
    echo -e "${PURPLE}[$(date +'%Y-%m-%d %H:%M:%S')] EMERGENCY: $1${NC}"
}

# Function to send notifications
send_notification() {
    local message="$1"
    local severity="${2:-info}"
    
    if [ -n "$NOTIFICATION_WEBHOOK" ]; then
        local payload=$(cat << EOF
{
  "text": "🚨 VoiceHive Deployment Alert",
  "attachments": [
    {
      "color": "$( [ "$severity" = "error" ] && echo "danger" || echo "warning" )",
      "fields": [
        {
          "title": "Message",
          "value": "$message",
          "short": false
        },
        {
          "title": "Namespace",
          "value": "$NAMESPACE",
          "short": true
        },
        {
          "title": "Rollout",
          "value": "$ROLLOUT_NAME",
          "short": true
        },
        {
          "title": "Timestamp",
          "value": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
          "short": true
        }
      ]
    }
  ]
}
EOF
        )
        
        curl -s -X POST -H "Content-Type: application/json" \
             -d "$payload" "$NOTIFICATION_WEBHOOK" > /dev/null || true
    fi
}

# Function to check current deployment status
check_current_status() {
    log "Checking current deployment status..."
    
    # Check if rollout exists
    if ! kubectl get rollout "$ROLLOUT_NAME" -n "$NAMESPACE" > /dev/null 2>&1; then
        error "Rollout $ROLLOUT_NAME not found in namespace $NAMESPACE"
        return 1
    fi
    
    # Get rollout status
    local status=$(kubectl get rollout "$ROLLOUT_NAME" -n "$NAMESPACE" -o jsonpath='{.status.phase}')
    local current_revision=$(kubectl get rollout "$ROLLOUT_NAME" -n "$NAMESPACE" -o jsonpath='{.status.currentPodHash}')
    local stable_revision=$(kubectl get rollout "$ROLLOUT_NAME" -n "$NAMESPACE" -o jsonpath='{.status.stableRS}')
    
    info "Current status: $status"
    info "Current revision: $current_revision"
    info "Stable revision: $stable_revision"
    
    # Check if rollback is needed
    if [ "$status" = "Degraded" ] || [ "$status" = "Progressing" ]; then
        warn "Deployment appears to be in problematic state: $status"
        return 2
    fi
    
    return 0
}

# Function to perform emergency rollback
emergency_rollback() {
    emergency "Initiating EMERGENCY ROLLBACK"
    send_notification "Emergency rollback initiated for $ROLLOUT_NAME" "error"
    
    # Abort current rollout immediately
    log "Aborting current rollout..."
    if kubectl argo rollouts abort "$ROLLOUT_NAME" -n "$NAMESPACE"; then
        log "Rollout aborted successfully"
    else
        error "Failed to abort rollout"
        return 1
    fi
    
    # Promote stable version immediately
    log "Promoting stable version..."
    if kubectl argo rollouts promote "$ROLLOUT_NAME" -n "$NAMESPACE" --skip-all-steps; then
        log "Stable version promoted"
    else
        error "Failed to promote stable version"
        return 1
    fi
    
    # Wait for rollback to complete
    log "Waiting for rollback to complete..."
    if kubectl argo rollouts status "$ROLLOUT_NAME" -n "$NAMESPACE" --timeout="${ROLLBACK_TIMEOUT}s"; then
        log "Emergency rollback completed successfully"
        send_notification "Emergency rollback completed successfully" "info"
        return 0
    else
        error "Emergency rollback failed or timed out"
        send_notification "Emergency rollback FAILED - manual intervention required" "error"
        return 1
    fi
}

# Function to perform standard rollback
standard_rollback() {
    log "Initiating standard rollback"
    send_notification "Standard rollback initiated for $ROLLOUT_NAME" "warning"
    
    # Get rollout history
    log "Checking rollout history..."
    kubectl argo rollouts history "$ROLLOUT_NAME" -n "$NAMESPACE"
    
    # Rollback to previous version
    log "Rolling back to previous version..."
    if kubectl argo rollouts undo "$ROLLOUT_NAME" -n "$NAMESPACE"; then
        log "Rollback command executed"
    else
        error "Failed to execute rollback command"
        return 1
    fi
    
    # Wait for rollback to complete
    log "Waiting for rollback to complete..."
    if kubectl argo rollouts status "$ROLLOUT_NAME" -n "$NAMESPACE" --timeout="${ROLLBACK_TIMEOUT}s"; then
        log "Standard rollback completed successfully"
        send_notification "Standard rollback completed successfully" "info"
        return 0
    else
        error "Standard rollback failed or timed out"
        send_notification "Standard rollback FAILED" "error"
        return 1
    fi
}

# Function to validate rollback success
validate_rollback() {
    log "Validating rollback success..."
    
    # Check pod health
    local pods=$(kubectl get pods -n "$NAMESPACE" -l "app=voicehive-orchestrator" --field-selector=status.phase=Running -o jsonpath='{.items[*].metadata.name}')
    
    if [ -z "$pods" ]; then
        error "No running pods found after rollback"
        return 1
    fi
    
    local pod_count=$(echo "$pods" | wc -w)
    log "Found $pod_count running pods"
    
    # Check service endpoints
    log "Checking service endpoints..."
    local active_service="voicehive-orchestrator-active"
    
    # Port forward to check health
    kubectl port-forward -n "$NAMESPACE" "service/$active_service" 8000:80 > /dev/null 2>&1 &
    local port_forward_pid=$!
    sleep 5
    
    # Cleanup function
    cleanup_validation() {
        kill $port_forward_pid 2>/dev/null || true
    }
    trap cleanup_validation EXIT
    
    # Test health endpoint
    if curl -f -s "http://localhost:8000/health/ready" > /dev/null; then
        log "Health endpoint is responding"
    else
        error "Health endpoint is not responding"
        cleanup_validation
        return 1
    fi
    
    # Test basic functionality
    local response_code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/health/live")
    if [ "$response_code" = "200" ]; then
        log "Basic functionality test passed"
    else
        error "Basic functionality test failed (HTTP $response_code)"
        cleanup_validation
        return 1
    fi
    
    cleanup_validation
    log "Rollback validation completed successfully"
    return 0
}

# Function to generate rollback report
generate_rollback_report() {
    local rollback_type="$1"
    local rollback_result="$2"
    local rollback_reason="${3:-Manual rollback}"
    
    local report_file="/tmp/rollback-report-$(date +%Y%m%d-%H%M%S).json"
    
    log "Generating rollback report: $report_file"
    
    # Get current rollout status
    local rollout_status=$(kubectl get rollout "$ROLLOUT_NAME" -n "$NAMESPACE" -o json 2>/dev/null || echo '{}')
    
    # Get pod information
    local pods_info=$(kubectl get pods -n "$NAMESPACE" -l "app=voicehive-orchestrator" -o json 2>/dev/null || echo '{}')
    
    # Create report
    cat > "$report_file" << EOF
{
  "rollback_timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "namespace": "$NAMESPACE",
  "rollout_name": "$ROLLOUT_NAME",
  "rollback_type": "$rollback_type",
  "rollback_result": "$rollback_result",
  "rollback_reason": "$rollback_reason",
  "rollout_status": $rollout_status,
  "pods_info": $pods_info,
  "rollback_steps": {
    "status_check": "completed",
    "rollback_execution": "completed",
    "validation": "completed"
  }
}
EOF
    
    info "Rollback report saved to: $report_file"
    
    # Output summary
    log "=== ROLLBACK SUMMARY ==="
    log "Type: $rollback_type"
    log "Result: $rollback_result"
    log "Reason: $rollback_reason"
    log "Namespace: $NAMESPACE"
    log "Rollout: $ROLLOUT_NAME"
    log "Timestamp: $(date)"
    log "======================="
    
    return 0
}

# Function to show usage
show_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Emergency Rollback Procedures for VoiceHive Deployments

OPTIONS:
    -n, --namespace NAMESPACE       Kubernetes namespace (default: voicehive-staging)
    -r, --rollout ROLLOUT          Rollout name (default: voicehive-orchestrator-rollout)
    -e, --emergency                Enable emergency mode (immediate rollback)
    -t, --timeout SECONDS          Rollback timeout in seconds (default: 120)
    -w, --webhook URL              Notification webhook URL
    -h, --help                     Show this help message

EXAMPLES:
    # Standard rollback
    $0 --namespace voicehive-production

    # Emergency rollback
    $0 --emergency --namespace voicehive-production

    # Rollback with notifications
    $0 --webhook https://hooks.slack.com/services/...

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -r|--rollout)
            ROLLOUT_NAME="$2"
            shift 2
            ;;
        -e|--emergency)
            EMERGENCY_MODE="true"
            shift
            ;;
        -t|--timeout)
            ROLLBACK_TIMEOUT="$2"
            shift 2
            ;;
        -w|--webhook)
            NOTIFICATION_WEBHOOK="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main execution
main() {
    if [ "$EMERGENCY_MODE" = "true" ]; then
        emergency "EMERGENCY MODE ACTIVATED"
        log "Starting emergency rollback procedures"
    else
        log "Starting standard rollback procedures"
    fi
    
    log "Namespace: $NAMESPACE"
    log "Rollout: $ROLLOUT_NAME"
    log "Timeout: ${ROLLBACK_TIMEOUT}s"
    
    local rollback_result="FAILED"
    local rollback_type="standard"
    
    # Check current status
    local status_check_result
    check_current_status
    status_check_result=$?
    
    if [ $status_check_result -eq 1 ]; then
        error "Cannot proceed with rollback - rollout not found"
        return 1
    fi
    
    # Perform rollback based on mode
    if [ "$EMERGENCY_MODE" = "true" ]; then
        rollback_type="emergency"
        if emergency_rollback; then
            rollback_result="SUCCESS"
        fi
    else
        rollback_type="standard"
        if standard_rollback; then
            rollback_result="SUCCESS"
        fi
    fi
    
    # Validate rollback if successful
    if [ "$rollback_result" = "SUCCESS" ]; then
        if validate_rollback; then
            log "Rollback validation passed"
        else
            warn "Rollback completed but validation failed"
            rollback_result="SUCCESS_WITH_WARNINGS"
        fi
    fi
    
    # Generate report
    generate_rollback_report "$rollback_type" "$rollback_result" "Automated rollback procedure"
    
    # Final notification
    if [ "$rollback_result" = "SUCCESS" ]; then
        log "🎉 Rollback completed successfully!"
        send_notification "Rollback completed successfully" "info"
        return 0
    else
        error "❌ Rollback failed or completed with issues"
        send_notification "Rollback failed - manual intervention may be required" "error"
        return 1
    fi
}

# Check dependencies
if ! command -v kubectl &> /dev/null; then
    error "kubectl is required but not installed"
    exit 1
fi

if ! kubectl argo rollouts version &> /dev/null; then
    error "Argo Rollouts CLI is required but not installed"
    exit 1
fi

# Run main function
main "$@"