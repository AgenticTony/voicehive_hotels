# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Must Follow Rules

- Always Use SOLID Principles
- Always Use Async/Await Patterns.
- Always Check Official Documentation first before starting a task using the MCP tools provided.
- Always check i file does not already exist before creating a new file
- Always create a new file in the correct folder accordind to the SOLID and project principles.
- Always use the correct folder structure for the project.
- Always use the correct file name for the project.

## Architecture Overview

VoiceHive Hotels is an **enterprise-grade conversational AI platform** for hospitality built as a **microservices architecture** with production-ready security, monitoring, and compliance.

### Core Service Structure

```
services/
├── orchestrator/          # Main AI orchestration service (FastAPI)
├── media/livekit-agent/   # WebRTC/SIP media handling
├── asr/granary-proxy/     # Speech recognition (25 EU languages)
└── tts/                   # Text-to-speech routing

connectors/                # PMS integration layer (80/20 pattern)
├── adapters/              # Vendor-specific implementations
├── contracts.py           # Universal PMS interface
└── factory.py             # Dynamic connector selection
```

The **orchestrator service** is the brain - it coordinates call flows, manages AI interactions, handles authentication, and integrates with PMS systems through the **connectors SDK**.

### Key Patterns

- **80/20 Connector Pattern**: Shared interface with vendor-specific adapters
- **Circuit Breaker Protection**: All external services protected with failover
- **Multi-tenant Architecture**: Hotel-scoped data isolation with row-level security
- **Async-First Design**: Full asyncio with proper typing and Pydantic validation

## Development Commands

### Environment Setup

```bash
# Initial setup
make setup-dev              # Install deps, pre-commit hooks, create .env
make up                     # Start local stack (PostgreSQL, Redis, Vault, Grafana)

# Service URLs after `make up`:
# - Orchestrator: http://localhost:8080
# - Grafana: http://localhost:3000
# - Prometheus: http://localhost:9090
```

### Testing Commands

```bash
# Run all tests (type checking, linting, security, unit tests)
make test

# Test specific components
make test-connectors                    # All connector tests
make test-connector VENDOR=apaleo      # Specific PMS connector

# Load testing
make load-test CALLS=100               # Concurrent call simulation

# Single test file
pytest services/orchestrator/tests/test_mfa_service.py -v

# Integration tests with 80% coverage requirement
pytest services/orchestrator/tests/integration/ -v
```

### PMS Connector Development

```bash
# Generate new connector scaffold
make new-connector VENDOR=mews

# Validate connector implementation
make validate-connector VENDOR=mews

# Run golden contract tests (universal compliance)
pytest connectors/tests/golden_contract/test_base_contract.py -v
```

### Deployment & Monitoring

```bash
# Deploy to environments
make deploy ENV=staging
make deploy ENV=production

# Monitor deployment health
make monitor ENV=production

# Database operations
make db-migrate                        # Run Alembic migrations
make db-backup ENV=production          # Backup database
```

## Configuration Architecture

### Three-Tier Configuration System

1. **Environment Variables** (highest priority)
2. **HashiCorp Vault** (secrets management with auto-rotation)
3. **Application defaults** (in `services/orchestrator/config.py`)

### Key Configuration Files

- `services/orchestrator/config.py` - Main configuration schema with Pydantic validation
- `.env.example` - Environment variable template
- `infra/k8s/overlays/*/kustomization.yaml` - Kubernetes environment configs
- `pytest.ini` - Test configuration with coverage requirements

### Configuration Features

- **Immutable Configuration**: All changes tracked with hashes and audit logs
- **Strict Validation**: Pydantic models with GDPR compliance validators
- **Zero Production Defaults**: All secrets must come from Vault
- **Drift Detection**: Configuration changes monitored and alerted

## Database & Models

### Core Database Models

Located in `services/orchestrator/database/models.py`:

