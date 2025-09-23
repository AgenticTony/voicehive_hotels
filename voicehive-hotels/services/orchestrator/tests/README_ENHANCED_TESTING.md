# Enhanced Testing Framework for Production Readiness

This comprehensive testing framework implements task 16 from the production readiness specification, providing enhanced test coverage and quality assurance to meet production standards.

## Overview

The Enhanced Testing Framework provides:

1. **Integration Test Coverage Enhancement** (70% → 90%+)
2. **Load Testing** for critical user journeys
3. **Chaos Engineering** with automated failure injection
4. **Security Penetration Testing** automation
5. **Performance Regression Testing** with baseline comparisons
6. **Contract Testing** for PMS connector integrations

## Quick Start

### Installation

```bash
# Install enhanced testing dependencies
pip install -r requirements-enhanced-testing.txt

# Ensure test reports directory exists
mkdir -p test_reports
```

### Basic Usage

```bash
# Run all enhanced tests
python test_enhanced_coverage_runner.py

# Run specific test categories
python test_enhanced_coverage_runner.py --categories coverage load security

# Run with custom configuration
python test_enhanced_coverage_runner.py --concurrent-users 100 --coverage-target 95.0
```

### Quick Validation

```bash
# Run the main test to validate framework
pytest test_coverage_enhancement.py -v
```

## Framework Components

### 1. Coverage Analyzer (`test_framework/coverage_analyzer.py`)

Analyzes current test coverage and automatically generates additional tests to reach >90% coverage.

**Features:**

- AST-based code analysis for gap identification
- Automatic test generation for uncovered code paths
- Priority-based coverage enhancement
- Integration with pytest and coverage.py

**Usage:**

```python
from test_framework.coverage_analyzer import CoverageAnalyzer

analyzer = CoverageAnalyzer(config)
results = await analyzer.analyze_and_enhance_coverage()
```

### 2. Load Tester (`test_framework/load_tester.py`)

Comprehensive load testing for critical user journeys with realistic traffic patterns.

**Features:**

- Concurrent user simulation
- Critical user journey testing
- Performance metrics collection
- Bottleneck identification

**Scenarios Tested:**

- Authentication flows
- Call creation and management
- PMS integration operations
- TTS synthesis requests
- Mixed production workloads

### 3. Chaos Engineer (`test_framework/chaos_engineer.py`)

Automated failure injection to test system resilience and recovery capabilities.

**Features:**

- Network failure simulation
- Service unavailability injection
- Resource pressure testing
- Recovery time measurement

**Failure Types:**

- Network latency and partitions
- Service unavailability
- Database/Redis failures
- Memory and CPU pressure
- Timeout and exception injection

### 4. Security Tester (`test_framework/security_tester.py`)

Comprehensive security testing with automated vulnerability scanning.

**Features:**

- SQL injection testing
- XSS vulnerability scanning
- Authentication/authorization bypass testing
- JWT security validation
- Security headers verification

**Vulnerability Types:**

- SQL Injection
- Cross-Site Scripting (XSS)
- CSRF vulnerabilities
- Authentication bypass
- Information disclosure
- Insecure headers

### 5. Performance Tester (`test_framework/performance_tester.py`)

Performance regression testing with baseline comparisons and trend analysis.

**Features:**

- Baseline performance tracking
- Regression detection
- Memory usage monitoring
- Response time analysis
- Performance scoring

**Metrics Tracked:**

- Response times (avg, p95, p99)
- Throughput (requests per second)
- Memory usage and leaks
- CPU utilization
- Error rates

### 6. Contract Tester (`test_framework/contract_tester.py`)

Contract testing for PMS connector integrations to ensure API compatibility.

**Features:**

- JSON schema validation
- Request/response contract verification
- PMS connector compatibility testing
- Webhook contract validation

**PMS Connectors Supported:**

- Apaleo
- Opera
- Protel
- Mews
- CloudBeds

## Configuration

### Configuration File (`enhanced_testing_config.yaml`)

The framework uses a comprehensive YAML configuration file for all settings:

```yaml
coverage:
  target_percentage: 90.0
  fail_under: 90.0

load_testing:
  concurrent_users: 50
  requests_per_user: 100
  max_response_time_ms: 2000

security_testing:
  scan_depth: "comprehensive"
  vulnerability_threshold: "medium"
# ... additional configuration options
```

### Environment Variables

```bash
# Test environment
export TEST_BASE_URL="http://localhost:8000"
export TEST_DATABASE_URL="postgresql://test:test@localhost:5432/test_db"
export TEST_REDIS_URL="redis://localhost:6379/1"

# Security testing
export SECURITY_SCAN_ENABLED="true"
export CHAOS_TESTING_ENABLED="true"
```

## Running Tests

### Command Line Interface

