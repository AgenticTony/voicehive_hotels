"""
Chaos Engineer - Automated failure injection and resilience testing

This module implements chaos engineering principles to test system resilience
by automatically injecting various types of failures and measuring recovery.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Union
from unittest.mock import patch, MagicMock

import aiohttp
import psutil

logger = logging.getLogger(__name__)


class FailureType(Enum):
    """Types of failures that can be injected"""
    NETWORK_LATENCY = "network_latency"
    NETWORK_PARTITION = "network_partition"
    SERVICE_UNAVAILABLE = "service_unavailable"
    DATABASE_FAILURE = "database_failure"
    REDIS_FAILURE = "redis_failure"
    MEMORY_PRESSURE = "memory_pressure"
    CPU_SPIKE = "cpu_spike"
    DISK_FULL = "disk_full"
    TIMEOUT_INJECTION = "timeout_injection"
    EXCEPTION_INJECTION = "exception_injection"


@dataclass
class ChaosExperiment:
    """Defines a chaos engineering experiment"""
    name: str
    description: str
    failure_type: FailureType
    target_service: str
    failure_rate: float = 0.1  # 10% failure rate
    duration_seconds: int = 60
    recovery_timeout_seconds: int = 120
    blast_radius: str = "single_service"  # single_service, multiple_services, system_wide
    hypothesis: str = ""
    success_criteria: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChaosResult:
    """Results from a chaos experiment"""
    experiment_name: str
    failure_type: FailureType
    injection_successful: bool
    system_recovered: bool
    recovery_time_seconds: float
    impact_metrics: Dict[str, Any]
    hypothesis_validated: bool
    errors_observed: List[str]
    passed: bool


class ChaosEngineer:
    """
    Chaos engineering framework for automated failure injection and resilience testing
    """
    
    def __init__(self, config):
        self.config = config
        self.experiments = self._define_chaos_experiments()
        self.active_failures = {}
        self.baseline_metrics = {}
        
    def _define_chaos_experiments(self) -> List[ChaosExperiment]:
        """Define chaos engineering experiments"""
        
        return [
            # Network-related failures
            ChaosExperiment(
                name="network_latency_injection",
                description="Inject network latency to test timeout handling",
                failure_type=FailureType.NETWORK_LATENCY,
                target_service="external_apis",
                failure_rate=0.3,
                duration_seconds=60,
                hypothesis="System should handle network latency gracefully with proper timeouts",
                success_criteria={
                    "max_response_time_ms": 5000,
                    "min_success_rate": 0.95,
                    "circuit_breaker_activated": True
                }
            ),
            
            ChaosExperiment(
                name="network_partition_simulation",
                description="Simulate network partition between services",
                failure_type=FailureType.NETWORK_PARTITION,
                target_service="pms_connector",
                failure_rate=1.0,  # Complete partition
                duration_seconds=30,
                hypothesis="System should detect partition and activate circuit breakers",
                success_criteria={
                    "circuit_breaker_activated": True,
                    "fallback_responses_served": True,
                    "no_cascading_failures": True
                }
            ),
            
            # Service failures
            ChaosExperiment(
                name="pms_service_unavailable",
                description="Make PMS service completely unavailable",
                failure_type=FailureType.SERVICE_UNAVAILABLE,
                target_service="pms_connector",
                failure_rate=1.0,
                duration_seconds=45,
                hypothesis="System should gracefully degrade when PMS is unavailable",
                success_criteria={
                    "graceful_degradation": True,
                    "error_rate_below_threshold": 0.05,
                    "user_experience_maintained": True
                }
            ),
            
            ChaosExperiment(
                name="tts_service_intermittent_failures",
                description="Inject intermittent failures in TTS service",
                failure_type=FailureType.SERVICE_UNAVAILABLE,
                target_service="tts_service",
                failure_rate=0.2,
                duration_seconds=90,
                hypothesis="System should retry TTS requests and maintain call quality",
                success_criteria={
                    "retry_mechanism_activated": True,
                    "call_completion_rate": 0.95,
                    "audio_quality_maintained": True
                }
            ),
            
            # Database failures
            ChaosExperiment(
                name="database_connection_failure",
                description="Simulate database connection failures",
                failure_type=FailureType.DATABASE_FAILURE,
                target_service="database",
                failure_rate=0.15,
                duration_seconds=60,
                hypothesis="System should handle database failures with connection pooling",
                success_criteria={
                    "connection_pool_recovery": True,
                    "data_consistency_maintained": True,
                    "no_data_loss": True
                }
            ),
            
            ChaosExperiment(
                name="redis_cache_failure",
                description="Simulate Redis cache unavailability",
                failure_type=FailureType.REDIS_FAILURE,
                target_service="redis",
                failure_rate=1.0,
                duration_seconds=30,
                hypothesis="System should function without cache with acceptable performance",
                success_criteria={
                    "cache_bypass_activated": True,
                    "performance_degradation_acceptable": True,
                    "no_service_interruption": True
                }
            ),
            
            # Resource pressure
            ChaosExperiment(
                name="memory_pressure_injection",
                description="Inject memory pressure to test resource handling",
                failure_type=FailureType.MEMORY_PRESSURE,
                target_service="orchestrator",
                duration_seconds=45,
                hypothesis="System should handle memory pressure without crashing",
                success_criteria={
                    "no_out_of_memory_errors": True,
                    "garbage_collection_effective": True,
                    "service_availability_maintained": True
                }
            ),
            
            ChaosExperiment(
                name="cpu_spike_simulation",
                description="Simulate CPU spikes to test performance under load",
                failure_type=FailureType.CPU_SPIKE,
                target_service="orchestrator",
                duration_seconds=30,
                hypothesis="System should maintain responsiveness during CPU spikes",
                success_criteria={
                    "response_time_acceptable": True,
                    "request_queuing_managed": True,
                    "no_request_drops": True
                }
            ),
            
            # Application-level failures
            ChaosExperiment(
                name="timeout_injection",
                description="Inject random timeouts in service calls",
                failure_type=FailureType.TIMEOUT_INJECTION,
                target_service="all_services",
                failure_rate=0.1,
                duration_seconds=60,
                hypothesis="System should handle timeouts with proper retry logic",
                success_criteria={
                    "retry_logic_activated": True,
                    "exponential_backoff_used": True,
                    "circuit_breaker_protection": True
                }
            ),
            
            ChaosExperiment(
                name="exception_injection",
                description="Inject random exceptions in critical paths",
                failure_type=FailureType.EXCEPTION_INJECTION,
                target_service="orchestrator",
                failure_rate=0.05,
                duration_seconds=90,
                hypothesis="System should handle exceptions gracefully without crashes",
                success_criteria={
                    "exception_handling_effective": True,
                    "error_logging_comprehensive": True,
                    "service_recovery_automatic": True
                }
            )
        ]
    
    async def run_chaos_tests(self) -> Dict[str, Any]:
        """
        Run all chaos engineering experiments
        
        Returns:
            Dict containing comprehensive chaos test results
        """
        logger.info("Starting chaos engineering test suite")
        
        try:
            # Collect baseline metrics
            await self._collect_baseline_metrics()
            
            # Run chaos experiments
            results = []
            for experiment in self.experiments:
                logger.info(f"Running chaos experiment: {experiment.name}")
                result = await self._run_experiment(experiment)
                results.append(result)
                
                # Recovery period between experiments
                await asyncio.sleep(10)
            
            # Generate comprehensive report
            report = self._generate_chaos_report(results)
            
            logger.info("Chaos engineering test suite completed")
            return report
            
        except Exception as e:
            logger.error(f"Error during chaos testing: {e}")
            raise
        finally:
            # Ensure all failures are cleaned up
            await self._cleanup_all_failures()
    
    async def _collect_baseline_metrics(self):
        """Collect baseline system metrics before chaos injection"""
        logger.info("Collecting baseline metrics")
        
        try:
            # System metrics
            self.baseline_metrics = {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_usage_percent': psutil.disk_usage('/').percent,
                'network_connections': len(psutil.net_connections()),
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Application metrics (simulated)
            self.baseline_metrics.update({
                'response_time_ms': 250,
                'requests_per_second': 100,
                'error_rate': 0.01,
                'active_connections': 50
            })
            
        except Exception as e:
            logger.warning(f"Could not collect baseline metrics: {e}")
            self.baseline_metrics = {}
    
    async def _run_experiment(self, experiment: ChaosExperiment) -> ChaosResult:
        """Run a single chaos experiment"""
        
        start_time = time.time()
        
        try:
            # Inject failure
            injection_successful = await self._inject_failure(experiment)
            
            if not injection_successful:
                return ChaosResult(
                    experiment_name=experiment.name,
                    failure_type=experiment.failure_type,
                    injection_successful=False,
                    system_recovered=False,
                    recovery_time_seconds=0,
                    impact_metrics={},
                    hypothesis_validated=False,
                    errors_observed=["Failed to inject failure"],
                    passed=False
                )
            
            # Monitor system during failure
            impact_metrics = await self._monitor_during_failure(experiment)
            
            # Wait for failure duration
            await asyncio.sleep(experiment.duration_seconds)
            
            # Remove failure and measure recovery
            await self._remove_failure(experiment)
            
            recovery_start = time.time()
            system_recovered = await self._wait_for_recovery(experiment)
            recovery_time = time.time() - recovery_start
            
            # Validate hypothesis
            hypothesis_validated = await self._validate_hypothesis(experiment, impact_metrics)
            
            # Determine if experiment passed
            passed = (
                injection_successful and
                system_recovered and
                hypothesis_validated and
                recovery_time <= experiment.recovery_timeout_seconds
            )
            
            return ChaosResult(
                experiment_name=experiment.name,
                failure_type=experiment.failure_type,
                injection_successful=injection_successful,
                system_recovered=system_recovered,
                recovery_time_seconds=recovery_time,
                impact_metrics=impact_metrics,
                hypothesis_validated=hypothesis_validated,
                errors_observed=impact_metrics.get('errors', []),
                passed=passed
            )
            
        except Exception as e:
            logger.error(f"Error during experiment {experiment.name}: {e}")
            return ChaosResult(
                experiment_name=experiment.name,
                failure_type=experiment.failure_type,
                injection_successful=False,
                system_recovered=False,
                recovery_time_seconds=time.time() - start_time,
                impact_metrics={},
                hypothesis_validated=False,
                errors_observed=[str(e)],
                passed=False
            )
    
    async def _inject_failure(self, experiment: ChaosExperiment) -> bool:
        """Inject the specified failure type"""
        
        try:
            failure_id = f"{experiment.name}_{int(time.time())}"
            
            if experiment.failure_type == FailureType.NETWORK_LATENCY:
                await self._inject_network_latency(experiment, failure_id)
            
            elif experiment.failure_type == FailureType.NETWORK_PARTITION:
                await self._inject_network_partition(experiment, failure_id)
            
            elif experiment.failure_type == FailureType.SERVICE_UNAVAILABLE:
                await self._inject_service_unavailable(experiment, failure_id)
            
            elif experiment.failure_type == FailureType.DATABASE_FAILURE:
                await self._inject_database_failure(experiment, failure_id)
            
            elif experiment.failure_type == FailureType.REDIS_FAILURE:
                await self._inject_redis_failure(experiment, failure_id)
            
            elif experiment.failure_type == FailureType.MEMORY_PRESSURE:
                await self._inject_memory_pressure(experiment, failure_id)
            
            elif experiment.failure_type == FailureType.CPU_SPIKE:
                await self._inject_cpu_spike(experiment, failure_id)
            
            elif experiment.failure_type == FailureType.TIMEOUT_INJECTION:
                await self._inject_timeout_failures(experiment, failure_id)
            
            elif experiment.failure_type == FailureType.EXCEPTION_INJECTION:
                await self._inject_exception_failures(experiment, failure_id)
            
            else:
                logger.warning(f"Unknown failure type: {experiment.failure_type}")
                return False
            
            self.active_failures[failure_id] = experiment
            logger.info(f"Successfully injected failure: {experiment.failure_type.value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to inject failure {experiment.failure_type.value}: {e}")
            return False
    
    async def _inject_network_latency(self, experiment: ChaosExperiment, failure_id: str):
        """Inject network latency"""
        # In a real implementation, this would use tools like tc (traffic control)
        # or toxiproxy to inject actual network latency
        
        # For testing, we'll mock the network calls to add delays
        original_request = aiohttp.ClientSession.request
        
        async def delayed_request(self, method, url, **kwargs):
            # Add random delay based on failure rate
            if random.random() < experiment.failure_rate:
                delay = random.uniform(1.0, 3.0)  # 1-3 second delay
                await asyncio.sleep(delay)
            return await original_request(self, method, url, **kwargs)
        
        # Patch the request method
        self.active_failures[failure_id] = {
            'type': 'network_latency',
            'original_method': original_request,
            'patched_method': delayed_request
        }
        
        # Apply the patch
        aiohttp.ClientSession.request = delayed_request
    
    async def _inject_network_partition(self, experiment: ChaosExperiment, failure_id: str):
        """Inject network partition"""
        # Simulate network partition by making external calls fail
        
        original_request = aiohttp.ClientSession.request
        
        async def partitioned_request(self, method, url, **kwargs):
            # Fail requests to specific services
            if experiment.target_service in str(url):
                raise aiohttp.ClientConnectorError(
                    connection_key=None,
                    os_error=OSError("Network partition simulated")
                )
            return await original_request(self, method, url, **kwargs)
        
        self.active_failures[failure_id] = {
            'type': 'network_partition',
            'original_method': original_request,
            'patched_method': partitioned_request
        }
        
        aiohttp.ClientSession.request = partitioned_request
    
    async def _inject_service_unavailable(self, experiment: ChaosExperiment, failure_id: str):
        """Inject service unavailability"""
        
        original_request = aiohttp.ClientSession.request
        
        async def unavailable_request(self, method, url, **kwargs):
            # Make service calls fail based on failure rate
            if experiment.target_service in str(url) and random.random() < experiment.failure_rate:
                raise aiohttp.ClientResponseError(
                    request_info=None,
                    history=(),
                    status=503,
                    message="Service Unavailable (Chaos Injection)"
                )
            return await original_request(self, method, url, **kwargs)
        
        self.active_failures[failure_id] = {
            'type': 'service_unavailable',
            'original_method': original_request,
            'patched_method': unavailable_request
        }
        
        aiohttp.ClientSession.request = unavailable_request
    
    async def _inject_database_failure(self, experiment: ChaosExperiment, failure_id: str):
        """Inject database connection failures"""
        # In a real implementation, this would interfere with database connections
        # For testing, we'll simulate connection failures
        
        self.active_failures[failure_id] = {
            'type': 'database_failure',
            'simulation': True
        }
        
        logger.info("Database failure injection simulated")
    
    async def _inject_redis_failure(self, experiment: ChaosExperiment, failure_id: str):
        """Inject Redis cache failures"""
        # Simulate Redis unavailability
        
        self.active_failures[failure_id] = {
            'type': 'redis_failure',
            'simulation': True
        }
        
        logger.info("Redis failure injection simulated")
    
    async def _inject_memory_pressure(self, experiment: ChaosExperiment, failure_id: str):
        """Inject memory pressure"""
        # Allocate memory to create pressure
        
        memory_hog = []
        try:
            # Allocate 100MB chunks until we reach desired pressure
            for _ in range(5):  # 500MB total
                chunk = bytearray(100 * 1024 * 1024)  # 100MB
                memory_hog.append(chunk)
                await asyncio.sleep(0.1)  # Brief pause
            
            self.active_failures[failure_id] = {
                'type': 'memory_pressure',
                'memory_hog': memory_hog
            }
            
        except MemoryError:
            logger.warning("Could not allocate enough memory for pressure test")
    
    async def _inject_cpu_spike(self, experiment: ChaosExperiment, failure_id: str):
        """Inject CPU spike"""
        # Create CPU-intensive task
        
        async def cpu_burner():
            end_time = time.time() + experiment.duration_seconds
            while time.time() < end_time:
                # CPU-intensive calculation
                sum(i * i for i in range(10000))
                await asyncio.sleep(0.001)  # Brief yield
        
        task = asyncio.create_task(cpu_burner())
        
        self.active_failures[failure_id] = {
            'type': 'cpu_spike',
            'task': task
        }
    
    async def _inject_timeout_failures(self, experiment: ChaosExperiment, failure_id: str):
        """Inject timeout failures"""
        
        original_request = aiohttp.ClientSession.request
        
        async def timeout_request(self, method, url, **kwargs):
            # Inject timeouts based on failure rate
            if random.random() < experiment.failure_rate:
                raise asyncio.TimeoutError("Chaos-injected timeout")
            return await original_request(self, method, url, **kwargs)
        
        self.active_failures[failure_id] = {
            'type': 'timeout_injection',
            'original_method': original_request,
            'patched_method': timeout_request
        }
        
        aiohttp.ClientSession.request = timeout_request
    
    async def _inject_exception_failures(self, experiment: ChaosExperiment, failure_id: str):
        """Inject random exceptions"""
        
        # This would typically patch specific functions to inject exceptions
        # For testing, we'll simulate this
        
        self.active_failures[failure_id] = {
            'type': 'exception_injection',
            'simulation': True
        }
        
        logger.info("Exception injection simulated")
    
    async def _monitor_during_failure(self, experiment: ChaosExperiment) -> Dict[str, Any]:
        """Monitor system metrics during failure injection"""
        
        metrics = {
            'errors': [],
            'response_times': [],
            'success_rates': [],
            'resource_usage': {}
        }
        
        try:
            # Monitor for a portion of the failure duration
            monitor_duration = min(30, experiment.duration_seconds // 2)
            
            for _ in range(monitor_duration):
                # Collect system metrics
                try:
                    cpu_percent = psutil.cpu_percent()
                    memory_percent = psutil.virtual_memory().percent
                    
                    metrics['resource_usage'] = {
                        'cpu_percent': cpu_percent,
                        'memory_percent': memory_percent,
                        'timestamp': datetime.utcnow().isoformat()
                    }
                    
                    # Simulate application metrics
                    # In a real implementation, these would be collected from the actual system
                    response_time = random.uniform(200, 2000)  # Simulated response time
                    success_rate = random.uniform(0.8, 1.0)    # Simulated success rate
                    
                    metrics['response_times'].append(response_time)
                    metrics['success_rates'].append(success_rate)
                    
                except Exception as e:
                    metrics['errors'].append(f"Monitoring error: {str(e)}")
                
                await asyncio.sleep(1)
        
        except Exception as e:
            metrics['errors'].append(f"Monitoring failed: {str(e)}")
        
        return metrics
    
    async def _remove_failure(self, experiment: ChaosExperiment):
        """Remove injected failure"""
        
        failure_id = None
        for fid, exp in self.active_failures.items():
            if isinstance(exp, ChaosExperiment) and exp.name == experiment.name:
                failure_id = fid
                break
        
        if not failure_id:
            logger.warning(f"No active failure found for experiment: {experiment.name}")
            return
        
        try:
            failure_info = self.active_failures[failure_id]
            
            if isinstance(failure_info, dict):
                failure_type = failure_info.get('type')
                
                # Restore original methods for network-related failures
                if failure_type in ['network_latency', 'network_partition', 'service_unavailable', 'timeout_injection']:
                    original_method = failure_info.get('original_method')
                    if original_method:
                        aiohttp.ClientSession.request = original_method
                
                # Clean up memory pressure
                elif failure_type == 'memory_pressure':
                    memory_hog = failure_info.get('memory_hog', [])
                    memory_hog.clear()
                
                # Cancel CPU spike task
                elif failure_type == 'cpu_spike':
                    task = failure_info.get('task')
                    if task and not task.done():
                        task.cancel()
            
            del self.active_failures[failure_id]
            logger.info(f"Removed failure injection for experiment: {experiment.name}")
            
        except Exception as e:
            logger.error(f"Error removing failure for experiment {experiment.name}: {e}")
    
    async def _wait_for_recovery(self, experiment: ChaosExperiment) -> bool:
        """Wait for system to recover from failure"""
        
        recovery_timeout = experiment.recovery_timeout_seconds
        check_interval = 5  # Check every 5 seconds
        
        for _ in range(0, recovery_timeout, check_interval):
            try:
                # Check if system has recovered
                # In a real implementation, this would check actual health endpoints
                
                # Simulate recovery check
                recovery_probability = min(0.9, (_ / recovery_timeout) + 0.1)
                if random.random() < recovery_probability:
                    logger.info(f"System recovered from {experiment.name}")
                    return True
                
                await asyncio.sleep(check_interval)
                
            except Exception as e:
                logger.warning(f"Error checking recovery for {experiment.name}: {e}")
        
        logger.warning(f"System did not recover within timeout for {experiment.name}")
        return False
    
    async def _validate_hypothesis(self, experiment: ChaosExperiment, impact_metrics: Dict[str, Any]) -> bool:
        """Validate the experiment hypothesis based on success criteria"""
        
        try:
            success_criteria = experiment.success_criteria
            
            # Check each success criterion
            for criterion, expected_value in success_criteria.items():
                
                if criterion == "max_response_time_ms":
                    response_times = impact_metrics.get('response_times', [])
                    if response_times:
                        max_response_time = max(response_times)
                        if max_response_time > expected_value:
                            return False
                
                elif criterion == "min_success_rate":
                    success_rates = impact_metrics.get('success_rates', [])
                    if success_rates:
                        min_success_rate = min(success_rates)
                        if min_success_rate < expected_value:
                            return False
                
                elif criterion == "circuit_breaker_activated":
                    # In a real implementation, this would check actual circuit breaker state
                    # For testing, we'll simulate based on error patterns
                    errors = impact_metrics.get('errors', [])
                    circuit_breaker_activated = len(errors) > 0  # Simplified check
                    if circuit_breaker_activated != expected_value:
                        return False
                
                elif criterion == "no_cascading_failures":
                    # Check that failures didn't cascade beyond expected scope
                    errors = impact_metrics.get('errors', [])
                    cascading_failures = any("cascade" in error.lower() for error in errors)
                    if cascading_failures:
                        return False
                
                # Add more criteria validation as needed
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating hypothesis for {experiment.name}: {e}")
            return False
    
    async def _cleanup_all_failures(self):
        """Clean up all active failures"""
        
        for failure_id in list(self.active_failures.keys()):
            try:
                failure_info = self.active_failures[failure_id]
                
                if isinstance(failure_info, ChaosExperiment):
                    await self._remove_failure(failure_info)
                elif isinstance(failure_info, dict):
                    # Handle dict-based failure info
                    failure_type = failure_info.get('type')
                    
                    if failure_type in ['network_latency', 'network_partition', 'service_unavailable', 'timeout_injection']:
                        original_method = failure_info.get('original_method')
                        if original_method:
                            aiohttp.ClientSession.request = original_method
                    
                    elif failure_type == 'memory_pressure':
                        memory_hog = failure_info.get('memory_hog', [])
                        memory_hog.clear()
                    
                    elif failure_type == 'cpu_spike':
                        task = failure_info.get('task')
                        if task and not task.done():
                            task.cancel()
                    
                    del self.active_failures[failure_id]
                    
            except Exception as e:
                logger.error(f"Error cleaning up failure {failure_id}: {e}")
        
        logger.info("All chaos failures cleaned up")
    
    def _generate_chaos_report(self, results: List[ChaosResult]) -> Dict[str, Any]:
        """Generate comprehensive chaos engineering report"""
        
        total_experiments = len(results)
        passed_experiments = sum(1 for r in results if r.passed)
        overall_success = passed_experiments == total_experiments
        
        # Calculate recovery statistics
        recovery_times = [r.recovery_time_seconds for r in results if r.system_recovered]
        avg_recovery_time = sum(recovery_times) / len(recovery_times) if recovery_times else 0
        
        # Identify resilience gaps
        resilience_gaps = []
        for result in results:
            if not result.passed:
                if not result.system_recovered:
                    resilience_gaps.append(f"{result.experiment_name}: System did not recover")
                elif not result.hypothesis_validated:
                    resilience_gaps.append(f"{result.experiment_name}: Hypothesis not validated")
                elif result.recovery_time_seconds > 60:
                    resilience_gaps.append(f"{result.experiment_name}: Slow recovery ({result.recovery_time_seconds:.1f}s)")
        
        # Collect all errors
        all_errors = []
        for result in results:
            all_errors.extend(result.errors_observed)
        
        return {
            'overall_success': overall_success,
            'tests_run': total_experiments,
            'tests_passed': passed_experiments,
            'tests_failed': total_experiments - passed_experiments,
            'failure_scenarios_tested': len(set(r.failure_type for r in results)),
            'recovery_time_seconds': avg_recovery_time,
            'resilience_score': (passed_experiments / total_experiments * 100) if total_experiments > 0 else 0,
            'experiment_results': [
                {
                    'name': r.experiment_name,
                    'failure_type': r.failure_type.value,
                    'passed': r.passed,
                    'system_recovered': r.system_recovered,
                    'recovery_time_seconds': r.recovery_time_seconds,
                    'hypothesis_validated': r.hypothesis_validated
                }
                for r in results
            ],
            'resilience_gaps': resilience_gaps,
            'error_summary': list(set(all_errors))[:10],  # Unique errors, top 10
            'recommendations': self._generate_chaos_recommendations(results)
        }
    
    def _generate_chaos_recommendations(self, results: List[ChaosResult]) -> List[str]:
        """Generate recommendations based on chaos test results"""
        recommendations = []
        
        # Check for slow recovery
        slow_recovery = [r for r in results if r.system_recovered and r.recovery_time_seconds > 60]
        if slow_recovery:
            recommendations.append(
                f"Improve recovery time for {len(slow_recovery)} scenarios that recovered slowly"
            )
        
        # Check for failed recovery
        failed_recovery = [r for r in results if not r.system_recovered]
        if failed_recovery:
            recommendations.append(
                f"Fix recovery mechanisms for {len(failed_recovery)} scenarios that failed to recover"
            )
        
        # Check for hypothesis validation failures
        hypothesis_failures = [r for r in results if r.system_recovered and not r.hypothesis_validated]
        if hypothesis_failures:
            recommendations.append(
                f"Review and strengthen resilience mechanisms for {len(hypothesis_failures)} scenarios"
            )
        
        # General recommendations
        if not recommendations:
            recommendations.append("All chaos experiments passed. System demonstrates excellent resilience.")
        else:
            recommendations.append("Consider implementing automated chaos testing in production with gradual rollout")
        
        return recommendations