- **User Management**: Users, Roles, Sessions with MFA support
- **Call Management**: Calls, Recordings, Transcripts with full audit trail
- **Multi-tenant**: Hotels, Tenant isolation with row-level security
- **PMS Integration**: Reservations, Guest profiles, Sync state
- **Compliance**: Audit logs, PII detection, Consent records

### Database Operations

- **Connection Pooling**: asyncpg with PgBouncer configuration
- **Migrations**: Alembic-based with automated backup verification
- **Backup Strategy**: Daily full + hourly incremental with 30-day point-in-time recovery
- **Query Optimization**: Automatic index recommendations and slow query analysis

## Security Architecture

### Multi-Layer Security

1. **Security Headers Middleware** - HSTS, CSP, X-Frame-Options
2. **Input Validation Middleware** - Request sanitization and validation
3. **Authentication Middleware** - JWT token validation with Redis session store
4. **MFA Middleware** - TOTP-based multi-factor authentication
5. **Authorization** - Role-based access control with hotel-scoped permissions

### Key Security Components

- **HashiCorp Vault Integration**: All secrets with automated rotation
- **PII Redaction**: Automatic detection and redaction in logs/storage
- **Path Validation**: Comprehensive protection against path traversal attacks
- **Circuit Breakers**: Automated failure detection across all external services
- **Audit Logging**: Immutable audit trail for all security events

### Critical Security Files

- `services/orchestrator/auth/mfa_service.py` - TOTP implementation
- `services/orchestrator/security/path_validator.py` - File path security
- `services/orchestrator/auth/jwt_service.py` - JWT token management
- `services/orchestrator/enhanced_pii_redactor.py` - PII detection/redaction

## Testing Strategy

### Multi-Tier Test Coverage

1. **Unit Tests** (45% threshold): Fast feedback for critical logic
2. **Integration Tests** (80% threshold): End-to-end workflow validation
3. **Golden Contract Tests**: Universal PMS adapter compliance
4. **Load Tests**: Concurrent call simulation and performance validation
5. **Security Tests**: Penetration testing and vulnerability assessment

### Test Organization

```
services/orchestrator/tests/
├── test_*.py                  # Unit tests (38 files)
├── integration/               # E2E tests with 80% coverage requirement
├── load_testing/              # Performance and scaling tests
└── conftest.py                # Shared fixtures and test configuration

connectors/tests/
├── golden_contract/           # Universal adapter compliance tests
├── test_apaleo_*.py          # Vendor-specific integration tests
└── fixtures.py               # Mock data factories
```

### Test Execution Patterns

- **Async Testing**: pytest-asyncio with proper async fixture management
- **Mock Strategy**: AsyncMock for external services, real databases for integration
- **Coverage Gates**: 45% unit tests (fast feedback), 80% integration (workflow coverage)
- **Contract Testing**: All PMS adapters must pass identical behavior tests

## Monitoring & Observability

### Observability Stack

- **Metrics**: Prometheus with custom business KPIs and SLI/SLO monitoring
- **Dashboards**: Grafana with enterprise dashboards for business and system metrics
- **Tracing**: OpenTelemetry distributed tracing across all services
- **Logging**: Structured logging with automatic PII redaction and audit trails
- **Alerting**: Multi-channel alerting (Slack, PagerDuty, Email) with escalation policies

### Key Monitoring Files

- `services/orchestrator/monitoring/prometheus_client.py` - Real Prometheus metrics
- `services/orchestrator/business_metrics.py` - Business KPI tracking
- `services/orchestrator/enhanced_alerting.py` - Advanced alerting system
- `services/orchestrator/dashboard_config.py` - Grafana dashboard configurations

### Business Metrics Tracked

- **Call Success Rate**: Real-time call completion and quality metrics
- **Revenue Metrics**: Upselling success and booking conversion rates
- **Guest Satisfaction**: Conversation quality and resolution rates
- **System Performance**: Response times, error rates, availability

## PMS Connector SDK

### Universal Interface Pattern

All PMS adapters implement the same interface defined in `connectors/contracts.py`:

