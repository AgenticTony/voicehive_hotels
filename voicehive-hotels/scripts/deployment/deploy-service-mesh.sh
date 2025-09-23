#!/bin/bash

# Deploy Service Mesh for VoiceHive Hotels
# Supports both Istio and Linkerd deployment options
# Production-grade configuration with security best practices

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MESH_TYPE="${MESH_TYPE:-istio}"  # Options: istio, linkerd
ENVIRONMENT="${ENVIRONMENT:-production}"
NAMESPACE="${NAMESPACE:-voicehive}"
DRY_RUN="${DRY_RUN:-false}"

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

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed or not in PATH"
        exit 1
    fi
    
    # Check cluster connectivity
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    # Check if running in correct environment
    CURRENT_CONTEXT=$(kubectl config current-context)
    if [[ "$ENVIRONMENT" == "production" && ! "$CURRENT_CONTEXT" =~ production ]]; then
        log_warning "Current context '$CURRENT_CONTEXT' doesn't seem to be production"
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    log_success "Prerequisites check passed"
}

# Install Istio service mesh
install_istio() {
    log_info "Installing Istio service mesh..."
    
    # Check if istioctl is available
    if ! command -v istioctl &> /dev/null; then
        log_info "Installing istioctl..."
        curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.19.3 sh -
        export PATH="$PWD/istio-1.19.3/bin:$PATH"
    fi
    
    # Create istio-system namespace
    kubectl create namespace istio-system --dry-run=client -o yaml | kubectl apply -f -
    
    # Install Istio with production configuration
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would install Istio with production configuration"
        istioctl install --set values.pilot.env.EXTERNAL_ISTIOD=false --dry-run
    else
        log_info "Installing Istio control plane..."
        istioctl install -f "$PROJECT_ROOT/infra/k8s/service-mesh/istio-config.yaml" -y
        
        # Wait for Istio to be ready
        kubectl wait --for=condition=Ready pods -l app=istiod -n istio-system --timeout=300s
        
        # Verify installation
        istioctl verify-install
    fi
    
    # Enable automatic sidecar injection for voicehive namespace
    kubectl label namespace "$NAMESPACE" istio-injection=enabled --overwrite
    
    log_success "Istio installation completed"
}

# Install Linkerd service mesh
install_linkerd() {
    log_info "Installing Linkerd service mesh..."
    
    # Check if linkerd CLI is available
    if ! command -v linkerd &> /dev/null; then
        log_info "Installing linkerd CLI..."
        curl -sL https://run.linkerd.io/install | sh
        export PATH=$PATH:$HOME/.linkerd2/bin
    fi
    
    # Pre-installation checks
    linkerd check --pre
    
    # Install Linkerd CRDs
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would install Linkerd CRDs"
        linkerd install --crds | head -20
    else
        linkerd install --crds | kubectl apply -f -
    fi
    
    # Install Linkerd control plane
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would install Linkerd control plane"
        linkerd install | head -20
    else
        linkerd install | kubectl apply -f -
        
        # Wait for Linkerd to be ready
        linkerd check
    fi
    
    # Install Linkerd viz extension for observability
    if [[ "$DRY_RUN" != "true" ]]; then
        linkerd viz install | kubectl apply -f -
        linkerd viz check
    fi
    
    # Inject Linkerd proxy into voicehive namespace
    kubectl get deploy -n "$NAMESPACE" -o yaml | linkerd inject - | kubectl apply -f -
    
    log_success "Linkerd installation completed"
}

# Apply network policies
apply_network_policies() {
    log_info "Applying network policies..."
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would apply network policies"
        kubectl apply --dry-run=client -f "$PROJECT_ROOT/infra/k8s/security/network-policies.yaml"
        kubectl apply --dry-run=client -f "$PROJECT_ROOT/infra/k8s/security/network-segmentation.yaml"
    else
        kubectl apply -f "$PROJECT_ROOT/infra/k8s/security/network-policies.yaml"
        kubectl apply -f "$PROJECT_ROOT/infra/k8s/security/network-segmentation.yaml"
        
        # Verify network policies are applied
        kubectl get networkpolicies -n "$NAMESPACE"
    fi
    
    log_success "Network policies applied"
}

# Apply service mesh configuration
apply_service_mesh_config() {
    log_info "Applying service mesh configuration..."
    
    case "$MESH_TYPE" in
        "istio")
            if [[ "$DRY_RUN" == "true" ]]; then
                log_info "DRY RUN: Would apply Istio configuration"
                kubectl apply --dry-run=client -f "$PROJECT_ROOT/infra/k8s/service-mesh/istio-config.yaml"
            else
                kubectl apply -f "$PROJECT_ROOT/infra/k8s/service-mesh/istio-config.yaml"
                
                # Verify Istio configuration
                istioctl analyze -n "$NAMESPACE"
            fi
            ;;
        "linkerd")
            if [[ "$DRY_RUN" == "true" ]]; then
                log_info "DRY RUN: Would apply Linkerd configuration"
                kubectl apply --dry-run=client -f "$PROJECT_ROOT/infra/k8s/service-mesh/linkerd-config.yaml"
            else
                kubectl apply -f "$PROJECT_ROOT/infra/k8s/service-mesh/linkerd-config.yaml"
                
                # Verify Linkerd configuration
                linkerd check
            fi
            ;;
        *)
            log_error "Unknown mesh type: $MESH_TYPE"
            exit 1
            ;;
    esac
    
    log_success "Service mesh configuration applied"
}

