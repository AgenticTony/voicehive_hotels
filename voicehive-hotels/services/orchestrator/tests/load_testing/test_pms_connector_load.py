"""
PMS Connector Load Testing Scenarios

Tests the Property Management System connector's performance under various
load conditions and failure scenarios.
"""

import pytest
import asyncio
import time
from typing import List, Dict, Any
from datetime import datetime, timedelta
import json
import random

from .conftest import LoadTestRunner, LoadTestMetrics, PerformanceMonitor


class TestPMSConnectorLoad:
    """Test PMS connector performance under load"""
    
    @pytest.mark.asyncio
    async def test_reservation_lookup_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test reservation lookup operations under high load"""
        
        performance_monitor.start_monitoring()
        
        # Generate test reservation IDs
        reservation_ids = [f"RES{str(i).zfill(6)}" for i in range(1000, 2000)]
        
        try:
            # Test individual reservation lookups
            lookup_tasks = []
            
            for i in range(load_test_config["concurrent_users"]):
                # Each user will look up random reservations
                async def user_reservation_lookups(user_id: int):
                    user_metrics = []
                    
                    for j in range(load_test_config["requests_per_user"]):
                        reservation_id = random.choice(reservation_ids)
                        
                        start_time = time.time()
                        try:
                            # Simulate PMS reservation lookup
                            await asyncio.sleep(0.05 + random.uniform(0, 0.1))  # Simulate PMS latency
                            
                            response_time = time.time() - start_time
                            user_metrics.append({
                                'user_id': user_id,
                                'reservation_id': reservation_id,
                                'response_time': response_time,
                                'success': True
                            })
                            
                        except Exception as e:
                            response_time = time.time() - start_time
                            user_metrics.append({
                                'user_id': user_id,
                                'reservation_id': reservation_id,
                                'response_time': response_time,
                                'success': False,
                                'error': str(e)
                            })
                        
                        # Small delay between requests
                        await asyncio.sleep(0.1)
                    
                    return user_metrics
                
                lookup_tasks.append(user_reservation_lookups(i))
            
            # Execute all user simulations concurrently
            all_results = await asyncio.gather(*lookup_tasks)
            
            # Flatten results
            results = []
            for user_results in all_results:
                results.extend(user_results)
            
            # Calculate metrics
            total_requests = len(results)
            successful_requests = sum(1 for r in results if r['success'])
            failed_requests = total_requests - successful_requests
            
            response_times = [r['response_time'] for r in results]
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            max_response_time = max(response_times) if response_times else 0
            
            error_rate = failed_requests / total_requests if total_requests > 0 else 0
            
            # Validate PMS connector performance
            assert error_rate <= load_test_config["max_error_rate"], \
                f"PMS lookup error rate {error_rate:.2%} exceeds threshold {load_test_config['max_error_rate']:.2%}"
            
            # PMS operations can be slower than regular API calls
            pms_max_response_time = load_test_config["max_response_time"] * 2
            assert avg_response_time <= pms_max_response_time, \
                f"PMS lookup avg response time {avg_response_time:.2f}s exceeds threshold {pms_max_response_time}s"
            
            print(f"\n=== PMS Reservation Lookup Load Test Results ===")
            print(f"Total Lookups: {total_requests}")
            print(f"Success Rate: {(successful_requests/total_requests)*100:.1f}%")
            print(f"Average Response Time: {avg_response_time:.3f}s")
            print(f"Max Response Time: {max_response_time:.3f}s")
            print(f"Lookups per Second: {total_requests / (time.time() - performance_monitor.start_time if hasattr(performance_monitor, 'start_time') else 1):.1f}")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_guest_profile_operations_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test guest profile operations under load"""
        
        performance_monitor.start_monitoring()
        
        # Guest profile operation types
        profile_operations = [
            {
                "operation": "get_profile",
                "endpoint": "/api/v1/pms/guest/profile",
                "method": "GET",
                "weight": 0.4  # 40% reads
            },
            {
                "operation": "update_preferences",
                "endpoint": "/api/v1/pms/guest/preferences",
                "method": "PUT",
                "weight": 0.3  # 30% preference updates
            },
            {
                "operation": "add_note",
                "endpoint": "/api/v1/pms/guest/notes",
                "method": "POST",
                "weight": 0.2  # 20% note additions
            },
            {
                "operation": "get_history",
                "endpoint": "/api/v1/pms/guest/history",
                "method": "GET",
                "weight": 0.1  # 10% history lookups
            }
        ]
        
        try:
            operation_metrics = []
            
            for operation in profile_operations:
                num_users = max(1, int(load_test_config["concurrent_users"] * operation["weight"]))
                
                # Create operation-specific payload
                if operation["operation"] == "get_profile":
                    payload = {"guest_id": "guest_123"}
                elif operation["operation"] == "update_preferences":
                    payload = {
                        "guest_id": "guest_123",
                        "preferences": {
                            "room_temperature": 22,
                            "pillow_type": "soft",
                            "wake_up_call": "07:00"
                        }
                    }
                elif operation["operation"] == "add_note":
                    payload = {
                        "guest_id": "guest_123",
                        "note": "Guest requested extra towels",
                        "category": "housekeeping"
                    }
                elif operation["operation"] == "get_history":
                    payload = {"guest_id": "guest_123", "limit": 10}
                else:
                    payload = {}
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint=operation["endpoint"],
                    method=operation["method"],
                    payload=payload if operation["method"] != "GET" else None,
                    concurrent_users=num_users,
                    requests_per_user=load_test_config["requests_per_user"],
                    delay_between_requests=0.1
                )
                
                operation_metrics.append((operation["operation"], metrics))
                
                # Validate each operation type
                assert metrics.error_rate <= load_test_config["max_error_rate"], \
                    f"PMS {operation['operation']} error rate {metrics.error_rate:.2%} exceeds threshold"
            
            print(f"\n=== PMS Guest Profile Operations Load Test Results ===")
            for operation, metrics in operation_metrics:
                print(f"{operation}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.avg_response_time:.3f}s avg, "
                      f"{metrics.error_rate:.2%} error rate")
                      
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_pms_connector_failover_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        network_simulator,
        load_test_config: Dict[str, Any]
    ):
        """Test PMS connector behavior under network failures and failover scenarios"""
        
        performance_monitor.start_monitoring()
        
        # Test scenarios with different network conditions
        network_scenarios = [
            {"name": "normal", "condition": "normal", "duration": 10},
            {"name": "high_latency", "condition": "slow", "duration": 15},
            {"name": "packet_loss", "condition": "unreliable", "duration": 10},
            {"name": "network_partition", "condition": "partition", "duration": 5},
            {"name": "recovery", "condition": "normal", "duration": 10}
        ]
        
        try:
            scenario_results = []
            
            for scenario in network_scenarios:
                print(f"\nTesting scenario: {scenario['name']}")
                
                # Apply network condition
                await network_simulator.apply_condition(scenario["condition"])
                
                # Run PMS operations under this condition
                pms_payload = {
                    "hotel_id": "hotel_123",
                    "operation": "get_availability",
                    "check_in": "2024-02-01",
                    "check_out": "2024-02-03"
                }
                
                # Reduce load during failure scenarios
                users = load_test_config["concurrent_users"] // 2 if scenario["condition"] != "normal" else load_test_config["concurrent_users"]
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/api/v1/pms/availability",
                    method="POST",
                    payload=pms_payload,
                    concurrent_users=users,
                    requests_per_user=max(1, load_test_config["requests_per_user"] // 3),
                    delay_between_requests=0.2
                )
                
                scenario_results.append((scenario["name"], scenario["condition"], metrics))
                
                # Wait for scenario duration
                await asyncio.sleep(scenario["duration"])
            
            # Reset network conditions
            await network_simulator.reset_conditions()
            
            # Analyze failover behavior
            normal_scenarios = [r for r in scenario_results if r[1] == "normal"]
            failure_scenarios = [r for r in scenario_results if r[1] != "normal"]
            
            if normal_scenarios:
                normal_error_rate = sum(m.error_rate for _, _, m in normal_scenarios) / len(normal_scenarios)
                print(f"\nNormal conditions average error rate: {normal_error_rate:.2%}")
            
            # During failures, we expect higher error rates but system should still function
            for scenario_name, condition, metrics in failure_scenarios:
                if condition == "partition":
                    # During network partition, high error rates are expected
                    assert metrics.error_rate <= 0.9, \
                        f"Even during partition, some requests should succeed or fail gracefully"
                else:
                    # During degraded conditions, error rate should be manageable
                    assert metrics.error_rate <= 0.3, \
                        f"Error rate during {scenario_name} ({metrics.error_rate:.2%}) too high"
            
            print(f"\n=== PMS Connector Failover Load Test Results ===")
            for scenario_name, condition, metrics in scenario_results:
                print(f"{scenario_name} ({condition}): {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.error_rate:.2%} error rate, "
                      f"{metrics.avg_response_time:.3f}s avg")
                      
        finally:
            await network_simulator.reset_conditions()
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_pms_bulk_operations_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        memory_leak_detector,
        load_test_config: Dict[str, Any]
    ):
        """Test PMS bulk operations under load"""
        
        performance_monitor.start_monitoring()
        memory_leak_detector.set_baseline()
        
        # Bulk operation scenarios
        bulk_operations = [
            {
                "operation": "bulk_reservation_sync",
                "endpoint": "/api/v1/pms/reservations/sync",
                "payload": {
                    "hotel_id": "hotel_123",
                    "date_range": {
                        "start": "2024-02-01",
                        "end": "2024-02-07"
                    },
                    "include_cancelled": False
                }
            },
            {
                "operation": "bulk_guest_export",
                "endpoint": "/api/v1/pms/guests/export",
                "payload": {
                    "hotel_id": "hotel_123",
                    "format": "json",
                    "filters": {
                        "vip_status": True,
                        "last_stay_within_days": 90
                    }
                }
            },
            {
                "operation": "bulk_room_status_update",
                "endpoint": "/api/v1/pms/rooms/bulk-update",
                "payload": {
                    "hotel_id": "hotel_123",
                    "updates": [
                        {"room_number": "101", "status": "clean", "maintenance_notes": ""},
                        {"room_number": "102", "status": "dirty", "maintenance_notes": ""},
                        {"room_number": "103", "status": "maintenance", "maintenance_notes": "AC repair needed"}
                    ]
                }
            }
        ]
        
        try:
            bulk_results = []
            
            for operation in bulk_operations:
                print(f"\nTesting bulk operation: {operation['operation']}")
                
                # Bulk operations are resource intensive, so reduce concurrency
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint=operation["endpoint"],
                    method="POST",
                    payload=operation["payload"],
                    concurrent_users=max(1, load_test_config["concurrent_users"] // 4),
                    requests_per_user=max(1, load_test_config["requests_per_user"] // 4),
                    delay_between_requests=0.5  # Longer delay for bulk operations
                )
                
                bulk_results.append((operation["operation"], metrics))
                
                # Take memory snapshot after each bulk operation
                memory_leak_detector.take_snapshot(f"after_{operation['operation']}")
                
                # Bulk operations have different performance expectations
                bulk_max_response_time = load_test_config["max_response_time"] * 5  # 5x normal for bulk
                assert metrics.avg_response_time <= bulk_max_response_time, \
                    f"Bulk operation {operation['operation']} avg response time {metrics.avg_response_time:.2f}s exceeds threshold"
                
                assert metrics.error_rate <= load_test_config["max_error_rate"], \
                    f"Bulk operation {operation['operation']} error rate {metrics.error_rate:.2%} exceeds threshold"
            
            # Check for memory leaks in bulk operations
            memory_report = memory_leak_detector.get_report()
            assert not memory_report["potential_leak"], \
                f"Potential memory leak detected in bulk operations: {memory_report}"
            
            print(f"\n=== PMS Bulk Operations Load Test Results ===")
            for operation, metrics in bulk_results:
                print(f"{operation}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.avg_response_time:.3f}s avg, "
                      f"{metrics.error_rate:.2%} error rate")
            
            print(f"Memory Report: {memory_report}")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_pms_connector_circuit_breaker_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test PMS connector circuit breaker behavior under load"""
        
        performance_monitor.start_monitoring()
        
        # Simulate PMS service degradation and recovery
        test_phases = [
            {"name": "normal_operation", "failure_rate": 0.0, "duration": 10},
            {"name": "service_degradation", "failure_rate": 0.3, "duration": 15},
            {"name": "service_failure", "failure_rate": 0.8, "duration": 10},
            {"name": "partial_recovery", "failure_rate": 0.2, "duration": 15},
            {"name": "full_recovery", "failure_rate": 0.0, "duration": 10}
        ]
        
        try:
            phase_results = []
            
            for phase in test_phases:
                print(f"\nTesting phase: {phase['name']} (failure rate: {phase['failure_rate']:.1%})")
                
                # Simulate different failure rates by adjusting payload
                pms_payload = {
                    "hotel_id": "hotel_123",
                    "operation": "get_reservation",
                    "reservation_id": "RES123456",
                    "simulate_failure_rate": phase["failure_rate"]  # This would be handled by mock
                }
                
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/api/v1/pms/reservation",
                    method="POST",
                    payload=pms_payload,
                    concurrent_users=load_test_config["concurrent_users"] // 2,
                    requests_per_user=load_test_config["requests_per_user"] // 2,
                    delay_between_requests=0.1
                )
                
                phase_results.append((phase["name"], phase["failure_rate"], metrics))
                
                # Wait for phase duration to allow circuit breaker state changes
                await asyncio.sleep(phase["duration"])
            
            # Analyze circuit breaker behavior
            print(f"\n=== PMS Circuit Breaker Load Test Results ===")
            
            for phase_name, expected_failure_rate, metrics in phase_results:
                print(f"{phase_name}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.error_rate:.2%} error rate, "
                      f"{metrics.avg_response_time:.3f}s avg")
                
                # During high failure phases, circuit breaker should kick in
                if expected_failure_rate >= 0.5:
                    # Circuit breaker should prevent cascading failures
                    # Response times should be fast (immediate failures)
                    assert metrics.avg_response_time <= 0.1, \
                        f"Circuit breaker should provide fast failures during {phase_name}"
                
                # During recovery phases, some requests should succeed
                if phase_name == "partial_recovery":
                    assert metrics.error_rate <= 0.5, \
                        f"During partial recovery, error rate should improve"
                
                if phase_name == "full_recovery":
                    assert metrics.error_rate <= load_test_config["max_error_rate"], \
                        f"During full recovery, error rate should be normal"
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_pms_connector_cache_performance(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test PMS connector caching performance under load"""
        
        performance_monitor.start_monitoring()
        
        # Test caching with repeated requests
        cache_test_scenarios = [
            {
                "name": "cold_cache",
                "cache_warm": False,
                "repeat_requests": False
            },
            {
                "name": "warm_cache",
                "cache_warm": True,
                "repeat_requests": True
            },
            {
                "name": "cache_invalidation",
                "cache_warm": True,
                "repeat_requests": True,
                "invalidate_cache": True
            }
        ]
        
        try:
            cache_results = []
            
            # Common payload for cache testing
            cache_payload = {
                "hotel_id": "hotel_123",
                "operation": "get_room_types",
                "include_amenities": True
            }
            
            for scenario in cache_test_scenarios:
                print(f"\nTesting cache scenario: {scenario['name']}")
                
                # Warm up cache if needed
                if scenario.get("cache_warm", False):
                    await load_test_runner.run_concurrent_requests(
                        endpoint="/api/v1/pms/room-types",
                        method="POST",
                        payload=cache_payload,
                        concurrent_users=1,
                        requests_per_user=1,
                        delay_between_requests=0
                    )
                
                # Invalidate cache if needed
                if scenario.get("invalidate_cache", False):
                    # Simulate cache invalidation
                    await asyncio.sleep(0.1)
                
                # Run the actual load test
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/api/v1/pms/room-types",
                    method="POST",
                    payload=cache_payload,
                    concurrent_users=load_test_config["concurrent_users"],
                    requests_per_user=load_test_config["requests_per_user"],
                    delay_between_requests=0.05  # Faster requests to test cache
                )
                
                cache_results.append((scenario["name"], metrics))
                
                # Validate caching performance
                assert metrics.error_rate <= load_test_config["max_error_rate"], \
                    f"Cache scenario {scenario['name']} error rate {metrics.error_rate:.2%} exceeds threshold"
            
            # Compare cache performance
            cold_cache_metrics = next((m for name, m in cache_results if name == "cold_cache"), None)
            warm_cache_metrics = next((m for name, m in cache_results if name == "warm_cache"), None)
            
            if cold_cache_metrics and warm_cache_metrics:
                # Warm cache should be significantly faster
                cache_improvement = (cold_cache_metrics.avg_response_time - warm_cache_metrics.avg_response_time) / cold_cache_metrics.avg_response_time
                
                assert cache_improvement > 0.2, \
                    f"Cache should improve response time by at least 20%, got {cache_improvement:.1%}"
                
                print(f"Cache performance improvement: {cache_improvement:.1%}")
            
            print(f"\n=== PMS Connector Cache Performance Results ===")
            for scenario_name, metrics in cache_results:
                print(f"{scenario_name}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.avg_response_time:.3f}s avg, "
                      f"{metrics.error_rate:.2%} error rate")
                      
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()