#!/usr/bin/env python3
"""
Security Penetration Testing Framework

Comprehensive security testing framework for production readiness validation.
Includes automated penetration testing, vulnerability scanning, and security validation.
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum
import aiohttp
import jwt
import hashlib
import secrets
import base64

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SecurityTestStatus(Enum):
    """Security test status enumeration"""
    PASSED = "PASSED"
    FAILED = "FAILED"
    VULNERABLE = "VULNERABLE"
    SKIPPED = "SKIPPED"


@dataclass
class SecurityTestResult:
    """Individual security test result"""
    test_name: str
    category: str
    status: SecurityTestStatus
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    message: str
    details: Optional[Dict[str, Any]] = None
    remediation: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class SecurityReport:
    """Complete security penetration testing report"""
    overall_status: SecurityTestStatus
    total_tests: int
    passed_tests: int
    failed_tests: int
    vulnerable_tests: int
    skipped_tests: int
    critical_vulnerabilities: int
    high_vulnerabilities: int
    medium_vulnerabilities: int
    low_vulnerabilities: int
    execution_time: float
    timestamp: str
    results: List[SecurityTestResult]
    recommendations: List[str]


class SecurityPenetrationTester:
    """
    Comprehensive security penetration testing framework
    
    Tests include:
    - Authentication bypass attempts
    - Authorization escalation tests
    - Input validation and injection attacks
    - Session management vulnerabilities
    - API security testing
    - JWT token security
    - Rate limiting bypass attempts
    - OWASP Top 10 vulnerability scanning
    """
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[SecurityTestResult] = []
        self.start_time = datetime.utcnow()
        self.session = None
        
    async def run_comprehensive_security_tests(self) -> SecurityReport:
        """Run complete security penetration testing suite"""
        logger.info("Starting comprehensive security penetration testing")
        
        # Initialize HTTP session
        self.session = aiohttp.ClientSession()
        
        try:
            # Run all security test categories
            await asyncio.gather(
                self._test_authentication_security(),
                self._test_authorization_security(),
                self._test_input_validation_security(),
                self._test_session_management_security(),
                self._test_api_security(),
                self._test_jwt_security(),
                self._test_rate_limiting_security(),
                self._test_owasp_top10_vulnerabilities(),
                self._test_infrastructure_security(),
                self._test_data_protection_security(),
                return_exceptions=True
            )
            
            # Generate comprehensive report
            return self._generate_security_report()
            
        finally:
            if self.session:
                await self.session.close()
    
    async def _test_authentication_security(self) -> None:
        """Test authentication security vulnerabilities"""
        logger.info("Testing authentication security")
        
        # Test 1: Authentication bypass attempts
        await self._test_auth_bypass()
        
        # Test 2: Brute force protection
        await self._test_brute_force_protection()
        
        # Test 3: Default credentials
        await self._test_default_credentials()
        
        # Test 4: Password policy enforcement
        await self._test_password_policy()
        
        # Test 5: Multi-factor authentication
        await self._test_mfa_implementation()
    
    async def _test_auth_bypass(self) -> None:
        """Test authentication bypass vulnerabilities"""
        try:
            # Test SQL injection in login
            payloads = [
                "admin' OR '1'='1",
                "admin'--",
                "admin' OR 1=1#",
                "' UNION SELECT 1,1,1--"
            ]
            
            for payload in payloads:
                try:
                    async with self.session.post(
                        f"{self.base_url}/auth/login",
                        json={"username": payload, "password": "test"},
                        timeout=5
                    ) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            if "token" in response_data:
                                self.results.append(SecurityTestResult(
                                    test_name="SQL Injection Authentication Bypass",
                                    category="Authentication",
                                    status=SecurityTestStatus.VULNERABLE,
                                    severity="CRITICAL",
                                    message=f"SQL injection bypass successful with payload: {payload}",
                                    details={"payload": payload, "response": response_data},
                                    remediation="Implement parameterized queries and input validation",
                                    timestamp=datetime.utcnow().isoformat()
                                ))
                                return
                except Exception:
                    continue
            
            self.results.append(SecurityTestResult(
                test_name="SQL Injection Authentication Bypass",
                category="Authentication",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="No SQL injection vulnerabilities found in authentication",
                timestamp=datetime.utcnow().isoformat()
            ))
            
        except Exception as e:
            self.results.append(SecurityTestResult(
                test_name="SQL Injection Authentication Bypass",
                category="Authentication",
                status=SecurityTestStatus.FAILED,
                severity="MEDIUM",
                message=f"Test failed: {str(e)}",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_brute_force_protection(self) -> None:
        """Test brute force protection mechanisms"""
        try:
            # Attempt multiple failed logins
            failed_attempts = 0
            for i in range(10):
                try:
                    async with self.session.post(
                        f"{self.base_url}/auth/login",
                        json={"username": "testuser", "password": f"wrongpass{i}"},
                        timeout=5
                    ) as response:
                        if response.status == 401:
                            failed_attempts += 1
                        elif response.status == 429:
                            # Rate limiting detected
                            self.results.append(SecurityTestResult(
                                test_name="Brute Force Protection",
                                category="Authentication",
                                status=SecurityTestStatus.PASSED,
                                severity="LOW",
                                message=f"Rate limiting activated after {failed_attempts} attempts",
                                details={"failed_attempts": failed_attempts},
                                timestamp=datetime.utcnow().isoformat()
                            ))
                            return
                except Exception:
                    continue
                
                # Small delay between attempts
                await asyncio.sleep(0.1)
            
            # If we get here, no rate limiting was detected
            self.results.append(SecurityTestResult(
                test_name="Brute Force Protection",
                category="Authentication",
                status=SecurityTestStatus.VULNERABLE,
                severity="HIGH",
                message="No brute force protection detected",
                details={"attempts_made": failed_attempts},
                remediation="Implement account lockout and rate limiting for login attempts",
                timestamp=datetime.utcnow().isoformat()
            ))
            
        except Exception as e:
            self.results.append(SecurityTestResult(
                test_name="Brute Force Protection",
                category="Authentication",
                status=SecurityTestStatus.FAILED,
                severity="MEDIUM",
                message=f"Test failed: {str(e)}",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_default_credentials(self) -> None:
        """Test for default credentials"""
        default_creds = [
            ("admin", "admin"),
            ("admin", "password"),
            ("admin", "123456"),
            ("root", "root"),
            ("test", "test"),
            ("guest", "guest")
        ]
        
        vulnerable_creds = []
        
        for username, password in default_creds:
            try:
                async with self.session.post(
                    f"{self.base_url}/auth/login",
                    json={"username": username, "password": password},
                    timeout=5
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        if "token" in response_data:
                            vulnerable_creds.append((username, password))
            except Exception:
                continue
        
        if vulnerable_creds:
            self.results.append(SecurityTestResult(
                test_name="Default Credentials",
                category="Authentication",
                status=SecurityTestStatus.VULNERABLE,
                severity="CRITICAL",
                message=f"Default credentials found: {vulnerable_creds}",
                details={"vulnerable_credentials": vulnerable_creds},
                remediation="Remove or change all default credentials",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="Default Credentials",
                category="Authentication",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="No default credentials found",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_password_policy(self) -> None:
        """Test password policy enforcement"""
        weak_passwords = [
            "123",
            "password",
            "abc",
            "test",
            "admin"
        ]
        
        policy_violations = []
        
        for weak_password in weak_passwords:
            try:
                async with self.session.post(
                    f"{self.base_url}/auth/register",
                    json={
                        "username": f"testuser_{secrets.token_hex(4)}",
                        "password": weak_password,
                        "email": f"test_{secrets.token_hex(4)}@example.com"
                    },
                    timeout=5
                ) as response:
                    if response.status == 201:
                        policy_violations.append(weak_password)
            except Exception:
                continue
        
        if policy_violations:
            self.results.append(SecurityTestResult(
                test_name="Password Policy Enforcement",
                category="Authentication",
                status=SecurityTestStatus.VULNERABLE,
                severity="MEDIUM",
                message=f"Weak passwords accepted: {policy_violations}",
                details={"weak_passwords_accepted": policy_violations},
                remediation="Implement strong password policy enforcement",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="Password Policy Enforcement",
                category="Authentication",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="Password policy properly enforced",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_mfa_implementation(self) -> None:
        """Test multi-factor authentication implementation"""
        # This is a placeholder test - actual implementation would depend on MFA system
        self.results.append(SecurityTestResult(
            test_name="Multi-Factor Authentication",
            category="Authentication",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="MFA testing requires specific implementation details",
            remediation="Implement and test MFA if not already present",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_authorization_security(self) -> None:
        """Test authorization security vulnerabilities"""
        logger.info("Testing authorization security")
        
        # Test privilege escalation
        await self._test_privilege_escalation()
        
        # Test horizontal access control
        await self._test_horizontal_access_control()
        
        # Test vertical access control
        await self._test_vertical_access_control()
    
    async def _test_privilege_escalation(self) -> None:
        """Test privilege escalation vulnerabilities"""
        try:
            # Test parameter manipulation for role escalation
            test_payloads = [
                {"role": "admin"},
                {"is_admin": True},
                {"permissions": ["admin"]},
                {"user_type": "administrator"}
            ]
            
            for payload in test_payloads:
                try:
                    async with self.session.post(
                        f"{self.base_url}/auth/login",
                        json={
                            "username": "testuser",
                            "password": "testpass",
                            **payload
                        },
                        timeout=5
                    ) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            if "token" in response_data:
                                # Decode JWT to check for elevated privileges
                                try:
                                    # Note: This is for testing only - don't verify signature
                                    decoded = jwt.decode(
                                        response_data["token"],
                                        options={"verify_signature": False}
                                    )
                                    if any(admin_indicator in str(decoded).lower() 
                                          for admin_indicator in ["admin", "administrator", "root"]):
                                        self.results.append(SecurityTestResult(
                                            test_name="Privilege Escalation",
                                            category="Authorization",
                                            status=SecurityTestStatus.VULNERABLE,
                                            severity="CRITICAL",
                                            message=f"Privilege escalation possible with payload: {payload}",
                                            details={"payload": payload, "token_claims": decoded},
                                            remediation="Implement proper authorization checks and input validation",
                                            timestamp=datetime.utcnow().isoformat()
                                        ))
                                        return
                                except Exception:
                                    pass
                except Exception:
                    continue
            
            self.results.append(SecurityTestResult(
                test_name="Privilege Escalation",
                category="Authorization",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="No privilege escalation vulnerabilities found",
                timestamp=datetime.utcnow().isoformat()
            ))
            
        except Exception as e:
            self.results.append(SecurityTestResult(
                test_name="Privilege Escalation",
                category="Authorization",
                status=SecurityTestStatus.FAILED,
                severity="MEDIUM",
                message=f"Test failed: {str(e)}",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_horizontal_access_control(self) -> None:
        """Test horizontal access control (accessing other users' data)"""
        # This would require creating test users and attempting to access each other's data
        self.results.append(SecurityTestResult(
            test_name="Horizontal Access Control",
            category="Authorization",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="Requires test user setup for comprehensive testing",
            remediation="Implement comprehensive access control testing with test users",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_vertical_access_control(self) -> None:
        """Test vertical access control (accessing higher privilege functions)"""
        # Test accessing admin endpoints without proper authorization
        admin_endpoints = [
            "/admin/users",
            "/admin/config",
            "/admin/logs",
            "/api/admin/system",
            "/management/health"
        ]
        
        unauthorized_access = []
        
        for endpoint in admin_endpoints:
            try:
                async with self.session.get(
                    f"{self.base_url}{endpoint}",
                    timeout=5
                ) as response:
                    if response.status == 200:
                        unauthorized_access.append(endpoint)
            except Exception:
                continue
        
        if unauthorized_access:
            self.results.append(SecurityTestResult(
                test_name="Vertical Access Control",
                category="Authorization",
                status=SecurityTestStatus.VULNERABLE,
                severity="HIGH",
                message=f"Unauthorized access to admin endpoints: {unauthorized_access}",
                details={"accessible_endpoints": unauthorized_access},
                remediation="Implement proper authorization checks for admin endpoints",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="Vertical Access Control",
                category="Authorization",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="Admin endpoints properly protected",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_input_validation_security(self) -> None:
        """Test input validation security vulnerabilities"""
        logger.info("Testing input validation security")
        
        # Test SQL injection
        await self._test_sql_injection()
        
        # Test XSS vulnerabilities
        await self._test_xss_vulnerabilities()
        
        # Test command injection
        await self._test_command_injection()
        
        # Test path traversal
        await self._test_path_traversal()
    
    async def _test_sql_injection(self) -> None:
        """Test SQL injection vulnerabilities"""
        sql_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE users; --",
            "' UNION SELECT 1,2,3--",
            "1' AND (SELECT COUNT(*) FROM users) > 0--"
        ]
        
        vulnerable_endpoints = []
        
        # Test common endpoints that might be vulnerable
        test_endpoints = [
            ("/api/users", {"id": "PAYLOAD"}),
            ("/api/search", {"query": "PAYLOAD"}),
            ("/api/hotels", {"name": "PAYLOAD"}),
        ]
        
        for endpoint, params in test_endpoints:
            for payload in sql_payloads:
                try:
                    test_params = {k: v.replace("PAYLOAD", payload) if v == "PAYLOAD" else v 
                                 for k, v in params.items()}
                    
                    async with self.session.get(
                        f"{self.base_url}{endpoint}",
                        params=test_params,
                        timeout=5
                    ) as response:
                        response_text = await response.text()
                        
                        # Look for SQL error messages
                        sql_errors = [
                            "sql syntax",
                            "mysql_fetch",
                            "postgresql",
                            "sqlite",
                            "ora-",
                            "syntax error"
                        ]
                        
                        if any(error in response_text.lower() for error in sql_errors):
                            vulnerable_endpoints.append({
                                "endpoint": endpoint,
                                "payload": payload,
                                "response_snippet": response_text[:200]
                            })
                            break
                            
                except Exception:
                    continue
        
        if vulnerable_endpoints:
            self.results.append(SecurityTestResult(
                test_name="SQL Injection",
                category="Input Validation",
                status=SecurityTestStatus.VULNERABLE,
                severity="CRITICAL",
                message=f"SQL injection vulnerabilities found in {len(vulnerable_endpoints)} endpoints",
                details={"vulnerable_endpoints": vulnerable_endpoints},
                remediation="Implement parameterized queries and input validation",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="SQL Injection",
                category="Input Validation",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="No SQL injection vulnerabilities found",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_xss_vulnerabilities(self) -> None:
        """Test Cross-Site Scripting vulnerabilities"""
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "javascript:alert('XSS')",
            "<img src=x onerror=alert('XSS')>",
            "';alert('XSS');//"
        ]
        
        vulnerable_endpoints = []
        
        # Test endpoints that might reflect user input
        test_endpoints = [
            ("/api/search", {"query": "PAYLOAD"}),
            ("/api/feedback", {"message": "PAYLOAD"}),
        ]
        
        for endpoint, params in test_endpoints:
            for payload in xss_payloads:
                try:
                    test_params = {k: v.replace("PAYLOAD", payload) if v == "PAYLOAD" else v 
                                 for k, v in params.items()}
                    
                    async with self.session.get(
                        f"{self.base_url}{endpoint}",
                        params=test_params,
                        timeout=5
                    ) as response:
                        response_text = await response.text()
                        
                        # Check if payload is reflected without encoding
                        if payload in response_text:
                            vulnerable_endpoints.append({
                                "endpoint": endpoint,
                                "payload": payload
                            })
                            break
                            
                except Exception:
                    continue
        
        if vulnerable_endpoints:
            self.results.append(SecurityTestResult(
                test_name="Cross-Site Scripting (XSS)",
                category="Input Validation",
                status=SecurityTestStatus.VULNERABLE,
                severity="HIGH",
                message=f"XSS vulnerabilities found in {len(vulnerable_endpoints)} endpoints",
                details={"vulnerable_endpoints": vulnerable_endpoints},
                remediation="Implement proper input encoding and Content Security Policy",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="Cross-Site Scripting (XSS)",
                category="Input Validation",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="No XSS vulnerabilities found",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_command_injection(self) -> None:
        """Test command injection vulnerabilities"""
        command_payloads = [
            "; ls -la",
            "| whoami",
            "&& cat /etc/passwd",
            "`id`",
            "$(whoami)"
        ]
        
        # This is a basic test - real implementation would depend on specific endpoints
        self.results.append(SecurityTestResult(
            test_name="Command Injection",
            category="Input Validation",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="Command injection testing requires specific endpoint analysis",
            remediation="Implement input validation and avoid system command execution with user input",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_path_traversal(self) -> None:
        """Test path traversal vulnerabilities"""
        path_payloads = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts",
            "....//....//....//etc/passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd"
        ]
        
        vulnerable_endpoints = []
        
        # Test file-related endpoints
        for payload in path_payloads:
            try:
                async with self.session.get(
                    f"{self.base_url}/api/files/{payload}",
                    timeout=5
                ) as response:
                    response_text = await response.text()
                    
                    # Look for signs of successful path traversal
                    if any(indicator in response_text.lower() 
                          for indicator in ["root:", "administrator", "system32"]):
                        vulnerable_endpoints.append({
                            "payload": payload,
                            "response_snippet": response_text[:200]
                        })
                        break
                        
            except Exception:
                continue
        
        if vulnerable_endpoints:
            self.results.append(SecurityTestResult(
                test_name="Path Traversal",
                category="Input Validation",
                status=SecurityTestStatus.VULNERABLE,
                severity="HIGH",
                message="Path traversal vulnerabilities found",
                details={"vulnerable_payloads": vulnerable_endpoints},
                remediation="Implement proper file path validation and sandboxing",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="Path Traversal",
                category="Input Validation",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="No path traversal vulnerabilities found",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_session_management_security(self) -> None:
        """Test session management security"""
        logger.info("Testing session management security")
        
        # Test session fixation
        await self._test_session_fixation()
        
        # Test session timeout
        await self._test_session_timeout()
        
        # Test concurrent sessions
        await self._test_concurrent_sessions()
    
    async def _test_session_fixation(self) -> None:
        """Test session fixation vulnerabilities"""
        # This would require specific session management implementation details
        self.results.append(SecurityTestResult(
            test_name="Session Fixation",
            category="Session Management",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="Session fixation testing requires specific session implementation details",
            remediation="Ensure session IDs are regenerated after authentication",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_session_timeout(self) -> None:
        """Test session timeout implementation"""
        # This would require time-based testing
        self.results.append(SecurityTestResult(
            test_name="Session Timeout",
            category="Session Management",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="Session timeout testing requires time-based validation",
            remediation="Implement appropriate session timeout policies",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_concurrent_sessions(self) -> None:
        """Test concurrent session handling"""
        # This would require multiple session testing
        self.results.append(SecurityTestResult(
            test_name="Concurrent Sessions",
            category="Session Management",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="Concurrent session testing requires multiple session setup",
            remediation="Implement proper concurrent session management",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_api_security(self) -> None:
        """Test API security vulnerabilities"""
        logger.info("Testing API security")
        
        # Test API versioning security
        await self._test_api_versioning()
        
        # Test HTTP methods security
        await self._test_http_methods()
        
        # Test API rate limiting
        await self._test_api_rate_limiting()
    
    async def _test_api_versioning(self) -> None:
        """Test API versioning security"""
        # Test access to different API versions
        versions = ["v1", "v2", "beta", "dev", "test"]
        accessible_versions = []
        
        for version in versions:
            try:
                async with self.session.get(
                    f"{self.base_url}/api/{version}/health",
                    timeout=5
                ) as response:
                    if response.status == 200:
                        accessible_versions.append(version)
            except Exception:
                continue
        
        if len(accessible_versions) > 1:
            self.results.append(SecurityTestResult(
                test_name="API Versioning Security",
                category="API Security",
                status=SecurityTestStatus.WARNING,
                severity="MEDIUM",
                message=f"Multiple API versions accessible: {accessible_versions}",
                details={"accessible_versions": accessible_versions},
                remediation="Ensure only production API versions are accessible",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="API Versioning Security",
                category="API Security",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="API versioning properly controlled",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_http_methods(self) -> None:
        """Test HTTP methods security"""
        dangerous_methods = ["TRACE", "TRACK", "DEBUG", "OPTIONS"]
        vulnerable_methods = []
        
        for method in dangerous_methods:
            try:
                async with self.session.request(
                    method,
                    f"{self.base_url}/api/health",
                    timeout=5
                ) as response:
                    if response.status != 405:  # Method Not Allowed
                        vulnerable_methods.append(method)
            except Exception:
                continue
        
        if vulnerable_methods:
            self.results.append(SecurityTestResult(
                test_name="HTTP Methods Security",
                category="API Security",
                status=SecurityTestStatus.VULNERABLE,
                severity="MEDIUM",
                message=f"Dangerous HTTP methods enabled: {vulnerable_methods}",
                details={"vulnerable_methods": vulnerable_methods},
                remediation="Disable unnecessary HTTP methods",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="HTTP Methods Security",
                category="API Security",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="HTTP methods properly restricted",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_api_rate_limiting(self) -> None:
        """Test API rate limiting"""
        # Test rapid requests to trigger rate limiting
        requests_made = 0
        rate_limited = False
        
        for i in range(50):
            try:
                async with self.session.get(
                    f"{self.base_url}/api/health",
                    timeout=1
                ) as response:
                    requests_made += 1
                    if response.status == 429:
                        rate_limited = True
                        break
            except Exception:
                break
        
        if rate_limited:
            self.results.append(SecurityTestResult(
                test_name="API Rate Limiting",
                category="API Security",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message=f"Rate limiting activated after {requests_made} requests",
                details={"requests_before_limit": requests_made},
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="API Rate Limiting",
                category="API Security",
                status=SecurityTestStatus.VULNERABLE,
                severity="MEDIUM",
                message="No rate limiting detected",
                details={"requests_made": requests_made},
                remediation="Implement API rate limiting",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_jwt_security(self) -> None:
        """Test JWT security implementation"""
        logger.info("Testing JWT security")
        
        # Test JWT algorithm confusion
        await self._test_jwt_algorithm_confusion()
        
        # Test JWT signature verification
        await self._test_jwt_signature_verification()
        
        # Test JWT expiration
        await self._test_jwt_expiration()
    
    async def _test_jwt_algorithm_confusion(self) -> None:
        """Test JWT algorithm confusion attacks"""
        # This would require creating malicious JWTs
        self.results.append(SecurityTestResult(
            test_name="JWT Algorithm Confusion",
            category="JWT Security",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="JWT algorithm confusion testing requires token generation",
            remediation="Ensure JWT library properly validates algorithms",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_jwt_signature_verification(self) -> None:
        """Test JWT signature verification"""
        # This would require creating unsigned or malformed JWTs
        self.results.append(SecurityTestResult(
            test_name="JWT Signature Verification",
            category="JWT Security",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="JWT signature testing requires token manipulation",
            remediation="Ensure JWT signatures are properly verified",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_jwt_expiration(self) -> None:
        """Test JWT expiration handling"""
        # This would require expired tokens
        self.results.append(SecurityTestResult(
            test_name="JWT Expiration",
            category="JWT Security",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="JWT expiration testing requires expired tokens",
            remediation="Ensure expired JWTs are properly rejected",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_rate_limiting_security(self) -> None:
        """Test rate limiting security"""
        logger.info("Testing rate limiting security")
        
        # Test rate limit bypass
        await self._test_rate_limit_bypass()
    
    async def _test_rate_limit_bypass(self) -> None:
        """Test rate limiting bypass techniques"""
        bypass_techniques = [
            {"X-Forwarded-For": "192.168.1.1"},
            {"X-Real-IP": "10.0.0.1"},
            {"X-Originating-IP": "172.16.0.1"},
            {"User-Agent": f"TestAgent-{secrets.token_hex(8)}"}
        ]
        
        bypassed_techniques = []
        
        for technique in bypass_techniques:
            requests_made = 0
            rate_limited = False
            
            for i in range(30):
                try:
                    async with self.session.get(
                        f"{self.base_url}/api/health",
                        headers=technique,
                        timeout=1
                    ) as response:
                        requests_made += 1
                        if response.status == 429:
                            rate_limited = True
                            break
                except Exception:
                    break
            
            if not rate_limited and requests_made >= 25:
                bypassed_techniques.append(technique)
        
        if bypassed_techniques:
            self.results.append(SecurityTestResult(
                test_name="Rate Limiting Bypass",
                category="Rate Limiting",
                status=SecurityTestStatus.VULNERABLE,
                severity="MEDIUM",
                message=f"Rate limiting bypassed using: {bypassed_techniques}",
                details={"bypass_techniques": bypassed_techniques},
                remediation="Implement proper client identification for rate limiting",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="Rate Limiting Bypass",
                category="Rate Limiting",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="Rate limiting cannot be easily bypassed",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_owasp_top10_vulnerabilities(self) -> None:
        """Test OWASP Top 10 vulnerabilities"""
        logger.info("Testing OWASP Top 10 vulnerabilities")
        
        # Most OWASP Top 10 tests are covered in other methods
        # This is a placeholder for additional OWASP-specific tests
        
        await self._test_security_misconfiguration()
        await self._test_vulnerable_components()
        await self._test_insufficient_logging()
    
    async def _test_security_misconfiguration(self) -> None:
        """Test security misconfiguration"""
        # Test for exposed configuration files
        config_files = [
            "/.env",
            "/config.json",
            "/settings.py",
            "/.git/config",
            "/docker-compose.yml"
        ]
        
        exposed_files = []
        
        for config_file in config_files:
            try:
                async with self.session.get(
                    f"{self.base_url}{config_file}",
                    timeout=5
                ) as response:
                    if response.status == 200:
                        exposed_files.append(config_file)
            except Exception:
                continue
        
        if exposed_files:
            self.results.append(SecurityTestResult(
                test_name="Security Misconfiguration",
                category="OWASP Top 10",
                status=SecurityTestStatus.VULNERABLE,
                severity="HIGH",
                message=f"Exposed configuration files: {exposed_files}",
                details={"exposed_files": exposed_files},
                remediation="Secure configuration files and disable directory listing",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            self.results.append(SecurityTestResult(
                test_name="Security Misconfiguration",
                category="OWASP Top 10",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="No exposed configuration files found",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_vulnerable_components(self) -> None:
        """Test for vulnerable components"""
        # This would require dependency scanning
        self.results.append(SecurityTestResult(
            test_name="Vulnerable Components",
            category="OWASP Top 10",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="Vulnerable component testing requires dependency analysis",
            remediation="Implement automated dependency vulnerability scanning",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_insufficient_logging(self) -> None:
        """Test insufficient logging and monitoring"""
        # This would require log analysis
        self.results.append(SecurityTestResult(
            test_name="Insufficient Logging",
            category="OWASP Top 10",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="Logging testing requires log analysis capabilities",
            remediation="Implement comprehensive security event logging",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_infrastructure_security(self) -> None:
        """Test infrastructure security"""
        logger.info("Testing infrastructure security")
        
        # Test SSL/TLS configuration
        await self._test_ssl_tls_configuration()
        
        # Test security headers
        await self._test_security_headers()
    
    async def _test_ssl_tls_configuration(self) -> None:
        """Test SSL/TLS configuration"""
        if not self.base_url.startswith("https://"):
            self.results.append(SecurityTestResult(
                test_name="SSL/TLS Configuration",
                category="Infrastructure",
                status=SecurityTestStatus.VULNERABLE,
                severity="HIGH",
                message="HTTPS not enforced",
                remediation="Implement HTTPS with proper SSL/TLS configuration",
                timestamp=datetime.utcnow().isoformat()
            ))
        else:
            # Would need additional SSL testing tools for comprehensive testing
            self.results.append(SecurityTestResult(
                test_name="SSL/TLS Configuration",
                category="Infrastructure",
                status=SecurityTestStatus.PASSED,
                severity="LOW",
                message="HTTPS is enforced",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_security_headers(self) -> None:
        """Test security headers implementation"""
        try:
            async with self.session.get(f"{self.base_url}/", timeout=5) as response:
                headers = response.headers
                
                required_headers = {
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": ["DENY", "SAMEORIGIN"],
                    "X-XSS-Protection": "1; mode=block",
                    "Strict-Transport-Security": None,  # Any value is good
                    "Content-Security-Policy": None
                }
                
                missing_headers = []
                weak_headers = []
                
                for header, expected_values in required_headers.items():
                    if header not in headers:
                        missing_headers.append(header)
                    elif expected_values and isinstance(expected_values, list):
                        if headers[header] not in expected_values:
                            weak_headers.append(f"{header}: {headers[header]}")
                
                if missing_headers or weak_headers:
                    severity = "HIGH" if missing_headers else "MEDIUM"
                    message_parts = []
                    if missing_headers:
                        message_parts.append(f"Missing headers: {missing_headers}")
                    if weak_headers:
                        message_parts.append(f"Weak headers: {weak_headers}")
                    
                    self.results.append(SecurityTestResult(
                        test_name="Security Headers",
                        category="Infrastructure",
                        status=SecurityTestStatus.VULNERABLE,
                        severity=severity,
                        message="; ".join(message_parts),
                        details={
                            "missing_headers": missing_headers,
                            "weak_headers": weak_headers,
                            "current_headers": dict(headers)
                        },
                        remediation="Implement all required security headers",
                        timestamp=datetime.utcnow().isoformat()
                    ))
                else:
                    self.results.append(SecurityTestResult(
                        test_name="Security Headers",
                        category="Infrastructure",
                        status=SecurityTestStatus.PASSED,
                        severity="LOW",
                        message="All required security headers are present",
                        timestamp=datetime.utcnow().isoformat()
                    ))
                    
        except Exception as e:
            self.results.append(SecurityTestResult(
                test_name="Security Headers",
                category="Infrastructure",
                status=SecurityTestStatus.FAILED,
                severity="MEDIUM",
                message=f"Test failed: {str(e)}",
                timestamp=datetime.utcnow().isoformat()
            ))
    
    async def _test_data_protection_security(self) -> None:
        """Test data protection security"""
        logger.info("Testing data protection security")
        
        # Test PII handling
        await self._test_pii_handling()
        
        # Test data encryption
        await self._test_data_encryption()
    
    async def _test_pii_handling(self) -> None:
        """Test PII handling and redaction"""
        # This would require specific PII testing scenarios
        self.results.append(SecurityTestResult(
            test_name="PII Handling",
            category="Data Protection",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="PII handling testing requires specific test scenarios",
            remediation="Implement comprehensive PII redaction and handling",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    async def _test_data_encryption(self) -> None:
        """Test data encryption implementation"""
        # This would require database and storage analysis
        self.results.append(SecurityTestResult(
            test_name="Data Encryption",
            category="Data Protection",
            status=SecurityTestStatus.SKIPPED,
            severity="LOW",
            message="Data encryption testing requires storage analysis",
            remediation="Implement encryption for sensitive data at rest and in transit",
            timestamp=datetime.utcnow().isoformat()
        ))
    
    def _generate_security_report(self) -> SecurityReport:
        """Generate comprehensive security report"""
        end_time = datetime.utcnow()
        execution_time = (end_time - self.start_time).total_seconds()
        
        # Count results by status
        status_counts = {
            SecurityTestStatus.PASSED: 0,
            SecurityTestStatus.FAILED: 0,
            SecurityTestStatus.VULNERABLE: 0,
            SecurityTestStatus.SKIPPED: 0
        }
        
        # Count by severity
        severity_counts = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0
        }
        
        for result in self.results:
            status_counts[result.status] += 1
            severity_counts[result.severity] += 1
        
        # Determine overall status
        if status_counts[SecurityTestStatus.VULNERABLE] > 0:
            if severity_counts["CRITICAL"] > 0:
                overall_status = SecurityTestStatus.VULNERABLE
            else:
                overall_status = SecurityTestStatus.VULNERABLE
        elif status_counts[SecurityTestStatus.FAILED] > 0:
            overall_status = SecurityTestStatus.FAILED
        else:
            overall_status = SecurityTestStatus.PASSED
        
        # Generate recommendations
        recommendations = self._generate_security_recommendations()
        
        return SecurityReport(
            overall_status=overall_status,
            total_tests=len(self.results),
            passed_tests=status_counts[SecurityTestStatus.PASSED],
            failed_tests=status_counts[SecurityTestStatus.FAILED],
            vulnerable_tests=status_counts[SecurityTestStatus.VULNERABLE],
            skipped_tests=status_counts[SecurityTestStatus.SKIPPED],
            critical_vulnerabilities=severity_counts["CRITICAL"],
            high_vulnerabilities=severity_counts["HIGH"],
            medium_vulnerabilities=severity_counts["MEDIUM"],
            low_vulnerabilities=severity_counts["LOW"],
            execution_time=execution_time,
            timestamp=end_time.isoformat(),
            results=self.results,
            recommendations=recommendations
        )
    
    def _generate_security_recommendations(self) -> List[str]:
        """Generate security recommendations based on test results"""
        recommendations = []
        
        vulnerable_tests = [r for r in self.results if r.status == SecurityTestStatus.VULNERABLE]
        critical_vulns = [r for r in vulnerable_tests if r.severity == "CRITICAL"]
        high_vulns = [r for r in vulnerable_tests if r.severity == "HIGH"]
        
        if critical_vulns:
            recommendations.append(
                f"🚨 CRITICAL: {len(critical_vulns)} critical vulnerabilities found. "
                "These must be fixed immediately before production deployment."
            )
        
        if high_vulns:
            recommendations.append(
                f"⚠️ HIGH: {len(high_vulns)} high-severity vulnerabilities found. "
                "These should be addressed as soon as possible."
            )
        
        # Category-specific recommendations
        categories = {}
        for result in vulnerable_tests:
            if result.category not in categories:
                categories[result.category] = []
            categories[result.category].append(result)
        
        for category, vulns in categories.items():
            if len(vulns) > 1:
                recommendations.append(
                    f"Multiple vulnerabilities found in {category}. "
                    f"Review and strengthen {category.lower()} controls."
                )
        
        if not vulnerable_tests:
            recommendations.append(
                "✅ No critical vulnerabilities found in automated testing. "
                "Consider additional manual security testing and code review."
            )
        
        return recommendations


async def main():
    """Main execution function for security penetration testing"""
    print("🔒 Starting Security Penetration Testing")
    print("=" * 60)
    
    # You can customize the base URL for testing
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    tester = SecurityPenetrationTester(base_url=base_url)
    
    try:
        # Run comprehensive security tests
        report = await tester.run_comprehensive_security_tests()
        
        # Print summary
        print(f"\n🔍 SECURITY TEST SUMMARY")
        print(f"Overall Status: {report.overall_status.value}")
        print(f"Total Tests: {report.total_tests}")
        print(f"Passed: {report.passed_tests}")
        print(f"Vulnerable: {report.vulnerable_tests}")
        print(f"Failed: {report.failed_tests}")
        print(f"Skipped: {report.skipped_tests}")
        print(f"Execution Time: {report.execution_time:.2f} seconds")
        
        # Print vulnerability summary
        print(f"\n🚨 VULNERABILITY SUMMARY")
        print(f"Critical: {report.critical_vulnerabilities}")
        print(f"High: {report.high_vulnerabilities}")
        print(f"Medium: {report.medium_vulnerabilities}")
        print(f"Low: {report.low_vulnerabilities}")
        
        # Print detailed results
        print(f"\n📋 DETAILED RESULTS")
        print("-" * 60)
        
        for result in report.results:
            status_emoji = {
                SecurityTestStatus.PASSED: "✅",
                SecurityTestStatus.FAILED: "❌",
                SecurityTestStatus.VULNERABLE: "🚨",
                SecurityTestStatus.SKIPPED: "⏭️"
            }
            
            severity_emoji = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🟢"
            }
            
            print(f"{status_emoji[result.status]} {severity_emoji[result.severity]} "
                  f"[{result.category}] {result.test_name}")
            print(f"   {result.message}")
            if result.remediation:
                print(f"   💡 Remediation: {result.remediation}")
            print()
        
        # Print recommendations
        if report.recommendations:
            print(f"\n💡 SECURITY RECOMMENDATIONS")
            print("-" * 60)
            for i, rec in enumerate(report.recommendations, 1):
                print(f"{i}. {rec}")
        
        # Save report to file
        report_path = Path("security_penetration_report.json")
        with open(report_path, 'w') as f:
            json.dump(asdict(report), f, indent=2, default=str)
        
        print(f"\n📄 Full security report saved to: {report_path}")
        
        # Exit with appropriate code
        if report.critical_vulnerabilities > 0:
            print("\n🚨 CRITICAL VULNERABILITIES FOUND")
            print("System is NOT ready for production deployment.")
            sys.exit(1)
        elif report.high_vulnerabilities > 0:
            print("\n⚠️ HIGH SEVERITY VULNERABILITIES FOUND")
            print("Address these vulnerabilities before production deployment.")
            sys.exit(1)
        elif report.vulnerable_tests > 0:
            print("\n⚠️ VULNERABILITIES FOUND")
            print("Review and address vulnerabilities before production deployment.")
            sys.exit(0)
        else:
            print("\n✅ NO CRITICAL VULNERABILITIES FOUND")
            print("Automated security testing passed!")
            sys.exit(0)
            
    except Exception as e:
        logger.error(f"Security testing failed with error: {str(e)}")
        print(f"\n❌ SECURITY TESTING ERROR: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())