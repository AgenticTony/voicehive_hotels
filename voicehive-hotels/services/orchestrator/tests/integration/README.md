# Integration Testing Suite

This directory contains comprehensive integration tests for the VoiceHive Hotels Orchestrator service, covering all aspects of production readiness including authentication, resilience, error handling, and performance.

## Test Suites

### 1. End-to-End Call Flow Tests (`test_call_flow_e2e.py`)

Tests complete call flows from incoming webhooks to TTS responses:

- Complete authenticated call flow scenarios
- PMS integration during call processing
- Error handling in call flows
- Concurrent call processing
- GDPR compliance and PII redaction
- Performance metrics collection
- Circuit breaker integration

### 2. PMS Connector Integration Tests (`test_pms_connector_integration.py`)

Tests integration with Property Management Systems:

- Apaleo connector integration
- PMS connector factory with multiple types
- Error handling and fallback behavior
- Performance optimization (caching, connection pooling)
- Data validation and sanitization
- Concurrent access patterns
- Circuit breaker behavior

### 3. Authentication Flow Tests (`test_auth_flow_integration.py`)

Tests complete authentication and authorization flows:

- JWT authentication flow (login to logout)
- API key authentication for services
- Role-based access control (RBAC)
- JWT token validation edge cases
- Session management with Redis
- Performance under concurrent load
- Security error handling
- Cross-origin authentication (CORS)

### 4. Resilience Integration Tests (`test_resilience_integration.py`)

Tests rate limiting, circuit breakers, and backpressure:

