#!/usr/bin/env python3

"""
VoiceHive Hotels - SBOM (Software Bill of Materials) Manager
Comprehensive SBOM generation, tracking, and compliance management
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import hashlib
import requests
from dataclasses import dataclass, asdict
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class VulnerabilityInfo:
    """Vulnerability information for a package"""
    id: str
    severity: str
    description: str
    fixed_version: Optional[str] = None
    published_date: Optional[str] = None

@dataclass
class PackageInfo:
    """Package information with vulnerability data"""
    name: str
    version: str
    type: str
    license: Optional[str] = None
    vulnerabilities: List[VulnerabilityInfo] = None
    
    def __post_init__(self):
        if self.vulnerabilities is None:
            self.vulnerabilities = []

@dataclass
class SBOMMetadata:
    """SBOM metadata and tracking information"""
    service_name: str
    image_name: str
    image_digest: str
    generation_time: str
    sbom_format: str
    sbom_hash: str
    total_packages: int
    vulnerability_count: Dict[str, int]
    compliance_status: str

class SBOMManager:
    """SBOM Manager for VoiceHive Hotels container images"""
    
    def __init__(self, output_dir: str = "./sbom-reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.services = [
            "orchestrator", "connectors", "riva-proxy", 
            "tts-router", "media-agent"
        ]
        self.registry = os.getenv("REGISTRY", "ghcr.io")
        self.image_prefix = os.getenv("IMAGE_PREFIX", "voicehive-hotels")
        
    def check_dependencies(self) -> bool:
        """Check if required tools are available"""
        required_tools = ["syft", "grype", "docker"]
        
        for tool in required_tools:
            if not self._command_exists(tool):
                logger.error(f"Required tool '{tool}' not found")
                return False
        
        logger.info("All required dependencies found")
        return True
    
    def _command_exists(self, command: str) -> bool:
        """Check if a command exists in PATH"""
        try:
            subprocess.run(
                ["which", command], 
                check=True, 
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False
    
    def _run_command(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a command and return the result"""
        logger.debug(f"Running command: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd, 
                check=True, 
                capture_output=True, 
                text=True,
                **kwargs
            )
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}")
            logger.error(f"Error: {e.stderr}")
            raise
    
    def get_image_digest(self, image: str) -> str:
        """Get the digest of a container image"""
        try:
            result = self._run_command([
                "docker", "image", "inspect", image, 
                "--format", "{{.RepoDigests}}"
            ])
            
            # Parse the digest from the output
            digests = result.stdout.strip()
            if digests and digests != "[]":
                # Extract digest from format like [registry/image@sha256:...]
                digest_part = digests.split("@")[-1].rstrip("]")
                return digest_part
            
            # Fallback to image ID if no digest available
            result = self._run_command([
                "docker", "image", "inspect", image,
                "--format", "{{.Id}}"
            ])
            return result.stdout.strip()
            
        except subprocess.CalledProcessError:
            logger.warning(f"Could not get digest for {image}")
            return "unknown"
    
    def generate_sbom(self, service: str, image: str, formats: List[str] = None) -> Dict[str, str]:
        """Generate SBOM for a service image"""
        if formats is None:
            formats = ["spdx-json", "cyclonedx-json", "table"]
        
        logger.info(f"Generating SBOM for {service} ({image})")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sbom_files = {}
        
        for fmt in formats:
            if fmt == "table":
                output_file = self.output_dir / f"sbom-{service}-{timestamp}.txt"
            else:
                ext = "json" if "json" in fmt else fmt
                output_file = self.output_dir / f"sbom-{service}-{timestamp}.{ext}"
            
            try:
                self._run_command([
                    "syft", image,
                    "-o", f"{fmt}={output_file}"
                ])
                
                sbom_files[fmt] = str(output_file)
                logger.info(f"Generated {fmt} SBOM: {output_file}")
                
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to generate {fmt} SBOM for {service}: {e}")
        
        return sbom_files
    
    def analyze_vulnerabilities(self, image: str) -> List[VulnerabilityInfo]:
        """Analyze vulnerabilities in the image"""
        logger.info(f"Analyzing vulnerabilities for {image}")
        
        try:
            # Run Grype to get vulnerability information
            result = self._run_command([
                "grype", image, "-o", "json"
            ])
            
            vuln_data = json.loads(result.stdout)
            vulnerabilities = []
            
            for match in vuln_data.get("matches", []):
                vuln = match.get("vulnerability", {})
                vulnerabilities.append(VulnerabilityInfo(
                    id=vuln.get("id", ""),
                    severity=vuln.get("severity", "UNKNOWN"),
                    description=vuln.get("description", ""),
                    fixed_version=match.get("matchDetails", {}).get("found", {}).get("fixedInVersion"),
                    published_date=vuln.get("publishedDate")
                ))
            
            logger.info(f"Found {len(vulnerabilities)} vulnerabilities")
            return vulnerabilities
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to analyze vulnerabilities: {e}")
            return []
    
    def parse_sbom_packages(self, sbom_file: str) -> List[PackageInfo]:
        """Parse packages from SPDX SBOM file"""
        logger.info(f"Parsing packages from {sbom_file}")
        
        try:
            with open(sbom_file, 'r') as f:
                sbom_data = json.load(f)
            
            packages = []
            
            for package in sbom_data.get("packages", []):
                # Skip the root package (usually the container image itself)
                if package.get("name") == sbom_data.get("name"):
                    continue
                
                pkg_info = PackageInfo(
                    name=package.get("name", ""),
                    version=package.get("versionInfo", ""),
                    type=package.get("packageType", ""),
                    license=self._extract_license(package)
                )
                packages.append(pkg_info)
            
            logger.info(f"Parsed {len(packages)} packages")
            return packages
            
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.error(f"Failed to parse SBOM file {sbom_file}: {e}")
            return []
    
    def _extract_license(self, package: Dict) -> Optional[str]:
        """Extract license information from package data"""
        license_info = package.get("licenseConcluded")
        if license_info and license_info != "NOASSERTION":
            return license_info
        
        # Try to get from license info array
        license_infos = package.get("licenseInfoFromFiles", [])
        if license_infos:
            return ", ".join([li for li in license_infos if li != "NOASSERTION"])
        
        return None
    
    def calculate_sbom_hash(self, sbom_file: str) -> str:
        """Calculate SHA256 hash of SBOM file"""
        try:
            with open(sbom_file, 'rb') as f:
                content = f.read()
            return hashlib.sha256(content).hexdigest()
        except FileNotFoundError:
            return ""
    
    def generate_metadata(self, service: str, image: str, sbom_files: Dict[str, str], 
                         vulnerabilities: List[VulnerabilityInfo]) -> SBOMMetadata:
        """Generate SBOM metadata"""
        
        # Get primary SBOM file (prefer SPDX JSON)
        primary_sbom = sbom_files.get("spdx-json", list(sbom_files.values())[0])
        
        # Parse packages to get count
        packages = self.parse_sbom_packages(primary_sbom) if "spdx-json" in sbom_files else []
        
        # Count vulnerabilities by severity
        vuln_count = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
        for vuln in vulnerabilities:
            severity = vuln.severity.upper()
            if severity in vuln_count:
                vuln_count[severity] += 1
            else:
                vuln_count["UNKNOWN"] += 1
        
        # Determine compliance status
        compliance_status = "COMPLIANT"
        if vuln_count["CRITICAL"] > 0:
            compliance_status = "NON_COMPLIANT"
        elif vuln_count["HIGH"] > 5:  # Threshold for high vulnerabilities
            compliance_status = "NEEDS_REVIEW"
        
        return SBOMMetadata(
            service_name=service,
            image_name=image,
            image_digest=self.get_image_digest(image),
            generation_time=datetime.now(timezone.utc).isoformat(),
            sbom_format="spdx-json" if "spdx-json" in sbom_files else list(sbom_files.keys())[0],
            sbom_hash=self.calculate_sbom_hash(primary_sbom),
            total_packages=len(packages),
            vulnerability_count=vuln_count,
            compliance_status=compliance_status
        )
    
    def generate_compliance_report(self, metadata_list: List[SBOMMetadata]) -> str:
        """Generate compliance report for all services"""
        
        report_file = self.output_dir / f"compliance-report-{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        with open(report_file, 'w') as f:
            f.write("# VoiceHive Hotels - SBOM Compliance Report\n\n")
            f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
            
            # Summary
            f.write("## Executive Summary\n\n")
            total_services = len(metadata_list)
            compliant_services = sum(1 for m in metadata_list if m.compliance_status == "COMPLIANT")
            non_compliant_services = sum(1 for m in metadata_list if m.compliance_status == "NON_COMPLIANT")
            needs_review_services = sum(1 for m in metadata_list if m.compliance_status == "NEEDS_REVIEW")
            
            f.write(f"- **Total Services**: {total_services}\n")
            f.write(f"- **Compliant**: {compliant_services}\n")
            f.write(f"- **Non-Compliant**: {non_compliant_services}\n")
            f.write(f"- **Needs Review**: {needs_review_services}\n\n")
            
            # Overall status
            if non_compliant_services > 0:
                f.write("🔴 **Overall Status**: NON-COMPLIANT\n\n")
            elif needs_review_services > 0:
                f.write("🟡 **Overall Status**: NEEDS REVIEW\n\n")
            else:
                f.write("🟢 **Overall Status**: COMPLIANT\n\n")
            
            # Service details
            f.write("## Service Details\n\n")
            
            for metadata in metadata_list:
                status_emoji = {
                    "COMPLIANT": "🟢",
                    "NON_COMPLIANT": "🔴", 
                    "NEEDS_REVIEW": "🟡"
                }.get(metadata.compliance_status, "⚪")
                
                f.write(f"### {metadata.service_name} {status_emoji}\n\n")
                f.write(f"- **Image**: {metadata.image_name}\n")
                f.write(f"- **Digest**: {metadata.image_digest[:16]}...\n")
                f.write(f"- **Packages**: {metadata.total_packages}\n")
                f.write(f"- **Critical Vulnerabilities**: {metadata.vulnerability_count['CRITICAL']}\n")
                f.write(f"- **High Vulnerabilities**: {metadata.vulnerability_count['HIGH']}\n")
                f.write(f"- **Medium Vulnerabilities**: {metadata.vulnerability_count['MEDIUM']}\n")
                f.write(f"- **SBOM Hash**: {metadata.sbom_hash[:16]}...\n\n")
            
            # Recommendations
            f.write("## Recommendations\n\n")
            
            if non_compliant_services > 0:
                f.write("### Immediate Actions Required\n\n")
                for metadata in metadata_list:
                    if metadata.compliance_status == "NON_COMPLIANT":
                        f.write(f"- **{metadata.service_name}**: Address {metadata.vulnerability_count['CRITICAL']} critical vulnerabilities\n")
                f.write("\n")
            
            if needs_review_services > 0:
                f.write("### Review Required\n\n")
                for metadata in metadata_list:
                    if metadata.compliance_status == "NEEDS_REVIEW":
                        f.write(f"- **{metadata.service_name}**: Review {metadata.vulnerability_count['HIGH']} high vulnerabilities\n")
                f.write("\n")
            
            f.write("### General Recommendations\n\n")
            f.write("1. Update base images to latest versions\n")
            f.write("2. Update dependencies to patched versions\n")
            f.write("3. Implement automated vulnerability scanning in CI/CD\n")
            f.write("4. Regular SBOM generation and tracking\n")
            f.write("5. Establish vulnerability response procedures\n\n")
        
        logger.info(f"Compliance report generated: {report_file}")
        return str(report_file)
    
    def export_metadata(self, metadata_list: List[SBOMMetadata]) -> str:
        """Export metadata to JSON file"""
        
        metadata_file = self.output_dir / f"sbom-metadata-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(metadata_file, 'w') as f:
            json.dump([asdict(m) for m in metadata_list], f, indent=2)
        
        logger.info(f"Metadata exported: {metadata_file}")
        return str(metadata_file)
    
    def process_service(self, service: str, tag: str = "latest") -> Optional[SBOMMetadata]:
        """Process a single service to generate SBOM and metadata"""
        
        image = f"{self.registry}/{self.image_prefix}/{service}:{tag}"
        
        logger.info(f"Processing service: {service}")
        
        try:
            # Ensure image is available
            self._run_command(["docker", "pull", image])
            
            # Generate SBOM
            sbom_files = self.generate_sbom(service, image)
            
            if not sbom_files:
                logger.error(f"Failed to generate SBOM for {service}")
                return None
            
            # Analyze vulnerabilities
            vulnerabilities = self.analyze_vulnerabilities(image)
            
            # Generate metadata
            metadata = self.generate_metadata(service, image, sbom_files, vulnerabilities)
            
            logger.info(f"Successfully processed {service}")
            return metadata
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to process service {service}: {e}")
            return None
    
    def process_all_services(self, tag: str = "latest") -> List[SBOMMetadata]:
        """Process all services to generate SBOMs and metadata"""
        
        logger.info("Processing all VoiceHive services")
        
        metadata_list = []
        
        for service in self.services:
            metadata = self.process_service(service, tag)
            if metadata:
                metadata_list.append(metadata)
        
        return metadata_list
    
    def run_compliance_check(self, services: List[str] = None, tag: str = "latest") -> bool:
        """Run compliance check for specified services"""
        
        if services is None:
            services = self.services
        
        logger.info(f"Running compliance check for services: {', '.join(services)}")
        
        metadata_list = []
        
        for service in services:
            if service not in self.services:
                logger.warning(f"Unknown service: {service}")
                continue
                
            metadata = self.process_service(service, tag)
            if metadata:
                metadata_list.append(metadata)
        
        if not metadata_list:
            logger.error("No services processed successfully")
            return False
        
        # Generate reports
        compliance_report = self.generate_compliance_report(metadata_list)
        metadata_file = self.export_metadata(metadata_list)
        
        # Check overall compliance
        non_compliant = sum(1 for m in metadata_list if m.compliance_status == "NON_COMPLIANT")
        
        logger.info(f"Compliance check completed")
        logger.info(f"Reports generated: {compliance_report}, {metadata_file}")
        
        if non_compliant > 0:
            logger.warning(f"{non_compliant} services are non-compliant")
            return False
        
        logger.info("All services are compliant")
        return True

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="VoiceHive Hotels SBOM Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --all                          # Process all services
  %(prog)s --service orchestrator         # Process specific service
  %(prog)s --compliance                   # Run compliance check
  %(prog)s --service connectors --tag v1.2.3  # Process with specific tag
        """
    )
    
    parser.add_argument(
        "--all", action="store_true",
        help="Process all services"
    )
    
    parser.add_argument(
        "--service", action="append",
        help="Process specific service (can be used multiple times)"
    )
    
    parser.add_argument(
        "--compliance", action="store_true",
        help="Run compliance check"
    )
    
    parser.add_argument(
        "--tag", default="latest",
        help="Image tag to process (default: latest)"
    )
    
    parser.add_argument(
        "--output-dir", default="./sbom-reports",
        help="Output directory for reports (default: ./sbom-reports)"
    )
    
    parser.add_argument(
        "--registry",
        help="Container registry URL (default: from REGISTRY env var)"
    )
    
    parser.add_argument(
        "--image-prefix",
        help="Image prefix (default: from IMAGE_PREFIX env var)"
    )
    
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize SBOM manager
    sbom_manager = SBOMManager(args.output_dir)
    
    if args.registry:
        sbom_manager.registry = args.registry
    
    if args.image_prefix:
        sbom_manager.image_prefix = args.image_prefix
    
    # Check dependencies
    if not sbom_manager.check_dependencies():
        sys.exit(1)
    
    # Determine services to process
    services = []
    if args.all:
        services = sbom_manager.services
    elif args.service:
        services = args.service
    else:
        logger.error("No services specified. Use --all or --service")
        sys.exit(1)
    
    # Run compliance check or process services
    if args.compliance:
        success = sbom_manager.run_compliance_check(services, args.tag)
        sys.exit(0 if success else 1)
    else:
        metadata_list = []
        for service in services:
            metadata = sbom_manager.process_service(service, args.tag)
            if metadata:
                metadata_list.append(metadata)
        
        if metadata_list:
            # Generate reports
            sbom_manager.generate_compliance_report(metadata_list)
            sbom_manager.export_metadata(metadata_list)
            logger.info("SBOM processing completed successfully")
        else:
            logger.error("No services processed successfully")
            sys.exit(1)

if __name__ == "__main__":
    main()