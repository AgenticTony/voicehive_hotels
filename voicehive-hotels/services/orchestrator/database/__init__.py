"""
Database Management module for VoiceHive Hotels Orchestrator

This module provides comprehensive database management including performance optimization,
backup management, migration handling, capacity planning, and reliability testing.
"""

from .performance_optimizer import DatabasePerformanceOptimizer, QueryOptimizationEngine
from .backup_manager import DatabaseBackupManager
from .migration_manager import DatabaseMigrationManager
from .capacity_planner import DatabaseCapacityPlanner
from .reliability_suite import DatabaseReliabilitySuite
from .pgbouncer_config import PgBouncerConfigManager

__all__ = [
    # Performance
    "DatabasePerformanceOptimizer",
    "QueryOptimizationEngine",
    
    # Backup & Recovery
    "DatabaseBackupManager",
    
    # Migration
    "DatabaseMigrationManager",
    
    # Capacity Planning
    "DatabaseCapacityPlanner",
    
    # Reliability
    "DatabaseReliabilitySuite",
    
    # Connection Pooling
    "PgBouncerConfigManager",
]