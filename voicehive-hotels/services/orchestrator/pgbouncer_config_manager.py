"""
PgBouncer Configuration Manager for VoiceHive Hotels
Production-grade connection pooling with pgBouncer integration
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import configparser
import tempfile
import subprocess

import asyncpg
from pydantic import BaseModel, Field, field_validator

from prometheus_client import Gauge, Counter, Histogram
from logging_adapter import get_safe_logger
from audit_logging import AuditLogger

logger = get_safe_logger("orchestrator.pgbouncer")
audit_logger = AuditLogger("pgbouncer_config")

# Prometheus metrics for pgBouncer monitoring
pgbouncer_connections = Gauge(
    'voicehive_pgbouncer_connections',
    'PgBouncer connection counts',
    ['pool_name', 'connection_type']
)

pgbouncer_pool_size = Gauge(
    'voicehive_pgbouncer_pool_size',
    'PgBouncer pool size',
    ['pool_name', 'metric_type']
)

pgbouncer_query_duration = Histogram(
    'voicehive_pgbouncer_query_duration_seconds',
    'Query duration through pgBouncer',
    ['pool_name'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

pgbouncer_errors = Counter(
    'voicehive_pgbouncer_errors_total',
    'PgBouncer errors',
    ['pool_name', 'error_type']
)

pgbouncer_config_reloads = Counter(
    'voicehive_pgbouncer_config_reloads_total',
    'PgBouncer configuration reloads',
    ['status']
)


class PoolMode(str, Enum):
    """PgBouncer pool modes"""
    SESSION = "session"
    TRANSACTION = "transaction"
    STATEMENT = "statement"


class AuthType(str, Enum):
    """PgBouncer authentication types"""
    MD5 = "md5"
    SCRAM_SHA_256 = "scram-sha-256"
    PLAIN = "plain"
    TRUST = "trust"
    ANY = "any"


@dataclass
class DatabaseConfig:
    """Database configuration for pgBouncer"""
    name: str
    host: str
    port: int
    dbname: str
    user: str
    password: str
    pool_size: int = 25
    reserve_pool: int = 5
    max_db_connections: int = 50
    
    def to_pgbouncer_line(self) -> str:
        """Convert to pgBouncer database configuration line"""
        return f"{self.name} = host={self.host} port={self.port} dbname={self.dbname} user={self.user} password={self.password} pool_size={self.pool_size} reserve_pool={self.reserve_pool} max_db_connections={self.max_db_connections}"


class PgBouncerConfig(BaseModel):
    """PgBouncer configuration model"""
    
    # Connection settings
    listen_addr: str = Field(default="*", description="Listen address")
    listen_port: int = Field(default=6432, ge=1024, le=65535, description="Listen port")
    
    # Pool settings
    pool_mode: PoolMode = Field(default=PoolMode.TRANSACTION, description="Pool mode")
    default_pool_size: int = Field(default=25, ge=1, le=1000, description="Default pool size")
    min_pool_size: int = Field(default=5, ge=0, le=100, description="Minimum pool size")
    reserve_pool_size: int = Field(default=5, ge=0, le=100, description="Reserve pool size")
    reserve_pool_timeout: int = Field(default=5, ge=1, le=60, description="Reserve pool timeout")
    
    # Connection limits
    max_client_conn: int = Field(default=1000, ge=1, le=10000, description="Maximum client connections")
    max_db_connections: int = Field(default=100, ge=1, le=1000, description="Maximum database connections")
    max_user_connections: int = Field(default=100, ge=1, le=1000, description="Maximum user connections")
    
    # Timeouts
    server_round_robin: bool = Field(default=True, description="Use round-robin for servers")
    server_idle_timeout: int = Field(default=600, ge=0, le=3600, description="Server idle timeout")
    server_connect_timeout: int = Field(default=15, ge=1, le=60, description="Server connect timeout")
    server_login_retry: int = Field(default=15, ge=1, le=60, description="Server login retry")
    client_idle_timeout: int = Field(default=0, ge=0, le=3600, description="Client idle timeout")
    client_login_timeout: int = Field(default=60, ge=1, le=300, description="Client login timeout")
    
    # Query settings
    query_timeout: int = Field(default=0, ge=0, le=3600, description="Query timeout")
    query_wait_timeout: int = Field(default=120, ge=1, le=600, description="Query wait timeout")
    cancel_wait_timeout: int = Field(default=10, ge=1, le=60, description="Cancel wait timeout")
    
    # Authentication
    auth_type: AuthType = Field(default=AuthType.MD5, description="Authentication type")
    auth_file: Optional[str] = Field(None, description="Authentication file path")
    auth_hba_file: Optional[str] = Field(None, description="HBA file path")
    
    # Logging
    log_connections: bool = Field(default=True, description="Log connections")
    log_disconnections: bool = Field(default=True, description="Log disconnections")
    log_pooler_errors: bool = Field(default=True, description="Log pooler errors")
    log_stats: bool = Field(default=True, description="Log statistics")
    stats_period: int = Field(default=60, ge=10, le=3600, description="Statistics period")
    
    # Security
    ignore_startup_parameters: List[str] = Field(
        default_factory=lambda: ["extra_float_digits", "search_path"],
        description="Parameters to ignore"
    )
    
    # Performance
    pkt_buf: int = Field(default=4096, ge=1024, le=65536, description="Packet buffer size")
    listen_backlog: int = Field(default=128, ge=1, le=1000, description="Listen backlog")
    sbuf_loopcnt: int = Field(default=5, ge=1, le=100, description="Socket buffer loop count")
    
    @field_validator('pool_mode')
    @classmethod
    def validate_pool_mode(cls, v):
        """Validate pool mode for production use"""
        if v == PoolMode.STATEMENT:
            logger.warning("statement_pooling_not_recommended_for_production")
        return v
    
    @field_validator('default_pool_size', 'min_pool_size', 'reserve_pool_size')
    @classmethod
    def validate_pool_sizes(cls, v, info):
        """Validate pool size relationships"""
        return v


class PgBouncerConfigManager:
    """PgBouncer configuration manager with production-grade features"""
    
    def __init__(self, config_dir: str = "/etc/pgbouncer"):
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "pgbouncer.ini"
        self.auth_file = self.config_dir / "userlist.txt"
        self.databases: Dict[str, DatabaseConfig] = {}
        self.config = PgBouncerConfig()
        self.pgbouncer_process: Optional[subprocess.Popen] = None
        self.monitoring_task: Optional[asyncio.Task] = None
        
    async def initialize(self, config: Optional[PgBouncerConfig] = None):
        """Initialize pgBouncer configuration manager"""
        if config:
            self.config = config
        
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate initial configuration
        await self.generate_config_files()
        
        # Start monitoring
        self.monitoring_task = asyncio.create_task(self._monitor_pgbouncer())
        
        logger.info("pgbouncer_config_manager_initialized",
                   config_dir=str(self.config_dir))
    
    def add_database(self, db_config: DatabaseConfig):
        """Add database configuration"""
        self.databases[db_config.name] = db_config
        
        audit_logger.log_security_event(
            event_type="pgbouncer_database_added",
            details={
                "database_name": db_config.name,
                "host": db_config.host,
                "port": db_config.port,
                "pool_size": db_config.pool_size
            },
            severity="info"
        )
        
        logger.info("database_added_to_pgbouncer",
                   name=db_config.name,
                   host=db_config.host,
                   pool_size=db_config.pool_size)
    
    def remove_database(self, name: str):
        """Remove database configuration"""
        if name in self.databases:
            del self.databases[name]
            
            audit_logger.log_security_event(
                event_type="pgbouncer_database_removed",
                details={"database_name": name},
                severity="info"
            )
            
            logger.info("database_removed_from_pgbouncer", name=name)
    
    async def generate_config_files(self):
        """Generate pgBouncer configuration files"""
        try:
            # Generate main configuration file
            await self._generate_pgbouncer_ini()
            
            # Generate authentication file
            await self._generate_userlist_txt()
            
            logger.info("pgbouncer_config_files_generated",
                       config_file=str(self.config_file),
                       auth_file=str(self.auth_file))
            
        except Exception as e:
            logger.error("failed_to_generate_pgbouncer_config", error=str(e))
            raise
    
    async def _generate_pgbouncer_ini(self):
        """Generate pgbouncer.ini configuration file"""
        config_content = []
        
        # Databases section
        config_content.append("[databases]")
        for db_config in self.databases.values():
            config_content.append(db_config.to_pgbouncer_line())
        
        if not self.databases:
            # Add a default database entry for template
            config_content.append("; Add database configurations here")
            config_content.append("; example_db = host=localhost port=5432 dbname=example user=example password=secret")
        
        config_content.append("")
        
        # pgBouncer section
        config_content.append("[pgbouncer]")
        
        # Connection settings
        config_content.append(f"listen_addr = {self.config.listen_addr}")
        config_content.append(f"listen_port = {self.config.listen_port}")
        
        # Pool settings
        config_content.append(f"pool_mode = {self.config.pool_mode}")
        config_content.append(f"default_pool_size = {self.config.default_pool_size}")
        config_content.append(f"min_pool_size = {self.config.min_pool_size}")
        config_content.append(f"reserve_pool_size = {self.config.reserve_pool_size}")
        config_content.append(f"reserve_pool_timeout = {self.config.reserve_pool_timeout}")
        
        # Connection limits
        config_content.append(f"max_client_conn = {self.config.max_client_conn}")
        config_content.append(f"max_db_connections = {self.config.max_db_connections}")
        config_content.append(f"max_user_connections = {self.config.max_user_connections}")
        
        # Timeouts
        config_content.append(f"server_round_robin = {'1' if self.config.server_round_robin else '0'}")
        config_content.append(f"server_idle_timeout = {self.config.server_idle_timeout}")
        config_content.append(f"server_connect_timeout = {self.config.server_connect_timeout}")
        config_content.append(f"server_login_retry = {self.config.server_login_retry}")
        config_content.append(f"client_idle_timeout = {self.config.client_idle_timeout}")
        config_content.append(f"client_login_timeout = {self.config.client_login_timeout}")
        
        # Query settings
        config_content.append(f"query_timeout = {self.config.query_timeout}")
        config_content.append(f"query_wait_timeout = {self.config.query_wait_timeout}")
        config_content.append(f"cancel_wait_timeout = {self.config.cancel_wait_timeout}")
        
        # Authentication
        config_content.append(f"auth_type = {self.config.auth_type}")
        if self.config.auth_file:
            config_content.append(f"auth_file = {self.config.auth_file}")
        else:
            config_content.append(f"auth_file = {self.auth_file}")
        
        if self.config.auth_hba_file:
            config_content.append(f"auth_hba_file = {self.config.auth_hba_file}")
        
        # Logging
        config_content.append(f"log_connections = {'1' if self.config.log_connections else '0'}")
        config_content.append(f"log_disconnections = {'1' if self.config.log_disconnections else '0'}")
        config_content.append(f"log_pooler_errors = {'1' if self.config.log_pooler_errors else '0'}")
        config_content.append(f"log_stats = {'1' if self.config.log_stats else '0'}")
        config_content.append(f"stats_period = {self.config.stats_period}")
        
        # Security
        if self.config.ignore_startup_parameters:
            params = ",".join(self.config.ignore_startup_parameters)
            config_content.append(f"ignore_startup_parameters = {params}")
        
        # Performance
        config_content.append(f"pkt_buf = {self.config.pkt_buf}")
        config_content.append(f"listen_backlog = {self.config.listen_backlog}")
        config_content.append(f"sbuf_loopcnt = {self.config.sbuf_loopcnt}")
        
        # Write configuration file
        config_text = "\n".join(config_content)
        
        # Write to temporary file first, then move (atomic operation)
        temp_file = self.config_file.with_suffix('.tmp')
        temp_file.write_text(config_text)
        temp_file.replace(self.config_file)
        
        # Set appropriate permissions
        os.chmod(self.config_file, 0o600)
    
    async def _generate_userlist_txt(self):
        """Generate userlist.txt authentication file"""
        auth_content = []
        
        # Add users from database configurations
        users_added = set()
        for db_config in self.databases.values():
            if db_config.user not in users_added:
                # Format: "username" "password"
                auth_content.append(f'"{db_config.user}" "{db_config.password}"')
                users_added.add(db_config.user)
        
        if not auth_content:
            # Add template entry
            auth_content.append('; "username" "password"')
            auth_content.append('; "example_user" "example_password"')
        
        # Write authentication file
        auth_text = "\n".join(auth_content)
        
        # Write to temporary file first, then move (atomic operation)
        temp_file = self.auth_file.with_suffix('.tmp')
        temp_file.write_text(auth_text)
        temp_file.replace(self.auth_file)
        
        # Set strict permissions for security
        os.chmod(self.auth_file, 0o600)
    
    async def reload_config(self):
        """Reload pgBouncer configuration"""
        try:
            # Regenerate configuration files
            await self.generate_config_files()
            
            # Send SIGHUP to pgBouncer process to reload config
            if self.pgbouncer_process and self.pgbouncer_process.poll() is None:
                self.pgbouncer_process.send_signal(1)  # SIGHUP
                
                pgbouncer_config_reloads.labels(status="success").inc()
                
                audit_logger.log_security_event(
                    event_type="pgbouncer_config_reloaded",
                    details={"config_file": str(self.config_file)},
                    severity="info"
                )
                
                logger.info("pgbouncer_config_reloaded")
            else:
                logger.warning("pgbouncer_process_not_running")
                pgbouncer_config_reloads.labels(status="no_process").inc()
            
        except Exception as e:
            pgbouncer_config_reloads.labels(status="error").inc()
            logger.error("failed_to_reload_pgbouncer_config", error=str(e))
            raise
    
    async def start_pgbouncer(self, daemon: bool = True):
        """Start pgBouncer process"""
        try:
            if self.pgbouncer_process and self.pgbouncer_process.poll() is None:
                logger.warning("pgbouncer_already_running")
                return
            
            # Build command
            cmd = ["pgbouncer"]
            if daemon:
                cmd.append("-d")
            cmd.append(str(self.config_file))
            
            # Start process
            self.pgbouncer_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait a moment to check if it started successfully
            await asyncio.sleep(1)
            
            if self.pgbouncer_process.poll() is None:
                logger.info("pgbouncer_started_successfully",
                           pid=self.pgbouncer_process.pid,
                           config_file=str(self.config_file))
                
                audit_logger.log_security_event(
                    event_type="pgbouncer_started",
                    details={
                        "pid": self.pgbouncer_process.pid,
                        "config_file": str(self.config_file)
                    },
                    severity="info"
                )
            else:
                # Process exited, get error output
                stdout, stderr = self.pgbouncer_process.communicate()
                error_msg = stderr or stdout or "Unknown error"
                
                logger.error("pgbouncer_failed_to_start", error=error_msg)
                raise RuntimeError(f"PgBouncer failed to start: {error_msg}")
            
        except Exception as e:
            logger.error("failed_to_start_pgbouncer", error=str(e))
            raise
    
    async def stop_pgbouncer(self):
        """Stop pgBouncer process"""
        try:
            if not self.pgbouncer_process or self.pgbouncer_process.poll() is not None:
                logger.warning("pgbouncer_not_running")
                return
            
            # Send SIGTERM for graceful shutdown
            self.pgbouncer_process.terminate()
            
            # Wait for graceful shutdown
            try:
                await asyncio.wait_for(
                    asyncio.create_task(self._wait_for_process_exit()),
                    timeout=30
                )
                logger.info("pgbouncer_stopped_gracefully")
            except asyncio.TimeoutError:
                # Force kill if graceful shutdown failed
                self.pgbouncer_process.kill()
                logger.warning("pgbouncer_force_killed")
            
            audit_logger.log_security_event(
                event_type="pgbouncer_stopped",
                details={"pid": self.pgbouncer_process.pid},
                severity="info"
            )
            
        except Exception as e:
            logger.error("failed_to_stop_pgbouncer", error=str(e))
            raise
    
    async def _wait_for_process_exit(self):
        """Wait for pgBouncer process to exit"""
        while self.pgbouncer_process.poll() is None:
            await asyncio.sleep(0.1)
    
    async def get_pgbouncer_stats(self) -> Dict[str, Any]:
        """Get pgBouncer statistics via admin interface"""
        stats = {}
        
        try:
            # Connect to pgBouncer admin interface
            admin_conn = await asyncpg.connect(
                host=self.config.listen_addr if self.config.listen_addr != "*" else "localhost",
                port=self.config.listen_port,
                database="pgbouncer",
                user="pgbouncer",  # Admin user
                password=""  # Usually no password for admin
            )
            
            try:
                # Get pool statistics
                pools = await admin_conn.fetch("SHOW POOLS")
                stats["pools"] = [dict(row) for row in pools]
                
                # Get client statistics
                clients = await admin_conn.fetch("SHOW CLIENTS")
                stats["clients"] = [dict(row) for row in clients]
                
                # Get server statistics
                servers = await admin_conn.fetch("SHOW SERVERS")
                stats["servers"] = [dict(row) for row in servers]
                
                # Get database statistics
                databases = await admin_conn.fetch("SHOW DATABASES")
                stats["databases"] = [dict(row) for row in databases]
                
                # Get general statistics
                general_stats = await admin_conn.fetch("SHOW STATS")
                stats["general"] = [dict(row) for row in general_stats]
                
            finally:
                await admin_conn.close()
            
        except Exception as e:
            logger.error("failed_to_get_pgbouncer_stats", error=str(e))
            stats["error"] = str(e)
        
        return stats
    
    async def _monitor_pgbouncer(self):
        """Monitor pgBouncer performance and health"""
        while True:
            try:
                await asyncio.sleep(30)  # Monitor every 30 seconds
                
                # Check if process is running
                if not self.pgbouncer_process or self.pgbouncer_process.poll() is not None:
                    logger.warning("pgbouncer_process_not_running")
                    continue
                
                # Get statistics
                stats = await self.get_pgbouncer_stats()
                
                if "error" not in stats:
                    # Update Prometheus metrics
                    await self._update_metrics_from_stats(stats)
                
            except Exception as e:
                logger.error("pgbouncer_monitoring_error", error=str(e))
    
    async def _update_metrics_from_stats(self, stats: Dict[str, Any]):
        """Update Prometheus metrics from pgBouncer statistics"""
        try:
            # Update pool metrics
            for pool in stats.get("pools", []):
                pool_name = pool.get("database", "unknown")
                
                pgbouncer_connections.labels(
                    pool_name=pool_name,
                    connection_type="active"
                ).set(pool.get("cl_active", 0))
                
                pgbouncer_connections.labels(
                    pool_name=pool_name,
                    connection_type="waiting"
                ).set(pool.get("cl_waiting", 0))
                
                pgbouncer_pool_size.labels(
                    pool_name=pool_name,
                    metric_type="current"
                ).set(pool.get("sv_active", 0))
                
                pgbouncer_pool_size.labels(
                    pool_name=pool_name,
                    metric_type="idle"
                ).set(pool.get("sv_idle", 0))
            
            # Update general statistics
            for stat in stats.get("general", []):
                database = stat.get("database", "total")
                
                # Record query duration (approximate from total_query_time / total_requests)
                total_requests = stat.get("total_requests", 0)
                total_query_time = stat.get("total_query_time", 0)
                
                if total_requests > 0:
                    avg_duration = total_query_time / total_requests / 1000000  # Convert to seconds
                    pgbouncer_query_duration.labels(pool_name=database).observe(avg_duration)
            
        except Exception as e:
            logger.error("failed_to_update_pgbouncer_metrics", error=str(e))
    
    async def validate_configuration(self) -> Dict[str, Any]:
        """Validate pgBouncer configuration"""
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "recommendations": []
        }
        
        # Check pool size relationships
        if self.config.min_pool_size > self.config.default_pool_size:
            validation_result["errors"].append(
                "min_pool_size cannot be greater than default_pool_size"
            )
            validation_result["valid"] = False
        
        if self.config.reserve_pool_size > self.config.default_pool_size:
            validation_result["warnings"].append(
                "reserve_pool_size is greater than default_pool_size"
            )
        
        # Check connection limits
        if self.config.max_client_conn < self.config.default_pool_size:
            validation_result["warnings"].append(
                "max_client_conn is less than default_pool_size"
            )
        
        # Check timeout settings
        if self.config.query_wait_timeout < 30:
            validation_result["warnings"].append(
                "query_wait_timeout is very low, may cause connection issues"
            )
        
        # Check pool mode for production
        if self.config.pool_mode == PoolMode.STATEMENT:
            validation_result["warnings"].append(
                "Statement pooling not recommended for production use"
            )
        
        # Performance recommendations
        if self.config.default_pool_size < 10:
            validation_result["recommendations"].append(
                "Consider increasing default_pool_size for better performance"
            )
        
        if not self.config.server_round_robin:
            validation_result["recommendations"].append(
                "Enable server_round_robin for better load distribution"
            )
        
        return validation_result
    
    async def shutdown(self):
        """Shutdown pgBouncer configuration manager"""
        logger.info("shutting_down_pgbouncer_config_manager")
        
        # Stop monitoring
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Stop pgBouncer process
        await self.stop_pgbouncer()
        
        logger.info("pgbouncer_config_manager_shutdown_complete")


# Factory function for easy initialization
async def create_pgbouncer_manager(
    config_dir: str = "/etc/pgbouncer",
    databases: Optional[List[DatabaseConfig]] = None,
    config: Optional[PgBouncerConfig] = None
) -> PgBouncerConfigManager:
    """Create and initialize pgBouncer configuration manager"""
    
    manager = PgBouncerConfigManager(config_dir)
    await manager.initialize(config)
    
    # Add databases if provided
    if databases:
        for db_config in databases:
            manager.add_database(db_config)
    
    return manager