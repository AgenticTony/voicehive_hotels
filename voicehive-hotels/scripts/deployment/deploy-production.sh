#!/bin/bash
# Production Deployment Automation
# Complete blue-green deployment pipeline with validation and rollback capabilities

set -euo pipefail

# Configuration
ENVIRONMENT="${ENVIRONMENT:-production}"
NAMESPACE="voicehive-$ENVIRONMENT"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DRY_RUN="${DRY_RUN:-false}"
SKIP_VALIDATION="${SKIP_VALIDATION:-false}"
AUTO_PROMOTE="${AUTO_PROMOTE:-false}"

# Timeouts
DEPLOYMENT_TIMEOUT="${DEPLOYMENT_TIMEOUT:-600}"
VALIDATION_TIMEOUT="${VALIDATION_TIMEOUT:-300}"
ROLLBACK_TIMEOUT="${ROLLBACK_TIMEOUT:-120}"

# Notification settings
SLACK_WEBHOOK="${SLACK_WEBHOOK:-}"
EMAIL_RECIPIENTS="${EMAIL_RECIPIENTS:-}"

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

success() {
    echo -e "${PURPLE}[$(date +'%Y-%m-%d %H:%M:%S')] SUCCESS: $1${NC}"
}

# Function to send notifications
send_notification() {
    local message="$1"
    local status="${2:-info}"
    
    # Slack notification
    if [ -n "$SLACK_WEBHOOK" ]; then
        local color="good"
        local emoji="ℹ️"
        
        case "$status" in
            "success") color="good"; emoji="✅" ;;
            "warning") color="warning"; emoji="⚠️" ;;
            "error") color="danger"; emoji="❌" ;;
            "info") color="#439FE0"; emoji="ℹ️" ;;
        esac
        
        local payload=$(cat << EOF
{
  "attachments": [
    {
      "color": "$color",
      "pretext": "$emoji VoiceHive Production Deployment",
      "fields": [
        {
          "title": "Environment",
          "value": "$ENVIRONMENT",
          "short": true
        },
        {
          "title": "Image Tag",
          "value": "$IMAGE_TAG",
          "short": true
        },
        {
          "title": "Status",
          "value": "$message",
          "short": false
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
             -d "$payload" "$SLACK_WEBHOOK" > /dev/null || true
    fi
    
    # Email notification (if configured)
    if [ -n "$EMAIL_RECIPIENTS" ]; then
        echo "$message" | mail -s "VoiceHive Deployment - $status" "$EMAIL_RECIPIENTS" || true
    fi
}

# Function to validate prerequisites
validate_prerequisites() {
    log "Validating deployment prerequisites..."
    
    # Check required tools
    local required_tools=("kubectl" "helm" "yq" "curl" "jq")
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            error "Required tool not found: $tool"
            return 1
        fi
    done
    
    # Check cluster connectivity
    if ! kubectl cluster-info > /dev/null 2>&1; then
        error "Cannot connect to Kubernetes cluster"
        return 1
    fi
    
    # Check namespace exists
    if ! kubectl get namespace "$NAMESPACE" > /dev/null 2>&1; then
        error "Namespace $NAMESPACE does not exist"
        return 1
    fi
    
    # Validate configuration
    if ! ./scripts/deployment/config-manager.sh check-readiness "$ENVIRONMENT"; then
        error "Environment configuration validation failed"
        return 1
    fi
    
    # Check Argo Rollouts
    if ! kubectl get crd rollouts.argoproj.io > /dev/null 2>&1; then
        error "Argo Rollouts CRD not found"
        return 1
    fi
    
    log "Prerequisites validation passed"
    return 0
}

# Function to prepare deployment
prepare_deployment() {
    log "Preparing deployment for environment: $ENVIRONMENT"
    
    # Generate configuration
    if ! ./scripts/deployment/config-manager.sh generate "$ENVIRONMENT"; then
        error "Failed to generate configuration"
        return 1
    fi
    
    # Apply configuration
    if ! ./scripts/deployment/config-manager.sh apply "$ENVIRONMENT"; then
        error "Failed to apply configuration"
        return 1
    fi
    
    # Backup current state
    if ! ./scripts/deployment/rollback-procedures.sh backup "$ENVIRONMENT"; then
        error "Failed to backup current state"
        return 1
    fi
    
    log "Deployment preparation completed"
    return 0
}

# Function to execute blue-green deployment
execute_deployment() {
    log "Executing blue-green deployment..."
    
    if [ "$DRY_RUN" = "true" ]; then
        warn "DRY RUN MODE - No actual deployment will be performed"
        return 0
    fi
    
    # Update image tag in rollout
    log "Updating image tag to: $IMAGE_TAG"
    kubectl patch rollout voicehive-orchestrator-rollout \
        -n "$NAMESPACE" \
        --type='merge' \
        -p="{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"orchestrator\",\"image\":\"voicehive/orchestrator:$IMAGE_TAG\"}]}}}}"
    
    # Wait for rollout to start
    log "Waiting for rollout to start..."
    kubectl argo rollouts status voicehive-orchestrator-rollout \
        -n "$NAMESPACE" \
        --timeout="${DEPLOYMENT_TIMEOUT}s" \
        --watch
    
    log "Blue-green deployment initiated successfully"
    return 0
}

# Function to validate deployment
validate_deployment() {
    if [ "$SKIP_VALIDATION" = "true" ]; then
        warn "Skipping deployment validation"
        return 0
    fi
    
    log "Validating deployment..."
    
    # Set environment variables for validation script
    export NAMESPACE="$NAMESPACE"
    export ROLLOUT_NAME="voicehive-orchestrator-rollout"
    export TIMEOUT="$VALIDATION_TIMEOUT"
    
    # Run validation
    if ./scripts/deployment/validate-deployment.sh; then
        log "Deployment validation passed"
        return 0
    else
        error "Deployment validation failed"
        return 1
    fi
}

# Function to promote deployment
promote_deployment() {
    log "Promoting deployment..."
    
    if [ "$DRY_RUN" = "true" ]; then
        warn "DRY RUN MODE - No actual promotion will be performed"
        return 0
    fi
    
    # Promote the rollout
    kubectl argo rollouts promote voicehive-orchestrator-rollout -n "$NAMESPACE"
    
    # Wait for promotion to complete
    kubectl argo rollouts status voicehive-orchestrator-rollout \
        -n "$NAMESPACE" \
        --timeout="${DEPLOYMENT_TIMEOUT}s"
    
    log "Deployment promoted successfully"
    return 0
}

# Function to handle deployment failure
handle_deployment_failure() {
    local failure_reason="$1"
    
    error "Deployment failed: $failure_reason"
    send_notification "Deployment failed: $failure_reason" "error"
    
    # Automatic rollback
    warn "Initiating automatic rollback..."
    
    export NAMESPACE="$NAMESPACE"
    export ROLLOUT_NAME="voicehive-orchestrator-rollout"
    export EMERGENCY_MODE="true"
    export ROLLBACK_TIMEOUT="$ROLLBACK_TIMEOUT"
    
    if ./scripts/deployment/rollback-procedures.sh --emergency; then
        log "Automatic rollback completed successfully"
        send_notification "Automatic rollback completed after deployment failure" "warning"
    else
        error "Automatic rollback failed - manual intervention required"
        send_notification "URGENT: Automatic rollback failed - manual intervention required" "error"
    fi
}

# Function to generate deployment report
generate_deployment_report() {
    local deployment_result="$1"
    local deployment_start_time="$2"
    local deployment_end_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    
    local report_file="/tmp/deployment-report-$(date +%Y%m%d-%H%M%S).json"
    
    log "Generating deployment report: $report_file"
    
    # Get rollout status
    local rollout_status=$(kubectl get rollout voicehive-orchestrator-rollout -n "$NAMESPACE" -o json 2>/dev/null || echo '{}')
    
    # Get deployment events
    local events=$(kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' -o json 2>/dev/null || echo '{}')
    
    # Create comprehensive report
    cat > "$report_file" << EOF
{
  "deployment_metadata": {
    "environment": "$ENVIRONMENT",
    "namespace": "$NAMESPACE",
    "image_tag": "$IMAGE_TAG",
    "deployment_result": "$deployment_result",
    "start_time": "$deployment_start_time",
    "end_time": "$deployment_end_time",
    "dry_run": $DRY_RUN,
    "auto_promote": $AUTO_PROMOTE,
    "skip_validation": $SKIP_VALIDATION
  },
  "rollout_status": $rollout_status,
  "events": $events,
  "deployment_steps": {
    "prerequisites_validation": "completed",
    "deployment_preparation": "completed",
    "blue_green_deployment": "completed",
    "deployment_validation": "$( [ "$SKIP_VALIDATION" = "true" ] && echo "skipped" || echo "completed" )",
    "deployment_promotion": "$( [ "$deployment_result" = "SUCCESS" ] && echo "completed" || echo "failed" )"
  }
}
EOF
    
    info "Deployment report saved to: $report_file"
    
    # Output summary
    log "=== DEPLOYMENT SUMMARY ==="
    log "Environment: $ENVIRONMENT"
    log "Image Tag: $IMAGE_TAG"
    log "Result: $deployment_result"
    log "Start Time: $deployment_start_time"
    log "End Time: $deployment_end_time"
    log "=========================="
    
    return 0
}

# Function to show usage
show_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Production Deployment Automation for VoiceHive

OPTIONS:
    -e, --environment ENV          Target environment (default: production)
    -t, --tag TAG                  Docker image tag to deploy (required)
    -d, --dry-run                  Perform dry run without actual deployment
    -s, --skip-validation          Skip deployment validation
    -a, --auto-promote             Automatically promote after validation
    --deployment-timeout SECONDS   Deployment timeout (default: 600)
    --validation-timeout SECONDS   Validation timeout (default: 300)
    --rollback-timeout SECONDS     Rollback timeout (default: 120)
    --slack-webhook URL            Slack webhook for notifications
    --email EMAIL                  Email recipients for notifications
    -h, --help                     Show this help message

EXAMPLES:
    # Deploy specific version to production
    $0 --tag v1.2.3

    # Dry run deployment
    $0 --tag v1.2.3 --dry-run

    # Deploy with auto-promotion
    $0 --tag v1.2.3 --auto-promote

    # Deploy to staging
    $0 --environment staging --tag v1.2.3

    # Deploy with notifications
    $0 --tag v1.2.3 --slack-webhook https://hooks.slack.com/...

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--environment)
            ENVIRONMENT="$2"
            NAMESPACE="voicehive-$ENVIRONMENT"
            shift 2
            ;;
        -t|--tag)
            IMAGE_TAG="$2"
            shift 2
            ;;
        -d|--dry-run)
            DRY_RUN="true"
            shift
            ;;
        -s|--skip-validation)
            SKIP_VALIDATION="true"
            shift
            ;;
        -a|--auto-promote)
            AUTO_PROMOTE="true"
            shift
            ;;
        --deployment-timeout)
            DEPLOYMENT_TIMEOUT="$2"
            shift 2
            ;;
        --validation-timeout)
            VALIDATION_TIMEOUT="$2"
            shift 2
            ;;
        --rollback-timeout)
            ROLLBACK_TIMEOUT="$2"
            shift 2
            ;;
        --slack-webhook)
            SLACK_WEBHOOK="$2"
            shift 2
            ;;
        --email)
            EMAIL_RECIPIENTS="$2"
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

