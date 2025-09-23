# VoiceHive Hotels Troubleshooting Guide

## Overview

This guide provides step-by-step troubleshooting procedures for common production issues in the VoiceHive Hotels system. Each section includes symptoms, root cause analysis, and resolution steps.

## Quick Reference

### Emergency Contacts

- **On-Call Engineer**: +1-555-0123
- **DevOps Team**: devops@voicehive.com
- **Engineering Lead**: eng-lead@voicehive.com
- **Incident Commander**: incident@voicehive.com

### Critical Commands

```bash
# Check system health
kubectl get pods -n voicehive
curl https://api.voicehive.com/health

# View logs
kubectl logs -f deployment/orchestrator -n voicehive

# Scale services
kubectl scale deployment/orchestrator --replicas=5 -n voicehive

# Emergency rollback
helm rollback voicehive -n voicehive
```

## Authentication Issues

### Issue: Users Cannot Login (401 Unauthorized)

**Symptoms:**

- Login requests return 401 status
- Error message: "Invalid credentials" or "Authentication failed"
- Multiple users affected

**Diagnosis Steps:**

1. **Check Authentication Service Health**

   ```bash
   kubectl get pods -n voicehive -l app=orchestrator
   kubectl logs deployment/orchestrator -n voicehive | grep -i auth
   ```

2. **Verify Database Connectivity**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     python -c "import asyncpg; print('DB test')"
   ```

3. **Check JWT Configuration**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     python -c "from jwt_service import JWTService; print('JWT config OK')"
   ```

**Common Root Causes:**

1. **Database Connection Issues**

   ```bash
   # Check database pod
   kubectl get pods -n voicehive -l app=postgresql

   # Test connection
   kubectl exec -n voicehive deployment/orchestrator -- \
     pg_isready -h postgresql.voicehive.com
   ```

2. **JWT Secret Rotation**

   ```bash
   # Check JWT secret
   kubectl get secret jwt-secret -n voicehive -o yaml

   # Verify secret is not corrupted
   kubectl get secret jwt-secret -n voicehive -o jsonpath='{.data.secret}' | base64 -d
   ```

3. **Redis Session Store Issues**

   ```bash
   # Check Redis connectivity
   kubectl exec -n voicehive deployment/orchestrator -- \
     redis-cli -h redis.voicehive.com ping

   # Check Redis memory usage
   kubectl exec -n voicehive deployment/orchestrator -- \
     redis-cli -h redis.voicehive.com info memory
   ```

**Resolution Steps:**

1. **Restart Authentication Service**

   ```bash
   kubectl rollout restart deployment/orchestrator -n voicehive
   kubectl rollout status deployment/orchestrator -n voicehive
   ```

2. **Clear Redis Sessions (if corrupted)**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     redis-cli -h redis.voicehive.com FLUSHDB
   ```

3. **Regenerate JWT Secret (last resort)**

   ```bash
   # Generate new secret
   NEW_SECRET=$(openssl rand -base64 32)
   kubectl create secret generic jwt-secret \
     --from-literal=secret=$NEW_SECRET \
     --dry-run=client -o yaml | kubectl apply -f -

   # Restart services
   kubectl rollout restart deployment/orchestrator -n voicehive
   ```

### Issue: API Key Authentication Failing

**Symptoms:**

- API requests with valid keys return 401
- Webhook deliveries failing
- Service-to-service auth errors

**Diagnosis Steps:**

1. **Check Vault Connectivity**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     vault status
   ```

2. **Verify API Key in Vault**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     vault kv get secret/api-keys/vh_live_1234567890abcdef
   ```

**Resolution Steps:**

1. **Restart Vault Connection**

   ```bash
   kubectl rollout restart deployment/orchestrator -n voicehive
   ```

2. **Re-authenticate with Vault**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     vault auth -method=kubernetes role=voicehive-orchestrator
   ```

## Rate Limiting Issues

### Issue: Legitimate Traffic Being Rate Limited

**Symptoms:**

- 429 "Too Many Requests" responses
- Retry-After headers in responses
- Customer complaints about service unavailability

**Diagnosis Steps:**

