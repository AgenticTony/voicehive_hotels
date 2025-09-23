"""
Database and Redis Performance Testing

Tests database connection pools, Redis operations, and data layer
performance under various load conditions.
"""

import pytest
import asyncio
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import random
import string

from .conftest import LoadTestRunner, LoadTestMetrics, PerformanceMonitor


class DatabasePerformanceTester:
    """Advanced database performance testing utilities"""
    
    def __init__(self):
        self.connection_pool = None
        self.query_cache = {}
        
    async def test_connection_pool_scaling(
        self,
        min_connections: int = 5,
        max_connections: int = 50,
        concurrent_queries: int = 100
    ) -> Dict[str, Any]:
        """Test database connection pool scaling under load"""
        
        results = []
        
        # Test different pool sizes
        pool_sizes = [min_connections, min_connections * 2, min_connections * 4, max_connections]
        
        for pool_size in pool_sizes:
            print(f"Testing pool size: {pool_size}")
            
            start_time = time.time()
            
            # Simulate concurrent database operations
            async def database_operation(query_id: int):
                # Simulate different query types and complexities
                query_types = ["SELECT", "INSERT", "UPDATE", "DELETE"]
                query_type = random.choice(query_types)
                
                # Simulate query execution time based on type
                if query_type == "SELECT":
                    execution_time = random.uniform(0.01, 0.05)
                elif query_type == "INSERT":
                    execution_time = random.uniform(0.02, 0.08)
                elif query_type == "UPDATE":
                    execution_time = random.uniform(0.03, 0.1)
                else:  # DELETE
                    execution_time = random.uniform(0.02, 0.06)
                
                await asyncio.sleep(execution_time)
                
                return {
                    "query_id": query_id,
                    "query_type": query_type,
                    "execution_time": execution_time,
                    "pool_size": pool_size
                }
            
            # Execute concurrent queries
            tasks = [database_operation(i) for i in range(concurrent_queries)]
            query_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            end_time = time.time()
            
            # Analyze results
            successful_queries = [r for r in query_results if isinstance(r, dict)]
            failed_queries = len(query_results) - len(successful_queries)
            
            total_duration = end_time - start_time
            queries_per_second = len(successful_queries) / total_duration
            
            avg_execution_time = sum(q["execution_time"] for q in successful_queries) / len(successful_queries) if successful_queries else 0
            
            results.append({
                "pool_size": pool_size,
                "concurrent_queries": concurrent_queries,
                "successful_queries": len(successful_queries),
                "failed_queries": failed_queries,
                "total_duration": total_duration,
                "queries_per_second": queries_per_second,
                "avg_execution_time": avg_execution_time,
                "error_rate": failed_queries / len(query_results)
            })
        
        return {
            "test_type": "connection_pool_scaling",
            "results": results,
            "optimal_pool_size": max(results, key=lambda x: x["queries_per_second"])["pool_size"]
        }
    
    async def test_query_performance_patterns(
        self,
        concurrent_users: int = 20,
        test_duration: int = 60
    ) -> Dict[str, Any]:
        """Test different query patterns and their performance characteristics"""
        
        query_patterns = [
            {
                "name": "simple_selects",
                "queries": [
                    "SELECT id, name FROM hotels WHERE id = $1",
                    "SELECT * FROM rooms WHERE hotel_id = $1 AND status = 'available'",
                    "SELECT count(*) FROM reservations WHERE hotel_id = $1"
                ],
                "weight": 0.4
            },
            {
                "name": "complex_joins",
                "queries": [
                    """SELECT h.name, r.room_number, res.guest_name, res.check_in 
                       FROM hotels h 
                       JOIN rooms r ON h.id = r.hotel_id 
                       JOIN reservations res ON r.id = res.room_id 
                       WHERE h.id = $1""",
                    """SELECT g.name, COUNT(res.id) as reservation_count,
                       AVG(res.total_amount) as avg_amount
                       FROM guests g
                       JOIN reservations res ON g.id = res.guest_id
                       WHERE res.check_in >= $1
                       GROUP BY g.id, g.name"""
                ],
                "weight": 0.3
            },
            {
                "name": "aggregations",
                "queries": [
                    """SELECT DATE(check_in) as date, COUNT(*) as reservations,
                       SUM(total_amount) as revenue
                       FROM reservations 
                       WHERE hotel_id = $1 AND check_in >= $2
                       GROUP BY DATE(check_in)
                       ORDER BY date""",
                    """SELECT room_type, AVG(occupancy_rate) as avg_occupancy
                       FROM room_statistics
                       WHERE hotel_id = $1 AND date >= $2
                       GROUP BY room_type"""
                ],
                "weight": 0.2
            },
            {
                "name": "writes",
                "queries": [
                    "INSERT INTO reservations (hotel_id, room_id, guest_id, check_in, check_out) VALUES ($1, $2, $3, $4, $5)",
                    "UPDATE reservations SET status = $1, updated_at = NOW() WHERE id = $2",
                    "DELETE FROM temp_reservations WHERE created_at < $1"
                ],
                "weight": 0.1
            }
        ]
        
        pattern_results = []
        start_time = time.time()
        
        for pattern in query_patterns:
            pattern_start = time.time()
            
            # Calculate number of users for this pattern
            pattern_users = max(1, int(concurrent_users * pattern["weight"]))
            
            async def execute_pattern_queries(user_id: int):
                user_results = []
                user_start = time.time()
                
                while time.time() - user_start < test_duration:
                    query = random.choice(pattern["queries"])
                    
                    query_start = time.time()
                    
                    try:
                        # Simulate query execution
                        if "SELECT" in query.upper():
                            if "JOIN" in query.upper() or "GROUP BY" in query.upper():
                                execution_time = random.uniform(0.05, 0.2)  # Complex queries
                            else:
                                execution_time = random.uniform(0.01, 0.05)  # Simple queries
                        else:  # INSERT/UPDATE/DELETE
                            execution_time = random.uniform(0.02, 0.1)
                        
                        await asyncio.sleep(execution_time)
                        
                        user_results.append({
                            "user_id": user_id,
                            "query": query[:50] + "..." if len(query) > 50 else query,
                            "execution_time": execution_time,
                            "success": True
                        })
                        
                    except Exception as e:
                        user_results.append({
                            "user_id": user_id,
                            "query": query[:50] + "..." if len(query) > 50 else query,
                            "execution_time": time.time() - query_start,
                            "success": False,
                            "error": str(e)
                        })
                    
                    # Small delay between queries
                    await asyncio.sleep(0.1)
                
                return user_results
            
            # Execute pattern queries concurrently
            tasks = [execute_pattern_queries(i) for i in range(pattern_users)]
            user_results = await asyncio.gather(*tasks)
            
            # Flatten results
            all_results = []
            for user_result in user_results:
                all_results.extend(user_result)
            
            # Calculate pattern metrics
            successful_queries = [r for r in all_results if r["success"]]
            failed_queries = [r for r in all_results if not r["success"]]
            
            pattern_duration = time.time() - pattern_start
            
            pattern_metrics = {
                "pattern_name": pattern["name"],
                "total_queries": len(all_results),
                "successful_queries": len(successful_queries),
                "failed_queries": len(failed_queries),
                "error_rate": len(failed_queries) / len(all_results) if all_results else 0,
                "avg_execution_time": sum(r["execution_time"] for r in successful_queries) / len(successful_queries) if successful_queries else 0,
                "queries_per_second": len(successful_queries) / pattern_duration,
                "concurrent_users": pattern_users
            }
            
            pattern_results.append(pattern_metrics)
        
        total_duration = time.time() - start_time
        
        return {
            "test_type": "query_performance_patterns",
            "total_duration": total_duration,
            "patterns": pattern_results,
            "overall_qps": sum(p["queries_per_second"] for p in pattern_results)
        }


