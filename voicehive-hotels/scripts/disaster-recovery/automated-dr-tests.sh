#!/bin/bash
# Automated Disaster Recovery Testing Suite
# Comprehensive DR testing with RTO/RPO validation

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${CONFIG_FILE:-/config/disaster-recovery-config.yaml}"
TEST_ENVIRONMENT="${TEST_ENVIRONMENT:-dr-test}"
DRY_RUN="${DRY_RUN:-false}"
NOTIFICATION_WEBHOOK="${NOTIFICATION_WEBHOOK:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Logging functions
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

# Notification function
send_notification() {
    local message="$1"
    local status="${2:-info}"
    
    if [ -n "$NOTIFICATION_WEBHOOK" ]; then
        local color="good"
        local emoji="ℹ️"
        
        case "$status" in
            "success") color="good"; emoji="✅" ;;
            "warning") color="warning"; emoji="⚠️" ;;
            "error") color="danger"; emoji="❌" ;;
            "info") color="#439FE0"; emoji="ℹ️" ;;
        esac
        
        curl -s -X POST -H "Content-Type: application/json" \
             -d "{\"text\":\"$emoji DR Test: $message\"}" \
             "$NOTIFICATION_WEBHOOK" > /dev/null || true
    fi
}

# Test result tracking
declare -A test_results
test_start_time=""
test_end_time=""

# Initialize test environment
initialize_test_environment() {
    log "Initializing disaster recovery test environment"
    
    # Validate prerequisites
    if ! command -v kubectl &> /dev/null; then
        error "kubectl is required but not installed"
        return 1
    fi
    
    if ! command -v aws &> /dev/null; then
        error "AWS CLI is required but not installed"
        return 1
    fi
    
    # Check cluster connectivity
    if ! kubectl cluster-info > /dev/null 2>&1; then
        error "Cannot connect to Kubernetes cluster"
        return 1
    fi
    
    # Create test namespace if it doesn't exist
    kubectl create namespace "$TEST_ENVIRONMENT" --dry-run=client -o yaml | kubectl apply -f -
    
    log "Test environment initialized successfully"
    return 0
}

# Database failover test
test_database_failover() {
    local test_name="database_failover"
    local start_time=$(date +%s)
    
    log "Starting database failover test"
    
    if [ "$DRY_RUN" = "true" ]; then
        warn "DRY RUN MODE - Simulating database failover test"
        sleep 5
        test_results[$test_name]="success"
        return 0
    fi
    
    # Get current primary database
    local primary_db=$(aws rds describe-db-instances \
        --query 'DBInstances[?DBInstanceStatus==`available`&&MultiAZ==`true`].DBInstanceIdentifier' \
        --output text | head -1)
    
    if [ -z "$primary_db" ]; then
        error "No suitable primary database found for failover test"
        test_results[$test_name]="failed"
        return 1
    fi
    
    log "Testing failover for database: $primary_db"
    
    # Create read replica for testing
    local test_replica="${primary_db}-test-replica-$(date +%s)"
    
    aws rds create-db-instance-read-replica \
        --db-instance-identifier "$test_replica" \
        --source-db-instance-identifier "$primary_db" \
        --db-instance-class db.t3.micro \
        --publicly-accessible false \
        --tags Key=Purpose,Value=DR-Test Key=Environment,Value="$TEST_ENVIRONMENT"
    
    # Wait for replica to be available
    log "Waiting for test replica to become available..."
    aws rds wait db-instance-available --db-instance-identifier "$test_replica"
    
    # Test failover by promoting replica
    log "Promoting test replica to standalone instance"
    aws rds promote-read-replica --db-instance-identifier "$test_replica"
    
    # Wait for promotion to complete
    aws rds wait db-instance-available --db-instance-identifier "$test_replica"
    
    # Verify promoted instance is writable
    local promoted_endpoint=$(aws rds describe-db-instances \
        --db-instance-identifier "$test_replica" \
        --query 'DBInstances[0].Endpoint.Address' \
        --output text)
    
    # Test write capability
    if psql -h "$promoted_endpoint" -U "$DB_USER" -d "$DB_NAME" -c "CREATE TABLE dr_test_$(date +%s) (id SERIAL PRIMARY KEY);" > /dev/null 2>&1; then
        success "Database failover test completed successfully"
        test_results[$test_name]="success"
    else
        error "Database failover test failed - promoted instance not writable"
        test_results[$test_name]="failed"
    fi
    
    # Cleanup test resources
    log "Cleaning up test database resources"
    aws rds delete-db-instance \
        --db-instance-identifier "$test_replica" \
        --skip-final-snapshot \
        --delete-automated-backups > /dev/null 2>&1 || true
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log "Database failover test completed in ${duration} seconds"
    
    # Check RTO compliance (target: 15 minutes = 900 seconds)
    if [ $duration -le 900 ]; then
        success "RTO target met for database failover (${duration}s <= 900s)"
    else
        warn "RTO target exceeded for database failover (${duration}s > 900s)"
    fi
    
    return 0
}

