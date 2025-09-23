# Load Testing & Performance Validation Suite

This comprehensive load testing suite validates the production readiness of the VoiceHive Hotels system by testing performance, scalability, and resilience under various load conditions.

## Overview

The load testing suite covers the following areas as specified in task 9 of the production readiness specification:

- **Concurrent Call Simulation Testing** - Tests the system's ability to handle multiple simultaneous voice calls
- **PMS Connector Load Testing** - Validates PMS integration performance under load
- **Authentication System Load Testing** - Tests JWT validation, API keys, and session management
- **Memory Usage and Leak Detection** - Monitors memory patterns and detects potential leaks
- **Database and Redis Performance Testing** - Validates data layer performance
- **Network Partition and Failure Simulation** - Tests system resilience under network failures

## Installation

1. Install load testing dependencies:

```bash
pip install -r requirements-load-test.txt
```

2. Ensure the main application dependencies are installed:

```bash
pip install -r ../requirements.txt
```

## Configuration

The load testing suite uses `load_test_config.json` for configuration. Key settings include:

- `concurrent_users`: Number of concurrent users to simulate
- `requests_per_user`: Number of requests each user makes
- `test_duration`: Duration of sustained load tests
- `memory_threshold_mb`: Memory usage threshold for validation
- `max_response_time`: Maximum acceptable response time
- `max_error_rate`: Maximum acceptable error rate

## Running Load Tests

### Run All Tests

```bash
python run_load_tests.py
```

### Run Specific Categories

```bash
python run_load_tests.py --categories "Concurrent Call Simulation" "Authentication System Load Testing"
```

### Run with Custom Parameters

```bash
python run_load_tests.py --concurrent-users 50 --requests-per-user 100 --test-duration 300
```

### Skip Specific Tests

```bash
python run_load_tests.py --skip-tests test_memory_leak_detection test_network_partition_recovery
```

## Test Categories

### 1. Concurrent Call Simulation (`test_concurrent_calls.py`)

Tests the system's ability to handle multiple simultaneous voice calls:

- **Call Creation Load** - Tests concurrent call creation and management
- **Call Events Processing** - Tests event processing under load (call started, answered, ended, etc.)
- **Audio Streaming** - Tests concurrent audio upload/download and TTS synthesis
- **Call Routing** - Tests call routing and transfer operations
- **Mixed Operations** - Tests realistic mixed workload patterns

### 2. PMS Connector Load Testing (`test_pms_connector_load.py`)

Validates Property Management System integration performance:

- **Reservation Lookup** - Tests reservation data retrieval under load
- **Guest Profile Operations** - Tests guest data operations (read/write)
- **Failover Scenarios** - Tests PMS connector behavior during failures
- **Bulk Operations** - Tests large data synchronization operations
- **Circuit Breaker** - Tests circuit breaker behavior under PMS failures
- **Cache Performance** - Tests caching effectiveness under load

### 3. Authentication System Load Testing (`test_auth_system_load.py`)

Tests authentication and authorization performance:

- **JWT Authentication** - Tests login operations under load
- **JWT Validation** - Tests token validation performance
- **API Key Validation** - Tests service-to-service authentication
- **Session Management** - Tests session creation, validation, and cleanup
- **RBAC Performance** - Tests role-based access control under load
- **Mixed Auth Load** - Tests realistic authentication workload patterns

### 4. Memory Performance Testing (`test_memory_performance.py`)

Monitors memory usage and detects potential leaks:

- **Memory Usage Patterns** - Tests memory usage under different load types
- **Memory Leak Detection** - Long-running tests to detect memory leaks
- **Connection Pool Memory** - Tests memory usage of database/Redis pools
- **Audio Processing Memory** - Tests memory usage during audio operations
- **Garbage Collection** - Tests GC performance and effectiveness

### 5. Database and Redis Performance (`test_database_redis_performance.py`)

Validates data layer performance:

- **Database Connection Pools** - Tests connection pool scaling and performance
- **Redis Operations** - Tests Redis operation performance by type
- **Integration Performance** - Tests combined database and Redis operations
- **Data Consistency** - Tests consistency under concurrent operations

### 6. Network Failure Simulation (`test_network_failure_simulation.py`)

Tests system resilience under network conditions:

- **High Latency Resilience** - Tests behavior under network latency
- **Packet Loss Resilience** - Tests behavior under packet loss conditions
- **Service Failure Resilience** - Tests behavior when external services fail
- **Network Partition Recovery** - Tests recovery after network partitions

## Performance Monitoring

The suite includes comprehensive performance monitoring:

- **Real-time Metrics** - Memory usage, CPU usage, response times
- **Memory Profiling** - Detailed memory allocation tracking
- **Network Simulation** - Configurable network conditions
- **Service Failure Simulation** - Configurable service degradation

## Test Results and Reporting

### Console Output

Real-time progress and results are displayed in the console with:

- Test progress indicators
- Performance metrics
- Pass/fail status
- Summary statistics

### Detailed Reports

Comprehensive JSON reports are generated containing:

- Overall test statistics
- Per-category results
- Failed test details
- Performance recommendations
- Raw performance data

### Performance Thresholds

Tests validate against configurable thresholds:

- Response time limits
- Error rate limits
- Memory usage limits
- Throughput requirements

## Integration with CI/CD

The load testing suite can be integrated into CI/CD pipelines:

```bash
# Run load tests in CI
python run_load_tests.py --concurrent-users 10 --requests-per-user 20 --test-duration 60

# Check exit code
if [ $? -eq 0 ]; then
    echo "Load tests passed"
else
    echo "Load tests failed"
    exit 1
fi
```

## Troubleshooting

### Common Issues

1. **High Memory Usage**

   - Reduce `concurrent_users` and `requests_per_user`
   - Check for memory leaks in application code
   - Ensure proper cleanup in test fixtures

2. **Test Timeouts**

   - Increase `max_response_time` threshold
   - Check system resources (CPU, memory, network)
   - Verify service dependencies are running

3. **Network Simulation Failures**
   - Ensure proper network simulation setup
   - Check firewall and network policies
   - Verify service endpoints are accessible

### Performance Optimization

1. **Database Performance**

   - Optimize connection pool sizes
   - Add database indexes for test queries
   - Monitor query execution plans

2. **Redis Performance**

   - Tune Redis configuration
   - Monitor Redis memory usage
   - Optimize data structures

3. **Application Performance**
   - Profile application code
   - Optimize hot code paths
   - Implement proper caching strategies

## Best Practices

1. **Test Environment**

   - Use production-like hardware
   - Isolate test environment
   - Monitor system resources

2. **Test Data**

   - Use realistic test data volumes
   - Clean up test data between runs
   - Avoid test data conflicts

3. **Load Patterns**

   - Start with baseline load
   - Gradually increase load
   - Test peak and sustained load

4. **Monitoring**
   - Monitor all system components
   - Set up alerting for failures
   - Collect detailed metrics

## Contributing

When adding new load tests:

1. Follow the existing test structure
2. Include proper error handling
3. Add performance validation
4. Update documentation
5. Test with various load levels

## References

- [Locust Documentation](https://docs.locust.io/)
- [Python Memory Profiler](https://pypi.org/project/memory-profiler/)
- [Production Readiness Specification](../../specs/production-readiness/)
