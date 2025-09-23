"""
Integration Test Runner

Comprehensive test runner for all integration tests with reporting,
metrics collection, and CI/CD integration capabilities.
"""

import pytest
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import argparse


class IntegrationTestRunner:
    """Main integration test runner"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or self._load_default_config()
        self.results = {}
        self.start_time = None
        self.end_time = None
    
    def _load_default_config(self) -> Dict[str, Any]:
        """Load default test configuration"""
        return {
            "test_suites": {
                "call_flow": {
                    "module": "test_call_flow_e2e",
                    "description": "End-to-end call flow integration tests",
                    "timeout": 300,
                    "required": True
                },
                "pms_connector": {
                    "module": "test_pms_connector_integration", 
                    "description": "PMS connector integration tests",
                    "timeout": 240,
                    "required": True
                },
                "auth_flow": {
                    "module": "test_auth_flow_integration",
                    "description": "Authentication and authorization flow tests",
                    "timeout": 180,
                    "required": True
                },
                "resilience": {
                    "module": "test_resilience_integration",
                    "description": "Rate limiting and circuit breaker tests",
                    "timeout": 300,
                    "required": True
                },
                "error_recovery": {
                    "module": "test_error_recovery_integration",
                    "description": "Error handling and recovery tests",
                    "timeout": 240,
                    "required": True
                },
                "performance": {
                    "module": "test_performance_regression",
                    "description": "Performance regression tests",
                    "timeout": 600,
                    "required": False  # Optional for quick runs
                }
            },
            "reporting": {
                "output_dir": "test_reports",
                "formats": ["json", "html", "junit"],
                "include_metrics": True
            },
            "thresholds": {
                "max_test_duration": 1800,  # 30 minutes
                "min_pass_rate": 0.95,      # 95% tests must pass
                "max_error_rate": 0.05      # 5% error rate threshold
            }
        }
    
    async def run_test_suite(
        self,
        suite_name: str,
        suite_config: Dict[str, Any],
        pytest_args: List[str] = None
    ) -> Dict[str, Any]:
        """Run a specific test suite"""
        
        print(f"Running test suite: {suite_name}")
        print(f"Description: {suite_config['description']}")
        
        # Prepare pytest arguments
        args = [
            f"tests/integration/{suite_config['module']}.py",
            "-v",
            "--tb=short",
            f"--timeout={suite_config['timeout']}",
            "--asyncio-mode=auto"
        ]
        
        if pytest_args:
            args.extend(pytest_args)
        
        # Add output formats
        if self.config["reporting"]["include_metrics"]:
            args.extend([
                "--cov=.",
                "--cov-report=json",
                f"--cov-report=html:{self.config['reporting']['output_dir']}/coverage_{suite_name}"
            ])
        
        # Run pytest
        start_time = datetime.utcnow()
        
        try:
            # Use pytest.main() for programmatic execution
            exit_code = pytest.main(args)
            
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            result = {
                "suite_name": suite_name,
                "status": "passed" if exit_code == 0 else "failed",
                "exit_code": exit_code,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration": duration,
                "timeout": suite_config["timeout"],
                "required": suite_config["required"]
            }
            
            print(f"Suite {suite_name} completed: {result['status']} in {duration:.2f}s")
            return result
            
        except Exception as e:
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            result = {
                "suite_name": suite_name,
                "status": "error",
                "error": str(e),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration": duration,
                "timeout": suite_config["timeout"],
                "required": suite_config["required"]
            }
            
            print(f"Suite {suite_name} failed with error: {e}")
            return result
    
    async def run_all_suites(
        self,
        suite_filter: List[str] = None,
        pytest_args: List[str] = None
    ) -> Dict[str, Any]:
        """Run all configured test suites"""
        
        self.start_time = datetime.utcnow()
        print(f"Starting integration test run at {self.start_time}")
        
        # Filter suites if specified
        suites_to_run = self.config["test_suites"]
        if suite_filter:
            suites_to_run = {
                name: config for name, config in suites_to_run.items()
                if name in suite_filter
            }
        
        # Run suites sequentially (could be parallel in future)
        suite_results = []
        
        for suite_name, suite_config in suites_to_run.items():
            result = await self.run_test_suite(suite_name, suite_config, pytest_args)
            suite_results.append(result)
            
            # Stop on required suite failure if configured
            if (result["status"] != "passed" and 
                suite_config["required"] and 
                self.config.get("fail_fast", False)):
                print(f"Stopping test run due to required suite failure: {suite_name}")
                break
        
        self.end_time = datetime.utcnow()
        total_duration = (self.end_time - self.start_time).total_seconds()
        
        # Calculate summary statistics
        total_suites = len(suite_results)
        passed_suites = sum(1 for r in suite_results if r["status"] == "passed")
        failed_suites = sum(1 for r in suite_results if r["status"] == "failed")
        error_suites = sum(1 for r in suite_results if r["status"] == "error")
        
        pass_rate = passed_suites / total_suites if total_suites > 0 else 0
        
        # Overall result
        overall_status = "passed"
        if pass_rate < self.config["thresholds"]["min_pass_rate"]:
            overall_status = "failed"
        elif any(r["status"] != "passed" and r["required"] for r in suite_results):
            overall_status = "failed"
        
        summary = {
            "overall_status": overall_status,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "total_duration": total_duration,
            "statistics": {
                "total_suites": total_suites,
                "passed_suites": passed_suites,
                "failed_suites": failed_suites,
                "error_suites": error_suites,
                "pass_rate": pass_rate
            },
            "suite_results": suite_results,
            "thresholds": self.config["thresholds"]
        }
        
        print(f"\nIntegration test run completed:")
        print(f"Overall status: {overall_status}")
        print(f"Pass rate: {pass_rate:.2%}")
        print(f"Duration: {total_duration:.2f}s")
        
        return summary
    
    def generate_reports(self, results: Dict[str, Any]) -> None:
        """Generate test reports in various formats"""
        
        output_dir = Path(self.config["reporting"]["output_dir"])
        output_dir.mkdir(exist_ok=True)
        
        # JSON report
        if "json" in self.config["reporting"]["formats"]:
            json_file = output_dir / "integration_test_results.json"
            with open(json_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"JSON report saved to: {json_file}")
        
        # HTML report
        if "html" in self.config["reporting"]["formats"]:
            html_file = output_dir / "integration_test_report.html"
            self._generate_html_report(results, html_file)
            print(f"HTML report saved to: {html_file}")
        
        # JUnit XML report
        if "junit" in self.config["reporting"]["formats"]:
            junit_file = output_dir / "integration_test_results.xml"
            self._generate_junit_report(results, junit_file)
            print(f"JUnit report saved to: {junit_file}")
    
    def _generate_html_report(self, results: Dict[str, Any], output_file: Path) -> None:
        """Generate HTML test report"""
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Integration Test Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
                .summary {{ margin: 20px 0; }}
                .suite {{ margin: 10px 0; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }}
                .passed {{ background-color: #d4edda; }}
                .failed {{ background-color: #f8d7da; }}
                .error {{ background-color: #fff3cd; }}
                .metrics {{ font-family: monospace; background-color: #f8f9fa; padding: 10px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Integration Test Report</h1>
                <p>Generated: {datetime.utcnow().isoformat()}</p>
                <p>Overall Status: <strong>{results['overall_status'].upper()}</strong></p>
            </div>
            
            <div class="summary">
                <h2>Summary</h2>
                <ul>
                    <li>Total Duration: {results['total_duration']:.2f} seconds</li>
                    <li>Total Suites: {results['statistics']['total_suites']}</li>
                    <li>Passed: {results['statistics']['passed_suites']}</li>
                    <li>Failed: {results['statistics']['failed_suites']}</li>
                    <li>Errors: {results['statistics']['error_suites']}</li>
                    <li>Pass Rate: {results['statistics']['pass_rate']:.2%}</li>
                </ul>
            </div>
            
            <div class="suites">
                <h2>Test Suite Results</h2>
        """
        
        for suite_result in results['suite_results']:
            status_class = suite_result['status']
            html_content += f"""
                <div class="suite {status_class}">
                    <h3>{suite_result['suite_name']}</h3>
                    <p>Status: <strong>{suite_result['status'].upper()}</strong></p>
                    <p>Duration: {suite_result['duration']:.2f} seconds</p>
                    <p>Required: {'Yes' if suite_result['required'] else 'No'}</p>
                    {f"<p>Error: {suite_result.get('error', '')}</p>" if 'error' in suite_result else ""}
                </div>
            """
        
        html_content += """
            </div>
        </body>
        </html>
        """
        
        with open(output_file, 'w') as f:
            f.write(html_content)
    
    def _generate_junit_report(self, results: Dict[str, Any], output_file: Path) -> None:
        """Generate JUnit XML test report"""
        
        junit_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="integration_tests" 
            tests="{results['statistics']['total_suites']}" 
            failures="{results['statistics']['failed_suites']}" 
            errors="{results['statistics']['error_suites']}" 
            time="{results['total_duration']:.2f}">
