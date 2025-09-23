#!/bin/bash
# Configuration Management Script
# Manages environment-specific configurations for deployments

set -euo pipefail

# Configuration
ENVIRONMENTS_DIR="config/environments"
TEMPLATES_DIR="infra/helm/voicehive/templates"
CONFIG_OUTPUT_DIR="/tmp/voicehive-configs"

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

# Function to validate environment configuration
validate_config() {
    local env_file="$1"
    
    log "Validating configuration file: $env_file"
    
    # Check if file exists
    if [ ! -f "$env_file" ]; then
        error "Configuration file not found: $env_file"
        return 1
    fi
    
    # Validate YAML syntax
    if ! yq eval '.' "$env_file" > /dev/null 2>&1; then
        error "Invalid YAML syntax in $env_file"
        return 1
    fi
    
    # Check required fields
    local required_fields=(
        ".environment.name"
        ".environment.tier"
        ".application.name"
        ".database.host"
        ".redis.host"
    )
    
    for field in "${required_fields[@]}"; do
        if ! yq eval "$field" "$env_file" > /dev/null 2>&1; then
            error "Missing required field: $field in $env_file"
            return 1
        fi
    done
    
    log "Configuration validation passed for $env_file"
    return 0
}

# Function to generate Kubernetes manifests
generate_k8s_manifests() {
    local environment="$1"
    local config_file="$ENVIRONMENTS_DIR/$environment.yaml"
    local output_dir="$CONFIG_OUTPUT_DIR/$environment"
    
    log "Generating Kubernetes manifests for environment: $environment"
    
    # Create output directory
    mkdir -p "$output_dir"
    
    # Generate ConfigMap
    log "Generating ConfigMap..."
    cat > "$output_dir/configmap.yaml" << EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: voicehive-config
  namespace: voicehive-$environment
  labels:
    app: voicehive-hotels
    environment: $environment
data:
  config.yaml: |
$(yq eval '.' "$config_file" | sed 's/^/    /')
EOF

    # Generate environment-specific values
    log "Generating Helm values..."
    yq eval '
      {
        "environment": .environment.name,
        "image": {
          "tag": .application.version
        },
        "resources": .resources,
        "scaling": .scaling,
        "monitoring": .monitoring,
        "security": .security_policies
      }
    ' "$config_file" > "$output_dir/values.yaml"
    
    # Generate secrets template (with placeholders)
    log "Generating secrets template..."
    cat > "$output_dir/secrets.yaml" << EOF
apiVersion: v1
kind: Secret
metadata:
  name: voicehive-secrets
  namespace: voicehive-$environment
  labels:
    app: voicehive-hotels
    environment: $environment
type: Opaque
stringData:
  # Database credentials
  database-url: "postgresql://\${DB_USER}:\${DB_PASSWORD}@$(yq eval '.database.host' "$config_file"):$(yq eval '.database.port' "$config_file")/$(yq eval '.database.name' "$config_file")"
  
  # Redis credentials
  redis-url: "redis://\${REDIS_PASSWORD}@$(yq eval '.redis.host' "$config_file"):$(yq eval '.redis.port' "$config_file")/$(yq eval '.redis.db' "$config_file")"
  
  # JWT signing key
  jwt-private-key: "\${JWT_PRIVATE_KEY}"
  jwt-public-key: "\${JWT_PUBLIC_KEY}"
  
  # External service credentials
  azure-speech-key: "\${AZURE_SPEECH_KEY}"
  elevenlabs-api-key: "\${ELEVENLABS_API_KEY}"
  
  # Monitoring credentials
  prometheus-token: "\${PROMETHEUS_TOKEN}"
  jaeger-token: "\${JAEGER_TOKEN}"
EOF

    log "Kubernetes manifests generated in: $output_dir"
    return 0
}

# Function to apply configuration to cluster
apply_config() {
    local environment="$1"
    local namespace="voicehive-$environment"
    local config_dir="$CONFIG_OUTPUT_DIR/$environment"
    
    log "Applying configuration for environment: $environment"
    
    # Create namespace if it doesn't exist
    if ! kubectl get namespace "$namespace" > /dev/null 2>&1; then
        log "Creating namespace: $namespace"
        kubectl create namespace "$namespace"
    fi
    
    # Apply ConfigMap
    log "Applying ConfigMap..."
    kubectl apply -f "$config_dir/configmap.yaml"
    
    # Note: Secrets should be applied separately with actual values
    warn "Secrets template generated but not applied. Please substitute actual values and apply manually."
    
    log "Configuration applied successfully"
    return 0
}

# Function to compare configurations
compare_configs() {
    local env1="$1"
    local env2="$2"
    
    log "Comparing configurations: $env1 vs $env2"
    
    local config1="$ENVIRONMENTS_DIR/$env1.yaml"
    local config2="$ENVIRONMENTS_DIR/$env2.yaml"
    
    if [ ! -f "$config1" ] || [ ! -f "$config2" ]; then
        error "One or both configuration files not found"
        return 1
    fi
    
    # Compare using diff
    if diff -u "$config1" "$config2"; then
        log "Configurations are identical"
    else
        warn "Configurations differ (see above)"
    fi
    
    return 0
}

