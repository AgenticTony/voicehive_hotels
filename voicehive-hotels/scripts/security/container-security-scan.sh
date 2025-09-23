#!/bin/bash

# VoiceHive Hotels - Container Security Scanning Script
# Comprehensive security scanning for container images

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE_PREFIX="${IMAGE_PREFIX:-voicehive-hotels}"
SCAN_OUTPUT_DIR="${PROJECT_ROOT}/security-reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Help function
show_help() {
    cat << EOF
VoiceHive Hotels Container Security Scanner

Usage: $0 [OPTIONS] [SERVICES...]

OPTIONS:
    -h, --help              Show this help message
    -a, --all               Scan all services
    -s, --service SERVICE   Scan specific service
    -t, --type TYPE         Scan type: vuln, config, secret, all (default: all)
    -f, --format FORMAT     Output format: table, json, sarif (default: table)
    -o, --output DIR        Output directory (default: ./security-reports)
    --severity LEVEL        Minimum severity: LOW, MEDIUM, HIGH, CRITICAL (default: HIGH)
    --fail-on LEVEL         Fail on severity level (default: CRITICAL)
    --sbom                  Generate SBOM
    --sign                  Sign images with Cosign
    --verify                Verify image signatures
    --policy FILE           Use custom policy file
    --registry URL          Container registry URL
    --push                  Push scan results to registry

SERVICES:
    orchestrator            Orchestrator service
    connectors              PMS connectors service
    riva-proxy              Riva ASR proxy service
    tts-router              TTS router service
    media-agent             LiveKit media agent

EXAMPLES:
    $0 --all                                    # Scan all services
    $0 -s orchestrator -t vuln                 # Scan orchestrator for vulnerabilities
    $0 --service connectors --sbom --sign      # Scan connectors, generate SBOM and sign
    $0 -a --severity MEDIUM --format json      # Scan all with medium+ severity in JSON

EOF
}

# Parse command line arguments
SERVICES=()
SCAN_TYPE="all"
OUTPUT_FORMAT="table"
SEVERITY="HIGH"
FAIL_ON="CRITICAL"
GENERATE_SBOM=false
SIGN_IMAGES=false
VERIFY_SIGNATURES=false
POLICY_FILE=""
PUSH_RESULTS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -a|--all)
            SERVICES=("orchestrator" "connectors" "riva-proxy" "tts-router" "media-agent")
            shift
            ;;
        -s|--service)
            SERVICES+=("$2")
            shift 2
            ;;
        -t|--type)
            SCAN_TYPE="$2"
            shift 2
            ;;
        -f|--format)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        -o|--output)
            SCAN_OUTPUT_DIR="$2"
            shift 2
            ;;
        --severity)
            SEVERITY="$2"
            shift 2
            ;;
        --fail-on)
            FAIL_ON="$2"
            shift 2
            ;;
        --sbom)
            GENERATE_SBOM=true
            shift
            ;;
        --sign)
            SIGN_IMAGES=true
            shift
            ;;
        --verify)
            VERIFY_SIGNATURES=true
            shift
            ;;
        --policy)
            POLICY_FILE="$2"
            shift 2
            ;;
        --registry)
            REGISTRY="$2"
            shift 2
            ;;
        --push)
            PUSH_RESULTS=true
            shift
            ;;
        *)
            SERVICES+=("$1")
            shift
            ;;
    esac
done

# Validate dependencies
check_dependencies() {
    local deps=("docker" "trivy" "grype" "syft")
    
    if [[ "$SIGN_IMAGES" == "true" || "$VERIFY_SIGNATURES" == "true" ]]; then
        deps+=("cosign")
    fi
    
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            log_error "Required dependency '$dep' not found"
            exit 1
        fi
    done
    
    log_success "All dependencies found"
}

# Create output directory
setup_output_dir() {
    mkdir -p "$SCAN_OUTPUT_DIR"
    log_info "Output directory: $SCAN_OUTPUT_DIR"
}

# Get image tag for service
get_image_tag() {
    local service=$1
    local tag="latest"
    
    # Try to get the latest tag from registry
    if docker image ls --format "table {{.Repository}}:{{.Tag}}" | grep -q "$REGISTRY/$IMAGE_PREFIX/$service"; then
        tag=$(docker image ls --format "table {{.Repository}}:{{.Tag}}" | grep "$REGISTRY/$IMAGE_PREFIX/$service" | head -1 | cut -d: -f2)
    fi
    
    echo "$tag"
}

# Pull image if not present
ensure_image() {
    local service=$1
    local tag=$2
    local image="$REGISTRY/$IMAGE_PREFIX/$service:$tag"
    
    if ! docker image inspect "$image" &> /dev/null; then
        log_info "Pulling image: $image"
        docker pull "$image" || {
            log_error "Failed to pull image: $image"
            return 1
        }
    fi
    
    echo "$image"
}

