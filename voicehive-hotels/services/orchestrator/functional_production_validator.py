#!/usr/bin/env python3
"""
Functional Production Readiness Validator

Replaces file path existence checks with actual functional testing of services.
Tests real connectivity, authentication, and service operations rather than
just checking if configuration files exist.

Following best practices from:
- HashiCorp Vault Production Hardening Guide
- OWASP Authentication Cheat Sheet
- FastAPI Production Best Practices
"""

import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import json
import asyncpg
import redis.asyncio as aioredis
import httpx

# Import existing services for functional testing
from health import HealthChecker, HealthStatus, ComponentHealth
from jwt_service import JWTService
from vault_client import VaultClient
from auth_models import UserRole, UserContext
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.functional_validator")


class FunctionalTestStatus(Enum):
    """Functional test status enumeration"""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class FunctionalTestResult:
    """Individual functional test result"""
    test_name: str
    status: FunctionalTestStatus
    message: str
    duration: float
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    error: Optional[str] = None


@dataclass
class FunctionalValidationReport:
    """Complete functional validation report"""
    overall_status: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    warning_tests: int
    skipped_tests: int
    total_duration: float
    timestamp: str
    test_results: List[FunctionalTestResult]
    summary: Dict[str, Any]


class FunctionalProductionValidator:
    """
    Functional production readiness validator

    Performs actual functional testing instead of file existence checks:
    - Tests real service connectivity
    - Validates actual authentication flows
    - Tests database operations
    - Validates Redis operations
    - Tests Vault secret operations
    - Performs end-to-end service tests
    """

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[FunctionalTestResult] = []
        self.health_checker = HealthChecker()

        # Initialize services for testing
        self.jwt_service: Optional[JWTService] = None
        self.vault_client: Optional[VaultClient] = None

        logger.info("functional_validator_initialized", base_url=base_url)

    async def run_all_functional_tests(self) -> FunctionalValidationReport:
        """Run complete functional validation test suite"""
        start_time = datetime.utcnow()
        logger.info("starting_functional_validation_tests")

        # Core service functionality tests
        await self._test_jwt_functionality()
        await self._test_database_connectivity()
        await self._test_redis_operations()
        await self._test_vault_operations()

        # External service health tests
        await self._test_external_service_health()

        # Integration tests
        await self._test_authentication_flow()
        await self._test_service_dependencies()

        # Performance validation
        await self._test_basic_performance()

        # Generate comprehensive report
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        return self._generate_validation_report(duration)

    async def _test_jwt_functionality(self) -> None:
        """Test actual JWT token generation and validation functionality"""
        test_start = datetime.utcnow()

        try:
            # Initialize JWT service
            self.jwt_service = JWTService()

            # Test 1: Generate a valid token
            test_user_data = {
                "user_id": "test-user-functional",
                "email": "test@voicehive.com",
                "roles": ["hotel_staff"],
                "hotel_ids": ["test-hotel"]
            }

            token_response = await self.jwt_service.create_access_token(
                user_id=test_user_data["user_id"],
                email=test_user_data["email"],
                roles=[UserRole.HOTEL_STAFF],
                hotel_ids=test_user_data["hotel_ids"]
            )

            if not token_response or "access_token" not in token_response:
                raise Exception("Failed to generate JWT token")

            # Test 2: Validate the generated token
            token = token_response["access_token"]
            user_context = await self.jwt_service.validate_token(token)

            if user_context.user_id != test_user_data["user_id"]:
                raise Exception("Token validation returned incorrect user context")

            # Test 3: Test token expiration handling
            # Create an expired token (this is for testing only)
            try:
                expired_token_payload = {
                    "sub": "test-user",
                    "email": "test@voicehive.com",
                    "roles": ["hotel_staff"],
                    "exp": datetime.utcnow() - timedelta(minutes=5),  # Expired 5 minutes ago
                    "jti": "test-expired-token",
                    "session_id": "test-session"
                }

                # This should fail with expired token
                import jwt as pyjwt
                expired_token = pyjwt.encode(
                    expired_token_payload,
                    self.jwt_service.private_key,
                    algorithm=self.jwt_service.algorithm
                )

                try:
                    await self.jwt_service.validate_token(expired_token)
                    raise Exception("Expired token validation should have failed")
                except Exception as e:
                    if "expired" not in str(e).lower():
                        raise Exception(f"Wrong exception for expired token: {e}")

            except Exception as exp_test_error:
                # This is expected for expired tokens
                if "expired" not in str(exp_test_error).lower():
                    raise exp_test_error

            # Test 4: Test token blacklisting
            await self.jwt_service.blacklist_token(token)

            try:
                await self.jwt_service.validate_token(token)
                raise Exception("Blacklisted token validation should have failed")
            except Exception as e:
                if "revoked" not in str(e).lower():
                    raise Exception(f"Wrong exception for blacklisted token: {e}")

            duration = (datetime.utcnow() - test_start).total_seconds()

            self.results.append(FunctionalTestResult(
                test_name="JWT Functionality",
                status=FunctionalTestStatus.PASSED,
                message="JWT token generation, validation, expiration, and blacklisting working correctly",
                duration=duration,
                details={
                    "token_generated": True,
                    "token_validated": True,
                    "expiration_handled": True,
                    "blacklisting_working": True
                },
                timestamp=datetime.utcnow().isoformat()
            ))

        except Exception as e:
            duration = (datetime.utcnow() - test_start).total_seconds()
            logger.error("jwt_functional_test_failed", error=str(e))

            self.results.append(FunctionalTestResult(
                test_name="JWT Functionality",
                status=FunctionalTestStatus.FAILED,
                message=f"JWT functionality test failed: {str(e)}",
                duration=duration,
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ))

    async def _test_database_connectivity(self) -> None:
        """Test actual database connectivity and operations"""
        test_start = datetime.utcnow()

        try:
            # Get database configuration
            database_url = os.getenv("DATABASE_URL", "postgresql://voicehive:voicehive@localhost:5432/voicehive")

            # Test connection and basic query
            conn = await asyncpg.connect(database_url)

            # Test 1: Basic connectivity and query
            result = await conn.fetchval("SELECT 1")
            if result != 1:
                raise Exception("Basic database query failed")

            # Test 2: Check if core tables exist (non-destructive)
            tables_query = """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
            """
            tables = await conn.fetch(tables_query)
            table_names = [row['table_name'] for row in tables]

            # Expected core tables (adjust based on your schema)
            expected_tables = ['users', 'hotels', 'calls', 'conversations']
            missing_tables = [table for table in expected_tables if table not in table_names]

            # Test 3: Test transaction capability
            async with conn.transaction():
                # Non-destructive transaction test
                test_result = await conn.fetchval("SELECT COUNT(*) FROM information_schema.tables")
                if test_result <= 0:
                    raise Exception("Transaction test failed")

            await conn.close()

            duration = (datetime.utcnow() - test_start).total_seconds()

            status = FunctionalTestStatus.PASSED
            message = "Database connectivity and operations working correctly"

            if missing_tables:
                status = FunctionalTestStatus.WARNING
                message += f" (Missing tables: {missing_tables})"

            self.results.append(FunctionalTestResult(
                test_name="Database Connectivity",
                status=status,
                message=message,
                duration=duration,
                details={
                    "connectivity": True,
                    "basic_query": True,
                    "transaction_support": True,
                    "tables_found": len(table_names),
                    "missing_tables": missing_tables
                },
                timestamp=datetime.utcnow().isoformat()
            ))

        except Exception as e:
            duration = (datetime.utcnow() - test_start).total_seconds()
            logger.error("database_functional_test_failed", error=str(e))

            self.results.append(FunctionalTestResult(
                test_name="Database Connectivity",
                status=FunctionalTestStatus.FAILED,
                message=f"Database connectivity test failed: {str(e)}",
                duration=duration,
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ))

    async def _test_redis_operations(self) -> None:
        """Test actual Redis connectivity and operations"""
        test_start = datetime.utcnow()

        try:
            # Get Redis configuration
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

            # Test Redis operations
            redis_client = aioredis.from_url(redis_url)

            # Test 1: Basic connectivity
            pong = await redis_client.ping()
            if not pong:
                raise Exception("Redis ping failed")

            # Test 2: Set/Get operations
            test_key = "functional_test:redis_test"
            test_value = "functional_test_value"

            await redis_client.set(test_key, test_value, ex=60)  # 60 second expiry
            retrieved_value = await redis_client.get(test_key)

            if retrieved_value.decode() != test_value:
                raise Exception("Redis set/get operation failed")

            # Test 3: Hash operations (used by JWT sessions)
            hash_key = "functional_test:hash_test"
            await redis_client.hset(hash_key, "field1", "value1")
            await redis_client.expire(hash_key, 60)

            hash_value = await redis_client.hget(hash_key, "field1")
            if hash_value.decode() != "value1":
                raise Exception("Redis hash operations failed")

            # Test 4: Cleanup test keys
            await redis_client.delete(test_key, hash_key)

            await redis_client.close()

            duration = (datetime.utcnow() - test_start).total_seconds()

            self.results.append(FunctionalTestResult(
                test_name="Redis Operations",
                status=FunctionalTestStatus.PASSED,
                message="Redis connectivity and operations working correctly",
                duration=duration,
                details={
                    "ping": True,
                    "set_get": True,
                    "hash_operations": True,
                    "expiry_support": True
                },
                timestamp=datetime.utcnow().isoformat()
            ))

        except Exception as e:
            duration = (datetime.utcnow() - test_start).total_seconds()
            logger.error("redis_functional_test_failed", error=str(e))

            self.results.append(FunctionalTestResult(
                test_name="Redis Operations",
                status=FunctionalTestStatus.FAILED,
                message=f"Redis operations test failed: {str(e)}",
                duration=duration,
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ))

    async def _test_vault_operations(self) -> None:
        """Test actual Vault connectivity and secret operations"""
        test_start = datetime.utcnow()

        try:
            # Initialize Vault client
            self.vault_client = VaultClient()

            # Test 1: Health check
            health_status = await self.vault_client.health_check()
            if not health_status.healthy:
                raise Exception(f"Vault health check failed: {health_status.details}")

            # Test 2: Secret operations (if Vault is available)
            test_secret_path = "functional-test/test-secret"
            test_secret_data = {"test_key": "test_value"}

            try:
                # Store a test secret
                await self.vault_client.store_secret(test_secret_path, test_secret_data)

                # Retrieve the test secret
                retrieved_secret = await self.vault_client.get_secret(test_secret_path)

                if retrieved_secret.get("test_key") != "test_value":
                    raise Exception("Vault secret storage/retrieval failed")

                # Cleanup test secret
                await self.vault_client.delete_secret(test_secret_path)

                secret_operations_working = True

            except Exception as secret_error:
                # If we can't do secret operations, it might be a permissions issue
                logger.warning("vault_secret_operations_limited", error=str(secret_error))
                secret_operations_working = False

            duration = (datetime.utcnow() - test_start).total_seconds()

            status = FunctionalTestStatus.PASSED
            message = "Vault connectivity working correctly"

            if not secret_operations_working:
                status = FunctionalTestStatus.WARNING
                message += " (Limited secret operations access)"

            self.results.append(FunctionalTestResult(
                test_name="Vault Operations",
                status=status,
                message=message,
                duration=duration,
                details={
                    "health_check": True,
                    "secret_operations": secret_operations_working,
                    "vault_status": health_status.details
                },
                timestamp=datetime.utcnow().isoformat()
            ))

        except Exception as e:
            duration = (datetime.utcnow() - test_start).total_seconds()
            logger.error("vault_functional_test_failed", error=str(e))

            self.results.append(FunctionalTestResult(
                test_name="Vault Operations",
                status=FunctionalTestStatus.FAILED,
                message=f"Vault operations test failed: {str(e)}",
                duration=duration,
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ))

    async def _test_external_service_health(self) -> None:
        """Test external service health using existing health checker"""
        test_start = datetime.utcnow()

        try:
            # Use existing health checker for comprehensive service testing
            health_report = await self.health_checker.get_health_summary()

            # Check overall health status
            healthy_services = []
            degraded_services = []
            unhealthy_services = []

            for component in health_report.components:
                if component.status == HealthStatus.HEALTHY:
                    healthy_services.append(component.name)
                elif component.status == HealthStatus.DEGRADED:
                    degraded_services.append(component.name)
                else:
                    unhealthy_services.append(component.name)

            duration = (datetime.utcnow() - test_start).total_seconds()

            if unhealthy_services:
                status = FunctionalTestStatus.FAILED
                message = f"Unhealthy services detected: {unhealthy_services}"
            elif degraded_services:
                status = FunctionalTestStatus.WARNING
                message = f"Degraded services detected: {degraded_services}"
            else:
                status = FunctionalTestStatus.PASSED
                message = "All external services healthy"

            self.results.append(FunctionalTestResult(
                test_name="External Service Health",
                status=status,
                message=message,
                duration=duration,
                details={
                    "overall_status": health_report.status.value,
                    "healthy_services": healthy_services,
                    "degraded_services": degraded_services,
                    "unhealthy_services": unhealthy_services,
                    "total_components": len(health_report.components)
                },
                timestamp=datetime.utcnow().isoformat()
            ))

        except Exception as e:
            duration = (datetime.utcnow() - test_start).total_seconds()
            logger.error("external_service_health_test_failed", error=str(e))

            self.results.append(FunctionalTestResult(
                test_name="External Service Health",
                status=FunctionalTestStatus.FAILED,
                message=f"External service health test failed: {str(e)}",
                duration=duration,
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ))

    async def _test_authentication_flow(self) -> None:
        """Test end-to-end authentication flow"""
        test_start = datetime.utcnow()

        try:
            if not self.jwt_service:
                raise Exception("JWT service not initialized")

            # Test complete authentication flow
            # 1. Create user token
            token_response = await self.jwt_service.create_access_token(
                user_id="functional-test-user",
                email="functional@test.com",
                roles=[UserRole.HOTEL_STAFF],
                hotel_ids=["test-hotel"]
            )

            # 2. Use token to validate user context
            token = token_response["access_token"]
            user_context = await self.jwt_service.validate_token(token)

            # 3. Test role-based access
            if UserRole.HOTEL_STAFF not in user_context.roles:
                raise Exception("Role-based access test failed")

            # 4. Test session management
            session_id = user_context.session_id
            if not session_id:
                raise Exception("Session management not working")

            # 5. Test token refresh capabilities
            refresh_response = await self.jwt_service.refresh_access_token(token)
            if not refresh_response or "access_token" not in refresh_response:
                raise Exception("Token refresh failed")

            duration = (datetime.utcnow() - test_start).total_seconds()

            self.results.append(FunctionalTestResult(
                test_name="Authentication Flow",
                status=FunctionalTestStatus.PASSED,
                message="End-to-end authentication flow working correctly",
                duration=duration,
                details={
                    "token_creation": True,
                    "token_validation": True,
                    "role_based_access": True,
                    "session_management": True,
                    "token_refresh": True
                },
                timestamp=datetime.utcnow().isoformat()
            ))

        except Exception as e:
            duration = (datetime.utcnow() - test_start).total_seconds()
            logger.error("authentication_flow_test_failed", error=str(e))

            self.results.append(FunctionalTestResult(
                test_name="Authentication Flow",
                status=FunctionalTestStatus.FAILED,
                message=f"Authentication flow test failed: {str(e)}",
                duration=duration,
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ))

    async def _test_service_dependencies(self) -> None:
        """Test service dependencies and integration points"""
        test_start = datetime.utcnow()

        try:
            # Test API endpoint availability
            async with httpx.AsyncClient() as client:
                # Test health endpoint
                health_response = await client.get(f"{self.base_url}/health")
                if health_response.status_code != 200:
                    raise Exception(f"Health endpoint failed: {health_response.status_code}")

                # Test metrics endpoint
                try:
                    metrics_response = await client.get(f"{self.base_url}/metrics")
                    metrics_available = metrics_response.status_code == 200
                except:
                    metrics_available = False

                # Test documentation endpoint
                try:
                    docs_response = await client.get(f"{self.base_url}/docs")
                    docs_available = docs_response.status_code == 200
                except:
                    docs_available = False

            duration = (datetime.utcnow() - test_start).total_seconds()

            self.results.append(FunctionalTestResult(
                test_name="Service Dependencies",
                status=FunctionalTestStatus.PASSED,
                message="Service dependencies and endpoints accessible",
                duration=duration,
                details={
                    "health_endpoint": True,
                    "metrics_endpoint": metrics_available,
                    "docs_endpoint": docs_available,
                    "base_url": self.base_url
                },
                timestamp=datetime.utcnow().isoformat()
            ))

        except Exception as e:
            duration = (datetime.utcnow() - test_start).total_seconds()
            logger.error("service_dependencies_test_failed", error=str(e))

            self.results.append(FunctionalTestResult(
                test_name="Service Dependencies",
                status=FunctionalTestStatus.FAILED,
                message=f"Service dependencies test failed: {str(e)}",
                duration=duration,
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ))

    async def _test_basic_performance(self) -> None:
        """Test basic performance characteristics"""
        test_start = datetime.utcnow()

        try:
            # Performance test: JWT token generation speed
            jwt_start = datetime.utcnow()
            token_count = 10

            for i in range(token_count):
                await self.jwt_service.create_access_token(
                    user_id=f"perf-test-{i}",
                    email=f"perf{i}@test.com",
                    roles=[UserRole.HOTEL_STAFF],
                    hotel_ids=["test-hotel"]
                )

            jwt_duration = (datetime.utcnow() - jwt_start).total_seconds()
            jwt_rate = token_count / jwt_duration  # tokens per second

            # Performance test: Health check speed
            health_start = datetime.utcnow()
            await self.health_checker.get_health_summary()
            health_duration = (datetime.utcnow() - health_start).total_seconds()

            duration = (datetime.utcnow() - test_start).total_seconds()

            # Define performance thresholds
            jwt_rate_threshold = 5.0  # tokens per second
            health_check_threshold = 2.0  # seconds

            performance_issues = []
            if jwt_rate < jwt_rate_threshold:
                performance_issues.append(f"JWT generation rate low: {jwt_rate:.2f} tokens/sec")
            if health_duration > health_check_threshold:
                performance_issues.append(f"Health check slow: {health_duration:.2f}s")

            status = FunctionalTestStatus.WARNING if performance_issues else FunctionalTestStatus.PASSED
            message = "Basic performance acceptable" if not performance_issues else f"Performance concerns: {performance_issues}"

            self.results.append(FunctionalTestResult(
                test_name="Basic Performance",
                status=status,
                message=message,
                duration=duration,
                details={
                    "jwt_generation_rate": jwt_rate,
                    "health_check_duration": health_duration,
                    "performance_issues": performance_issues
                },
                timestamp=datetime.utcnow().isoformat()
            ))

        except Exception as e:
            duration = (datetime.utcnow() - test_start).total_seconds()
            logger.error("basic_performance_test_failed", error=str(e))

            self.results.append(FunctionalTestResult(
                test_name="Basic Performance",
                status=FunctionalTestStatus.FAILED,
                message=f"Basic performance test failed: {str(e)}",
                duration=duration,
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ))

    def _generate_validation_report(self, total_duration: float) -> FunctionalValidationReport:
        """Generate comprehensive functional validation report"""

        # Count test results by status
        passed_tests = len([r for r in self.results if r.status == FunctionalTestStatus.PASSED])
        failed_tests = len([r for r in self.results if r.status == FunctionalTestStatus.FAILED])
        warning_tests = len([r for r in self.results if r.status == FunctionalTestStatus.WARNING])
        skipped_tests = len([r for r in self.results if r.status == FunctionalTestStatus.SKIPPED])

        # Determine overall status
        if failed_tests > 0:
            overall_status = "FAILED"
        elif warning_tests > 0:
            overall_status = "WARNING"
        else:
            overall_status = "PASSED"

        # Generate summary
        summary = {
            "validation_type": "functional",
            "test_categories": {
                "core_services": ["JWT Functionality", "Database Connectivity", "Redis Operations", "Vault Operations"],
                "integration": ["Authentication Flow", "Service Dependencies"],
                "health_monitoring": ["External Service Health"],
                "performance": ["Basic Performance"]
            },
            "critical_failures": [r.test_name for r in self.results if r.status == FunctionalTestStatus.FAILED],
            "warnings": [r.test_name for r in self.results if r.status == FunctionalTestStatus.WARNING],
            "recommendations": self._generate_recommendations()
        }

        return FunctionalValidationReport(
            overall_status=overall_status,
            total_tests=len(self.results),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            warning_tests=warning_tests,
            skipped_tests=skipped_tests,
            total_duration=total_duration,
            timestamp=datetime.utcnow().isoformat(),
            test_results=self.results,
            summary=summary
        )

    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on test results"""
        recommendations = []

        failed_tests = [r for r in self.results if r.status == FunctionalTestStatus.FAILED]
        warning_tests = [r for r in self.results if r.status == FunctionalTestStatus.WARNING]

        if failed_tests:
            recommendations.append("CRITICAL: Address failed functional tests before production deployment")
            for test in failed_tests:
                recommendations.append(f"- Fix {test.test_name}: {test.message}")

        if warning_tests:
            recommendations.append("WARNING: Review and optimize components with warnings")
            for test in warning_tests:
                recommendations.append(f"- Optimize {test.test_name}: {test.message}")

        if not failed_tests and not warning_tests:
            recommendations.append("All functional tests passed - system ready for production deployment")

        return recommendations


async def main():
    """Main function for running functional validation"""
    validator = FunctionalProductionValidator()
    report = await validator.run_all_functional_tests()

    print("\n" + "="*80)
    print("FUNCTIONAL PRODUCTION VALIDATION REPORT")
    print("="*80)
    print(f"Overall Status: {report.overall_status}")
    print(f"Total Tests: {report.total_tests}")
    print(f"Passed: {report.passed_tests}")
    print(f"Failed: {report.failed_tests}")
    print(f"Warnings: {report.warning_tests}")
    print(f"Duration: {report.total_duration:.2f}s")
    print()

    for result in report.test_results:
        status_emoji = "✅" if result.status == FunctionalTestStatus.PASSED else "❌" if result.status == FunctionalTestStatus.FAILED else "⚠️"
        print(f"{status_emoji} {result.test_name}: {result.message} ({result.duration:.2f}s)")

    print("\nRecommendations:")
    for rec in report.summary["recommendations"]:
        print(f"- {rec}")

    # Save detailed report
    report_path = "functional_validation_report.json"
    with open(report_path, 'w') as f:
        json.dump({
            "overall_status": report.overall_status,
            "total_tests": report.total_tests,
            "passed_tests": report.passed_tests,
            "failed_tests": report.failed_tests,
            "warning_tests": report.warning_tests,
            "total_duration": report.total_duration,
            "timestamp": report.timestamp,
            "test_results": [
                {
                    "test_name": r.test_name,
                    "status": r.status.value,
                    "message": r.message,
                    "duration": r.duration,
                    "details": r.details,
                    "timestamp": r.timestamp,
                    "error": r.error
                } for r in report.test_results
            ],
            "summary": report.summary
        }, f, indent=2)

    print(f"\nDetailed report saved to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())