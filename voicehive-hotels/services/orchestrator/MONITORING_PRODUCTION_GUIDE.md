# VoiceHive Hotels - Production Monitoring Guide

This guide provides production-ready configuration and deployment instructions for the monitoring and observability stack, following official documentation and best practices.

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Application   │───▶│   Prometheus    │───▶│     Grafana     │
│  (FastAPI +     │    │   (Metrics)     │    │  (Dashboards)   │
│   Prometheus)   │    └─────────────────┘    └─────────────────┘
└─────────────────┘              │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ OpenTelemetry   │    │   AlertManager  │    │   Notification  │
│ (Jaeger/Tempo)  │    │   (Alerting)    │    │   Channels      │
└─────────────────┘    └─────────────────┘    │ (Slack/PagerDuty)│
                                              └─────────────────┘
```

## 📊 Prometheus Configuration

### 1. Prometheus Server Configuration (`prometheus.yml`)

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "voicehive_alerts.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093

scrape_configs:
  - job_name: "voicehive-orchestrator"
    static_configs:
      - targets: ["orchestrator:8000"]
    metrics_path: "/metrics"
    scrape_interval: 15s
    scrape_timeout: 10s

  - job_name: "voicehive-business-metrics"
    static_configs:
      - targets: ["orchestrator:8000"]
    metrics_path: "/monitoring/metrics"
    scrape_interval: 30s
```

### 2. Alert Rules (`voicehive_alerts.yml`)

```yaml
groups:
  - name: voicehive.rules
    rules:
      # Call Success Rate SLA
      - alert: CallSuccessRateLow
        expr: (rate(voicehive_call_success_total[5m]) / (rate(voicehive_call_success_total[5m]) + rate(voicehive_call_failures_total[5m]))) * 100 < 99
        for: 2m
        labels:
          severity: critical
          service: voicehive-orchestrator
        annotations:
          summary: "Call success rate below SLA threshold"
          description: "Call success rate is {{ $value }}% which is below the 99% SLA threshold"
          runbook_url: "https://docs.voicehive.com/runbooks/call-failures"

      # PMS Response Time
      - alert: PMSResponseTimeSlow
        expr: histogram_quantile(0.95, rate(voicehive_pms_response_seconds_bucket[5m])) > 2
        for: 3m
        labels:
          severity: warning
          service: voicehive-orchestrator
        annotations:
          summary: "PMS response time is slow"
          description: "95th percentile PMS response time is {{ $value }}s"
          runbook_url: "https://docs.voicehive.com/runbooks/pms-performance"

      # High Error Rate
      - alert: HighErrorRate
        expr: rate(voicehive_errors_total[5m]) > 0.05
        for: 2m
        labels:
          severity: high
          service: voicehive-orchestrator
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} errors/second"

      # Memory Usage
      - alert: HighMemoryUsage
        expr: voicehive_memory_usage_bytes / (1024*1024*1024) > 1
        for: 5m
        labels:
          severity: warning
          service: voicehive-orchestrator
        annotations:
          summary: "High memory usage"
          description: "Memory usage is {{ $value }}GB"
```

## 🔔 AlertManager Configuration

### AlertManager Configuration (`alertmanager.yml`)

```yaml
global:
  smtp_smarthost: "localhost:587"
  smtp_from: "alerts@voicehive.com"

route:
  group_by: ["alertname", "service"]
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: "web.hook"
  routes:
    - match:
        severity: critical
      receiver: "pagerduty-critical"
    - match:
        severity: warning
      receiver: "slack-warnings"

receivers:
  - name: "web.hook"
    webhook_configs:
      - url: "http://orchestrator:8000/monitoring/alerts/webhook"

  - name: "slack-warnings"
    slack_configs:
      - api_url: "${SLACK_WEBHOOK_URL}"
        channel: "#alerts"
        title: "VoiceHive Alert"
        text: "{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}"

  - name: "pagerduty-critical"
    pagerduty_configs:
      - routing_key: "${PAGERDUTY_INTEGRATION_KEY}"
        description: "{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}"
```

## 📈 Grafana Configuration

### 1. Data Source Configuration

```json
{
  "name": "Prometheus",
  "type": "prometheus",
  "url": "http://prometheus:9090",
  "access": "proxy",
  "isDefault": true,
  "jsonData": {
    "timeInterval": "15s"
  }
}
```

### 2. Dashboard Import

Import the pre-configured dashboards via API:

```bash
# Business Metrics Dashboard
curl -X POST \
  http://grafana:3000/api/dashboards/db \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ${GRAFANA_API_KEY}' \
  -d @business-metrics-dashboard.json

# System Health Dashboard
curl -X POST \
  http://grafana:3000/api/dashboards/db \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ${GRAFANA_API_KEY}' \
  -d @system-health-dashboard.json

# SLA Monitoring Dashboard
curl -X POST \
  http://grafana:3000/api/dashboards/db \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ${GRAFANA_API_KEY}' \
  -d @sla-monitoring-dashboard.json
```

## 🔍 OpenTelemetry Configuration

### 1. Jaeger Configuration

