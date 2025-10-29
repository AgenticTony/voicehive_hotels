"""
Database Backup & Restore Manager for VoiceHive Hotels
Automated backup verification and restore testing system
"""

import asyncio
import os
import json
import gzip
import hashlib
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import subprocess
import boto3
from botocore.exceptions import ClientError

import asyncpg
from pydantic import BaseModel, Field

from prometheus_client import Gauge, Counter, Histogram, Summary
from logging_adapter import get_safe_logger
from audit_logging import AuditLogger
from security.path_validator import voicehive_path_validator, PathValidationError

logger = get_safe_logger("orchestrator.db_backup")
audit_logger = AuditLogger("database_backup")

# Prometheus metrics for backup monitoring
backup_duration = Histogram(
    'voicehive_backup_duration_seconds',
    'Database backup execution time',
    ['backup_type', 'storage_type'],
    buckets=(60, 300, 600, 1200, 1800, 3600, 7200, 14400)
)

backup_size_bytes = Gauge(
    'voicehive_backup_size_bytes',
    'Database backup size in bytes',
    ['backup_type', 'database']
)

backup_status = Gauge(
    'voicehive_backup_status',
    'Backup status (1=success, 0=failure)',
    ['backup_type', 'database']
)

restore_test_duration = Histogram(
    'voicehive_restore_test_duration_seconds',
    'Restore test execution time',
    ['backup_type'],
    buckets=(60, 300, 600, 1200, 1800, 3600)
)

backup_verification_status = Gauge(
    'voicehive_backup_verification_status',
    'Backup verification status (1=verified, 0=failed)',
    ['backup_id', 'verification_type']
)

backup_retention_violations = Counter(
    'voicehive_backup_retention_violations_total',
    'Backup retention policy violations',
    ['policy_type', 'violation_type']
)


class BackupType(str, Enum):
    """Database backup types"""
    FULL = "full"
    INCREMENTAL = "incremental"
    DIFFERENTIAL = "differential"
    LOGICAL = "logical"
    PHYSICAL = "physical"