```python
class PMSConnector(Protocol):
    async def get_availability() -> AvailabilityGrid
    async def get_rates() -> RateQuote
    async def create_reservation() -> Reservation
    async def modify_reservation() -> Reservation
    async def get_guest_profile() -> GuestProfile
```

### Connector Development Process

1. **Generate Scaffold**: `make new-connector VENDOR=name`
2. **Implement Interface**: Follow the contracts.py interface
3. **Pass Golden Contract**: All connectors must pass universal behavior tests
4. **Add Integration Tests**: Vendor-specific testing with real API mocking
5. **Update Capability Matrix**: Document supported features

### Current PMS Support

- **Apaleo**: ✅ Full implementation with OAuth2 and circuit breaker protection
- **Mews**: 📅 Sprint 2 planned
- **Oracle OPERA**: 📅 Sprint 2 planned
- **Cloudbeds**: 📅 Sprint 3 planned

## Multi-Tenant Architecture

### Tenant Isolation Strategy

- **Row-Level Security**: PostgreSQL policies ensure data isolation
- **Tenant-Scoped Caching**: Redis keys prefixed with hotel_id
- **Hotel Chain Management**: Hierarchical organization with shared configurations
- **User Access Control**: Users can access multiple hotels with role-based permissions

### Key Multi-Tenant Files

- `services/orchestrator/hotel_chain_manager.py` - Multi-hotel management
- `services/orchestrator/tenant_cache_service.py` - Tenant-scoped caching
- `services/orchestrator/database/tenant_isolation_schema.sql` - Database isolation

## Compliance & Data Protection

### GDPR Implementation

- **Data Protection Impact Assessment**: Complete GDPR compliance framework
- **Automated PII Redaction**: Real-time detection and redaction in all data flows
- **Right to Erasure**: Automated user data deletion with audit trails
- **Consent Management**: Explicit consent tracking with automatic expiration
- **Data Retention**: Automated enforcement of retention policies

### Compliance Files

- `docs/compliance/gdpr-dpia.md` - Data Protection Impact Assessment
- `services/orchestrator/enhanced_pii_redactor.py` - PII detection/redaction
- `services/orchestrator/data_retention_enforcer.py` - Automated data lifecycle
- `services/orchestrator/audit_logging.py` - Immutable audit trails

## Common Development Workflows

### Adding a New Feature

1. **Create feature branch**: `git checkout -b feature/your-feature`
2. **Update configuration**: Modify `config.py` if new settings needed
3. **Implement with tests**: Write tests first, then implementation
4. **Security review**: Check for PII exposure, input validation, authorization
5. **Integration tests**: Add end-to-end workflow tests
6. **Documentation**: Update API docs and runbooks

### Debugging Production Issues

1. **Check monitoring**: Grafana dashboards and Prometheus alerts
2. **Review audit logs**: Structured logs with correlation IDs
3. **Trace requests**: OpenTelemetry distributed tracing
4. **Check circuit breakers**: Service health and failure patterns
5. **Verify configuration**: Immutable config with drift detection

### Emergency Procedures

- **Secret Rotation**: `./services/orchestrator/emergency_rotation_cli.py`
- **Rollback Deployment**: `./scripts/deployment/rollback-procedures.sh --emergency`
- **Incident Response**: Follow documented procedures in `docs/security/incident-response-procedures.md`

## Important Notes

- **Always use async/await patterns** - This is an async-first codebase
- **Tenant context required** - All operations must include hotel_id for data isolation
- **Circuit breaker protection** - Wrap all external service calls with circuit breakers
- **Structured logging** - Use the safe logger adapter to prevent PII exposure
- **Type safety** - Full mypy --strict compliance required
- **Test coverage** - 45% unit tests, 80% integration tests required
- **Security first** - All user input validated, all secrets from Vault, all operations audited

The codebase follows enterprise patterns with production-grade security, monitoring, and operational capabilities. Focus on maintaining these standards when making changes.
