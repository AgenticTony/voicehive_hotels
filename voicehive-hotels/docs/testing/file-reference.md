# VoiceHive Hotels - Testing Infrastructure File Reference

## Quick Navigation

### Analysis Documents
- **Detailed Analysis**: `/TESTING_INFRASTRUCTURE_ANALYSIS.md` (comprehensive 700+ line analysis)
- **Quick Summary**: `/TESTING_INFRASTRUCTURE_SUMMARY.txt` (executive summary)
- **This File**: `/TESTING_INFRASTRUCTURE_FILES.md` (file reference guide)

---

## Test Files Directory Structure

### Unit Tests - Orchestrator Service
```
/services/orchestrator/tests/
├── conftest.py (integration test configuration)
├── test_app_refactored.py
├── test_call_event_endpoint.py
├── test_call_events_counter.py
├── test_circuit_breaker.py
├── test_compliance_integration.py
├── test_coverage_enhancement.py
├── test_database_performance_optimization.py
├── test_disaster_recovery.py
├── test_enhanced_coverage_runner.py
├── test_error_handling.py
├── test_fixes.py
├── test_logging_adapter.py
├── test_metrics_endpoint.py
├── test_monitoring_observability.py
├── test_performance_optimization.py
├── test_prometheus_counter_simple.py
├── test_rate_limiter.py
├── test_resilience_integration.py
├── test_security_compliance.py
├── test_security_penetration.py
├── test_security_runner.py
├── test_security_validation_comprehensive.py
├── test_slo_monitoring.py
├── test_tenacity_retry.py
├── test_tts_integration.py
├── test_tts_metrics.py
├── test_webhook.py
```

### Unit Tests - Connector Service
```
/connectors/tests/
├── conftest.py (connector test configuration)
├── fixtures.py (shared test fixtures)
├── test_apaleo_httpx.py
├── test_apaleo_mocked.py
├── test_apaleo_simple.py
├── test_apaleo_unit.py
├── test_apaleo_integration.py
├── test_azure_openai.py
├── test_factory.py
├── test_golden_contract.py
├── test_granary_asr.py
├── test_pii_redaction.py
├── test_twilio_integration.py
├── test_vault_client_v2.py
└── golden_contract/
    ├── README.md
    ├── __init__.py
    ├── test_apaleo.py
    └── test_base_contract.py
```

### Integration Tests
```
/services/orchestrator/tests/integration/
├── README.md
├── __init__.py
├── conftest.py (308-line integration fixtures)
├── pytest.ini (integration test configuration)
├── test_auth_flow_integration.py
├── test_call_flow_e2e.py
├── test_error_recovery_integration.py
├── test_performance_regression.py
├── test_pms_connector_integration.py
├── test_resilience_integration.py
└── test_runner.py
```

### Load Testing
```
/services/orchestrator/tests/load_testing/
├── README.md
├── __init__.py
├── conftest.py
├── load_test_config.json
├── requirements-load-test.txt
├── run_load_tests.py
├── test_auth_system_load.py
├── test_concurrent_calls.py
├── test_database_redis_performance.py
├── test_memory_performance.py
├── test_network_failure_simulation.py
└── test_pms_connector_load.py
```

### Test Framework
```
/services/orchestrator/tests/test_framework/
├── __init__.py
├── chaos_engineer.py
├── contract_tester.py
├── coverage_analyzer.py
├── load_tester.py
├── performance_tester.py
└── security_tester.py
```

### Configuration Files
```
/services/orchestrator/tests/
├── IMPLEMENTATION_SUMMARY.md
├── README_ENHANCED_TESTING.md
├── enhanced_testing_config.yaml
├── requirements-enhanced-testing.txt
└── security_test_config.yaml
```

---

## Configuration Files

### Root Configuration
```
/pytest.ini - Main pytest configuration
  - Coverage: 45% minimum
  - Async support: pytest-asyncio
  - Test markers: unit, integration, e2e, slow
  - Output: HTML and XML coverage reports
  - Timeout: 30 seconds per test
```

### Integration Test Configuration
```
/services/orchestrator/tests/integration/pytest.ini
  - Coverage: 80% minimum fail-under
  - Timeout: 300 seconds per test
  - CLI logging: INFO level
  - Markers: 8 custom categories (integration, e2e, performance, etc.)
```

### Enhanced Testing Configuration
```
/services/orchestrator/tests/enhanced_testing_config.yaml
  - Coverage target: 90%
  - Load testing parameters
  - Chaos engineering scenarios
  - Security testing depth: comprehensive
  - Performance baselines
  - Environment configuration
```

### Load Testing Configuration
```
/services/orchestrator/tests/load_testing/load_test_config.json
  - Concurrent users: 20
  - Requests per user: 50
  - Test duration: 120 seconds
  - Performance thresholds
  - Network simulation scenarios
  - Database and Redis configs
```

---

## CI/CD Pipelines