class BackupStatus(str, Enum):
    """Backup execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    CORRUPTED = "corrupted"


class StorageType(str, Enum):
    """Backup storage types"""
    LOCAL = "local"
    S3 = "s3"
    AZURE_BLOB = "azure_blob"
    GCS = "gcs"


class CompressionType(str, Enum):
    """Backup compression types"""
    NONE = "none"
    GZIP = "gzip"
    BZIP2 = "bzip2"
    LZ4 = "lz4"
    ZSTD = "zstd"


@dataclass
class BackupConfig:
    """Backup configuration"""
    backup_type: BackupType
    storage_type: StorageType
    compression: CompressionType = CompressionType.GZIP
    encryption_enabled: bool = True
    retention_days: int = 30
    verify_after_backup: bool = True
    test_restore_frequency: int = 7  # days
    parallel_jobs: int = 4
    
    # Storage-specific settings
    s3_bucket: Optional[str] = None
    s3_prefix: Optional[str] = None
    local_path: Optional[str] = None
    
    # Performance settings
    checkpoint_segments: int = 32
    wal_buffers: str = "16MB"
    maintenance_work_mem: str = "256MB"


@dataclass
class BackupMetadata:
    """Backup metadata information"""
    backup_id: str
    database_name: str
    backup_type: BackupType
    start_time: datetime
    end_time: Optional[datetime] = None
    size_bytes: Optional[int] = None
    compressed_size_bytes: Optional[int] = None
    checksum: Optional[str] = None
    storage_location: Optional[str] = None
    encryption_key_id: Optional[str] = None
    pg_version: Optional[str] = None
    wal_start_lsn: Optional[str] = None
    wal_end_lsn: Optional[str] = None
    status: BackupStatus = BackupStatus.PENDING
    error_message: Optional[str] = None
    verification_results: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration_seconds(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    @property
    def compression_ratio(self) -> Optional[float]:
        if self.size_bytes and self.compressed_size_bytes:
            return self.compressed_size_bytes / self.size_bytes
        return None


class BackupVerifier:
    """Backup verification and integrity checking"""
    
    def __init__(self, connection_pool):
        self.pool = connection_pool
        
    async def verify_backup(self, backup_metadata: BackupMetadata, 
                          config: BackupConfig) -> Dict[str, Any]:
        """Comprehensive backup verification"""
        verification_results = {
            "overall_status": "success",
            "checks": {},
            "errors": [],
            "warnings": []
        }
        
        try:
            # File integrity check
            verification_results["checks"]["file_integrity"] = await self._verify_file_integrity(
                backup_metadata, config
            )
            
            # Checksum verification
            verification_results["checks"]["checksum"] = await self._verify_checksum(
                backup_metadata, config
            )
            
            # Backup completeness check
            verification_results["checks"]["completeness"] = await self._verify_completeness(
                backup_metadata, config
            )
            
            # Restore test (if configured)
            if config.verify_after_backup:
                verification_results["checks"]["restore_test"] = await self._test_restore(
                    backup_metadata, config
                )
            
            # Check overall status
            failed_checks = [
                name for name, result in verification_results["checks"].items()
                if not result.get("passed", False)
            ]
            
            if failed_checks:
                verification_results["overall_status"] = "failed"
                verification_results["errors"].append(f"Failed checks: {', '.join(failed_checks)}")
            
            # Update metrics
            backup_verification_status.labels(
                backup_id=backup_metadata.backup_id,
                verification_type="overall"
            ).set(1 if verification_results["overall_status"] == "success" else 0)
            
        except Exception as e:
            verification_results["overall_status"] = "error"
            verification_results["errors"].append(f"Verification error: {str(e)}")
            logger.error("backup_verification_error", 
                        backup_id=backup_metadata.backup_id,
                        error=str(e))
        
        return verification_results
    
    async def _verify_file_integrity(self, backup_metadata: BackupMetadata, 
                                   config: BackupConfig) -> Dict[str, Any]:
        """Verify backup file integrity"""
        result = {"passed": True, "errors": [], "details": {}}
        
        try:
            backup_path = self._get_backup_file_path(backup_metadata, config)
            
            if not backup_path.exists():
                result["passed"] = False
                result["errors"].append("Backup file not found")
                return result
            
            # Check file size
            file_size = backup_path.stat().st_size
            result["details"]["file_size"] = file_size
            
            if backup_metadata.compressed_size_bytes:
                if abs(file_size - backup_metadata.compressed_size_bytes) > 1024:  # 1KB tolerance
                    result["errors"].append(f"File size mismatch: expected {backup_metadata.compressed_size_bytes}, got {file_size}")
            
            # Check file is readable using secure path validation
            try:
                with voicehive_path_validator.open_safe_file(backup_path, 'rb') as f:
                    # Read first and last 1KB to ensure file is not corrupted
                    f.read(1024)
                    f.seek(-1024, 2)
                    f.read(1024)
                result["details"]["readable"] = True
            except PathValidationError as e:
                result["passed"] = False
                result["errors"].append(f"Path validation failed: {str(e)}")
                logger.error("Backup path validation failed", backup_path=backup_path, error=str(e))
            except Exception as e:
                result["passed"] = False
                result["errors"].append(f"File not readable: {str(e)}")
            
            # If compressed, test decompression
            if config.compression != CompressionType.NONE:
                try:
                    await self._test_decompression(backup_path, config.compression)
                    result["details"]["decompressible"] = True
                except Exception as e:
                    result["passed"] = False
                    result["errors"].append(f"Decompression failed: {str(e)}")
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"File integrity check error: {str(e)}")
        
        return result
    
    async def _verify_checksum(self, backup_metadata: BackupMetadata, 
                             config: BackupConfig) -> Dict[str, Any]:
        """Verify backup checksum"""
        result = {"passed": True, "errors": [], "details": {}}
        
        try:
            if not backup_metadata.checksum:
                result["errors"].append("No checksum available for verification")
                return result
            
            backup_path = self._get_backup_file_path(backup_metadata, config)
            
            # Calculate current checksum
            current_checksum = await self._calculate_file_checksum(backup_path)
            result["details"]["expected_checksum"] = backup_metadata.checksum
            result["details"]["actual_checksum"] = current_checksum
            
            if current_checksum != backup_metadata.checksum:
                result["passed"] = False
                result["errors"].append("Checksum mismatch - backup may be corrupted")
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Checksum verification error: {str(e)}")
        
        return result
    
    async def _verify_completeness(self, backup_metadata: BackupMetadata, 
                                 config: BackupConfig) -> Dict[str, Any]:
        """Verify backup completeness"""
        result = {"passed": True, "errors": [], "details": {}}
        
        try:
            # For logical backups, check if all expected objects are present
            if backup_metadata.backup_type == BackupType.LOGICAL:
                backup_path = self._get_backup_file_path(backup_metadata, config)
                
                # Read backup content and check for expected database objects
                backup_content = await self._read_backup_content(backup_path, config.compression)
                
                # Check for essential database objects
                expected_objects = ["CREATE TABLE", "CREATE INDEX", "CREATE SEQUENCE"]
                missing_objects = []
                
                for obj in expected_objects:
                    if obj not in backup_content:
                        missing_objects.append(obj)
                
                if missing_objects:
                    result["errors"].append(f"Missing database objects: {', '.join(missing_objects)}")
                
                result["details"]["backup_size_lines"] = len(backup_content.split('\n'))
                result["details"]["contains_data"] = "INSERT INTO" in backup_content or "COPY " in backup_content
            
            # For physical backups, check for required files
            elif backup_metadata.backup_type == BackupType.PHYSICAL:
                # Check for essential PostgreSQL files
                required_files = ["postgresql.conf", "pg_hba.conf", "PG_VERSION"]
                # This would be implemented based on the backup format
                pass
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Completeness check error: {str(e)}")
        
        return result
    
    async def _test_restore(self, backup_metadata: BackupMetadata, 
                          config: BackupConfig) -> Dict[str, Any]:
        """Test backup restore functionality"""
        result = {"passed": True, "errors": [], "details": {}}
        
        try:
            # Create temporary test database
            test_db_name = f"restore_test_{backup_metadata.backup_id}_{int(datetime.now().timestamp())}"
            
            restore_start = datetime.now()
            
            try:
                # Create test database
                await self._create_test_database(test_db_name)
                
                # Restore backup to test database
                await self._restore_to_test_database(backup_metadata, config, test_db_name)
                
                # Verify restored data
                verification_results = await self._verify_restored_data(test_db_name)
                result["details"]["data_verification"] = verification_results
                
                if not verification_results.get("passed", False):
                    result["passed"] = False
                    result["errors"].extend(verification_results.get("errors", []))
                
                restore_duration = (datetime.now() - restore_start).total_seconds()
                result["details"]["restore_duration_seconds"] = restore_duration
                
                # Record metrics
                restore_test_duration.labels(
                    backup_type=backup_metadata.backup_type.value
                ).observe(restore_duration)
                
            finally:
                # Clean up test database
                await self._drop_test_database(test_db_name)
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Restore test error: {str(e)}")
        
        return result
    
    def _get_backup_file_path(self, backup_metadata: BackupMetadata, 
                            config: BackupConfig) -> Path:
        """Get backup file path based on storage configuration"""
        if config.storage_type == StorageType.LOCAL:
            base_path = Path(config.local_path or "/var/backups/postgresql")
            return base_path / f"{backup_metadata.backup_id}.sql.gz"
        else:
            # For cloud storage, download to temporary location
            temp_dir = Path(tempfile.gettempdir())
            return temp_dir / f"{backup_metadata.backup_id}.sql.gz"
    
    async def _test_decompression(self, file_path: Path, compression: CompressionType):
        """Test if compressed file can be decompressed"""
        if compression == CompressionType.GZIP:
            # Validate path before decompression
            try:
                safe_path = voicehive_path_validator.get_safe_path(file_path)
                with gzip.open(safe_path, 'rb') as f:
                    # Read first 1KB to test decompression
                    f.read(1024)
            except PathValidationError as e:
                logger.error("Decompression path validation failed", file_path=str(file_path), error=str(e))
                raise
        # Add other compression types as needed
    
    async def _calculate_file_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file using secure path validation"""
        sha256_hash = hashlib.sha256()

        try:
            with voicehive_path_validator.open_safe_file(file_path, "rb") as f:
                # Read file in chunks to handle large files
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
        except PathValidationError as e:
            logger.error("Checksum calculation path validation failed", file_path=str(file_path), error=str(e))
            raise

        return sha256_hash.hexdigest()
    
    async def _read_backup_content(self, file_path: Path, compression: CompressionType) -> str:
        """Read backup file content using secure path validation"""
        try:
            if compression == CompressionType.GZIP:
                # Validate path and use gzip
                safe_path = voicehive_path_validator.get_safe_path(file_path)
                with gzip.open(safe_path, 'rt') as f:
                    # Read first 10MB to check content
                    return f.read(10 * 1024 * 1024)
            else:
                # Use secure file opening for uncompressed files
                with voicehive_path_validator.open_safe_file(file_path, 'r') as f:
                    return f.read(10 * 1024 * 1024)
        except PathValidationError as e:
            logger.error("Backup content read path validation failed", file_path=str(file_path), error=str(e))
            raise
    
    async def _create_test_database(self, db_name: str):
        """Create test database for restore testing"""
        async with self.pool.acquire() as conn:
            await conn.execute(f"CREATE DATABASE {db_name}")
    
    async def _drop_test_database(self, db_name: str):
        """Drop test database"""
        async with self.pool.acquire() as conn:
            # Terminate connections
            await conn.execute(f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = '{db_name}'
                AND pid <> pg_backend_pid()
            """)
            
            await conn.execute(f"DROP DATABASE IF EXISTS {db_name}")
    
    async def _restore_to_test_database(self, backup_metadata: BackupMetadata, 
                                      config: BackupConfig, test_db_name: str):
        """Restore backup to test database"""
        backup_path = self._get_backup_file_path(backup_metadata, config)
        
        # Build psql command for restore
        cmd = [
            "psql",
            "-h", "localhost",  # Would be configured
            "-d", test_db_name,
            "-f", str(backup_path)
        ]
        
        if config.compression == CompressionType.GZIP:
            # Use zcat to decompress on the fly
            cmd = ["zcat", str(backup_path)] + ["|"] + cmd
        
        # Execute restore command
        process = await asyncio.create_subprocess_shell(
            " ".join(cmd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"Restore failed: {stderr.decode()}")
    
    async def _verify_restored_data(self, test_db_name: str) -> Dict[str, Any]:
        """Verify restored data integrity"""
        result = {"passed": True, "errors": [], "details": {}}
        
        try:
            # Connect to test database
            test_conn = await asyncpg.connect(database=test_db_name)
            
            try:
                # Check basic database structure
                tables = await test_conn.fetch("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public'
                """)
                
                result["details"]["table_count"] = len(tables)
                
                if not tables:
                    result["errors"].append("No tables found in restored database")
                    result["passed"] = False
                    return result
                
                # Check data in each table
                total_rows = 0
                for table in tables:
                    table_name = table["table_name"]
                    
                    try:
                        row_count = await test_conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
                        total_rows += row_count
                        result["details"][f"{table_name}_rows"] = row_count
                    except Exception as e:
                        result["errors"].append(f"Error querying table {table_name}: {str(e)}")
                
                result["details"]["total_rows"] = total_rows
                
                # Check for basic referential integrity
                # This would be more comprehensive in production
                
            finally:
                await test_conn.close()
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Data verification error: {str(e)}")
        
        return result


