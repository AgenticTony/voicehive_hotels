"""
Performance Regression Testing Framework

Tests system performance characteristics and detects regressions in response times,
throughput, memory usage, and resource utilization under various load conditions.
"""

import pytest
import asyncio
import time
import psutil
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from dataclasses import dataclass, asdict


@dataclass
class PerformanceMetrics:
    """Performance metrics data structure"""
    endpoint: str
    method: str
    response_time_avg: float
    response_time_p95: float
    response_time_p99: float
    throughput_rps: float
    memory_usage_mb: float
    cpu_usage_percent: float
    error_rate: float
    concurrent_requests: int
    test_duration: float
    timestamp: str


class PerformanceTestFramework:
    """Framework for performance regression testing"""
    
    def __init__(self):
        self.baseline_metrics: Dict[str, PerformanceMetrics] = {}
        self.current_metrics: Dict[str, PerformanceMetrics] = {}
        
    async def measure_endpoint_performance(
        self,
        client,
        endpoint: str,
        method: str = "GET",
        payload: Dict = None,
        concurrent_requests: int = 10,
        test_duration: float = 30.0,
        headers: Dict = None
    ) -> PerformanceMetrics:
        """Measure performance metrics for a specific endpoint"""
        
        response_times = []
        error_count = 0
        total_requests = 0
        
        # Get initial system metrics
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        start_time = time.time()
        end_time = start_time + test_duration
        
        async def make_request():
            """Make a single request and record metrics"""
            nonlocal error_count, total_requests
            
            request_start = time.time()
            try:
                if method.upper() == "GET":
                    response = await client.get(endpoint, headers=headers)
                elif method.upper() == "POST":
                    response = await client.post(endpoint, json=payload, headers=headers)
                elif method.upper() == "PUT":
                    response = await client.put(endpoint, json=payload, headers=headers)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                request_end = time.time()
                response_time = request_end - request_start
                
                if response.status_code >= 400:
                    error_count += 1
                
                response_times.append(response_time)
                total_requests += 1
                
            except Exception as e:
                error_count += 1
                total_requests += 1
                # Record timeout/error as max response time
                response_times.append(10.0)
        
        # Run concurrent requests for the specified duration
        while time.time() < end_time:
            # Create batch of concurrent requests
            tasks = [make_request() for _ in range(concurrent_requests)]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Small delay between batches
            await asyncio.sleep(0.1)
        
        # Calculate final metrics
        actual_duration = time.time() - start_time
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_usage = final_memory - initial_memory
        
        # CPU usage (approximate)
        cpu_usage = process.cpu_percent()
        
        # Calculate response time percentiles
        if response_times:
            response_times.sort()
            avg_response_time = sum(response_times) / len(response_times)
            p95_index = int(len(response_times) * 0.95)
            p99_index = int(len(response_times) * 0.99)
            p95_response_time = response_times[p95_index] if p95_index < len(response_times) else response_times[-1]
            p99_response_time = response_times[p99_index] if p99_index < len(response_times) else response_times[-1]
        else:
            avg_response_time = p95_response_time = p99_response_time = 0.0
        
        # Calculate throughput
        throughput = total_requests / actual_duration if actual_duration > 0 else 0.0
        
        # Calculate error rate
        error_rate = error_count / total_requests if total_requests > 0 else 0.0
        
        return PerformanceMetrics(
            endpoint=endpoint,
            method=method,
            response_time_avg=avg_response_time,
            response_time_p95=p95_response_time,
            response_time_p99=p99_response_time,
            throughput_rps=throughput,
            memory_usage_mb=memory_usage,
            cpu_usage_percent=cpu_usage,
            error_rate=error_rate,
            concurrent_requests=concurrent_requests,
            test_duration=actual_duration,
            timestamp=datetime.utcnow().isoformat()
        )
    
    def compare_metrics(
        self,
        baseline: PerformanceMetrics,
        current: PerformanceMetrics,
        thresholds: Dict[str, float] = None
    ) -> Dict[str, Any]:
        """Compare current metrics against baseline"""
        
        if thresholds is None:
            thresholds = {
                "response_time_degradation": 1.5,  # 50% slower is a regression
                "throughput_degradation": 0.8,     # 20% less throughput is a regression
                "memory_increase": 2.0,            # 100% more memory is a regression
                "error_rate_increase": 0.05        # 5% more errors is a regression
            }
        
        comparison = {
            "endpoint": current.endpoint,
            "baseline_timestamp": baseline.timestamp,
            "current_timestamp": current.timestamp,
            "regressions": [],
            "improvements": [],
            "metrics_comparison": {}
        }
        
        # Response time comparison
        if baseline.response_time_avg > 0:
            response_time_ratio = current.response_time_avg / baseline.response_time_avg
            comparison["metrics_comparison"]["response_time_ratio"] = response_time_ratio
            
            if response_time_ratio > thresholds["response_time_degradation"]:
                comparison["regressions"].append({
                    "metric": "response_time_avg",
                    "baseline": baseline.response_time_avg,
                    "current": current.response_time_avg,
                    "ratio": response_time_ratio,
                    "threshold": thresholds["response_time_degradation"]
                })
            elif response_time_ratio < 0.9:  # 10% improvement
                comparison["improvements"].append({
                    "metric": "response_time_avg",
                    "baseline": baseline.response_time_avg,
                    "current": current.response_time_avg,
                    "improvement": (1 - response_time_ratio) * 100
                })
        
        # Throughput comparison
        if baseline.throughput_rps > 0:
            throughput_ratio = current.throughput_rps / baseline.throughput_rps
            comparison["metrics_comparison"]["throughput_ratio"] = throughput_ratio
            
            if throughput_ratio < thresholds["throughput_degradation"]:
                comparison["regressions"].append({
                    "metric": "throughput_rps",
                    "baseline": baseline.throughput_rps,
                    "current": current.throughput_rps,
                    "ratio": throughput_ratio,
                    "threshold": thresholds["throughput_degradation"]
                })
            elif throughput_ratio > 1.1:  # 10% improvement
                comparison["improvements"].append({
                    "metric": "throughput_rps",
                    "baseline": baseline.throughput_rps,
                    "current": current.throughput_rps,
                    "improvement": (throughput_ratio - 1) * 100
                })
        
        # Memory usage comparison
        if baseline.memory_usage_mb > 0:
            memory_ratio = current.memory_usage_mb / baseline.memory_usage_mb
            comparison["metrics_comparison"]["memory_ratio"] = memory_ratio
            
            if memory_ratio > thresholds["memory_increase"]:
                comparison["regressions"].append({
                    "metric": "memory_usage_mb",
                    "baseline": baseline.memory_usage_mb,
                    "current": current.memory_usage_mb,
                    "ratio": memory_ratio,
                    "threshold": thresholds["memory_increase"]
                })
        
        # Error rate comparison
        error_rate_diff = current.error_rate - baseline.error_rate
        comparison["metrics_comparison"]["error_rate_diff"] = error_rate_diff
        
        if error_rate_diff > thresholds["error_rate_increase"]:
            comparison["regressions"].append({
                "metric": "error_rate",
                "baseline": baseline.error_rate,
                "current": current.error_rate,
                "difference": error_rate_diff,
                "threshold": thresholds["error_rate_increase"]
            })
        
        return comparison


