"""
Security Tester - Comprehensive security penetration testing automation

This module implements automated security testing including vulnerability scanning,
penetration testing, and security compliance validation.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import random
import re
import string
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlencode, quote

import aiohttp
import jwt as pyjwt

logger = logging.getLogger(__name__)


class VulnerabilityType(Enum):
    """Types of security vulnerabilities to test"""
    SQL_INJECTION = "sql_injection"
    XSS = "cross_site_scripting"
    CSRF = "cross_site_request_forgery"
    AUTHENTICATION_BYPASS = "authentication_bypass"
    AUTHORIZATION_BYPASS = "authorization_bypass"
    JWT_VULNERABILITIES = "jwt_vulnerabilities"
    INPUT_VALIDATION = "input_validation"
    INFORMATION_DISCLOSURE = "information_disclosure"
    INSECURE_HEADERS = "insecure_headers"
    RATE_LIMITING_BYPASS = "rate_limiting_bypass"


class Severity(Enum):
    """Vulnerability severity levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class SecurityTest:
    """Defines a security test case"""
    name: str
    description: str
    vulnerability_type: VulnerabilityType
    severity: Severity
    endpoint: str
    method: str = "GET"
    payload: Optional[Dict] = None
    headers: Optional[Dict] = None
    expected_status_codes: List[int] = field(default_factory=lambda: [400, 401, 403])
    test_function: Optional[str] = None


@dataclass
class SecurityVulnerability:
    """Represents a discovered security vulnerability"""
    test_name: str
    vulnerability_type: VulnerabilityType
    severity: Severity
    endpoint: str
    description: str
    evidence: str
    recommendation: str
    cve_references: List[str] = field(default_factory=list)


@dataclass
class SecurityTestResult:
    """Results from security testing"""
    test_name: str
    vulnerability_type: VulnerabilityType
    passed: bool
    vulnerabilities_found: List[SecurityVulnerability]
    response_status: int
    response_headers: Dict[str, str]
    response_body: str
    execution_time_ms: float


