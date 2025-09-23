"""
Network Partition and Failure Simulation Testing

Tests system resilience under various network conditions including
partitions, high latency, packet loss, and service failures.
"""

import pytest
import asyncio
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import random
from enum import Enum

from .conftest import LoadTestRunner, LoadTestMetrics, PerformanceMonitor


class NetworkCondition(Enum):
    """Network condition types for simulation"""
    NORMAL = "normal"
    HIGH_LATENCY = "high_latency"
    PACKET_LOSS = "packet_loss"
    BANDWIDTH_LIMITED = "bandwidth_limited"
    INTERMITTENT = "intermittent"
    PARTITION = "partition"


class NetworkFailureSimulator:
    """Simulate various network failure conditions"""
    
    def __init__(self):
        self.current_condition = NetworkCondition.NORMAL
        self.condition_start_time = None
        self.failure_patterns = {}
        
    async def apply_condition(
        self, 
        condition: NetworkCondition, 
        severity: float = 0.5,
        duration: Optional[float] = None
    ):
        """Apply a network condition with specified severity"""
        
        self.current_condition = condition
        self.condition_start_time = time.time()
        
        condition_config = {
            NetworkCondition.NORMAL: {
                "latency_ms": 0,
                "packet_loss_rate": 0.0,
                "bandwidth_limit_mbps": None,
                "jitter_ms": 0
            },
            NetworkCondition.HIGH_LATENCY: {
                "latency_ms": 100 + (severity * 400),  # 100-500ms
                "packet_loss_rate": 0.0,
                "bandwidth_limit_mbps": None,
                "jitter_ms": 10 + (severity * 40)  # 10-50ms jitter
            },
            NetworkCondition.PACKET_LOSS: {
                "latency_ms": 20,
                "packet_loss_rate": 0.01 + (severity * 0.19),  # 1-20% loss
                "bandwidth_limit_mbps": None,
                "jitter_ms": 5
            },
            NetworkCondition.BANDWIDTH_LIMITED: {
                "latency_ms": 10,
                "packet_loss_rate": 0.0,
                "bandwidth_limit_mbps": 10 - (severity * 9),  # 10-1 Mbps
                "jitter_ms": 2
            },
            NetworkCondition.INTERMITTENT: {
                "latency_ms": 50,
                "packet_loss_rate": 0.05,
                "bandwidth_limit_mbps": None,
                "jitter_ms": 20,
                "intermittent_failure_rate": severity  # 0-100% intermittent failures
            },
            NetworkCondition.PARTITION: {
                "latency_ms": float('inf'),
                "packet_loss_rate": 1.0,  # 100% packet loss = partition
                "bandwidth_limit_mbps": 0,
                "jitter_ms": 0
            }
        }
        
        self.failure_patterns[condition] = condition_config[condition]
        
        print(f"Applied network condition: {condition.value} (severity: {severity:.1%})")
        if duration:
            print(f"Duration: {duration}s")
            
    async def simulate_request_delay(self, base_delay: float = 0.0) -> float:
        """Simulate network delay for a request based on current conditions"""
        
        if self.current_condition == NetworkCondition.NORMAL:
            return base_delay
            
        config = self.failure_patterns.get(self.current_condition, {})
        
        # Calculate total delay
        total_delay = base_delay
        
        # Add latency
        latency_ms = config.get("latency_ms", 0)
        if latency_ms != float('inf'):
            total_delay += latency_ms / 1000.0
            
            # Add jitter
            jitter_ms = config.get("jitter_ms", 0)
            if jitter_ms > 0:
                jitter = random.uniform(-jitter_ms, jitter_ms) / 1000.0
                total_delay += jitter
        
        # Simulate packet loss (request fails)
        packet_loss_rate = config.get("packet_loss_rate", 0.0)
        if random.random() < packet_loss_rate:
            raise ConnectionError("Simulated packet loss")
        
        # Simulate intermittent failures
        intermittent_rate = config.get("intermittent_failure_rate", 0.0)
        if random.random() < intermittent_rate:
            raise TimeoutError("Simulated intermittent failure")
        
        # Simulate bandwidth limitations (affects large requests)
        bandwidth_limit = config.get("bandwidth_limit_mbps")
        if bandwidth_limit and bandwidth_limit > 0:
            # Assume 1KB request size, add delay based on bandwidth
            request_size_mb = 0.001  # 1KB
            bandwidth_delay = request_size_mb / bandwidth_limit
            total_delay += bandwidth_delay
        
        return total_delay
        
    async def reset_conditions(self):
        """Reset to normal network conditions"""
        await self.apply_condition(NetworkCondition.NORMAL)
        self.failure_patterns.clear()


