#!/usr/bin/env python3
"""
Enhanced Test Coverage Runner
Main runner for executing comprehensive testing coverage enhancement.

This script orchestrates all testing components to achieve >90% coverage
and production readiness validation.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('test_reports/enhanced_coverage.log')
    ]
)
logger = logging.getLogger(__name__)

# Import test framework components
try:
    from test_coverage_enhancement import EnhancedTestSuite, TestConfiguration
except ImportError:
    logger.error("Could not import test framework. Ensure all dependencies are installed.")
    sys.exit(1)


class EnhancedCoverageRunner:
    """
    Main runner for enhanced test coverage execution
    """
    
    def __init__(self, config: TestConfiguration):
        self.config = config
        self.start_time = None
        self.end_time = None
        self.results = {}
        
        # Ensure output directory exists
        self.output_dir = Path("test_reports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def run_all_tests(self, test_categories: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Run all enhanced testing categories
        
        Args:
            test_categories: Optional list of specific categories to run
                           ['coverage', 'load', 'chaos', 'security', 'performance', 'contract']
        
        Returns:
            Dict containing comprehensive test results
        """
        self.start_time = datetime.utcnow()
        logger.info("Starting enhanced test coverage execution")
        
        try:
            # Initialize test suite
            test_suite = EnhancedTestSuite(self.config)
            
            # Run comprehensive tests
            if test_categories:
                logger.info(f"Running specific test categories: {test_categories}")
                results = await self._run_selective_tests(test_suite, test_categories)
            else:
                logger.info("Running all test categories")
                results = await test_suite.run_comprehensive_tests()
            
            self.results = results
            self.end_time = datetime.utcnow()
            
            # Generate and save reports
            await self._generate_reports()
            
            # Print summary
            self._print_summary()
            
            return results
            
        except Exception as e:
            logger.error(f"Error during enhanced test execution: {e}")
            raise
    
    async def _run_selective_tests(self, test_suite: EnhancedTestSuite, 
                                 categories: List[str]) -> Dict[str, Any]:
        """Run only selected test categories"""
        
        results = {}
        
        for category in categories:
            logger.info(f"Running {category} tests...")
            
            try:
                if category == 'coverage':
                    results['coverage'] = await test_suite.coverage_analyzer.analyze_and_enhance_coverage()
                elif category == 'load':
                    results['load_testing'] = await test_suite.load_tester.run_critical_journey_tests()
                elif category == 'chaos':
                    results['chaos_engineering'] = await test_suite.chaos_engineer.run_chaos_tests()
                elif category == 'security':
                    results['security_testing'] = await test_suite.security_tester.run_penetration_tests()
                elif category == 'performance':
                    results['performance_testing'] = await test_suite.performance_tester.run_regression_tests()
                elif category == 'contract':
                    results['contract_testing'] = await test_suite.contract_tester.run_contract_tests()
                else:
                    logger.warning(f"Unknown test category: {category}")
            
            except Exception as e:
                logger.error(f"Error running {category} tests: {e}")
                results[category] = {'error': str(e)}
        
        # Generate summary
        results['summary'] = test_suite._generate_comprehensive_report()
        
        return results
    
    async def _generate_reports(self):
        """Generate comprehensive test reports"""
        
        try:
            # Generate JSON report
            json_report_path = self.output_dir / f"enhanced_coverage_report_{int(time.time())}.json"
            with open(json_report_path, 'w') as f:
                json.dump(self.results, f, indent=2, default=str)
            
            logger.info(f"JSON report saved to: {json_report_path}")
            
            # Generate HTML report
            html_report_path = self.output_dir / f"enhanced_coverage_report_{int(time.time())}.html"
            await self._generate_html_report(html_report_path)
            
            logger.info(f"HTML report saved to: {html_report_path}")
            
            # Generate summary report
            summary_path = self.output_dir / "latest_summary.txt"
            await self._generate_summary_report(summary_path)
            
            logger.info(f"Summary report saved to: {summary_path}")
        
        except Exception as e:
            logger.error(f"Error generating reports: {e}")
    
    async def _generate_html_report(self, output_path: Path):
        """Generate HTML report"""
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Enhanced Test Coverage Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
        .success {{ background-color: #d4edda; border-color: #c3e6cb; }}
        .warning {{ background-color: #fff3cd; border-color: #ffeaa7; }}
        .error {{ background-color: #f8d7da; border-color: #f5c6cb; }}
        .metric {{ display: inline-block; margin: 10px; padding: 10px; background-color: #e9ecef; border-radius: 3px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .progress-bar {{ width: 100%; background-color: #f0f0f0; border-radius: 3px; }}
        .progress-fill {{ height: 20px; background-color: #28a745; border-radius: 3px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Enhanced Test Coverage Report</h1>
        <p>Generated: {datetime.utcnow().isoformat()}</p>
        <p>Duration: {(self.end_time - self.start_time).total_seconds():.1f} seconds</p>
    </div>
    
    {self._generate_html_summary()}
    {self._generate_html_coverage_section()}
    {self._generate_html_load_testing_section()}
    {self._generate_html_chaos_section()}
    {self._generate_html_security_section()}
    {self._generate_html_performance_section()}
    {self._generate_html_contract_section()}
    {self._generate_html_recommendations()}
    
</body>
</html>
"""
        
        with open(output_path, 'w') as f:
            f.write(html_content)
    
    def _generate_html_summary(self) -> str:
        """Generate HTML summary section"""
        
        summary = self.results.get('summary', {})
        exec_summary = summary.get('execution_summary', {})
        
        production_ready = exec_summary.get('production_ready', False)
        status_class = 'success' if production_ready else 'error'
        
        return f"""
    <div class="section {status_class}">
        <h2>Executive Summary</h2>
        <div class="metric">
            <strong>Production Ready:</strong> {'✅ YES' if production_ready else '❌ NO'}
        </div>
        <div class="metric">
            <strong>Total Tests:</strong> {exec_summary.get('total_tests', 0)}
        </div>
        <div class="metric">
            <strong>Passed Tests:</strong> {exec_summary.get('passed_tests', 0)}
        </div>
        <div class="metric">
            <strong>Success Rate:</strong> {exec_summary.get('success_rate_percent', 0):.1f}%
        </div>
    </div>
"""
    
    def _generate_html_coverage_section(self) -> str:
        """Generate HTML coverage section"""
        
        coverage = self.results.get('coverage', {})
        if not coverage:
            return '<div class="section warning"><h2>Coverage Analysis</h2><p>No coverage data available</p></div>'
        
        coverage_pct = coverage.get('overall_coverage_percent', 0)
        target_pct = self.config.target_coverage_percentage
        
        status_class = 'success' if coverage_pct >= target_pct else 'warning'
        
        return f"""
    <div class="section {status_class}">
        <h2>Test Coverage Analysis</h2>
        <div class="progress-bar">
            <div class="progress-fill" style="width: {coverage_pct}%"></div>
        </div>
        <p><strong>Coverage:</strong> {coverage_pct:.1f}% (Target: {target_pct}%)</p>
        <p><strong>New Tests Added:</strong> {coverage.get('new_tests_added', 0)}</p>
        <p><strong>Missing Areas:</strong> {len(coverage.get('missing_coverage_areas', []))}</p>
    </div>
"""
    
    def _generate_html_load_testing_section(self) -> str:
        """Generate HTML load testing section"""
        
        load_testing = self.results.get('load_testing', {})
        if not load_testing:
            return '<div class="section warning"><h2>Load Testing</h2><p>No load testing data available</p></div>'
        
        success = load_testing.get('overall_success', False)
        status_class = 'success' if success else 'error'
        
        return f"""
    <div class="section {status_class}">
        <h2>Load Testing Results</h2>
        <div class="metric">
            <strong>Overall Success:</strong> {'✅' if success else '❌'}
        </div>
        <div class="metric">
            <strong>Total Requests:</strong> {load_testing.get('total_requests', 0)}
        </div>
        <div class="metric">
            <strong>Success Rate:</strong> {load_testing.get('overall_success_rate', 0):.2%}
        </div>
        <div class="metric">
            <strong>Avg Response Time:</strong> {load_testing.get('average_response_time_ms', 0):.0f}ms
        </div>
    </div>
"""
    
    def _generate_html_chaos_section(self) -> str:
        """Generate HTML chaos engineering section"""
        
        chaos = self.results.get('chaos_engineering', {})
        if not chaos:
            return '<div class="section warning"><h2>Chaos Engineering</h2><p>No chaos testing data available</p></div>'
        
        success = chaos.get('overall_success', False)
        status_class = 'success' if success else 'error'
        
        return f"""
    <div class="section {status_class}">
        <h2>Chaos Engineering Results</h2>
        <div class="metric">
            <strong>Overall Success:</strong> {'✅' if success else '❌'}
        </div>
        <div class="metric">
            <strong>Scenarios Tested:</strong> {chaos.get('failure_scenarios_tested', 0)}
        </div>
        <div class="metric">
            <strong>Recovery Time:</strong> {chaos.get('recovery_time_seconds', 0):.1f}s
        </div>
        <div class="metric">
            <strong>Resilience Score:</strong> {chaos.get('resilience_score', 0):.1f}%
        </div>
    </div>
"""
    
    def _generate_html_security_section(self) -> str:
        """Generate HTML security testing section"""
        
        security = self.results.get('security_testing', {})
        if not security:
            return '<div class="section warning"><h2>Security Testing</h2><p>No security testing data available</p></div>'
        
        critical_vulns = security.get('critical_vulnerabilities', 0)
        status_class = 'success' if critical_vulns == 0 else 'error'
        
        return f"""
    <div class="section {status_class}">
        <h2>Security Testing Results</h2>
        <div class="metric">
            <strong>Security Score:</strong> {security.get('security_score', 0):.0f}/100
        </div>
        <div class="metric">
            <strong>Critical Vulnerabilities:</strong> {critical_vulns}
        </div>
        <div class="metric">
            <strong>High Vulnerabilities:</strong> {security.get('high_vulnerabilities', 0)}
        </div>
        <div class="metric">
            <strong>Total Vulnerabilities:</strong> {security.get('vulnerabilities_found', 0)}
        </div>
    </div>
"""
    
    def _generate_html_performance_section(self) -> str:
        """Generate HTML performance testing section"""
        
        performance = self.results.get('performance_testing', {})
        if not performance:
            return '<div class="section warning"><h2>Performance Testing</h2><p>No performance testing data available</p></div>'
        
        regression = performance.get('regression_detected', False)
        status_class = 'error' if regression else 'success'
        
        return f"""
    <div class="section {status_class}">
        <h2>Performance Testing Results</h2>
        <div class="metric">
            <strong>Regression Detected:</strong> {'❌ YES' if regression else '✅ NO'}
        </div>
        <div class="metric">
            <strong>Avg Response Time:</strong> {performance.get('average_response_time_ms', 0):.0f}ms
        </div>
        <div class="metric">
            <strong>Peak Memory:</strong> {performance.get('peak_memory_usage_mb', 0):.0f}MB
        </div>
        <div class="metric">
            <strong>Performance Score:</strong> {performance.get('overall_performance_score', 0):.1f}/100
        </div>
    </div>
"""
    
    def _generate_html_contract_section(self) -> str:
        """Generate HTML contract testing section"""
        
        contract = self.results.get('contract_testing', {})
        if not contract:
            return '<div class="section warning"><h2>Contract Testing</h2><p>No contract testing data available</p></div>'
        
        success = contract.get('overall_success', False)
        status_class = 'success' if success else 'error'
        
        return f"""
    <div class="section {status_class}">
        <h2>Contract Testing Results</h2>
        <div class="metric">
            <strong>Overall Success:</strong> {'✅' if success else '❌'}
        </div>
        <div class="metric">
            <strong>PMS Connectors:</strong> {contract.get('pms_connectors_tested', 0)}
        </div>
        <div class="metric">
            <strong>Contract Violations:</strong> {contract.get('contract_violations', 0)}
        </div>
        <div class="metric">
            <strong>Compliance Score:</strong> {contract.get('compliance_score', 0):.1f}%
        </div>
    </div>
"""
    
    def _generate_html_recommendations(self) -> str:
        """Generate HTML recommendations section"""
        
        summary = self.results.get('summary', {})
        recommendations = summary.get('recommendations', [])
        
        if not recommendations:
            return '<div class="section success"><h2>Recommendations</h2><p>No recommendations - all tests passed!</p></div>'
        
        rec_html = '<div class="section warning"><h2>Recommendations</h2><ul>'
        for rec in recommendations:
            rec_html += f'<li>{rec}</li>'
        rec_html += '</ul></div>'
        
        return rec_html
    
    async def _generate_summary_report(self, output_path: Path):
        """Generate text summary report"""
        
        summary = self.results.get('summary', {})
        exec_summary = summary.get('execution_summary', {})
        
        content = f"""
ENHANCED TEST COVERAGE SUMMARY REPORT
=====================================

Generated: {datetime.utcnow().isoformat()}
Duration: {(self.end_time - self.start_time).total_seconds():.1f} seconds

EXECUTIVE SUMMARY
-----------------
Production Ready: {'YES' if exec_summary.get('production_ready', False) else 'NO'}
Total Tests: {exec_summary.get('total_tests', 0)}
Passed Tests: {exec_summary.get('passed_tests', 0)}
Success Rate: {exec_summary.get('success_rate_percent', 0):.1f}%

COVERAGE ANALYSIS
-----------------
{self._format_coverage_summary()}

LOAD TESTING
------------
{self._format_load_testing_summary()}

CHAOS ENGINEERING
-----------------
{self._format_chaos_summary()}

SECURITY TESTING
----------------
{self._format_security_summary()}

PERFORMANCE TESTING
-------------------
{self._format_performance_summary()}

CONTRACT TESTING
----------------
{self._format_contract_summary()}

RECOMMENDATIONS
---------------
{self._format_recommendations()}
"""
        
        with open(output_path, 'w') as f:
            f.write(content)
    
    def _format_coverage_summary(self) -> str:
        """Format coverage summary for text report"""
        coverage = self.results.get('coverage', {})
        if not coverage:
            return "No coverage data available"
        
        return f"""Current Coverage: {coverage.get('overall_coverage_percent', 0):.1f}%
Target Coverage: {self.config.target_coverage_percentage}%
New Tests Added: {coverage.get('new_tests_added', 0)}
Missing Areas: {len(coverage.get('missing_coverage_areas', []))}"""
    
    def _format_load_testing_summary(self) -> str:
        """Format load testing summary for text report"""
        load_testing = self.results.get('load_testing', {})
        if not load_testing:
            return "No load testing data available"
        
        return f"""Overall Success: {'YES' if load_testing.get('overall_success', False) else 'NO'}
Total Requests: {load_testing.get('total_requests', 0)}
Success Rate: {load_testing.get('overall_success_rate', 0):.2%}
Avg Response Time: {load_testing.get('average_response_time_ms', 0):.0f}ms"""
    
    def _format_chaos_summary(self) -> str:
        """Format chaos engineering summary for text report"""
        chaos = self.results.get('chaos_engineering', {})
        if not chaos:
            return "No chaos testing data available"
        
        return f"""Overall Success: {'YES' if chaos.get('overall_success', False) else 'NO'}
Scenarios Tested: {chaos.get('failure_scenarios_tested', 0)}
Recovery Time: {chaos.get('recovery_time_seconds', 0):.1f}s
Resilience Score: {chaos.get('resilience_score', 0):.1f}%"""
    
    def _format_security_summary(self) -> str:
        """Format security testing summary for text report"""
        security = self.results.get('security_testing', {})
        if not security:
            return "No security testing data available"
        
        return f"""Security Score: {security.get('security_score', 0):.0f}/100
Critical Vulnerabilities: {security.get('critical_vulnerabilities', 0)}
High Vulnerabilities: {security.get('high_vulnerabilities', 0)}
Total Vulnerabilities: {security.get('vulnerabilities_found', 0)}"""
    
    def _format_performance_summary(self) -> str:
        """Format performance testing summary for text report"""
        performance = self.results.get('performance_testing', {})
        if not performance:
            return "No performance testing data available"
        
        return f"""Regression Detected: {'YES' if performance.get('regression_detected', False) else 'NO'}
Avg Response Time: {performance.get('average_response_time_ms', 0):.0f}ms
Peak Memory: {performance.get('peak_memory_usage_mb', 0):.0f}MB
Performance Score: {performance.get('overall_performance_score', 0):.1f}/100"""
    
    def _format_contract_summary(self) -> str:
        """Format contract testing summary for text report"""
        contract = self.results.get('contract_testing', {})
        if not contract:
            return "No contract testing data available"
        
        return f"""Overall Success: {'YES' if contract.get('overall_success', False) else 'NO'}
PMS Connectors: {contract.get('pms_connectors_tested', 0)}
Contract Violations: {contract.get('contract_violations', 0)}
Compliance Score: {contract.get('compliance_score', 0):.1f}%"""
    
    def _format_recommendations(self) -> str:
        """Format recommendations for text report"""
        summary = self.results.get('summary', {})
        recommendations = summary.get('recommendations', [])
        
        if not recommendations:
            return "No recommendations - all tests passed!"
        
        return '\n'.join(f"- {rec}" for rec in recommendations)
    
    def _print_summary(self):
        """Print test execution summary to console"""
        
        summary = self.results.get('summary', {})
        exec_summary = summary.get('execution_summary', {})
        
        print("\n" + "="*60)
        print("ENHANCED TEST COVERAGE EXECUTION SUMMARY")
        print("="*60)
        
        production_ready = exec_summary.get('production_ready', False)
        print(f"Production Ready: {'✅ YES' if production_ready else '❌ NO'}")
        print(f"Total Tests: {exec_summary.get('total_tests', 0)}")
        print(f"Passed Tests: {exec_summary.get('passed_tests', 0)}")
        print(f"Success Rate: {exec_summary.get('success_rate_percent', 0):.1f}%")
        print(f"Duration: {(self.end_time - self.start_time).total_seconds():.1f} seconds")
        
        # Print key metrics
        if 'coverage' in self.results:
            coverage_pct = self.results['coverage'].get('overall_coverage_percent', 0)
            print(f"Coverage: {coverage_pct:.1f}% (Target: {self.config.target_coverage_percentage}%)")
        
        if 'security_testing' in self.results:
            security_score = self.results['security_testing'].get('security_score', 0)
            critical_vulns = self.results['security_testing'].get('critical_vulnerabilities', 0)
            print(f"Security Score: {security_score:.0f}/100 (Critical Vulns: {critical_vulns})")
        
        # Print recommendations
        recommendations = summary.get('recommendations', [])
        if recommendations:
            print("\nKey Recommendations:")
            for i, rec in enumerate(recommendations[:3], 1):
                print(f"{i}. {rec}")
        
        print("="*60)


def parse_arguments():
    """Parse command line arguments"""
    
    parser = argparse.ArgumentParser(
        description="Enhanced Test Coverage Runner for Production Readiness"
    )
    
    parser.add_argument(
        '--categories',
        nargs='+',
        choices=['coverage', 'load', 'chaos', 'security', 'performance', 'contract'],
        help='Specific test categories to run (default: all)'
    )
    
    parser.add_argument(
        '--concurrent-users',
        type=int,
        default=50,
        help='Number of concurrent users for load testing (default: 50)'
    )
    
    parser.add_argument(
        '--requests-per-user',
        type=int,
        default=100,
        help='Number of requests per user for load testing (default: 100)'
    )
    
    parser.add_argument(
        '--test-duration',
        type=int,
        default=300,
        help='Test duration in seconds for sustained tests (default: 300)'
    )
    
    parser.add_argument(
        '--coverage-target',
        type=float,
        default=90.0,
        help='Target coverage percentage (default: 90.0)'
    )
    
    parser.add_argument(
        '--memory-threshold',
        type=int,
        default=512,
        help='Memory threshold in MB (default: 512)'
    )
    
    parser.add_argument(
        '--output-dir',
        type=str,
        default='test_reports',
        help='Output directory for test reports (default: test_reports)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    return parser.parse_args()


async def main():
    """Main entry point"""
    
    args = parse_arguments()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create test configuration
    config = TestConfiguration(
        target_coverage_percentage=args.coverage_target,
        concurrent_users=args.concurrent_users,
        requests_per_user=args.requests_per_user,
        test_duration_seconds=args.test_duration,
        memory_threshold_mb=args.memory_threshold
    )
    
    # Create and run test runner
    runner = EnhancedCoverageRunner(config)
    
    try:
        results = await runner.run_all_tests(args.categories)
        
        # Determine exit code based on results
        summary = results.get('summary', {})
        exec_summary = summary.get('execution_summary', {})
        production_ready = exec_summary.get('production_ready', False)
        
        if production_ready:
            logger.info("All tests passed - system is production ready!")
            sys.exit(0)
        else:
            logger.error("Tests failed - system is not production ready")
            sys.exit(1)
    
    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())