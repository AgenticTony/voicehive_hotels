#!/usr/bin/env python3
"""
Test script for dependency security manager

This script tests the basic functionality of the dependency security system
without requiring external API keys or network access.
"""

import json
import tempfile
from pathlib import Path
import sys
import os

# Add the scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from dependency_security_manager import DependencySecurityManager, DependencyInfo, Vulnerability, SeverityLevel
except ImportError:
    # Try importing with full module path
    import importlib.util
    spec = importlib.util.spec_from_file_location("dependency_security_manager", 
                                                  Path(__file__).parent / "dependency-security-manager.py")
    dsm_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dsm_module)
    
    DependencySecurityManager = dsm_module.DependencySecurityManager
    DependencyInfo = dsm_module.DependencyInfo
    Vulnerability = dsm_module.Vulnerability
    SeverityLevel = dsm_module.SeverityLevel


def test_dependency_parsing():
    """Test parsing of requirements files"""
    print("Testing dependency parsing...")
    
    # Create a temporary requirements file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("""
# Test requirements file
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.2
# Comment line
redis==5.0.1
        """)
        temp_req_file = Path(f.name)
    
    try:
        # Create a temporary project structure
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            services_dir = project_root / "services" / "test-service"
            services_dir.mkdir(parents=True)
            
            # Copy requirements file to the service directory
            service_req_file = services_dir / "requirements.txt"
            service_req_file.write_text(temp_req_file.read_text())
            
            # Initialize the manager
            manager = DependencySecurityManager(project_root)
            
            # Test service discovery
            assert "test-service" in manager.services
            print("✅ Service discovery works")
            
            # Test dependency parsing
            dependencies = manager._parse_requirements(service_req_file)
            assert len(dependencies) == 4  # Should find 4 packages
            
            package_names = [dep.name for dep in dependencies]
            assert "fastapi" in package_names
            assert "uvicorn" in package_names
            assert "pydantic" in package_names
            assert "redis" in package_names
            print("✅ Dependency parsing works")
            
    finally:
        # Clean up
        temp_req_file.unlink()


def test_vulnerability_processing():
    """Test vulnerability data processing"""
    print("Testing vulnerability processing...")
    
    # Create mock vulnerability data
    vulnerabilities = [
        Vulnerability(
            id="VULN-001",
            package="test-package",
            installed_version="1.0.0",
            fixed_version="1.0.1",
            severity=SeverityLevel.HIGH,
            description="Test vulnerability",
            cve="CVE-2023-12345"
        ),
        Vulnerability(
            id="VULN-002", 
            package="another-package",
            installed_version="2.0.0",
            fixed_version=None,
            severity=SeverityLevel.CRITICAL,
            description="Critical test vulnerability"
        )
    ]
    
    # Test vulnerability counting
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)
        manager = DependencySecurityManager(project_root)
        
        counts = manager._count_vulnerabilities_by_severity(vulnerabilities)
        assert counts[SeverityLevel.CRITICAL] == 1
        assert counts[SeverityLevel.HIGH] == 1
        assert counts[SeverityLevel.MEDIUM] == 0
        assert counts[SeverityLevel.LOW] == 0
        print("✅ Vulnerability counting works")
        
        # Test recommendation generation
        recommendations = manager._generate_recommendations(vulnerabilities, [], [])
        assert len(recommendations) >= 2  # Should have critical and high recommendations
        print("✅ Recommendation generation works")


def test_configuration_loading():
    """Test configuration loading"""
    print("Testing configuration loading...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)
        
        # Create config directory structure
        config_dir = project_root / "config" / "security"
        config_dir.mkdir(parents=True)
        
        # Create a test config file
        config_file = config_dir / "dependency-security-config.yaml"
        config_file.write_text("""
vulnerability_scanners:
  safety:
    enabled: true
    severity_threshold: "high"
  pip_audit:
    enabled: false

license_compliance:
  allowed_licenses:
    - "MIT"
    - "Apache-2.0"
  forbidden_licenses:
    - "GPL-3.0"

update_policy:
  auto_update_security: true
        """)
        
        # Initialize manager and test config loading
        manager = DependencySecurityManager(project_root)
        
        assert manager.config["vulnerability_scanners"]["safety"]["enabled"] is True
        assert manager.config["vulnerability_scanners"]["pip_audit"]["enabled"] is False
        assert "MIT" in manager.config["license_compliance"]["allowed_licenses"]
        assert "GPL-3.0" in manager.config["license_compliance"]["forbidden_licenses"]
        print("✅ Configuration loading works")


def test_report_generation():
    """Test security report generation"""
    print("Testing report generation...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)
        manager = DependencySecurityManager(project_root)
        
        # Create mock report data
        try:
            from dependency_security_manager import SecurityReport
        except ImportError:
            SecurityReport = dsm_module.SecurityReport
        
        mock_vulnerabilities = [
            Vulnerability(
                id="TEST-001",
                package="test-pkg",
                installed_version="1.0.0",
                fixed_version="1.0.1",
                severity=SeverityLevel.HIGH,
                description="Test vulnerability"
            )
        ]
        
        mock_dependencies = [
            DependencyInfo(name="test-pkg", version="1.0.0", has_vulnerabilities=True)
        ]
        
        report = SecurityReport(
            timestamp="2024-01-01T00:00:00Z",
            service="test-service",
            total_dependencies=1,
            vulnerable_dependencies=1,
            outdated_dependencies=0,
            critical_vulnerabilities=0,
            high_vulnerabilities=1,
            medium_vulnerabilities=0,
            low_vulnerabilities=0,
            vulnerabilities=mock_vulnerabilities,
            dependencies=mock_dependencies,
            license_issues=[],
            recommendations=["Update test-pkg to 1.0.1"]
        )
        
        reports = {"test-service": report}
        
        # Test JSON report generation
        json_report = manager.generate_security_report(reports, "json")
        report_data = json.loads(json_report)
        assert "reports" in report_data
        assert "test-service" in report_data["reports"]
        print("✅ JSON report generation works")
        
        # Test Markdown report generation
        md_report = manager.generate_security_report(reports, "markdown")
        assert "# Dependency Security Report" in md_report
        assert "test-service" in md_report.lower()
        print("✅ Markdown report generation works")


def main():
    """Run all tests"""
    print("🔒 Testing Dependency Security Manager")
    print("=" * 50)
    
    try:
        test_configuration_loading()
        test_dependency_parsing()
        test_vulnerability_processing()
        test_report_generation()
        
        print("\n" + "=" * 50)
        print("✅ All tests passed! Dependency security system is working correctly.")
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())