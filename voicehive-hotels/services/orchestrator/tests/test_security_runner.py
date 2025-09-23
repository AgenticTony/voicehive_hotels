"""
Security Test Runner for VoiceHive Hotels
Comprehensive security test execution with reporting and validation
"""

import pytest
import sys
import os
import json
import time
from datetime import datetime
from typing import Dict, List, Any
from pathlib import Path

# Add the orchestrator directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class SecurityTestRunner:
    """Comprehensive security test runner with reporting"""
    
    def __init__(self):
        self.test_results = {}
        self.start_time = None
        self.end_time = None
        
    def run_all_security_tests(self) -> Dict[str, Any]:
        """Run all security tests and generate comprehensive report"""
        
        self.start_time = datetime.utcnow()
        print("🔒 Starting Comprehensive Security Test Suite")
        print("=" * 60)
        
        # Define test suites
        test_suites = [
            {
                "name": "JWT Token Security Tests",
                "file": "test_security_validation_comprehensive.py::TestJWTTokenSecurity",
                "description": "JWT token creation, validation, expiration, and security"
            },
            {
                "name": "API Key Security Tests", 
                "file": "test_security_validation_comprehensive.py::TestAPIKeySecurity",
                "description": "API key validation, rotation, and rate limiting"
            },
            {
                "name": "Input Validation Security Tests",
                "file": "test_security_validation_comprehensive.py::TestInputValidationSecurity", 
                "description": "XSS, SQL injection, and input validation security"
            },
            {
                "name": "Webhook Security Tests",
                "file": "test_security_validation_comprehensive.py::TestWebhookSignatureVerification",
                "description": "Webhook signature verification and security"
            },
            {
                "name": "Audit Logging Tests",
                "file": "test_security_validation_comprehensive.py::TestAuditLoggingCompleteness",
                "description": "Audit logging completeness and compliance"
            },
            {
                "name": "RBAC Permission Tests",
                "file": "test_security_validation_comprehensive.py::TestRBACPermissionBoundaries",
                "description": "Role-based access control and permission boundaries"
            },
            {
                "name": "Advanced JWT Attack Tests",
                "file": "test_security_penetration.py::TestAdvancedJWTAttacks",
                "description": "Advanced JWT attack scenarios and prevention"
            },
            {
                "name": "Advanced Input Validation Tests",
                "file": "test_security_penetration.py::TestAdvancedInputValidationAttacks",
                "description": "Advanced input validation attack scenarios"
            },
            {
                "name": "Advanced Webhook Attack Tests",
                "file": "test_security_penetration.py::TestAdvancedWebhookAttacks",
                "description": "Advanced webhook attack scenarios"
            },
            {
                "name": "Security Bypass Tests",
                "file": "test_security_penetration.py::TestSecurityBypassAttempts",
                "description": "Security bypass attempt detection"
            },
            {
                "name": "GDPR Compliance Tests",
                "file": "test_security_compliance.py::TestGDPRCompliance",
                "description": "GDPR compliance and data protection"
            },
            {
                "name": "Security Documentation Tests",
                "file": "test_security_compliance.py::TestSecurityDocumentationCompliance",
                "description": "Security documentation completeness"
            },
            {
                "name": "Security Configuration Tests",
                "file": "test_security_compliance.py::TestSecurityConfigurationValidation",
                "description": "Security configuration validation"
            },
            {
                "name": "Regulatory Compliance Tests",
                "file": "test_security_compliance.py::TestRegulatoryCompliance",
                "description": "PCI DSS, SOX, and ISO 27001 compliance"
            }
        ]
        
        # Run each test suite
        for suite in test_suites:
            print(f"\n🧪 Running: {suite['name']}")
            print(f"   {suite['description']}")
            
            result = self._run_test_suite(suite)
            self.test_results[suite['name']] = result
            
            # Print immediate results
            if result['passed']:
                print(f"   ✅ PASSED ({result['duration']:.2f}s)")
            else:
                print(f"   ❌ FAILED ({result['duration']:.2f}s)")
                if result['errors']:
                    print(f"   Errors: {len(result['errors'])}")
        
        self.end_time = datetime.utcnow()
        
        # Generate comprehensive report
        report = self._generate_security_report()
        
        # Print summary
        self._print_summary()
        
        return report
    
    def _run_test_suite(self, suite: Dict[str, str]) -> Dict[str, Any]:
        """Run a single test suite"""
        
        start_time = time.time()
        
        # Prepare pytest arguments
        pytest_args = [
            suite['file'],
            '-v',
            '--tb=short',
            '--json-report',
            '--json-report-file=/tmp/pytest_report.json'
        ]
        
        try:
            # Run pytest
            exit_code = pytest.main(pytest_args)
            
            # Read JSON report if available
            report_data = {}
            try:
                with open('/tmp/pytest_report.json', 'r') as f:
                    report_data = json.load(f)
            except FileNotFoundError:
                pass
            
            end_time = time.time()
            duration = end_time - start_time
            
            return {
                'passed': exit_code == 0,
                'exit_code': exit_code,
                'duration': duration,
                'report_data': report_data,
                'errors': self._extract_errors_from_report(report_data)
            }
            
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            
            return {
                'passed': False,
                'exit_code': -1,
                'duration': duration,
                'report_data': {},
                'errors': [str(e)]
            }
    
    def _extract_errors_from_report(self, report_data: Dict) -> List[str]:
        """Extract error messages from pytest report"""
        errors = []
        
        if 'tests' in report_data:
            for test in report_data['tests']:
                if test.get('outcome') == 'failed':
                    if 'call' in test and 'longrepr' in test['call']:
                        errors.append(test['call']['longrepr'])
        
        return errors
    
    def _generate_security_report(self) -> Dict[str, Any]:
        """Generate comprehensive security test report"""
        
        total_suites = len(self.test_results)
        passed_suites = sum(1 for result in self.test_results.values() if result['passed'])
        failed_suites = total_suites - passed_suites
        
        total_duration = (self.end_time - self.start_time).total_seconds()
        
        report = {
            'summary': {
                'total_test_suites': total_suites,
                'passed_suites': passed_suites,
                'failed_suites': failed_suites,
                'success_rate': (passed_suites / total_suites) * 100 if total_suites > 0 else 0,
                'total_duration': total_duration,
                'start_time': self.start_time.isoformat(),
                'end_time': self.end_time.isoformat()
            },
            'test_results': self.test_results,
            'security_coverage': self._calculate_security_coverage(),
            'recommendations': self._generate_recommendations()
        }
        
        # Save report to file
        report_file = f"security_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n📊 Detailed report saved to: {report_file}")
        
        return report
    
    def _calculate_security_coverage(self) -> Dict[str, Any]:
        """Calculate security test coverage metrics"""
        
        coverage_areas = {
            'authentication': ['JWT Token Security Tests', 'API Key Security Tests', 'Advanced JWT Attack Tests'],
            'authorization': ['RBAC Permission Tests'],
            'input_validation': ['Input Validation Security Tests', 'Advanced Input Validation Tests'],
            'webhook_security': ['Webhook Security Tests', 'Advanced Webhook Attack Tests'],
            'audit_logging': ['Audit Logging Tests'],
            'compliance': ['GDPR Compliance Tests', 'Security Documentation Tests', 'Regulatory Compliance Tests'],
            'penetration_testing': ['Advanced JWT Attack Tests', 'Advanced Input Validation Tests', 'Security Bypass Tests']
        }
        
        coverage = {}
        for area, test_suites in coverage_areas.items():
            passed_tests = sum(1 for suite in test_suites if self.test_results.get(suite, {}).get('passed', False))
            total_tests = len(test_suites)
            coverage[area] = {
                'passed': passed_tests,
                'total': total_tests,
                'percentage': (passed_tests / total_tests) * 100 if total_tests > 0 else 0
            }
        
        return coverage
    
    def _generate_recommendations(self) -> List[str]:
        """Generate security recommendations based on test results"""
        
        recommendations = []
        
        # Check for failed test suites
        failed_suites = [name for name, result in self.test_results.items() if not result['passed']]
        
        if failed_suites:
            recommendations.append(f"Address failures in: {', '.join(failed_suites)}")
        
        # Check coverage
        coverage = self._calculate_security_coverage()
        
        for area, metrics in coverage.items():
            if metrics['percentage'] < 100:
                recommendations.append(f"Improve {area} test coverage (currently {metrics['percentage']:.1f}%)")
        
        # General recommendations
        if not recommendations:
            recommendations.extend([
                "All security tests passed! Consider adding more edge case tests",
                "Regularly update security test scenarios based on new threats",
                "Implement continuous security testing in CI/CD pipeline",
                "Review and update security policies quarterly"
            ])
        
        return recommendations
    
    def _print_summary(self):
        """Print test execution summary"""
        
        print("\n" + "=" * 60)
        print("🔒 SECURITY TEST SUMMARY")
        print("=" * 60)
        
        total_suites = len(self.test_results)
        passed_suites = sum(1 for result in self.test_results.values() if result['passed'])
        failed_suites = total_suites - passed_suites
        
        print(f"Total Test Suites: {total_suites}")
        print(f"Passed: {passed_suites} ✅")
        print(f"Failed: {failed_suites} ❌")
        print(f"Success Rate: {(passed_suites / total_suites) * 100:.1f}%")
        print(f"Total Duration: {(self.end_time - self.start_time).total_seconds():.2f}s")
        
        # Print coverage summary
        coverage = self._calculate_security_coverage()
        print("\n📊 SECURITY COVERAGE:")
        for area, metrics in coverage.items():
            status = "✅" if metrics['percentage'] == 100 else "⚠️" if metrics['percentage'] >= 80 else "❌"
            print(f"  {area.replace('_', ' ').title()}: {metrics['percentage']:.1f}% {status}")
        
        # Print recommendations
        recommendations = self._generate_recommendations()
        if recommendations:
            print("\n💡 RECOMMENDATIONS:")
            for i, rec in enumerate(recommendations, 1):
                print(f"  {i}. {rec}")
        
        # Overall security status
        overall_success = failed_suites == 0
        if overall_success:
            print("\n🎉 ALL SECURITY TESTS PASSED!")
            print("   Your application has strong security controls.")
        else:
            print(f"\n⚠️  {failed_suites} TEST SUITE(S) FAILED")
            print("   Please address the failed tests before production deployment.")


def run_security_validation():
    """Main function to run security validation"""
    
    print("VoiceHive Hotels - Security Validation Suite")
    print("Task 10: Security Testing & Validation")
    print("=" * 60)
    
    # Check if we're in the right directory
    current_dir = os.getcwd()
    if not os.path.exists("voicehive-hotels/services/orchestrator"):
        print("❌ Error: Please run from the project root directory")
        return False
    
    # Change to orchestrator directory for tests
    os.chdir("voicehive-hotels/services/orchestrator")
    
    try:
        # Run security tests
        runner = SecurityTestRunner()
        report = runner.run_all_security_tests()
        
        # Return to original directory
        os.chdir(current_dir)
        
        # Check if all tests passed
        all_passed = all(result['passed'] for result in report['test_results'].values())
        
        if all_passed:
            print("\n✅ Security validation completed successfully!")
            print("   All security controls are properly implemented and tested.")
            return True
        else:
            print("\n❌ Security validation found issues!")
            print("   Please review the failed tests and address security gaps.")
            return False
            
    except Exception as e:
        print(f"\n❌ Error running security tests: {e}")
        os.chdir(current_dir)
        return False


if __name__ == "__main__":
    success = run_security_validation()
    sys.exit(0 if success else 1)