```bash
# Run all tests with default configuration
python test_enhanced_coverage_runner.py

# Run specific categories
python test_enhanced_coverage_runner.py --categories coverage load

# Custom configuration
python test_enhanced_coverage_runner.py \
  --concurrent-users 100 \
  --coverage-target 95.0 \
  --test-duration 600 \
  --memory-threshold 1024

# Verbose output
python test_enhanced_coverage_runner.py --verbose
```

### Programmatic Usage

```python
import asyncio
from test_coverage_enhancement import EnhancedTestSuite, TestConfiguration

# Create configuration
config = TestConfiguration(
    target_coverage_percentage=90.0,
    concurrent_users=50,
    test_duration_seconds=300
)

# Run tests
async def run_tests():
    suite = EnhancedTestSuite(config)
    results = await suite.run_comprehensive_tests()
    return results

# Execute
results = asyncio.run(run_tests())
```

### Integration with pytest

```bash
# Run enhanced tests through pytest
pytest test_coverage_enhancement.py -v

# With coverage reporting
pytest test_coverage_enhancement.py --cov=services/orchestrator --cov-report=html

# Parallel execution
pytest test_coverage_enhancement.py -n auto
```

## Test Categories

### 1. Coverage Enhancement Tests

**Objective:** Increase integration test coverage from 70% to >90%

**Process:**

1. Analyze current coverage using AST parsing
2. Identify critical uncovered code paths
3. Generate targeted tests for gaps
4. Validate new coverage meets targets

**Output:**

- New test files for uncovered areas
- Coverage report with gap analysis
- Recommendations for manual test additions

### 2. Load Testing Scenarios

**Objective:** Validate system performance under production load

**Scenarios:**

- User authentication flows (20 concurrent users, 50 requests each)
- Call creation and events (25-50 concurrent users)
- PMS integration operations (15-20 concurrent users)
- Mixed production workload simulation

**Metrics:**

- Response times (average, p95, p99)
- Throughput (requests per second)
- Error rates and failure patterns
- Resource utilization

### 3. Chaos Engineering Tests

**Objective:** Validate system resilience and recovery

**Experiments:**

- Network latency injection (1-3 second delays)
- Service unavailability (complete service failures)
- Database connection failures
- Memory and CPU pressure
- Timeout and exception injection

**Validation:**

- Circuit breaker activation
- Graceful degradation
- Recovery time measurement
- No cascading failures

### 4. Security Penetration Tests

**Objective:** Identify and validate security vulnerabilities

**Test Types:**

- SQL injection (10+ payload variations)
- XSS attacks (reflected and stored)
- Authentication bypass attempts
- JWT token manipulation
- Security headers validation
- Rate limiting bypass

**Compliance:**

- OWASP Top 10 coverage
- Security header requirements
- Input validation effectiveness
- Authentication/authorization robustness

### 5. Performance Regression Tests

**Objective:** Detect performance degradations

**Baselines:**

- Response time baselines per endpoint
- Memory usage patterns
- Throughput benchmarks
- Resource utilization norms

**Detection:**

- 20% response time increase threshold
- Memory usage growth monitoring
- Throughput degradation alerts
- Performance scoring (0-100)

### 6. Contract Testing

**Objective:** Ensure PMS connector API compatibility

**Contracts:**

- Request/response schemas
- Status code expectations
- Header requirements
- Error format standards

**Validation:**

- JSON schema compliance
- API contract adherence
- Backward compatibility
- Error handling consistency

## Reports and Output

### Report Types

1. **HTML Report** - Comprehensive visual report with charts and metrics
2. **JSON Report** - Machine-readable results for CI/CD integration
3. **Text Summary** - Console-friendly summary report
4. **JUnit XML** - CI/CD compatible test results

### Report Contents

- Executive summary with production readiness assessment
- Detailed results for each test category
- Performance metrics and trends
- Security vulnerability findings
- Coverage analysis and gaps
- Actionable recommendations

### Sample Report Structure

```
test_reports/
├── enhanced_coverage_report_1234567890.html
├── enhanced_coverage_report_1234567890.json
├── latest_summary.txt
├── coverage/
│   ├── htmlcov/
│   └── coverage.xml
├── performance/
│   ├── baselines.json
│   └── regression_analysis.json
└── security/
    ├── vulnerability_report.json
    └── penetration_test_results.json
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Enhanced Testing

on: [push, pull_request]

jobs:
  enhanced-testing:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install -r requirements-enhanced-testing.txt

      - name: Run enhanced tests
        run: |
          python test_enhanced_coverage_runner.py --categories coverage security

      - name: Upload test reports
        uses: actions/upload-artifact@v3
        with:
          name: test-reports
          path: test_reports/
```

### Quality Gates

The framework supports configurable quality gates:

- **Coverage Gate:** Fail if coverage < 90%
- **Security Gate:** Fail if critical vulnerabilities found
- **Performance Gate:** Fail if regression > 20%
- **Contract Gate:** Fail if contract violations detected