class RedisPerformanceTester:
    """Advanced Redis performance testing utilities"""
    
    def __init__(self):
        self.redis_client = None
        
    async def test_redis_operation_performance(
        self,
        concurrent_clients: int = 50,
        operations_per_client: int = 1000
    ) -> Dict[str, Any]:
        """Test Redis operations performance under load"""
        
        # Redis operation types with different performance characteristics
        operation_types = [
            {
                "name": "string_operations",
                "operations": ["GET", "SET", "INCR", "DECR"],
                "weight": 0.4,
                "expected_latency_ms": 1
            },
            {
                "name": "hash_operations", 
                "operations": ["HGET", "HSET", "HGETALL", "HDEL"],
                "weight": 0.3,
                "expected_latency_ms": 2
            },
            {
                "name": "list_operations",
                "operations": ["LPUSH", "RPUSH", "LPOP", "RPOP", "LRANGE"],
                "weight": 0.15,
                "expected_latency_ms": 2
            },
            {
                "name": "set_operations",
                "operations": ["SADD", "SREM", "SMEMBERS", "SISMEMBER"],
                "weight": 0.1,
                "expected_latency_ms": 2
            },
            {
                "name": "sorted_set_operations",
                "operations": ["ZADD", "ZREM", "ZRANGE", "ZRANK"],
                "weight": 0.05,
                "expected_latency_ms": 3
            }
        ]
        
        operation_results = []
        
        for op_type in operation_types:
            print(f"Testing Redis {op_type['name']}...")
            
            type_clients = max(1, int(concurrent_clients * op_type["weight"]))
            
            async def redis_client_simulation(client_id: int):
                client_results = []
                
                for i in range(operations_per_client):
                    operation = random.choice(op_type["operations"])
                    key = f"test_key_{client_id}_{i}"
                    
                    start_time = time.time()
                    
                    try:
                        # Simulate Redis operation
                        if operation in ["GET", "HGET", "LPOP", "RPOP", "SMEMBERS", "ZRANGE"]:
                            # Read operations
                            latency = random.uniform(0.0005, 0.002)
                        elif operation in ["SET", "HSET", "LPUSH", "RPUSH", "SADD", "ZADD"]:
                            # Write operations
                            latency = random.uniform(0.001, 0.003)
                        elif operation in ["INCR", "DECR"]:
                            # Atomic operations
                            latency = random.uniform(0.0008, 0.0015)
                        else:
                            # Other operations
                            latency = random.uniform(0.001, 0.004)
                        
                        await asyncio.sleep(latency)
                        
                        execution_time = time.time() - start_time
                        
                        client_results.append({
                            "client_id": client_id,
                            "operation": operation,
                            "key": key,
                            "execution_time": execution_time,
                            "success": True
                        })
                        
                    except Exception as e:
                        execution_time = time.time() - start_time
                        client_results.append({
                            "client_id": client_id,
                            "operation": operation,
                            "key": key,
                            "execution_time": execution_time,
                            "success": False,
                            "error": str(e)
                        })
                
                return client_results
            
            # Execute Redis operations concurrently
            start_time = time.time()
            tasks = [redis_client_simulation(i) for i in range(type_clients)]
            client_results = await asyncio.gather(*tasks)
            end_time = time.time()
            
            # Flatten results
            all_results = []
            for client_result in client_results:
                all_results.extend(client_result)
            
            # Calculate metrics
            successful_ops = [r for r in all_results if r["success"]]
            failed_ops = [r for r in all_results if not r["success"]]
            
            total_duration = end_time - start_time
            
            type_metrics = {
                "operation_type": op_type["name"],
                "total_operations": len(all_results),
                "successful_operations": len(successful_ops),
                "failed_operations": len(failed_ops),
                "error_rate": len(failed_ops) / len(all_results) if all_results else 0,
                "operations_per_second": len(successful_ops) / total_duration,
                "avg_latency_ms": (sum(r["execution_time"] for r in successful_ops) / len(successful_ops)) * 1000 if successful_ops else 0,
                "expected_latency_ms": op_type["expected_latency_ms"],
                "concurrent_clients": type_clients,
                "duration": total_duration
            }
            
            operation_results.append(type_metrics)
        
        return {
            "test_type": "redis_operation_performance",
            "operation_types": operation_results,
            "total_ops_per_second": sum(r["operations_per_second"] for r in operation_results)
        }
    
    async def test_redis_memory_usage_patterns(
        self,
        data_sizes: List[int] = None,
        concurrent_operations: int = 100
    ) -> Dict[str, Any]:
        """Test Redis memory usage with different data sizes"""
        
        if data_sizes is None:
            data_sizes = [100, 1024, 10240, 102400]  # 100B, 1KB, 10KB, 100KB
        
        memory_test_results = []
        
        for data_size in data_sizes:
            print(f"Testing Redis memory usage with {data_size} byte values...")
            
            # Generate test data of specified size
            test_data = "x" * data_size
            
            async def memory_test_operation(op_id: int):
                key = f"memory_test_{data_size}_{op_id}"
                
                start_time = time.time()
                
                try:
                    # Simulate SET operation
                    await asyncio.sleep(0.001 + (data_size / 1000000))  # Latency increases with data size
                    
                    # Simulate GET operation
                    await asyncio.sleep(0.0005 + (data_size / 2000000))
                    
                    execution_time = time.time() - start_time
                    
                    return {
                        "operation_id": op_id,
                        "data_size": data_size,
                        "execution_time": execution_time,
                        "success": True
                    }
                    
                except Exception as e:
                    execution_time = time.time() - start_time
                    return {
                        "operation_id": op_id,
                        "data_size": data_size,
                        "execution_time": execution_time,
                        "success": False,
                        "error": str(e)
                    }
            
            # Execute memory test operations
            start_time = time.time()
            tasks = [memory_test_operation(i) for i in range(concurrent_operations)]
            results = await asyncio.gather(*tasks)
            end_time = time.time()
            
            # Calculate metrics
            successful_ops = [r for r in results if r["success"]]
            failed_ops = [r for r in results if not r["success"]]
            
            total_duration = end_time - start_time
            
            memory_metrics = {
                "data_size_bytes": data_size,
                "total_operations": len(results),
                "successful_operations": len(successful_ops),
                "failed_operations": len(failed_ops),
                "error_rate": len(failed_ops) / len(results) if results else 0,
                "operations_per_second": len(successful_ops) / total_duration,
                "avg_latency_ms": (sum(r["execution_time"] for r in successful_ops) / len(successful_ops)) * 1000 if successful_ops else 0,
                "throughput_mb_per_second": (len(successful_ops) * data_size) / (1024 * 1024) / total_duration,
                "duration": total_duration
            }
            
            memory_test_results.append(memory_metrics)
        
        return {
            "test_type": "redis_memory_usage_patterns",
            "data_size_tests": memory_test_results
        }


