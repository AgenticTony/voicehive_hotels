#!/usr/bin/env python3
"""
Dependency Security & Vulnerability Management System

This script provides comprehensive dependency security management including:
- Automated vulnerability scanning with safety and pip-audit
- Dependency pinning with hash verification
- Security patch management workflow
- License compliance checking
- Security advisory monitoring

Usage:
    python dependency-security-manager.py scan --service orchestrator
    python dependency-security-manager.py update --service all --security-only
    python dependency-security-manager.py audit --format json
    python dependency-security-manager.py pin --service orchestrator --with-hashes
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
import tempfile
import hashlib
import re
from dataclasses import dataclass, asdict
from enum import Enum

import requests
import yaml
from packaging import version
from packaging.requirements import Requirement


class SeverityLevel(Enum):
    """Vulnerability severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Vulnerability:
    """Represents a security vulnerability"""
    id: str
    package: str
    installed_version: str
    fixed_version: Optional[str]
    severity: SeverityLevel
    description: str
    cve: Optional[str] = None
    advisory_url: Optional[str] = None
    published_date: Optional[str] = None


@dataclass
class DependencyInfo:
    """Information about a dependency"""
    name: str
    version: str
    latest_version: Optional[str] = None
    license: Optional[str] = None
    is_outdated: bool = False
    has_vulnerabilities: bool = False
    vulnerabilities: List[Vulnerability] = None
    hash_sha256: Optional[str] = None

    def __post_init__(self):
        if self.vulnerabilities is None:
            self.vulnerabilities = []


@dataclass
class SecurityReport:
    """Security scan report"""
    timestamp: str
    service: str
    total_dependencies: int
    vulnerable_dependencies: int
    outdated_dependencies: int
    critical_vulnerabilities: int
    high_vulnerabilities: int
    medium_vulnerabilities: int
    low_vulnerabilities: int
    vulnerabilities: List[Vulnerability]
    dependencies: List[DependencyInfo]
    license_issues: List[Dict[str, Any]]
    recommendations: List[str]


