#!/usr/bin/env python3
"""
License Compliance Checker

This script checks the licenses of all dependencies against the allowed/forbidden
license lists defined in the security configuration.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Set
import yaml
import re


class LicenseComplianceChecker:
    """Check license compliance for dependencies"""

    def __init__(self, config_path: Path):
        self.config = self._load_config(config_path)
        self.allowed_licenses = set(self.config["license_compliance"]["allowed_licenses"])
        self.forbidden_licenses = set(self.config["license_compliance"]["forbidden_licenses"])
        
        # Normalize license names for better matching
        self.allowed_licenses_normalized = {self._normalize_license(lic) for lic in self.allowed_licenses}
        self.forbidden_licenses_normalized = {self._normalize_license(lic) for lic in self.forbidden_licenses}

    def _load_config(self, config_path: Path) -> Dict[str, Any]:
        """Load security configuration"""
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    def _normalize_license(self, license_name: str) -> str:
        """Normalize license name for comparison"""
        if not license_name:
            return "unknown"
        
        # Convert to lowercase and remove common variations
        normalized = license_name.lower().strip()
        
        # Common license name mappings
        mappings = {
            "apache software license": "apache-2.0",
            "apache license": "apache-2.0",
            "apache 2.0": "apache-2.0",
            "apache-2.0 license": "apache-2.0",
            "bsd license": "bsd-3-clause",
            "bsd": "bsd-3-clause",
            "new bsd license": "bsd-3-clause",
            "modified bsd license": "bsd-3-clause",
            "mit license": "mit",
            "the mit license": "mit",
            "python software foundation license": "python software foundation license",
            "psf": "python software foundation license",
            "mozilla public license 2.0": "mozilla public license 2.0 (mpl 2.0)",
            "mpl-2.0": "mozilla public license 2.0 (mpl 2.0)",
            "gnu general public license v3": "gpl-3.0",
            "gpl v3": "gpl-3.0",
            "gnu general public license v2": "gpl-2.0",
            "gpl v2": "gpl-2.0",
            "gnu lesser general public license v3": "lgpl-3.0",
            "lgpl v3": "lgpl-3.0",
            "gnu affero general public license v3": "agpl-3.0",
            "agpl v3": "agpl-3.0"
        }
        
        return mappings.get(normalized, normalized)

    def check_license_compliance(self, license_reports: List[Path]) -> Dict[str, Any]:
        """Check license compliance across all services"""
        
        compliance_report = {
            "timestamp": self._get_timestamp(),
            "total_packages": 0,
            "compliant_packages": 0,
            "non_compliant_packages": 0,
            "unknown_license_packages": 0,
            "forbidden_license_packages": 0,
            "services": {},
            "violations": [],
            "summary": {
                "status": "compliant",
                "critical_issues": 0,
                "warnings": 0
            }
        }

        for report_path in license_reports:
            if not report_path.exists():
                continue
                
            service_name = self._extract_service_name(report_path)
            service_compliance = self._check_service_compliance(report_path)
            
            compliance_report["services"][service_name] = service_compliance
            compliance_report["total_packages"] += service_compliance["total_packages"]
            compliance_report["compliant_packages"] += service_compliance["compliant_packages"]
            compliance_report["non_compliant_packages"] += service_compliance["non_compliant_packages"]
            compliance_report["unknown_license_packages"] += service_compliance["unknown_license_packages"]
            compliance_report["forbidden_license_packages"] += service_compliance["forbidden_license_packages"]
            
            # Collect violations
            compliance_report["violations"].extend(service_compliance["violations"])

        # Determine overall compliance status
        if compliance_report["forbidden_license_packages"] > 0:
            compliance_report["summary"]["status"] = "non_compliant"
            compliance_report["summary"]["critical_issues"] = compliance_report["forbidden_license_packages"]
        elif compliance_report["unknown_license_packages"] > 0:
            compliance_report["summary"]["status"] = "warnings"
            compliance_report["summary"]["warnings"] = compliance_report["unknown_license_packages"]

        return compliance_report

    def _extract_service_name(self, report_path: Path) -> str:
        """Extract service name from report file path"""
        # Extract from filename like "license-report-orchestrator.json"
        filename = report_path.name
        if filename.startswith("license-report-") and filename.endswith(".json"):
            return filename[15:-5]  # Remove "license-report-" and ".json"
        return filename.stem

    def _check_service_compliance(self, report_path: Path) -> Dict[str, Any]:
        """Check license compliance for a single service"""
        
        service_compliance = {
            "total_packages": 0,
            "compliant_packages": 0,
            "non_compliant_packages": 0,
            "unknown_license_packages": 0,
            "forbidden_license_packages": 0,
            "violations": [],
            "packages": []
        }

        try:
            with open(report_path, 'r') as f:
                license_data = json.load(f)

            for package_info in license_data:
                package_name = package_info.get("Name", "unknown")
                license_name = package_info.get("License", "Unknown")
                version = package_info.get("Version", "unknown")
                
                service_compliance["total_packages"] += 1
                
                package_compliance = self._check_package_license(
                    package_name, license_name, version
                )
                
                service_compliance["packages"].append({
                    "name": package_name,
                    "version": version,
                    "license": license_name,
                    "status": package_compliance["status"],
                    "issue": package_compliance.get("issue")
                })

                if package_compliance["status"] == "compliant":
                    service_compliance["compliant_packages"] += 1
                elif package_compliance["status"] == "forbidden":
                    service_compliance["forbidden_license_packages"] += 1
                    service_compliance["non_compliant_packages"] += 1
                    service_compliance["violations"].append({
                        "package": package_name,
                        "version": version,
                        "license": license_name,
                        "severity": "critical",
                        "issue": "forbidden_license",
                        "description": f"Package {package_name} uses forbidden license: {license_name}"
                    })
                elif package_compliance["status"] == "unknown":
                    service_compliance["unknown_license_packages"] += 1
                    service_compliance["violations"].append({
                        "package": package_name,
                        "version": version,
                        "license": license_name,
                        "severity": "warning",
                        "issue": "unknown_license",
                        "description": f"Package {package_name} has unknown/unverified license: {license_name}"
                    })

        except Exception as e:
            print(f"Error processing {report_path}: {e}")

        return service_compliance

    def _check_package_license(self, package_name: str, license_name: str, version: str) -> Dict[str, Any]:
        """Check if a package's license is compliant"""
        
        normalized_license = self._normalize_license(license_name)
        
        # Check if license is forbidden
        if self._is_forbidden_license(normalized_license, license_name):
            return {
                "status": "forbidden",
                "issue": "forbidden_license"
            }
        
        # Check if license is allowed
        if self._is_allowed_license(normalized_license, license_name):
            return {
                "status": "compliant"
            }
        
        # License is unknown or not in allowed list
        return {
            "status": "unknown",
            "issue": "unknown_license"
        }

    def _is_forbidden_license(self, normalized_license: str, original_license: str) -> bool:
        """Check if license is in forbidden list"""
        # Check exact match
        if normalized_license in self.forbidden_licenses_normalized:
            return True
        
        # Check if any forbidden license is contained in the license name
        for forbidden in self.forbidden_licenses_normalized:
            if forbidden in normalized_license or forbidden in original_license.lower():
                return True
        
        return False

    def _is_allowed_license(self, normalized_license: str, original_license: str) -> bool:
        """Check if license is in allowed list"""
        # Check exact match
        if normalized_license in self.allowed_licenses_normalized:
            return True
        
        # Check if any allowed license is contained in the license name
        for allowed in self.allowed_licenses_normalized:
            if allowed in normalized_license or allowed in original_license.lower():
                return True
        
        return False

    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.utcnow().isoformat()

    def generate_compliance_report(self, compliance_data: Dict[str, Any], 
                                 output_format: str = "json") -> str:
        """Generate compliance report in specified format"""
        
        if output_format == "json":
            return json.dumps(compliance_data, indent=2)
        
        elif output_format == "markdown":
            return self._generate_markdown_report(compliance_data)
        
        elif output_format == "html":
            return self._generate_html_report(compliance_data)
        
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

    def _generate_markdown_report(self, compliance_data: Dict[str, Any]) -> str:
        """Generate markdown compliance report"""
        
        md_lines = [
            "# License Compliance Report",
            f"Generated: {compliance_data['timestamp']}",
            ""
        ]

        # Summary
        summary = compliance_data["summary"]
        status_emoji = "✅" if summary["status"] == "compliant" else "⚠️" if summary["status"] == "warnings" else "❌"
        
        md_lines.extend([
            "## Executive Summary",
            f"{status_emoji} **Status**: {summary['status'].title()}",
            f"- **Total Packages**: {compliance_data['total_packages']}",
            f"- **Compliant Packages**: {compliance_data['compliant_packages']}",
            f"- **Non-Compliant Packages**: {compliance_data['non_compliant_packages']}",
            f"- **Unknown License Packages**: {compliance_data['unknown_license_packages']}",
            f"- **Forbidden License Packages**: {compliance_data['forbidden_license_packages']}",
            ""
        ])

        # Violations
        if compliance_data["violations"]:
            md_lines.extend([
                "## License Violations",
                ""
            ])
            
            critical_violations = [v for v in compliance_data["violations"] if v["severity"] == "critical"]
            warning_violations = [v for v in compliance_data["violations"] if v["severity"] == "warning"]
            
            if critical_violations:
                md_lines.extend([
                    "### Critical Violations (Forbidden Licenses)",
                    ""
                ])
                for violation in critical_violations:
                    md_lines.append(
                        f"- **{violation['package']}** ({violation['version']}): "
                        f"{violation['license']} - {violation['description']}"
                    )
                md_lines.append("")
            
            if warning_violations:
                md_lines.extend([
                    "### Warnings (Unknown Licenses)",
                    ""
                ])
                for violation in warning_violations:
                    md_lines.append(
                        f"- **{violation['package']}** ({violation['version']}): "
                        f"{violation['license']} - {violation['description']}"
                    )
                md_lines.append("")

        # Service details
        md_lines.extend([
            "## Service Details",
            ""
        ])
        
        for service_name, service_data in compliance_data["services"].items():
            status_emoji = "✅" if service_data["forbidden_license_packages"] == 0 else "❌"
            md_lines.extend([
                f"### {status_emoji} {service_name.title()}",
                f"- **Total Packages**: {service_data['total_packages']}",
                f"- **Compliant**: {service_data['compliant_packages']}",
                f"- **Non-Compliant**: {service_data['non_compliant_packages']}",
                f"- **Unknown License**: {service_data['unknown_license_packages']}",
                f"- **Forbidden License**: {service_data['forbidden_license_packages']}",
                ""
            ])

        # Recommendations
        md_lines.extend([
            "## Recommendations",
            ""
        ])
        
        if compliance_data["forbidden_license_packages"] > 0:
            md_lines.append("🚨 **CRITICAL**: Replace packages with forbidden licenses immediately.")
        
        if compliance_data["unknown_license_packages"] > 0:
            md_lines.append("⚠️ **WARNING**: Review packages with unknown licenses and verify compliance.")
        
        if compliance_data["forbidden_license_packages"] == 0 and compliance_data["unknown_license_packages"] == 0:
            md_lines.append("✅ **GOOD**: All packages have compliant licenses.")

        return "\n".join(md_lines)

    def _generate_html_report(self, compliance_data: Dict[str, Any]) -> str:
        """Generate HTML compliance report"""
        
        status = compliance_data["summary"]["status"]
        status_color = "#4caf50" if status == "compliant" else "#ff9800" if status == "warnings" else "#f44336"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>License Compliance Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .status {{ padding: 10px; border-radius: 5px; color: white; background-color: {status_color}; }}
                .critical {{ color: #d32f2f; }}
                .warning {{ color: #f57c00; }}
                .compliant {{ color: #388e3c; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .violation {{ background-color: #ffebee; }}
            </style>
        </head>
        <body>
            <h1>License Compliance Report</h1>
            <p>Generated: {compliance_data['timestamp']}</p>
            
            <div class="status">
                <h2>Status: {status.title()}</h2>
            </div>
            
            <h2>Summary</h2>
            <ul>
                <li>Total Packages: {compliance_data['total_packages']}</li>
                <li>Compliant Packages: {compliance_data['compliant_packages']}</li>
                <li>Non-Compliant Packages: {compliance_data['non_compliant_packages']}</li>
                <li>Unknown License Packages: {compliance_data['unknown_license_packages']}</li>
                <li>Forbidden License Packages: {compliance_data['forbidden_license_packages']}</li>
            </ul>
        """
        
        # Add violations table if any
        if compliance_data["violations"]:
            html += """
            <h2>License Violations</h2>
            <table>
                <tr>
                    <th>Package</th>
                    <th>Version</th>
                    <th>License</th>
                    <th>Severity</th>
                    <th>Description</th>
                </tr>
            """
            
            for violation in compliance_data["violations"]:
                severity_class = "critical" if violation["severity"] == "critical" else "warning"
                html += f"""
                <tr class="violation">
                    <td>{violation['package']}</td>
                    <td>{violation['version']}</td>
                    <td>{violation['license']}</td>
                    <td class="{severity_class}">{violation['severity'].upper()}</td>
                    <td>{violation['description']}</td>
                </tr>
                """
            
            html += "</table>"
        
        html += """
        </body>
        </html>
        """
        
        return html


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description="Check license compliance for dependencies")
    parser.add_argument("--config", required=True, help="Security configuration file")
    parser.add_argument("--reports", nargs="+", required=True, help="License report files")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--format", choices=["json", "markdown", "html"], default="json")
    parser.add_argument("--fail-on-forbidden", action="store_true", 
                       help="Exit with error code if forbidden licenses found")

    args = parser.parse_args()

    try:
        # Initialize checker
        checker = LicenseComplianceChecker(Path(args.config))
        
        # Check compliance
        report_paths = [Path(report) for report in args.reports]
        compliance_data = checker.check_license_compliance(report_paths)
        
        # Generate report
        report_output = checker.generate_compliance_report(compliance_data, args.format)
        
        # Output report
        if args.output:
            with open(args.output, 'w') as f:
                f.write(report_output)
            print(f"License compliance report saved to {args.output}")
        else:
            print(report_output)

        # Exit with error if forbidden licenses found and flag is set
        if args.fail_on_forbidden and compliance_data["forbidden_license_packages"] > 0:
            print(f"ERROR: {compliance_data['forbidden_license_packages']} packages with forbidden licenses found!")
            sys.exit(1)

        # Exit with warning code if unknown licenses found
        if compliance_data["unknown_license_packages"] > 0:
            print(f"WARNING: {compliance_data['unknown_license_packages']} packages with unknown licenses found.")
            # Don't exit with error for unknown licenses, just warn

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()