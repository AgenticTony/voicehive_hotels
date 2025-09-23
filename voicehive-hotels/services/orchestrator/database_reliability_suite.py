"""
Database Reliability Suite Integration for VoiceHive Hotels
Comprehensive integration of all database performance and reliability components
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path

from database_performance_optimizer import DatabasePerformanceOptimizer
from pgbouncer_config_manager import PgBouncerConfigManager, PgBouncerConfig, DatabaseConfig
from database_migration_manager import DatabaseMigrationManager
from database_backup_manager import DatabaseBackupManager, BackupConfig, BackupType, StorageType, CompressionType
from database_capacity_planner import DatabaseCapacityManager
from connection_pool_manager import get_connection_pool_manager, ConnectionPoolConfig

from logging_adapter import get_safe_logger
from audit_logging import AuditLogger

logger = get_safe_logger("orchestrator.db_reliability")
audit_logger = AuditLogger("database_reliability")


class DatabaseReliabilitySuite:
    """
    Comprehensive database reliability and performance management suite
    Integrates all database optimization, backup, migration, and monitoring components
    """
    
    def __init__(self, database_url: str, config: Optional[Dict[str, Any]] = None):
        self.database_url = database_url
        self.config = config or {}
        
        # Initialize connection pool
        self.pool_manager = None
        self.connection_pool = None
        
        # Initialize components
        self.performance_optimizer: Optional[DatabasePerformanceOptimizer] = None
        self.pgbouncer_manager: Optional[PgBouncerConfigManager] = None
        self.migration_manager: Optional[DatabaseMigrationManager] = None
        self.backup_manager: Optional[DatabaseBackupManager] = None
        self.capacity_manager: Optional[DatabaseCapacityManager] = None
        
        # Background tasks
        self.background_tasks: List[asyncio.Task] = []
        
    async def initialize(self):
        """Initialize the complete database reliability suite"""
        logger.info("initializing_database_reliability_suite")
        
        try:
            # Initialize connection pool
            await self._initialize_connection_pool()
            
            # Initialize performance optimizer
            await self._initialize_performance_optimizer()
            
            # Initialize pgBouncer manager
            await self._initialize_pgbouncer_manager()
            
            # Initialize migration manager
            await self._initialize_migration_manager()
            
            # Initialize backup manager
            await self._initialize_backup_manager()
            
            # Initialize capacity manager
            await self._initialize_capacity_manager()
            
            # Start background monitoring
            await self._start_background_monitoring()
            
            logger.info("database_reliability_suite_initialized_successfully")
            
        except Exception as e:
            logger.error("failed_to_initialize_database_reliability_suite", error=str(e))
            raise
    
    async def _initialize_connection_pool(self):
        """Initialize database connection pool"""
        pool_config = ConnectionPoolConfig(
            db_min_size=self.config.get("pool_min_size", 5),
            db_max_size=self.config.get("pool_max_size", 20),
            db_command_timeout=self.config.get("command_timeout", 30.0)
        )
        
        self.pool_manager = get_connection_pool_manager(pool_config)
        await self.pool_manager.initialize()
        
        # Create database pool
        self.connection_pool = await self.pool_manager.create_database_pool(
            "main", self.database_url
        )
        
        logger.info("database_connection_pool_initialized")
    
    async def _initialize_performance_optimizer(self):
        """Initialize database performance optimizer"""
        self.performance_optimizer = DatabasePerformanceOptimizer(
            self.connection_pool.pool
        )
        await self.performance_optimizer.initialize()
        
        logger.info("database_performance_optimizer_initialized")
    
    async def _initialize_pgbouncer_manager(self):
        """Initialize pgBouncer configuration manager"""
        pgbouncer_config = PgBouncerConfig(
            pool_mode=self.config.get("pgbouncer_pool_mode", "transaction"),
            default_pool_size=self.config.get("pgbouncer_pool_size", 25),
            max_client_conn=self.config.get("pgbouncer_max_clients", 1000)
        )
        
        self.pgbouncer_manager = PgBouncerConfigManager(
            config_dir=self.config.get("pgbouncer_config_dir", "/etc/pgbouncer")
        )
        
        await self.pgbouncer_manager.initialize(pgbouncer_config)
        
        # Add database configuration
        db_config = DatabaseConfig(
            name="voicehive_main",
            host=self.config.get("db_host", "localhost"),
            port=self.config.get("db_port", 5432),
            dbname=self.config.get("db_name", "voicehive"),
            user=self.config.get("db_user", "postgres"),
            password=self.config.get("db_password", ""),
            pool_size=25
        )
        
        self.pgbouncer_manager.add_database(db_config)
        await self.pgbouncer_manager.generate_config_files()
        
        logger.info("pgbouncer_manager_initialized")
    
    async def _initialize_migration_manager(self):
        """Initialize database migration manager"""
        alembic_config_path = self.config.get(
            "alembic_config_path", 
            "alembic.ini"
        )
        
        self.migration_manager = DatabaseMigrationManager(
            self.connection_pool.pool,
            alembic_config_path
        )
        
        await self.migration_manager.initialize()
        
        logger.info("database_migration_manager_initialized")
    
    async def _initialize_backup_manager(self):
        """Initialize database backup manager"""
        backup_config = BackupConfig(
            backup_type=BackupType(self.config.get("backup_type", "logical")),
            storage_type=StorageType(self.config.get("storage_type", "local")),
            compression=CompressionType(self.config.get("compression", "gzip")),
            retention_days=self.config.get("retention_days", 30),
            local_path=self.config.get("backup_local_path", "/var/backups/postgresql"),
            s3_bucket=self.config.get("backup_s3_bucket"),
            s3_prefix=self.config.get("backup_s3_prefix", "voicehive-backups")
        )
        
        self.backup_manager = DatabaseBackupManager(
            self.connection_pool.pool,
            backup_config
        )
        
        await self.backup_manager.initialize()
        
        logger.info("database_backup_manager_initialized")
    
    async def _initialize_capacity_manager(self):
        """Initialize database capacity manager"""
        self.capacity_manager = DatabaseCapacityManager(
            self.connection_pool.pool
        )
        
        await self.capacity_manager.initialize()
        
        logger.info("database_capacity_manager_initialized")
    
    async def _start_background_monitoring(self):
        """Start background monitoring tasks"""
        # Schedule daily backup
        backup_task = asyncio.create_task(self._daily_backup_scheduler())
        self.background_tasks.append(backup_task)
        
        # Schedule weekly cleanup
        cleanup_task = asyncio.create_task(self._weekly_cleanup_scheduler())
        self.background_tasks.append(cleanup_task)
        
        logger.info("background_monitoring_tasks_started")
    
    async def _daily_backup_scheduler(self):
        """Schedule daily database backups"""
        while True:
            try:
                # Wait until 2 AM for daily backup
                now = datetime.now()
                next_backup = now.replace(hour=2, minute=0, second=0, microsecond=0)
                
                if next_backup <= now:
                    next_backup = next_backup.replace(day=next_backup.day + 1)
                
                sleep_seconds = (next_backup - now).total_seconds()
                await asyncio.sleep(sleep_seconds)
                
                # Create backup
                logger.info("starting_scheduled_daily_backup")
                
                backup_result = await self.backup_manager.create_backup("voicehive")
                
                if backup_result.status.value in ["success", "verified"]:
                    logger.info("daily_backup_completed_successfully",
                               backup_id=backup_result.backup_id)
                else:
                    logger.error("daily_backup_failed",
                               backup_id=backup_result.backup_id,
                               error=backup_result.error_message)
                
            except Exception as e:
                logger.error("daily_backup_scheduler_error", error=str(e))
                await asyncio.sleep(3600)  # Retry in 1 hour on error
    
    async def _weekly_cleanup_scheduler(self):
        """Schedule weekly cleanup tasks"""
        while True:
            try:
                # Wait for Sunday 3 AM for weekly cleanup
                now = datetime.now()
                days_until_sunday = (6 - now.weekday()) % 7
                
                next_cleanup = now.replace(hour=3, minute=0, second=0, microsecond=0)
                next_cleanup = next_cleanup.replace(day=next_cleanup.day + days_until_sunday)
                
                if next_cleanup <= now:
                    next_cleanup = next_cleanup.replace(day=next_cleanup.day + 7)
                
                sleep_seconds = (next_cleanup - now).total_seconds()
                await asyncio.sleep(sleep_seconds)
                
                # Run cleanup tasks
                logger.info("starting_weekly_cleanup_tasks")
                
                # Clean up old backups
                cleanup_result = await self.backup_manager.cleanup_old_backups()
                logger.info("backup_cleanup_completed",
                           deleted_count=cleanup_result["deleted_count"],
                           freed_bytes=cleanup_result["freed_bytes"])
                
                # Generate performance report
                perf_report = await self.performance_optimizer.get_performance_report()
                logger.info("weekly_performance_report_generated",
                           recommendations=len(perf_report.get("index_recommendations", [])))
                
            except Exception as e:
                logger.error("weekly_cleanup_scheduler_error", error=str(e))
                await asyncio.sleep(86400)  # Retry in 24 hours on error
    
    async def get_comprehensive_status(self) -> Dict[str, Any]:
        """Get comprehensive status of all database reliability components"""
        status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_health": "unknown",
            "components": {},
            "alerts": [],
            "recommendations": []
        }
        
        try:
            # Connection pool status
            if self.pool_manager:
                pool_health = await self.pool_manager.health_check()
                status["components"]["connection_pool"] = {
                    "status": "healthy" if all(pool_health.get("database", {}).values()) else "degraded",
                    "details": pool_health
                }
            
            # Performance optimizer status
            if self.performance_optimizer:
                perf_report = await self.performance_optimizer.get_performance_report()
                status["components"]["performance_optimizer"] = {
                    "status": "active",
                    "index_recommendations": len(perf_report.get("index_recommendations", [])),
                    "optimization_suggestions": perf_report.get("optimization_suggestions", [])
                }
                
                # Add performance recommendations to overall recommendations
                status["recommendations"].extend(perf_report.get("optimization_suggestions", []))
            
            # pgBouncer status
            if self.pgbouncer_manager:
                pgbouncer_stats = await self.pgbouncer_manager.get_pgbouncer_stats()
                status["components"]["pgbouncer"] = {
                    "status": "active" if "error" not in pgbouncer_stats else "error",
                    "stats": pgbouncer_stats
                }
            
            # Migration status
            if self.migration_manager:
                migration_integrity = await self.migration_manager.validate_migration_integrity()
                status["components"]["migrations"] = {
                    "status": "valid" if migration_integrity["valid"] else "invalid",
                    "current_revision": migration_integrity.get("current_revision"),
                    "total_migrations": migration_integrity.get("total_migrations", 0),
                    "errors": migration_integrity.get("errors", [])
                }
                
                if migration_integrity.get("errors"):
                    status["alerts"].extend([
                        {"type": "error", "component": "migrations", "message": error}
                        for error in migration_integrity["errors"]
                    ])
            
            # Backup status
            if self.backup_manager:
                backup_report = await self.backup_manager.get_backup_status_report()
                status["components"]["backups"] = {
                    "status": "active",
                    "success_rate": backup_report.get("success_rate", 0),
                    "recent_backups": len(backup_report.get("recent_backups", [])),
                    "retention_compliance": backup_report.get("retention_compliance", {})
                }
                
                # Check for backup issues
                if backup_report.get("success_rate", 0) < 0.9:
                    status["alerts"].append({
                        "type": "warning",
                        "component": "backups",
                        "message": f"Backup success rate is low: {backup_report['success_rate']:.1%}"
                    })
            
            # Capacity status
            if self.capacity_manager:
                capacity_data = await self.capacity_manager.get_capacity_dashboard_data()
                status["components"]["capacity_planning"] = {
                    "status": "monitoring",
                    "alerts": len(capacity_data.get("alerts", [])),
                    "high_growth_tables": len([
                        t for t in capacity_data.get("growth_analysis", {}).values()
                        if t.get("is_high_growth", False)
                    ])
                }
                
                # Add capacity alerts to overall alerts
                status["alerts"].extend(capacity_data.get("alerts", []))
            
            # Determine overall health
            component_statuses = [
                comp.get("status", "unknown") 
                for comp in status["components"].values()
            ]
            
            if all(s in ["healthy", "active", "valid", "monitoring"] for s in component_statuses):
                status["overall_health"] = "healthy"
            elif any(s in ["error", "invalid"] for s in component_statuses):
                status["overall_health"] = "critical"
            else:
                status["overall_health"] = "degraded"
            
        except Exception as e:
            logger.error("failed_to_get_comprehensive_status", error=str(e))
            status["error"] = str(e)
            status["overall_health"] = "error"
        
        return status
    
    async def run_maintenance_cycle(self) -> Dict[str, Any]:
        """Run comprehensive database maintenance cycle"""
        maintenance_result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tasks_completed": [],
            "tasks_failed": [],
            "recommendations": [],
            "duration_seconds": 0
        }
        
        start_time = datetime.now()
        
        try:
            logger.info("starting_database_maintenance_cycle")
            
            # 1. Performance optimization
            try:
                perf_report = await self.performance_optimizer.get_performance_report()
                
                # Create high-priority indexes
                high_priority_indexes = [
                    rec for rec in perf_report.get("index_recommendations", [])
                    if rec.get("priority") == 1
                ]
                
                if high_priority_indexes:
                    # This would create indexes - simplified for demo
                    maintenance_result["tasks_completed"].append(
                        f"Analyzed {len(high_priority_indexes)} high-priority index recommendations"
                    )
                
            except Exception as e:
                maintenance_result["tasks_failed"].append(f"Performance optimization: {str(e)}")
            
            # 2. Backup verification
            try:
                backup_report = await self.backup_manager.get_backup_status_report()
                
                # Check recent backup success
                recent_backups = backup_report.get("recent_backups", [])
                if recent_backups:
                    latest_backup = recent_backups[0]
                    if latest_backup.get("status") in ["success", "verified"]:
                        maintenance_result["tasks_completed"].append("Latest backup verified successfully")
                    else:
                        maintenance_result["recommendations"].append("Latest backup failed - investigate backup system")
                
            except Exception as e:
                maintenance_result["tasks_failed"].append(f"Backup verification: {str(e)}")
            
            # 3. Capacity analysis
            try:
                capacity_data = await self.capacity_manager.get_capacity_dashboard_data()
                
                # Check for capacity alerts
                critical_alerts = [
                    alert for alert in capacity_data.get("alerts", [])
                    if alert.get("type") == "critical"
                ]
                
                if critical_alerts:
                    maintenance_result["recommendations"].extend([
                        f"Critical capacity issue: {alert['message']}"
                        for alert in critical_alerts
                    ])
                
                maintenance_result["tasks_completed"].append("Capacity analysis completed")
                
            except Exception as e:
                maintenance_result["tasks_failed"].append(f"Capacity analysis: {str(e)}")
            
            # 4. Migration validation
            try:
                migration_integrity = await self.migration_manager.validate_migration_integrity()
                
                if migration_integrity["valid"]:
                    maintenance_result["tasks_completed"].append("Migration integrity validated")
                else:
                    maintenance_result["recommendations"].extend([
                        f"Migration issue: {error}"
                        for error in migration_integrity.get("errors", [])
                    ])
                
            except Exception as e:
                maintenance_result["tasks_failed"].append(f"Migration validation: {str(e)}")
            
            # Calculate duration
            maintenance_result["duration_seconds"] = (datetime.now() - start_time).total_seconds()
            
            logger.info("database_maintenance_cycle_completed",
                       completed_tasks=len(maintenance_result["tasks_completed"]),
                       failed_tasks=len(maintenance_result["tasks_failed"]),
                       recommendations=len(maintenance_result["recommendations"]))
            
        except Exception as e:
            logger.error("database_maintenance_cycle_error", error=str(e))
            maintenance_result["error"] = str(e)
        
        return maintenance_result
    
    async def shutdown(self):
        """Shutdown the database reliability suite"""
        logger.info("shutting_down_database_reliability_suite")
        
        try:
            # Cancel background tasks
            for task in self.background_tasks:
                task.cancel()
            
            # Wait for tasks to complete
            if self.background_tasks:
                await asyncio.gather(*self.background_tasks, return_exceptions=True)
            
            # Shutdown components
            if self.performance_optimizer:
                await self.performance_optimizer.shutdown()
            
            if self.pgbouncer_manager:
                await self.pgbouncer_manager.shutdown()
            
            if self.backup_manager:
                # Backup manager doesn't have explicit shutdown
                pass
            
            if self.capacity_manager:
                await self.capacity_manager.shutdown()
            
            # Shutdown connection pool
            if self.pool_manager:
                await self.pool_manager.close_all()
            
            logger.info("database_reliability_suite_shutdown_complete")
            
        except Exception as e:
            logger.error("error_during_shutdown", error=str(e))


# Factory function for easy initialization
async def create_database_reliability_suite(
    database_url: str,
    config: Optional[Dict[str, Any]] = None
) -> DatabaseReliabilitySuite:
    """Create and initialize database reliability suite"""
    
    suite = DatabaseReliabilitySuite(database_url, config)
    await suite.initialize()
    
    return suite