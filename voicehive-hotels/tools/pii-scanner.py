#!/usr/bin/env python3
"""
VoiceHive Hotels PII Scanner Tool
Uses Microsoft Presidio for GDPR-compliant PII detection
Includes custom patterns for EU-specific data types
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig
except ImportError:
    print("ERROR: Presidio not installed. Please run: pip install presidio-analyzer presidio-anonymizer spacy")
    print("Then download the spaCy model: python -m spacy download en_core_web_lg")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# EU-specific patterns
EU_PATTERNS = {
    "EU_PHONE": {
        "patterns": [
            # International format
            Pattern(name="EU_PHONE_INTERNATIONAL", 
                   regex=r"\+(?:32|33|34|39|44|45|46|47|48|49|351|352|353|354|355|356|357|358|359|370|371|372|373|374|375|376|377|378|380|381|382|383|385|386|387|389|420|421|423)\s?\d{6,14}", 
                   score=0.9),
            # Local formats with country codes
            Pattern(name="EU_PHONE_LOCAL",
                   regex=r"(?:0[1-9]|00(?:32|33|34|39|44|45|46|47|48|49|351|352|353|354|355|356|357|358|359|370|371|372|373|374|375|376|377|378|380|381|382|383|385|386|387|389|420|421|423))\s?\d{6,12}",
                   score=0.8),
        ],
        "context": ["phone", "tel", "mobile", "contact", "call", "telefon", "téléphone", "telefono"]
    },
    "IBAN": {
        "patterns": [
            # IBAN format
            Pattern(name="IBAN",
                   regex=r"[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}",
                   score=0.95),
        ],
        "context": ["iban", "bank", "account", "payment", "transfer"]
    },
    "EU_VAT": {
        "patterns": [
            # EU VAT numbers
            Pattern(name="EU_VAT",
                   regex=r"(?:AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK)(?:\s?)\d{8,12}",
                   score=0.9),
        ],
        "context": ["vat", "tax", "btw", "mva", "iva", "tva", "mwst", "ust"]
    },
    "EU_PASSPORT": {
        "patterns": [
            # Common EU passport formats
            Pattern(name="EU_PASSPORT",
                   regex=r"(?:[A-Z]{1,2}\d{6,9})|(?:\d{9}[A-Z]{1,2})",
                   score=0.8),
        ],
        "context": ["passport", "passeport", "reisepass", "pasaporte", "passaporto"]
    },
    "EU_NATIONAL_ID": {
        "patterns": [
            # German ID
            Pattern(name="DE_ID",
                   regex=r"[0-9]{10}[A-Z][0-9]{11}",
                   score=0.85),
            # French ID
            Pattern(name="FR_ID",
                   regex=r"[0-9]{15}",
                   score=0.85),
            # Spanish DNI
            Pattern(name="ES_DNI",
                   regex=r"[0-9]{8}[A-Z]",
                   score=0.85),
        ],
        "context": ["id", "identity", "personalausweis", "dni", "carte", "identité"]
    }
}

class EUPIIRecognizer(PatternRecognizer):
    """Custom recognizer for EU-specific PII patterns"""
    
    def __init__(self, entity_name: str, patterns: List[Pattern], context_words: List[str]):
        super().__init__(
            supported_entity=entity_name,
            patterns=patterns,
            context=context_words
        )

class PIIScanner:
    """Main PII scanner class for VoiceHive Hotels"""
    
    def __init__(self):
        # Initialize NLP engine
        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
        }
        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()
        
        # Initialize analyzer with NLP engine
        self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        self.anonymizer = AnonymizerEngine()
        
        # Add custom EU recognizers
        self._add_eu_recognizers()
        
        # Statistics
        self.stats: Dict[str, int] = {}
        self.files_scanned = 0
        self.files_with_pii = 0
        
    def _add_eu_recognizers(self):
        """Add custom recognizers for EU-specific PII"""
        for entity_name, config in EU_PATTERNS.items():
            recognizer = EUPIIRecognizer(
                entity_name=entity_name,
                patterns=config["patterns"],
                context_words=config["context"]
            )
            self.analyzer.registry.add_recognizer(recognizer)
            
    def scan_text(self, text: str, language: str = "en") -> List[Dict]:
        """Scan text for PII entities"""
        results = self.analyzer.analyze(
            text=text,
            language=language,
            entities=None  # Detect all entity types
        )
        
        # Convert results to dict format
        findings = []
        for result in results:
            finding = {
                "entity_type": result.entity_type,
                "start": result.start,
                "end": result.end,
                "score": result.score,
                "text": text[result.start:result.end],
                "redacted": self._redact_text(text[result.start:result.end], result.entity_type)
            }
            findings.append(finding)
            
            # Update statistics
            self.stats[result.entity_type] = self.stats.get(result.entity_type, 0) + 1
            
        return findings
    
    def _redact_text(self, text: str, entity_type: str) -> str:
        """Redact PII text based on entity type"""
        if entity_type in ["EMAIL_ADDRESS", "IBAN", "CREDIT_CARD"]:
            # Keep first and last few characters
            if len(text) > 8:
                return f"{text[:3]}...{text[-3:]}"
            else:
                return "***"
        elif entity_type in ["PHONE_NUMBER", "EU_PHONE"]:
            # Keep country code and last 2 digits
            if text.startswith("+"):
                return f"{text[:3]}*****{text[-2:]}"
            else:
                return f"****{text[-2:]}"
        elif entity_type in ["PERSON", "LOCATION"]:
            # Replace with entity type
            return f"[{entity_type}]"
        else:
            # Default redaction
            return "*" * len(text)
    
    def scan_file(self, file_path: Path) -> Optional[List[Dict]]:
        """Scan a single file for PII"""
        try:
            # Skip binary files
            if file_path.suffix in ['.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe']:
                return None
                
            # Read file content
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Skip binary files
                return None
                
            self.files_scanned += 1
            
            # Scan for PII
            findings = self.scan_text(content)
            
            if findings:
                self.files_with_pii += 1
                logger.warning(f"Found {len(findings)} PII entities in {file_path}")
                return findings
                
        except Exception as e:
            logger.error(f"Error scanning {file_path}: {e}")
            
        return None
    
    def scan_directory(self, directory: Path, exclude_patterns: List[str] = None) -> Dict[str, List[Dict]]:
        """Recursively scan directory for PII"""
        if exclude_patterns is None:
            exclude_patterns = [
                "__pycache__", ".git", ".venv", "venv", "node_modules",
                "*.pyc", "*.pyo", "*.so", "*.dylib", "*.dll"
            ]
            
        findings_by_file = {}
        
        for file_path in directory.rglob("*"):
            # Skip excluded patterns
            if any(pattern in str(file_path) for pattern in exclude_patterns):
                continue
                
            if file_path.is_file():
                findings = self.scan_file(file_path)
                if findings:
                    findings_by_file[str(file_path)] = findings
                    
        return findings_by_file
    
    def scan_logs(self, log_dir: Path) -> Dict[str, List[Dict]]:
        """Scan log files for PII"""
        log_patterns = ["*.log", "*.txt", "*.out"]
        findings_by_file = {}
        
        for pattern in log_patterns:
            for log_file in log_dir.rglob(pattern):
                findings = self.scan_file(log_file)
                if findings:
                    findings_by_file[str(log_file)] = findings
                    
        return findings_by_file
    
    def generate_report(self, findings: Dict[str, List[Dict]], output_format: str = "json") -> str:
        """Generate PII scan report"""
        report = {
            "scan_date": datetime.utcnow().isoformat() + "Z",
            "files_scanned": self.files_scanned,
            "files_with_pii": self.files_with_pii,
            "total_findings": sum(len(f) for f in findings.values()),
            "findings_by_type": self.stats,
            "details": findings,
            "gdpr_compliance": {
                "data_minimization": "Review and remove unnecessary PII",
                "retention_policy": "Ensure PII is deleted after retention period",
                "encryption": "Ensure PII is encrypted at rest and in transit",
                "access_control": "Limit access to PII on need-to-know basis"
            }
        }
        
        if output_format == "json":
            return json.dumps(report, indent=2)
        else:
            # Human-readable format
            lines = [
                f"PII Scan Report - {report['scan_date']}",
                "=" * 50,
                f"Files scanned: {report['files_scanned']}",
                f"Files with PII: {report['files_with_pii']}",
                f"Total findings: {report['total_findings']}",
                "",
                "Findings by type:",
                "-" * 20
            ]
            
            for entity_type, count in sorted(report['findings_by_type'].items()):
                lines.append(f"  {entity_type}: {count}")
                
            lines.extend([
                "",
                "GDPR Compliance Recommendations:",
                "-" * 30
            ])
            
            for key, value in report['gdpr_compliance'].items():
                lines.append(f"  • {key.replace('_', ' ').title()}: {value}")
                
            if findings:
                lines.extend([
                    "",
                    "Detailed Findings:",
                    "-" * 20
                ])
                
                for file_path, file_findings in sorted(findings.items()):
                    lines.append(f"\n{file_path}:")
                    for finding in file_findings:
                        lines.append(
                            f"  - {finding['entity_type']} at {finding['start']}-{finding['end']}: "
                            f"{finding['redacted']} (confidence: {finding['score']:.2f})"
                        )
                        
            return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="VoiceHive Hotels PII Scanner - GDPR Compliant PII Detection"
    )
    parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to scan (file or directory)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for report (default: stdout)"
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)"
    )
    parser.add_argument(
        "--database",
        action="store_true",
        help="Scan database (requires connection string in env)"
    )
    parser.add_argument(
        "--exclude",
        type=str,
        nargs="+",
        help="Patterns to exclude from scanning"
    )
    
    args = parser.parse_args()
    
    # Initialize scanner
    scanner = PIIScanner()
    
    # Determine scan target
    scan_path = Path(args.path)
    
    if args.database:
        logger.error("Database scanning not yet implemented")
        sys.exit(1)
        
    if scan_path.is_file():
        findings = {}
        file_findings = scanner.scan_file(scan_path)
        if file_findings:
            findings[str(scan_path)] = file_findings
    elif scan_path.is_dir():
        logger.info(f"Scanning directory: {scan_path}")
        findings = scanner.scan_directory(scan_path, exclude_patterns=args.exclude)
    else:
        logger.error(f"Path not found: {scan_path}")
        sys.exit(1)
        
    # Generate report
    report = scanner.generate_report(findings, output_format=args.format)
    
    # Output report
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        logger.info(f"Report written to: {args.output}")
    else:
        print(report)
        
    # Exit with error code if PII found
    if findings:
        sys.exit(1)
    else:
        logger.info("No PII found!")
        sys.exit(0)


if __name__ == "__main__":
    main()
