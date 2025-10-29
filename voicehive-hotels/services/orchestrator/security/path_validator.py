"""
Centralized Path Validation Service for VoiceHive Hotels
Provides secure file path validation and access controls to prevent path traversal and other security vulnerabilities
"""

import os
import stat
import hashlib
from pathlib import Path, PurePath
from typing import List, Optional, Union, Set, Dict, Any, Tuple
from enum import Enum
from dataclasses import dataclass
from contextlib import contextmanager
import logging
import time
from datetime import datetime, timezone

from ..logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.path_validator")


class PathSecurityLevel(Enum):
    """Security levels for path validation"""
    STRICT = "strict"       # No symlinks, strict boundary checks
    MODERATE = "moderate"   # Allow symlinks within boundaries
    PERMISSIVE = "permissive"  # Allow most operations with basic checks


class PathValidationError(Exception):
    """Raised when path validation fails"""
    pass


class PathTraversalError(PathValidationError):
    """Raised when path traversal is detected"""
    pass


class SymlinkSecurityError(PathValidationError):
    """Raised when symlink security violation is detected"""
    pass


class DirectoryBoundaryError(PathValidationError):
    """Raised when path exceeds allowed directory boundaries"""
    pass


@dataclass
class PathValidationResult:
    """Result of path validation"""
    is_valid: bool
    normalized_path: Optional[Path] = None
    security_warnings: List[str] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.security_warnings is None:
            self.security_warnings = []


@dataclass
class AllowedDirectory:
    """Configuration for an allowed directory"""
    path: Path
    allow_subdirs: bool = True
    allow_symlinks: bool = False
    allow_create: bool = False
    description: str = ""