class ServiceFailureSimulator:
    """Simulate various service failure scenarios"""
    
    def __init__(self):
        self.failed_services = set()
        self.degraded_services = {}
        
    async def fail_service(self, service_name: str, failure_type: str = "complete"):
        """Simulate service failure"""
        
        if failure_type == "complete":
            self.failed_services.add(service_name)
        elif failure_type == "degraded":
            self.degraded_services[service_name] = {
                "error_rate": 0.3,
                "latency_multiplier": 3.0
            }
        elif failure_type == "slow":
            self.degraded_services[service_name] = {
                "error_rate": 0.1,
                "latency_multiplier": 5.0
            }
            
        print(f"Simulated {failure_type} failure for service: {service_name}")
        
    async def recover_service(self, service_name: str):
        """Recover a failed service"""
        
        if service_name in self.failed_services:
            self.failed_services.remove(service_name)
            
        if service_name in self.degraded_services:
            del self.degraded_services[service_name]
            
        print(f"Recovered service: {service_name}")
        
    async def simulate_service_call(
        self, 
        service_name: str, 
        base_latency: float = 0.05
    ) -> Dict[str, Any]:
        """Simulate a service call with potential failures"""
        
        # Check if service is completely failed
        if service_name in self.failed_services:
            raise ConnectionError(f"Service {service_name} is unavailable")
        
        # Check if service is degraded
        if service_name in self.degraded_services:
            degradation = self.degraded_services[service_name]
            
            # Simulate increased error rate
            if random.random() < degradation["error_rate"]:
                raise Exception(f"Service {service_name} error (degraded)")
            
            # Simulate increased latency
            actual_latency = base_latency * degradation["latency_multiplier"]
        else:
            actual_latency = base_latency
        
        # Simulate service call
        await asyncio.sleep(actual_latency)
        
        return {
            "service": service_name,
            "latency": actual_latency,
            "status": "success"
        }