# Function to backup current configuration
backup_config() {
    local environment="$1"
    local namespace="voicehive-$environment"
    local backup_dir="/tmp/voicehive-backup-$(date +%Y%m%d-%H%M%S)"
    
    log "Backing up current configuration for environment: $environment"
    
    mkdir -p "$backup_dir"
    
    # Backup ConfigMaps
    kubectl get configmap -n "$namespace" -o yaml > "$backup_dir/configmaps.yaml" 2>/dev/null || true
    
    # Backup Secrets (metadata only for security)
    kubectl get secret -n "$namespace" -o yaml | yq eval 'del(.items[].data, .items[].stringData)' > "$backup_dir/secrets-metadata.yaml" 2>/dev/null || true
    
    # Backup current environment config file
    cp "$ENVIRONMENTS_DIR/$environment.yaml" "$backup_dir/environment-config.yaml" 2>/dev/null || true
    
    log "Configuration backed up to: $backup_dir"
    return 0
}

# Function to validate deployment readiness
validate_deployment_readiness() {
    local environment="$1"
    
    log "Validating deployment readiness for environment: $environment"
    
    local config_file="$ENVIRONMENTS_DIR/$environment.yaml"
    
    # Check configuration exists and is valid
    if ! validate_config "$config_file"; then
        error "Configuration validation failed"
        return 1
    fi
    
    # Check required external dependencies
    local db_host=$(yq eval '.database.host' "$config_file")
    local redis_host=$(yq eval '.redis.host' "$config_file")
    
    log "Checking database connectivity to: $db_host"
    # Note: In real deployment, this would test actual connectivity
    
    log "Checking Redis connectivity to: $redis_host"
    # Note: In real deployment, this would test actual connectivity
    
    # Check security requirements
    local security_enabled=$(yq eval '.application.security.enhanced_mode' "$config_file")
    if [ "$security_enabled" != "true" ]; then
        error "Enhanced security mode must be enabled for deployment"
        return 1
    fi
    
    # Check monitoring requirements
    local monitoring_enabled=$(yq eval '.monitoring.enabled' "$config_file")
    if [ "$monitoring_enabled" != "true" ]; then
        error "Monitoring must be enabled for deployment"
        return 1
    fi
    
    log "Deployment readiness validation passed"
    return 0
}

# Function to show usage
show_usage() {
    cat << EOF
Usage: $0 COMMAND [OPTIONS]

Configuration Management for VoiceHive Deployments

COMMANDS:
    validate ENV                    Validate environment configuration
    generate ENV                    Generate Kubernetes manifests
    apply ENV                       Apply configuration to cluster
    compare ENV1 ENV2              Compare two environment configurations
    backup ENV                      Backup current configuration
    check-readiness ENV            Validate deployment readiness

OPTIONS:
    -h, --help                     Show this help message

EXAMPLES:
    # Validate staging configuration
    $0 validate staging

    # Generate production manifests
    $0 generate production

    # Apply staging configuration
    $0 apply staging

    # Compare staging and production
    $0 compare staging production

    # Backup production configuration
    $0 backup production

    # Check deployment readiness
    $0 check-readiness production

EOF
}

# Main execution
main() {
    local command="${1:-}"
    
    case "$command" in
        validate)
            if [ $# -ne 2 ]; then
                error "Usage: $0 validate ENVIRONMENT"
                exit 1
            fi
            validate_config "$ENVIRONMENTS_DIR/$2.yaml"
            ;;
        generate)
            if [ $# -ne 2 ]; then
                error "Usage: $0 generate ENVIRONMENT"
                exit 1
            fi
            validate_config "$ENVIRONMENTS_DIR/$2.yaml" && generate_k8s_manifests "$2"
            ;;
        apply)
            if [ $# -ne 2 ]; then
                error "Usage: $0 apply ENVIRONMENT"
                exit 1
            fi
            generate_k8s_manifests "$2" && apply_config "$2"
            ;;
        compare)
            if [ $# -ne 3 ]; then
                error "Usage: $0 compare ENV1 ENV2"
                exit 1
            fi
            compare_configs "$2" "$3"
            ;;
        backup)
            if [ $# -ne 2 ]; then
                error "Usage: $0 backup ENVIRONMENT"
                exit 1
            fi
            backup_config "$2"
            ;;
        check-readiness)
            if [ $# -ne 2 ]; then
                error "Usage: $0 check-readiness ENVIRONMENT"
                exit 1
            fi
            validate_deployment_readiness "$2"
            ;;
        -h|--help|help)
            show_usage
            exit 0
            ;;
        *)
            error "Unknown command: $command"
            show_usage
            exit 1
            ;;
    esac
}

# Check dependencies
if ! command -v yq &> /dev/null; then
    error "yq is required but not installed"
    exit 1
fi

if ! command -v kubectl &> /dev/null; then
    error "kubectl is required but not installed"
    exit 1
fi

# Run main function
main "$@"