1. **Check Current Rate Limit Usage**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     redis-cli -h redis.voicehive.com KEYS "rate_limit:*"

   kubectl exec -n voicehive deployment/orchestrator -- \
     redis-cli -h redis.voicehive.com GET "rate_limit:user:123:per_minute"
   ```

2. **Review Rate Limit Configuration**

   ```bash
   kubectl get configmap rate-limit-config -n voicehive -o yaml
   ```

3. **Check for DDoS or Abuse**
   ```bash
   # Check top IPs by request count
   kubectl logs deployment/orchestrator -n voicehive | \
     grep "rate_limit_exceeded" | \
     awk '{print $5}' | sort | uniq -c | sort -nr | head -10
   ```

**Resolution Steps:**

1. **Temporarily Increase Rate Limits**

   ```bash
   kubectl patch configmap rate-limit-config -n voicehive \
     --type merge -p '{"data":{"requests_per_minute":"120"}}'

   kubectl rollout restart deployment/orchestrator -n voicehive
   ```

2. **Whitelist Specific IPs/Users**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     redis-cli -h redis.voicehive.com SET "rate_limit:whitelist:1.2.3.4" "true" EX 3600
   ```

3. **Clear Rate Limit Counters**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     redis-cli -h redis.voicehive.com DEL "rate_limit:user:123:per_minute"
   ```

## Circuit Breaker Issues

### Issue: Circuit Breakers Stuck Open

**Symptoms:**

- 503 "Service Unavailable" responses
- External service calls failing
- Circuit breaker metrics showing "open" state

**Diagnosis Steps:**

1. **Check Circuit Breaker Status**

   ```bash
   curl -s https://api.voicehive.com/metrics | grep circuit_breaker_state
   ```

2. **Check External Service Health**

   ```bash
   # Test PMS connector
   curl -f https://api.apaleo.com/health

   # Test TTS service
   curl -f https://tts.voicehive.com/health
   ```

3. **Review Circuit Breaker Logs**
   ```bash
   kubectl logs deployment/orchestrator -n voicehive | \
     grep -i "circuit.*breaker"
   ```

**Resolution Steps:**

1. **Manually Reset Circuit Breaker**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     python -c "
   from circuit_breaker import CircuitBreakerManager
   manager = CircuitBreakerManager()
   manager.reset_circuit_breaker('pms_connector')
   "
   ```

2. **Adjust Circuit Breaker Thresholds**

   ```bash
   kubectl patch configmap circuit-breaker-config -n voicehive \
     --type merge -p '{"data":{"failure_threshold":"10","timeout":"30"}}'
   ```

3. **Enable Fallback Mode**
   ```bash
   kubectl set env deployment/orchestrator FALLBACK_MODE=true -n voicehive
   ```

## Performance Issues

### Issue: High Response Times

**Symptoms:**

- API response times > 5 seconds
- Timeout errors
- Customer complaints about slow service

**Diagnosis Steps:**

1. **Check Resource Usage**

   ```bash
   kubectl top pods -n voicehive
   kubectl top nodes
   ```

2. **Analyze Slow Queries**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     psql $DATABASE_URL -c "
   SELECT query, mean_time, calls
   FROM pg_stat_statements
   ORDER BY mean_time DESC
   LIMIT 10;"
   ```

3. **Check Connection Pool Status**
   ```bash
   kubectl logs deployment/orchestrator -n voicehive | \
     grep -i "connection.*pool"
   ```

**Resolution Steps:**

1. **Scale Up Services**

   ```bash
   kubectl scale deployment/orchestrator --replicas=10 -n voicehive
   kubectl scale deployment/livekit-agent --replicas=5 -n voicehive
   ```

2. **Increase Connection Pool Size**

   ```bash
   kubectl patch configmap database-config -n voicehive \
     --type merge -p '{"data":{"max_connections":"50"}}'

   kubectl rollout restart deployment/orchestrator -n voicehive
   ```

3. **Enable Caching**
   ```bash
   kubectl set env deployment/orchestrator CACHE_ENABLED=true -n voicehive
   kubectl set env deployment/orchestrator CACHE_TTL=300 -n voicehive
   ```

### Issue: Memory Leaks

**Symptoms:**

- Pods being OOMKilled
- Memory usage continuously increasing
- Pod restarts due to memory limits

**Diagnosis Steps:**

1. **Check Memory Usage Trends**

   ```bash
   kubectl top pods -n voicehive --sort-by=memory
   ```

2. **Analyze Memory Patterns**

   ```bash
   # Check for memory leaks in logs
   kubectl logs deployment/orchestrator -n voicehive | \
     grep -i "memory\|oom\|killed"
   ```

3. **Profile Memory Usage**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     python -c "
   import psutil
   process = psutil.Process()
   print(f'Memory: {process.memory_info().rss / 1024 / 1024:.2f} MB')
   "
   ```

