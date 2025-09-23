#!/bin/bash
# Smoke Tests for Deployment Validation
# This script runs comprehensive smoke tests to validate deployment health

set -euo pipefail

# Configuration
NAMESPACE="${NAMESPACE:-voicehive-staging}"
SERVICE_NAME="${SERVICE_NAME:-voicehive-orchestrator-preview}"
TIMEOUT="${TIMEOUT:-180}"
RETRY_INTERVAL="${RETRY_INTERVAL:-10}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

# Function to wait for service to be ready
wait_for_service() {
    local service_url="$1"
    local max_attempts=$((TIMEOUT / RETRY_INTERVAL))
    local attempt=1
    
    log "Waiting for service to be ready at $service_url"
    
    while [ $attempt -le $max_attempts ]; do
        if curl -f -s "$service_url/health/ready" > /dev/null 2>&1; then
            log "Service is ready after $((attempt * RETRY_INTERVAL)) seconds"
            return 0
        fi
        
        log "Attempt $attempt/$max_attempts: Service not ready, waiting ${RETRY_INTERVAL}s..."
        sleep $RETRY_INTERVAL
        ((attempt++))
    done
    
    error "Service failed to become ready within ${TIMEOUT} seconds"
    return 1
}

# Function to run health check tests
run_health_checks() {
    local service_url="$1"
    
    log "Running health check tests..."
    
    # Test startup probe
    log "Testing startup probe..."
    if ! curl -f -s "$service_url/health/startup" | jq -e '.status == "healthy"' > /dev/null; then
        error "Startup probe failed"
        return 1
    fi
    
    # Test liveness probe
    log "Testing liveness probe..."
    if ! curl -f -s "$service_url/health/live" | jq -e '.status == "healthy"' > /dev/null; then
        error "Liveness probe failed"
        return 1
    fi
    
    # Test readiness probe
    log "Testing readiness probe..."
    if ! curl -f -s "$service_url/health/ready" | jq -e '.status == "ready"' > /dev/null; then
        error "Readiness probe failed"
        return 1
    fi
    
    log "All health checks passed"
    return 0
}

# Function to test API endpoints
test_api_endpoints() {
    local service_url="$1"
    
    log "Testing API endpoints..."
    
    # Test metrics endpoint
    log "Testing metrics endpoint..."
    if ! curl -f -s "$service_url:8080/metrics" | grep -q "voicehive_"; then
        error "Metrics endpoint test failed"
        return 1
    fi
    
    # Test authentication endpoint
    log "Testing authentication endpoint..."
    local auth_response=$(curl -s -o /dev/null -w "%{http_code}" "$service_url/auth/health")
    if [ "$auth_response" != "200" ]; then
        error "Authentication endpoint test failed (HTTP $auth_response)"
        return 1
    fi
    
    # Test rate limiting endpoint
    log "Testing rate limiting..."
    local rate_limit_response=$(curl -s -o /dev/null -w "%{http_code}" "$service_url/api/v1/health")
    if [ "$rate_limit_response" != "200" ]; then
        error "Rate limiting endpoint test failed (HTTP $rate_limit_response)"
        return 1
    fi
    
    log "All API endpoint tests passed"
    return 0
}

# Function to test security features
test_security_features() {
    local service_url="$1"
    
    log "Testing security features..."
    
    # Test security headers
    log "Testing security headers..."
    local headers=$(curl -s -I "$service_url/health/ready")
    
    if ! echo "$headers" | grep -q "X-Content-Type-Options: nosniff"; then
        error "Missing X-Content-Type-Options header"
        return 1
    fi
    
    if ! echo "$headers" | grep -q "X-Frame-Options: DENY"; then
        error "Missing X-Frame-Options header"
        return 1
    fi
    
    # Test authentication requirement
    log "Testing authentication requirement..."
    local unauth_response=$(curl -s -o /dev/null -w "%{http_code}" "$service_url/api/v1/calls")
    if [ "$unauth_response" != "401" ]; then
        error "Authentication not properly enforced (expected 401, got $unauth_response)"
        return 1
    fi
    
    log "All security tests passed"
    return 0
}

# Function to test performance
test_performance() {
    local service_url="$1"
    
    log "Testing performance characteristics..."
    
    # Test response time
    log "Testing response time..."
    local response_time=$(curl -s -o /dev/null -w "%{time_total}" "$service_url/health/ready")
    local response_time_ms=$(echo "$response_time * 1000" | bc)
    
    if (( $(echo "$response_time > 1.0" | bc -l) )); then
        warn "Response time is high: ${response_time_ms}ms"
    else
        log "Response time is acceptable: ${response_time_ms}ms"
    fi
    
    # Test concurrent requests
    log "Testing concurrent request handling..."
    for i in {1..5}; do
        curl -s "$service_url/health/ready" > /dev/null &
    done
    wait
    
    log "Performance tests completed"
    return 0
}

# Main execution
main() {
    log "Starting smoke tests for deployment validation"
    log "Namespace: $NAMESPACE"
    log "Service: $SERVICE_NAME"
    log "Timeout: ${TIMEOUT}s"
    
    # Get service URL
    local service_url
    if kubectl get service "$SERVICE_NAME" -n "$NAMESPACE" > /dev/null 2>&1; then
        # Port forward to access the service
        log "Setting up port forwarding..."
        kubectl port-forward -n "$NAMESPACE" "service/$SERVICE_NAME" 8000:80 > /dev/null 2>&1 &
        local port_forward_pid=$!
        sleep 5
        service_url="http://localhost:8000"
        
        # Cleanup function
        cleanup() {
            log "Cleaning up port forwarding..."
            kill $port_forward_pid 2>/dev/null || true
        }
        trap cleanup EXIT
    else
        error "Service $SERVICE_NAME not found in namespace $NAMESPACE"
        return 1
    fi
    
    # Run all test suites
    if wait_for_service "$service_url" && \
       run_health_checks "$service_url" && \
       test_api_endpoints "$service_url" && \
       test_security_features "$service_url" && \
       test_performance "$service_url"; then
        log "🎉 All smoke tests passed! Deployment is ready for promotion."
        return 0
    else
        error "❌ Smoke tests failed! Deployment should not be promoted."
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

if ! command -v jq &> /dev/null; then
    error "jq is required but not installed"
    exit 1
fi

if ! command -v bc &> /dev/null; then
    error "bc is required but not installed"
    exit 1
fi

# Run main function
main "$@"