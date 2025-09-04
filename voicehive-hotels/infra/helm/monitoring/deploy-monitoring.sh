#!/bin/bash
# Deploy Prometheus monitoring stack to Kubernetes

set -e

NAMESPACE="monitoring"
RELEASE_NAME="prometheus-stack"
CHART_VERSION="60.2.0"  # Latest stable version

echo "Deploying Prometheus Stack for VoiceHive Hotels monitoring"

# Create namespace if it doesn't exist
echo "Creating namespace: $NAMESPACE"
kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

# Add Prometheus Community Helm repository
echo "Adding prometheus-community Helm repository"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Deploy or upgrade the stack
echo "Installing/Upgrading Prometheus Stack"
helm upgrade --install $RELEASE_NAME \
  prometheus-community/kube-prometheus-stack \
  --namespace $NAMESPACE \
  --version $CHART_VERSION \
  --values prometheus-stack-values.yaml \
  --wait \
  --timeout 10m

echo "Deployment complete!"
echo ""
echo "Access points:"
echo "  Prometheus: kubectl port-forward -n $NAMESPACE svc/$RELEASE_NAME-kube-prom-prometheus 9090:9090"
echo "  Grafana: kubectl port-forward -n $NAMESPACE svc/$RELEASE_NAME-grafana 3000:80"
echo "  Alertmanager: kubectl port-forward -n $NAMESPACE svc/$RELEASE_NAME-kube-prom-alertmanager 9093:9093"
echo ""
echo "Default Grafana credentials:"
echo "  Username: admin"
echo "  Password: changeme (please change this!)"