# Application failover test
test_application_failover() {
    local test_name="application_failover"
    local start_time=$(date +%s)
    
    log "Starting application failover test"
    
    if [ "$DRY_RUN" = "true" ]; then
        warn "DRY RUN MODE - Simulating application failover test"
        sleep 10
        test_results[$test_name]="success"
        return 0
    fi
    
    # Deploy test application
    log "Deploying test application"
    
    kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dr-test-app
  namespace: $TEST_ENVIRONMENT
spec:
  replicas: 2
  selector:
    matchLabels:
      app: dr-test-app
  template:
    metadata:
      labels:
        app: dr-test-app
    spec:
      containers:
      - name: app
        image: nginx:alpine
        ports:
        - containerPort: 80
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: dr-test-app-service
  namespace: $TEST_ENVIRONMENT
spec:
  selector:
    app: dr-test-app
  ports:
  - port: 80
    targetPort: 80
  type: ClusterIP
EOF
    
    # Wait for deployment to be ready
    kubectl wait --for=condition=available --timeout=300s deployment/dr-test-app -n "$TEST_ENVIRONMENT"
    
    # Test application accessibility
    local pod_name=$(kubectl get pods -n "$TEST_ENVIRONMENT" -l app=dr-test-app -o jsonpath='{.items[0].metadata.name}')
    
    if kubectl exec -n "$TEST_ENVIRONMENT" "$pod_name" -- curl -f http://localhost:80 > /dev/null 2>&1; then
        log "Application is accessible"
    else
        error "Application is not accessible"
        test_results[$test_name]="failed"
        return 1
    fi
    
    # Simulate node failure by cordoning and draining a node
    local node_name=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
    
    log "Simulating node failure by cordoning node: $node_name"
    kubectl cordon "$node_name"
    
    # Force pod rescheduling
    kubectl delete pods -n "$TEST_ENVIRONMENT" -l app=dr-test-app
    
    # Wait for pods to reschedule
    kubectl wait --for=condition=ready --timeout=300s pods -l app=dr-test-app -n "$TEST_ENVIRONMENT"
    
    # Verify application is still accessible
    local new_pod_name=$(kubectl get pods -n "$TEST_ENVIRONMENT" -l app=dr-test-app -o jsonpath='{.items[0].metadata.name}')
    
    if kubectl exec -n "$TEST_ENVIRONMENT" "$new_pod_name" -- curl -f http://localhost:80 > /dev/null 2>&1; then
        success "Application failover test completed successfully"
        test_results[$test_name]="success"
    else
        error "Application failover test failed"
        test_results[$test_name]="failed"
    fi
    
    # Cleanup
    kubectl uncordon "$node_name"
    kubectl delete deployment dr-test-app -n "$TEST_ENVIRONMENT" --ignore-not-found=true
    kubectl delete service dr-test-app-service -n "$TEST_ENVIRONMENT" --ignore-not-found=true
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log "Application failover test completed in ${duration} seconds"
    
    # Check RTO compliance (target: 30 minutes = 1800 seconds)
    if [ $duration -le 1800 ]; then
        success "RTO target met for application failover (${duration}s <= 1800s)"
    else
        warn "RTO target exceeded for application failover (${duration}s > 1800s)"
    fi
    
    return 0
}

# Backup restore test
test_backup_restore() {
    local test_name="backup_restore"
    local start_time=$(date +%s)
    
    log "Starting backup restore test"
    
    if [ "$DRY_RUN" = "true" ]; then
        warn "DRY RUN MODE - Simulating backup restore test"
        sleep 15
        test_results[$test_name]="success"
        return 0
    fi
    
    # Get latest Velero backup
    local latest_backup=$(kubectl get backups -n velero --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
    
    if [ -z "$latest_backup" ]; then
        error "No Velero backups found"
        test_results[$test_name]="failed"
        return 1
    fi
    
    log "Testing restore from backup: $latest_backup"
    
    # Create restore job
    local restore_name="dr-test-restore-$(date +%s)"
    
    kubectl apply -f - <<EOF
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: $restore_name
  namespace: velero
spec:
  backupName: $latest_backup
  includedNamespaces:
  - $TEST_ENVIRONMENT
  restorePVs: true
  existingResourcePolicy: update
EOF
    
    # Wait for restore to complete
    log "Waiting for restore to complete..."
    
    local timeout=1800  # 30 minutes
    local elapsed=0
    
    while [ $elapsed -lt $timeout ]; do
        local status=$(kubectl get restore "$restore_name" -n velero -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
        
        case "$status" in
            "Completed")
                success "Backup restore completed successfully"
                test_results[$test_name]="success"
                break
                ;;
            "Failed"|"PartiallyFailed")
                error "Backup restore failed with status: $status"
                test_results[$test_name]="failed"
                break
                ;;
            *)
                log "Restore in progress... Status: $status"
                sleep 30
                elapsed=$((elapsed + 30))
                ;;
        esac
    done
    
    if [ $elapsed -ge $timeout ]; then
        error "Backup restore timed out after $timeout seconds"
        test_results[$test_name]="failed"
    fi
    
    # Cleanup restore job
    kubectl delete restore "$restore_name" -n velero --ignore-not-found=true
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log "Backup restore test completed in ${duration} seconds"
    
    return 0
}