**Resolution Steps:**

1. **Increase Memory Limits**

   ```bash
   kubectl patch deployment orchestrator -n voicehive \
     --type='json' \
     -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "2Gi"}]'
   ```

2. **Enable Memory Optimization**

   ```bash
   kubectl set env deployment/orchestrator MEMORY_OPTIMIZATION=true -n voicehive
   kubectl set env deployment/orchestrator GC_THRESHOLD=100 -n voicehive
   ```

3. **Restart Affected Pods**
   ```bash
   kubectl delete pods -n voicehive -l app=orchestrator
   ```

## Database Issues

### Issue: Database Connection Failures

**Symptoms:**

- "Connection refused" errors
- Database timeout errors
- 500 Internal Server Error responses

**Diagnosis Steps:**

1. **Check Database Pod Status**

   ```bash
   kubectl get pods -n voicehive -l app=postgresql
   kubectl describe pod postgresql-0 -n voicehive
   ```

2. **Test Database Connectivity**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     pg_isready -h postgresql.voicehive.com -p 5432
   ```

3. **Check Database Logs**
   ```bash
   kubectl logs postgresql-0 -n voicehive | tail -50
   ```

**Resolution Steps:**

1. **Restart Database Connection Pool**

   ```bash
   kubectl rollout restart deployment/orchestrator -n voicehive
   ```

2. **Scale Down Load Temporarily**

   ```bash
   kubectl scale deployment/orchestrator --replicas=1 -n voicehive
   ```

3. **Restart Database (if necessary)**
   ```bash
   kubectl delete pod postgresql-0 -n voicehive
   kubectl wait --for=condition=ready pod/postgresql-0 -n voicehive --timeout=300s
   ```

### Issue: Database Performance Problems

**Symptoms:**

- Slow query responses
- High database CPU usage
- Connection pool exhaustion

**Diagnosis Steps:**

1. **Check Active Connections**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     psql $DATABASE_URL -c "
   SELECT count(*) as active_connections
   FROM pg_stat_activity
   WHERE state = 'active';"
   ```

2. **Identify Slow Queries**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     psql $DATABASE_URL -c "
   SELECT query, state, query_start
   FROM pg_stat_activity
   WHERE state != 'idle'
   ORDER BY query_start;"
   ```

**Resolution Steps:**

1. **Kill Long-Running Queries**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     psql $DATABASE_URL -c "
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state != 'idle'
   AND query_start < now() - interval '5 minutes';"
   ```

2. **Increase Connection Pool**
   ```bash
   kubectl patch configmap database-config -n voicehive \
     --type merge -p '{"data":{"max_connections":"100"}}'
   ```

## External Service Issues

### Issue: PMS Connector Failures

**Symptoms:**

- Hotel data not syncing
- Guest information unavailable
- PMS webhook failures

**Diagnosis Steps:**

1. **Check PMS Service Health**

   ```bash
   curl -f https://api.apaleo.com/health
   ```

2. **Test PMS Authentication**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     python -c "
   from connectors.adapters.apaleo import ApaleoConnector
   connector = ApaleoConnector()
   print(connector.test_connection())
   "
   ```

3. **Check PMS Credentials in Vault**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     vault kv get secret/pms/apaleo/credentials
   ```

**Resolution Steps:**