### GitHub Actions Workflows
```
/.github/workflows/
├── ci.yml - Main CI/CD pipeline
│   - Security scanning (Trivy, TruffleHog)
│   - Python tests with coverage
│   - Connector golden contract tests
│   - Docker build and security scan
│   - Terraform validation
│   - Staging/Production deployment
│
├── ci-enhanced.yml - Production testing pipeline
│   - Comprehensive security scanning (Gitleaks, TruffleHog, Trivy, Semgrep, Snyk)
│   - CodeQL analysis (Python, Go, JavaScript)
│   - Python tests & quality checks
│   - PMS connector compliance
│   - GDPR compliance validation
│   - Infrastructure validation
│   - Container scanning and signing
│   - Integration tests
│   - Performance tests (k6)
│   - Post-deployment monitoring
│
├── container-security.yml
├── dependency-security.yml
└── secret-scanning.yml
```

---

## Test Requirements

### Main Test Requirements
```
/services/test-requirements.txt - Service-level test dependencies
  - pytest, pytest-asyncio, pytest-cov, pytest-mock
  - httpx, websocket-client
  - prometheus-client
```

### Connector Test Requirements
```
/connectors/requirements-test.txt - Connector test dependencies
  - pytest, pytest-asyncio, pytest-httpx
  - pytest-cov, pytest-mock, pytest-timeout
  - factory-boy, faker
  - mypy, black, ruff, isort
```

### Enhanced Testing Requirements
```
/services/orchestrator/tests/requirements-enhanced-testing.txt
  - 111 dependencies including:
  - pytest, coverage, httpx, aiohttp
  - locust (load testing)
  - memory-profiler, psutil (performance)
  - bandit, safety, semgrep (security)
  - jsonschema, pact-python (contract testing)
  - JWT, cryptography libraries
  - faker, factory-boy (test data)
  - pytest-xdist (parallel execution)
```

### Load Testing Requirements
```
/services/orchestrator/tests/load_testing/requirements-load-test.txt
  - locust (load testing)
  - memory-profiler, psutil, pytest-benchmark
  - pytest-xdist, aiofiles
  - matplotlib, numpy, pandas
  - netem, toxiproxy-python (network simulation)
  - py-spy (profiling)
```

---

## Testing Tools and Frameworks

### Core Testing Framework
```
Tool                    Purpose                  Location
pytest (7.4.0+)        Test framework           All test files
pytest-asyncio         Async test support       conftest.py files
pytest-cov             Coverage measurement      All test runs
pytest-mock            Mock fixtures             Integration tests
```

### Load Testing
```
Tool                    Purpose                  Location
locust                  Load testing             load_testing/
memory-profiler         Memory profiling         load_testing/
psutil                  System metrics           load_testing/
py-spy                  Performance profiling    load_testing/
```

### Security Testing
```
Tool                    Purpose                  Location
bandit                  Security scanning        CI/CD + test framework
safety                  Dependency scanning      CI/CD + test framework
semgrep                 SAST scanning            CI/CD pipelines
Trivy                   Container scanning       CI/CD pipelines
```

### Performance Testing
```
Tool                    Purpose                  Location
test_framework/         Custom performance      services/orchestrator/tests/
performance_tester.py   regression framework    test_framework/
coverage_analyzer.py    Coverage analysis       test_framework/
```

---

## Key Test Files by Category

### Unit Tests (400+ functions across 50+ files)
```
Core Functionality:
  - test_app_refactored.py
  - test_call_event_endpoint.py
  - test_webhook.py

Reliability:
  - test_circuit_breaker.py
  - test_tenacity_retry.py
  - test_error_handling.py

Performance:
  - test_database_performance_optimization.py
  - test_performance_optimization.py
  - test_rate_limiter.py

Monitoring:
  - test_monitoring_observability.py
  - test_metrics_endpoint.py
  - test_prometheus_counter_simple.py
  - test_slo_monitoring.py

Security:
  - test_security_compliance.py
  - test_security_penetration.py
  - test_security_validation_comprehensive.py
```

### Integration Tests (80+ functions across 6 files)
```
Authentication:
  - test_auth_flow_integration.py (JWT, OAuth, permissions)

Call Management:
  - test_call_flow_e2e.py (complete lifecycle)

Error Handling:
  - test_error_recovery_integration.py (retry, fallback)

Connectors:
  - test_pms_connector_integration.py (PMS integration)

Resilience:
  - test_resilience_integration.py (circuit breaker, backpressure)

Performance:
  - test_performance_regression.py (baseline comparison)
```

### Load Tests (60+ functions across 6 files)
```
Concurrent Operations:
  - test_concurrent_calls.py
  - test_auth_system_load.py

Backend Performance:
  - test_database_redis_performance.py
  - test_pms_connector_load.py

Resource Management:
  - test_memory_performance.py
  - test_network_failure_simulation.py
```

---

## Mock Services