class DependencySecurityManager:
    """Main class for dependency security management"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.logger = self._setup_logging()
        self.services = self._discover_services()
        self.config = self._load_config()

    def _setup_logging(self) -> logging.Logger:
        """Setup structured logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)

    def _discover_services(self) -> Dict[str, Path]:
        """Discover all services with requirements files"""
        services = {}
        
        # Main services
        services_dir = self.project_root / "services"
        if services_dir.exists():
            for service_path in services_dir.iterdir():
                if service_path.is_dir():
                    req_file = service_path / "requirements.txt"
                    if req_file.exists():
                        services[service_path.name] = req_file

        # Connectors
        connectors_dir = self.project_root / "connectors"
        if connectors_dir.exists():
            req_file = connectors_dir / "requirements-test.txt"
            if req_file.exists():
                services["connectors"] = req_file

        # Tools
        tools_dir = self.project_root / "tools"
        if tools_dir.exists():
            req_file = tools_dir / "requirements-pii-scanner.txt"
            if req_file.exists():
                services["pii-scanner"] = req_file

        return services

    def _load_config(self) -> Dict[str, Any]:
        """Load security configuration"""
        config_file = self.project_root / "config" / "security" / "dependency-security-config.yaml"
        
        default_config = {
            "vulnerability_scanners": {
                "safety": {
                    "enabled": True,
                    "api_key": None,  # Set via environment variable
                    "ignore_ids": [],
                    "severity_threshold": "medium"
                },
                "pip_audit": {
                    "enabled": True,
                    "format": "json",
                    "severity_threshold": "medium"
                }
            },
            "license_compliance": {
                "allowed_licenses": [
                    "MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause",
                    "ISC", "Python Software Foundation License"
                ],
                "forbidden_licenses": [
                    "GPL-3.0", "AGPL-3.0", "LGPL-3.0"
                ],
                "require_license_check": True
            },
            "update_policy": {
                "auto_update_security": True,
                "auto_update_minor": False,
                "auto_update_major": False,
                "test_before_update": True
            },
            "hash_verification": {
                "enabled": True,
                "algorithm": "sha256",
                "require_hashes": True
            },
            "notifications": {
                "slack_webhook": None,  # Set via environment variable
                "email_recipients": [],
                "severity_threshold": "high"
            }
        }

        if config_file.exists():
            with open(config_file, 'r') as f:
                user_config = yaml.safe_load(f)
                default_config.update(user_config)

        return default_config

    async def scan_vulnerabilities(self, service: str = "all") -> Dict[str, SecurityReport]:
        """Scan for vulnerabilities in dependencies"""
        self.logger.info(f"Starting vulnerability scan for service: {service}")
        
        services_to_scan = [service] if service != "all" else list(self.services.keys())
        reports = {}

        for svc in services_to_scan:
            if svc not in self.services:
                self.logger.warning(f"Service {svc} not found")
                continue

            self.logger.info(f"Scanning {svc}...")
            report = await self._scan_service_vulnerabilities(svc)
            reports[svc] = report

        return reports

    async def _scan_service_vulnerabilities(self, service: str) -> SecurityReport:
        """Scan vulnerabilities for a specific service"""
        req_file = self.services[service]
        dependencies = self._parse_requirements(req_file)
        
        # Run safety scan
        safety_vulns = []
        if self.config["vulnerability_scanners"]["safety"]["enabled"]:
            safety_vulns = await self._run_safety_scan(req_file)

        # Run pip-audit scan
        pip_audit_vulns = []
        if self.config["vulnerability_scanners"]["pip_audit"]["enabled"]:
            pip_audit_vulns = await self._run_pip_audit_scan(req_file)

        # Combine and deduplicate vulnerabilities
        all_vulns = self._merge_vulnerabilities(safety_vulns, pip_audit_vulns)

        # Check for outdated packages
        outdated_deps = await self._check_outdated_packages(dependencies)

        # License compliance check
        license_issues = []
        if self.config["license_compliance"]["require_license_check"]:
            license_issues = await self._check_license_compliance(dependencies)

        # Generate recommendations
        recommendations = self._generate_recommendations(all_vulns, outdated_deps, license_issues)

        # Count vulnerabilities by severity
        vuln_counts = self._count_vulnerabilities_by_severity(all_vulns)

        return SecurityReport(
            timestamp=datetime.utcnow().isoformat(),
            service=service,
            total_dependencies=len(dependencies),
            vulnerable_dependencies=len([d for d in dependencies if d.has_vulnerabilities]),
            outdated_dependencies=len([d for d in dependencies if d.is_outdated]),
            critical_vulnerabilities=vuln_counts.get(SeverityLevel.CRITICAL, 0),
            high_vulnerabilities=vuln_counts.get(SeverityLevel.HIGH, 0),
            medium_vulnerabilities=vuln_counts.get(SeverityLevel.MEDIUM, 0),
            low_vulnerabilities=vuln_counts.get(SeverityLevel.LOW, 0),
            vulnerabilities=all_vulns,
            dependencies=dependencies,
            license_issues=license_issues,
            recommendations=recommendations
        )

    def _parse_requirements(self, req_file: Path) -> List[DependencyInfo]:
        """Parse requirements file and extract dependency information"""
        dependencies = []
        
        with open(req_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('-'):
                    try:
                        req = Requirement(line)
                        dep_info = DependencyInfo(
                            name=req.name,
                            version=str(req.specifier) if req.specifier else "latest"
                        )
                        dependencies.append(dep_info)
                    except Exception as e:
                        self.logger.warning(f"Failed to parse requirement: {line}, error: {e}")

        return dependencies

    async def _run_safety_scan(self, req_file: Path) -> List[Vulnerability]:
        """Run safety vulnerability scan"""
        try:
            cmd = ["safety", "check", "-r", str(req_file), "--json"]
            
            # Add API key if configured
            api_key = os.getenv("SAFETY_API_KEY") or self.config["vulnerability_scanners"]["safety"]["api_key"]
            if api_key:
                cmd.extend(["--key", api_key])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                return []  # No vulnerabilities found

            # Parse safety output
            vulnerabilities = []
            try:
                safety_data = json.loads(result.stdout)
                for vuln_data in safety_data:
                    vulnerability = Vulnerability(
                        id=vuln_data.get("id", ""),
                        package=vuln_data.get("package", ""),
                        installed_version=vuln_data.get("installed_version", ""),
                        fixed_version=vuln_data.get("fixed_version"),
                        severity=self._map_safety_severity(vuln_data.get("severity", "medium")),
                        description=vuln_data.get("advisory", ""),
                        cve=vuln_data.get("cve"),
                        advisory_url=vuln_data.get("more_info_url")
                    )
                    vulnerabilities.append(vulnerability)
            except json.JSONDecodeError:
                self.logger.error(f"Failed to parse safety output: {result.stdout}")

            return vulnerabilities

        except subprocess.TimeoutExpired:
            self.logger.error("Safety scan timed out")
            return []
        except Exception as e:
            self.logger.error(f"Safety scan failed: {e}")
            return []

    async def _run_pip_audit_scan(self, req_file: Path) -> List[Vulnerability]:
        """Run pip-audit vulnerability scan"""
        try:
            cmd = ["pip-audit", "-r", str(req_file), "--format", "json"]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            vulnerabilities = []
            if result.stdout:
                try:
                    audit_data = json.loads(result.stdout)
                    for vuln_data in audit_data.get("vulnerabilities", []):
                        vulnerability = Vulnerability(
                            id=vuln_data.get("id", ""),
                            package=vuln_data.get("package", ""),
                            installed_version=vuln_data.get("installed_version", ""),
                            fixed_version=vuln_data.get("fixed_version"),
                            severity=self._map_pip_audit_severity(vuln_data.get("severity", "medium")),
                            description=vuln_data.get("description", ""),
                            cve=vuln_data.get("cve"),
                            advisory_url=vuln_data.get("advisory_url")
                        )
                        vulnerabilities.append(vulnerability)
                except json.JSONDecodeError:
                    self.logger.error(f"Failed to parse pip-audit output: {result.stdout}")

            return vulnerabilities

        except subprocess.TimeoutExpired:
            self.logger.error("pip-audit scan timed out")
            return []
        except Exception as e:
            self.logger.error(f"pip-audit scan failed: {e}")
            return []

    def _map_safety_severity(self, severity: str) -> SeverityLevel:
        """Map safety severity to our enum"""
        severity_map = {
            "low": SeverityLevel.LOW,
            "medium": SeverityLevel.MEDIUM,
            "high": SeverityLevel.HIGH,
            "critical": SeverityLevel.CRITICAL
        }
        return severity_map.get(severity.lower(), SeverityLevel.MEDIUM)

    def _map_pip_audit_severity(self, severity: str) -> SeverityLevel:
        """Map pip-audit severity to our enum"""
        severity_map = {
            "low": SeverityLevel.LOW,
            "moderate": SeverityLevel.MEDIUM,
            "medium": SeverityLevel.MEDIUM,
            "high": SeverityLevel.HIGH,
            "critical": SeverityLevel.CRITICAL
        }
        return severity_map.get(severity.lower(), SeverityLevel.MEDIUM)

    def _merge_vulnerabilities(self, safety_vulns: List[Vulnerability], 
                             pip_audit_vulns: List[Vulnerability]) -> List[Vulnerability]:
        """Merge and deduplicate vulnerabilities from different scanners"""
        seen_vulns = set()
        merged_vulns = []

        for vuln in safety_vulns + pip_audit_vulns:
            # Create a unique key for deduplication
            key = f"{vuln.package}:{vuln.installed_version}:{vuln.id or vuln.cve}"
            if key not in seen_vulns:
                seen_vulns.add(key)
                merged_vulns.append(vuln)

        return merged_vulns

    async def _check_outdated_packages(self, dependencies: List[DependencyInfo]) -> List[DependencyInfo]:
        """Check for outdated packages"""
        outdated = []
        
        for dep in dependencies:
            try:
                # Get latest version from PyPI
                response = requests.get(f"https://pypi.org/pypi/{dep.name}/json", timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    latest_version = data["info"]["version"]
                    dep.latest_version = latest_version
                    
                    # Check if outdated (simplified version comparison)
                    if dep.version != "latest" and dep.version != latest_version:
                        try:
                            current_ver = version.parse(dep.version.replace("==", ""))
                            latest_ver = version.parse(latest_version)
                            if current_ver < latest_ver:
                                dep.is_outdated = True
                                outdated.append(dep)
                        except Exception:
                            # If version parsing fails, assume it might be outdated
                            dep.is_outdated = True
                            outdated.append(dep)
                            
            except Exception as e:
                self.logger.warning(f"Failed to check version for {dep.name}: {e}")

        return outdated

    async def _check_license_compliance(self, dependencies: List[DependencyInfo]) -> List[Dict[str, Any]]:
        """Check license compliance for dependencies"""
        license_issues = []
        allowed_licenses = self.config["license_compliance"]["allowed_licenses"]
        forbidden_licenses = self.config["license_compliance"]["forbidden_licenses"]

        for dep in dependencies:
            try:
                # Get license info from PyPI
                response = requests.get(f"https://pypi.org/pypi/{dep.name}/json", timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    license_info = data["info"].get("license", "Unknown")
                    dep.license = license_info

                    # Check against forbidden licenses
                    if any(forbidden in license_info for forbidden in forbidden_licenses):
                        license_issues.append({
                            "package": dep.name,
                            "license": license_info,
                            "issue": "forbidden_license",
                            "severity": "high"
                        })

                    # Check if license is in allowed list
                    elif not any(allowed in license_info for allowed in allowed_licenses):
                        license_issues.append({
                            "package": dep.name,
                            "license": license_info,
                            "issue": "unknown_license",
                            "severity": "medium"
                        })

            except Exception as e:
                self.logger.warning(f"Failed to check license for {dep.name}: {e}")
                license_issues.append({
                    "package": dep.name,
                    "license": "Unknown",
                    "issue": "license_check_failed",
                    "severity": "low"
                })

        return license_issues

    def _count_vulnerabilities_by_severity(self, vulnerabilities: List[Vulnerability]) -> Dict[SeverityLevel, int]:
        """Count vulnerabilities by severity level"""
        counts = {level: 0 for level in SeverityLevel}
        for vuln in vulnerabilities:
            counts[vuln.severity] += 1
        return counts

    def _generate_recommendations(self, vulnerabilities: List[Vulnerability],
                                outdated_deps: List[DependencyInfo],
                                license_issues: List[Dict[str, Any]]) -> List[str]:
        """Generate security recommendations"""
        recommendations = []

        # Critical vulnerability recommendations
        critical_vulns = [v for v in vulnerabilities if v.severity == SeverityLevel.CRITICAL]
        if critical_vulns:
            recommendations.append(
                f"URGENT: {len(critical_vulns)} critical vulnerabilities found. "
                "Update affected packages immediately."
            )

        # High severity recommendations
        high_vulns = [v for v in vulnerabilities if v.severity == SeverityLevel.HIGH]
        if high_vulns:
            recommendations.append(
                f"HIGH PRIORITY: {len(high_vulns)} high-severity vulnerabilities found. "
                "Schedule updates within 7 days."
            )

        # Outdated packages
        if outdated_deps:
            recommendations.append(
                f"UPDATE RECOMMENDED: {len(outdated_deps)} packages are outdated. "
                "Consider updating to latest versions."
            )

        # License issues
        forbidden_license_issues = [i for i in license_issues if i["issue"] == "forbidden_license"]
        if forbidden_license_issues:
            recommendations.append(
                f"LICENSE VIOLATION: {len(forbidden_license_issues)} packages have forbidden licenses. "
                "Review and replace these dependencies."
            )

        # Hash verification
        if self.config["hash_verification"]["enabled"]:
            recommendations.append(
                "Enable hash verification in requirements files for supply chain security."
            )

        return recommendations

    async def pin_dependencies_with_hashes(self, service: str = "all") -> Dict[str, bool]:
        """Pin dependencies with hash verification"""
        self.logger.info(f"Pinning dependencies with hashes for service: {service}")
        
        services_to_pin = [service] if service != "all" else list(self.services.keys())
        results = {}

        for svc in services_to_pin:
            if svc not in self.services:
                self.logger.warning(f"Service {svc} not found")
                results[svc] = False
                continue

            try:
                success = await self._pin_service_dependencies(svc)
                results[svc] = success
            except Exception as e:
                self.logger.error(f"Failed to pin dependencies for {svc}: {e}")
                results[svc] = False

        return results

    async def _pin_service_dependencies(self, service: str) -> bool:
        """Pin dependencies for a specific service with hash verification"""
        req_file = self.services[service]
        
        try:
            # Create a temporary requirements file with hashes
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
                temp_req_file = Path(temp_file.name)

            # Use pip-compile to generate hashed requirements
            cmd = [
                "pip-compile",
                "--generate-hashes",
                "--allow-unsafe",
                "--output-file", str(temp_req_file),
                str(req_file)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                # Backup original file
                backup_file = req_file.with_suffix('.txt.backup')
                req_file.rename(backup_file)
                
                # Move compiled file to original location
                temp_req_file.rename(req_file)
                
                self.logger.info(f"Successfully pinned dependencies for {service}")
                return True
            else:
                self.logger.error(f"pip-compile failed for {service}: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            self.logger.error(f"pip-compile timed out for {service}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to pin dependencies for {service}: {e}")
            return False
        finally:
            # Clean up temporary file if it exists
            if temp_req_file.exists():
                temp_req_file.unlink()

    async def update_dependencies(self, service: str = "all", security_only: bool = True) -> Dict[str, bool]:
        """Update dependencies with security patches"""
        self.logger.info(f"Updating dependencies for service: {service}, security_only: {security_only}")
        
        services_to_update = [service] if service != "all" else list(self.services.keys())
        results = {}

        for svc in services_to_update:
            if svc not in self.services:
                self.logger.warning(f"Service {svc} not found")
                results[svc] = False
                continue

            try:
                success = await self._update_service_dependencies(svc, security_only)
                results[svc] = success
            except Exception as e:
                self.logger.error(f"Failed to update dependencies for {svc}: {e}")
                results[svc] = False

        return results

    async def _update_service_dependencies(self, service: str, security_only: bool) -> bool:
        """Update dependencies for a specific service"""
        req_file = self.services[service]
        
        # First, scan for vulnerabilities to identify what needs updating
        report = await self._scan_service_vulnerabilities(service)
        
        if not report.vulnerabilities and security_only:
            self.logger.info(f"No security vulnerabilities found for {service}")
            return True

        # Create updated requirements
        updated_requirements = []
        
        with open(req_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('-'):
                    try:
                        req = Requirement(line)
                        
                        # Check if this package has vulnerabilities
                        package_vulns = [v for v in report.vulnerabilities if v.package == req.name]
                        
                        if package_vulns and security_only:
                            # Update to fixed version if available
                            fixed_versions = [v.fixed_version for v in package_vulns if v.fixed_version]
                            if fixed_versions:
                                # Use the highest fixed version
                                latest_fix = max(fixed_versions, key=lambda x: version.parse(x))
                                updated_line = f"{req.name}=={latest_fix}"
                                updated_requirements.append(updated_line)
                                self.logger.info(f"Updated {req.name} to {latest_fix} for security fix")
                            else:
                                updated_requirements.append(line)
                        else:
                            updated_requirements.append(line)
                    except Exception as e:
                        self.logger.warning(f"Failed to parse requirement: {line}, error: {e}")
                        updated_requirements.append(line)
                else:
                    updated_requirements.append(line)

        # Write updated requirements
        backup_file = req_file.with_suffix('.txt.backup')
        req_file.rename(backup_file)
        
        with open(req_file, 'w') as f:
            f.write('\n'.join(updated_requirements))

        self.logger.info(f"Updated dependencies for {service}")
        return True

    def generate_security_report(self, reports: Dict[str, SecurityReport], 
                               output_format: str = "json") -> str:
        """Generate comprehensive security report"""
        if output_format == "json":
            return json.dumps({
                "timestamp": datetime.utcnow().isoformat(),
                "reports": {svc: asdict(report) for svc, report in reports.items()}
            }, indent=2, default=str)
        
        elif output_format == "markdown":
            return self._generate_markdown_report(reports)
        
        elif output_format == "html":
            return self._generate_html_report(reports)
        
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

    def _generate_markdown_report(self, reports: Dict[str, SecurityReport]) -> str:
        """Generate markdown security report"""
        md_lines = [
            "# Dependency Security Report",
            f"Generated: {datetime.utcnow().isoformat()}",
            ""
        ]

        # Summary
        total_vulns = sum(len(report.vulnerabilities) for report in reports.values())
        total_critical = sum(report.critical_vulnerabilities for report in reports.values())
        total_high = sum(report.high_vulnerabilities for report in reports.values())

        md_lines.extend([
            "## Executive Summary",
            f"- **Total Services Scanned**: {len(reports)}",
            f"- **Total Vulnerabilities**: {total_vulns}",
            f"- **Critical Vulnerabilities**: {total_critical}",
            f"- **High Vulnerabilities**: {total_high}",
            ""
        ])

        # Service details
        for service, report in reports.items():
            md_lines.extend([
                f"## {service.title()} Service",
                f"- **Dependencies**: {report.total_dependencies}",
                f"- **Vulnerable Dependencies**: {report.vulnerable_dependencies}",
                f"- **Outdated Dependencies**: {report.outdated_dependencies}",
                ""
            ])

            if report.vulnerabilities:
                md_lines.append("### Vulnerabilities")
                for vuln in report.vulnerabilities:
                    md_lines.append(
                        f"- **{vuln.id}** ({vuln.severity.value.upper()}): "
                        f"{vuln.package} {vuln.installed_version} - {vuln.description[:100]}..."
                    )
                md_lines.append("")

            if report.recommendations:
                md_lines.append("### Recommendations")
                for rec in report.recommendations:
                    md_lines.append(f"- {rec}")
                md_lines.append("")

        return "\n".join(md_lines)

    def _generate_html_report(self, reports: Dict[str, SecurityReport]) -> str:
        """Generate HTML security report"""
        # This would generate a comprehensive HTML report
        # For brevity, returning a simple HTML structure
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Dependency Security Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .critical {{ color: #d32f2f; }}
                .high {{ color: #f57c00; }}
                .medium {{ color: #fbc02d; }}
                .low {{ color: #388e3c; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h1>Dependency Security Report</h1>
            <p>Generated: {datetime.utcnow().isoformat()}</p>
            
            <h2>Summary</h2>
            <ul>
                <li>Total Services: {len(reports)}</li>
                <li>Total Vulnerabilities: {sum(len(r.vulnerabilities) for r in reports.values())}</li>
            </ul>
            
            <!-- Service details would be generated here -->
        </body>
        </html>
        """
        return html


async def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description="Dependency Security & Vulnerability Management")
    parser.add_argument("command", choices=["scan", "update", "pin", "audit", "report"])
    parser.add_argument("--service", default="all", help="Service to operate on")
    parser.add_argument("--security-only", action="store_true", help="Only security updates")
    parser.add_argument("--with-hashes", action="store_true", help="Include hash verification")
    parser.add_argument("--format", choices=["json", "markdown", "html"], default="json")
    parser.add_argument("--output", help="Output file path")

    args = parser.parse_args()

    # Find project root
    current_dir = Path.cwd()
    project_root = current_dir
    while project_root.parent != project_root:
        if (project_root / "services").exists() or (project_root / "connectors").exists():
            break
        project_root = project_root.parent

    manager = DependencySecurityManager(project_root)

    try:
        if args.command == "scan":
            reports = await manager.scan_vulnerabilities(args.service)
            output = manager.generate_security_report(reports, args.format)
            
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(output)
                print(f"Report saved to {args.output}")
            else:
                print(output)

        elif args.command == "update":
            results = await manager.update_dependencies(args.service, args.security_only)
            print(json.dumps(results, indent=2))

        elif args.command == "pin":
            results = await manager.pin_dependencies_with_hashes(args.service)
            print(json.dumps(results, indent=2))

        elif args.command == "audit":
            reports = await manager.scan_vulnerabilities(args.service)
            # Return non-zero exit code if critical vulnerabilities found
            critical_count = sum(r.critical_vulnerabilities for r in reports.values())
            if critical_count > 0:
                print(f"CRITICAL: {critical_count} critical vulnerabilities found!")
                sys.exit(1)
            else:
                print("No critical vulnerabilities found.")

        elif args.command == "report":
            reports = await manager.scan_vulnerabilities(args.service)
            output = manager.generate_security_report(reports, args.format)
            
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(output)
                print(f"Report saved to {args.output}")
            else:
                print(output)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())