class SecurityTester:
    """
    Comprehensive security testing framework with automated penetration testing
    """
    
    def __init__(self, config):
        self.config = config
        self.base_url = "http://localhost:8000"
        self.session = None
        self.security_tests = self._define_security_tests()
        
        # Common payloads for testing
        self.sql_injection_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE users; --",
            "' UNION SELECT * FROM users --",
            "admin'--",
            "' OR 1=1#",
            "1' AND (SELECT COUNT(*) FROM users) > 0 --"
        ]
        
        self.xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "javascript:alert('XSS')",
            "<svg onload=alert('XSS')>",
            "';alert('XSS');//",
            "<iframe src=javascript:alert('XSS')></iframe>"
        ]
        
        self.command_injection_payloads = [
            "; ls -la",
            "| whoami",
            "&& cat /etc/passwd",
            "`id`",
            "$(whoami)",
            "; ping -c 1 127.0.0.1"
        ]
    
    def _define_security_tests(self) -> List[SecurityTest]:
        """Define comprehensive security test cases"""
        
        return [
            # SQL Injection Tests
            SecurityTest(
                name="sql_injection_login",
                description="Test for SQL injection in login endpoint",
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=Severity.CRITICAL,
                endpoint="/auth/login",
                method="POST",
                test_function="test_sql_injection"
            ),
            
            SecurityTest(
                name="sql_injection_search",
                description="Test for SQL injection in search parameters",
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=Severity.HIGH,
                endpoint="/pms/reservations/search",
                method="GET",
                test_function="test_sql_injection_params"
            ),
            
            # XSS Tests
            SecurityTest(
                name="reflected_xss_search",
                description="Test for reflected XSS in search functionality",
                vulnerability_type=VulnerabilityType.XSS,
                severity=Severity.HIGH,
                endpoint="/search",
                method="GET",
                test_function="test_reflected_xss"
            ),
            
            SecurityTest(
                name="stored_xss_profile",
                description="Test for stored XSS in user profile",
                vulnerability_type=VulnerabilityType.XSS,
                severity=Severity.HIGH,
                endpoint="/profile",
                method="POST",
                test_function="test_stored_xss"
            ),
            
            # Authentication Tests
            SecurityTest(
                name="jwt_token_manipulation",
                description="Test JWT token manipulation vulnerabilities",
                vulnerability_type=VulnerabilityType.JWT_VULNERABILITIES,
                severity=Severity.CRITICAL,
                endpoint="/auth/validate",
                method="GET",
                test_function="test_jwt_vulnerabilities"
            ),
            
            SecurityTest(
                name="authentication_bypass",
                description="Test for authentication bypass vulnerabilities",
                vulnerability_type=VulnerabilityType.AUTHENTICATION_BYPASS,
                severity=Severity.CRITICAL,
                endpoint="/admin",
                method="GET",
                test_function="test_authentication_bypass"
            ),
            
            # Authorization Tests
            SecurityTest(
                name="privilege_escalation",
                description="Test for privilege escalation vulnerabilities",
                vulnerability_type=VulnerabilityType.AUTHORIZATION_BYPASS,
                severity=Severity.HIGH,
                endpoint="/admin/users",
                method="GET",
                test_function="test_privilege_escalation"
            ),
            
            SecurityTest(
                name="idor_vulnerability",
                description="Test for Insecure Direct Object Reference",
                vulnerability_type=VulnerabilityType.AUTHORIZATION_BYPASS,
                severity=Severity.HIGH,
                endpoint="/users/{user_id}",
                method="GET",
                test_function="test_idor_vulnerability"
            ),
            
            # Input Validation Tests
            SecurityTest(
                name="input_validation_bypass",
                description="Test input validation bypass techniques",
                vulnerability_type=VulnerabilityType.INPUT_VALIDATION,
                severity=Severity.MEDIUM,
                endpoint="/api/data",
                method="POST",
                test_function="test_input_validation"
            ),
            
            # Information Disclosure Tests
            SecurityTest(
                name="error_information_disclosure",
                description="Test for information disclosure in error messages",
                vulnerability_type=VulnerabilityType.INFORMATION_DISCLOSURE,
                severity=Severity.MEDIUM,
                endpoint="/api/debug",
                method="GET",
                test_function="test_information_disclosure"
            ),
            
            # Security Headers Tests
            SecurityTest(
                name="security_headers_validation",
                description="Validate security headers implementation",
                vulnerability_type=VulnerabilityType.INSECURE_HEADERS,
                severity=Severity.MEDIUM,
                endpoint="/",
                method="GET",
                test_function="test_security_headers"
            ),
            
            # Rate Limiting Tests
            SecurityTest(
                name="rate_limiting_bypass",
                description="Test rate limiting bypass techniques",
                vulnerability_type=VulnerabilityType.RATE_LIMITING_BYPASS,
                severity=Severity.MEDIUM,
                endpoint="/auth/login",
                method="POST",
                test_function="test_rate_limiting_bypass"
            ),
            
            # CSRF Tests
            SecurityTest(
                name="csrf_protection",
                description="Test CSRF protection mechanisms",
                vulnerability_type=VulnerabilityType.CSRF,
                severity=Severity.HIGH,
                endpoint="/api/sensitive-action",
                method="POST",
                test_function="test_csrf_protection"
            )
        ]
    
    async def run_penetration_tests(self) -> Dict[str, Any]:
        """
        Run comprehensive security penetration tests
        
        Returns:
            Dict containing security test results and vulnerability report
        """
        logger.info("Starting security penetration testing")
        
        try:
            # Initialize HTTP session
            await self._initialize_session()
            
            # Run all security tests
            results = []
            vulnerabilities = []
            
            for test in self.security_tests:
                logger.info(f"Running security test: {test.name}")
                result = await self._run_security_test(test)
                results.append(result)
                vulnerabilities.extend(result.vulnerabilities_found)
                
                # Brief pause between tests
                await asyncio.sleep(0.5)
            
            # Generate comprehensive security report
            report = self._generate_security_report(results, vulnerabilities)
            
            logger.info("Security penetration testing completed")
            return report
            
        except Exception as e:
            logger.error(f"Error during security testing: {e}")
            raise
        finally:
            await self._cleanup_session()
    
    async def _initialize_session(self):
        """Initialize HTTP session for security testing"""
        connector = aiohttp.TCPConnector(
            limit=50,
            limit_per_host=20,
            keepalive_timeout=30
        )
        
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "VoiceHive-SecurityTester/1.0"}
        )
    
    async def _cleanup_session(self):
        """Cleanup HTTP session"""
        if self.session:
            await self.session.close()
    
    async def _run_security_test(self, test: SecurityTest) -> SecurityTestResult:
        """Run a single security test"""
        
        start_time = time.time()
        vulnerabilities = []
        
        try:
            # Get the test function
            test_function = getattr(self, test.test_function, None)
            if not test_function:
                logger.warning(f"Test function {test.test_function} not found")
                return SecurityTestResult(
                    test_name=test.name,
                    vulnerability_type=test.vulnerability_type,
                    passed=False,
                    vulnerabilities_found=[],
                    response_status=0,
                    response_headers={},
                    response_body="Test function not found",
                    execution_time_ms=0
                )
            
            # Execute the test function
            test_result = await test_function(test)
            
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000
            
            return SecurityTestResult(
                test_name=test.name,
                vulnerability_type=test.vulnerability_type,
                passed=test_result['passed'],
                vulnerabilities_found=test_result['vulnerabilities'],
                response_status=test_result.get('status_code', 0),
                response_headers=test_result.get('headers', {}),
                response_body=test_result.get('body', ''),
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000
            
            logger.error(f"Error running security test {test.name}: {e}")
            return SecurityTestResult(
                test_name=test.name,
                vulnerability_type=test.vulnerability_type,
                passed=False,
                vulnerabilities_found=[],
                response_status=0,
                response_headers={},
                response_body=str(e),
                execution_time_ms=execution_time
            )
    
    async def test_sql_injection(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for SQL injection vulnerabilities"""
        
        vulnerabilities = []
        
        for payload in self.sql_injection_payloads:
            try:
                # Test in login credentials
                test_payload = {
                    "email": f"admin{payload}",
                    "password": f"password{payload}"
                }
                
                async with self.session.post(
                    f"{self.base_url}{test.endpoint}",
                    json=test_payload
                ) as response:
                    
                    response_text = await response.text()
                    
                    # Check for SQL injection indicators
                    sql_indicators = [
                        "sql syntax",
                        "mysql_fetch",
                        "ora-",
                        "postgresql",
                        "sqlite",
                        "syntax error",
                        "database error"
                    ]
                    
                    if any(indicator in response_text.lower() for indicator in sql_indicators):
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=test.vulnerability_type,
                            severity=test.severity,
                            endpoint=test.endpoint,
                            description=f"SQL injection vulnerability detected with payload: {payload}",
                            evidence=f"Response contains SQL error indicators: {response_text[:200]}",
                            recommendation="Implement parameterized queries and input validation"
                        )
                        vulnerabilities.append(vulnerability)
                    
                    # Check for successful bypass (status 200 when it should be 401/403)
                    if response.status == 200 and "admin" in payload:
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=VulnerabilityType.AUTHENTICATION_BYPASS,
                            severity=Severity.CRITICAL,
                            endpoint=test.endpoint,
                            description=f"Authentication bypass via SQL injection: {payload}",
                            evidence=f"Received status 200 with malicious payload",
                            recommendation="Implement proper authentication and parameterized queries"
                        )
                        vulnerabilities.append(vulnerability)
            
            except Exception as e:
                logger.warning(f"Error testing SQL injection payload {payload}: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 200,  # Mock response
            'headers': {},
            'body': 'SQL injection test completed'
        }
    
    async def test_sql_injection_params(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for SQL injection in URL parameters"""
        
        vulnerabilities = []
        
        for payload in self.sql_injection_payloads:
            try:
                # Test in query parameters
                params = {
                    'search': payload,
                    'filter': f"name={payload}",
                    'id': payload
                }
                
                url = f"{self.base_url}{test.endpoint}?" + urlencode(params)
                
                async with self.session.get(url) as response:
                    response_text = await response.text()
                    
                    # Check for SQL injection indicators
                    if any(indicator in response_text.lower() for indicator in [
                        "sql syntax", "mysql_fetch", "ora-", "postgresql", "sqlite"
                    ]):
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=test.vulnerability_type,
                            severity=test.severity,
                            endpoint=test.endpoint,
                            description=f"SQL injection in URL parameters: {payload}",
                            evidence=f"SQL error in response: {response_text[:200]}",
                            recommendation="Sanitize and validate all URL parameters"
                        )
                        vulnerabilities.append(vulnerability)
            
            except Exception as e:
                logger.warning(f"Error testing SQL injection in params {payload}: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 200,
            'headers': {},
            'body': 'SQL injection parameter test completed'
        }
    
    async def test_reflected_xss(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for reflected XSS vulnerabilities"""
        
        vulnerabilities = []
        
        for payload in self.xss_payloads:
            try:
                # Test in query parameters
                params = {'q': payload, 'search': payload}
                url = f"{self.base_url}{test.endpoint}?" + urlencode(params)
                
                async with self.session.get(url) as response:
                    response_text = await response.text()
                    
                    # Check if payload is reflected without encoding
                    if payload in response_text and not self._is_properly_encoded(payload, response_text):
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=test.vulnerability_type,
                            severity=test.severity,
                            endpoint=test.endpoint,
                            description=f"Reflected XSS vulnerability: {payload}",
                            evidence=f"Payload reflected unencoded in response",
                            recommendation="Implement proper output encoding and CSP headers"
                        )
                        vulnerabilities.append(vulnerability)
            
            except Exception as e:
                logger.warning(f"Error testing XSS payload {payload}: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 200,
            'headers': {},
            'body': 'Reflected XSS test completed'
        }
    
    async def test_stored_xss(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for stored XSS vulnerabilities"""
        
        vulnerabilities = []
        
        for payload in self.xss_payloads:
            try:
                # Test storing XSS payload
                profile_data = {
                    'name': payload,
                    'bio': f"User bio with {payload}",
                    'website': payload
                }
                
                # Store the payload
                async with self.session.post(
                    f"{self.base_url}{test.endpoint}",
                    json=profile_data
                ) as response:
                    
                    if response.status in [200, 201]:
                        # Retrieve the stored data
                        async with self.session.get(f"{self.base_url}/profile") as get_response:
                            response_text = await get_response.text()
                            
                            # Check if stored payload is rendered without encoding
                            if payload in response_text and not self._is_properly_encoded(payload, response_text):
                                vulnerability = SecurityVulnerability(
                                    test_name=test.name,
                                    vulnerability_type=test.vulnerability_type,
                                    severity=Severity.CRITICAL,  # Stored XSS is more severe
                                    endpoint=test.endpoint,
                                    description=f"Stored XSS vulnerability: {payload}",
                                    evidence=f"Stored payload rendered unencoded",
                                    recommendation="Implement input validation and output encoding"
                                )
                                vulnerabilities.append(vulnerability)
            
            except Exception as e:
                logger.warning(f"Error testing stored XSS payload {payload}: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 200,
            'headers': {},
            'body': 'Stored XSS test completed'
        }
    
    async def test_jwt_vulnerabilities(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for JWT token vulnerabilities"""
        
        vulnerabilities = []
        
        try:
            # Test various JWT vulnerabilities
            
            # 1. Test with no signature (alg: none)
            none_token = self._create_jwt_with_none_algorithm()
            await self._test_jwt_token(test, none_token, "None algorithm bypass", vulnerabilities)
            
            # 2. Test with weak secret
            weak_token = self._create_jwt_with_weak_secret()
            await self._test_jwt_token(test, weak_token, "Weak secret vulnerability", vulnerabilities)
            
            # 3. Test with modified payload
            modified_token = self._create_modified_jwt()
            await self._test_jwt_token(test, modified_token, "Modified payload acceptance", vulnerabilities)
            
            # 4. Test with expired token
            expired_token = self._create_expired_jwt()
            await self._test_jwt_token(test, expired_token, "Expired token acceptance", vulnerabilities)
            
            # 5. Test algorithm confusion (RS256 vs HS256)
            confused_token = self._create_algorithm_confused_jwt()
            await self._test_jwt_token(test, confused_token, "Algorithm confusion", vulnerabilities)
        
        except Exception as e:
            logger.warning(f"Error testing JWT vulnerabilities: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 200,
            'headers': {},
            'body': 'JWT vulnerability test completed'
        }
    
    async def test_authentication_bypass(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for authentication bypass vulnerabilities"""
        
        vulnerabilities = []
        
        bypass_techniques = [
            # Header manipulation
            {"X-Forwarded-For": "127.0.0.1"},
            {"X-Real-IP": "localhost"},
            {"X-Originating-IP": "127.0.0.1"},
            {"X-Remote-IP": "127.0.0.1"},
            {"X-Client-IP": "127.0.0.1"},
            
            # User agent manipulation
            {"User-Agent": "GoogleBot/2.1"},
            {"User-Agent": "internal-service"},
            
            # Custom headers
            {"X-Admin": "true"},
            {"X-Internal": "1"},
            {"X-Bypass": "auth"},
        ]
        
        for headers in bypass_techniques:
            try:
                async with self.session.get(
                    f"{self.base_url}{test.endpoint}",
                    headers=headers
                ) as response:
                    
                    # If we get 200 instead of 401/403, it might be a bypass
                    if response.status == 200:
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=test.vulnerability_type,
                            severity=test.severity,
                            endpoint=test.endpoint,
                            description=f"Authentication bypass via headers: {headers}",
                            evidence=f"Received status 200 with bypass headers",
                            recommendation="Implement proper authentication checks for all requests"
                        )
                        vulnerabilities.append(vulnerability)
            
            except Exception as e:
                logger.warning(f"Error testing auth bypass with headers {headers}: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 401,  # Expected status
            'headers': {},
            'body': 'Authentication bypass test completed'
        }
    
    async def test_privilege_escalation(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for privilege escalation vulnerabilities"""
        
        vulnerabilities = []
        
        # Test with different user roles
        test_tokens = [
            self._create_jwt_with_role("user"),
            self._create_jwt_with_role("guest"),
            self._create_jwt_with_role("admin"),  # This should work
            self._create_jwt_with_role("super_admin"),  # Privilege escalation attempt
        ]
        
        for token in test_tokens:
            try:
                headers = {"Authorization": f"Bearer {token}"}
                
                async with self.session.get(
                    f"{self.base_url}{test.endpoint}",
                    headers=headers
                ) as response:
                    
                    # Decode token to check role
                    try:
                        payload = pyjwt.decode(token, options={"verify_signature": False})
                        role = payload.get('role', 'unknown')
                        
                        # If non-admin role gets access, it's privilege escalation
                        if response.status == 200 and role not in ['admin', 'super_admin']:
                            vulnerability = SecurityVulnerability(
                                test_name=test.name,
                                vulnerability_type=test.vulnerability_type,
                                severity=test.severity,
                                endpoint=test.endpoint,
                                description=f"Privilege escalation: {role} role accessing admin endpoint",
                                evidence=f"Role '{role}' received status 200 for admin endpoint",
                                recommendation="Implement proper role-based access control"
                            )
                            vulnerabilities.append(vulnerability)
                    
                    except Exception as decode_error:
                        logger.warning(f"Could not decode test token: {decode_error}")
            
            except Exception as e:
                logger.warning(f"Error testing privilege escalation: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 403,  # Expected for non-admin
            'headers': {},
            'body': 'Privilege escalation test completed'
        }
    
    async def test_idor_vulnerability(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for Insecure Direct Object Reference vulnerabilities"""
        
        vulnerabilities = []
        
        # Test accessing other users' data
        user_ids = ["1", "2", "admin", "../admin", "../../etc/passwd", "null", "0", "-1"]
        
        for user_id in user_ids:
            try:
                endpoint = test.endpoint.replace("{user_id}", user_id)
                
                # Use a regular user token
                headers = {"Authorization": f"Bearer {self._create_jwt_with_role('user')}"}
                
                async with self.session.get(
                    f"{self.base_url}{endpoint}",
                    headers=headers
                ) as response:
                    
                    response_text = await response.text()
                    
                    # Check if we can access other users' data
                    if response.status == 200 and user_id != "1":  # Assuming user 1 is the authenticated user
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=test.vulnerability_type,
                            severity=test.severity,
                            endpoint=endpoint,
                            description=f"IDOR vulnerability: accessing user {user_id} data",
                            evidence=f"User 1 can access user {user_id} data",
                            recommendation="Implement proper authorization checks for object access"
                        )
                        vulnerabilities.append(vulnerability)
                    
                    # Check for path traversal indicators
                    if "root:" in response_text or "/etc/passwd" in response_text:
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=VulnerabilityType.INFORMATION_DISCLOSURE,
                            severity=Severity.CRITICAL,
                            endpoint=endpoint,
                            description=f"Path traversal via IDOR: {user_id}",
                            evidence=f"System file content in response",
                            recommendation="Implement input validation and access controls"
                        )
                        vulnerabilities.append(vulnerability)
            
            except Exception as e:
                logger.warning(f"Error testing IDOR with user_id {user_id}: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 200,
            'headers': {},
            'body': 'IDOR vulnerability test completed'
        }
    
    async def test_input_validation(self, test: SecurityTest) -> Dict[str, Any]:
        """Test input validation bypass techniques"""
        
        vulnerabilities = []
        
        # Various input validation bypass payloads
        bypass_payloads = [
            # Null byte injection
            "test\x00.txt",
            "admin\x00",
            
            # Unicode bypass
            "admin\u0000",
            "test\u202e",
            
            # Double encoding
            "%2527",  # Double encoded single quote
            "%253cscript%253e",  # Double encoded <script>
            
            # Case variation
            "ADMIN",
            "Admin",
            "aDmIn",
            
            # Length bypass
            "a" * 1000,
            "a" * 10000,
            
            # Special characters
            "test\r\n",
            "test\t",
            "test\b",
        ]
        
        for payload in bypass_payloads:
            try:
                test_data = {
                    'username': payload,
                    'data': payload,
                    'filename': payload
                }
                
                async with self.session.post(
                    f"{self.base_url}{test.endpoint}",
                    json=test_data
                ) as response:
                    
                    response_text = await response.text()
                    
                    # Check if validation was bypassed
                    if response.status == 200 and ("error" not in response_text.lower()):
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=test.vulnerability_type,
                            severity=test.severity,
                            endpoint=test.endpoint,
                            description=f"Input validation bypass: {repr(payload)}",
                            evidence=f"Malicious input accepted without validation",
                            recommendation="Implement comprehensive input validation and sanitization"
                        )
                        vulnerabilities.append(vulnerability)
            
            except Exception as e:
                logger.warning(f"Error testing input validation bypass {repr(payload)}: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 400,  # Expected for invalid input
            'headers': {},
            'body': 'Input validation test completed'
        }
    
    async def test_information_disclosure(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for information disclosure vulnerabilities"""
        
        vulnerabilities = []
        
        try:
            # Test various endpoints for information disclosure
            disclosure_endpoints = [
                "/debug",
                "/info",
                "/status",
                "/config",
                "/env",
                "/.env",
                "/phpinfo.php",
                "/server-info",
                "/admin/config",
                "/api/debug"
            ]
            
            for endpoint in disclosure_endpoints:
                try:
                    async with self.session.get(f"{self.base_url}{endpoint}") as response:
                        response_text = await response.text()
                        
                        # Check for sensitive information
                        sensitive_patterns = [
                            r"password\s*[:=]\s*['\"]?[\w\-@#$%^&*()]+",
                            r"api[_\-]?key\s*[:=]\s*['\"]?[\w\-]+",
                            r"secret\s*[:=]\s*['\"]?[\w\-]+",
                            r"token\s*[:=]\s*['\"]?[\w\-\.]+",
                            r"database\s*[:=]\s*['\"]?[\w\-\.]+",
                            r"connection\s*string",
                            r"stack\s*trace",
                            r"exception\s*details"
                        ]
                        
                        for pattern in sensitive_patterns:
                            if re.search(pattern, response_text, re.IGNORECASE):
                                vulnerability = SecurityVulnerability(
                                    test_name=test.name,
                                    vulnerability_type=test.vulnerability_type,
                                    severity=test.severity,
                                    endpoint=endpoint,
                                    description=f"Information disclosure: {pattern}",
                                    evidence=f"Sensitive information pattern found in response",
                                    recommendation="Remove debug endpoints and sanitize error messages"
                                )
                                vulnerabilities.append(vulnerability)
                                break
                
                except Exception as e:
                    logger.warning(f"Error testing information disclosure on {endpoint}: {e}")
        
        except Exception as e:
            logger.warning(f"Error in information disclosure test: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 404,  # Expected for most debug endpoints
            'headers': {},
            'body': 'Information disclosure test completed'
        }
    
    async def test_security_headers(self, test: SecurityTest) -> Dict[str, Any]:
        """Test for proper security headers implementation"""
        
        vulnerabilities = []
        
        try:
            async with self.session.get(f"{self.base_url}{test.endpoint}") as response:
                headers = dict(response.headers)
                
                # Required security headers
                required_headers = {
                    'X-Content-Type-Options': 'nosniff',
                    'X-Frame-Options': ['DENY', 'SAMEORIGIN'],
                    'X-XSS-Protection': '1; mode=block',
                    'Strict-Transport-Security': 'max-age=',
                    'Content-Security-Policy': 'default-src',
                    'Referrer-Policy': ['strict-origin-when-cross-origin', 'no-referrer']
                }
                
                for header_name, expected_values in required_headers.items():
                    header_value = headers.get(header_name, '')
                    
                    if not header_value:
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=test.vulnerability_type,
                            severity=Severity.MEDIUM,
                            endpoint=test.endpoint,
                            description=f"Missing security header: {header_name}",
                            evidence=f"Header {header_name} not present in response",
                            recommendation=f"Add {header_name} header with appropriate value"
                        )
                        vulnerabilities.append(vulnerability)
                    
                    elif isinstance(expected_values, list):
                        if not any(expected in header_value for expected in expected_values):
                            vulnerability = SecurityVulnerability(
                                test_name=test.name,
                                vulnerability_type=test.vulnerability_type,
                                severity=Severity.LOW,
                                endpoint=test.endpoint,
                                description=f"Weak security header: {header_name}",
                                evidence=f"Header {header_name} has value: {header_value}",
                                recommendation=f"Strengthen {header_name} header configuration"
                            )
                            vulnerabilities.append(vulnerability)
                    
                    elif isinstance(expected_values, str) and expected_values not in header_value:
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=test.vulnerability_type,
                            severity=Severity.LOW,
                            endpoint=test.endpoint,
                            description=f"Weak security header: {header_name}",
                            evidence=f"Header {header_name} has value: {header_value}",
                            recommendation=f"Configure {header_name} header properly"
                        )
                        vulnerabilities.append(vulnerability)
                
                # Check for information disclosure in headers
                disclosure_headers = ['Server', 'X-Powered-By', 'X-AspNet-Version']
                for header_name in disclosure_headers:
                    if header_name in headers:
                        vulnerability = SecurityVulnerability(
                            test_name=test.name,
                            vulnerability_type=VulnerabilityType.INFORMATION_DISCLOSURE,
                            severity=Severity.LOW,
                            endpoint=test.endpoint,
                            description=f"Information disclosure header: {header_name}",
                            evidence=f"Header {header_name}: {headers[header_name]}",
                            recommendation=f"Remove or obfuscate {header_name} header"
                        )
                        vulnerabilities.append(vulnerability)
        
        except Exception as e:
            logger.warning(f"Error testing security headers: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 200,
            'headers': {},
            'body': 'Security headers test completed'
        }
    
    async def test_rate_limiting_bypass(self, test: SecurityTest) -> Dict[str, Any]:
        """Test rate limiting bypass techniques"""
        
        vulnerabilities = []
        
        bypass_techniques = [
            # Header manipulation
            {"X-Forwarded-For": f"192.168.1.{random.randint(1, 254)}"},
            {"X-Real-IP": f"10.0.0.{random.randint(1, 254)}"},
            {"X-Client-IP": f"172.16.0.{random.randint(1, 254)}"},
            
            # User agent rotation
            {"User-Agent": f"Mozilla/5.0 (Test {random.randint(1, 1000)})"},
            
            # Session rotation
            {"Cookie": f"session=test_{random.randint(1, 1000)}"},
        ]
        
        # Test rapid requests with bypass techniques
        for headers in bypass_techniques:
            success_count = 0
            
            for i in range(20):  # Try 20 rapid requests
                try:
                    test_payload = {
                        "email": f"test{i}@example.com",
                        "password": "testpass"
                    }
                    
                    async with self.session.post(
                        f"{self.base_url}{test.endpoint}",
                        json=test_payload,
                        headers=headers
                    ) as response:
                        
                        if response.status != 429:  # Not rate limited
                            success_count += 1
                
                except Exception as e:
                    logger.warning(f"Error in rate limiting test request {i}: {e}")
            
            # If more than 10 requests succeeded, rate limiting might be bypassed
            if success_count > 10:
                vulnerability = SecurityVulnerability(
                    test_name=test.name,
                    vulnerability_type=test.vulnerability_type,
                    severity=test.severity,
                    endpoint=test.endpoint,
                    description=f"Rate limiting bypass via headers: {headers}",
                    evidence=f"{success_count}/20 requests succeeded with bypass headers",
                    recommendation="Implement rate limiting based on multiple factors, not just IP"
                )
                vulnerabilities.append(vulnerability)
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 429,  # Expected after rate limit
            'headers': {},
            'body': 'Rate limiting bypass test completed'
        }
    
    async def test_csrf_protection(self, test: SecurityTest) -> Dict[str, Any]:
        """Test CSRF protection mechanisms"""
        
        vulnerabilities = []
        
        try:
            # Test CSRF without token
            test_payload = {"action": "sensitive_operation", "value": "test"}
            
            async with self.session.post(
                f"{self.base_url}{test.endpoint}",
                json=test_payload
            ) as response:
                
                # If request succeeds without CSRF token, it's vulnerable
                if response.status == 200:
                    vulnerability = SecurityVulnerability(
                        test_name=test.name,
                        vulnerability_type=test.vulnerability_type,
                        severity=test.severity,
                        endpoint=test.endpoint,
                        description="CSRF protection missing",
                        evidence="Sensitive operation succeeded without CSRF token",
                        recommendation="Implement CSRF token validation for state-changing operations"
                    )
                    vulnerabilities.append(vulnerability)
            
            # Test with invalid CSRF token
            headers = {"X-CSRF-Token": "invalid_token"}
            async with self.session.post(
                f"{self.base_url}{test.endpoint}",
                json=test_payload,
                headers=headers
            ) as response:
                
                if response.status == 200:
                    vulnerability = SecurityVulnerability(
                        test_name=test.name,
                        vulnerability_type=test.vulnerability_type,
                        severity=test.severity,
                        endpoint=test.endpoint,
                        description="CSRF token validation insufficient",
                        evidence="Sensitive operation succeeded with invalid CSRF token",
                        recommendation="Implement proper CSRF token validation"
                    )
                    vulnerabilities.append(vulnerability)
        
        except Exception as e:
            logger.warning(f"Error testing CSRF protection: {e}")
        
        return {
            'passed': len(vulnerabilities) == 0,
            'vulnerabilities': vulnerabilities,
            'status_code': 403,  # Expected without valid CSRF token
            'headers': {},
            'body': 'CSRF protection test completed'
        }
    
    # Helper methods for JWT testing
    
    def _create_jwt_with_none_algorithm(self) -> str:
        """Create JWT with 'none' algorithm"""
        header = {"alg": "none", "typ": "JWT"}
        payload = {"sub": "admin", "role": "admin", "exp": int(time.time()) + 3600}
        
        # Create unsigned JWT
        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        
        return f"{header_b64}.{payload_b64}."
    
    def _create_jwt_with_weak_secret(self) -> str:
        """Create JWT with weak secret"""
        payload = {"sub": "admin", "role": "admin", "exp": int(time.time()) + 3600}
        return pyjwt.encode(payload, "secret", algorithm="HS256")
    
    def _create_modified_jwt(self) -> str:
        """Create JWT with modified payload"""
        # Create legitimate token first
        payload = {"sub": "user", "role": "user", "exp": int(time.time()) + 3600}
        token = pyjwt.encode(payload, "secret", algorithm="HS256")
        
        # Modify payload to admin (this should fail signature verification)
        parts = token.split('.')
        modified_payload = {"sub": "admin", "role": "admin", "exp": int(time.time()) + 3600}
        modified_payload_b64 = base64.urlsafe_b64encode(json.dumps(modified_payload).encode()).decode().rstrip('=')
        
        return f"{parts[0]}.{modified_payload_b64}.{parts[2]}"
    
    def _create_expired_jwt(self) -> str:
        """Create expired JWT"""
        payload = {"sub": "admin", "role": "admin", "exp": int(time.time()) - 3600}  # Expired 1 hour ago
        return pyjwt.encode(payload, "secret", algorithm="HS256")
    
    def _create_algorithm_confused_jwt(self) -> str:
        """Create JWT with algorithm confusion"""
        # This would typically involve using a public key as HMAC secret
        payload = {"sub": "admin", "role": "admin", "exp": int(time.time()) + 3600}
        return pyjwt.encode(payload, "public_key_content", algorithm="HS256")
    
    def _create_jwt_with_role(self, role: str) -> str:
        """Create JWT with specific role"""
        payload = {
            "sub": f"user_{role}",
            "role": role,
            "exp": int(time.time()) + 3600
        }
        return pyjwt.encode(payload, "secret", algorithm="HS256")
    
    async def _test_jwt_token(self, test: SecurityTest, token: str, vulnerability_desc: str, vulnerabilities: List):
        """Test a JWT token and add vulnerability if accepted"""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            
            async with self.session.get(
                f"{self.base_url}{test.endpoint}",
                headers=headers
            ) as response:
                
                if response.status == 200:
                    vulnerability = SecurityVulnerability(
                        test_name=test.name,
                        vulnerability_type=test.vulnerability_type,
                        severity=test.severity,
                        endpoint=test.endpoint,
                        description=f"JWT vulnerability: {vulnerability_desc}",
                        evidence=f"Malicious JWT token accepted",
                        recommendation="Implement proper JWT validation and signature verification"
                    )
                    vulnerabilities.append(vulnerability)
        
        except Exception as e:
            logger.warning(f"Error testing JWT token: {e}")
    
    def _is_properly_encoded(self, payload: str, response: str) -> bool:
        """Check if payload is properly encoded in response"""
        # Check for HTML encoding
        encoded_variants = [
            payload.replace('<', '&lt;').replace('>', '&gt;'),
            payload.replace('"', '&quot;').replace("'", '&#x27;'),
            quote(payload),  # URL encoding
        ]
        
        return any(variant in response for variant in encoded_variants)
    
    def _generate_security_report(self, results: List[SecurityTestResult], 
                                vulnerabilities: List[SecurityVulnerability]) -> Dict[str, Any]:
        """Generate comprehensive security report"""
        
        total_tests = len(results)
        passed_tests = sum(1 for r in results if r.passed)
        overall_success = len(vulnerabilities) == 0
        
        # Categorize vulnerabilities by severity
        severity_counts = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 0,
            Severity.MEDIUM: 0,
            Severity.LOW: 0,
            Severity.INFO: 0
        }
        
        for vuln in vulnerabilities:
            severity_counts[vuln.severity] += 1
        
        # Calculate security score (0-100)
        security_score = max(0, 100 - (
            severity_counts[Severity.CRITICAL] * 25 +
            severity_counts[Severity.HIGH] * 15 +
            severity_counts[Severity.MEDIUM] * 10 +
            severity_counts[Severity.LOW] * 5 +
            severity_counts[Severity.INFO] * 1
        ))
        
        return {
            'overall_success': overall_success,
            'tests_run': total_tests,
            'tests_passed': passed_tests,
            'tests_failed': total_tests - passed_tests,
            'vulnerabilities_found': len(vulnerabilities),
            'critical_vulnerabilities': severity_counts[Severity.CRITICAL],
            'high_vulnerabilities': severity_counts[Severity.HIGH],
            'medium_vulnerabilities': severity_counts[Severity.MEDIUM],
            'low_vulnerabilities': severity_counts[Severity.LOW],
            'security_score': security_score,
            'penetration_tests_passed': passed_tests,
            'vulnerability_details': [
                {
                    'test_name': v.test_name,
                    'type': v.vulnerability_type.value,
                    'severity': v.severity.value,
                    'endpoint': v.endpoint,
                    'description': v.description,
                    'recommendation': v.recommendation
                }
                for v in vulnerabilities
            ],
            'test_results': [
                {
                    'name': r.test_name,
                    'type': r.vulnerability_type.value,
                    'passed': r.passed,
                    'vulnerabilities_count': len(r.vulnerabilities_found),
                    'execution_time_ms': r.execution_time_ms
                }
                for r in results
            ],
            'recommendations': self._generate_security_recommendations(vulnerabilities)
        }
    
    def _generate_security_recommendations(self, vulnerabilities: List[SecurityVulnerability]) -> List[str]:
        """Generate security recommendations based on vulnerabilities found"""
        recommendations = []
        
        # Critical vulnerabilities
        critical_vulns = [v for v in vulnerabilities if v.severity == Severity.CRITICAL]
        if critical_vulns:
            recommendations.append(
                f"URGENT: Address {len(critical_vulns)} critical security vulnerabilities before production deployment"
            )
        
        # High severity vulnerabilities
        high_vulns = [v for v in vulnerabilities if v.severity == Severity.HIGH]
        if high_vulns:
            recommendations.append(
                f"Address {len(high_vulns)} high-severity vulnerabilities to improve security posture"
            )
        
        # Specific recommendations by vulnerability type
        vuln_types = set(v.vulnerability_type for v in vulnerabilities)
        
        if VulnerabilityType.SQL_INJECTION in vuln_types:
            recommendations.append("Implement parameterized queries and input validation to prevent SQL injection")
        
        if VulnerabilityType.XSS in vuln_types:
            recommendations.append("Implement output encoding and Content Security Policy to prevent XSS attacks")
        
        if VulnerabilityType.JWT_VULNERABILITIES in vuln_types:
            recommendations.append("Strengthen JWT implementation with proper signature verification and secure algorithms")
        
        if VulnerabilityType.AUTHENTICATION_BYPASS in vuln_types:
            recommendations.append("Review and strengthen authentication mechanisms")
        
        if VulnerabilityType.INSECURE_HEADERS in vuln_types:
            recommendations.append("Implement comprehensive security headers")
        
        # General recommendations
        if not vulnerabilities:
            recommendations.append("Security testing passed all checks. Consider implementing continuous security testing.")
        else:
            recommendations.append("Implement automated security testing in CI/CD pipeline")
            recommendations.append("Conduct regular security audits and penetration testing")
        
        return recommendations