1. **Refresh PMS Credentials**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     python -c "
   from connectors.adapters.apaleo import ApaleoConnector
   connector = ApaleoConnector()
   connector.refresh_token()
   "
   ```

2. **Enable PMS Fallback Mode**

   ```bash
   kubectl set env deployment/orchestrator PMS_FALLBACK_MODE=true -n voicehive
   ```

3. **Restart PMS Connector**
   ```bash
   kubectl rollout restart deployment/orchestrator -n voicehive
   ```

### Issue: LiveKit Connection Problems

**Symptoms:**

- Call setup failures
- Audio quality issues
- WebRTC connection errors

**Diagnosis Steps:**

1. **Check LiveKit Service**

   ```bash
   curl -f https://livekit.voicehive.com/health
   ```

2. **Test LiveKit Token Generation**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     python -c "
   from livekit import AccessToken
   token = AccessToken('api_key', 'secret')
   print('Token generation OK')
   "
   ```

3. **Check Network Connectivity**
   ```bash
   kubectl exec -n voicehive deployment/livekit-agent -- \
     nc -zv livekit.voicehive.com 443
   ```

**Resolution Steps:**

1. **Restart LiveKit Agent**

   ```bash
   kubectl rollout restart deployment/livekit-agent -n voicehive
   ```

2. **Update LiveKit Configuration**
   ```bash
   kubectl patch configmap livekit-config -n voicehive \
     --type merge -p '{"data":{"server_url":"wss://livekit.voicehive.com"}}'
   ```

## Monitoring and Alerting Issues

### Issue: Missing Metrics

**Symptoms:**

- Grafana dashboards showing no data
- Prometheus targets down
- Missing business metrics

**Diagnosis Steps:**

1. **Check Prometheus Targets**

   ```bash
   curl -s https://prometheus.voicehive.com/api/v1/targets | \
     jq '.data.activeTargets[] | select(.health != "up")'
   ```

2. **Verify Metrics Endpoints**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     curl -s http://localhost:8000/metrics | head -20
   ```

**Resolution Steps:**

1. **Restart Prometheus**

   ```bash
   kubectl rollout restart deployment/prometheus -n monitoring
   ```

2. **Update Service Monitor**
   ```bash
   kubectl apply -f infra/k8s/monitoring/prometheus-config.yaml
   ```

### Issue: Alert Fatigue

**Symptoms:**

- Too many false positive alerts
- Important alerts being ignored
- Alert storm conditions

**Resolution Steps:**

1. **Adjust Alert Thresholds**

   ```bash
   kubectl patch configmap alert-rules -n monitoring \
     --type merge -p '{"data":{"high_error_rate":"0.05"}}'
   ```

2. **Enable Alert Grouping**
   ```bash
   kubectl patch configmap alertmanager-config -n monitoring \
     --type merge -p '{"data":{"group_wait":"30s"}}'
   ```

## Security Issues

### Issue: Suspicious Activity Detected

**Symptoms:**

- Unusual traffic patterns
- Failed authentication attempts
- Potential security breach

**Immediate Actions:**

1. **Enable Enhanced Logging**

   ```bash
   kubectl set env deployment/orchestrator LOG_LEVEL=DEBUG -n voicehive
   kubectl set env deployment/orchestrator AUDIT_LOGGING=true -n voicehive
   ```

2. **Block Suspicious IPs**

   ```bash
   kubectl patch configmap security-config -n voicehive \
     --type merge -p '{"data":{"blocked_ips":"1.2.3.4,5.6.7.8"}}'
   ```

3. **Rotate Secrets**

   ```bash
   # Rotate JWT secret
   NEW_SECRET=$(openssl rand -base64 32)
   kubectl create secret generic jwt-secret \
     --from-literal=secret=$NEW_SECRET \
     --dry-run=client -o yaml | kubectl apply -f -

   # Rotate API keys
   kubectl exec -n voicehive deployment/orchestrator -- \
     python scripts/rotate_api_keys.py
   ```

## Network Issues

### Issue: Service Discovery Problems

**Symptoms:**

- Services cannot reach each other
- DNS resolution failures
- Connection timeouts between services

**Diagnosis Steps:**

1. **Test DNS Resolution**

   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     nslookup redis.voicehive.com
   ```