## Troubleshooting

### Common Issues

1. **Import Errors**

   ```bash
   # Ensure all dependencies are installed
   pip install -r requirements-enhanced-testing.txt

   # Check Python path
   export PYTHONPATH="${PYTHONPATH}:$(pwd)"
   ```

2. **Coverage Measurement Issues**

   ```bash
   # Clear coverage data
   coverage erase

   # Run with explicit source
   coverage run --source=services/orchestrator -m pytest
   ```

3. **Load Testing Failures**

   ```bash
   # Reduce concurrent users for resource-constrained environments
   python test_enhanced_coverage_runner.py --concurrent-users 10

   # Increase timeouts
   python test_enhanced_coverage_runner.py --test-duration 600
   ```

4. **Security Test False Positives**
   ```bash
   # Adjust vulnerability threshold
   # Edit enhanced_testing_config.yaml:
   # security_testing:
   #   vulnerability_threshold: "high"
   ```

### Debug Mode

```bash
# Enable debug logging
python test_enhanced_coverage_runner.py --verbose

# Run single test category for debugging
python test_enhanced_coverage_runner.py --categories coverage --verbose
```

### Performance Optimization

```bash
# Reduce test scope for faster execution
python test_enhanced_coverage_runner.py \
  --concurrent-users 20 \
  --requests-per-user 50 \
  --test-duration 120

# Skip resource-intensive tests
python test_enhanced_coverage_runner.py --categories coverage security
```

## Development and Extension

### Adding New Test Categories

1. Create new tester class in `test_framework/`
2. Implement required interface methods
3. Add to `EnhancedTestSuite` initialization
4. Update configuration schema
5. Add CLI arguments if needed

### Custom Test Scenarios

```python
# Example: Custom load test scenario
from test_framework.load_tester import LoadTester, PerformanceTest

custom_test = PerformanceTest(
    name="custom_endpoint_test",
    description="Test custom endpoint performance",
    endpoint="/api/custom",
    method="POST",
    concurrent_users=30,
    requests_per_user=25
)

# Add to load tester scenarios
load_tester.performance_tests.append(custom_test)
```

### Extending Security Tests

```python
# Example: Custom security test
from test_framework.security_tester import SecurityTester, SecurityTest

custom_security_test = SecurityTest(
    name="custom_vulnerability_test",
    description="Test for custom vulnerability",
    vulnerability_type=VulnerabilityType.CUSTOM,
    endpoint="/api/vulnerable",
    test_function="test_custom_vulnerability"
)
```

## Best Practices

### Test Organization

1. **Separate Concerns** - Keep different test types in separate modules
2. **Mock External Dependencies** - Use mocks for external services
3. **Parameterize Tests** - Use configuration for test parameters
4. **Clean Test Data** - Ensure tests clean up after themselves

### Performance Considerations

1. **Parallel Execution** - Run independent tests in parallel
2. **Resource Limits** - Set appropriate resource limits
3. **Test Isolation** - Ensure tests don't interfere with each other
4. **Efficient Mocking** - Use lightweight mocks for external services

### Security Testing

1. **Safe Payloads** - Use safe, non-destructive test payloads
2. **Isolated Environment** - Run security tests in isolated environments
3. **Regular Updates** - Keep security test payloads updated
4. **False Positive Handling** - Implement mechanisms to handle false positives

## Contributing

### Development Setup

```bash
# Clone repository
git clone <repository-url>
cd voicehive-hotels

# Install development dependencies
pip install -r services/orchestrator/tests/requirements-enhanced-testing.txt

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run framework tests
pytest services/orchestrator/tests/test_coverage_enhancement.py -v

# Run with coverage
pytest services/orchestrator/tests/test_coverage_enhancement.py --cov=test_framework

# Run all enhanced tests
python services/orchestrator/tests/test_enhanced_coverage_runner.py
```

### Code Quality

```bash
# Format code
black services/orchestrator/tests/

# Sort imports
isort services/orchestrator/tests/

# Lint code
flake8 services/orchestrator/tests/

# Type checking
mypy services/orchestrator/tests/
```

## License

This enhanced testing framework is part of the VoiceHive Hotels project and follows the same licensing terms.

## Support

For issues, questions, or contributions:

1. Check existing issues in the project repository
2. Create detailed bug reports with reproduction steps
3. Submit feature requests with clear use cases
4. Contribute improvements via pull requests

## Changelog

### Version 1.0.0

- Initial implementation of enhanced testing framework
- Coverage enhancement from 70% to 90%+
- Load testing for critical user journeys
- Chaos engineering with failure injection
- Security penetration testing automation
- Performance regression testing with baselines
- Contract testing for PMS connectors
- Comprehensive reporting and CI/CD integration