@pytest.fixture
def performance_framework():
    """Performance testing framework fixture"""
    return PerformanceTestFramework()


class TestPerformanceRegression:
    """Performance regression test suite"""
    
    async def test_health_endpoint_performance(
        self,
        authenticated_client,
        integration_test_app,
        performance_framework,
        performance_test_config
    ):
        """Test health endpoint performance characteristics"""
        
        metrics = await performance_framework.measure_endpoint_performance(
            client=authenticated_client,
            endpoint="/healthz",
            method="GET",
            concurrent_requests=performance_test_config["concurrent_requests"],
            test_duration=10.0  # Shorter duration for health checks
        )
        
        # Verify performance requirements
        assert metrics.response_time_avg < 0.1  # Health checks should be very fast
        assert metrics.response_time_p95 < 0.2
        assert metrics.error_rate < 0.01  # Less than 1% error rate
        assert metrics.throughput_rps > 50  # Should handle at least 50 RPS
        
        # Store baseline for future comparisons
        performance_framework.baseline_metrics["health_endpoint"] = metrics
    
    async def test_webhook_endpoint_performance(
        self,
        authenticated_client,
        integration_test_app,
        performance_framework,
        performance_test_config
    ):
        """Test webhook endpoint performance under load"""
        
        call_payload = {
            "event": "call.started",
            "call_id": "perf-test-001",
            "from_number": "+1234567890",
            "to_number": "+0987654321",
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": {"hotel_id": "perf-hotel"}
        }
        
        metrics = await performance_framework.measure_endpoint_performance(
            client=authenticated_client,
            endpoint="/webhook/call-event",
            method="POST",
            payload=call_payload,
            concurrent_requests=performance_test_config["concurrent_requests"],
            test_duration=performance_test_config["test_duration"]
        )
        
        # Verify performance requirements
        assert metrics.response_time_avg < performance_test_config["max_response_time"]
        assert metrics.response_time_p95 < performance_test_config["max_response_time"] * 2
        assert metrics.error_rate < performance_test_config["acceptable_error_rate"]
        assert metrics.throughput_rps > 10  # Should handle at least 10 RPS
        
        # Store baseline
        performance_framework.baseline_metrics["webhook_endpoint"] = metrics
    
    async def test_authentication_performance(
        self,
        unauthenticated_client,
        integration_test_app,
        performance_framework,
        jwt_service
    ):
        """Test authentication endpoint performance"""
        
        login_payload = {
            "email": "perf@voicehive-hotels.eu",
            "password": "performance_test_password"
        }
        
        # Mock successful authentication
        with patch('auth_middleware.validate_user_credentials') as mock_validate:
            from auth_models import UserContext
            mock_validate.return_value = UserContext(
                user_id="perf-user-123",
                email="perf@voicehive-hotels.eu",
                roles=["user"],
                permissions=["read"],
                session_id="perf-session",
                expires_at=None
            )
            
            metrics = await performance_framework.measure_endpoint_performance(
                client=unauthenticated_client,
                endpoint="/auth/login",
                method="POST",
                payload=login_payload,
                concurrent_requests=5,  # Lower concurrency for auth
                test_duration=15.0
            )
        
        # Verify authentication performance
        assert metrics.response_time_avg < 1.0  # Auth should be under 1 second
        assert metrics.response_time_p95 < 2.0
        assert metrics.error_rate < 0.05  # Less than 5% error rate
        assert metrics.throughput_rps > 5  # Should handle at least 5 auth/sec
        
        performance_framework.baseline_metrics["auth_endpoint"] = metrics
    
    async def test_tts_endpoint_performance(
        self,
        authenticated_client,
        integration_test_app,
        performance_framework,
        mock_tts_service
    ):
        """Test TTS endpoint performance characteristics"""
        
        tts_payload = {
            "text": "Performance test message for TTS synthesis",
            "voice": "female",
            "language": "en-US"
        }
        
        # Configure TTS service for performance testing
        mock_tts_service.response_delay = 0.1  # Simulate realistic TTS delay
        
        metrics = await performance_framework.measure_endpoint_performance(
            client=authenticated_client,
            endpoint="/tts/synthesize",
            method="POST",
            payload=tts_payload,
            concurrent_requests=3,  # Lower concurrency for TTS
            test_duration=20.0
        )
        
        # Verify TTS performance (more lenient due to processing time)
        assert metrics.response_time_avg < 2.0  # TTS can take longer
        assert metrics.response_time_p95 < 5.0
        assert metrics.error_rate < 0.1  # Less than 10% error rate
        assert metrics.throughput_rps > 1  # Should handle at least 1 TTS/sec
        
        performance_framework.baseline_metrics["tts_endpoint"] = metrics
    
    async def test_concurrent_mixed_workload_performance(
        self,
        authenticated_client,
        integration_test_app,
        performance_framework
    ):
        """Test performance under mixed concurrent workload"""
        
        async def mixed_workload_test():
            """Run mixed workload simulation"""
            
            # Define workload mix
            workload_tasks = []
            
            # Health checks (high frequency, low cost)
            for i in range(20):
                workload_tasks.append(
                    authenticated_client.get("/healthz")
                )
            
            # Webhook calls (medium frequency, medium cost)
            for i in range(10):
                call_payload = {
                    "event": "call.started",
                    "call_id": f"mixed-workload-{i}",
                    "from_number": "+1234567890",
                    "to_number": "+0987654321",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {"hotel_id": f"mixed-hotel-{i}"}
                }
                workload_tasks.append(
                    authenticated_client.post("/webhook/call-event", json=call_payload)
                )
            
            # TTS requests (low frequency, high cost)
            for i in range(3):
                tts_payload = {
                    "text": f"Mixed workload TTS test {i}",
                    "voice": "female"
                }
                workload_tasks.append(
                    authenticated_client.post("/tts/synthesize", json=tts_payload)
                )
            
            # Execute all tasks concurrently
            start_time = time.time()
            results = await asyncio.gather(*workload_tasks, return_exceptions=True)
            end_time = time.time()
            
            return results, end_time - start_time
        
        # Run mixed workload test
        results, total_time = await mixed_workload_test()
        
        # Analyze mixed workload performance
        successful_requests = 0
        failed_requests = 0
        
        for result in results:
            if isinstance(result, Exception):
                failed_requests += 1
            elif hasattr(result, 'status_code'):
                if result.status_code < 400:
                    successful_requests += 1
                else:
                    failed_requests += 1
        
        total_requests = successful_requests + failed_requests
        success_rate = successful_requests / total_requests if total_requests > 0 else 0
        throughput = total_requests / total_time
        
        # Verify mixed workload performance
        assert success_rate >= 0.9  # At least 90% success rate
        assert total_time < 30.0  # Should complete within 30 seconds
        assert throughput > 1.0  # Should process at least 1 request/second
    
    async def test_memory_usage_under_load(
        self,
        authenticated_client,
        integration_test_app,
        performance_framework
    ):
        """Test memory usage characteristics under sustained load"""
        
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Run sustained load for memory testing
        async def sustained_load():
            tasks = []
            for i in range(100):  # Many requests
                call_payload = {
                    "event": "call.started",
                    "call_id": f"memory-test-{i}",
                    "from_number": "+1234567890",
                    "to_number": "+0987654321",
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": {
                        "hotel_id": f"memory-hotel-{i}",
                        "large_data": "x" * 1000  # Some data to process
                    }
                }
                tasks.append(
                    authenticated_client.post("/webhook/call-event", json=call_payload)
                )
                
                # Process in batches to avoid overwhelming
                if len(tasks) >= 10:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    tasks = []
                    await asyncio.sleep(0.1)  # Small delay between batches
            
            # Process remaining tasks
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        
        await sustained_load()
        
        # Measure memory after load
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Verify memory usage is reasonable
        assert memory_increase < 100  # Should not increase by more than 100MB
        
        # Wait a bit and check for memory leaks
        await asyncio.sleep(2)
        gc_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Memory should not continue growing after load
        post_gc_increase = gc_memory - final_memory
        assert post_gc_increase < 10  # Should not grow more than 10MB after GC
    
    async def test_performance_regression_detection(
        self,
        authenticated_client,
        integration_test_app,
        performance_framework
    ):
        """Test performance regression detection framework"""
        
        # Create baseline metrics (simulate previous good performance)
        baseline_metrics = PerformanceMetrics(
            endpoint="/healthz",
            method="GET",
            response_time_avg=0.05,
            response_time_p95=0.1,
            response_time_p99=0.15,
            throughput_rps=100.0,
            memory_usage_mb=10.0,
            cpu_usage_percent=5.0,
            error_rate=0.001,
            concurrent_requests=10,
            test_duration=30.0,
            timestamp=(datetime.utcnow() - timedelta(days=1)).isoformat()
        )
        
        # Measure current performance
        current_metrics = await performance_framework.measure_endpoint_performance(
            client=authenticated_client,
            endpoint="/healthz",
            method="GET",
            concurrent_requests=10,
            test_duration=5.0  # Shorter test
        )
        
        # Compare metrics
        comparison = performance_framework.compare_metrics(
            baseline=baseline_metrics,
            current=current_metrics
        )
        
        # Verify comparison structure
        assert "regressions" in comparison
        assert "improvements" in comparison
        assert "metrics_comparison" in comparison
        
        # Log comparison results for analysis
        print(f"Performance comparison: {json.dumps(comparison, indent=2)}")
        
        # Check for significant regressions
        significant_regressions = [
            r for r in comparison["regressions"]
            if r["metric"] in ["response_time_avg", "throughput_rps"]
        ]
        
        # Should not have significant performance regressions
        assert len(significant_regressions) == 0, \
            f"Performance regressions detected: {significant_regressions}"
    
    async def test_scalability_characteristics(
        self,
        authenticated_client,
        integration_test_app,
        performance_framework
    ):
        """Test system scalability with increasing load"""
        
        # Test with increasing concurrent load
        concurrency_levels = [1, 5, 10, 20]
        scalability_results = []
        
        for concurrency in concurrency_levels:
            metrics = await performance_framework.measure_endpoint_performance(
                client=authenticated_client,
                endpoint="/healthz",
                method="GET",
                concurrent_requests=concurrency,
                test_duration=10.0
            )
            
            scalability_results.append({
                "concurrency": concurrency,
                "throughput": metrics.throughput_rps,
                "response_time": metrics.response_time_avg,
                "error_rate": metrics.error_rate
            })
        
        # Analyze scalability characteristics
        for i in range(1, len(scalability_results)):
            current = scalability_results[i]
            previous = scalability_results[i-1]
            
            # Throughput should generally increase with concurrency
            # (until saturation point)
            throughput_ratio = current["throughput"] / previous["throughput"]
            
            # Response time should not degrade too much
            response_time_ratio = current["response_time"] / previous["response_time"]
            
            # Error rate should remain low
            assert current["error_rate"] < 0.1, \
                f"High error rate at concurrency {current['concurrency']}: {current['error_rate']}"
            
            # Response time should not increase dramatically
            assert response_time_ratio < 5.0, \
                f"Response time degraded too much at concurrency {current['concurrency']}"
        
        # Log scalability results
        print(f"Scalability results: {json.dumps(scalability_results, indent=2)}")
    
    async def test_performance_monitoring_integration(
        self,
        authenticated_client,
        integration_test_app
    ):
        """Test integration with performance monitoring systems"""
        
        # Make some requests to generate metrics
        for i in range(10):
            await authenticated_client.get("/healthz")
            await asyncio.sleep(0.1)
        
        # Check metrics endpoint
        response = await authenticated_client.get("/metrics")
        assert response.status_code == 200
        
        metrics_text = response.text
        
        # Verify key performance metrics are exposed
        expected_metrics = [
            "http_requests_total",
            "http_request_duration_seconds",
            "process_resident_memory_bytes",
            "process_cpu_seconds_total"
        ]
        
        for metric in expected_metrics:
            assert metric in metrics_text, f"Missing metric: {metric}"
        
        # Verify metrics format (Prometheus format)
        assert "# HELP" in metrics_text
        assert "# TYPE" in metrics_text
        
        # Verify metrics have reasonable values
        lines = metrics_text.split('\n')
        for line in lines:
            if line.startswith('http_request_duration_seconds_sum'):
                # Extract value
                parts = line.split()
                if len(parts) >= 2:
                    duration_sum = float(parts[1])
                    assert duration_sum > 0, "Should have some request duration"
                    assert duration_sum < 100, "Duration sum should be reasonable"