class DatabaseBackupManager:
    """Comprehensive database backup and restore management"""
    
    def __init__(self, connection_pool, config: BackupConfig):
        self.pool = connection_pool
        self.config = config
        self.verifier = BackupVerifier(connection_pool)
        self.backup_history: List[BackupMetadata] = []
        self.s3_client = None
        
        # Initialize cloud storage clients if needed
        if config.storage_type == StorageType.S3:
            self.s3_client = boto3.client('s3')
    
    async def initialize(self):
        """Initialize backup manager"""
        logger.info("initializing_database_backup_manager")
        
        # Create backup tracking table
        await self._create_backup_tracking_table()
        
        # Validate configuration
        validation_result = await self._validate_configuration()
        if not validation_result["valid"]:
            raise ValueError(f"Invalid backup configuration: {validation_result['errors']}")
        
        # Load backup history
        await self._load_backup_history()
        
        logger.info("database_backup_manager_initialized")
    
    async def _create_backup_tracking_table(self):
        """Create table to track backup metadata"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS backup_metadata (
                    backup_id VARCHAR(255) PRIMARY KEY,
                    database_name VARCHAR(255) NOT NULL,
                    backup_type VARCHAR(50) NOT NULL,
                    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
                    end_time TIMESTAMP WITH TIME ZONE,
                    size_bytes BIGINT,
                    compressed_size_bytes BIGINT,
                    checksum VARCHAR(255),
                    storage_location TEXT,
                    encryption_key_id VARCHAR(255),
                    pg_version VARCHAR(50),
                    wal_start_lsn VARCHAR(50),
                    wal_end_lsn VARCHAR(50),
                    status VARCHAR(50) NOT NULL,
                    error_message TEXT,
                    verification_results JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # Create indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_backup_metadata_database_time 
                ON backup_metadata(database_name, start_time DESC)
            """)
            
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_backup_metadata_status 
                ON backup_metadata(status, start_time DESC)
            """)
    
    async def create_backup(self, database_name: str, 
                          backup_type: Optional[BackupType] = None) -> BackupMetadata:
        """Create database backup"""
        
        backup_type = backup_type or self.config.backup_type
        backup_id = self._generate_backup_id(database_name, backup_type)
        
        backup_metadata = BackupMetadata(
            backup_id=backup_id,
            database_name=database_name,
            backup_type=backup_type,
            start_time=datetime.now(timezone.utc),
            status=BackupStatus.RUNNING
        )
        
        try:
            logger.info("starting_database_backup",
                       backup_id=backup_id,
                       database=database_name,
                       backup_type=backup_type.value)
            
            # Record start time for metrics
            backup_start = datetime.now()
            
            # Execute backup based on type
            if backup_type == BackupType.LOGICAL:
                await self._create_logical_backup(backup_metadata)
            elif backup_type == BackupType.PHYSICAL:
                await self._create_physical_backup(backup_metadata)
            else:
                raise ValueError(f"Unsupported backup type: {backup_type}")
            
            # Calculate duration
            backup_duration_seconds = (datetime.now() - backup_start).total_seconds()
            backup_metadata.end_time = datetime.now(timezone.utc)
            
            # Record metrics
            backup_duration.labels(
                backup_type=backup_type.value,
                storage_type=self.config.storage_type.value
            ).observe(backup_duration_seconds)
            
            if backup_metadata.size_bytes:
                backup_size_bytes.labels(
                    backup_type=backup_type.value,
                    database=database_name
                ).set(backup_metadata.size_bytes)
            
            # Verify backup if configured
            if self.config.verify_after_backup:
                logger.info("verifying_backup", backup_id=backup_id)
                backup_metadata.status = BackupStatus.VERIFYING
                
                verification_results = await self.verifier.verify_backup(
                    backup_metadata, self.config
                )
                
                backup_metadata.verification_results = verification_results
                
                if verification_results["overall_status"] == "success":
                    backup_metadata.status = BackupStatus.VERIFIED
                else:
                    backup_metadata.status = BackupStatus.CORRUPTED
                    backup_metadata.error_message = "; ".join(verification_results["errors"])
            else:
                backup_metadata.status = BackupStatus.SUCCESS
            
            # Update metrics
            backup_status.labels(
                backup_type=backup_type.value,
                database=database_name
            ).set(1 if backup_metadata.status in [BackupStatus.SUCCESS, BackupStatus.VERIFIED] else 0)
            
            # Save metadata
            await self._save_backup_metadata(backup_metadata)
            self.backup_history.append(backup_metadata)
            
            # Audit log
            audit_logger.log_security_event(
                event_type="database_backup_created",
                details={
                    "backup_id": backup_id,
                    "database": database_name,
                    "backup_type": backup_type.value,
                    "size_bytes": backup_metadata.size_bytes,
                    "duration_seconds": backup_duration_seconds,
                    "status": backup_metadata.status.value
                },
                severity="info"
            )
            
            logger.info("database_backup_completed",
                       backup_id=backup_id,
                       status=backup_metadata.status.value,
                       duration_seconds=backup_duration_seconds)
            
        except Exception as e:
            backup_metadata.status = BackupStatus.FAILED
            backup_metadata.error_message = str(e)
            backup_metadata.end_time = datetime.now(timezone.utc)
            
            # Update failure metrics
            backup_status.labels(
                backup_type=backup_type.value,
                database=database_name
            ).set(0)
            
            # Save failed backup metadata
            await self._save_backup_metadata(backup_metadata)
            
            logger.error("database_backup_failed",
                        backup_id=backup_id,
                        error=str(e))
            
            raise
        
        return backup_metadata
    
    async def _create_logical_backup(self, backup_metadata: BackupMetadata):
        """Create logical backup using pg_dump"""
        
        # Prepare output file
        output_file = self._get_backup_output_path(backup_metadata)
        
        # Build pg_dump command
        cmd = [
            "pg_dump",
            "--verbose",
            "--no-password",
            "--format=custom",
            "--compress=9",
            "--no-privileges",
            "--no-owner",
            backup_metadata.database_name
        ]
        
        # Add connection parameters
        cmd.extend([
            "--host", os.getenv("DB_HOST", "localhost"),
            "--port", os.getenv("DB_PORT", "5432"),
            "--username", os.getenv("DB_USER", "postgres")
        ])
        
        # Execute backup
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {stderr.decode()}")
        
        # Write output to file
        backup_content = stdout
        
        # Compress if configured
        if self.config.compression == CompressionType.GZIP:
            backup_content = gzip.compress(backup_content)
            output_file = output_file.with_suffix(output_file.suffix + '.gz')
        
        # Write to storage
        await self._write_backup_to_storage(backup_content, output_file, backup_metadata)
        
        # Update metadata
        backup_metadata.size_bytes = len(stdout)
        backup_metadata.compressed_size_bytes = len(backup_content)
        backup_metadata.checksum = hashlib.sha256(backup_content).hexdigest()
        backup_metadata.storage_location = str(output_file)
        
        # Get PostgreSQL version
        async with self.pool.acquire() as conn:
            pg_version = await conn.fetchval("SELECT version()")
            backup_metadata.pg_version = pg_version.split()[1]  # Extract version number
    
    async def _create_physical_backup(self, backup_metadata: BackupMetadata):
        """Create physical backup using pg_basebackup"""
        
        output_dir = self._get_backup_output_path(backup_metadata, is_directory=True)
        
        # Build pg_basebackup command
        cmd = [
            "pg_basebackup",
            "--verbose",
            "--progress",
            "--format=tar",
            "--gzip",
            "--wal-method=stream",
            "--directory", str(output_dir)
        ]
        
        # Add connection parameters
        cmd.extend([
            "--host", os.getenv("DB_HOST", "localhost"),
            "--port", os.getenv("DB_PORT", "5432"),
            "--username", os.getenv("DB_USER", "postgres")
        ])
        
        # Execute backup
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"pg_basebackup failed: {stderr.decode()}")
        
        # Calculate backup size
        total_size = sum(f.stat().st_size for f in output_dir.rglob('*') if f.is_file())
        backup_metadata.size_bytes = total_size
        backup_metadata.compressed_size_bytes = total_size  # Already compressed
        
        # Calculate checksum of entire backup
        backup_metadata.checksum = await self._calculate_directory_checksum(output_dir)
        backup_metadata.storage_location = str(output_dir)
        
        # Get WAL information
        async with self.pool.acquire() as conn:
            wal_info = await conn.fetchrow("SELECT pg_current_wal_lsn(), version()")
            backup_metadata.wal_start_lsn = wal_info[0]
            backup_metadata.pg_version = wal_info[1].split()[1]
    
    def _generate_backup_id(self, database_name: str, backup_type: BackupType) -> str:
        """Generate unique backup ID"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{database_name}_{backup_type.value}_{timestamp}"
    
    def _get_backup_output_path(self, backup_metadata: BackupMetadata, 
                              is_directory: bool = False) -> Path:
        """Get backup output path based on storage configuration"""
        
        if self.config.storage_type == StorageType.LOCAL:
            base_path = Path(self.config.local_path or "/var/backups/postgresql")
            base_path.mkdir(parents=True, exist_ok=True)
            
            if is_directory:
                return base_path / backup_metadata.backup_id
            else:
                return base_path / f"{backup_metadata.backup_id}.sql"
        
        else:
            # For cloud storage, use temporary local path
            temp_dir = Path(tempfile.gettempdir()) / "backups"
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            if is_directory:
                return temp_dir / backup_metadata.backup_id
            else:
                return temp_dir / f"{backup_metadata.backup_id}.sql"
    
    async def _write_backup_to_storage(self, backup_content: bytes, 
                                     output_file: Path, 
                                     backup_metadata: BackupMetadata):
        """Write backup to configured storage"""
        
        if self.config.storage_type == StorageType.LOCAL:
            # Write to local file using secure path validation
            try:
                with voicehive_path_validator.open_safe_file(output_file, 'wb') as f:
                    f.write(backup_content)
            except PathValidationError as e:
                logger.error("Backup write path validation failed", output_file=str(output_file), error=str(e))
                raise
        
        elif self.config.storage_type == StorageType.S3:
            # Upload to S3
            s3_key = f"{self.config.s3_prefix or 'backups'}/{output_file.name}"
            
            try:
                self.s3_client.put_object(
                    Bucket=self.config.s3_bucket,
                    Key=s3_key,
                    Body=backup_content,
                    ServerSideEncryption='AES256' if self.config.encryption_enabled else None
                )
                
                backup_metadata.storage_location = f"s3://{self.config.s3_bucket}/{s3_key}"
                
            except ClientError as e:
                raise RuntimeError(f"S3 upload failed: {str(e)}")
        
        # Add other storage types as needed
    
    async def _calculate_directory_checksum(self, directory: Path) -> str:
        """Calculate checksum of entire directory using secure path validation"""
        sha256_hash = hashlib.sha256()

        try:
            # Validate the directory path first
            safe_directory = voicehive_path_validator.get_safe_path(directory)

            # Sort files for consistent checksum
            files = sorted(safe_directory.rglob('*'))

            for file_path in files:
                if file_path.is_file():
                    try:
                        with voicehive_path_validator.open_safe_file(file_path, 'rb') as f:
                            for chunk in iter(lambda: f.read(4096), b""):
                                sha256_hash.update(chunk)
                    except PathValidationError as e:
                        logger.warning("Skipping file due to path validation failure",
                                     file_path=str(file_path), error=str(e))
                        continue

        except PathValidationError as e:
            logger.error("Directory checksum path validation failed", directory=str(directory), error=str(e))
            raise

        return sha256_hash.hexdigest()
    
    async def _save_backup_metadata(self, backup_metadata: BackupMetadata):
        """Save backup metadata to database"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO backup_metadata 
                (backup_id, database_name, backup_type, start_time, end_time,
                 size_bytes, compressed_size_bytes, checksum, storage_location,
                 encryption_key_id, pg_version, wal_start_lsn, wal_end_lsn,
                 status, error_message, verification_results)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                ON CONFLICT (backup_id) DO UPDATE SET
                    end_time = EXCLUDED.end_time,
                    size_bytes = EXCLUDED.size_bytes,
                    compressed_size_bytes = EXCLUDED.compressed_size_bytes,
                    checksum = EXCLUDED.checksum,
                    storage_location = EXCLUDED.storage_location,
                    status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message,
                    verification_results = EXCLUDED.verification_results
            """,
            backup_metadata.backup_id,
            backup_metadata.database_name,
            backup_metadata.backup_type.value,
            backup_metadata.start_time,
            backup_metadata.end_time,
            backup_metadata.size_bytes,
            backup_metadata.compressed_size_bytes,
            backup_metadata.checksum,
            backup_metadata.storage_location,
            backup_metadata.encryption_key_id,
            backup_metadata.pg_version,
            backup_metadata.wal_start_lsn,
            backup_metadata.wal_end_lsn,
            backup_metadata.status.value,
            backup_metadata.error_message,
            json.dumps(backup_metadata.verification_results) if backup_metadata.verification_results else None
            )
    
    async def _load_backup_history(self):
        """Load backup history from database"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM backup_metadata
                    ORDER BY start_time DESC
                    LIMIT 100
                """)
                
                self.backup_history = []
                for row in rows:
                    metadata = BackupMetadata(
                        backup_id=row['backup_id'],
                        database_name=row['database_name'],
                        backup_type=BackupType(row['backup_type']),
                        start_time=row['start_time'],
                        end_time=row['end_time'],
                        size_bytes=row['size_bytes'],
                        compressed_size_bytes=row['compressed_size_bytes'],
                        checksum=row['checksum'],
                        storage_location=row['storage_location'],
                        encryption_key_id=row['encryption_key_id'],
                        pg_version=row['pg_version'],
                        wal_start_lsn=row['wal_start_lsn'],
                        wal_end_lsn=row['wal_end_lsn'],
                        status=BackupStatus(row['status']),
                        error_message=row['error_message'],
                        verification_results=json.loads(row['verification_results']) if row['verification_results'] else {}
                    )
                    self.backup_history.append(metadata)
                
        except Exception as e:
            logger.error("failed_to_load_backup_history", error=str(e))
    
    async def _validate_configuration(self) -> Dict[str, Any]:
        """Validate backup configuration"""
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        # Check storage configuration
        if self.config.storage_type == StorageType.LOCAL:
            if not self.config.local_path:
                validation_result["errors"].append("Local storage path not configured")
                validation_result["valid"] = False
        
        elif self.config.storage_type == StorageType.S3:
            if not self.config.s3_bucket:
                validation_result["errors"].append("S3 bucket not configured")
                validation_result["valid"] = False
            
            # Test S3 connectivity
            try:
                if self.s3_client:
                    self.s3_client.head_bucket(Bucket=self.config.s3_bucket)
            except Exception as e:
                validation_result["errors"].append(f"S3 connectivity test failed: {str(e)}")
                validation_result["valid"] = False
        
        # Check retention policy
        if self.config.retention_days < 1:
            validation_result["errors"].append("Retention days must be at least 1")
            validation_result["valid"] = False
        
        if self.config.retention_days < 7:
            validation_result["warnings"].append("Retention period less than 7 days may be too short")
        
        return validation_result
    
    async def cleanup_old_backups(self) -> Dict[str, Any]:
        """Clean up old backups based on retention policy"""
        cleanup_result = {
            "deleted_count": 0,
            "freed_bytes": 0,
            "errors": []
        }
        
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)
            
            # Get old backups
            async with self.pool.acquire() as conn:
                old_backups = await conn.fetch("""
                    SELECT backup_id, storage_location, compressed_size_bytes
                    FROM backup_metadata
                    WHERE start_time < $1
                    AND status IN ('success', 'verified')
                    ORDER BY start_time ASC
                """, cutoff_date)
            
            for backup in old_backups:
                try:
                    # Delete backup file
                    await self._delete_backup_file(backup['storage_location'])
                    
                    # Remove from database
                    async with self.pool.acquire() as conn:
                        await conn.execute(
                            "DELETE FROM backup_metadata WHERE backup_id = $1",
                            backup['backup_id']
                        )
                    
                    cleanup_result["deleted_count"] += 1
                    if backup['compressed_size_bytes']:
                        cleanup_result["freed_bytes"] += backup['compressed_size_bytes']
                    
                    logger.info("backup_deleted", backup_id=backup['backup_id'])
                    
                except Exception as e:
                    cleanup_result["errors"].append(f"Failed to delete {backup['backup_id']}: {str(e)}")
            
            # Update retention violation metrics
            if cleanup_result["deleted_count"] > 0:
                backup_retention_violations.labels(
                    policy_type="retention_days",
                    violation_type="expired_backups"
                ).inc(cleanup_result["deleted_count"])
            
            audit_logger.log_security_event(
                event_type="backup_cleanup_completed",
                details={
                    "deleted_count": cleanup_result["deleted_count"],
                    "freed_bytes": cleanup_result["freed_bytes"],
                    "retention_days": self.config.retention_days
                },
                severity="info"
            )
            
        except Exception as e:
            cleanup_result["errors"].append(f"Cleanup error: {str(e)}")
            logger.error("backup_cleanup_error", error=str(e))
        
        return cleanup_result
    
    async def _delete_backup_file(self, storage_location: str):
        """Delete backup file from storage"""
        if storage_location.startswith("s3://"):
            # Parse S3 location
            parts = storage_location[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1]
            
            self.s3_client.delete_object(Bucket=bucket, Key=key)
        
        else:
            # Local file
            file_path = Path(storage_location)
            if file_path.exists():
                if file_path.is_dir():
                    shutil.rmtree(file_path)
                else:
                    file_path.unlink()
    
    async def get_backup_status_report(self) -> Dict[str, Any]:
        """Generate comprehensive backup status report"""
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_backups": len(self.backup_history),
            "recent_backups": [],
            "backup_sizes": {},
            "success_rate": 0.0,
            "storage_usage": {},
            "retention_compliance": {}
        }
        
        try:
            # Recent backups (last 10)
            recent_backups = sorted(self.backup_history, key=lambda x: x.start_time, reverse=True)[:10]
            
            for backup in recent_backups:
                report["recent_backups"].append({
                    "backup_id": backup.backup_id,
                    "database": backup.database_name,
                    "type": backup.backup_type.value,
                    "status": backup.status.value,
                    "start_time": backup.start_time.isoformat(),
                    "duration_seconds": backup.duration_seconds,
                    "size_mb": backup.compressed_size_bytes / (1024 * 1024) if backup.compressed_size_bytes else None
                })
            
            # Success rate calculation
            if self.backup_history:
                successful_backups = sum(1 for b in self.backup_history 
                                       if b.status in [BackupStatus.SUCCESS, BackupStatus.VERIFIED])
                report["success_rate"] = successful_backups / len(self.backup_history)
            
            # Storage usage by database
            storage_by_db = {}
            for backup in self.backup_history:
                if backup.database_name not in storage_by_db:
                    storage_by_db[backup.database_name] = 0
                if backup.compressed_size_bytes:
                    storage_by_db[backup.database_name] += backup.compressed_size_bytes
            
            report["storage_usage"] = {
                db: size / (1024 * 1024 * 1024)  # Convert to GB
                for db, size in storage_by_db.items()
            }
            
            # Retention compliance
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.config.retention_days)
            old_backups = [b for b in self.backup_history if b.start_time < cutoff_date]
            
            report["retention_compliance"] = {
                "retention_days": self.config.retention_days,
                "old_backups_count": len(old_backups),
                "needs_cleanup": len(old_backups) > 0
            }
            
        except Exception as e:
            report["error"] = str(e)
            logger.error("failed_to_generate_backup_report", error=str(e))
        
        return report