2. **Check Service Endpoints**

   ```bash
   kubectl get endpoints -n voicehive
   ```

3. **Test Network Connectivity**
   ```bash
   kubectl exec -n voicehive deployment/orchestrator -- \
     nc -zv postgresql.voicehive.com 5432
   ```

**Resolution Steps:**

1. **Restart CoreDNS**

   ```bash
   kubectl rollout restart deployment/coredns -n kube-system
   ```

2. **Update Service Configuration**
   ```bash
   kubectl apply -f infra/k8s/base/
   ```

## Disaster Recovery

### Issue: Complete System Failure

**Emergency Procedures:**

1. **Activate Disaster Recovery Site**

   ```bash
   # Switch DNS to DR site
   aws route53 change-resource-record-sets \
     --hosted-zone-id Z123456789 \
     --change-batch file://dr-dns-change.json
   ```

2. **Restore from Backup**

   ```bash
   # Restore database
   kubectl exec -i -n voicehive deployment/postgresql -- \
     psql $DATABASE_URL < latest-backup.sql

   # Restore Redis data
   kubectl exec -n voicehive deployment/redis -- \
     redis-cli --rdb /data/dump.rdb
   ```

3. **Validate DR Environment**

   ```bash
   # Run health checks
   curl -f https://dr.voicehive.com/health

   # Test critical functionality
   python tests/smoke/test_critical_path.py
   ```

## Escalation Procedures

### Level 1: Self-Service Resolution

- Use this troubleshooting guide
- Check monitoring dashboards
- Review recent changes

### Level 2: Engineering Team

- Contact on-call engineer: +1-555-0123
- Provide correlation IDs and error messages
- Include steps already attempted

### Level 3: Incident Commander

- For customer-impacting issues
- Multiple service failures
- Security incidents

### Level 4: Executive Escalation

- For extended outages (> 4 hours)
- Data breach incidents
- Regulatory compliance issues

## Prevention Strategies

### Proactive Monitoring

1. **Set Up Synthetic Monitoring**

   ```bash
   # Deploy synthetic tests
   kubectl apply -f infra/k8s/monitoring/synthetic-tests.yaml
   ```

2. **Implement Chaos Engineering**

   ```bash
   # Run chaos experiments
   kubectl apply -f infra/k8s/chaos/network-partition.yaml
   ```

3. **Regular Health Checks**
   ```bash
   # Automated health validation
   kubectl create cronjob health-check \
     --image=voicehive/health-checker \
     --schedule="*/5 * * * *"
   ```

### Capacity Planning

1. **Monitor Resource Trends**

   ```bash
   # CPU trend analysis
   curl -s 'https://prometheus.voicehive.com/api/v1/query_range?query=rate(container_cpu_usage_seconds_total[5m])&start=1642723200&end=1642809600&step=3600'
   ```

2. **Set Up Auto-scaling**
   ```bash
   kubectl apply -f infra/k8s/base/hpa.yaml
   ```

## Documentation Updates

After resolving issues:

1. **Update Runbooks**

   - Document new procedures
   - Update contact information
   - Add lessons learned

2. **Update Monitoring**

   - Add new alerts for detected issues
   - Improve dashboard visibility
   - Update alert thresholds

3. **Share Knowledge**
   - Conduct post-incident reviews
   - Update team documentation
   - Train team members on new procedures

## Tools and Resources

### Monitoring Tools

- **Grafana**: https://grafana.voicehive.com
- **Prometheus**: https://prometheus.voicehive.com
- **Jaeger**: https://jaeger.voicehive.com
- **Kibana**: https://kibana.voicehive.com

### Management Tools

- **Kubernetes Dashboard**: https://k8s.voicehive.com
- **ArgoCD**: https://argocd.voicehive.com
- **Vault UI**: https://vault.voicehive.com

### Communication

- **Status Page**: https://status.voicehive.com
- **Slack**: #voicehive-ops
- **PagerDuty**: https://voicehive.pagerduty.com
