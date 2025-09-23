#!/usr/bin/env python3
"""
Convert vulnerability scan results to SARIF format for GitHub Security integration

SARIF (Static Analysis Results Interchange Format) is the standard format
for security scan results that can be uploaded to GitHub Security tab.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
from urllib.parse import urljoin


class SarifConverter:
    """Convert vulnerability reports to SARIF format"""

    def __init__(self):
        self.sarif_version = "2.1.0"
        self.tool_name = "VoiceHive Dependency Security Scanner"
        self.tool_version = "1.0.0"

    def convert_vulnerability_report(self, report_data: Dict[str, Any], service: str) -> Dict[str, Any]:
        """Convert vulnerability report to SARIF format"""
        
        # Extract service report
        service_report = report_data.get("reports", {}).get(service, {})
        vulnerabilities = service_report.get("vulnerabilities", [])
        
        # Create SARIF structure
        sarif_report = {
            "version": self.sarif_version,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": self.tool_name,
                            "version": self.tool_version,
                            "informationUri": "https://github.com/voicehive/voicehive-hotels",
                            "rules": self._create_rules(vulnerabilities),
                            "notifications": []
                        }
                    },
                    "results": self._create_results(vulnerabilities, service),
                    "columnKind": "utf16CodeUnits",
                    "properties": {
                        "service": service,
                        "scanTimestamp": service_report.get("timestamp", datetime.utcnow().isoformat()),
                        "totalDependencies": service_report.get("total_dependencies", 0),
                        "vulnerableDependencies": service_report.get("vulnerable_dependencies", 0)
                    }
                }
            ]
        }

        return sarif_report

    def _create_rules(self, vulnerabilities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create SARIF rules from vulnerabilities"""
        rules = []
        seen_rules = set()

        for vuln in vulnerabilities:
            rule_id = vuln.get("id", "unknown")
            if rule_id in seen_rules:
                continue
            
            seen_rules.add(rule_id)
            
            severity = vuln.get("severity", "medium")
            
            rule = {
                "id": rule_id,
                "name": f"Vulnerability {rule_id}",
                "shortDescription": {
                    "text": f"Security vulnerability in {vuln.get('package', 'unknown package')}"
                },
                "fullDescription": {
                    "text": vuln.get("description", "No description available")
                },
                "help": {
                    "text": self._create_help_text(vuln),
                    "markdown": self._create_help_markdown(vuln)
                },
                "properties": {
                    "tags": ["security", "vulnerability", "dependency"],
                    "precision": "high",
                    "security-severity": self._map_severity_to_score(severity)
                },
                "defaultConfiguration": {
                    "level": self._map_severity_to_level(severity)
                }
            }

            # Add CVE information if available
            if vuln.get("cve"):
                rule["properties"]["cve"] = vuln["cve"]
                rule["help"]["text"] += f"\n\nCVE: {vuln['cve']}"

            # Add advisory URL if available
            if vuln.get("advisory_url"):
                rule["helpUri"] = vuln["advisory_url"]

            rules.append(rule)

        return rules

    def _create_results(self, vulnerabilities: List[Dict[str, Any]], service: str) -> List[Dict[str, Any]]:
        """Create SARIF results from vulnerabilities"""
        results = []

        for vuln in vulnerabilities:
            rule_id = vuln.get("id", "unknown")
            package = vuln.get("package", "unknown")
            installed_version = vuln.get("installed_version", "unknown")
            fixed_version = vuln.get("fixed_version")
            severity = vuln.get("severity", "medium")

            # Determine the file location (requirements file)
            artifact_location = self._get_requirements_file_location(service)

            result = {
                "ruleId": rule_id,
                "ruleIndex": 0,  # Will be updated when we have the actual rule index
                "message": {
                    "text": f"Vulnerable dependency: {package} {installed_version}",
                    "markdown": self._create_result_markdown(vuln)
                },
                "level": self._map_severity_to_level(severity),
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": artifact_location,
                                "uriBaseId": "%SRCROOT%"
                            },
                            "region": {
                                "startLine": 1,  # We don't have exact line numbers
                                "startColumn": 1,
                                "endLine": 1,
                                "endColumn": 1
                            }
                        }
                    }
                ],
                "properties": {
                    "package": package,
                    "installedVersion": installed_version,
                    "fixedVersion": fixed_version,
                    "severity": severity,
                    "service": service
                }
            }

            # Add fingerprint for result deduplication
            result["fingerprints"] = {
                "primary": self._create_fingerprint(vuln, service)
            }

            # Add fix suggestion if available
            if fixed_version:
                result["fixes"] = [
                    {
                        "description": {
                            "text": f"Update {package} to version {fixed_version}",
                            "markdown": f"Update `{package}` to version `{fixed_version}` to fix this vulnerability."
                        },
                        "artifactChanges": [
                            {
                                "artifactLocation": {
                                    "uri": artifact_location,
                                    "uriBaseId": "%SRCROOT%"
                                },
                                "replacements": [
                                    {
                                        "deletedRegion": {
                                            "startLine": 1,
                                            "startColumn": 1,
                                            "endLine": 1,
                                            "endColumn": 1
                                        },
                                        "insertedContent": {
                                            "text": f"{package}=={fixed_version}"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]

            results.append(result)

        return results

    def _get_requirements_file_location(self, service: str) -> str:
        """Get the requirements file location for a service"""
        service_file_map = {
            "orchestrator": "services/orchestrator/requirements.txt",
            "connectors": "connectors/requirements-test.txt",
            "riva-proxy": "services/asr/riva-proxy/requirements.txt",
            "tts-router": "services/tts/router/requirements.txt",
            "media-agent": "services/media/livekit-agent/requirements.txt",
            "pii-scanner": "tools/requirements-pii-scanner.txt"
        }
        return service_file_map.get(service, f"services/{service}/requirements.txt")

    def _create_help_text(self, vuln: Dict[str, Any]) -> str:
        """Create help text for vulnerability"""
        package = vuln.get("package", "unknown")
        installed_version = vuln.get("installed_version", "unknown")
        fixed_version = vuln.get("fixed_version")
        description = vuln.get("description", "No description available")

        help_text = f"Vulnerability found in {package} version {installed_version}.\n\n"
        help_text += f"Description: {description}\n\n"
        
        if fixed_version:
            help_text += f"Fix: Update to version {fixed_version} or later.\n"
        else:
            help_text += "Fix: No fixed version available. Consider finding an alternative package.\n"

        return help_text

    def _create_help_markdown(self, vuln: Dict[str, Any]) -> str:
        """Create help markdown for vulnerability"""
        package = vuln.get("package", "unknown")
        installed_version = vuln.get("installed_version", "unknown")
        fixed_version = vuln.get("fixed_version")
        description = vuln.get("description", "No description available")
        cve = vuln.get("cve")
        advisory_url = vuln.get("advisory_url")

        markdown = f"## Vulnerability in {package}\n\n"
        markdown += f"**Installed Version:** `{installed_version}`\n\n"
        
        if fixed_version:
            markdown += f"**Fixed Version:** `{fixed_version}`\n\n"
        
        markdown += f"**Description:** {description}\n\n"
        
        if cve:
            markdown += f"**CVE:** [{cve}](https://cve.mitre.org/cgi-bin/cvename.cgi?name={cve})\n\n"
        
        if advisory_url:
            markdown += f"**Advisory:** [View Details]({advisory_url})\n\n"

        markdown += "### Remediation\n\n"
        if fixed_version:
            markdown += f"Update the package to version `{fixed_version}` or later:\n\n"
            markdown += f"```bash\npip install {package}>={fixed_version}\n```\n\n"
            markdown += f"Or update your requirements file:\n\n"
            markdown += f"```\n{package}>={fixed_version}\n```"
        else:
            markdown += "No fixed version is available. Consider:\n\n"
            markdown += "- Finding an alternative package\n"
            markdown += "- Contacting the package maintainer\n"
            markdown += "- Implementing additional security measures"

        return markdown

    def _create_result_markdown(self, vuln: Dict[str, Any]) -> str:
        """Create result markdown for vulnerability"""
        package = vuln.get("package", "unknown")
        installed_version = vuln.get("installed_version", "unknown")
        fixed_version = vuln.get("fixed_version")
        severity = vuln.get("severity", "medium").upper()

        markdown = f"**{severity}** vulnerability in `{package}` version `{installed_version}`"
        
        if fixed_version:
            markdown += f". Update to `{fixed_version}` to fix."
        else:
            markdown += ". No fix available."

        return markdown

    def _create_fingerprint(self, vuln: Dict[str, Any], service: str) -> str:
        """Create a unique fingerprint for the vulnerability"""
        package = vuln.get("package", "unknown")
        vuln_id = vuln.get("id", "unknown")
        installed_version = vuln.get("installed_version", "unknown")
        
        fingerprint_data = f"{service}:{package}:{installed_version}:{vuln_id}"
        
        # Create a simple hash
        import hashlib
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]

    def _map_severity_to_level(self, severity: str) -> str:
        """Map vulnerability severity to SARIF level"""
        severity_map = {
            "critical": "error",
            "high": "error", 
            "medium": "warning",
            "low": "note"
        }
        return severity_map.get(severity.lower(), "warning")

    def _map_severity_to_score(self, severity: str) -> str:
        """Map vulnerability severity to security severity score"""
        severity_map = {
            "critical": "9.0",
            "high": "7.0",
            "medium": "5.0", 
            "low": "3.0"
        }
        return severity_map.get(severity.lower(), "5.0")


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description="Convert vulnerability reports to SARIF format")
    parser.add_argument("--input", required=True, help="Input vulnerability report JSON file")
    parser.add_argument("--output", required=True, help="Output SARIF file")
    parser.add_argument("--service", required=True, help="Service name")

    args = parser.parse_args()

    try:
        # Read input report
        with open(args.input, 'r') as f:
            report_data = json.load(f)

        # Convert to SARIF
        converter = SarifConverter()
        sarif_report = converter.convert_vulnerability_report(report_data, args.service)

        # Write SARIF output
        with open(args.output, 'w') as f:
            json.dump(sarif_report, f, indent=2)

        print(f"Successfully converted {args.input} to SARIF format: {args.output}")

    except FileNotFoundError:
        print(f"Error: Input file {args.input} not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in input file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()