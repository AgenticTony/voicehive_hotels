#!/usr/bin/env python3
"""
Security Dashboard Generator

Generates comprehensive security dashboards from vulnerability and license reports.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import glob


class SecurityDashboardGenerator:
    """Generate comprehensive security dashboards"""

    def __init__(self):
        self.dashboard_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {},
            "services": {},
            "trends": {},
            "recommendations": []
        }

    def generate_dashboard(self, vulnerability_reports: List[Path], 
                         license_reports: Optional[List[Path]] = None) -> Dict[str, Any]:
        """Generate comprehensive security dashboard"""
        
        # Process vulnerability reports
        vuln_summary = self._process_vulnerability_reports(vulnerability_reports)
        
        # Process license reports if provided
        license_summary = {}
        if license_reports:
            license_summary = self._process_license_reports(license_reports)

        # Generate overall summary
        self.dashboard_data["summary"] = self._generate_summary(vuln_summary, license_summary)
        
        # Generate service-level data
        self.dashboard_data["services"] = self._generate_service_data(vuln_summary, license_summary)
        
        # Generate trends (if historical data available)
        self.dashboard_data["trends"] = self._generate_trends()
        
        # Generate recommendations
        self.dashboard_data["recommendations"] = self._generate_recommendations(vuln_summary, license_summary)

        return self.dashboard_data

    def _process_vulnerability_reports(self, report_paths: List[Path]) -> Dict[str, Any]:
        """Process vulnerability reports"""
        
        vuln_summary = {
            "total_services": 0,
            "total_dependencies": 0,
            "total_vulnerabilities": 0,
            "critical_vulnerabilities": 0,
            "high_vulnerabilities": 0,
            "medium_vulnerabilities": 0,
            "low_vulnerabilities": 0,
            "services": {},
            "top_vulnerable_packages": {},
            "vulnerability_trends": []
        }

        for report_path in report_paths:
            if not report_path.exists():
                continue

            try:
                with open(report_path, 'r') as f:
                    report_data = json.load(f)

                # Extract service name from filename or report
                service_name = self._extract_service_name_from_vuln_report(report_path, report_data)
                
                if "reports" in report_data:
                    for svc_name, svc_report in report_data["reports"].items():
                        self._process_service_vulnerability_report(svc_name, svc_report, vuln_summary)
                else:
                    # Single service report
                    self._process_service_vulnerability_report(service_name, report_data, vuln_summary)

            except Exception as e:
                print(f"Error processing vulnerability report {report_path}: {e}")

        # Calculate top vulnerable packages
        vuln_summary["top_vulnerable_packages"] = self._calculate_top_vulnerable_packages(vuln_summary)

        return vuln_summary

    def _process_service_vulnerability_report(self, service_name: str, 
                                            service_report: Dict[str, Any], 
                                            vuln_summary: Dict[str, Any]):
        """Process a single service vulnerability report"""
        
        vuln_summary["total_services"] += 1
        vuln_summary["total_dependencies"] += service_report.get("total_dependencies", 0)
        vuln_summary["total_vulnerabilities"] += len(service_report.get("vulnerabilities", []))
        vuln_summary["critical_vulnerabilities"] += service_report.get("critical_vulnerabilities", 0)
        vuln_summary["high_vulnerabilities"] += service_report.get("high_vulnerabilities", 0)
        vuln_summary["medium_vulnerabilities"] += service_report.get("medium_vulnerabilities", 0)
        vuln_summary["low_vulnerabilities"] += service_report.get("low_vulnerabilities", 0)

        # Store service-specific data
        vuln_summary["services"][service_name] = {
            "total_dependencies": service_report.get("total_dependencies", 0),
            "vulnerable_dependencies": service_report.get("vulnerable_dependencies", 0),
            "outdated_dependencies": service_report.get("outdated_dependencies", 0),
            "vulnerabilities": service_report.get("vulnerabilities", []),
            "critical_count": service_report.get("critical_vulnerabilities", 0),
            "high_count": service_report.get("high_vulnerabilities", 0),
            "medium_count": service_report.get("medium_vulnerabilities", 0),
            "low_count": service_report.get("low_vulnerabilities", 0),
            "risk_score": self._calculate_risk_score(service_report)
        }

    def _process_license_reports(self, report_paths: List[Path]) -> Dict[str, Any]:
        """Process license compliance reports"""
        
        license_summary = {
            "total_packages": 0,
            "compliant_packages": 0,
            "non_compliant_packages": 0,
            "unknown_license_packages": 0,
            "forbidden_license_packages": 0,
            "services": {},
            "license_distribution": {},
            "violations": []
        }

        for report_path in report_paths:
            if not report_path.exists():
                continue

            try:
                with open(report_path, 'r') as f:
                    report_data = json.load(f)

                license_summary["total_packages"] += report_data.get("total_packages", 0)
                license_summary["compliant_packages"] += report_data.get("compliant_packages", 0)
                license_summary["non_compliant_packages"] += report_data.get("non_compliant_packages", 0)
                license_summary["unknown_license_packages"] += report_data.get("unknown_license_packages", 0)
                license_summary["forbidden_license_packages"] += report_data.get("forbidden_license_packages", 0)

                # Merge service data
                for service_name, service_data in report_data.get("services", {}).items():
                    license_summary["services"][service_name] = service_data

                # Collect violations
                license_summary["violations"].extend(report_data.get("violations", []))

            except Exception as e:
                print(f"Error processing license report {report_path}: {e}")

        # Calculate license distribution
        license_summary["license_distribution"] = self._calculate_license_distribution(license_summary)

        return license_summary

    def _extract_service_name_from_vuln_report(self, report_path: Path, report_data: Dict[str, Any]) -> str:
        """Extract service name from vulnerability report"""
        # Try to get from filename
        filename = report_path.name
        if "vulnerability-report-" in filename:
            return filename.replace("vulnerability-report-", "").replace(".json", "")
        
        # Try to get from report data
        if "reports" in report_data and len(report_data["reports"]) == 1:
            return list(report_data["reports"].keys())[0]
        
        return "unknown"

    def _calculate_risk_score(self, service_report: Dict[str, Any]) -> float:
        """Calculate risk score for a service based on vulnerabilities"""
        critical = service_report.get("critical_vulnerabilities", 0)
        high = service_report.get("high_vulnerabilities", 0)
        medium = service_report.get("medium_vulnerabilities", 0)
        low = service_report.get("low_vulnerabilities", 0)
        
        # Weighted risk score (0-100)
        risk_score = (critical * 10) + (high * 7) + (medium * 4) + (low * 1)
        
        # Normalize to 0-100 scale (assuming max reasonable vulnerabilities)
        max_score = 100  # Adjust based on your scale
        return min(risk_score, max_score)

    def _calculate_top_vulnerable_packages(self, vuln_summary: Dict[str, Any]) -> Dict[str, int]:
        """Calculate top vulnerable packages across all services"""
        package_vuln_count = {}
        
        for service_data in vuln_summary["services"].values():
            for vuln in service_data["vulnerabilities"]:
                package = vuln.get("package", "unknown")
                package_vuln_count[package] = package_vuln_count.get(package, 0) + 1
        
        # Return top 10 most vulnerable packages
        return dict(sorted(package_vuln_count.items(), key=lambda x: x[1], reverse=True)[:10])

    def _calculate_license_distribution(self, license_summary: Dict[str, Any]) -> Dict[str, int]:
        """Calculate license distribution across all packages"""
        license_count = {}
        
        for service_data in license_summary["services"].values():
            for package in service_data.get("packages", []):
                license_name = package.get("license", "Unknown")
                license_count[license_name] = license_count.get(license_name, 0) + 1
        
        return dict(sorted(license_count.items(), key=lambda x: x[1], reverse=True))

    def _generate_summary(self, vuln_summary: Dict[str, Any], license_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Generate overall security summary"""
        
        summary = {
            "overall_status": "unknown",
            "risk_level": "unknown",
            "total_services": vuln_summary.get("total_services", 0),
            "total_dependencies": vuln_summary.get("total_dependencies", 0),
            "security_score": 0,
            "compliance_score": 0,
            "key_metrics": {}
        }

        # Calculate security score (0-100, higher is better)
        total_vulns = vuln_summary.get("total_vulnerabilities", 0)
        critical_vulns = vuln_summary.get("critical_vulnerabilities", 0)
        high_vulns = vuln_summary.get("high_vulnerabilities", 0)
        
        if total_vulns == 0:
            summary["security_score"] = 100
        else:
            # Penalize critical and high vulnerabilities more heavily
            penalty = (critical_vulns * 20) + (high_vulns * 10) + (total_vulns * 2)
            summary["security_score"] = max(0, 100 - penalty)

        # Calculate compliance score
        if license_summary:
            total_packages = license_summary.get("total_packages", 1)
            forbidden_packages = license_summary.get("forbidden_license_packages", 0)
            unknown_packages = license_summary.get("unknown_license_packages", 0)
            
            if forbidden_packages > 0:
                summary["compliance_score"] = 0
            else:
                penalty = (unknown_packages / total_packages) * 30  # 30% penalty for unknown licenses
                summary["compliance_score"] = max(0, 100 - penalty)
        else:
            summary["compliance_score"] = 100  # No license issues if not checked

        # Determine overall status
        if critical_vulns > 0 or (license_summary and license_summary.get("forbidden_license_packages", 0) > 0):
            summary["overall_status"] = "critical"
            summary["risk_level"] = "high"
        elif high_vulns > 0 or (license_summary and license_summary.get("unknown_license_packages", 0) > 0):
            summary["overall_status"] = "warning"
            summary["risk_level"] = "medium"
        elif total_vulns > 0:
            summary["overall_status"] = "attention"
            summary["risk_level"] = "low"
        else:
            summary["overall_status"] = "secure"
            summary["risk_level"] = "low"

        # Key metrics
        summary["key_metrics"] = {
            "critical_vulnerabilities": critical_vulns,
            "high_vulnerabilities": high_vulns,
            "total_vulnerabilities": total_vulns,
            "vulnerable_services": len([s for s in vuln_summary["services"].values() if len(s["vulnerabilities"]) > 0]),
            "outdated_dependencies": sum(s.get("outdated_dependencies", 0) for s in vuln_summary["services"].values())
        }

        if license_summary:
            summary["key_metrics"].update({
                "forbidden_licenses": license_summary.get("forbidden_license_packages", 0),
                "unknown_licenses": license_summary.get("unknown_license_packages", 0),
                "license_compliance_rate": (license_summary.get("compliant_packages", 0) / max(license_summary.get("total_packages", 1), 1)) * 100
            })

        return summary

    def _generate_service_data(self, vuln_summary: Dict[str, Any], license_summary: Dict[str, Any]) -> Dict[str, Any]:
        """Generate service-level security data"""
        
        services = {}
        
        # Merge vulnerability and license data by service
        all_services = set(vuln_summary.get("services", {}).keys())
        if license_summary:
            all_services.update(license_summary.get("services", {}).keys())

        for service_name in all_services:
            vuln_data = vuln_summary.get("services", {}).get(service_name, {})
            license_data = license_summary.get("services", {}).get(service_name, {}) if license_summary else {}

            services[service_name] = {
                "name": service_name,
                "security": {
                    "total_dependencies": vuln_data.get("total_dependencies", 0),
                    "vulnerable_dependencies": vuln_data.get("vulnerable_dependencies", 0),
                    "outdated_dependencies": vuln_data.get("outdated_dependencies", 0),
                    "critical_vulnerabilities": vuln_data.get("critical_count", 0),
                    "high_vulnerabilities": vuln_data.get("high_count", 0),
                    "medium_vulnerabilities": vuln_data.get("medium_count", 0),
                    "low_vulnerabilities": vuln_data.get("low_count", 0),
                    "risk_score": vuln_data.get("risk_score", 0)
                },
                "compliance": {
                    "total_packages": license_data.get("total_packages", 0),
                    "compliant_packages": license_data.get("compliant_packages", 0),
                    "forbidden_packages": license_data.get("forbidden_license_packages", 0),
                    "unknown_packages": license_data.get("unknown_license_packages", 0),
                    "violations": license_data.get("violations", [])
                },
                "status": self._determine_service_status(vuln_data, license_data)
            }

        return services

    def _determine_service_status(self, vuln_data: Dict[str, Any], license_data: Dict[str, Any]) -> str:
        """Determine overall status for a service"""
        
        critical_vulns = vuln_data.get("critical_count", 0)
        high_vulns = vuln_data.get("high_count", 0)
        forbidden_licenses = license_data.get("forbidden_license_packages", 0)
        
        if critical_vulns > 0 or forbidden_licenses > 0:
            return "critical"
        elif high_vulns > 0 or license_data.get("unknown_license_packages", 0) > 0:
            return "warning"
        elif len(vuln_data.get("vulnerabilities", [])) > 0:
            return "attention"
        else:
            return "secure"

    def _generate_trends(self) -> Dict[str, Any]:
        """Generate trend analysis (placeholder for historical data)"""
        
        # This would analyze historical data if available
        # For now, return empty trends
        return {
            "vulnerability_trend": "stable",  # increasing, decreasing, stable
            "compliance_trend": "stable",
            "risk_trend": "stable",
            "historical_data": []
        }

    def _generate_recommendations(self, vuln_summary: Dict[str, Any], license_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate security recommendations"""
        
        recommendations = []

        # Critical vulnerability recommendations
        critical_count = vuln_summary.get("critical_vulnerabilities", 0)
        if critical_count > 0:
            recommendations.append({
                "priority": "critical",
                "category": "vulnerability",
                "title": f"Fix {critical_count} Critical Vulnerabilities",
                "description": "Critical vulnerabilities pose immediate security risks and should be fixed within 24 hours.",
                "action": "Update affected packages to fixed versions immediately."
            })

        # High vulnerability recommendations
        high_count = vuln_summary.get("high_vulnerabilities", 0)
        if high_count > 0:
            recommendations.append({
                "priority": "high",
                "category": "vulnerability", 
                "title": f"Address {high_count} High-Severity Vulnerabilities",
                "description": "High-severity vulnerabilities should be fixed within 7 days.",
                "action": "Schedule updates for affected packages in the next sprint."
            })

        # License compliance recommendations
        if license_summary:
            forbidden_count = license_summary.get("forbidden_license_packages", 0)
            if forbidden_count > 0:
                recommendations.append({
                    "priority": "critical",
                    "category": "compliance",
                    "title": f"Replace {forbidden_count} Packages with Forbidden Licenses",
                    "description": "Packages with forbidden licenses create legal compliance risks.",
                    "action": "Find alternative packages or negotiate license exceptions."
                })

            unknown_count = license_summary.get("unknown_license_packages", 0)
            if unknown_count > 0:
                recommendations.append({
                    "priority": "medium",
                    "category": "compliance",
                    "title": f"Review {unknown_count} Packages with Unknown Licenses",
                    "description": "Packages with unknown licenses need license verification.",
                    "action": "Research and document licenses for these packages."
                })

        # Outdated dependencies recommendation
        total_outdated = sum(s.get("outdated_dependencies", 0) for s in vuln_summary.get("services", {}).values())
        if total_outdated > 0:
            recommendations.append({
                "priority": "medium",
                "category": "maintenance",
                "title": f"Update {total_outdated} Outdated Dependencies",
                "description": "Outdated dependencies may contain unpatched vulnerabilities.",
                "action": "Review and update dependencies to latest stable versions."
            })

        # Security best practices
        if not recommendations:
            recommendations.append({
                "priority": "low",
                "category": "best_practice",
                "title": "Maintain Current Security Posture",
                "description": "Continue regular security scans and dependency updates.",
                "action": "Schedule regular security reviews and automated scanning."
            })

        return recommendations

    def generate_html_dashboard(self, dashboard_data: Dict[str, Any]) -> str:
        """Generate HTML dashboard"""
        
        summary = dashboard_data["summary"]
        services = dashboard_data["services"]
        recommendations = dashboard_data["recommendations"]

        # Status colors
        status_colors = {
            "secure": "#4caf50",
            "attention": "#ff9800", 
            "warning": "#ff5722",
            "critical": "#f44336"
        }

        status_color = status_colors.get(summary["overall_status"], "#9e9e9e")

        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>VoiceHive Security Dashboard</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background-color: #f5f5f5;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    background-color: white;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    overflow: hidden;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                .status-badge {{
                    display: inline-block;
                    padding: 8px 16px;
                    border-radius: 20px;
                    background-color: {status_color};
                    color: white;
                    font-weight: bold;
                    margin-top: 10px;
                }}
                .metrics-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                    padding: 30px;
                }}
                .metric-card {{
                    background: white;
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    padding: 20px;
                    text-align: center;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .metric-value {{
                    font-size: 2em;
                    font-weight: bold;
                    color: #333;
                }}
                .metric-label {{
                    color: #666;
                    margin-top: 5px;
                }}
                .services-section {{
                    padding: 30px;
                    border-top: 1px solid #e0e0e0;
                }}
                .service-card {{
                    border: 1px solid #e0e0e0;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    overflow: hidden;
                }}
                .service-header {{
                    padding: 15px 20px;
                    background-color: #f8f9fa;
                    border-bottom: 1px solid #e0e0e0;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }}
                .service-status {{
                    padding: 4px 12px;
                    border-radius: 12px;
                    color: white;
                    font-size: 0.8em;
                    font-weight: bold;
                }}
                .service-details {{
                    padding: 20px;
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 20px;
                }}
                .recommendations-section {{
                    padding: 30px;
                    border-top: 1px solid #e0e0e0;
                    background-color: #f8f9fa;
                }}
                .recommendation {{
                    background: white;
                    border-left: 4px solid #2196f3;
                    padding: 15px;
                    margin-bottom: 15px;
                    border-radius: 0 4px 4px 0;
                }}
                .recommendation.critical {{
                    border-left-color: #f44336;
                }}
                .recommendation.high {{
                    border-left-color: #ff5722;
                }}
                .recommendation.medium {{
                    border-left-color: #ff9800;
                }}
                .footer {{
                    padding: 20px;
                    text-align: center;
                    color: #666;
                    border-top: 1px solid #e0e0e0;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔒 VoiceHive Security Dashboard</h1>
                    <p>Generated: {dashboard_data['timestamp']}</p>
                    <div class="status-badge">{summary['overall_status'].title()}</div>
                </div>

                <div class="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-value">{summary['total_services']}</div>
                        <div class="metric-label">Services Scanned</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{summary['total_dependencies']}</div>
                        <div class="metric-label">Total Dependencies</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{summary['key_metrics'].get('critical_vulnerabilities', 0)}</div>
                        <div class="metric-label">Critical Vulnerabilities</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{summary['key_metrics'].get('high_vulnerabilities', 0)}</div>
                        <div class="metric-label">High Vulnerabilities</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{summary['security_score']:.0f}%</div>
                        <div class="metric-label">Security Score</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">{summary['compliance_score']:.0f}%</div>
                        <div class="metric-label">Compliance Score</div>
                    </div>
                </div>

                <div class="services-section">
                    <h2>Service Security Status</h2>
        """

        # Add service cards
        for service_name, service_data in services.items():
            service_status = service_data["status"]
            service_color = status_colors.get(service_status, "#9e9e9e")
            
            html += f"""
                    <div class="service-card">
                        <div class="service-header">
                            <h3>{service_name.title()}</h3>
                            <div class="service-status" style="background-color: {service_color};">
                                {service_status.title()}
                            </div>
                        </div>
                        <div class="service-details">
                            <div>
                                <h4>Security</h4>
                                <p>Dependencies: {service_data['security']['total_dependencies']}</p>
                                <p>Vulnerable: {service_data['security']['vulnerable_dependencies']}</p>
                                <p>Critical: {service_data['security']['critical_vulnerabilities']}</p>
                                <p>High: {service_data['security']['high_vulnerabilities']}</p>
                                <p>Risk Score: {service_data['security']['risk_score']:.1f}</p>
                            </div>
                            <div>
                                <h4>Compliance</h4>
                                <p>Total Packages: {service_data['compliance']['total_packages']}</p>
                                <p>Compliant: {service_data['compliance']['compliant_packages']}</p>
                                <p>Forbidden: {service_data['compliance']['forbidden_packages']}</p>
                                <p>Unknown: {service_data['compliance']['unknown_packages']}</p>
                            </div>
                        </div>
                    </div>
            """

        # Add recommendations
        html += f"""
                </div>

                <div class="recommendations-section">
                    <h2>Security Recommendations</h2>
        """

        for rec in recommendations:
            html += f"""
                    <div class="recommendation {rec['priority']}">
                        <h4>{rec['title']}</h4>
                        <p>{rec['description']}</p>
                        <p><strong>Action:</strong> {rec['action']}</p>
                    </div>
            """

        html += f"""
                </div>

                <div class="footer">
                    <p>VoiceHive Security Dashboard - Last updated: {dashboard_data['timestamp']}</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description="Generate security dashboard")
    parser.add_argument("--vulnerability-reports", nargs="+", help="Vulnerability report files (glob patterns supported)")
    parser.add_argument("--license-reports", nargs="+", help="License report files (glob patterns supported)")
    parser.add_argument("--output", required=True, help="Output file path")
    parser.add_argument("--format", choices=["json", "html"], default="html")

    args = parser.parse_args()

    try:
        generator = SecurityDashboardGenerator()

        # Expand glob patterns and collect report files
        vuln_reports = []
        if args.vulnerability_reports:
            for pattern in args.vulnerability_reports:
                vuln_reports.extend([Path(f) for f in glob.glob(pattern)])

        license_reports = []
        if args.license_reports:
            for pattern in args.license_reports:
                license_reports.extend([Path(f) for f in glob.glob(pattern)])

        # Generate dashboard
        dashboard_data = generator.generate_dashboard(vuln_reports, license_reports)

        # Generate output
        if args.format == "json":
            output = json.dumps(dashboard_data, indent=2)
        else:  # html
            output = generator.generate_html_dashboard(dashboard_data)

        # Write output
        with open(args.output, 'w') as f:
            f.write(output)

        print(f"Security dashboard generated: {args.output}")

        # Also save JSON data alongside HTML
        if args.format == "html":
            json_output = args.output.replace('.html', '.json')
            with open(json_output, 'w') as f:
                json.dump(dashboard_data, f, indent=2)
            print(f"Dashboard data saved: {json_output}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()