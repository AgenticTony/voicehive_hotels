# VoiceHive Hotels Service Level Agreement (SLA)

**Effective Date**: January 1, 2024  
**Version**: 1.0

## Service Availability

### Uptime Commitment

| Service Tier | Monthly Uptime SLA | Downtime Allowed |
|--------------|-------------------|------------------|
| Enterprise | 99.95% | 21.6 minutes |
| Business | 99.9% | 43.2 minutes |
| Standard | 99.5% | 3.6 hours |

### Measurement Period

- Calculated monthly
- Excludes scheduled maintenance
- Measured from EU regions only

### Service Credits

| Monthly Uptime | Service Credit |
|----------------|----------------|
| < 99.95% but ≥ 99.0% | 10% |
| < 99.0% but ≥ 95.0% | 25% |
| < 95.0% | 50% |

## Performance Guarantees

### Response Time SLAs

| Metric | Target | Measurement |
|--------|--------|-------------|
| API Response Time | < 200ms | P95 |
| End-to-End Call Latency | < 500ms | P95 |
| ASR First Token | < 100ms | P95 |
| TTS First Byte | < 150ms | P95 |
| PMS API Response | < 250ms | P95 (cached) |

### Capacity SLAs

| Metric | Guarantee |
|--------|-----------|
| Concurrent Calls | 100+ per cluster |
| Calls per Minute | 1000+ |
| API Requests/sec | 100+ |

## Support Response Times

### Severity Levels

| Severity | Definition | Initial Response | Resolution Target |
|----------|------------|------------------|-------------------|
| P0 - Critical | Complete service outage | 15 minutes | 4 hours |
| P1 - High | Major feature unavailable | 1 hour | 8 hours |
| P2 - Medium | Partial feature degradation | 4 hours | 24 hours |
| P3 - Low | Minor issues | 24 hours | 72 hours |

### Support Channels

- **24/7 Hotline**: For P0/P1 issues
- **Email**: For all severities
- **Portal**: Ticket tracking
- **Slack**: Enterprise customers only

## Data Guarantees

### Data Durability

- **Call Recordings**: 99.999999999% (11 9's)
- **Transcripts**: 99.999999999% (11 9's)
- **Metadata**: 99.99%

### Backup & Recovery

| Data Type | Backup Frequency | Retention | Recovery Time |
|-----------|------------------|-----------|---------------|
| Database | Continuous | 30 days | < 1 hour |
| Recordings | Daily | 90 days | < 4 hours |
| Configuration | Hourly | 7 days | < 30 minutes |

### Data Residency

- 100% EU data processing
- No data leaves EU regions
- Certified data centers only

## Security Commitments

### Compliance

- GDPR compliant
- SOC 2 Type II (in progress)
- ISO 27001 (planned)
- PCI DSS Level 1

### Security Measures

| Control | Implementation |
|---------|----------------|
| Encryption at Rest | AES-256-GCM |
| Encryption in Transit | TLS 1.2+ |
| Access Control | MFA required |
| Vulnerability Scanning | Daily |
| Penetration Testing | Quarterly |

## Integration SLAs

### PMS Partner Availability

| Partner | Availability Target | Notes |
|---------|-------------------|--------|
| Apaleo | 99.9% | Excludes partner downtime |
| Mews | 99.9% | Excludes partner downtime |
| Oracle OPERA | 99.5% | Excludes partner downtime |
| Cloudbeds | 99.5% | Excludes partner downtime |
| SiteMinder | 99.0% | Best effort |

### Webhook Delivery

- Delivery guarantee: At least once
- Retry policy: Exponential backoff
- Maximum retries: 5
- Timeout: 30 seconds

## Exclusions

This SLA does not apply to:

1. **Scheduled Maintenance** (notified 7 days in advance)
2. **Emergency Maintenance** (security patches)
3. **Force Majeure Events**
4. **Customer-caused issues**:
   - Misconfiguration
   - Exceeding rate limits
   - Invalid API usage
5. **Third-party service outages**:
   - Twilio
   - Cloud providers
   - PMS systems

## Maintenance Windows

### Scheduled Maintenance

- **Window**: Sundays 02:00-06:00 UTC
- **Frequency**: Monthly
- **Notification**: 7 days advance

### Emergency Maintenance

- **Notification**: As soon as possible
- **Duration**: Minimized
- **Approval**: CTO required

## Claiming Service Credits

1. Submit claim within 30 days
2. Include:
   - Dates and times of unavailability
   - Error logs or screenshots
   - Business impact description
3. Credits applied to next invoice
4. Maximum credit: 50% of monthly fee

## Monitoring & Reporting

### Status Page

- Public: https://status.voicehive-hotels.com
- Real-time system status
- Historical uptime data
- Incident history

### Monthly Reports

Enterprise customers receive:
- Uptime statistics
- Performance metrics
- Incident summary
- SLA compliance report

## Changes to SLA

- 30 days notice for changes
- No degradation of existing commitments
- Customers may terminate if degraded

## Contact Information

### SLA Support

- Email: sla@voicehive-hotels.com
- Phone: +44 20 XXXX XXXX
- Portal: https://support.voicehive-hotels.com

### Escalation

- Level 1: Support Team
- Level 2: Support Manager
- Level 3: VP of Operations
- Level 4: CTO

---

**Agreement**: By using VoiceHive Hotels services, you agree to these SLA terms.

**Last Updated**: January 2024
