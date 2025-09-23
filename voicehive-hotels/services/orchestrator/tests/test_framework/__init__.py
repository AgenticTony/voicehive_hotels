"""
Enhanced Testing Framework for Production Readiness

This package provides comprehensive testing capabilities including:
- Coverage analysis and enhancement
- Load testing for critical user journeys  
- Chaos engineering with failure injection
- Security penetration testing
- Performance regression testing
- Contract testing for PMS integrations
"""

__version__ = "1.0.0"
__author__ = "VoiceHive Hotels Team"

from .coverage_analyzer import CoverageAnalyzer
from .load_tester import LoadTester
from .chaos_engineer import ChaosEngineer
from .security_tester import SecurityTester
from .performance_tester import PerformanceTester
from .contract_tester import ContractTester

__all__ = [
    "CoverageAnalyzer",
    "LoadTester", 
    "ChaosEngineer",
    "SecurityTester",
    "PerformanceTester",
    "ContractTester"
]