class PathValidator:
    """
    Centralized path validation service providing secure file access controls

    Features:
    - Path traversal prevention (../../../etc/passwd)
    - Symlink resolution and validation
    - Directory boundary enforcement
    - Path normalization and canonicalization
    - Audit logging of all path operations
    - Caching of validated paths for performance
    """

    def __init__(self,
                 allowed_directories: List[AllowedDirectory] = None,
                 security_level: PathSecurityLevel = PathSecurityLevel.STRICT,
                 enable_caching: bool = True,
                 cache_ttl_seconds: int = 300):
        """
        Initialize path validator

        Args:
            allowed_directories: List of directories that are allowed for file operations
            security_level: Security level for validation strictness
            enable_caching: Whether to cache validation results
            cache_ttl_seconds: TTL for cache entries
        """
        self.allowed_directories = allowed_directories or self._get_default_allowed_directories()
        self.security_level = security_level
        self.enable_caching = enable_caching
        self.cache_ttl_seconds = cache_ttl_seconds

        # Cache for validated paths
        self._validation_cache: Dict[str, Tuple[PathValidationResult, float]] = {}

        # Normalize allowed directory paths
        self._normalize_allowed_directories()

        # Security audit log
        self._audit_log: List[Dict[str, Any]] = []

        logger.info("PathValidator initialized",
                   allowed_dirs=len(self.allowed_directories),
                   security_level=security_level.value,
                   caching_enabled=enable_caching)

    def _get_default_allowed_directories(self) -> List[AllowedDirectory]:
        """Get default allowed directories for VoiceHive Hotels"""
        base_path = Path(__file__).parent.parent.parent  # Go up to voicehive-hotels root

        return [
            AllowedDirectory(
                path=base_path / "services" / "orchestrator" / "config",
                allow_subdirs=True,
                allow_create=True,
                description="Orchestrator configuration files"
            ),
            AllowedDirectory(
                path=base_path / "services" / "orchestrator" / "reports",
                allow_subdirs=True,
                allow_create=True,
                description="Generated reports and validation output"
            ),
            AllowedDirectory(
                path=base_path / "services" / "orchestrator" / "backups",
                allow_subdirs=True,
                allow_create=True,
                description="Database backups and restoration files"
            ),
            AllowedDirectory(
                path=base_path / "services" / "orchestrator" / "logs",
                allow_subdirs=True,
                allow_create=True,
                description="Application logs"
            ),
            AllowedDirectory(
                path=base_path / "services" / "orchestrator" / "temp",
                allow_subdirs=True,
                allow_create=True,
                description="Temporary files"
            ),
            AllowedDirectory(
                path=Path("/tmp") / "voicehive",
                allow_subdirs=True,
                allow_create=True,
                description="System temporary directory for VoiceHive"
            ),
        ]

    def _normalize_allowed_directories(self):
        """Normalize and resolve allowed directory paths"""
        normalized_dirs = []
        for dir_config in self.allowed_directories:
            try:
                # Resolve to absolute path
                normalized_path = dir_config.path.resolve()

                # Create directory if it doesn't exist and creation is allowed
                if dir_config.allow_create and not normalized_path.exists():
                    normalized_path.mkdir(parents=True, exist_ok=True)
                    logger.info("Created allowed directory", path=str(normalized_path))

                normalized_dirs.append(AllowedDirectory(
                    path=normalized_path,
                    allow_subdirs=dir_config.allow_subdirs,
                    allow_symlinks=dir_config.allow_symlinks,
                    allow_create=dir_config.allow_create,
                    description=dir_config.description
                ))

            except Exception as e:
                logger.warning("Failed to normalize allowed directory",
                             path=str(dir_config.path), error=str(e))

        self.allowed_directories = normalized_dirs

    def validate_path(self,
                     path: Union[str, Path],
                     operation: str = "read",
                     must_exist: bool = True) -> PathValidationResult:
        """
        Validate a file path for security and access permissions

        Args:
            path: Path to validate
            operation: Operation type (read, write, delete, etc.)
            must_exist: Whether the path must already exist

        Returns:
            PathValidationResult with validation outcome
        """
        # Convert to Path object
        if isinstance(path, str):
            path = Path(path)

        # Check cache first
        cache_key = f"{path}:{operation}:{must_exist}"
        if self.enable_caching and cache_key in self._validation_cache:
            result, timestamp = self._validation_cache[cache_key]
            if time.time() - timestamp < self.cache_ttl_seconds:
                logger.debug("Path validation cache hit", path=str(path))
                return result

        # Perform validation
        try:
            result = self._validate_path_internal(path, operation, must_exist)

            # Cache result
            if self.enable_caching:
                self._validation_cache[cache_key] = (result, time.time())

            # Audit log
            self._log_path_access(path, operation, result)

            return result

        except Exception as e:
            error_result = PathValidationResult(
                is_valid=False,
                error_message=f"Path validation failed: {str(e)}"
            )

            # Log security event
            self._log_path_access(path, operation, error_result, exception=e)

            return error_result

    def _validate_path_internal(self,
                               path: Path,
                               operation: str,
                               must_exist: bool) -> PathValidationResult:
        """Internal path validation logic"""
        warnings = []

        # Step 1: Check for obvious path traversal patterns
        path_str = str(path)
        if self._contains_path_traversal(path_str):
            raise PathTraversalError(f"Path traversal detected: {path_str}")

        # Step 2: Normalize path (resolve . and .. components)
        try:
            if path.is_absolute():
                normalized_path = path.resolve()
            else:
                # For relative paths, resolve against current working directory
                normalized_path = Path.cwd() / path
                normalized_path = normalized_path.resolve()
        except (OSError, ValueError) as e:
            raise PathValidationError(f"Failed to normalize path: {str(e)}")

        # Step 3: Check if path exists when required
        if must_exist and not normalized_path.exists():
            raise PathValidationError(f"Required path does not exist: {normalized_path}")

        # Step 4: Check for symlinks and resolve them if allowed
        if normalized_path.is_symlink():
            if self.security_level == PathSecurityLevel.STRICT:
                raise SymlinkSecurityError(f"Symlinks not allowed in strict mode: {normalized_path}")

            # Resolve symlink and validate target
            try:
                symlink_target = normalized_path.readlink()
                if symlink_target.is_absolute():
                    resolved_target = symlink_target
                else:
                    resolved_target = (normalized_path.parent / symlink_target).resolve()

                warnings.append(f"Symlink detected: {normalized_path} -> {resolved_target}")

                # Recursively validate symlink target
                target_result = self._validate_path_internal(resolved_target, operation, must_exist)
                if not target_result.is_valid:
                    raise SymlinkSecurityError(f"Symlink target validation failed: {target_result.error_message}")

                warnings.extend(target_result.security_warnings)

            except (OSError, ValueError) as e:
                raise SymlinkSecurityError(f"Failed to resolve symlink: {str(e)}")

        # Step 5: Check directory boundaries
        allowed_dir = self._find_allowed_directory(normalized_path)
        if not allowed_dir:
            raise DirectoryBoundaryError(f"Path not within allowed directories: {normalized_path}")

        # Step 6: Check if symlinks are allowed for this directory
        if normalized_path.is_symlink() and not allowed_dir.allow_symlinks:
            raise SymlinkSecurityError(f"Symlinks not allowed in directory: {allowed_dir.path}")

        # Step 7: Validate operation permissions
        if operation in ("write", "delete", "create") and not allowed_dir.allow_create:
            raise PathValidationError(f"Write operations not allowed in directory: {allowed_dir.path}")

        return PathValidationResult(
            is_valid=True,
            normalized_path=normalized_path,
            security_warnings=warnings
        )

    def _contains_path_traversal(self, path_str: str) -> bool:
        """Check for path traversal patterns in string"""
        dangerous_patterns = [
            "../",
            "..\\",
            "%2e%2e%2f",  # URL encoded ../
            "%2e%2e\\",   # URL encoded ..\
            "..%2f",      # Mixed encoding
            "..%5c",      # Mixed encoding
        ]

        path_lower = path_str.lower()
        return any(pattern in path_lower for pattern in dangerous_patterns)

    def _find_allowed_directory(self, path: Path) -> Optional[AllowedDirectory]:
        """Find which allowed directory contains this path"""
        for allowed_dir in self.allowed_directories:
            try:
                # Check if path is within allowed directory
                path.relative_to(allowed_dir.path)
                return allowed_dir
            except ValueError:
                # Path is not relative to this allowed directory
                continue

        return None

    def _log_path_access(self,
                        path: Path,
                        operation: str,
                        result: PathValidationResult,
                        exception: Exception = None):
        """Log path access for security auditing"""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": str(path),
            "operation": operation,
            "is_valid": result.is_valid,
            "normalized_path": str(result.normalized_path) if result.normalized_path else None,
            "warnings": result.security_warnings,
            "error": result.error_message,
            "exception": str(exception) if exception else None
        }

        self._audit_log.append(log_entry)

        # Keep audit log size manageable
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-500:]  # Keep last 500 entries

        # Log to application logger
        if result.is_valid:
            if result.security_warnings:
                logger.warning("Path validation succeeded with warnings", **log_entry)
            else:
                logger.debug("Path validation succeeded", **log_entry)
        else:
            logger.error("Path validation failed", **log_entry)

    def validate_file_exists_safe(self, path: Union[str, Path]) -> bool:
        """Safely check if a file exists within allowed directories"""
        result = self.validate_path(path, operation="read", must_exist=False)

        if not result.is_valid:
            logger.warning("File existence check failed validation",
                         path=str(path), error=result.error_message)
            return False

        return result.normalized_path.exists() if result.normalized_path else False

    @contextmanager
    def open_safe_file(self,
                      path: Union[str, Path],
                      mode: str = 'r',
                      encoding: Optional[str] = None,
                      **kwargs):
        """
        Safely open a file with path validation

        Usage:
            with path_validator.open_safe_file('/path/to/file', 'r') as f:
                content = f.read()
        """
        # Determine operation type from mode
        operation = "read"
        if any(m in mode for m in ['w', 'a', 'x']):
            operation = "write"

        must_exist = 'r' in mode and 'w' not in mode and 'a' not in mode

        # Validate path
        result = self.validate_path(path, operation=operation, must_exist=must_exist)

        if not result.is_valid:
            raise PathValidationError(f"Cannot open file: {result.error_message}")

        if not result.normalized_path:
            raise PathValidationError("Path validation succeeded but no normalized path returned")

        # Log file access
        logger.info("Opening file with validation",
                   path=str(path),
                   normalized_path=str(result.normalized_path),
                   mode=mode,
                   operation=operation)

        # Open file using validated path
        try:
            if encoding:
                file_obj = open(result.normalized_path, mode, encoding=encoding, **kwargs)
            else:
                file_obj = open(result.normalized_path, mode, **kwargs)

            yield file_obj

        except Exception as e:
            logger.error("File operation failed",
                        path=str(result.normalized_path),
                        mode=mode,
                        error=str(e))
            raise
        finally:
            try:
                if 'file_obj' in locals():
                    file_obj.close()
            except:
                pass

    def get_safe_path(self, path: Union[str, Path]) -> Path:
        """
        Get a validated and normalized path

        Raises:
            PathValidationError: If path validation fails
        """
        result = self.validate_path(path, operation="read", must_exist=False)

        if not result.is_valid:
            raise PathValidationError(f"Path validation failed: {result.error_message}")

        if not result.normalized_path:
            raise PathValidationError("Path validation succeeded but no normalized path returned")

        return result.normalized_path

    def clear_cache(self):
        """Clear the path validation cache"""
        self._validation_cache.clear()
        logger.info("Path validation cache cleared")

    def get_audit_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent path access audit log entries"""
        return self._audit_log[-limit:]

    def add_allowed_directory(self, directory: AllowedDirectory):
        """Add a new allowed directory"""
        # Normalize the new directory
        try:
            normalized_path = directory.path.resolve()

            if directory.allow_create and not normalized_path.exists():
                normalized_path.mkdir(parents=True, exist_ok=True)

            normalized_dir = AllowedDirectory(
                path=normalized_path,
                allow_subdirs=directory.allow_subdirs,
                allow_symlinks=directory.allow_symlinks,
                allow_create=directory.allow_create,
                description=directory.description
            )

            self.allowed_directories.append(normalized_dir)
            self.clear_cache()  # Clear cache since allowed directories changed

            logger.info("Added allowed directory", path=str(normalized_path))

        except Exception as e:
            logger.error("Failed to add allowed directory",
                        path=str(directory.path), error=str(e))
            raise


# Global instance for VoiceHive Hotels
# This can be imported and used throughout the application
voicehive_path_validator = PathValidator(
    security_level=PathSecurityLevel.STRICT,
    enable_caching=True,
    cache_ttl_seconds=300
)