- Rate limiting per client and endpoint
- Sliding window algorithm behavior
- Authentication bypass for internal services
- Circuit breaker with external service failures
- Circuit breaker recovery mechanisms
- Service isolation (failures don't cascade)
- Timeout handling
- Backpressure under concurrent load
- Combined resilience features

### 5. Error Recovery Tests (`test_error_recovery_integration.py`)

Tests comprehensive error handling and recovery:

- Standardized error response formats
- Correlation ID tracking across services
- Retry logic with exponential backoff
- Graceful degradation scenarios
- Error alerting and notifications
- Service restoration recovery
- Concurrent error handling
- Database/Redis connection recovery
- External API timeout recovery
- Memory pressure handling
- Cascading failure prevention

### 6. Performance Regression Tests (`test_performance_regression.py`)

Tests system performance and detects regressions:

- Individual endpoint performance characteristics
- Mixed workload performance
- Memory usage under sustained load
- Performance regression detection framework
- Scalability with increasing load
- Integration with monitoring systems
- Performance metrics collection and analysis

## Running Tests

### Prerequisites

```bash
# Install test dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov pytest-timeout

# Ensure Redis and other services are available for testing
# (Tests use mocks by default, but some integration points may need real services)
```

### Running Individual Test Suites

```bash
# Run specific test suite
pytest tests/integration/test_call_flow_e2e.py -v

# Run with coverage
pytest tests/integration/test_auth_flow_integration.py --cov=. --cov-report=html

# Run performance tests (longer duration)
pytest tests/integration/test_performance_regression.py --timeout=600
```

### Running All Integration Tests

```bash
# Run all integration tests
pytest tests/integration/ -v

# Run with comprehensive reporting
pytest tests/integration/ --cov=. --cov-report=html:test_reports/coverage --junit-xml=test_reports/junit.xml

# Quick run (skip performance tests)
pytest tests/integration/ -m "not performance" -v
```

### Using the Test Runner

```bash
# Run all suites with comprehensive reporting
python tests/integration/test_runner.py

# Run specific suites
python tests/integration/test_runner.py --suites call_flow auth_flow

# Skip performance tests for faster execution
python tests/integration/test_runner.py --skip-performance

# Generate reports in custom directory
python tests/integration/test_runner.py --output-dir custom_reports
```

## Test Configuration

### Environment Variables

```bash
# Test environment configuration
export ENVIRONMENT=test
export REDIS_URL=redis://localhost:6379/1
export VAULT_ADDR=http://localhost:8200

# Optional: Real service endpoints for integration testing
export PMS_API_URL=https://api.apaleo.com
export TTS_SERVICE_URL=https://api.elevenlabs.io
```

### Test Data

Tests use mock data by default, but can be configured to use real test data:

- Mock PMS reservations in `conftest.py`
- Test user accounts for authentication
- Sample audio data for TTS testing

### Performance Baselines

Performance tests can use baseline metrics for regression detection:

- Store baseline metrics in `test_reports/baselines/`
- Compare current runs against historical baselines
- Alert on significant performance regressions

## Test Architecture

### Fixtures and Mocks

- `conftest.py`: Shared fixtures for all integration tests
- Mock services: PMS, TTS, LiveKit, Redis, Vault
- Test clients: Authenticated, service, unauthenticated
- Performance testing framework

### Test Patterns

- **Arrange-Act-Assert**: Standard test structure
- **Given-When-Then**: BDD-style scenarios for complex flows
- **Property-based testing**: For data validation scenarios
- **Load testing**: Concurrent request patterns

### Error Simulation

Tests simulate various failure scenarios:

- Network timeouts and connection failures
- Service unavailability and degraded performance
- Authentication and authorization failures
- Data corruption and validation errors
- Resource exhaustion (memory, connections)

## Continuous Integration

### CI/CD Integration

```yaml
# Example GitHub Actions workflow
- name: Run Integration Tests
  run: |
    python tests/integration/test_runner.py --output-dir ci_reports

- name: Upload Test Reports
  uses: actions/upload-artifact@v3
  with:
    name: integration-test-reports
    path: ci_reports/
```

### Quality Gates

- Minimum 95% test pass rate
- Maximum 5% error rate under load
- Performance regression thresholds
- Security vulnerability detection

## Monitoring and Alerting

### Test Metrics

Integration tests collect and report:

- Test execution times and success rates
- System performance under test load
- Resource utilization during tests
- Error patterns and failure modes

### Integration with Monitoring

- Prometheus metrics from test runs
- Grafana dashboards for test trends
- PagerDuty alerts for test failures
- Slack notifications for CI results

## Troubleshooting

### Common Issues

1. **Redis Connection Errors**: Ensure Redis is running on correct port
2. **Authentication Failures**: Check JWT secret configuration
3. **Timeout Errors**: Increase test timeouts for slow environments
4. **Memory Issues**: Reduce concurrent request counts
5. **Mock Service Failures**: Verify mock configurations in conftest.py

### Debug Mode

```bash
# Run tests with debug logging
pytest tests/integration/ -v -s --log-cli-level=DEBUG

# Run single test with full output
pytest tests/integration/test_call_flow_e2e.py::TestCallFlowEndToEnd::test_complete_call_flow_authenticated -v -s
```

### Performance Debugging

```bash
# Profile test execution
pytest tests/integration/test_performance_regression.py --profile

# Memory profiling
pytest tests/integration/ --memray

# Generate performance reports
python tests/integration/test_runner.py --suites performance --output-dir perf_debug
```

## Contributing

### Adding New Tests

1. Follow existing test patterns and naming conventions
2. Add appropriate markers for test categorization
3. Include both positive and negative test scenarios
4. Add performance considerations for new endpoints
5. Update this README with new test descriptions

### Test Review Checklist

- [ ] Tests cover happy path and error scenarios
- [ ] Appropriate mocks and fixtures used
- [ ] Performance implications considered
- [ ] Security aspects tested
- [ ] Documentation updated
- [ ] CI/CD integration verified

## References

- [FastAPI Testing Documentation](https://fastapi.tiangolo.com/tutorial/testing/)
- [pytest-asyncio Documentation](https://pytest-asyncio.readthedocs.io/)
- [Production Readiness Requirements](../../specs/production-readiness/requirements.md)
- [System Design Document](../../specs/production-readiness/design.md)