# Run Trivy scan
run_trivy_scan() {
    local image=$1
    local service=$2
    local scan_types=()
    
    case "$SCAN_TYPE" in
        "vuln")
            scan_types=("vuln")
            ;;
        "config")
            scan_types=("config")
            ;;
        "secret")
            scan_types=("secret")
            ;;
        "all")
            scan_types=("vuln" "config" "secret")
            ;;
    esac
    
    local exit_code=0
    
    for scan_type in "${scan_types[@]}"; do
        local output_file="$SCAN_OUTPUT_DIR/trivy-${service}-${scan_type}-${TIMESTAMP}"
        
        log_info "Running Trivy $scan_type scan for $service..."
        
        local trivy_args=(
            "image"
            "--security-checks" "$scan_type"
            "--severity" "$SEVERITY,CRITICAL"
            "--ignore-unfixed"
        )
        
        # Add policy file if specified
        if [[ -n "$POLICY_FILE" && -f "$POLICY_FILE" ]]; then
            trivy_args+=("--config" "$POLICY_FILE")
        fi
        
        # Set output format
        case "$OUTPUT_FORMAT" in
            "json")
                trivy_args+=("--format" "json" "--output" "${output_file}.json")
                ;;
            "sarif")
                trivy_args+=("--format" "sarif" "--output" "${output_file}.sarif")
                ;;
            "table")
                trivy_args+=("--format" "table" "--output" "${output_file}.txt")
                ;;
        esac
        
        trivy_args+=("$image")
        
        if ! trivy "${trivy_args[@]}"; then
            log_warning "Trivy $scan_type scan found issues for $service"
            exit_code=1
        fi
        
        log_success "Trivy $scan_type scan completed for $service"
    done
    
    return $exit_code
}

# Run Grype scan
run_grype_scan() {
    local image=$1
    local service=$2
    local output_file="$SCAN_OUTPUT_DIR/grype-${service}-${TIMESTAMP}"
    
    log_info "Running Grype vulnerability scan for $service..."
    
    local grype_args=(
        "$image"
        "--fail-on" "$FAIL_ON"
    )
    
    case "$OUTPUT_FORMAT" in
        "json")
            grype_args+=("--output" "json" "--file" "${output_file}.json")
            ;;
        "sarif")
            grype_args+=("--output" "sarif" "--file" "${output_file}.sarif")
            ;;
        "table")
            grype_args+=("--output" "table" "--file" "${output_file}.txt")
            ;;
    esac
    
    local exit_code=0
    if ! grype "${grype_args[@]}"; then
        log_warning "Grype scan found critical vulnerabilities for $service"
        exit_code=1
    fi
    
    log_success "Grype scan completed for $service"
    return $exit_code
}

# Generate SBOM
generate_sbom() {
    local image=$1
    local service=$2
    local output_file="$SCAN_OUTPUT_DIR/sbom-${service}-${TIMESTAMP}"
    
    log_info "Generating SBOM for $service..."
    
    # Generate SPDX format
    syft "$image" -o spdx-json="${output_file}.spdx.json"
    
    # Generate CycloneDX format
    syft "$image" -o cyclonedx-json="${output_file}.cyclonedx.json"
    
    # Generate human-readable format
    syft "$image" -o table="${output_file}.txt"
    
    log_success "SBOM generated for $service"
}

# Sign image with Cosign
sign_image() {
    local image=$1
    local service=$2
    
    log_info "Signing image for $service..."
    
    # Use keyless signing with OIDC
    COSIGN_EXPERIMENTAL=1 cosign sign --yes "$image"
    
    log_success "Image signed for $service"
}

# Verify image signature
verify_signature() {
    local image=$1
    local service=$2
    
    log_info "Verifying signature for $service..."
    
    # Verify with keyless verification
    COSIGN_EXPERIMENTAL=1 cosign verify "$image" \
        --certificate-identity-regexp=".*" \
        --certificate-oidc-issuer-regexp=".*"
    
    log_success "Signature verified for $service"
}

# Generate security report
generate_report() {
    local service=$1
    local image=$2
    local scan_results=()
    
    local report_file="$SCAN_OUTPUT_DIR/security-report-${service}-${TIMESTAMP}.md"
    
    cat > "$report_file" << EOF
# Security Report - $service

**Generated**: $(date)
**Image**: $image
**Scanner Version**: $(trivy --version | head -1)

## Summary

EOF
    
    # Add vulnerability summary
    if [[ -f "$SCAN_OUTPUT_DIR/trivy-${service}-vuln-${TIMESTAMP}.json" ]]; then
        local vuln_file="$SCAN_OUTPUT_DIR/trivy-${service}-vuln-${TIMESTAMP}.json"
        local critical_count=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' "$vuln_file" 2>/dev/null || echo "0")
        local high_count=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "HIGH")] | length' "$vuln_file" 2>/dev/null || echo "0")
        local medium_count=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "MEDIUM")] | length' "$vuln_file" 2>/dev/null || echo "0")
        
        cat >> "$report_file" << EOF
### Vulnerability Summary
- **Critical**: $critical_count
- **High**: $high_count  
- **Medium**: $medium_count