class TestNetworkFailureSimulation:
    """Test system resilience under network failures"""
    
    @pytest.mark.asyncio
    async def test_high_latency_resilience(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test system behavior under high network latency"""
        
        performance_monitor.start_monitoring()
        network_simulator = NetworkFailureSimulator()
        
        try:
            # Test different latency levels
            latency_scenarios = [
                {"name": "normal", "condition": NetworkCondition.NORMAL, "severity": 0.0},
                {"name": "moderate_latency", "condition": NetworkCondition.HIGH_LATENCY, "severity": 0.3},
                {"name": "high_latency", "condition": NetworkCondition.HIGH_LATENCY, "severity": 0.7},
                {"name": "extreme_latency", "condition": NetworkCondition.HIGH_LATENCY, "severity": 1.0}
            ]
            
            latency_results = []
            
            for scenario in latency_scenarios:
                print(f"\nTesting latency scenario: {scenario['name']}")
                
                # Apply network condition
                await network_simulator.apply_condition(
                    scenario["condition"], 
                    severity=scenario["severity"]
                )
                
                # Custom load test runner that simulates network delays
                async def latency_aware_request(endpoint: str, method: str = "GET", payload: Dict = None):
                    start_time = time.time()
                    
                    try:
                        # Simulate network delay
                        network_delay = await network_simulator.simulate_request_delay(0.01)
                        await asyncio.sleep(network_delay)
                        
                        # Simulate successful response
                        return {
                            "status_code": 200,
                            "response_time": time.time() - start_time,
                            "success": True
                        }
                        
                    except Exception as e:
                        return {
                            "status_code": 0,
                            "response_time": time.time() - start_time,
                            "success": False,
                            "error": str(e)
                        }
                
                # Run concurrent requests with simulated latency
                start_time = time.time()
                tasks = []
                
                for user_id in range(load_test_config["concurrent_users"] // 2):
                    for req_id in range(load_test_config["requests_per_user"] // 2):
                        task = latency_aware_request("/api/v1/health")
                        tasks.append(task)
                
                results = await asyncio.gather(*tasks)
                end_time = time.time()
                
                # Calculate metrics
                successful_requests = [r for r in results if r["success"]]
                failed_requests = [r for r in results if not r["success"]]
                
                total_requests = len(results)
                error_rate = len(failed_requests) / total_requests if total_requests > 0 else 0
                
                response_times = [r["response_time"] for r in successful_requests]
                avg_response_time = sum(response_times) / len(response_times) if response_times else 0
                
                scenario_metrics = {
                    "scenario": scenario["name"],
                    "condition": scenario["condition"].value,
                    "severity": scenario["severity"],
                    "total_requests": total_requests,
                    "successful_requests": len(successful_requests),
                    "failed_requests": len(failed_requests),
                    "error_rate": error_rate,
                    "avg_response_time": avg_response_time,
                    "requests_per_second": len(successful_requests) / (end_time - start_time)
                }
                
                latency_results.append(scenario_metrics)
                
                # Wait between scenarios
                await asyncio.sleep(2)
            
            # Reset network conditions
            await network_simulator.reset_conditions()
            
            # Analyze latency resilience
            print(f"\n=== High Latency Resilience Test Results ===")
            
            for result in latency_results:
                print(f"{result['scenario']} (severity: {result['severity']:.1%}):")
                print(f"  Success Rate: {((result['successful_requests']/result['total_requests'])*100):.1f}%")
                print(f"  Avg Response Time: {result['avg_response_time']:.3f}s")
                print(f"  RPS: {result['requests_per_second']:.1f}")
                print(f"  Error Rate: {result['error_rate']:.2%}")
            
            # Validate latency resilience
            normal_result = next(r for r in latency_results if r["scenario"] == "normal")
            
            for result in latency_results:
                if result["scenario"] != "normal":
                    # Under high latency, error rate should not exceed 50%
                    assert result["error_rate"] <= 0.5, \
                        f"Error rate under {result['scenario']} too high: {result['error_rate']:.2%}"
                    
                    # Response time should increase proportionally but system should still respond
                    if result["severity"] < 1.0:  # Not extreme latency
                        assert result["requests_per_second"] > 0, \
                            f"System should still process requests under {result['scenario']}"
                            
        finally:
            await network_simulator.reset_conditions()
            performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_packet_loss_resilience(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test system behavior under packet loss conditions"""
        
        performance_monitor.start_monitoring()
        network_simulator = NetworkFailureSimulator()
        
        try:
            # Test different packet loss rates
            packet_loss_scenarios = [
                {"name": "no_loss", "severity": 0.0},
                {"name": "light_loss", "severity": 0.1},  # 2% loss
                {"name": "moderate_loss", "severity": 0.3},  # 6% loss
                {"name": "heavy_loss", "severity": 0.7},  # 14% loss
                {"name": "severe_loss", "severity": 1.0}   # 20% loss
            ]
            
            packet_loss_results = []
            
            for scenario in packet_loss_scenarios:
                print(f"\nTesting packet loss scenario: {scenario['name']}")
                
                # Apply packet loss condition
                await network_simulator.apply_condition(
                    NetworkCondition.PACKET_LOSS,
                    severity=scenario["severity"]
                )
                
                # Test with retry logic simulation
                async def packet_loss_aware_request(endpoint: str, max_retries: int = 3):
                    for attempt in range(max_retries + 1):
                        start_time = time.time()
                        
                        try:
                            # Simulate network delay and potential packet loss
                            network_delay = await network_simulator.simulate_request_delay(0.01)
                            await asyncio.sleep(network_delay)
                            
                            return {
                                "status_code": 200,
                                "response_time": time.time() - start_time,
                                "success": True,
                                "attempts": attempt + 1
                            }
                            
                        except (ConnectionError, TimeoutError) as e:
                            if attempt == max_retries:
                                return {
                                    "status_code": 0,
                                    "response_time": time.time() - start_time,
                                    "success": False,
                                    "attempts": attempt + 1,
                                    "error": str(e)
                                }
                            # Wait before retry
                            await asyncio.sleep(0.1 * (attempt + 1))  # Exponential backoff
                
                # Run requests with retry logic
                start_time = time.time()
                tasks = []
                
                for user_id in range(load_test_config["concurrent_users"] // 3):
                    for req_id in range(load_test_config["requests_per_user"] // 3):
                        task = packet_loss_aware_request("/api/v1/health")
                        tasks.append(task)
                
                results = await asyncio.gather(*tasks)
                end_time = time.time()
                
                # Calculate metrics
                successful_requests = [r for r in results if r["success"]]
                failed_requests = [r for r in results if not r["success"]]
                
                total_requests = len(results)
                error_rate = len(failed_requests) / total_requests if total_requests > 0 else 0
                
                # Calculate retry statistics
                retry_stats = {}
                for result in results:
                    attempts = result.get("attempts", 1)
                    retry_stats[attempts] = retry_stats.get(attempts, 0) + 1
                
                avg_attempts = sum(r.get("attempts", 1) for r in results) / len(results)
                
                scenario_metrics = {
                    "scenario": scenario["name"],
                    "severity": scenario["severity"],
                    "total_requests": total_requests,
                    "successful_requests": len(successful_requests),
                    "failed_requests": len(failed_requests),
                    "error_rate": error_rate,
                    "avg_attempts": avg_attempts,
                    "retry_distribution": retry_stats,
                    "requests_per_second": len(successful_requests) / (end_time - start_time)
                }
                
                packet_loss_results.append(scenario_metrics)
                
                # Wait between scenarios
                await asyncio.sleep(2)
            
            # Reset network conditions
            await network_simulator.reset_conditions()
            
            print(f"\n=== Packet Loss Resilience Test Results ===")
            
            for result in packet_loss_results:
                print(f"{result['scenario']} (loss rate: ~{result['severity']*20:.1f}%):")
                print(f"  Success Rate: {((result['successful_requests']/result['total_requests'])*100):.1f}%")
                print(f"  Avg Attempts: {result['avg_attempts']:.1f}")
                print(f"  RPS: {result['requests_per_second']:.1f}")
                print(f"  Retry Distribution: {result['retry_distribution']}")
            
            # Validate packet loss resilience
            for result in packet_loss_results:
                # Even with severe packet loss, retry logic should achieve reasonable success rate
                if result["severity"] <= 0.7:  # Up to 14% loss
                    assert result["error_rate"] <= 0.1, \
                        f"Error rate under {result['scenario']} too high: {result['error_rate']:.2%}"
                
                # Retry logic should be working (more attempts under higher loss)
                if result["severity"] > 0.1:
                    assert result["avg_attempts"] > 1.0, \
                        f"Retry logic should be active under {result['scenario']}"
                        
        finally:
            await network_simulator.reset_conditions()
            performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_service_failure_resilience(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test system resilience when external services fail"""
        
        performance_monitor.start_monitoring()
        service_simulator = ServiceFailureSimulator()
        
        try:
            # Test different service failure scenarios
            service_failure_scenarios = [
                {
                    "name": "pms_complete_failure",
                    "failed_services": ["pms_connector"],
                    "failure_type": "complete"
                },
                {
                    "name": "tts_degraded",
                    "failed_services": ["tts_service"],
                    "failure_type": "degraded"
                },
                {
                    "name": "multiple_service_degradation",
                    "failed_services": ["pms_connector", "tts_service"],
                    "failure_type": "degraded"
                },
                {
                    "name": "database_slow",
                    "failed_services": ["database"],
                    "failure_type": "slow"
                }
            ]
            
            service_failure_results = []
            
            for scenario in service_failure_scenarios:
                print(f"\nTesting service failure scenario: {scenario['name']}")
                
                # Apply service failures
                for service in scenario["failed_services"]:
                    await service_simulator.fail_service(service, scenario["failure_type"])
                
                # Test system behavior with service failures
                async def service_aware_request(endpoint: str, expected_services: List[str]):
                    start_time = time.time()
                    
                    try:
                        # Simulate calls to various services
                        service_results = {}
                        
                        for service in expected_services:
                            try:
                                result = await service_simulator.simulate_service_call(service)
                                service_results[service] = result
                            except Exception as e:
                                service_results[service] = {"error": str(e)}
                        
                        # Determine if request can succeed with available services
                        critical_services = ["database"]  # Services that are critical
                        optional_services = ["pms_connector", "tts_service"]  # Services with fallbacks
                        
                        critical_failures = [s for s in critical_services if s in expected_services and "error" in service_results.get(s, {})]
                        
                        if critical_failures:
                            # Critical service failed, request fails
                            return {
                                "status_code": 503,
                                "response_time": time.time() - start_time,
                                "success": False,
                                "service_results": service_results,
                                "critical_failures": critical_failures
                            }
                        else:
                            # Request succeeds, possibly with degraded functionality
                            return {
                                "status_code": 200,
                                "response_time": time.time() - start_time,
                                "success": True,
                                "service_results": service_results
                            }
                            
                    except Exception as e:
                        return {
                            "status_code": 500,
                            "response_time": time.time() - start_time,
                            "success": False,
                            "error": str(e)
                        }
                
                # Test different endpoints that depend on different services
                endpoint_tests = [
                    {
                        "endpoint": "/api/v1/health",
                        "services": ["database"],
                        "weight": 0.3
                    },
                    {
                        "endpoint": "/api/v1/reservations",
                        "services": ["database", "pms_connector"],
                        "weight": 0.4
                    },
                    {
                        "endpoint": "/api/v1/tts/synthesize",
                        "services": ["database", "tts_service"],
                        "weight": 0.3
                    }
                ]
                
                endpoint_results = []
                
                for endpoint_test in endpoint_tests:
                    num_requests = int(load_test_config["concurrent_users"] * endpoint_test["weight"] * 10)
                    
                    tasks = [
                        service_aware_request(endpoint_test["endpoint"], endpoint_test["services"])
                        for _ in range(num_requests)
                    ]
                    
                    start_time = time.time()
                    results = await asyncio.gather(*tasks)
                    end_time = time.time()
                    
                    successful_requests = [r for r in results if r["success"]]
                    failed_requests = [r for r in results if not r["success"]]
                    
                    endpoint_metrics = {
                        "endpoint": endpoint_test["endpoint"],
                        "services": endpoint_test["services"],
                        "total_requests": len(results),
                        "successful_requests": len(successful_requests),
                        "failed_requests": len(failed_requests),
                        "error_rate": len(failed_requests) / len(results) if results else 0,
                        "avg_response_time": sum(r["response_time"] for r in successful_requests) / len(successful_requests) if successful_requests else 0,
                        "requests_per_second": len(successful_requests) / (end_time - start_time)
                    }
                    
                    endpoint_results.append(endpoint_metrics)
                
                scenario_metrics = {
                    "scenario": scenario["name"],
                    "failed_services": scenario["failed_services"],
                    "failure_type": scenario["failure_type"],
                    "endpoint_results": endpoint_results
                }
                
                service_failure_results.append(scenario_metrics)
                
                # Recover services for next scenario
                for service in scenario["failed_services"]:
                    await service_simulator.recover_service(service)
                
                # Wait between scenarios
                await asyncio.sleep(2)
            
            print(f"\n=== Service Failure Resilience Test Results ===")
            
            for result in service_failure_results:
                print(f"\n{result['scenario']} ({result['failure_type']} failure):")
                print(f"  Failed Services: {result['failed_services']}")
                
                for endpoint_result in result["endpoint_results"]:
                    print(f"  {endpoint_result['endpoint']}:")
                    print(f"    Success Rate: {((endpoint_result['successful_requests']/endpoint_result['total_requests'])*100):.1f}%")
                    print(f"    Avg Response Time: {endpoint_result['avg_response_time']:.3f}s")
                    print(f"    RPS: {endpoint_result['requests_per_second']:.1f}")
            
            # Validate service failure resilience
            for result in service_failure_results:
                for endpoint_result in result["endpoint_results"]:
                    endpoint_services = set(endpoint_result["services"])
                    failed_services = set(result["failed_services"])
                    
                    # If no critical services failed, endpoint should mostly work
                    if "database" not in failed_services:
                        if result["failure_type"] == "degraded":
                            # Degraded services should still allow some success
                            assert endpoint_result["error_rate"] <= 0.5, \
                                f"Error rate too high for {endpoint_result['endpoint']} under degraded services"
                        elif result["failure_type"] == "slow":
                            # Slow services should still work but be slower
                            assert endpoint_result["error_rate"] <= 0.2, \
                                f"Error rate too high for {endpoint_result['endpoint']} under slow services"
                    
                    # If critical services failed, high error rate is expected
                    if "database" in failed_services and result["failure_type"] == "complete":
                        assert endpoint_result["error_rate"] >= 0.8, \
                            f"Should have high error rate when database fails completely"
                            
        finally:
            performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_network_partition_recovery(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test system recovery after network partitions"""
        
        performance_monitor.start_monitoring()
        network_simulator = NetworkFailureSimulator()
        
        try:
            # Test partition and recovery cycle
            partition_scenarios = [
                {"phase": "normal_operation", "condition": NetworkCondition.NORMAL, "duration": 10},
                {"phase": "network_partition", "condition": NetworkCondition.PARTITION, "duration": 15},
                {"phase": "partition_recovery", "condition": NetworkCondition.HIGH_LATENCY, "duration": 10, "severity": 0.8},
                {"phase": "full_recovery", "condition": NetworkCondition.NORMAL, "duration": 10}
            ]
            
            partition_results = []
            
            for scenario in partition_scenarios:
                print(f"\nTesting partition phase: {scenario['phase']}")
                
                # Apply network condition
                severity = scenario.get("severity", 0.5)
                await network_simulator.apply_condition(scenario["condition"], severity=severity)
                
                # Run requests during this phase
                phase_start = time.time()
                
                async def partition_aware_request(endpoint: str):
                    start_time = time.time()
                    
                    try:
                        # Simulate network delay with potential partition
                        network_delay = await network_simulator.simulate_request_delay(0.01)
                        await asyncio.sleep(network_delay)
                        
                        return {
                            "status_code": 200,
                            "response_time": time.time() - start_time,
                            "success": True
                        }
                        
                    except Exception as e:
                        return {
                            "status_code": 0,
                            "response_time": time.time() - start_time,
                            "success": False,
                            "error": str(e)
                        }
                
                # Run requests for the duration of this phase
                phase_results = []
                
                while time.time() - phase_start < scenario["duration"]:
                    # Run a batch of requests
                    batch_tasks = [
                        partition_aware_request("/api/v1/health")
                        for _ in range(load_test_config["concurrent_users"] // 4)
                    ]
                    
                    batch_start = time.time()
                    batch_results = await asyncio.gather(*batch_tasks)
                    batch_end = time.time()
                    
                    phase_results.extend(batch_results)
                    
                    # Wait before next batch
                    await asyncio.sleep(1)
                
                # Calculate phase metrics
                successful_requests = [r for r in phase_results if r["success"]]
                failed_requests = [r for r in phase_results if not r["success"]]
                
                phase_metrics = {
                    "phase": scenario["phase"],
                    "condition": scenario["condition"].value,
                    "duration": scenario["duration"],
                    "total_requests": len(phase_results),
                    "successful_requests": len(successful_requests),
                    "failed_requests": len(failed_requests),
                    "error_rate": len(failed_requests) / len(phase_results) if phase_results else 0,
                    "avg_response_time": sum(r["response_time"] for r in successful_requests) / len(successful_requests) if successful_requests else 0,
                    "requests_per_second": len(successful_requests) / scenario["duration"]
                }
                
                partition_results.append(phase_metrics)
            
            # Reset network conditions
            await network_simulator.reset_conditions()
            
            print(f"\n=== Network Partition Recovery Test Results ===")
            
            for result in partition_results:
                print(f"{result['phase']} ({result['condition']}):")
                print(f"  Duration: {result['duration']}s")
                print(f"  Success Rate: {((result['successful_requests']/result['total_requests'])*100):.1f}%")
                print(f"  Avg Response Time: {result['avg_response_time']:.3f}s")
                print(f"  RPS: {result['requests_per_second']:.1f}")
            
            # Validate partition recovery behavior
            normal_phases = [r for r in partition_results if r["phase"] in ["normal_operation", "full_recovery"]]
            partition_phase = next((r for r in partition_results if r["phase"] == "network_partition"), None)
            recovery_phase = next((r for r in partition_results if r["phase"] == "partition_recovery"), None)
            
            # During normal operation, error rate should be low
            for normal_phase in normal_phases:
                assert normal_phase["error_rate"] <= 0.05, \
                    f"Error rate during {normal_phase['phase']} too high: {normal_phase['error_rate']:.2%}"
            
            # During partition, most requests should fail
            if partition_phase:
                assert partition_phase["error_rate"] >= 0.9, \
                    f"During partition, most requests should fail: {partition_phase['error_rate']:.2%}"
            
            # During recovery, error rate should improve but may still be elevated
            if recovery_phase:
                assert recovery_phase["error_rate"] <= 0.5, \
                    f"During recovery, error rate should improve: {recovery_phase['error_rate']:.2%}"
            
            # Full recovery should restore normal operation
            full_recovery = next((r for r in partition_results if r["phase"] == "full_recovery"), None)
            if full_recovery and normal_phases:
                normal_baseline = normal_phases[0]
                recovery_improvement = normal_baseline["error_rate"] - full_recovery["error_rate"]
                
                assert abs(recovery_improvement) <= 0.1, \
                    f"Full recovery should restore normal error rates"
                    
        finally:
            await network_simulator.reset_conditions()
            performance_monitor.stop_monitoring()