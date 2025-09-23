#!/usr/bin/env python3
"""
Production-grade Secret Scanner for CI/CD Pipeline
Prevents accidental exposure of secrets in code repositories
"""

import argparse
import json
import os
import re
import sys
import hashlib
import base64
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import subprocess
import tempfile

# Third-party imports for enhanced detection
try:
    import entropy
    ENTROPY_AVAILABLE = True
except ImportError:
    ENTROPY_AVAILABLE = False

try:
    import yara
    YARA_AVAILABLE = True
except ImportError:
    YARA_AVAILABLE = False


class SeverityLevel(str, Enum):
    """Severity levels for detected secrets"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class SecretType(str, Enum):
    """Types of secrets that can be detected"""
    API_KEY = "api_key"
    PASSWORD = "password"
    TOKEN = "token"
    CERTIFICATE = "certificate"
    PRIVATE_KEY = "private_key"
    DATABASE_URL = "database_url"
    JWT_SECRET = "jwt_secret"
    ENCRYPTION_KEY = "encryption_key"
    WEBHOOK_SECRET = "webhook_secret"
    CLOUD_CREDENTIALS = "cloud_credentials"
    GENERIC_SECRET = "generic_secret"


@dataclass
class SecretMatch:
    """Represents a detected secret"""
    file_path: str
    line_number: int
    column_start: int
    column_end: int
    secret_type: SecretType
    severity: SeverityLevel
    matched_text: str
    context: str
    entropy_score: Optional[float]
    rule_id: str
    confidence: float
    is_test_file: bool
    is_example_file: bool


@dataclass
class ScanResult:
    """Results of a secret scan"""
    total_files_scanned: int
    secrets_found: List[SecretMatch]
    scan_duration_seconds: float
    scanner_version: str
    scan_timestamp: str
    exit_code: int
    errors: List[str]


class SecretPattern:
    """Represents a secret detection pattern"""
    
    def __init__(self, 
                 pattern: str, 
                 secret_type: SecretType, 
                 severity: SeverityLevel,
                 rule_id: str,
                 description: str,
                 min_entropy: Optional[float] = None,
                 context_patterns: Optional[List[str]] = None):
        self.pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        self.secret_type = secret_type
        self.severity = severity
        self.rule_id = rule_id
        self.description = description
        self.min_entropy = min_entropy
        self.context_patterns = [re.compile(p, re.IGNORECASE) for p in (context_patterns or [])]


class SecretScanner:
    """
    Production-grade secret scanner with comprehensive detection rules
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.patterns = self._initialize_patterns()
        self.whitelist_patterns = self._initialize_whitelist()
        self.file_extensions = {'.py', '.js', '.ts', '.java', '.go', '.rb', '.php', '.sh', '.yaml', '.yml', '.json', '.xml', '.env', '.conf', '.config', '.ini', '.properties'}
        self.excluded_dirs = {'.git', '.svn', '.hg', 'node_modules', '__pycache__', '.pytest_cache', 'venv', '.venv', 'env', '.env'}
        
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load scanner configuration"""
        default_config = {
            "min_entropy_threshold": 3.5,
            "max_file_size_mb": 10,
            "scan_binary_files": False,
            "exclude_test_files": False,
            "exclude_example_files": True,
            "confidence_threshold": 0.7,
            "enable_entropy_analysis": True,
            "enable_context_analysis": True
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                default_config.update(user_config)
            except Exception as e:
                print(f"Warning: Failed to load config from {config_path}: {e}")
        
        return default_config
    
    def _initialize_patterns(self) -> List[SecretPattern]:
        """Initialize comprehensive secret detection patterns"""
        patterns = [
            # AWS Credentials
            SecretPattern(
                r'AKIA[0-9A-Z]{16}',
                SecretType.CLOUD_CREDENTIALS,
                SeverityLevel.CRITICAL,
                'aws-access-key',
                'AWS Access Key ID',
                min_entropy=3.0
            ),
            SecretPattern(
                r'aws_secret_access_key\s*[=:]\s*["\']?([A-Za-z0-9+/]{40})["\']?',
                SecretType.CLOUD_CREDENTIALS,
                SeverityLevel.CRITICAL,
                'aws-secret-key',
                'AWS Secret Access Key',
                min_entropy=4.0
            ),
            
            # API Keys - Generic patterns
            SecretPattern(
                r'api[_-]?key\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})["\']?',
                SecretType.API_KEY,
                SeverityLevel.HIGH,
                'generic-api-key',
                'Generic API Key',
                min_entropy=3.5
            ),
            
            # JWT Tokens
            SecretPattern(
                r'eyJ[A-Za-z0-9_\-]*\.eyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*',
                SecretType.TOKEN,
                SeverityLevel.HIGH,
                'jwt-token',
                'JWT Token',
                min_entropy=4.0
            ),
            
            # Database URLs
            SecretPattern(
                r'(postgresql|mysql|mongodb|redis)://[^:\s]+:[^@\s]+@[^/\s]+',
                SecretType.DATABASE_URL,
                SeverityLevel.CRITICAL,
                'database-url',
                'Database Connection URL with credentials'
            ),
            
            # Private Keys
            SecretPattern(
                r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----',
                SecretType.PRIVATE_KEY,
                SeverityLevel.CRITICAL,
                'private-key',
                'Private Key'
            ),
            
            # GitHub Tokens
            SecretPattern(
                r'gh[pousr]_[A-Za-z0-9_]{36,255}',
                SecretType.TOKEN,
                SeverityLevel.HIGH,
                'github-token',
                'GitHub Token'
            ),
            
            # Slack Tokens
            SecretPattern(
                r'xox[baprs]-[0-9]{12}-[0-9]{12}-[A-Za-z0-9]{24}',
                SecretType.TOKEN,
                SeverityLevel.HIGH,
                'slack-token',
                'Slack Token'
            ),
            
            # Generic high-entropy strings
            SecretPattern(
                r'["\']([A-Za-z0-9+/]{32,}={0,2})["\']',
                SecretType.GENERIC_SECRET,
                SeverityLevel.MEDIUM,
                'high-entropy-string',
                'High entropy string (possible secret)',
                min_entropy=4.5
            ),
            
            # VoiceHive specific patterns
            SecretPattern(
                r'vh_[A-Za-z0-9_\-]{32,}',
                SecretType.API_KEY,
                SeverityLevel.HIGH,
                'voicehive-api-key',
                'VoiceHive API Key'
            ),
            
            # Vault tokens
            SecretPattern(
                r'hvs\.[A-Za-z0-9_\-]{20,}',
                SecretType.TOKEN,
                SeverityLevel.CRITICAL,
                'vault-token',
                'HashiCorp Vault Token'
            ),
            
            # LiveKit keys
            SecretPattern(
                r'(livekit[_-]?(?:api[_-]?)?(?:key|secret))\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})["\']?',
                SecretType.API_KEY,
                SeverityLevel.HIGH,
                'livekit-key',
                'LiveKit API Key/Secret',
                context_patterns=[r'livekit', r'webrtc']
            ),
            
            # Twilio credentials
            SecretPattern(
                r'AC[a-z0-9]{32}',
                SecretType.API_KEY,
                SeverityLevel.HIGH,
                'twilio-sid',
                'Twilio Account SID'
            ),
            
            # Azure OpenAI keys
            SecretPattern(
                r'(azure[_-]?openai[_-]?key)\s*[=:]\s*["\']?([A-Za-z0-9]{32})["\']?',
                SecretType.API_KEY,
                SeverityLevel.HIGH,
                'azure-openai-key',
                'Azure OpenAI API Key'
            ),
            
            # ElevenLabs API keys
            SecretPattern(
                r'(elevenlabs[_-]?api[_-]?key)\s*[=:]\s*["\']?([A-Za-z0-9]{32})["\']?',
                SecretType.API_KEY,
                SeverityLevel.HIGH,
                'elevenlabs-key',
                'ElevenLabs API Key'
            ),
            
            # Generic password patterns
            SecretPattern(
                r'password\s*[=:]\s*["\']([^"\']{8,})["\']',
                SecretType.PASSWORD,
                SeverityLevel.MEDIUM,
                'generic-password',
                'Generic password',
                min_entropy=2.5
            ),
            
            # JWT secrets
            SecretPattern(
                r'jwt[_-]?secret\s*[=:]\s*["\']?([A-Za-z0-9+/=]{32,})["\']?',
                SecretType.JWT_SECRET,
                SeverityLevel.HIGH,
                'jwt-secret',
                'JWT Secret Key',
                min_entropy=4.0
            ),
            
            # Webhook secrets
            SecretPattern(
                r'webhook[_-]?secret\s*[=:]\s*["\']?([A-Za-z0-9_\-]{16,})["\']?',
                SecretType.WEBHOOK_SECRET,
                SeverityLevel.HIGH,
                'webhook-secret',
                'Webhook Secret'
            )
        ]
        
        return patterns
    
    def _initialize_whitelist(self) -> List[re.Pattern]:
        """Initialize patterns for known false positives"""
        whitelist_patterns = [
            # Example/placeholder values
            re.compile(r'your[_-]?(?:api[_-]?)?key', re.IGNORECASE),
            re.compile(r'example[_-]?(?:api[_-]?)?key', re.IGNORECASE),
            re.compile(r'test[_-]?(?:api[_-]?)?key', re.IGNORECASE),
            re.compile(r'placeholder', re.IGNORECASE),
            re.compile(r'changeme', re.IGNORECASE),
            re.compile(r'replace[_-]?with', re.IGNORECASE),
            re.compile(r'xxx+', re.IGNORECASE),
            re.compile(r'yyy+', re.IGNORECASE),
            re.compile(r'zzz+', re.IGNORECASE),
            
            # Common non-secrets
            re.compile(r'^(true|false|null|undefined)$', re.IGNORECASE),
            re.compile(r'^[0-9]+$'),  # Pure numbers
            re.compile(r'^[a-f0-9]{32}$'),  # MD5 hashes (common in tests)
            
            # VoiceHive specific whitelisted values
            re.compile(r'dev-root-token', re.IGNORECASE),
            re.compile(r'development-key', re.IGNORECASE),
            re.compile(r'test-secret', re.IGNORECASE),
        ]
        
        return whitelist_patterns
    
    def calculate_entropy(self, text: str) -> float:
        """Calculate Shannon entropy of a string"""
        if not text:
            return 0.0
        
        # Count character frequencies
        char_counts = {}
        for char in text:
            char_counts[char] = char_counts.get(char, 0) + 1
        
        # Calculate entropy
        entropy = 0.0
        text_len = len(text)
        
        for count in char_counts.values():
            probability = count / text_len
            if probability > 0:
                entropy -= probability * (probability.bit_length() - 1)
        
        return entropy
    
    def is_whitelisted(self, text: str) -> bool:
        """Check if text matches whitelist patterns"""
        for pattern in self.whitelist_patterns:
            if pattern.search(text):
                return True
        return False
    
    def is_test_file(self, file_path: str) -> bool:
        """Check if file is a test file"""
        path_lower = file_path.lower()
        return any(indicator in path_lower for indicator in [
            'test', 'spec', 'mock', '__test__', '.test.', '.spec.',
            'tests/', 'testing/', 'fixtures/', 'conftest'
        ])
    
    def is_example_file(self, file_path: str) -> bool:
        """Check if file is an example/documentation file"""
        path_lower = file_path.lower()
        return any(indicator in path_lower for indicator in [
            'example', 'sample', 'demo', 'template', '.example',
            'readme', 'doc/', 'docs/', 'documentation/'
        ])
    
    def should_scan_file(self, file_path: Path) -> bool:
        """Determine if a file should be scanned"""
        # Check file size
        try:
            if file_path.stat().st_size > self.config['max_file_size_mb'] * 1024 * 1024:
                return False
        except OSError:
            return False
        
        # Check extension
        if file_path.suffix.lower() not in self.file_extensions:
            return False
        
        # Check if it's a binary file (basic check)
        if not self.config['scan_binary_files']:
            try:
                with open(file_path, 'rb') as f:
                    chunk = f.read(1024)
                    if b'\x00' in chunk:  # Null bytes indicate binary
                        return False
            except (OSError, IOError):
                return False
        
        return True
    
    def scan_file(self, file_path: Path) -> List[SecretMatch]:
        """Scan a single file for secrets"""
        matches = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.splitlines()
        except (OSError, IOError, UnicodeDecodeError) as e:
            return matches
        
        is_test = self.is_test_file(str(file_path))
        is_example = self.is_example_file(str(file_path))
        
        # Skip if configured to exclude test/example files
        if is_test and self.config.get('exclude_test_files', False):
            return matches
        if is_example and self.config.get('exclude_example_files', True):
            return matches
        
        # Scan with each pattern
        for pattern_obj in self.patterns:
            for match in pattern_obj.pattern.finditer(content):
                matched_text = match.group(1) if match.groups() else match.group(0)
                
                # Skip if whitelisted
                if self.is_whitelisted(matched_text):
                    continue
                
                # Calculate entropy if required
                entropy_score = None
                if pattern_obj.min_entropy is not None:
                    entropy_score = self.calculate_entropy(matched_text)
                    if entropy_score < pattern_obj.min_entropy:
                        continue
                
                # Calculate confidence based on various factors
                confidence = self._calculate_confidence(
                    pattern_obj, matched_text, entropy_score, is_test, is_example
                )
                
                if confidence < self.config['confidence_threshold']:
                    continue
                
                # Find line number and column
                line_start = content.rfind('\n', 0, match.start()) + 1
                line_number = content[:match.start()].count('\n') + 1
                column_start = match.start() - line_start
                column_end = match.end() - line_start
                
                # Get context (surrounding lines)
                context_start = max(0, line_number - 2)
                context_end = min(len(lines), line_number + 1)
                context = '\n'.join(lines[context_start:context_end])
                
                secret_match = SecretMatch(
                    file_path=str(file_path),
                    line_number=line_number,
                    column_start=column_start,
                    column_end=column_end,
                    secret_type=pattern_obj.secret_type,
                    severity=pattern_obj.severity,
                    matched_text=matched_text[:50] + '...' if len(matched_text) > 50 else matched_text,
                    context=context,
                    entropy_score=entropy_score,
                    rule_id=pattern_obj.rule_id,
                    confidence=confidence,
                    is_test_file=is_test,
                    is_example_file=is_example
                )
                
                matches.append(secret_match)
        
        return matches
    
    def _calculate_confidence(self, 
                            pattern_obj: SecretPattern, 
                            matched_text: str, 
                            entropy_score: Optional[float],
                            is_test: bool, 
                            is_example: bool) -> float:
        """Calculate confidence score for a match"""
        confidence = 0.8  # Base confidence
        
        # Adjust based on entropy
        if entropy_score is not None:
            if entropy_score > 4.5:
                confidence += 0.2
            elif entropy_score > 3.5:
                confidence += 0.1
            elif entropy_score < 2.0:
                confidence -= 0.3
        
        # Adjust based on file type
        if is_test:
            confidence -= 0.2
        if is_example:
            confidence -= 0.3
        
        # Adjust based on pattern specificity
        if pattern_obj.secret_type in [SecretType.PRIVATE_KEY, SecretType.JWT_SECRET]:
            confidence += 0.1
        
        # Adjust based on context patterns
        if pattern_obj.context_patterns:
            confidence += 0.1
        
        return max(0.0, min(1.0, confidence))
    
    def scan_directory(self, directory: Path, recursive: bool = True) -> ScanResult:
        """Scan a directory for secrets"""
        import time
        
        start_time = time.time()
        all_matches = []
        files_scanned = 0
        errors = []
        
        try:
            if recursive:
                file_iterator = directory.rglob('*')
            else:
                file_iterator = directory.iterdir()
            
            for item in file_iterator:
                if not item.is_file():
                    continue
                
                # Skip excluded directories
                if any(excluded in item.parts for excluded in self.excluded_dirs):
                    continue
                
                if not self.should_scan_file(item):
                    continue
                
                try:
                    matches = self.scan_file(item)
                    all_matches.extend(matches)
                    files_scanned += 1
                except Exception as e:
                    errors.append(f"Error scanning {item}: {str(e)}")
        
        except Exception as e:
            errors.append(f"Error scanning directory {directory}: {str(e)}")
        
        scan_duration = time.time() - start_time
        
        # Determine exit code
        exit_code = 0
        if any(match.severity in [SeverityLevel.CRITICAL, SeverityLevel.HIGH] for match in all_matches):
            exit_code = 1
        
        return ScanResult(
            total_files_scanned=files_scanned,
            secrets_found=all_matches,
            scan_duration_seconds=scan_duration,
            scanner_version="1.0.0",
            scan_timestamp=time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
            exit_code=exit_code,
            errors=errors
        )
    
    def generate_report(self, result: ScanResult, format_type: str = 'json') -> str:
        """Generate scan report in specified format"""
        if format_type == 'json':
            return self._generate_json_report(result)
        elif format_type == 'sarif':
            return self._generate_sarif_report(result)
        elif format_type == 'text':
            return self._generate_text_report(result)
        else:
            raise ValueError(f"Unsupported format: {format_type}")
    
    def _generate_json_report(self, result: ScanResult) -> str:
        """Generate JSON report"""
        report_data = asdict(result)
        
        # Convert enums to strings
        for match in report_data['secrets_found']:
            match['secret_type'] = match['secret_type']
            match['severity'] = match['severity']
        
        return json.dumps(report_data, indent=2, default=str)
    
    def _generate_sarif_report(self, result: ScanResult) -> str:
        """Generate SARIF format report for GitHub integration"""
        sarif_report = {
            "version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "VoiceHive Secret Scanner",
                        "version": result.scanner_version,
                        "informationUri": "https://github.com/voicehive/security-tools"
                    }
                },
                "results": []
            }]
        }
        
        for match in result.secrets_found:
            sarif_result = {
                "ruleId": match.rule_id,
                "message": {
                    "text": f"Potential {match.secret_type.value} detected"
                },
                "level": self._severity_to_sarif_level(match.severity),
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": match.file_path
                        },
                        "region": {
                            "startLine": match.line_number,
                            "startColumn": match.column_start + 1,
                            "endColumn": match.column_end + 1
                        }
                    }
                }],
                "properties": {
                    "confidence": match.confidence,
                    "entropy": match.entropy_score,
                    "secretType": match.secret_type.value
                }
            }
            
            sarif_report["runs"][0]["results"].append(sarif_result)
        
        return json.dumps(sarif_report, indent=2)
    
    def _generate_text_report(self, result: ScanResult) -> str:
        """Generate human-readable text report"""
        lines = []
        lines.append("VoiceHive Secret Scanner Report")
        lines.append("=" * 40)
        lines.append(f"Scan completed: {result.scan_timestamp}")
        lines.append(f"Files scanned: {result.total_files_scanned}")
        lines.append(f"Secrets found: {len(result.secrets_found)}")
        lines.append(f"Scan duration: {result.scan_duration_seconds:.2f} seconds")
        lines.append("")
        
        if result.secrets_found:
            lines.append("Detected Secrets:")
            lines.append("-" * 20)
            
            for match in result.secrets_found:
                lines.append(f"File: {match.file_path}")
                lines.append(f"Line: {match.line_number}")
                lines.append(f"Type: {match.secret_type.value}")
                lines.append(f"Severity: {match.severity.value}")
                lines.append(f"Rule: {match.rule_id}")
                lines.append(f"Confidence: {match.confidence:.2f}")
                if match.entropy_score:
                    lines.append(f"Entropy: {match.entropy_score:.2f}")
                lines.append(f"Match: {match.matched_text}")
                lines.append("")
        else:
            lines.append("No secrets detected!")
        
        if result.errors:
            lines.append("Errors:")
            lines.append("-" * 10)
            for error in result.errors:
                lines.append(f"- {error}")
        
        return "\n".join(lines)
    
    def _severity_to_sarif_level(self, severity: SeverityLevel) -> str:
        """Convert severity to SARIF level"""
        mapping = {
            SeverityLevel.CRITICAL: "error",
            SeverityLevel.HIGH: "error",
            SeverityLevel.MEDIUM: "warning",
            SeverityLevel.LOW: "note",
            SeverityLevel.INFO: "note"
        }
        return mapping.get(severity, "warning")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="VoiceHive Secret Scanner - Detect secrets in code repositories"
    )
    
    parser.add_argument(
        "path",
        help="Path to scan (file or directory)"
    )
    
    parser.add_argument(
        "--config",
        help="Path to configuration file"
    )
    
    parser.add_argument(
        "--format",
        choices=["json", "sarif", "text"],
        default="text",
        help="Output format (default: text)"
    )
    
    parser.add_argument(
        "--output",
        help="Output file (default: stdout)"
    )
    
    parser.add_argument(
        "--recursive",
        action="store_true",
        default=True,
        help="Scan directories recursively (default: true)"
    )
    
    parser.add_argument(
        "--fail-on-secrets",
        action="store_true",
        help="Exit with non-zero code if secrets are found"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Initialize scanner
    scanner = SecretScanner(args.config)
    
    # Scan path
    scan_path = Path(args.path)
    
    if not scan_path.exists():
        print(f"Error: Path {scan_path} does not exist", file=sys.stderr)
        sys.exit(1)
    
    if scan_path.is_file():
        # Scan single file
        matches = scanner.scan_file(scan_path)
        result = ScanResult(
            total_files_scanned=1,
            secrets_found=matches,
            scan_duration_seconds=0.0,
            scanner_version="1.0.0",
            scan_timestamp="",
            exit_code=1 if matches else 0,
            errors=[]
        )
    else:
        # Scan directory
        result = scanner.scan_directory(scan_path, args.recursive)
    
    # Generate report
    report = scanner.generate_report(result, args.format)
    
    # Output report
    if args.output:
        with open(args.output, 'w') as f:
            f.write(report)
        if args.verbose:
            print(f"Report written to {args.output}")
    else:
        print(report)
    
    # Exit with appropriate code
    if args.fail_on_secrets and result.secrets_found:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()