#!/bin/bash

# Production Readiness Validation Execution Script
# 
# This script orchestrates the complete production readiness validation process
# including all testing phases and final certification report generation.

set -e  # Exit on any error

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICES_DIR="$PROJECT_ROOT/services/orchestrator"
REPORTS_DIR="$PROJECT_ROOT/validation-reports"
BASE_URL="${BASE_URL:-http://localhost:8000}"
SKIP_PHASES="${SKIP_PHASES:-}"
VERBOSE="${VERBOSE:-false}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
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

log_header() {
    echo -e "${PURPLE}$1${NC}"
}

# Function to print usage
print_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Production Readiness Validation Script

OPTIONS:
    -u, --base-url URL          Base URL for testing (default: http://localhost:8000)
    -s, --skip-phases PHASES    Comma-separated list of phases to skip
    -o, --output-dir DIR        Output directory for reports (default: ./validation-reports)
    -v, --verbose               Enable verbose output
    -h, --help                  Show this help message

PHASES:
    infrastructure_check        - Infrastructure and dependency validation
    production_readiness        - Production readiness component validation
    security_testing           - Security penetration testing
    load_testing              - Load testing and performance validation
    disaster_recovery         - Disaster recovery testing
    compliance_verification   - Compliance and regulatory validation
    certification_generation  - Final certification report generation

EXAMPLES:
    # Run complete validation
    $0

    # Run with custom URL
    $0 --base-url https://staging.example.com

    # Skip load testing and disaster recovery
    $0 --skip-phases load_testing,disaster_recovery

    # Run with verbose output
    $0 --verbose

ENVIRONMENT VARIABLES:
    BASE_URL                   - Base URL for testing
    SKIP_PHASES               - Phases to skip (comma-separated)
    VERBOSE                   - Enable verbose output (true/false)

EOF
}