EOF
    fi
    
    # Add configuration issues
    if [[ -f "$SCAN_OUTPUT_DIR/trivy-${service}-config-${TIMESTAMP}.json" ]]; then
        local config_file="$SCAN_OUTPUT_DIR/trivy-${service}-config-${TIMESTAMP}.json"
        local config_issues=$(jq '[.Results[]?.Misconfigurations[]?] | length' "$config_file" 2>/dev/null || echo "0")
        
        cat >> "$report_file" << EOF
### Configuration Issues
- **Total Issues**: $config_issues

EOF
    fi
    
    # Add SBOM information
    if [[ "$GENERATE_SBOM" == "true" ]]; then
        cat >> "$report_file" << EOF
### Software Bill of Materials
- **SPDX Format**: sbom-${service}-${TIMESTAMP}.spdx.json
- **CycloneDX Format**: sbom-${service}-${TIMESTAMP}.cyclonedx.json

EOF
    fi
    
    # Add signature information
    if [[ "$SIGN_IMAGES" == "true" || "$VERIFY_SIGNATURES" == "true" ]]; then
        cat >> "$report_file" << EOF
### Image Signature
- **Signed**: $(if [[ "$SIGN_IMAGES" == "true" ]]; then echo "✅ Yes"; else echo "❓ Unknown"; fi)
- **Verified**: $(if [[ "$VERIFY_SIGNATURES" == "true" ]]; then echo "✅ Yes"; else echo "❓ Not checked"; fi)

EOF
    fi
    
    cat >> "$report_file" << EOF
## Recommendations

1. **Critical Vulnerabilities**: Address immediately
2. **High Vulnerabilities**: Address within 7 days
3. **Configuration Issues**: Review and fix misconfigurations
4. **SBOM**: Keep SBOM updated with each build
5. **Signatures**: Ensure all images are signed and verified

## Files Generated

EOF
    
    # List all generated files
    find "$SCAN_OUTPUT_DIR" -name "*${service}*${TIMESTAMP}*" -type f | while read -r file; do
        echo "- $(basename "$file")" >> "$report_file"
    done
    
    log_success "Security report generated: $report_file"
}

# Scan single service
scan_service() {
    local service=$1
    local tag
    local image
    local scan_exit_code=0
    
    log_info "Starting security scan for service: $service"
    
    # Get image tag and ensure image is available
    tag=$(get_image_tag "$service")
    image=$(ensure_image "$service" "$tag") || return 1
    
    log_info "Scanning image: $image"
    
    # Run vulnerability scans
    if [[ "$SCAN_TYPE" == "all" || "$SCAN_TYPE" == "vuln" ]]; then
        run_trivy_scan "$image" "$service" || scan_exit_code=1
        run_grype_scan "$image" "$service" || scan_exit_code=1
    fi
    
    # Run configuration scan
    if [[ "$SCAN_TYPE" == "all" || "$SCAN_TYPE" == "config" ]]; then
        run_trivy_scan "$image" "$service" || scan_exit_code=1
    fi
    
    # Run secret scan
    if [[ "$SCAN_TYPE" == "all" || "$SCAN_TYPE" == "secret" ]]; then
        run_trivy_scan "$image" "$service" || scan_exit_code=1
    fi
    
    # Generate SBOM if requested
    if [[ "$GENERATE_SBOM" == "true" ]]; then
        generate_sbom "$image" "$service"
    fi
    
    # Sign image if requested
    if [[ "$SIGN_IMAGES" == "true" ]]; then
        sign_image "$image" "$service"
    fi
    
    # Verify signature if requested
    if [[ "$VERIFY_SIGNATURES" == "true" ]]; then
        verify_signature "$image" "$service" || {
            log_warning "Signature verification failed for $service"
            scan_exit_code=1
        }
    fi
    
    # Generate security report
    generate_report "$service" "$image"
    
    if [[ $scan_exit_code -eq 0 ]]; then
        log_success "Security scan completed successfully for $service"
    else
        log_warning "Security scan completed with issues for $service"
    fi
    
    return $scan_exit_code
}

# Main function
main() {
    log_info "VoiceHive Hotels Container Security Scanner"
    log_info "Timestamp: $TIMESTAMP"
    
    # Validate dependencies
    check_dependencies
    
    # Setup output directory
    setup_output_dir
    
    # Check if services are specified
    if [[ ${#SERVICES[@]} -eq 0 ]]; then
        log_error "No services specified. Use --all or specify services."
        show_help
        exit 1
    fi
    
    local overall_exit_code=0
    local scanned_services=0
    local failed_services=0
    
    # Scan each service
    for service in "${SERVICES[@]}"; do
        echo
        log_info "=" "Scanning service: $service" "="
        
        if scan_service "$service"; then
            ((scanned_services++))
        else
            ((failed_services++))
            overall_exit_code=1
        fi
    done
    
    # Summary
    echo
    log_info "=" "Scan Summary" "="
    log_info "Total services scanned: $scanned_services"
    log_info "Services with issues: $failed_services"
    log_info "Output directory: $SCAN_OUTPUT_DIR"
    
    if [[ $overall_exit_code -eq 0 ]]; then
        log_success "All security scans completed successfully!"
    else
        log_warning "Some security scans found issues. Check the reports for details."
    fi
    
    exit $overall_exit_code
}

# Run main function
main "$@"