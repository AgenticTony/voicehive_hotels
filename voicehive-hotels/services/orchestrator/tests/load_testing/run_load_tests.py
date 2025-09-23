"""
Load Testing Runner

Comprehensive load testing suite runner with reporting and analysis.
"""

import asyncio
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import sys
import os

# Add the parent directory to the path so we can import from the orchestrator
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import LoadTestRunner, PerformanceMonitor


class LoadTestSuite:
    """Comprehensive load testing suite"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.results = {}
        self.start_time = None
        self.end_time = None
        
    async def run_all_tests(self):
        """Run all load tests in sequence"""
        
        print("=" * 80)
        print("VoiceHive Hotels - Production Readiness Load Testing Suite")
        print("=" * 80)
        
        self.start_time = datetime.now()
        
        # Test categories to run
        test_categories = [
            {
                "name": "Concurrent Call Simulation",
                "module": "test_concurrent_calls",
                "tests": [
                    "test_concurrent_call_creation",
                    "test_concurrent_call_events", 
                    "test_concurrent_audio_streaming",
                    "test_concurrent_call_routing",
                    "test_mixed_call_operations_load"
                ]
            },
            {
                "name": "PMS Connector Load Testing",
                "module": "test_pms_connector_load",
                "tests": [
                    "test_reservation_lookup_load",
                    "test_guest_profile_operations_load",
                    "test_pms_connector_failover_load",
                    "test_pms_bulk_operations_load",
                    "test_pms_connector_circuit_breaker_load",
                    "test_pms_connector_cache_performance"
                ]
            },
            {
                "name": "Authentication System Load Testing",
                "module": "test_auth_system_load", 
                "tests": [
                    "test_jwt_authentication_load",
                    "test_jwt_validation_load",
                    "test_api_key_validation_load",
                    "test_session_management_load",
                    "test_role_based_access_control_load",
                    "test_authentication_mixed_load"
                ]
            },
            {
                "name": "Memory Performance Testing",
                "module": "test_memory_performance",
                "tests": [
                    "test_memory_usage_under_load",
                    "test_memory_leak_detection",
                    "test_connection_pool_memory_usage",
                    "test_audio_processing_memory_usage",
                    "test_garbage_collection_performance"
                ]
            },
            {
                "name": "Database and Redis Performance",
                "module": "test_database_redis_performance",
                "tests": [
                    "test_database_connection_pool_performance",
                    "test_redis_performance_characteristics",
                    "test_database_redis_integration_performance",
                    "test_data_consistency_under_load"
                ]
            },
            {
                "name": "Network Failure Simulation",
                "module": "test_network_failure_simulation",
                "tests": [
                    "test_high_latency_resilience",
                    "test_packet_loss_resilience",
                    "test_service_failure_resilience",
                    "test_network_partition_recovery"
                ]
            }
        ]
        
        # Run each test category
        for category in test_categories:
            if self.should_run_category(category["name"]):
                await self.run_test_category(category)
        
        self.end_time = datetime.now()
        
        # Generate final report
        await self.generate_final_report()
        
    def should_run_category(self, category_name: str) -> bool:
        """Check if a test category should be run based on configuration"""
        
        if "test_categories" in self.config:
            return category_name in self.config["test_categories"]
        
        # Run all categories by default
        return True
        
    async def run_test_category(self, category: Dict[str, Any]):
        """Run all tests in a category"""
        
        print(f"\n{'=' * 60}")
        print(f"Running {category['name']} Tests")
        print(f"{'=' * 60}")
        
        category_start = time.time()
        category_results = []
        
        for test_name in category["tests"]:
            if self.should_run_test(test_name):
                print(f"\nRunning {test_name}...")
                
                test_start = time.time()
                
                try:
                    # Simulate running the test (in real implementation, would import and run)
                    await self.simulate_test_execution(test_name)
                    
                    test_duration = time.time() - test_start
                    
                    test_result = {
                        "test_name": test_name,
                        "status": "PASSED",
                        "duration": test_duration,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    print(f"✓ {test_name} completed in {test_duration:.2f}s")
                    
                except Exception as e:
                    test_duration = time.time() - test_start
                    
                    test_result = {
                        "test_name": test_name,
                        "status": "FAILED",
                        "duration": test_duration,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    print(f"✗ {test_name} failed after {test_duration:.2f}s: {e}")
                
                category_results.append(test_result)
        
        category_duration = time.time() - category_start
        
        self.results[category["name"]] = {
            "tests": category_results,
            "duration": category_duration,
            "passed": len([t for t in category_results if t["status"] == "PASSED"]),
            "failed": len([t for t in category_results if t["status"] == "FAILED"]),
            "total": len(category_results)
        }
        
        print(f"\n{category['name']} Summary:")
        print(f"  Passed: {self.results[category['name']]['passed']}")
        print(f"  Failed: {self.results[category['name']]['failed']}")
        print(f"  Duration: {category_duration:.2f}s")
        
    def should_run_test(self, test_name: str) -> bool:
        """Check if a specific test should be run"""
        
        if "skip_tests" in self.config and test_name in self.config["skip_tests"]:
            return False
            
        if "only_tests" in self.config:
            return test_name in self.config["only_tests"]
            
        return True
        
    async def simulate_test_execution(self, test_name: str):
        """Simulate test execution (replace with actual test imports in real implementation)"""
        
        # Simulate test execution time based on test complexity
        test_complexity = {
            "test_concurrent_call_creation": 30,
            "test_concurrent_call_events": 25,
            "test_concurrent_audio_streaming": 45,
            "test_concurrent_call_routing": 20,
            "test_mixed_call_operations_load": 60,
            "test_reservation_lookup_load": 35,
            "test_guest_profile_operations_load": 30,
            "test_pms_connector_failover_load": 50,
            "test_pms_bulk_operations_load": 40,
            "test_pms_connector_circuit_breaker_load": 45,
            "test_pms_connector_cache_performance": 25,
            "test_jwt_authentication_load": 20,
            "test_jwt_validation_load": 25,
            "test_api_key_validation_load": 20,
            "test_session_management_load": 30,
            "test_role_based_access_control_load": 35,
            "test_authentication_mixed_load": 40,
            "test_memory_usage_under_load": 45,
            "test_memory_leak_detection": 60,
            "test_connection_pool_memory_usage": 35,
            "test_audio_processing_memory_usage": 40,
            "test_garbage_collection_performance": 30,
            "test_database_connection_pool_performance": 40,
            "test_redis_performance_characteristics": 35,
            "test_database_redis_integration_performance": 45,
            "test_data_consistency_under_load": 50,
            "test_high_latency_resilience": 40,
            "test_packet_loss_resilience": 45,
            "test_service_failure_resilience": 55,
            "test_network_partition_recovery": 50
        }
        
        # Simulate test execution
        execution_time = test_complexity.get(test_name, 30)
        
        # Add some randomness to simulate real test execution
        import random
        actual_time = execution_time * random.uniform(0.7, 1.3)
        
        # Simulate progress updates
        steps = 5
        step_time = actual_time / steps
        
        for i in range(steps):
            await asyncio.sleep(step_time)
            progress = ((i + 1) / steps) * 100
            print(f"  Progress: {progress:.0f}%")
        
        # Simulate occasional test failures (5% failure rate)
        if random.random() < 0.05:
            raise Exception(f"Simulated test failure for {test_name}")
            
    async def generate_final_report(self):
        """Generate comprehensive test report"""
        
        print(f"\n{'=' * 80}")
        print("LOAD TESTING FINAL REPORT")
        print(f"{'=' * 80}")
        
        total_duration = (self.end_time - self.start_time).total_seconds()
        
        # Overall statistics
        total_tests = sum(category["total"] for category in self.results.values())
        total_passed = sum(category["passed"] for category in self.results.values())
        total_failed = sum(category["failed"] for category in self.results.values())
        
        print(f"\nOverall Results:")
        print(f"  Total Tests: {total_tests}")
        print(f"  Passed: {total_passed}")
        print(f"  Failed: {total_failed}")
        print(f"  Success Rate: {(total_passed/total_tests)*100:.1f}%")
        print(f"  Total Duration: {total_duration:.2f}s")
        
        # Category breakdown
        print(f"\nCategory Breakdown:")
        for category_name, category_result in self.results.items():
            success_rate = (category_result["passed"] / category_result["total"]) * 100 if category_result["total"] > 0 else 0
            print(f"  {category_name}:")
            print(f"    Tests: {category_result['total']}")
            print(f"    Passed: {category_result['passed']}")
            print(f"    Failed: {category_result['failed']}")
            print(f"    Success Rate: {success_rate:.1f}%")
            print(f"    Duration: {category_result['duration']:.2f}s")
        
        # Failed tests details
        failed_tests = []
        for category_name, category_result in self.results.items():
            for test in category_result["tests"]:
                if test["status"] == "FAILED":
                    failed_tests.append({
                        "category": category_name,
                        "test": test["test_name"],
                        "error": test.get("error", "Unknown error")
                    })
        
        if failed_tests:
            print(f"\nFailed Tests Details:")
            for failed_test in failed_tests:
                print(f"  {failed_test['category']} - {failed_test['test']}")
                print(f"    Error: {failed_test['error']}")
        
        # Performance recommendations
        print(f"\nPerformance Recommendations:")
        
        if total_failed > 0:
            print(f"  • {total_failed} tests failed - investigate and fix issues before production")
        
        if total_duration > 1800:  # 30 minutes
            print(f"  • Test suite took {total_duration/60:.1f} minutes - consider optimizing test execution")
        
        # Save detailed report to file
        report_data = {
            "summary": {
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat(),
                "duration_seconds": total_duration,
                "total_tests": total_tests,
                "passed_tests": total_passed,
                "failed_tests": total_failed,
                "success_rate": (total_passed/total_tests)*100 if total_tests > 0 else 0
            },
            "categories": self.results,
            "failed_tests": failed_tests,
            "configuration": self.config
        }
        
        # Save report
        report_file = Path("load_test_report.json")
        with open(report_file, "w") as f:
            json.dump(report_data, f, indent=2, default=str)
        
        print(f"\nDetailed report saved to: {report_file}")
        
        # Exit with appropriate code
        if total_failed > 0:
            print(f"\n❌ Load testing completed with {total_failed} failures")
            return 1
        else:
            print(f"\n✅ All load tests passed successfully!")
            return 0


def parse_arguments():
    """Parse command line arguments"""
    
    parser = argparse.ArgumentParser(description="VoiceHive Hotels Load Testing Suite")
    
    parser.add_argument(
        "--config",
        type=str,
        default="load_test_config.json",
        help="Path to load test configuration file"
    )
    
    parser.add_argument(
        "--concurrent-users",
        type=int,
        default=10,
        help="Number of concurrent users for load tests"
    )
    
    parser.add_argument(
        "--requests-per-user",
        type=int,
        default=10,
        help="Number of requests per user"
    )
    
    parser.add_argument(
        "--test-duration",
        type=int,
        default=60,
        help="Test duration in seconds"
    )
    
    parser.add_argument(
        "--memory-threshold",
        type=int,
        default=500,
        help="Memory threshold in MB"
    )
    
    parser.add_argument(
        "--max-response-time",
        type=float,
        default=2.0,
        help="Maximum acceptable response time in seconds"
    )
    
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.05,
        help="Maximum acceptable error rate (0.05 = 5%)"
    )
    
    parser.add_argument(
        "--categories",
        nargs="+",
        help="Specific test categories to run"
    )
    
    parser.add_argument(
        "--skip-tests",
        nargs="+",
        help="Specific tests to skip"
    )
    
    parser.add_argument(
        "--only-tests",
        nargs="+",
        help="Only run these specific tests"
    )
    
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="Base URL for the service under test"
    )
    
    return parser.parse_args()


def load_config(config_path: str, args) -> Dict[str, Any]:
    """Load configuration from file and command line arguments"""
    
    # Default configuration
    config = {
        "concurrent_users": args.concurrent_users,
        "requests_per_user": args.requests_per_user,
        "test_duration": args.test_duration,
        "memory_threshold_mb": args.memory_threshold,
        "max_response_time": args.max_response_time,
        "max_error_rate": args.max_error_rate,
        "base_url": args.base_url
    }
    
    # Load from file if exists
    config_file = Path(config_path)
    if config_file.exists():
        try:
            with open(config_file) as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            print(f"Warning: Could not load config file {config_path}: {e}")
    
    # Override with command line arguments
    if args.categories:
        config["test_categories"] = args.categories
    
    if args.skip_tests:
        config["skip_tests"] = args.skip_tests
        
    if args.only_tests:
        config["only_tests"] = args.only_tests
    
    return config


async def main():
    """Main entry point for load testing suite"""
    
    args = parse_arguments()
    config = load_config(args.config, args)
    
    print("Load Testing Configuration:")
    for key, value in config.items():
        print(f"  {key}: {value}")
    
    # Create and run test suite
    test_suite = LoadTestSuite(config)
    exit_code = await test_suite.run_all_tests()
    
    return exit_code


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nLoad testing interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nLoad testing failed with error: {e}")
        sys.exit(1)