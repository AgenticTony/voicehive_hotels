# Observability Runbook

## Overview

VoiceHive Hotels implements comprehensive observability through metrics, logging, and distributed tracing. This runbook covers key endpoints, dashboards, and troubleshooting procedures.

## Health Check Endpoints

### Orchestrator Service

All health endpoints are available under the orchestrator service:

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `GET /health` | Basic health check | `{"status": "healthy"}` |
| `GET /health/live` | Kubernetes liveness probe | 200 OK |
| `GET /health/ready` | Kubernetes readiness probe | 200 OK when all dependencies ready |
| `GET /health/metrics` | Component health gauges | Prometheus format metrics |
| `GET /health/vault` | Vault connectivity status | `{"status": "connected", "sealed": false}` |
| `GET /metrics` | Prometheus metrics | Full metrics in Prometheus format |

### Example Health Checks

```bash
# Check orchestrator health
curl -s http://orchestrator.voicehive.svc.cluster.local:8000/health | jq .

# Check readiness (includes dependency checks)
curl -s http://orchestrator.voicehive.svc.cluster.local:8000/health/ready

# Get component metrics
curl -s http://orchestrator.voicehive.svc.cluster.local:8000/health/metrics

# Check Vault connectivity
curl -s http://orchestrator.voicehive.svc.cluster.local:8000/health/vault | jq .
```

## Metrics

### Key Metrics to Monitor

#### Connector Metrics
- `connector_requests_total` - Total requests by vendor, method, status
- `connector_request_duration_seconds` - Request latency histogram
- `connector_errors_total` - Error count by vendor and error type
- `connector_circuit_breaker_state` - Circuit breaker status (0=closed, 1=open)

#### Call Metrics  
- `calls_total` - Total calls by status
- `active_calls` - Currently active calls gauge
- `call_duration_seconds` - Call duration histogram

#### PMS Integration Metrics
- `pms_api_requests_total` - PMS API call count
- `pms_api_latency_seconds` - PMS API response time
- `pms_cache_hits_total` - Cache hit rate
- `pms_rate_limit_remaining` - Rate limit headroom

### Prometheus Queries

```promql
# Connector error rate by vendor (5m)
sum(rate(connector_errors_total[5m])) by (vendor) 
/ sum(rate(connector_requests_total[5m])) by (vendor)

# P95 response time by vendor
histogram_quantile(0.95, 
  sum(rate(connector_request_duration_seconds_bucket[5m])) by (vendor, le)
)

# Active calls
active_calls

# Vault health (1 = healthy, 0 = unhealthy)
vault_health_status
```

## Grafana Dashboards

### Available Dashboards

1. **PMS Connectors Performance** (`/dashboards/pms-connectors`)
   - Request rates by vendor
   - Error rates and types
   - Response time percentiles
   - API method distribution

2. **System Overview** (coming in Sprint 1)
   - Call volume and success rate
   - Resource utilization
   - Service dependencies

3. **SLA Monitoring** (coming in Sprint 1)
   - SLO compliance tracking
   - Error budget consumption

### Accessing Grafana

```bash
# Port-forward for local access
kubectl port-forward -n monitoring svc/grafana 3000:3000

# Default URL: http://localhost:3000
# Credentials: Retrieved from Vault or ExternalSecrets
```

## Logging

### Log Aggregation (Sprint 1)

Logs are structured JSON with PII automatically redacted:

```json
{
  "timestamp": "2024-08-15T10:30:45.123Z",
  "level": "INFO",
  "service": "orchestrator",
  "correlation_id": "abc123",
  "hotel_id": "hotel_xyz",
  "message": "PMS API call completed",
  "pms_vendor": "apaleo",
  "duration_ms": 156,
  "guest_name": "[REDACTED]"
}
```

### Key Log Queries

```bash
# Check for connector errors
kubectl logs -n voicehive -l app=orchestrator --tail=100 | jq 'select(.level=="ERROR")'

# Monitor PMS API calls
kubectl logs -n voicehive -l app=orchestrator --tail=100 | jq 'select(.pms_vendor!=null)'

# Check circuit breaker events  
kubectl logs -n voicehive -l app=orchestrator | grep -i "circuit.*open"
```

## Alerting Rules

### Critical Alerts

1. **High Error Rate**
   ```yaml
   - alert: ConnectorHighErrorRate
     expr: |
       sum(rate(connector_errors_total[5m])) by (vendor)
       / sum(rate(connector_requests_total[5m])) by (vendor) > 0.05
     for: 5m
     labels:
       severity: critical
     annotations:
       summary: "High error rate for {{ $labels.vendor }} connector"
   ```

2. **Vault Unavailable**
   ```yaml
   - alert: VaultDown
     expr: vault_health_status == 0
     for: 1m
     labels:
       severity: critical
   ```

3. **High Latency**
   ```yaml
   - alert: ConnectorHighLatency
     expr: |
       histogram_quantile(0.95,
         sum(rate(connector_request_duration_seconds_bucket[5m])) by (vendor, le)
       ) > 0.5
     for: 5m
   ```

## Troubleshooting

### Connector Issues

```bash
# Check connector health
curl http://orchestrator:8000/health/metrics | grep connector_

# View connector logs
kubectl logs -n voicehive deployment/orchestrator -f | grep -i apaleo

# Check circuit breaker state
curl http://orchestrator:8000/metrics | grep circuit_breaker
```

### Performance Issues

```bash
# Check resource usage
kubectl top pods -n voicehive

# Review slow queries
kubectl logs -n voicehive -l app=orchestrator | jq 'select(.duration_ms > 1000)'

# Check cache effectiveness
curl http://orchestrator:8000/metrics | grep cache_hits
```

### Vault Connectivity

```bash
# Check Vault health endpoint
curl http://orchestrator:8000/health/vault

# Verify Vault pod
kubectl get pods -n vault

# Check Vault seal status
kubectl exec -n vault vault-0 -- vault status
```

## Maintenance Procedures

### Metric Retention

Prometheus is configured with 30-day retention:
```yaml
retention: 30d
retentionSize: 10GB
```

### Dashboard Backup

```bash
# Export all dashboards
kubectl exec -n monitoring deployment/grafana -- \
  grafana-cli admin export-dashboard --dir /tmp/dashboards

# Copy locally
kubectl cp monitoring/grafana-xxx:/tmp/dashboards ./dashboard-backup/
```

### Adding New Metrics

1. Instrument code with Prometheus client
2. Update Prometheus scrape config if needed
3. Create/update Grafana dashboard
4. Add relevant alerts

## References

- [Prometheus Best Practices](https://prometheus.io/docs/practices/)
- [Grafana Dashboard Guide](https://grafana.com/docs/grafana/latest/dashboards/)
- [OpenTelemetry Integration](https://opentelemetry.io/) (Sprint 2)