# Function to check prerequisites
check_prerequisites() {
    log_header "🔍 Checking Prerequisites"
    
    # Check if we're in the right directory
    if [[ ! -f "$PROJECT_ROOT/services/orchestrator/production_validation_orchestrator.py" ]]; then
        log_error "Production validation orchestrator not found. Please run from project root."
        exit 1
    fi
    
    # Check Python version
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required but not installed."
        exit 1
    fi
    
    local python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1-2)
    log_info "Python version: $python_version"
    
    # Check required Python packages
    log_info "Checking Python dependencies..."
    local required_packages=("aiohttp" "asyncpg" "redis" "psutil" "pydantic")
    local missing_packages=()
    
    for package in "${required_packages[@]}"; do
        if ! python3 -c "import $package" 2>/dev/null; then
            missing_packages+=("$package")
        fi
    done
    
    if [[ ${#missing_packages[@]} -gt 0 ]]; then
        log_warning "Missing Python packages: ${missing_packages[*]}"
        log_info "Installing missing packages..."
        pip3 install "${missing_packages[@]}" || {
            log_error "Failed to install required packages"
            exit 1
        }
    fi
    
    # Check if target system is accessible (if not localhost)
    if [[ "$BASE_URL" != "http://localhost:8000" ]]; then
        log_info "Checking target system accessibility: $BASE_URL"
        if curl -s --connect-timeout 10 "$BASE_URL/health" > /dev/null; then
            log_success "Target system is accessible"
        else
            log_warning "Target system may not be accessible: $BASE_URL"
        fi
    fi
    
    log_success "Prerequisites check completed"
}

# Function to setup environment
setup_environment() {
    log_header "🛠️ Setting Up Environment"
    
    # Create reports directory
    mkdir -p "$REPORTS_DIR"
    log_info "Created reports directory: $REPORTS_DIR"
    
    # Set Python path
    export PYTHONPATH="$SERVICES_DIR:$PYTHONPATH"
    log_info "Set Python path: $PYTHONPATH"
    
    # Change to services directory
    cd "$SERVICES_DIR"
    log_info "Changed to services directory: $SERVICES_DIR"
    
    log_success "Environment setup completed"
}

# Function to run validation orchestrator
run_validation() {
    log_header "🚀 Starting Production Validation"
    
    local cmd_args=()
    cmd_args+=("--base-url" "$BASE_URL")
    cmd_args+=("--output-dir" "$REPORTS_DIR")
    
    if [[ -n "$SKIP_PHASES" ]]; then
        IFS=',' read -ra PHASES_ARRAY <<< "$SKIP_PHASES"
        cmd_args+=("--skip-phases" "${PHASES_ARRAY[@]}")
    fi
    
    log_info "Running validation with arguments: ${cmd_args[*]}"
    
    # Run the validation orchestrator
    if [[ "$VERBOSE" == "true" ]]; then
        python3 production_validation_orchestrator.py "${cmd_args[@]}"
    else
        python3 production_validation_orchestrator.py "${cmd_args[@]}" 2>&1 | grep -E "(INFO|SUCCESS|WARNING|ERROR|🚀|✅|❌|⚠️|🎉|💥)"
    fi
    
    local exit_code=$?
    
    if [[ $exit_code -eq 0 ]]; then
        log_success "Validation completed successfully"
    else
        log_error "Validation completed with issues (exit code: $exit_code)"
    fi
    
    return $exit_code
}

# Function to generate summary report
generate_summary() {
    log_header "📊 Generating Summary Report"
    
    local summary_file="$REPORTS_DIR/validation_summary.txt"
    
    cat > "$summary_file" << EOF
Production Readiness Validation Summary
=======================================

Execution Time: $(date)
Base URL: $BASE_URL
Reports Directory: $REPORTS_DIR

Generated Reports:
EOF
    
    # List generated reports
    local reports=(
        "production_readiness_report.json"
        "security_penetration_report.json"
        "load_testing_report.json"
        "production_certification_report.json"
        "production_certification_report.html"
        "production_validation_orchestration_report.json"
    )
    
    for report in "${reports[@]}"; do
        if [[ -f "$report" ]]; then
            echo "  ✅ $report" >> "$summary_file"
            log_success "Generated: $report"
        else
            echo "  ❌ $report (not generated)" >> "$summary_file"
            log_warning "Missing: $report"
        fi
    done
    
    # Add quick stats if orchestration report exists
    if [[ -f "production_validation_orchestration_report.json" ]]; then
        echo "" >> "$summary_file"
        echo "Quick Stats:" >> "$summary_file"
        
        # Extract key metrics using jq if available
        if command -v jq &> /dev/null; then
            local overall_status=$(jq -r '.overall_status' production_validation_orchestration_report.json 2>/dev/null || echo "UNKNOWN")
            local total_phases=$(jq -r '.total_phases' production_validation_orchestration_report.json 2>/dev/null || echo "UNKNOWN")
            local successful_phases=$(jq -r '.successful_phases' production_validation_orchestration_report.json 2>/dev/null || echo "UNKNOWN")
            local failed_phases=$(jq -r '.failed_phases' production_validation_orchestration_report.json 2>/dev/null || echo "UNKNOWN")
            
            echo "  Overall Status: $overall_status" >> "$summary_file"
            echo "  Total Phases: $total_phases" >> "$summary_file"
            echo "  Successful Phases: $successful_phases" >> "$summary_file"
            echo "  Failed Phases: $failed_phases" >> "$summary_file"
        fi
    fi
    
    echo "" >> "$summary_file"
    echo "For detailed results, see the individual report files." >> "$summary_file"
    
    log_info "Summary report generated: $summary_file"
}

# Function to open reports (if in interactive mode)
open_reports() {
    if [[ -t 1 ]] && command -v open &> /dev/null; then  # macOS
        log_info "Opening HTML report..."
        open "production_certification_report.html" 2>/dev/null || true
    elif [[ -t 1 ]] && command -v xdg-open &> /dev/null; then  # Linux
        log_info "Opening HTML report..."
        xdg-open "production_certification_report.html" 2>/dev/null || true
    fi
}

# Function to cleanup on exit
cleanup() {
    local exit_code=$?
    
    if [[ $exit_code -ne 0 ]]; then
        log_error "Validation failed with exit code: $exit_code"
        
        # Copy any generated reports to reports directory
        for report in *.json *.html; do
            if [[ -f "$report" ]]; then
                cp "$report" "$REPORTS_DIR/" 2>/dev/null || true
            fi
        done
    fi
    
    # Change back to original directory
    cd "$SCRIPT_DIR"
    
    exit $exit_code
}

# Main execution function
main() {
    # Set up trap for cleanup
    trap cleanup EXIT
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -u|--base-url)
                BASE_URL="$2"
                shift 2
                ;;
            -s|--skip-phases)
                SKIP_PHASES="$2"
                shift 2
                ;;
            -o|--output-dir)
                REPORTS_DIR="$2"
                shift 2
                ;;
            -v|--verbose)
                VERBOSE="true"
                shift
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                print_usage
                exit 1
                ;;
        esac
    done
    
    # Print header
    log_header "🎯 Production Readiness Validation"
    log_header "=================================="
    log_info "Base URL: $BASE_URL"
    log_info "Reports Directory: $REPORTS_DIR"
    if [[ -n "$SKIP_PHASES" ]]; then
        log_info "Skipped Phases: $SKIP_PHASES"
    fi
    log_info "Verbose Mode: $VERBOSE"
    echo ""
    
    # Execute validation steps
    check_prerequisites
    echo ""
    
    setup_environment
    echo ""
    
    # Run validation and capture exit code
    local validation_exit_code=0
    run_validation || validation_exit_code=$?
    echo ""
    
    # Copy reports to reports directory
    log_info "Copying reports to $REPORTS_DIR..."
    for report in *.json *.html; do
        if [[ -f "$report" ]]; then
            cp "$report" "$REPORTS_DIR/"
        fi
    done
    
    # Generate summary
    generate_summary
    echo ""
    
    # Open reports if available
    open_reports
    
    # Final status
    if [[ $validation_exit_code -eq 0 ]]; then
        log_header "🎉 VALIDATION COMPLETED SUCCESSFULLY"
        log_success "All reports have been generated in: $REPORTS_DIR"
        log_success "Review the certification report for final production readiness status."
    else
        log_header "⚠️ VALIDATION COMPLETED WITH ISSUES"
        log_warning "Some validation phases failed or had warnings."
        log_warning "Review the reports in: $REPORTS_DIR"
        log_warning "Address the issues before production deployment."
    fi
    
    return $validation_exit_code
}

# Execute main function
main "$@"