```yaml
# docker-compose.yml
services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"
      - "14268:14268"
    environment:
      - COLLECTOR_OTLP_ENABLED=true
```

### 2. Tempo Configuration (Alternative to Jaeger)

```yaml
# tempo.yml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317

storage:
  trace:
    backend: local
    local:
      path: /tmp/tempo/traces
```

## 🚀 Docker Compose Production Setup

```yaml
version: "3.8"

services:
  orchestrator:
    build: .
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=production
      - METRICS_ENABLED=true
      - ALERTING_ENABLED=true
      - TRACING_ENABLED=true
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}
      - PAGERDUTY_INTEGRATION_KEY=${PAGERDUTY_INTEGRATION_KEY}
      - JAEGER_ENDPOINT=http://jaeger:14268/api/traces
      - OTLP_ENDPOINT=http://tempo:4317
    depends_on:
      - prometheus
      - jaeger
      - redis

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - ./monitoring/voicehive_alerts.yml:/etc/prometheus/voicehive_alerts.yml
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--web.console.libraries=/etc/prometheus/console_libraries"
      - "--web.console.templates=/etc/prometheus/consoles"
      - "--web.enable-lifecycle"
      - "--web.enable-admin-api"

  alertmanager:
    image: prom/alertmanager:latest
    ports:
      - "9093:9093"
    volumes:
      - ./monitoring/alertmanager.yml:/etc/alertmanager/alertmanager.yml

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
    volumes:
      - grafana-storage:/var/lib/grafana
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"
      - "14268:14268"
    environment:
      - COLLECTOR_OTLP_ENABLED=true

volumes:
  grafana-storage:
```

## 🔧 Environment Variables

```bash
# Required Environment Variables
export ENVIRONMENT=production
export METRICS_ENABLED=true
export ALERTING_ENABLED=true
export TRACING_ENABLED=true

# Notification Channels
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
export PAGERDUTY_INTEGRATION_KEY="your-pagerduty-integration-key"

# Grafana
export GRAFANA_ADMIN_PASSWORD="secure-password"
export GRAFANA_API_KEY="your-grafana-api-key"

# Tracing
export JAEGER_ENDPOINT="http://jaeger:14268/api/traces"
export OTLP_ENDPOINT="http://tempo:4317"
export TRACE_SAMPLE_RATE="0.01"  # 1% sampling in production

# Thresholds
export CALL_SUCCESS_RATE_THRESHOLD="99.0"
export PMS_RESPONSE_TIME_THRESHOLD="2.0"
export CPU_USAGE_THRESHOLD="80.0"
export MEMORY_USAGE_THRESHOLD="80.0"
```

## 📋 Production Checklist

### Pre-Deployment

- [ ] Configure Prometheus scraping endpoints
- [ ] Set up AlertManager with notification channels
- [ ] Import Grafana dashboards
- [ ] Configure OpenTelemetry exporters
- [ ] Set up log aggregation (ELK/Loki)
- [ ] Configure backup for metrics data

### Security

- [ ] Enable HTTPS for all monitoring endpoints
- [ ] Configure authentication for Grafana
- [ ] Secure Prometheus with basic auth
- [ ] Network isolation for monitoring stack
- [ ] Regular security updates

### Performance

- [ ] Configure appropriate retention policies
- [ ] Set up metrics storage optimization
- [ ] Configure trace sampling rates
- [ ] Monitor monitoring stack resource usage

### Reliability

- [ ] Set up monitoring stack high availability
- [ ] Configure data backup and recovery
- [ ] Test alert notification channels
- [ ] Validate dashboard functionality
- [ ] Test trace collection and querying

## 🔍 Troubleshooting

### Common Issues

1. **Metrics not appearing in Prometheus**

   - Check scrape configuration
   - Verify endpoint accessibility
   - Check application logs

2. **Alerts not firing**

   - Validate alert rule syntax
   - Check AlertManager configuration
   - Verify notification channel setup

3. **Traces not appearing**

   - Check OpenTelemetry configuration
   - Verify exporter endpoints
   - Check sampling configuration

4. **Dashboard not loading**
   - Verify data source configuration
   - Check Prometheus connectivity
   - Validate dashboard JSON

### Monitoring the Monitoring Stack

```bash
# Check Prometheus targets
curl http://prometheus:9090/api/v1/targets

# Check AlertManager status
curl http://alertmanager:9093/api/v1/status

# Check Grafana health
curl http://grafana:3000/api/health

# Check application metrics endpoint
curl http://orchestrator:8000/metrics
```

## 📚 References

- [Prometheus Best Practices](https://prometheus.io/docs/practices/)
- [Grafana Dashboard Best Practices](https://grafana.com/docs/grafana/latest/best-practices/)
- [OpenTelemetry Python Documentation](https://opentelemetry.io/docs/languages/python/)
- [Slack Webhook API](https://api.slack.com/messaging/webhooks)
- [PagerDuty Events API](https://developer.pagerduty.com/docs/events-api-v2/overview/)

This production guide ensures your monitoring stack follows industry best practices and official documentation recommendations.
