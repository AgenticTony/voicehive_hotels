#!/usr/bin/env python3
"""
Test Production Validation System

Simple test runner to validate that the production validation system works correctly.
This can be used for development and CI/CD integration.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_production_readiness_validator():
    """Test the production readiness validator"""
    try:
        from production_readiness_validator import ProductionReadinessValidator
        
        logger.info("Testing Production Readiness Validator...")
        validator = ProductionReadinessValidator()
        
        # Run a subset of validations for testing
        await validator._validate_security_controls()
        await validator._validate_authentication_system()
        await validator._validate_performance_optimization()
        
        # Check if we have some results
        if len(validator.results) > 0:
            logger.info(f"✅ Production Readiness Validator: {len(validator.results)} tests completed")
            return True
        else:
            logger.error("❌ Production Readiness Validator: No test results")
            return False
            
    except Exception as e:
        logger.error(f"❌ Production Readiness Validator failed: {str(e)}")
        return False


async def test_security_penetration_tester():
    """Test the security penetration tester"""
    try:
        from security_penetration_tester import SecurityPenetrationTester
        
        logger.info("Testing Security Penetration Tester...")
        tester = SecurityPenetrationTester(base_url="http://httpbin.org")  # Use httpbin for testing
        
        # Run a subset of security tests
        await tester._test_security_headers()
        await tester._test_http_methods()
        
        # Check if we have some results
        if len(tester.results) > 0:
            logger.info(f"✅ Security Penetration Tester: {len(tester.results)} tests completed")
            return True
        else:
            logger.error("❌ Security Penetration Tester: No test results")
            return False
            
    except Exception as e:
        logger.error(f"❌ Security Penetration Tester failed: {str(e)}")
        return False


async def test_load_testing_validator():
    """Test the load testing validator"""
    try:
        from load_testing_validator import LoadTestingValidator
        
        logger.info("Testing Load Testing Validator...")
        validator = LoadTestingValidator(base_url="http://httpbin.org")  # Use httpbin for testing
        
        # Run a simple baseline test
        await validator._test_baseline_performance()
        
        # Check if we have some results
        if len(validator.results) > 0:
            logger.info(f"✅ Load Testing Validator: {len(validator.results)} tests completed")
            return True
        else:
            logger.error("❌ Load Testing Validator: No test results")
            return False
            
    except Exception as e:
        logger.error(f"❌ Load Testing Validator failed: {str(e)}")
        return False


async def test_certification_generator():
    """Test the certification generator"""
    try:
        from production_certification_generator import ProductionCertificationGenerator
        
        logger.info("Testing Production Certification Generator...")
        generator = ProductionCertificationGenerator()
        
        # Test criteria definition
        criteria = generator._define_certification_criteria()
        
        if len(criteria) > 0:
            logger.info(f"✅ Certification Generator: {len(criteria)} criteria defined")
            return True
        else:
            logger.error("❌ Certification Generator: No criteria defined")
            return False
            
    except Exception as e:
        logger.error(f"❌ Certification Generator failed: {str(e)}")
        return False


async def test_validation_orchestrator():
    """Test the validation orchestrator"""
    try:
        from production_validation_orchestrator import ProductionValidationOrchestrator
        
        logger.info("Testing Production Validation Orchestrator...")
        orchestrator = ProductionValidationOrchestrator(
            base_url="http://httpbin.org",
            skip_phases=["load_testing", "disaster_recovery", "compliance_verification"]
        )
        
        # Test infrastructure check only
        result = await orchestrator._run_infrastructure_check()
        
        if result and "status" in result:
            logger.info(f"✅ Validation Orchestrator: Infrastructure check completed with status {result['status']}")
            return True
        else:
            logger.error("❌ Validation Orchestrator: Infrastructure check failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Validation Orchestrator failed: {str(e)}")
        return False


async def run_all_tests():
    """Run all validation system tests"""
    logger.info("🧪 Starting Production Validation System Tests")
    logger.info("=" * 60)
    
    tests = [
        ("Production Readiness Validator", test_production_readiness_validator),
        ("Security Penetration Tester", test_security_penetration_tester),
        ("Load Testing Validator", test_load_testing_validator),
        ("Certification Generator", test_certification_generator),
        ("Validation Orchestrator", test_validation_orchestrator),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        logger.info(f"\n🔄 Running {test_name}...")
        start_time = time.time()
        
        try:
            success = await test_func()
            duration = time.time() - start_time
            results[test_name] = {
                "success": success,
                "duration": duration,
                "error": None
            }
            
            if success:
                logger.info(f"✅ {test_name} completed successfully in {duration:.2f}s")
            else:
                logger.error(f"❌ {test_name} failed in {duration:.2f}s")
                
        except Exception as e:
            duration = time.time() - start_time
            results[test_name] = {
                "success": False,
                "duration": duration,
                "error": str(e)
            }
            logger.error(f"💥 {test_name} crashed in {duration:.2f}s: {str(e)}")
    
    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 60)
    
    successful_tests = [name for name, result in results.items() if result["success"]]
    failed_tests = [name for name, result in results.items() if not result["success"]]
    
    logger.info(f"Total Tests: {len(tests)}")
    logger.info(f"Successful: {len(successful_tests)}")
    logger.info(f"Failed: {len(failed_tests)}")
    
    if failed_tests:
        logger.info(f"\nFailed Tests:")
        for test_name in failed_tests:
            error = results[test_name].get("error")
            if error:
                logger.info(f"  ❌ {test_name}: {error}")
            else:
                logger.info(f"  ❌ {test_name}: Test returned False")
    
    # Save test results
    test_results_path = Path("validation_system_test_results.json")
    with open(test_results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info(f"\n📄 Test results saved to: {test_results_path}")
    
    # Return overall success
    return len(failed_tests) == 0


async def main():
    """Main test execution function"""
    try:
        success = await run_all_tests()
        
        if success:
            logger.info("\n🎉 ALL TESTS PASSED")
            logger.info("Production validation system is working correctly!")
            sys.exit(0)
        else:
            logger.error("\n❌ SOME TESTS FAILED")
            logger.error("Production validation system has issues that need to be addressed.")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"\n💥 TEST EXECUTION FAILED: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())