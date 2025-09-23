# VoiceHive SLO Monitoring Guide

## Overview

This guide covers the Service Level Indicators (SLI) and Service Level Objectives (SLO) monitoring system implemented for VoiceHive Hotels. The system provides production-grade observability with error budget tracking, burn rate alerting, and automated incident response.

## Table of Contents

1. [SLI/SLO Concepts](#slislo-concepts)
2. [VoiceHive SLO Definitions](#voicehive-slo-definitions)
3. [Error Budget Management](#error-budget-management)
4. [Burn Rate Monitoring](#burn-rate-monitoring)
5. [Runbook Automation](#runbook-automation)
6. [Dashboards and Alerting](#dashboards-and-alerting)
7. [API Reference](#api-reference)
8. [Troubleshooting](#troubleshooting)

## SLI/SLO Concepts

### Service Level Indicators (SLIs)

SLIs are quantitative measures of service performance. VoiceHive uses the following SLI types:

- **Availability**: Percentage of successful requests (non-5xx responses)
- **Latency**: Percentage of requests completed within threshold time
- **Error Rate**: Percentage of failed requests
- **Business Metrics**: Custom metrics like guest satisfaction scores

### Service Level Objectives (SLOs)

SLOs define target values for SLIs over specific time periods. Each SLO includes:

- **Target Percentage**: The desired performance level (e.g., 99.9%)
- **Compliance Period**: Time window for measurement (e.g., 30 days)
- **Error Budget**: Allowed failure rate (100% - SLO target)

### Error Budgets

Error budgets quantify how much a service can fail while still meeting its SLO:

```
Error Budget = (100% - SLO Target) × Total Events
```

For a 99.9% SLO over 30 days:

- Error Budget = 0.1% of all requests
- If you serve 1M requests, you can have 1,000 failures

## VoiceHive SLO Definitions

### Core Infrastructure SLOs

#### 1. API Availability

- **Target**: 99.9% over 30 days, 99.5% over 7 days
- **SLI Query**:
  ```promql
  sum(rate(voicehive_requests_total{status!~"5.."}[5m])) /
  sum(rate(voicehive_requests_total[5m]))
  ```
- **Criticality**: High
- **Team**: Platform

#### 2. API Latency (P95)

- **Target**: 95% of requests under 2 seconds
- **SLI Query**:
  ```promql
  sum(rate(voicehive_request_duration_seconds_bucket{le="2.0"}[5m])) /
  sum(rate(voicehive_request_duration_seconds_count[5m]))
  ```
- **Criticality**: High
- **Team**: Platform

#### 3. Authentication Success Rate

- **Target**: 99.5% over 30 days
- **SLI Query**:
  ```promql
  (sum(rate(voicehive_auth_requests_total[5m])) - sum(rate(voicehive_auth_failures_total[5m]))) /
  sum(rate(voicehive_auth_requests_total[5m]))
  ```
- **Criticality**: Critical
- **Team**: Security

### Business SLOs

#### 4. Call Success Rate

- **Target**: 99% over 30 days, 98% over 7 days
- **SLI Query**:
  ```promql
  sum(rate(voicehive_call_success_total[5m])) /
  (sum(rate(voicehive_call_success_total[5m])) + sum(rate(voicehive_call_failures_total[5m])))
  ```
- **Criticality**: Critical
- **Team**: Voice Engineering

#### 5. Guest Satisfaction

- **Target**: 90% of time with satisfaction score ≥ 4.0
- **SLI Query**:
  ```promql
  (sum(rate(voicehive_guest_satisfaction_sum[24h])) /
   sum(rate(voicehive_guest_satisfaction_count[24h]))) >= 4.0
  ```
- **Criticality**: High
- **Team**: Product

### Integration SLOs

#### 6. PMS Connector Availability

- **Target**: 98% over 30 days
- **SLI Query**:
  ```promql
  sum(rate(voicehive_pms_operations_total{status="success"}[5m])) /
  sum(rate(voicehive_pms_operations_total[5m]))
  ```
- **Criticality**: High
- **Team**: Integrations

## Error Budget Management

### Error Budget Policies

Each SLO has an error budget policy defining:

```yaml
error_budget_policy:
  burn_rate_thresholds:
    1h: 14.4 # Alert if burning 1% budget in 1 hour
    6h: 6.0 # Alert if burning 5% budget in 6 hours
    24h: 3.0 # Alert if burning 10% budget in 24 hours
    72h: 1.0 # Alert if burning 25% budget in 72 hours
  alert_on_exhaustion_percentage: 90.0
  freeze_deployments_percentage: 95.0
```

### Error Budget Calculation

Error budget remaining is calculated as:

```
Remaining = 1 - ((Target - Current_SLI) / (100 - Target))
```

### Deployment Freeze Policy

When error budgets are critically low (< 5% remaining):

1. **Automatic Alerts**: Sent to team channels and on-call
2. **Deployment Freeze**: Recommended for non-critical changes
3. **Focus on Reliability**: Prioritize bug fixes over new features
4. **Runbook Execution**: Automated remediation attempts

## Burn Rate Monitoring

### Burn Rate Definition

Burn rate indicates how fast you're consuming your error budget:

```
Burn Rate = (Error Rate) / (Error Budget Rate)
```

- **Burn Rate = 1**: Consuming budget at expected rate
- **Burn Rate > 1**: Consuming budget faster than sustainable
- **Burn Rate = 0**: No errors, budget not consumed

### Multi-Window Alerting

VoiceHive uses multi-window burn rate alerting:

| Window | Threshold | Alert Severity | Response Time |
| ------ | --------- | -------------- | ------------- |
| 1h     | 14.4x     | Critical       | 2 minutes     |
| 6h     | 6.0x      | Warning        | 15 minutes    |
| 24h    | 3.0x      | Info           | 1 hour        |
| 72h    | 1.0x      | Info           | 4 hours       |

### Burn Rate Alerts

Fast burn rate alerts (1h window) indicate immediate issues:

- Service outages
- Performance degradation
- High error rates

Slow burn rate alerts (24h+ window) indicate trends:

- Gradual performance decline
- Capacity issues
- Code quality problems

## Runbook Automation

### Automated Response System

VoiceHive includes automated runbook execution for common SLO violations:

#### API Availability Runbook

```yaml
trigger_conditions: ["VoiceHiveAPIAvailabilityFastBurnRate"]
steps: 1. Check service health endpoints
  2. Notify on-call team via Slack/PagerDuty
  3. Scale orchestrator service (if error budget < 20%)
  4. Reset circuit breakers
  5. Verify recovery
```

#### High Latency Runbook

```yaml
trigger_conditions: ["VoiceHiveAPILatencyFastBurnRate"]
steps: 1. Clear application cache
  2. Reset database connection pool
  3. Notify performance team
  4. Verify latency improvement
```

#### Call Success Rate Runbook

```yaml
trigger_conditions: ["VoiceHiveCallSuccessFastBurnRate"]
steps: 1. Check PMS connector health
  2. Restart call manager (if error budget < 10%)
  3. Notify voice engineering team
  4. Enable fallback mode if needed
```

### Runbook Configuration

Runbooks include safety controls:

- **Cooldown Period**: Minimum time between executions
- **Rate Limiting**: Maximum executions per hour
- **Conditional Steps**: Execute only when conditions are met
- **Required vs Optional**: Stop execution if required steps fail

## Dashboards and Alerting

### Grafana Dashboards

#### SLO Overview Dashboard

- **URL**: `/d/slo-overview/slo-overview`
- **Panels**:
  - SLO compliance summary
  - Current SLI values vs targets
  - Error budget remaining
  - Burn rate analysis
  - Active alerts

#### Business Metrics Dashboard

- Guest satisfaction trends
- Booking conversion rates
- Revenue impact metrics
- Call success rates by hotel

### Alert Routing

Alerts are routed based on severity and team:

```yaml
routes:
  - match: { severity: critical }
    receiver: critical-alerts
    group_wait: 5s
    repeat_interval: 30m

  - match: { team: security }
    receiver: security-alerts
    group_wait: 0s
    repeat_interval: 15m
```

### Alert Receivers

- **Critical Alerts**: PagerDuty + Slack + Email
- **Warning Alerts**: Slack + Email
- **Security Alerts**: Security team Slack + Email
- **Business Alerts**: Product team notifications

## API Reference

### SLO Status Endpoint

```http
GET /slo/status
```

Query parameters:

- `slo_name`: Filter by specific SLO
- `service`: Filter by service name

Response:

```json
{
  "summary": {
    "total_slos": 8,
    "compliant": 6,
    "at_risk": 1,
    "violated": 1
  },
  "slos": {
    "api_availability": {
      "current_sli": 99.95,
      "target": 99.9,
      "compliance_status": "compliant",
      "error_budget_remaining": 75.0,
      "burn_rates": {
        "1h": 0.5,
        "6h": 0.3
      }
    }
  }
}
```

### Error Budget Endpoint

```http
GET /slo/error-budget
```

Response includes:

- Current error budget status
- Burn rate analysis
- Deployment freeze recommendations
- Budget exhaustion ETA

### Runbook Execution

```http
POST /slo/runbooks/{runbook_name}/execute
```

Manually trigger runbook execution for testing or emergency response.

## Troubleshooting

### Common Issues

#### 1. SLO Evaluation Failures

**Symptoms**: Missing SLO data, "unknown" compliance status

**Causes**:

- Prometheus connectivity issues
- Invalid SLI queries
- Missing metrics

**Resolution**:

```bash
# Check Prometheus connectivity
curl http://prometheus:9090/api/v1/query?query=up

# Verify SLI metrics exist
curl "http://prometheus:9090/api/v1/query?query=voicehive_requests_total"

# Check SLO monitor logs
kubectl logs -f deployment/voicehive-orchestrator | grep slo_monitor
```

#### 2. False Positive Burn Rate Alerts

**Symptoms**: Burn rate alerts during normal operation

**Causes**:

- Incorrect burn rate thresholds
- Seasonal traffic patterns
- Deployment-related temporary spikes

**Resolution**:

1. Review burn rate thresholds in SLO configuration
2. Adjust thresholds based on historical data
3. Implement deployment-aware alerting

#### 3. Runbook Execution Failures

**Symptoms**: Runbooks not executing or failing

**Causes**:

- Cooldown periods active
- Rate limiting triggered
- Step execution failures
- Permission issues

**Resolution**:

```bash
# Check runbook execution history
curl http://voicehive-orchestrator:8000/slo/runbooks

# View execution logs
kubectl logs -f deployment/voicehive-orchestrator | grep runbook

# Manually execute runbook for testing
curl -X POST http://voicehive-orchestrator:8000/slo/runbooks/api_availability_slo_violation/execute
```

### Debugging Commands

#### Check SLO Status

```bash
# Get all SLO status
curl http://voicehive-orchestrator:8000/slo/status | jq

# Get specific SLO
curl "http://voicehive-orchestrator:8000/slo/status?slo_name=api_availability" | jq
```

#### Verify Prometheus Queries

```bash
# Test SLI query directly
curl "http://prometheus:9090/api/v1/query" \
  --data-urlencode 'query=sum(rate(voicehive_requests_total{status!~"5.."}[5m])) / sum(rate(voicehive_requests_total[5m]))'
```

#### Check Recording Rules

```bash
# Verify recording rules are active
curl "http://prometheus:9090/api/v1/query?query=voicehive:api_availability:ratio_rate5m"
```

### Performance Optimization

#### SLO Evaluation Performance

- **Batch Queries**: Group related SLI queries
- **Recording Rules**: Pre-compute complex queries
- **Caching**: Cache SLO evaluation results
- **Parallel Execution**: Evaluate SLOs concurrently

#### Alert Noise Reduction

- **Smart Grouping**: Group related alerts
- **Inhibition Rules**: Suppress redundant alerts
- **Adaptive Thresholds**: Adjust based on historical patterns
- **Maintenance Windows**: Suppress alerts during deployments

## Best Practices

### SLO Definition

1. **Start Simple**: Begin with basic availability and latency SLOs
2. **User-Centric**: Focus on user-visible metrics
3. **Achievable Targets**: Set realistic targets based on historical data
4. **Regular Review**: Review and adjust SLOs quarterly

### Error Budget Management

1. **Proactive Monitoring**: Monitor burn rates, not just SLO compliance
2. **Deployment Discipline**: Respect error budget constraints
3. **Incident Learning**: Use SLO violations to improve reliability
4. **Team Alignment**: Ensure all teams understand error budget impact

### Alerting Strategy

1. **Actionable Alerts**: Every alert should require human action
2. **Clear Runbooks**: Provide clear response procedures
3. **Escalation Paths**: Define clear escalation for unresolved issues
4. **Regular Testing**: Test alert routing and runbook procedures

### Continuous Improvement

1. **Post-Incident Reviews**: Analyze SLO violations after incidents
2. **Trend Analysis**: Look for patterns in burn rate data
3. **Capacity Planning**: Use SLO data for capacity decisions
4. **Tool Evolution**: Continuously improve monitoring tools and processes

## References

- [Google SRE Book - Service Level Objectives](https://sre.google/sre-book/service-level-objectives/)
- [Prometheus Recording Rules](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/)
- [Grafana SLO Dashboards](https://grafana.com/docs/grafana/latest/dashboards/)
- [VoiceHive Architecture Documentation](../architecture/system-architecture.md)
- [VoiceHive Incident Response Procedures](../security/incident-response-procedures.md)