# Validate required parameters
if [ -z "$IMAGE_TAG" ]; then
    error "Image tag is required. Use --tag option."
    show_usage
    exit 1
fi

# Main execution
main() {
    local deployment_start_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    local deployment_result="FAILED"
    
    log "Starting production deployment automation"
    log "Environment: $ENVIRONMENT"
    log "Namespace: $NAMESPACE"
    log "Image Tag: $IMAGE_TAG"
    log "Dry Run: $DRY_RUN"
    log "Auto Promote: $AUTO_PROMOTE"
    
    send_notification "Deployment started for image tag: $IMAGE_TAG" "info"
    
    # Execute deployment pipeline
    if validate_prerequisites && \
       prepare_deployment && \
       execute_deployment && \
       validate_deployment; then
        
        # Decide on promotion
        if [ "$AUTO_PROMOTE" = "true" ]; then
            if promote_deployment; then
                deployment_result="SUCCESS"
                success "🎉 Deployment completed successfully and promoted!"
                send_notification "Deployment completed successfully and promoted" "success"
            else
                handle_deployment_failure "Promotion failed"
            fi
        else
            deployment_result="SUCCESS_PENDING_PROMOTION"
            success "🎉 Deployment completed successfully! Manual promotion required."
            send_notification "Deployment completed successfully - awaiting manual promotion" "success"
        fi
    else
        handle_deployment_failure "Deployment pipeline failed"
    fi
    
    # Generate report
    generate_deployment_report "$deployment_result" "$deployment_start_time"
    
    # Return appropriate exit code
    if [[ "$deployment_result" =~ ^SUCCESS ]]; then
        return 0
    else
        return 1
    fi
}

# Run main function
main "$@"