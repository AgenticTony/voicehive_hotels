"""
Concurrent Call Simulation Load Testing

Tests the system's ability to handle multiple simultaneous voice calls
and related operations under high load conditions.
"""

import pytest
import asyncio
import time
from typing import List, Dict, Any
from datetime import datetime, timedelta
import json

from .conftest import LoadTestRunner, LoadTestMetrics, PerformanceMonitor


class TestConcurrentCallSimulation:
    """Test concurrent call handling under load"""
    
    @pytest.mark.asyncio
    async def test_concurrent_call_creation(
        self, 
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test concurrent call creation and management"""
        
        performance_monitor.start_monitoring()
        
        # Simulate call creation payload
        call_payload = {
            "hotel_id": "hotel_123",
            "room_number": "101",
            "guest_phone": "+1234567890",
            "call_type": "room_service",
            "priority": "normal"
        }
        
        try:
            metrics = await load_test_runner.run_concurrent_requests(
                endpoint="/api/v1/calls",
                method="POST",
                payload=call_payload,
                concurrent_users=load_test_config["concurrent_users"],
                requests_per_user=load_test_config["requests_per_user"],
                delay_between_requests=0.1
            )
            
            # Validate performance requirements
            assert metrics.error_rate <= load_test_config["max_error_rate"], \
                f"Error rate {metrics.error_rate:.2%} exceeds threshold {load_test_config['max_error_rate']:.2%}"
            
            assert metrics.avg_response_time <= load_test_config["max_response_time"], \
                f"Average response time {metrics.avg_response_time:.2f}s exceeds threshold {load_test_config['max_response_time']}s"
            
            assert metrics.memory_usage_mb <= load_test_config["memory_threshold_mb"], \
                f"Memory usage {metrics.memory_usage_mb:.1f}MB exceeds threshold {load_test_config['memory_threshold_mb']}MB"
            
            # Log performance metrics
            print(f"\n=== Concurrent Call Creation Test Results ===")
            print(f"Total Requests: {metrics.total_requests}")
            print(f"Success Rate: {(metrics.successful_requests/metrics.total_requests)*100:.1f}%")
            print(f"Average Response Time: {metrics.avg_response_time:.3f}s")
            print(f"Requests per Second: {metrics.requests_per_second:.1f}")
            print(f"Memory Usage: {metrics.memory_usage_mb:.1f}MB")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
            
            # Analyze memory usage over time
            if memory_snapshots:
                max_memory = max(s.rss_mb for s in memory_snapshots)
                min_memory = min(s.rss_mb for s in memory_snapshots)
                print(f"Memory Range: {min_memory:.1f}MB - {max_memory:.1f}MB")
    
    @pytest.mark.asyncio
    async def test_concurrent_call_events(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test concurrent call event processing"""
        
        performance_monitor.start_monitoring()
        
        # Different call event types
        event_types = [
            {"event": "call.started", "call_id": "call_001", "timestamp": datetime.now().isoformat()},
            {"event": "call.answered", "call_id": "call_002", "timestamp": datetime.now().isoformat()},
            {"event": "call.ended", "call_id": "call_003", "duration": 120, "timestamp": datetime.now().isoformat()},
            {"event": "call.transferred", "call_id": "call_004", "to_extension": "reception", "timestamp": datetime.now().isoformat()},
            {"event": "call.hold", "call_id": "call_005", "timestamp": datetime.now().isoformat()}
        ]
        
        try:
            # Test each event type under load
            all_metrics = []
            
            for event_payload in event_types:
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/webhook/call-event",
                    method="POST",
                    payload=event_payload,
                    concurrent_users=load_test_config["concurrent_users"] // 2,  # Reduce load per event type
                    requests_per_user=load_test_config["requests_per_user"] // 2,
                    delay_between_requests=0.05
                )
                
                all_metrics.append((event_payload["event"], metrics))
                
                # Validate each event type performance
                assert metrics.error_rate <= load_test_config["max_error_rate"], \
                    f"Error rate for {event_payload['event']}: {metrics.error_rate:.2%} exceeds threshold"
            
            # Overall performance validation
            total_requests = sum(m.total_requests for _, m in all_metrics)
            total_errors = sum(m.failed_requests for _, m in all_metrics)
            overall_error_rate = total_errors / total_requests if total_requests > 0 else 0
            
            assert overall_error_rate <= load_test_config["max_error_rate"], \
                f"Overall error rate {overall_error_rate:.2%} exceeds threshold"
            
            # Log results for each event type
            print(f"\n=== Concurrent Call Events Test Results ===")
            for event_type, metrics in all_metrics:
                print(f"{event_type}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.avg_response_time:.3f}s avg, "
                      f"{metrics.error_rate:.2%} error rate")
                
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_concurrent_audio_streaming(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        memory_leak_detector,
        load_test_config: Dict[str, Any]
    ):
        """Test concurrent audio streaming operations"""
        
        performance_monitor.start_monitoring()
        memory_leak_detector.set_baseline()
        
        # Audio streaming simulation payload
        audio_payload = {
            "call_id": "call_audio_001",
            "audio_format": "wav",
            "sample_rate": 16000,
            "channels": 1,
            "duration_ms": 5000
        }
        
        try:
            # Test audio upload/streaming
            upload_metrics = await load_test_runner.run_concurrent_requests(
                endpoint="/api/v1/audio/upload",
                method="POST",
                payload=audio_payload,
                concurrent_users=load_test_config["concurrent_users"] // 3,  # Audio is more resource intensive
                requests_per_user=5,  # Fewer requests for audio
                delay_between_requests=0.2
            )
            
            memory_leak_detector.take_snapshot("after_audio_upload")
            
            # Test TTS synthesis
            tts_payload = {
                "text": "Hello, this is a test message for text-to-speech synthesis.",
                "voice": "en-US-Standard-A",
                "audio_format": "wav"
            }
            
            tts_metrics = await load_test_runner.run_concurrent_requests(
                endpoint="/api/v1/tts/synthesize",
                method="POST",
                payload=tts_payload,
                concurrent_users=load_test_config["concurrent_users"] // 3,
                requests_per_user=5,
                delay_between_requests=0.2
            )
            
            memory_leak_detector.take_snapshot("after_tts_synthesis")
            
            # Validate audio processing performance
            assert upload_metrics.error_rate <= load_test_config["max_error_rate"], \
                f"Audio upload error rate {upload_metrics.error_rate:.2%} exceeds threshold"
            
            assert tts_metrics.error_rate <= load_test_config["max_error_rate"], \
                f"TTS synthesis error rate {tts_metrics.error_rate:.2%} exceeds threshold"
            
            # Audio operations should have reasonable response times (allowing for processing)
            max_audio_response_time = load_test_config["max_response_time"] * 3  # 3x normal for audio
            assert upload_metrics.avg_response_time <= max_audio_response_time, \
                f"Audio upload response time {upload_metrics.avg_response_time:.2f}s exceeds threshold"
            
            assert tts_metrics.avg_response_time <= max_audio_response_time, \
                f"TTS response time {tts_metrics.avg_response_time:.2f}s exceeds threshold"
            
            # Check for memory leaks in audio processing
            memory_report = memory_leak_detector.get_report()
            assert not memory_report["potential_leak"], \
                f"Potential memory leak detected in audio processing: {memory_report}"
            
            print(f"\n=== Concurrent Audio Streaming Test Results ===")
            print(f"Audio Upload: {upload_metrics.requests_per_second:.1f} RPS, "
                  f"{upload_metrics.avg_response_time:.3f}s avg")
            print(f"TTS Synthesis: {tts_metrics.requests_per_second:.1f} RPS, "
                  f"{tts_metrics.avg_response_time:.3f}s avg")
            print(f"Memory Report: {memory_report}")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_concurrent_call_routing(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        load_test_config: Dict[str, Any]
    ):
        """Test concurrent call routing and transfer operations"""
        
        performance_monitor.start_monitoring()
        
        # Call routing scenarios
        routing_scenarios = [
            {
                "call_id": "route_001",
                "action": "route_to_reception",
                "destination": "reception",
                "priority": "high"
            },
            {
                "call_id": "route_002", 
                "action": "route_to_room_service",
                "destination": "room_service",
                "priority": "normal"
            },
            {
                "call_id": "route_003",
                "action": "route_to_concierge",
                "destination": "concierge", 
                "priority": "normal"
            },
            {
                "call_id": "route_004",
                "action": "route_to_maintenance",
                "destination": "maintenance",
                "priority": "urgent"
            }
        ]
        
        try:
            routing_metrics = []
            
            for scenario in routing_scenarios:
                metrics = await load_test_runner.run_concurrent_requests(
                    endpoint="/api/v1/calls/route",
                    method="POST",
                    payload=scenario,
                    concurrent_users=load_test_config["concurrent_users"] // 4,
                    requests_per_user=load_test_config["requests_per_user"] // 2,
                    delay_between_requests=0.1
                )
                
                routing_metrics.append((scenario["action"], metrics))
                
                # Validate routing performance
                assert metrics.error_rate <= load_test_config["max_error_rate"], \
                    f"Routing error rate for {scenario['action']}: {metrics.error_rate:.2%} exceeds threshold"
            
            # Test call transfer operations
            transfer_payload = {
                "call_id": "transfer_001",
                "from_extension": "101",
                "to_extension": "reception",
                "transfer_type": "warm"
            }
            
            transfer_metrics = await load_test_runner.run_concurrent_requests(
                endpoint="/api/v1/calls/transfer",
                method="POST",
                payload=transfer_payload,
                concurrent_users=load_test_config["concurrent_users"] // 2,
                requests_per_user=load_test_config["requests_per_user"] // 2,
                delay_between_requests=0.15
            )
            
            assert transfer_metrics.error_rate <= load_test_config["max_error_rate"], \
                f"Transfer error rate {transfer_metrics.error_rate:.2%} exceeds threshold"
            
            print(f"\n=== Concurrent Call Routing Test Results ===")
            for action, metrics in routing_metrics:
                print(f"{action}: {metrics.requests_per_second:.1f} RPS, "
                      f"{metrics.avg_response_time:.3f}s avg")
            print(f"Call Transfer: {transfer_metrics.requests_per_second:.1f} RPS, "
                  f"{transfer_metrics.avg_response_time:.3f}s avg")
                  
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_mixed_call_operations_load(
        self,
        load_test_runner: LoadTestRunner,
        performance_monitor: PerformanceMonitor,
        memory_leak_detector,
        load_test_config: Dict[str, Any]
    ):
        """Test mixed call operations under realistic load patterns"""
        
        performance_monitor.start_monitoring()
        memory_leak_detector.set_baseline()
        
        # Simulate realistic mixed workload
        operations = [
            {"endpoint": "/api/v1/calls", "method": "POST", "weight": 0.3},  # 30% call creation
            {"endpoint": "/webhook/call-event", "method": "POST", "weight": 0.4},  # 40% events
            {"endpoint": "/api/v1/calls/route", "method": "POST", "weight": 0.2},  # 20% routing
            {"endpoint": "/api/v1/calls/transfer", "method": "POST", "weight": 0.1}  # 10% transfers
        ]
        
        try:
            # Run mixed operations concurrently
            tasks = []
            
            for operation in operations:
                num_users = int(load_test_config["concurrent_users"] * operation["weight"])
                if num_users == 0:
                    continue
                    
                # Create appropriate payload for each operation
                if "calls" in operation["endpoint"] and operation["method"] == "POST":
                    payload = {"hotel_id": "hotel_123", "room_number": "101"}
                elif "call-event" in operation["endpoint"]:
                    payload = {"event": "call.started", "call_id": f"call_{int(time.time())}"}
                elif "route" in operation["endpoint"]:
                    payload = {"call_id": f"route_{int(time.time())}", "destination": "reception"}
                elif "transfer" in operation["endpoint"]:
                    payload = {"call_id": f"transfer_{int(time.time())}", "to_extension": "reception"}
                else:
                    payload = {}
                
                task = load_test_runner.run_concurrent_requests(
                    endpoint=operation["endpoint"],
                    method=operation["method"],
                    payload=payload,
                    concurrent_users=num_users,
                    requests_per_user=load_test_config["requests_per_user"],
                    delay_between_requests=0.1
                )
                tasks.append((operation["endpoint"], task))
            
            # Execute all operations concurrently
            results = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)
            
            memory_leak_detector.take_snapshot("after_mixed_operations")
            
            # Analyze results
            total_requests = 0
            total_errors = 0
            
            for i, (endpoint, _) in enumerate(tasks):
                if isinstance(results[i], LoadTestMetrics):
                    metrics = results[i]
                    total_requests += metrics.total_requests
                    total_errors += metrics.failed_requests
                    
                    print(f"{endpoint}: {metrics.requests_per_second:.1f} RPS, "
                          f"{metrics.error_rate:.2%} error rate")
            
            overall_error_rate = total_errors / total_requests if total_requests > 0 else 0
            
            assert overall_error_rate <= load_test_config["max_error_rate"], \
                f"Overall mixed operations error rate {overall_error_rate:.2%} exceeds threshold"
            
            # Check for memory leaks
            memory_report = memory_leak_detector.get_report()
            assert not memory_report["potential_leak"], \
                f"Potential memory leak detected in mixed operations: {memory_report}"
            
            print(f"\n=== Mixed Call Operations Load Test Results ===")
            print(f"Total Requests: {total_requests}")
            print(f"Overall Error Rate: {overall_error_rate:.2%}")
            print(f"Memory Report: {memory_report}")
            
        finally:
            memory_snapshots = performance_monitor.stop_monitoring()
            
            # Generate performance report
            if memory_snapshots:
                max_memory = max(s.rss_mb for s in memory_snapshots)
                avg_memory = sum(s.rss_mb for s in memory_snapshots) / len(memory_snapshots)
                print(f"Peak Memory Usage: {max_memory:.1f}MB")
                print(f"Average Memory Usage: {avg_memory:.1f}MB")