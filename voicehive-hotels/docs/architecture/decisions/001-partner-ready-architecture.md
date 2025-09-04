# ADR-001: Partner-Ready Architecture with 80/20 Connector Pattern

**Date**: January 2024  
**Status**: Accepted  
**Context**: VoiceHive Hotels needs to integrate with multiple PMS vendors while maintaining consistent behavior and rapid certification.

## Decision

We will adopt a partner-ready architecture where:
1. 80% of integration code is reusable (contracts, tests, security)
2. 20% is vendor-specific adapters implementing a universal interface
3. All connectors must pass golden contract tests before certification

## Architecture Pattern

```
┌─────────────────────────────────────┐
│         Orchestrator                │
│  (Never knows about PMS vendors)    │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│      PMSConnector Protocol          │  ← 80% Reusable
│   - Standard methods & models       │
│   - Golden contract tests           │
│   - Security/retry/circuit breaker  │
└─────────────────┬───────────────────┘
                  │
     ┌────────────┼────────────┐
     ▼            ▼            ▼
┌─────────┐  ┌─────────┐  ┌─────────┐
│ Apaleo  │  │  Mews   │  │  Opera  │  ← 20% Custom
│ Adapter │  │ Adapter │  │ Adapter │
└─────────┘  └─────────┘  └─────────┘
```

## Key Components

### 1. Universal Contract (`PMSConnector`)
```python
class PMSConnector(Protocol):
    async def get_availability(...) -> AvailabilityGrid
    async def create_reservation(...) -> Reservation
    async def modify_reservation(...) -> Reservation
    # ... standard interface for all PMS operations
```

### 2. Capability Matrix
```yaml
vendors:
  apaleo:
    capabilities:
      availability: true
      modify_reservation: true
      webhooks: true
  mews:
    capabilities:
      availability: true
      modify_reservation: true
      webhooks: limited
```

### 3. Golden Contract Tests
- Same test suite runs against ALL connectors
- Ensures identical behavior from orchestrator's perspective
- New connector MUST pass 100% before certification

### 4. Vendor Adapters
- Implement `PMSConnector` protocol
- Handle vendor-specific:
  - Authentication (OAuth2 vs API key)
  - Field mappings
  - Rate limits
  - Error translations

## Consequences

### Positive
- **Fast Integration**: New PMS in 3-5 days vs 3-4 weeks
- **Consistent Behavior**: Orchestrator code never changes
- **Easy Testing**: One test suite for all vendors
- **Partner Trust**: Can guarantee behavior in contracts
- **Lower Maintenance**: Fix once in base class, all benefit

### Negative
- **Initial Complexity**: More upfront design work
- **Abstraction Overhead**: Some vendor features may not fit
- **Learning Curve**: Engineers must understand the pattern

## Alternatives Considered

### 1. Direct Integration (Rejected)
- **Pro**: Simpler initially
- **Con**: Each PMS integration is bespoke, 3-4 weeks each
- **Con**: Orchestrator becomes littered with if/else vendor logic

### 2. Middleware/ESB Pattern (Rejected)
- **Pro**: Complete abstraction
- **Con**: Another service to maintain
- **Con**: Added latency for real-time voice

### 3. Generated Code from OpenAPI (Rejected)
- **Pro**: Auto-generated from specs
- **Con**: Most hotel PMS lack good OpenAPI specs
- **Con**: Can't handle business logic differences

## Implementation Guidelines

### Adding a New PMS
1. Copy connector template
2. Implement all `PMSConnector` methods
3. Map vendor fields to our domain models
4. Run golden contract tests
5. Add vendor-specific tests for edge cases
6. Update capability matrix
7. Generate partner documentation

### Quality Gates
- [ ] Type hints on all methods
- [ ] 95%+ test coverage
- [ ] Pass all golden contract tests
- [ ] Performance <200ms P95
- [ ] Handle all vendor error codes
- [ ] Document limitations

## References
- [Adapter Pattern](https://refactoring.guru/design-patterns/adapter)
- [Contract Testing](https://martinfowler.com/bliki/ContractTest.html)
- Hotel PMS API docs (Apaleo, Mews, Opera, etc.)

---
**Decision made by**: Engineering Team  
**Reviewed by**: CTO, Head of Partnerships