"""
        
        for suite_result in results['suite_results']:
            junit_content += f"""
    <testsuite name="{suite_result['suite_name']}" 
               tests="1" 
               failures="{'1' if suite_result['status'] == 'failed' else '0'}" 
               errors="{'1' if suite_result['status'] == 'error' else '0'}" 
               time="{suite_result['duration']:.2f}">
        <testcase name="{suite_result['suite_name']}" 
                  classname="integration.{suite_result['suite_name']}" 
                  time="{suite_result['duration']:.2f}">
"""
            
            if suite_result['status'] == 'failed':
                junit_content += f"""
            <failure message="Test suite failed" type="TestFailure">
                Suite {suite_result['suite_name']} failed with exit code {suite_result.get('exit_code', 'unknown')}
            </failure>
"""
            elif suite_result['status'] == 'error':
                junit_content += f"""
            <error message="Test suite error" type="TestError">
                {suite_result.get('error', 'Unknown error')}
            </error>
"""
            
            junit_content += """
        </testcase>
    </testsuite>
"""
        
        junit_content += """
</testsuites>
"""
        
        with open(output_file, 'w') as f:
            f.write(junit_content)


async def main():
    """Main entry point for integration test runner"""
    
    parser = argparse.ArgumentParser(description="Integration Test Runner")
    parser.add_argument(
        "--suites", 
        nargs="+", 
        help="Specific test suites to run",
        choices=["call_flow", "pms_connector", "auth_flow", "resilience", "error_recovery", "performance"]
    )
    parser.add_argument(
        "--config", 
        help="Path to test configuration file"
    )
    parser.add_argument(
        "--output-dir", 
        default="test_reports",
        help="Output directory for test reports"
    )
    parser.add_argument(
        "--fail-fast", 
        action="store_true",
        help="Stop on first required suite failure"
    )
    parser.add_argument(
        "--skip-performance", 
        action="store_true",
        help="Skip performance tests for faster execution"
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = None
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = json.load(f)
    
    # Create test runner
    runner = IntegrationTestRunner(config)
    
    # Update configuration from command line args
    if args.output_dir:
        runner.config["reporting"]["output_dir"] = args.output_dir
    if args.fail_fast:
        runner.config["fail_fast"] = True
    if args.skip_performance:
        runner.config["test_suites"]["performance"]["required"] = False
    
    # Run tests
    try:
        results = await runner.run_all_suites(
            suite_filter=args.suites,
            pytest_args=["--tb=short", "-v"]
        )
        
        # Generate reports
        runner.generate_reports(results)
        
        # Exit with appropriate code
        exit_code = 0 if results["overall_status"] == "passed" else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\nTest run interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"Test run failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())