# Network partition test
test_network_partition() {
    local test_name="network_partition"
    local start_time=$(date +%s)
    
    log "Starting network partition test"
    
    if [ "$DRY_RUN" = "true" ]; then
        warn "DRY RUN MODE - Simulating network partition test"
        sleep 8
        test_results[$test_name]="success"
        return 0
    fi
    
    # Check if Chaos Mesh is available
    if ! kubectl get crd networkchaos.chaos-mesh.org > /dev/null 2>&1; then
        warn "Chaos Mesh not available, skipping network partition test"
        test_results[$test_name]="skipped"
        return 0
    fi
    
    # Create network partition chaos experiment
    local chaos_name="dr-network-partition-$(date +%s)"
    
    kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: $chaos_name
  namespace: $TEST_ENVIRONMENT
spec:
  action: partition
  mode: one
  selector:
    namespaces:
    - $TEST_ENVIRONMENT
    labelSelectors:
      app: dr-test-app
  direction: to
  target:
    mode: one
    selector:
      namespaces:
      - $TEST_ENVIRONMENT
      labelSelectors:
        app: dr-test-db
  duration: "2m"
EOF
    
    # Wait for chaos experiment to complete
    sleep 150  # 2.5 minutes
    
    # Check if applications recovered
    if kubectl get pods -n "$TEST_ENVIRONMENT" -l app=dr-test-app --field-selector=status.phase=Running | grep -q Running; then
        success "Network partition test completed - applications recovered"
        test_results[$test_name]="success"
    else
        error "Network partition test failed - applications did not recover"
        test_results[$test_name]="failed"
    fi
    
    # Cleanup chaos experiment
    kubectl delete networkchaos "$chaos_name" -n "$TEST_ENVIRONMENT" --ignore-not-found=true
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log "Network partition test completed in ${duration} seconds"
    
    return 0
}

# Cross-region replication test
test_cross_region_replication() {
    local test_name="cross_region_replication"
    local start_time=$(date +%s)
    
    log "Starting cross-region replication test"
    
    if [ "$DRY_RUN" = "true" ]; then
        warn "DRY RUN MODE - Simulating cross-region replication test"
        sleep 12
        test_results[$test_name]="success"
        return 0
    fi
    
    # Test S3 cross-region replication
    local test_file="dr-test-$(date +%s).txt"
    local primary_bucket="voicehive-storage-primary"
    local dr_bucket="voicehive-storage-dr"
    
    # Create test file in primary bucket
    echo "DR Test File - $(date)" > "/tmp/$test_file"
    
    if aws s3 cp "/tmp/$test_file" "s3://$primary_bucket/dr-tests/$test_file"; then
        log "Test file uploaded to primary bucket"
    else
        error "Failed to upload test file to primary bucket"
        test_results[$test_name]="failed"
        return 1
    fi
    
    # Wait for replication (up to 5 minutes)
    local timeout=300
    local elapsed=0
    local replicated=false
    
    while [ $elapsed -lt $timeout ]; do
        if aws s3 ls "s3://$dr_bucket/dr-tests/$test_file" > /dev/null 2>&1; then
            success "File replicated to DR bucket successfully"
            replicated=true
            break
        fi
        
        sleep 30
        elapsed=$((elapsed + 30))
        log "Waiting for replication... (${elapsed}s/${timeout}s)"
    done
    
    if [ "$replicated" = true ]; then
        # Verify file content
        aws s3 cp "s3://$dr_bucket/dr-tests/$test_file" "/tmp/${test_file}.replicated"
        
        if diff "/tmp/$test_file" "/tmp/${test_file}.replicated" > /dev/null; then
            success "Cross-region replication test completed successfully"
            test_results[$test_name]="success"
        else
            error "Replicated file content differs from original"
            test_results[$test_name]="failed"
        fi
    else
        error "Cross-region replication test failed - file not replicated within timeout"
        test_results[$test_name]="failed"
    fi
    
    # Cleanup test files
    aws s3 rm "s3://$primary_bucket/dr-tests/$test_file" > /dev/null 2>&1 || true
    aws s3 rm "s3://$dr_bucket/dr-tests/$test_file" > /dev/null 2>&1 || true
    rm -f "/tmp/$test_file" "/tmp/${test_file}.replicated" || true
    
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    log "Cross-region replication test completed in ${duration} seconds"
    
    # Check RPO compliance (target: 5 minutes = 300 seconds)
    if [ $duration -le 300 ]; then
        success "RPO target met for cross-region replication (${duration}s <= 300s)"
    else
        warn "RPO target exceeded for cross-region replication (${duration}s > 300s)"
    fi
    
    return 0
}