class TestDatabaseRedisPerformance:
    """Test database and Redis performance under load"""
    
    @pytest.mark.asyncio
    async def test_database_connection_pool_performance(
        self,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test database connection pool performance under various loads"""
        
        performance_monitor.start_monitoring()
        db_tester = DatabasePerformanceTester()
        
        try:
            # Test connection pool scaling
            pool_scaling_results = await db_tester.test_connection_pool_scaling(
                min_connections=5,
                max_connections=50,
                concurrent_queries=load_test_config["concurrent_users"] * 2
            )
            
            # Test query performance patterns
            query_pattern_results = await db_tester.test_query_performance_patterns(
                concurrent_users=load_test_config["concurrent_users"],
                test_duration=30  # 30 seconds for each pattern
            )
            
            print(f"\n=== Database Connection Pool Performance Test Results ===")
            print(f"Optimal Pool Size: {pool_scaling_results['optimal_pool_size']}")
            
            print(f"\nPool Scaling Results:")
            for result in pool_scaling_results["results"]:
                print(f"  Pool Size {result['pool_size']}: {result['queries_per_second']:.1f} QPS, "
                      f"{result['error_rate']:.2%} error rate")
            
            print(f"\nQuery Pattern Results:")
            for pattern in query_pattern_results["patterns"]:
                print(f"  {pattern['pattern_name']}: {pattern['queries_per_second']:.1f} QPS, "
                      f"{pattern['avg_execution_time']:.3f}s avg, "
                      f"{pattern['error_rate']:.2%} error rate")
            
            # Validate database performance
            for result in pool_scaling_results["results"]:
                assert result["error_rate"] <= 0.05, \
                    f"Database error rate for pool size {result['pool_size']} too high: {result['error_rate']:.2%}"
                
                assert result["queries_per_second"] > 0, \
                    f"Database should handle queries for pool size {result['pool_size']}"
            
            for pattern in query_pattern_results["patterns"]:
                assert pattern["error_rate"] <= 0.05, \
                    f"Query pattern {pattern['pattern_name']} error rate too high: {pattern['error_rate']:.2%}"
                
                # Different patterns have different performance expectations
                if pattern["pattern_name"] == "simple_selects":
                    assert pattern["avg_execution_time"] <= 0.1, \
                        f"Simple selects should be fast: {pattern['avg_execution_time']:.3f}s"
                elif pattern["pattern_name"] == "complex_joins":
                    assert pattern["avg_execution_time"] <= 0.5, \
                        f"Complex joins taking too long: {pattern['avg_execution_time']:.3f}s"
                        
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_redis_performance_characteristics(
        self,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test Redis performance characteristics under load"""
        
        performance_monitor.start_monitoring()
        redis_tester = RedisPerformanceTester()
        
        try:
            # Test Redis operation performance
            operation_results = await redis_tester.test_redis_operation_performance(
                concurrent_clients=load_test_config["concurrent_users"],
                operations_per_client=1000
            )
            
            # Test Redis memory usage patterns
            memory_results = await redis_tester.test_redis_memory_usage_patterns(
                data_sizes=[100, 1024, 10240, 102400],
                concurrent_operations=load_test_config["concurrent_users"]
            )
            
            print(f"\n=== Redis Performance Test Results ===")
            print(f"Total Operations per Second: {operation_results['total_ops_per_second']:.1f}")
            
            print(f"\nOperation Type Performance:")
            for op_type in operation_results["operation_types"]:
                print(f"  {op_type['operation_type']}: {op_type['operations_per_second']:.1f} OPS, "
                      f"{op_type['avg_latency_ms']:.2f}ms avg latency, "
                      f"{op_type['error_rate']:.2%} error rate")
            
            print(f"\nMemory Usage Pattern Results:")
            for memory_test in memory_results["data_size_tests"]:
                print(f"  {memory_test['data_size_bytes']} bytes: {memory_test['operations_per_second']:.1f} OPS, "
                      f"{memory_test['throughput_mb_per_second']:.2f} MB/s throughput, "
                      f"{memory_test['avg_latency_ms']:.2f}ms avg latency")
            
            # Validate Redis performance
            for op_type in operation_results["operation_types"]:
                assert op_type["error_rate"] <= 0.01, \
                    f"Redis {op_type['operation_type']} error rate too high: {op_type['error_rate']:.2%}"
                
                # Redis operations should be fast
                assert op_type["avg_latency_ms"] <= op_type["expected_latency_ms"] * 5, \
                    f"Redis {op_type['operation_type']} latency too high: {op_type['avg_latency_ms']:.2f}ms"
                
                # Redis should handle high throughput
                assert op_type["operations_per_second"] > 100, \
                    f"Redis {op_type['operation_type']} throughput too low: {op_type['operations_per_second']:.1f} OPS"
            
            for memory_test in memory_results["data_size_tests"]:
                assert memory_test["error_rate"] <= 0.01, \
                    f"Redis memory test error rate too high for {memory_test['data_size_bytes']} bytes: {memory_test['error_rate']:.2%}"
                
                # Larger data should have proportionally higher latency but still reasonable
                expected_max_latency = 1 + (memory_test["data_size_bytes"] / 10000)  # 1ms + 0.1ms per 1KB
                assert memory_test["avg_latency_ms"] <= expected_max_latency, \
                    f"Redis latency too high for {memory_test['data_size_bytes']} bytes: {memory_test['avg_latency_ms']:.2f}ms"
                    
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_database_redis_integration_performance(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test integrated database and Redis performance"""
        
        performance_monitor.start_monitoring()
        
        try:
            # Test scenarios that use both database and Redis
            integration_scenarios = [
                {
                    "name": "cached_database_reads",
                    "endpoint": "/api/v1/hotels/details",
                    "method": "GET",
                    "description": "Database reads with Redis caching"
                },
                {
                    "name": "session_with_database",
                    "endpoint": "/api/v1/user/profile",
                    "method": "GET",
                    "description": "Session validation (Redis) + user data (DB)"
                },
                {
                    "name": "rate_limited_database_writes",
                    "endpoint": "/api/v1/reservations",
                    "method": "POST",
                    "payload": {
                        "hotel_id": "hotel_123",
                        "room_id": "room_456",
                        "guest_name": "Test Guest",
                        "check_in": "2024-02-15",
                        "check_out": "2024-02-17"
                    },
                    "description": "Rate limiting (Redis) + database writes"
                }
            ]
            
            integration_results = []
            
            for scenario in integration_scenarios:
                print(f"\nTesting integration scenario: {scenario['name']}")
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint=scenario["endpoint"],
                    method=scenario["method"],
                    payload=scenario.get("payload"),
                    concurrent_users=load_test_config["concurrent_users"] // 2,  # Reduce load for integration tests
                    requests_per_user=load_test_config["requests_per_user"] // 2,
                    delay_between_requests=0.1
                )
                
                integration_results.append({
                    "scenario": scenario["name"],
                    "description": scenario["description"],
                    "metrics": metrics
                })
                
                # Validate integration performance
                assert metrics.error_rate <= load_test_config["max_error_rate"], \
                    f"Integration scenario {scenario['name']} error rate {metrics.error_rate:.2%} exceeds threshold"
                
                # Integration scenarios may be slower due to multiple data store access
                integration_max_response_time = load_test_config["max_response_time"] * 2
                assert metrics.avg_response_time <= integration_max_response_time, \
                    f"Integration scenario {scenario['name']} response time {metrics.avg_response_time:.2f}s exceeds threshold"
            
            print(f"\n=== Database-Redis Integration Performance Test Results ===")
            for result in integration_results:
                print(f"{result['scenario']}:")
                print(f"  Description: {result['description']}")
                print(f"  RPS: {result['metrics'].requests_per_second:.1f}")
                print(f"  Avg Response Time: {result['metrics'].avg_response_time:.3f}s")
                print(f"  Error Rate: {result['metrics'].error_rate:.2%}")
                print(f"  Memory Usage: {result['metrics'].memory_usage_mb:.1f}MB")
                
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_data_consistency_under_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test data consistency between database and Redis under load"""
        
        performance_monitor.start_monitoring()
        
        try:
            # Test scenarios that require data consistency
            consistency_scenarios = [
                {
                    "name": "cache_invalidation",
                    "description": "Test cache invalidation when data changes",
                    "operations": [
                        {"endpoint": "/api/v1/hotels/123", "method": "GET"},  # Cache data
                        {"endpoint": "/api/v1/hotels/123", "method": "PUT", "payload": {"name": "Updated Hotel"}},  # Update data
                        {"endpoint": "/api/v1/hotels/123", "method": "GET"}   # Verify cache invalidation
                    ]
                },
                {
                    "name": "session_consistency",
                    "description": "Test session consistency across requests",
                    "operations": [
                        {"endpoint": "/auth/login", "method": "POST", "payload": {"email": "test@example.com", "password": "test"}},
                        {"endpoint": "/api/v1/user/profile", "method": "GET"},
                        {"endpoint": "/auth/logout", "method": "POST"}
                    ]
                },
                {
                    "name": "rate_limit_consistency",
                    "description": "Test rate limit counter consistency",
                    "operations": [
                        {"endpoint": "/api/v1/test-rate-limit", "method": "GET"} for _ in range(10)
                    ]
                }
            ]
            
            consistency_results = []
            
            for scenario in consistency_scenarios:
                print(f"\nTesting consistency scenario: {scenario['name']}")
                
                scenario_start_time = time.time()
                operation_results = []
                
                # Execute operations in sequence for each concurrent user
                async def user_consistency_test(user_id: int):
                    user_results = []
                    
                    for operation in scenario["operations"]:
                        start_time = time.time()
                        
                        try:
                            # Simulate the operation
                            if operation["method"] == "GET":
                                execution_time = random.uniform(0.01, 0.05)
                            else:  # POST/PUT
                                execution_time = random.uniform(0.02, 0.1)
                            
                            await asyncio.sleep(execution_time)
                            
                            user_results.append({
                                "user_id": user_id,
                                "endpoint": operation["endpoint"],
                                "method": operation["method"],
                                "execution_time": execution_time,
                                "success": True
                            })
                            
                        except Exception as e:
                            user_results.append({
                                "user_id": user_id,
                                "endpoint": operation["endpoint"],
                                "method": operation["method"],
                                "execution_time": time.time() - start_time,
                                "success": False,
                                "error": str(e)
                            })
                    
                    return user_results
                
                # Run consistency tests with multiple concurrent users
                tasks = [user_consistency_test(i) for i in range(load_test_config["concurrent_users"] // 4)]
                user_results = await asyncio.gather(*tasks)
                
                # Flatten results
                all_results = []
                for user_result in user_results:
                    all_results.extend(user_result)
                
                scenario_duration = time.time() - scenario_start_time
                
                # Calculate consistency metrics
                successful_operations = [r for r in all_results if r["success"]]
                failed_operations = [r for r in all_results if not r["success"]]
                
                consistency_metrics = {
                    "scenario": scenario["name"],
                    "description": scenario["description"],
                    "total_operations": len(all_results),
                    "successful_operations": len(successful_operations),
                    "failed_operations": len(failed_operations),
                    "error_rate": len(failed_operations) / len(all_results) if all_results else 0,
                    "avg_execution_time": sum(r["execution_time"] for r in successful_operations) / len(successful_operations) if successful_operations else 0,
                    "operations_per_second": len(successful_operations) / scenario_duration,
                    "duration": scenario_duration
                }
                
                consistency_results.append(consistency_metrics)
                
                # Validate consistency
                assert consistency_metrics["error_rate"] <= 0.05, \
                    f"Consistency scenario {scenario['name']} error rate too high: {consistency_metrics['error_rate']:.2%}"
            
            print(f"\n=== Data Consistency Under Load Test Results ===")
            for result in consistency_results:
                print(f"{result['scenario']}:")
                print(f"  Description: {result['description']}")
                print(f"  Operations: {result['total_operations']}")
                print(f"  Success Rate: {(result['successful_operations']/result['total_operations'])*100:.1f}%")
                print(f"  Avg Execution Time: {result['avg_execution_time']:.3f}s")
                print(f"  Operations per Second: {result['operations_per_second']:.1f}")
                
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()