### Integration Test Fixtures (conftest.py - 308 lines)
```
Mock Services:
  ✓ Redis client (full async API)
  ✓ Vault client (secret management)
  ✓ PMS server (with failure injection)
  ✓ TTS service (speech synthesis)
  ✓ LiveKit service (media gateway)

HTTP Clients:
  ✓ Authenticated user client
  ✓ Service-to-service client
  ✓ Unauthenticated client

Application Configuration:
  ✓ Full integration test app setup
  ✓ Performance test config
  ✓ Load test scenarios
```

---

## Test Execution

### Make Commands
```bash
make test                        # Run all tests with coverage
make test-connector VENDOR=name  # Test specific connector
make load-test CALLS=50          # Run load tests
make security-scan               # Run security scans
make ci-test                     # CI test execution
```

### Direct Pytest Commands
```bash
# Run all tests
pytest -v --cov=services --cov=connectors

# Run integration tests only
pytest services/orchestrator/tests/integration -v

# Run load tests
python services/orchestrator/tests/load_testing/run_load_tests.py

# Run with specific markers
pytest -v -m integration        # Integration tests
pytest -v -m e2e               # End-to-end tests
pytest -v -m slow              # Slow tests

# Run enhanced testing framework
python services/orchestrator/tests/test_enhanced_coverage_runner.py
```

---

## Test Reports

### Report Directory
```
/test_reports/
├── enhanced_coverage_report_*.html  # HTML dashboard
├── enhanced_coverage_report_*.json  # JSON results
├── latest_summary.txt              # Text summary
├── coverage/
│   ├── htmlcov/                    # Coverage HTML
│   └── coverage.xml                # Coverage XML
├── performance/
│   ├── baselines.json              # Performance baselines
│   └── regression_analysis.json    # Regression analysis
└── security/
    ├── vulnerability_report.json   # Security findings
    └── penetration_test_results.json
```

---

## Documentation

### Key Documentation Files
```
/TESTING_INFRASTRUCTURE_ANALYSIS.md
  - Comprehensive analysis (700+ lines)
  - Detailed breakdown of all testing components
  - Technology stack and tools
  - Production readiness assessment
  - Recommendations

/TESTING_INFRASTRUCTURE_SUMMARY.txt
  - Executive summary
  - Quick reference guide
  - All 12 testing categories
  - File structure overview

/services/orchestrator/tests/README_ENHANCED_TESTING.md
  - Enhanced testing framework guide
  - Installation and usage instructions
  - Configuration details
  - CI/CD integration examples
  - Troubleshooting guide

/services/orchestrator/tests/IMPLEMENTATION_SUMMARY.md
  - Framework implementation details
  - Feature descriptions
  - Usage examples
  - Test results and validation

/services/orchestrator/tests/integration/README.md
  - Integration test guide
  - Setup instructions
  - Test categories and scenarios

/services/orchestrator/tests/load_testing/README.md
  - Load testing documentation
  - Configuration guide
  - Scenario descriptions
```

---

## Quick Stats

### Coverage Summary
```
Total Test Files:        70+
Total Test Functions:    619+
Unit Tests:             50+ files, 400+ functions
Integration Tests:      6 files, 80+ functions
Load Tests:             6 files, 60+ functions
Security Tests:         2+ files, 50+ functions
E2E Tests:              1 file, 30+ functions
```

### Configuration Files
```
pytest.ini files:       2 (main + integration)
YAML configs:           3 (enhanced, security, database)
JSON configs:           1 (load testing)
Requirements files:     3 (connectors, orchestrator, load)
```

### CI/CD Workflows
```
GitHub Actions files:   5 workflows
Total test jobs:        15+ distinct test jobs
Security scans:         5+ different security tools
Quality gates:          4 (coverage, security, performance, contract)
```

---

## Starting Points by Use Case

### If you want to...

**Understand the complete testing strategy**
→ Read: `TESTING_INFRASTRUCTURE_ANALYSIS.md`

**Get a quick overview**
→ Read: `TESTING_INFRASTRUCTURE_SUMMARY.txt`

**Run all tests**
→ Execute: `make test`

**Run specific test category**
→ Navigate to: `/services/orchestrator/tests/[category]/`
→ Execute: `pytest -v -m [marker]`

**Review load testing configuration**
→ Check: `load_testing/load_test_config.json`
→ Read: `load_testing/README.md`

**Understand security testing**
→ Review: `test_framework/security_tester.py`
→ Check: `security_test_config.yaml`

**Add new tests**
→ Reference: `README_ENHANCED_TESTING.md`
→ Review: Example fixtures in `conftest.py` files

**Debug test failures**
→ Check: Test logs in `/test_reports/`
→ Review: CI/CD logs in `.github/workflows/`

---

## Key Metrics

```
Code Coverage:           45-90% (configurable)
Integration Coverage:    80% minimum
Performance Regression:  20% threshold
Response Time SLA:       2000ms (API), 500ms (DB)
Security Severity:       Fail on CRITICAL vulnerabilities
Load Test Users:         20-100 concurrent
Load Test Duration:      120 seconds (configurable)
E2E Test Timeout:        5+ minutes
```

---

Generated: 2024
Status: PRODUCTION READY ✅
