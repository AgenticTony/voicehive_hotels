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

# Core database components
from .models import Base, User, Role, Hotel, UserSession
from .repository import UserRepository, SessionRepository
from .connection import (
    DatabaseManager, db_manager, get_db_session,
    initialize_database, close_database, get_database_health
)

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

    # Core Models
    "Base",
    "User",
    "Role",
    "Hotel",
    "UserSession",

    # Repositories
    "UserRepository",
    "SessionRepository",

    # Connection Management
    "DatabaseManager",
    "db_manager",
    "get_db_session",
    "initialize_database",
    "close_database",
    "get_database_health",
]