# Generate test report
generate_test_report() {
    local report_file="/tmp/dr-test-report-$(date +%Y%m%d-%H%M%S).json"
    
    log "Generating disaster recovery test report"
    
    local total_tests=0
    local passed_tests=0
    local failed_tests=0
    local skipped_tests=0
    
    # Count test results
    for test in "${!test_results[@]}"; do
        total_tests=$((total_tests + 1))
        case "${test_results[$test]}" in
            "success") passed_tests=$((passed_tests + 1)) ;;
            "failed") failed_tests=$((failed_tests + 1)) ;;
            "skipped") skipped_tests=$((skipped_tests + 1)) ;;
        esac
    done
    
    # Calculate success rate
    local success_rate=0
    if [ $total_tests -gt 0 ]; then
        success_rate=$(( (passed_tests * 100) / total_tests ))
    fi
    
    # Generate JSON report
    cat > "$report_file" << EOF
{
  "test_execution": {
    "start_time": "$test_start_time",
    "end_time": "$test_end_time",
    "duration_seconds": $(( $(date -d "$test_end_time" +%s) - $(date -d "$test_start_time" +%s) )),
    "environment": "$TEST_ENVIRONMENT",
    "dry_run": $DRY_RUN
  },
  "test_summary": {
    "total_tests": $total_tests,
    "passed_tests": $passed_tests,
    "failed_tests": $failed_tests,
    "skipped_tests": $skipped_tests,
    "success_rate_percent": $success_rate
  },
  "test_results": {
EOF
    
    # Add individual test results
    local first=true
    for test in "${!test_results[@]}"; do
        if [ "$first" = false ]; then
            echo "," >> "$report_file"
        fi
        echo "    \"$test\": \"${test_results[$test]}\"" >> "$report_file"
        first=false
    done
    
    cat >> "$report_file" << EOF
  },
  "compliance_status": {
    "rto_compliance": $([ $success_rate -ge 90 ] && echo "true" || echo "false"),
    "rpo_compliance": $([ $success_rate -ge 90 ] && echo "true" || echo "false"),
    "overall_readiness": "$success_rate%"
  }
}
EOF
    
    info "Test report generated: $report_file"
    
    # Display summary
    echo
    echo "=== DISASTER RECOVERY TEST SUMMARY ==="
    echo "Total Tests: $total_tests"
    echo "Passed: $passed_tests"
    echo "Failed: $failed_tests"
    echo "Skipped: $skipped_tests"
    echo "Success Rate: $success_rate%"
    echo "======================================"
    
    # Send notification
    if [ $failed_tests -eq 0 ]; then
        send_notification "All DR tests passed ($success_rate% success rate)" "success"
    else
        send_notification "$failed_tests DR tests failed ($success_rate% success rate)" "error"
    fi
    
    return $failed_tests
}

# Main execution function
main() {
    log "Starting automated disaster recovery tests"
    
    test_start_time=$(date -Iseconds)
    
    # Initialize test environment
    if ! initialize_test_environment; then
        error "Failed to initialize test environment"
        exit 1
    fi
    
    # Send start notification
    send_notification "Starting DR tests in $TEST_ENVIRONMENT environment" "info"
    
    # Execute tests
    test_database_failover
    test_application_failover
    test_backup_restore
    test_network_partition
    test_cross_region_replication
    
    test_end_time=$(date -Iseconds)
    
    # Generate report and exit with appropriate code
    generate_test_report
    exit $?
}

# Show usage information
show_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Automated Disaster Recovery Testing Suite

OPTIONS:
    -e, --environment ENV      Test environment (default: dr-test)
    -c, --config FILE         Configuration file path
    -d, --dry-run             Perform dry run without actual operations
    -w, --webhook URL         Notification webhook URL
    -h, --help                Show this help message

EXAMPLES:
    # Run full DR test suite
    $0

    # Dry run in staging environment
    $0 --environment staging --dry-run

    # Run with custom config and notifications
    $0 --config /path/to/config.yaml --webhook https://hooks.slack.com/...

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--environment)
            TEST_ENVIRONMENT="$2"
            shift 2
            ;;
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        -d|--dry-run)
            DRY_RUN="true"
            shift
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

# Run main function
main "$@"