# Setup monitoring
setup_monitoring() {
    log_info "Setting up network monitoring..."
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would apply monitoring configuration"
        kubectl apply --dry-run=client -f "$PROJECT_ROOT/infra/k8s/monitoring/network-monitoring.yaml"
    else
        kubectl apply -f "$PROJECT_ROOT/infra/k8s/monitoring/network-monitoring.yaml"
        
        # Verify monitoring setup
        kubectl get servicemonitor -n monitoring
        kubectl get prometheusrule -n monitoring
    fi
    
    log_success "Network monitoring setup completed"
}

# Restart deployments to inject service mesh sidecars
restart_deployments() {
    log_info "Restarting deployments to inject service mesh sidecars..."
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would restart deployments in namespace $NAMESPACE"
        kubectl get deployments -n "$NAMESPACE"
    else
        # Get all deployments in the namespace
        DEPLOYMENTS=$(kubectl get deployments -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}')
        
        for deployment in $DEPLOYMENTS; do
            log_info "Restarting deployment: $deployment"
            kubectl rollout restart deployment/"$deployment" -n "$NAMESPACE"
        done
        
        # Wait for rollouts to complete
        for deployment in $DEPLOYMENTS; do
            log_info "Waiting for deployment $deployment to be ready..."
            kubectl rollout status deployment/"$deployment" -n "$NAMESPACE" --timeout=300s
        done
    fi
    
    log_success "Deployments restarted successfully"
}

# Verify service mesh deployment
verify_deployment() {
    log_info "Verifying service mesh deployment..."
    
    case "$MESH_TYPE" in
        "istio")
            # Check Istio proxy status
            istioctl proxy-status
            
            # Verify mTLS is working
            log_info "Checking mTLS configuration..."
            istioctl authn tls-check orchestrator."$NAMESPACE".svc.cluster.local
            
            # Check authorization policies
            kubectl get authorizationpolicy -n "$NAMESPACE"
            ;;
        "linkerd")
            # Check Linkerd status
            linkerd check
            
            # Check proxy status
            linkerd stat deployments -n "$NAMESPACE"
            
            # Check authorization policies
            kubectl get serverauthorization -n "$NAMESPACE"
            ;;
    esac
    
    # Verify network policies
    log_info "Checking network policies..."
    kubectl get networkpolicies -n "$NAMESPACE"
    
    # Test service connectivity
    log_info "Testing service connectivity..."
    if kubectl get pod -n "$NAMESPACE" -l app=orchestrator -o name | head -1 | xargs -I {} kubectl exec -n "$NAMESPACE" {} -- curl -s -o /dev/null -w "%{http_code}" http://tts-router/healthz 2>/dev/null | grep -q "200"; then
        log_success "Service connectivity test passed"
    else
        log_warning "Service connectivity test failed - this may be expected during initial deployment"
    fi
    
    log_success "Service mesh deployment verification completed"
}

# Cleanup function
cleanup() {
    log_info "Cleaning up temporary files..."
    # Add any cleanup logic here
}

# Main deployment function
main() {
    log_info "Starting service mesh deployment for VoiceHive Hotels"
    log_info "Mesh type: $MESH_TYPE"
    log_info "Environment: $ENVIRONMENT"
    log_info "Namespace: $NAMESPACE"
    log_info "Dry run: $DRY_RUN"
    
    # Set trap for cleanup
    trap cleanup EXIT
    
    # Execute deployment steps
    check_prerequisites
    
    case "$MESH_TYPE" in
        "istio")
            install_istio
            ;;
        "linkerd")
            install_linkerd
            ;;
        *)
            log_error "Unknown mesh type: $MESH_TYPE. Supported types: istio, linkerd"
            exit 1
            ;;
    esac
    
    apply_network_policies
    apply_service_mesh_config
    setup_monitoring
    
    if [[ "$DRY_RUN" != "true" ]]; then
        restart_deployments
        verify_deployment
    fi
    
    log_success "Service mesh deployment completed successfully!"
    
    # Print next steps
    echo
    log_info "Next steps:"
    echo "1. Monitor the deployment using: kubectl get pods -n $NAMESPACE"
    echo "2. Check service mesh status with appropriate CLI tool"
    echo "3. Review monitoring dashboards for network security metrics"
    echo "4. Test application functionality end-to-end"
    echo "5. Review incident response procedures in docs/security/"
}

# Help function
show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Deploy service mesh for VoiceHive Hotels with zero-trust network security.

OPTIONS:
    -m, --mesh-type TYPE     Service mesh type (istio|linkerd) [default: istio]
    -e, --environment ENV    Environment (production|staging|development) [default: production]
    -n, --namespace NS       Kubernetes namespace [default: voicehive]
    -d, --dry-run           Perform a dry run without making changes
    -h, --help              Show this help message

EXAMPLES:
    # Deploy Istio in production
    $0 --mesh-type istio --environment production

    # Deploy Linkerd in staging with dry run
    $0 --mesh-type linkerd --environment staging --dry-run

    # Deploy with custom namespace
    $0 --namespace voicehive-prod

ENVIRONMENT VARIABLES:
    MESH_TYPE               Service mesh type (overridden by --mesh-type)
    ENVIRONMENT             Environment name (overridden by --environment)
    NAMESPACE               Kubernetes namespace (overridden by --namespace)
    DRY_RUN                 Dry run mode (overridden by --dry-run)

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -m|--mesh-type)
            MESH_TYPE="$2"
            shift 2
            ;;
        -e|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -d|--dry-run)
            DRY_RUN="true"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Validate mesh type
if [[ "$MESH_TYPE" != "istio" && "$MESH_TYPE" != "linkerd" ]]; then
    log_error "Invalid mesh type: $MESH_TYPE. Supported types: istio, linkerd"
    exit 1
fi

# Run main function
main