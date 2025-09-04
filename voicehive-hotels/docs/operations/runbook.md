# VoiceHive Hotels Operational Runbook

## On-Call Guide

### Severity Levels

| Level | Response Time | Examples |
|-------|---------------|----------|
| P0 - Critical | 15 min | Complete outage, data breach |
| P1 - High | 1 hour | Major functionality broken |
| P2 - Medium | 4 hours | Degraded performance |
| P3 - Low | 24 hours | Minor issues |

### Escalation Path

1. On-call engineer
2. Team lead
3. Platform architect
4. CTO

## Common Issues and Solutions

### 1. High Call Failure Rate

**Symptoms:**
- Call success rate < 95%
- Increased "call.failed" events
- Customer complaints

**Diagnosis:**
```bash
# Check orchestrator logs
kubectl logs -n voicehive -l app=orchestrator --tail=1000 | grep ERROR

# Check LiveKit connectivity
kubectl exec -it deployment/media-agent -n voicehive -- ping livekit-sfu

# Check Twilio status
curl https://status.twilio.com/api/v2/status.json
```

**Resolution:**
1. Restart media agents: `kubectl rollout restart deployment/media-agent -n voicehive`
2. Check Twilio SIP trunk configuration
3. Verify LiveKit region settings
4. Scale up if needed: `kubectl scale deployment/orchestrator --replicas=5`

### 2. ASR/TTS Latency Issues

**Symptoms:**
- P95 latency > 500ms
- Slow speech recognition
- Delayed TTS responses

**Diagnosis:**
```bash
# Check Riva GPU utilization
kubectl exec -it deployment/riva-server -n voicehive -- nvidia-smi

# Check TTS router metrics
curl http://tts-router:9090/metrics | grep ttfb

# Check network latency
kubectl exec -it deployment/orchestrator -n voicehive -- \
  traceroute elevenlabs.io
```

**Resolution:**
1. Scale GPU nodes if utilization > 80%
2. Enable TTS caching: `kubectl set env deployment/tts-router CACHE_ENABLED=true`
3. Switch to regional TTS endpoint
4. Pre-warm models: `make warm-models`

### 3. PMS Connection Failures

**Symptoms:**
- "PMS unavailable" errors
- Reservation lookups failing
- Timeout errors

**Diagnosis:**
```bash
# Check specific connector
kubectl logs -n voicehive -l app=connectors,vendor=apaleo --tail=500

# Test PMS API directly
kubectl exec -it deployment/connectors -n voicehive -- \
  curl -H "Authorization: Bearer $TOKEN" https://api.apaleo.com/health

# Check rate limits
kubectl exec -it deployment/connectors -n voicehive -- \
  redis-cli GET "ratelimit:apaleo"
```

**Resolution:**
1. Check PMS vendor status page
2. Rotate API credentials if authentication failing
3. Clear rate limit: `redis-cli DEL "ratelimit:apaleo"`
4. Enable circuit breaker: `kubectl set env deployment/connectors CIRCUIT_BREAKER_ENABLED=true`

### 4. Memory/CPU Spikes

**Symptoms:**
- Pods getting OOMKilled
- High CPU alerts
- Slow response times

**Diagnosis:**
```bash
# Check resource usage
kubectl top pods -n voicehive
kubectl top nodes

# Get memory profile
kubectl exec -it <pod> -n voicehive -- \
  python -m memory_profiler app.py

# Check for memory leaks
kubectl logs <pod> -n voicehive | grep "memory"
```

**Resolution:**
1. Increase resource limits if needed
2. Enable memory profiling
3. Restart affected pods
4. Review recent code changes

### 5. Database Issues

**Symptoms:**
- Slow queries
- Connection pool exhausted
- Lock timeouts

**Diagnosis:**
```bash
# Check slow queries
psql -h db.voicehive-hotels.eu -U postgres -c \
  "SELECT query, mean_time FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"

# Check connections
psql -h db.voicehive-hotels.eu -U postgres -c \
  "SELECT count(*) FROM pg_stat_activity;"

# Check locks
psql -h db.voicehive-hotels.eu -U postgres -c \
  "SELECT * FROM pg_locks WHERE NOT granted;"
```

**Resolution:**
1. Kill long-running queries
2. Increase connection pool size
3. Run VACUUM ANALYZE
4. Scale read replicas

### 6. GDPR Compliance Alerts

**Symptoms:**
- Data retention policy violations
- Non-EU region access detected
- PII found in logs

**Diagnosis:**
```bash
# Check retention jobs
kubectl logs -n voicehive job/data-retention-cleanup

# Scan for PII in logs
make pii-scan

# Check region compliance
kubectl logs -n voicehive -l app=orchestrator | grep "region_violation"
```

**Resolution:**
1. Run manual cleanup: `make gdpr-cleanup`
2. Update retention policies
3. Fix PII logging issues
4. Block non-EU traffic at WAF level

## Monitoring and Alerts

### Key Dashboards

1. **System Overview**: https://grafana.voicehive-hotels.eu/d/system
2. **Call Analytics**: https://grafana.voicehive-hotels.eu/d/calls  
3. **PMS Integration**: https://grafana.voicehive-hotels.eu/d/pms
4. **GDPR Compliance**: https://grafana.voicehive-hotels.eu/d/gdpr

### Critical Alerts

| Alert | Threshold | Action |
|-------|-----------|--------|
| High Error Rate | > 1% | Check logs, scale up |
| Low Call Success | < 95% | Check media services |
| PMS Timeout | > 5% | Check connector health |
| High Latency | P95 > 500ms | Scale ASR/TTS |
| Low Disk Space | < 20% | Clean up logs/recordings |

## Maintenance Procedures

### Daily Tasks
- Review error logs
- Check backup status
- Monitor resource usage
- Review security alerts

### Weekly Tasks
- Update dependencies
- Run security scans
- Review performance metrics
- Test disaster recovery

### Monthly Tasks
- Rotate API keys
- Update SSL certificates
- Review cost optimization
- Conduct security audit

## Emergency Contacts

| Role | Name | Phone | Email |
|------|------|-------|-------|
| On-Call Lead | [Name] | +44 XXX | oncall@voicehive |
| Platform Architect | [Name] | +44 XXX | platform@voicehive |
| Security Lead | [Name] | +44 XXX | security@voicehive |
| CTO | [Name] | +44 XXX | cto@voicehive |

### External Vendors

| Service | Support | Phone | Priority |
|---------|---------|-------|----------|
| AWS | Enterprise | +1-XXX | P0/P1 |
| Twilio | Premier | +1-XXX | P0/P1 |
| LiveKit | Enterprise | Email | P1/P2 |
| ElevenLabs | Business | Email | P2/P3 |

## Disaster Recovery

### RTO/RPO Targets
- **RTO**: 4 hours (time to restore service)
- **RPO**: 1 hour (maximum data loss)

### DR Procedures
1. Activate DR region (eu-central-1)
2. Restore from latest backup
3. Update DNS to DR endpoints
4. Notify customers of degraded service
5. Begin root cause analysis

---
**Last Updated**: January 2024
**Maintained by**: Platform Team
