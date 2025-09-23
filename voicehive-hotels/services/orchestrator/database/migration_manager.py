"""
Database Migration Manager for VoiceHive Hotels
Automated database migration testing and rollback procedures
"""

import asyncio
import os
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import tempfile
import shutil
import subprocess

import asyncpg
from sqlalchemy import text, create_engine, MetaData
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from alembic.operations import Operations
from pydantic import BaseModel, Field

from prometheus_client import Gauge, Counter, Histogram, Summary
from logging_adapter import get_safe_logger
from audit_logging import AuditLogger

logger = get_safe_logger("orchestrator.db_migration")
audit_logger = AuditLogger("database_migration")

# Prometheus metrics for migration monitoring
migration_duration = Histogram(
    'voicehive_migration_duration_seconds',
    'Database migration execution time',
    ['migration_id', 'direction'],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200)
)

migration_status = Gauge(
    'voicehive_migration_status',
    'Migration status (1=success, 0=failure, -1=rollback)',
    ['migration_id', 'environment']
)

migration_test_results = Counter(
    'voicehive_migration_test_results_total',
    'Migration test results',
    ['test_type', 'status']
)

migration_rollback_count = Counter(
    'voicehive_migration_rollbacks_total',
    'Migration rollback count',
    ['migration_id', 'reason']
)

schema_validation_errors = Counter(
    'voicehive_schema_validation_errors_total',
    'Schema validation errors',
    ['error_type', 'migration_id']
)


class MigrationStatus(str, Enum):
    """Migration execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    TESTING = "testing"


class MigrationDirection(str, Enum):
    """Migration direction"""
    UP = "up"
    DOWN = "down"


class TestType(str, Enum):
    """Migration test types"""
    SYNTAX = "syntax"
    SCHEMA = "schema"
    DATA_INTEGRITY = "data_integrity"
    PERFORMANCE = "performance"
    ROLLBACK = "rollback"
    COMPATIBILITY = "compatibility"


@dataclass
class MigrationInfo:
    """Migration information"""
    revision_id: str
    description: str
    file_path: str
    up_sql: str
    down_sql: str
    dependencies: List[str] = field(default_factory=list)
    estimated_duration: Optional[int] = None  # seconds
    risk_level: str = "medium"  # low, medium, high
    requires_downtime: bool = False
    
    @property
    def migration_hash(self) -> str:
        """Calculate hash of migration content"""
        content = f"{self.up_sql}{self.down_sql}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class MigrationResult:
    """Migration execution result"""
    migration_id: str
    status: MigrationStatus
    direction: MigrationDirection
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    rollback_sql: Optional[str] = None
    test_results: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def success(self) -> bool:
        return self.status == MigrationStatus.SUCCESS


class MigrationTestSuite:
    """Comprehensive migration testing suite"""
    
    def __init__(self, connection_pool):
        self.pool = connection_pool
        
    async def run_all_tests(self, migration: MigrationInfo, test_db_url: str) -> Dict[str, Any]:
        """Run comprehensive migration tests"""
        test_results = {
            "overall_status": "success",
            "tests": {},
            "errors": [],
            "warnings": []
        }
        
        try:
            # Create test database
            test_db_name = f"migration_test_{migration.revision_id}_{int(datetime.now().timestamp())}"
            await self._create_test_database(test_db_name)
            
            try:
                # Run individual tests
                test_results["tests"]["syntax"] = await self._test_syntax(migration)
                test_results["tests"]["schema"] = await self._test_schema_changes(migration, test_db_name)
                test_results["tests"]["data_integrity"] = await self._test_data_integrity(migration, test_db_name)
                test_results["tests"]["performance"] = await self._test_performance(migration, test_db_name)
                test_results["tests"]["rollback"] = await self._test_rollback(migration, test_db_name)
                test_results["tests"]["compatibility"] = await self._test_compatibility(migration, test_db_name)
                
                # Check overall status
                failed_tests = [name for name, result in test_results["tests"].items() 
                              if not result.get("passed", False)]
                
                if failed_tests:
                    test_results["overall_status"] = "failed"
                    test_results["errors"].append(f"Failed tests: {', '.join(failed_tests)}")
                
            finally:
                # Clean up test database
                await self._drop_test_database(test_db_name)
            
        except Exception as e:
            test_results["overall_status"] = "error"
            test_results["errors"].append(f"Test suite error: {str(e)}")
            logger.error("migration_test_suite_error", 
                        migration_id=migration.revision_id, 
                        error=str(e))
        
        return test_results
    
    async def _create_test_database(self, db_name: str):
        """Create isolated test database"""
        async with self.pool.acquire() as conn:
            # Create database
            await conn.execute(f"CREATE DATABASE {db_name}")
            
            # Copy schema from main database (without data)
            await conn.execute(f"""
                CREATE DATABASE {db_name}_schema_copy 
                WITH TEMPLATE template0
            """)
    
    async def _drop_test_database(self, db_name: str):
        """Drop test database"""
        async with self.pool.acquire() as conn:
            # Terminate connections to test database
            await conn.execute(f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = '{db_name}'
                AND pid <> pg_backend_pid()
            """)
            
            # Drop database
            await conn.execute(f"DROP DATABASE IF EXISTS {db_name}")
            await conn.execute(f"DROP DATABASE IF EXISTS {db_name}_schema_copy")
    
    async def _test_syntax(self, migration: MigrationInfo) -> Dict[str, Any]:
        """Test SQL syntax validity"""
        result = {"passed": True, "errors": [], "warnings": []}
        
        try:
            # Test UP migration syntax
            async with self.pool.acquire() as conn:
                # Use EXPLAIN to validate syntax without execution
                try:
                    # Split migration into individual statements
                    statements = self._split_sql_statements(migration.up_sql)
                    
                    for i, stmt in enumerate(statements):
                        if stmt.strip() and not stmt.strip().startswith('--'):
                            # For DDL statements, we can't use EXPLAIN, so we validate differently
                            if any(keyword in stmt.upper() for keyword in ['CREATE', 'ALTER', 'DROP']):
                                # Basic syntax validation for DDL
                                await self._validate_ddl_syntax(conn, stmt)
                            else:
                                # Use EXPLAIN for DML statements
                                await conn.fetchval(f"EXPLAIN {stmt}")
                
                except Exception as e:
                    result["passed"] = False
                    result["errors"].append(f"UP migration syntax error: {str(e)}")
            
            # Test DOWN migration syntax
            if migration.down_sql:
                async with self.pool.acquire() as conn:
                    try:
                        statements = self._split_sql_statements(migration.down_sql)
                        
                        for stmt in statements:
                            if stmt.strip() and not stmt.strip().startswith('--'):
                                if any(keyword in stmt.upper() for keyword in ['CREATE', 'ALTER', 'DROP']):
                                    await self._validate_ddl_syntax(conn, stmt)
                                else:
                                    await conn.fetchval(f"EXPLAIN {stmt}")
                    
                    except Exception as e:
                        result["passed"] = False
                        result["errors"].append(f"DOWN migration syntax error: {str(e)}")
            
            migration_test_results.labels(
                test_type="syntax",
                status="passed" if result["passed"] else "failed"
            ).inc()
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Syntax test error: {str(e)}")
        
        return result
    
    def _split_sql_statements(self, sql: str) -> List[str]:
        """Split SQL into individual statements"""
        # Simple statement splitting - in production use proper SQL parser
        statements = []
        current_statement = []
        
        for line in sql.split('\n'):
            line = line.strip()
            if line and not line.startswith('--'):
                current_statement.append(line)
                if line.endswith(';'):
                    statements.append('\n'.join(current_statement))
                    current_statement = []
        
        if current_statement:
            statements.append('\n'.join(current_statement))
        
        return statements
    
    async def _validate_ddl_syntax(self, conn, statement: str):
        """Validate DDL statement syntax"""
        # For DDL statements, we can try to parse them or use a dry-run approach
        # This is a simplified validation - production would use more sophisticated parsing
        
        # Check for common DDL syntax patterns
        statement_upper = statement.upper().strip()
        
        if statement_upper.startswith('CREATE TABLE'):
            # Validate CREATE TABLE syntax
            if '(' not in statement or ')' not in statement:
                raise ValueError("Invalid CREATE TABLE syntax: missing parentheses")
        
        elif statement_upper.startswith('ALTER TABLE'):
            # Validate ALTER TABLE syntax
            if 'ADD COLUMN' in statement_upper or 'DROP COLUMN' in statement_upper:
                pass  # Basic validation passed
            else:
                # More complex ALTER statements would need detailed validation
                pass
        
        # Additional DDL validations would go here
    
    async def _test_schema_changes(self, migration: MigrationInfo, test_db_name: str) -> Dict[str, Any]:
        """Test schema changes and validation"""
        result = {"passed": True, "errors": [], "warnings": [], "schema_diff": {}}
        
        try:
            # Connect to test database
            test_conn = await asyncpg.connect(database=test_db_name)
            
            try:
                # Get schema before migration
                schema_before = await self._get_schema_info(test_conn)
                
                # Execute migration
                statements = self._split_sql_statements(migration.up_sql)
                for stmt in statements:
                    if stmt.strip():
                        await test_conn.execute(stmt)
                
                # Get schema after migration
                schema_after = await self._get_schema_info(test_conn)
                
                # Compare schemas
                schema_diff = self._compare_schemas(schema_before, schema_after)
                result["schema_diff"] = schema_diff
                
                # Validate schema changes
                if not schema_diff:
                    result["warnings"].append("No schema changes detected")
                
                # Check for potential issues
                if "dropped_tables" in schema_diff and schema_diff["dropped_tables"]:
                    result["warnings"].append(f"Tables dropped: {schema_diff['dropped_tables']}")
                
                if "dropped_columns" in schema_diff and schema_diff["dropped_columns"]:
                    result["warnings"].append(f"Columns dropped: {schema_diff['dropped_columns']}")
            
            finally:
                await test_conn.close()
            
            migration_test_results.labels(
                test_type="schema",
                status="passed" if result["passed"] else "failed"
            ).inc()
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Schema test error: {str(e)}")
        
        return result
    
    async def _get_schema_info(self, conn) -> Dict[str, Any]:
        """Get comprehensive schema information"""
        schema_info = {}
        
        # Get tables
        tables = await conn.fetch("""
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        schema_info["tables"] = {row["table_name"]: row["table_type"] for row in tables}
        
        # Get columns
        columns = await conn.fetch("""
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """)
        
        schema_info["columns"] = {}
        for row in columns:
            table = row["table_name"]
            if table not in schema_info["columns"]:
                schema_info["columns"][table] = []
            schema_info["columns"][table].append({
                "name": row["column_name"],
                "type": row["data_type"],
                "nullable": row["is_nullable"],
                "default": row["column_default"]
            })
        
        # Get indexes
        indexes = await conn.fetch("""
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
        """)
        
        schema_info["indexes"] = {}
        for row in indexes:
            table = row["tablename"]
            if table not in schema_info["indexes"]:
                schema_info["indexes"][table] = []
            schema_info["indexes"][table].append({
                "name": row["indexname"],
                "definition": row["indexdef"]
            })
        
        return schema_info
    
    def _compare_schemas(self, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
        """Compare two schema snapshots"""
        diff = {}
        
        # Compare tables
        before_tables = set(before.get("tables", {}).keys())
        after_tables = set(after.get("tables", {}).keys())
        
        diff["added_tables"] = list(after_tables - before_tables)
        diff["dropped_tables"] = list(before_tables - after_tables)
        
        # Compare columns for existing tables
        common_tables = before_tables & after_tables
        diff["column_changes"] = {}
        
        for table in common_tables:
            before_cols = {col["name"]: col for col in before.get("columns", {}).get(table, [])}
            after_cols = {col["name"]: col for col in after.get("columns", {}).get(table, [])}
            
            before_col_names = set(before_cols.keys())
            after_col_names = set(after_cols.keys())
            
            table_changes = {
                "added_columns": list(after_col_names - before_col_names),
                "dropped_columns": list(before_col_names - after_col_names),
                "modified_columns": []
            }
            
            # Check for modified columns
            common_cols = before_col_names & after_col_names
            for col_name in common_cols:
                if before_cols[col_name] != after_cols[col_name]:
                    table_changes["modified_columns"].append({
                        "column": col_name,
                        "before": before_cols[col_name],
                        "after": after_cols[col_name]
                    })
            
            if any(table_changes.values()):
                diff["column_changes"][table] = table_changes
        
        return diff
    
    async def _test_data_integrity(self, migration: MigrationInfo, test_db_name: str) -> Dict[str, Any]:
        """Test data integrity during migration"""
        result = {"passed": True, "errors": [], "warnings": []}
        
        try:
            # This would involve creating test data, running migration, and validating data integrity
            # For now, implement basic checks
            
            test_conn = await asyncpg.connect(database=test_db_name)
            
            try:
                # Create some test data if tables exist
                tables = await test_conn.fetch("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """)
                
                # Insert test data and run migration
                # This is a simplified version - production would have comprehensive test data sets
                
                for table in tables:
                    table_name = table["table_name"]
                    
                    # Get table structure
                    columns = await test_conn.fetch("""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_name = $1 AND table_schema = 'public'
                        ORDER BY ordinal_position
                    """, table_name)
                    
                    if columns:
                        # Create minimal test data
                        await self._insert_test_data(test_conn, table_name, columns)
                
                # Execute migration
                statements = self._split_sql_statements(migration.up_sql)
                for stmt in statements:
                    if stmt.strip():
                        await test_conn.execute(stmt)
                
                # Validate data integrity after migration
                # Check for orphaned records, constraint violations, etc.
                integrity_issues = await self._check_data_integrity(test_conn)
                
                if integrity_issues:
                    result["warnings"].extend(integrity_issues)
            
            finally:
                await test_conn.close()
            
            migration_test_results.labels(
                test_type="data_integrity",
                status="passed" if result["passed"] else "failed"
            ).inc()
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Data integrity test error: {str(e)}")
        
        return result
    
    async def _insert_test_data(self, conn, table_name: str, columns: List[Dict]):
        """Insert minimal test data for integrity testing"""
        try:
            # Create a simple INSERT statement with default/null values
            col_names = [col["column_name"] for col in columns]
            
            # Generate test values based on column types
            test_values = []
            for col in columns:
                col_type = col["data_type"].lower()
                is_nullable = col["is_nullable"] == "YES"
                
                if "int" in col_type or "serial" in col_type:
                    test_values.append("1")
                elif "varchar" in col_type or "text" in col_type:
                    test_values.append("'test_data'")
                elif "timestamp" in col_type or "date" in col_type:
                    test_values.append("NOW()")
                elif "boolean" in col_type:
                    test_values.append("true")
                elif is_nullable:
                    test_values.append("NULL")
                else:
                    test_values.append("DEFAULT")
            
            insert_sql = f"""
                INSERT INTO {table_name} ({', '.join(col_names)})
                VALUES ({', '.join(test_values)})
            """
            
            await conn.execute(insert_sql)
            
        except Exception as e:
            # It's okay if test data insertion fails - some tables might have complex constraints
            logger.debug("test_data_insertion_failed", table=table_name, error=str(e))
    
    async def _check_data_integrity(self, conn) -> List[str]:
        """Check for data integrity issues"""
        issues = []
        
        try:
            # Check for foreign key violations
            fk_violations = await conn.fetch("""
                SELECT conname, conrelid::regclass as table_name
                FROM pg_constraint
                WHERE contype = 'f'
                AND NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgconstraint = pg_constraint.oid
                    AND tgenabled = 'O'
                )
            """)
            
            if fk_violations:
                issues.append(f"Potential foreign key issues: {len(fk_violations)} constraints")
            
            # Check for check constraint violations
            # This would require more sophisticated analysis in production
            
        except Exception as e:
            issues.append(f"Integrity check error: {str(e)}")
        
        return issues
    
    async def _test_performance(self, migration: MigrationInfo, test_db_name: str) -> Dict[str, Any]:
        """Test migration performance impact"""
        result = {"passed": True, "errors": [], "warnings": [], "performance_metrics": {}}
        
        try:
            test_conn = await asyncpg.connect(database=test_db_name)
            
            try:
                # Measure migration execution time
                start_time = datetime.now()
                
                statements = self._split_sql_statements(migration.up_sql)
                for stmt in statements:
                    if stmt.strip():
                        stmt_start = datetime.now()
                        await test_conn.execute(stmt)
                        stmt_duration = (datetime.now() - stmt_start).total_seconds()
                        
                        # Log slow statements
                        if stmt_duration > 5:  # 5 seconds threshold
                            result["warnings"].append(f"Slow statement: {stmt_duration:.2f}s")
                
                total_duration = (datetime.now() - start_time).total_seconds()
                result["performance_metrics"]["total_duration"] = total_duration
                
                # Check if migration exceeds estimated duration
                if migration.estimated_duration and total_duration > migration.estimated_duration * 1.5:
                    result["warnings"].append(
                        f"Migration took longer than estimated: {total_duration:.2f}s vs {migration.estimated_duration}s"
                    )
                
                # Performance thresholds
                if total_duration > 300:  # 5 minutes
                    result["warnings"].append("Migration duration exceeds 5 minutes - consider breaking into smaller migrations")
                
            finally:
                await test_conn.close()
            
            migration_test_results.labels(
                test_type="performance",
                status="passed" if result["passed"] else "failed"
            ).inc()
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Performance test error: {str(e)}")
        
        return result
    
    async def _test_rollback(self, migration: MigrationInfo, test_db_name: str) -> Dict[str, Any]:
        """Test migration rollback functionality"""
        result = {"passed": True, "errors": [], "warnings": []}
        
        try:
            if not migration.down_sql:
                result["warnings"].append("No rollback SQL provided")
                return result
            
            test_conn = await asyncpg.connect(database=test_db_name)
            
            try:
                # Get schema before migration
                schema_before = await self._get_schema_info(test_conn)
                
                # Execute UP migration
                up_statements = self._split_sql_statements(migration.up_sql)
                for stmt in up_statements:
                    if stmt.strip():
                        await test_conn.execute(stmt)
                
                # Execute DOWN migration (rollback)
                down_statements = self._split_sql_statements(migration.down_sql)
                for stmt in down_statements:
                    if stmt.strip():
                        await test_conn.execute(stmt)
                
                # Get schema after rollback
                schema_after = await self._get_schema_info(test_conn)
                
                # Compare schemas - they should be identical after rollback
                schema_diff = self._compare_schemas(schema_before, schema_after)
                
                if schema_diff:
                    # Check if differences are significant
                    has_significant_diff = (
                        schema_diff.get("added_tables") or
                        schema_diff.get("dropped_tables") or
                        any(changes.get("added_columns") or changes.get("dropped_columns") 
                            for changes in schema_diff.get("column_changes", {}).values())
                    )
                    
                    if has_significant_diff:
                        result["passed"] = False
                        result["errors"].append("Rollback did not restore original schema")
                    else:
                        result["warnings"].append("Minor schema differences after rollback")
            
            finally:
                await test_conn.close()
            
            migration_test_results.labels(
                test_type="rollback",
                status="passed" if result["passed"] else "failed"
            ).inc()
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Rollback test error: {str(e)}")
        
        return result
    
    async def _test_compatibility(self, migration: MigrationInfo, test_db_name: str) -> Dict[str, Any]:
        """Test migration compatibility with existing application code"""
        result = {"passed": True, "errors": [], "warnings": []}
        
        try:
            # This would test compatibility with application models, queries, etc.
            # For now, implement basic compatibility checks
            
            test_conn = await asyncpg.connect(database=test_db_name)
            
            try:
                # Execute migration
                statements = self._split_sql_statements(migration.up_sql)
                for stmt in statements:
                    if stmt.strip():
                        await test_conn.execute(stmt)
                
                # Test common query patterns that applications might use
                await self._test_common_queries(test_conn, result)
                
            finally:
                await test_conn.close()
            
            migration_test_results.labels(
                test_type="compatibility",
                status="passed" if result["passed"] else "failed"
            ).inc()
            
        except Exception as e:
            result["passed"] = False
            result["errors"].append(f"Compatibility test error: {str(e)}")
        
        return result
    
    async def _test_common_queries(self, conn, result: Dict[str, Any]):
        """Test common application query patterns"""
        try:
            # Get all tables
            tables = await conn.fetch("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """)
            
            for table in tables:
                table_name = table["table_name"]
                
                try:
                    # Test basic SELECT
                    await conn.fetch(f"SELECT * FROM {table_name} LIMIT 1")
                    
                    # Test COUNT
                    await conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
                    
                except Exception as e:
                    result["warnings"].append(f"Query compatibility issue with table {table_name}: {str(e)}")
        
        except Exception as e:
            result["errors"].append(f"Common query test error: {str(e)}")


class DatabaseMigrationManager:
    """Comprehensive database migration management system"""
    
    def __init__(self, connection_pool, alembic_config_path: str):
        self.pool = connection_pool
        self.alembic_config_path = alembic_config_path
        self.test_suite = MigrationTestSuite(connection_pool)
        self.migration_history: List[MigrationResult] = []
        
    async def initialize(self):
        """Initialize migration manager"""
        logger.info("initializing_database_migration_manager")
        
        # Validate Alembic configuration
        if not Path(self.alembic_config_path).exists():
            raise FileNotFoundError(f"Alembic config not found: {self.alembic_config_path}")
        
        # Create migration tracking table if not exists
        await self._create_migration_tracking_table()
        
        logger.info("database_migration_manager_initialized")
    
    async def _create_migration_tracking_table(self):
        """Create table to track migration execution details"""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS migration_execution_log (
                    id SERIAL PRIMARY KEY,
                    migration_id VARCHAR(255) NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
                    end_time TIMESTAMP WITH TIME ZONE,
                    duration_seconds FLOAT,
                    error_message TEXT,
                    test_results JSONB,
                    rollback_sql TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            
            # Create index for efficient queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_migration_log_migration_id 
                ON migration_execution_log(migration_id)
            """)
    
    async def run_migration(self, target_revision: Optional[str] = None, 
                          dry_run: bool = False, 
                          test_first: bool = True) -> MigrationResult:
        """Run database migration with comprehensive testing"""
        
        start_time = datetime.now(timezone.utc)
        
        try:
            # Get pending migrations
            pending_migrations = await self._get_pending_migrations(target_revision)
            
            if not pending_migrations:
                logger.info("no_pending_migrations")
                return MigrationResult(
                    migration_id="none",
                    status=MigrationStatus.SUCCESS,
                    direction=MigrationDirection.UP,
                    start_time=start_time,
                    end_time=datetime.now(timezone.utc)
                )
            
            # Process each migration
            for migration in pending_migrations:
                result = await self._execute_single_migration(
                    migration, dry_run, test_first
                )
                
                self.migration_history.append(result)
                
                # Log migration result
                await self._log_migration_result(result)
                
                if not result.success:
                    logger.error("migration_failed", 
                               migration_id=migration.revision_id,
                               error=result.error_message)
                    return result
            
            logger.info("all_migrations_completed_successfully")
            return MigrationResult(
                migration_id="batch",
                status=MigrationStatus.SUCCESS,
                direction=MigrationDirection.UP,
                start_time=start_time,
                end_time=datetime.now(timezone.utc)
            )
            
        except Exception as e:
            logger.error("migration_execution_error", error=str(e))
            return MigrationResult(
                migration_id="error",
                status=MigrationStatus.FAILED,
                direction=MigrationDirection.UP,
                start_time=start_time,
                end_time=datetime.now(timezone.utc),
                error_message=str(e)
            )
    
    async def _execute_single_migration(self, migration: MigrationInfo, 
                                      dry_run: bool, test_first: bool) -> MigrationResult:
        """Execute a single migration with testing"""
        
        start_time = datetime.now(timezone.utc)
        result = MigrationResult(
            migration_id=migration.revision_id,
            status=MigrationStatus.RUNNING,
            direction=MigrationDirection.UP,
            start_time=start_time
        )
        
        try:
            # Run tests first if requested
            if test_first:
                logger.info("running_migration_tests", migration_id=migration.revision_id)
                
                test_results = await self.test_suite.run_all_tests(
                    migration, 
                    self._get_test_database_url()
                )
                
                result.test_results = test_results
                
                if test_results["overall_status"] == "failed":
                    result.status = MigrationStatus.FAILED
                    result.error_message = "Migration tests failed"
                    result.end_time = datetime.now(timezone.utc)
                    return result
            
            # Execute migration
            if not dry_run:
                logger.info("executing_migration", migration_id=migration.revision_id)
                
                # Record start time for metrics
                migration_start = datetime.now()
                
                # Execute using Alembic
                config = Config(self.alembic_config_path)
                command.upgrade(config, migration.revision_id)
                
                # Record duration
                duration = (datetime.now() - migration_start).total_seconds()
                
                migration_duration.labels(
                    migration_id=migration.revision_id,
                    direction="up"
                ).observe(duration)
                
                result.duration_seconds = duration
                result.status = MigrationStatus.SUCCESS
                
                # Update metrics
                migration_status.labels(
                    migration_id=migration.revision_id,
                    environment=os.getenv("ENVIRONMENT", "unknown")
                ).set(1)
                
            else:
                logger.info("dry_run_migration_validated", migration_id=migration.revision_id)
                result.status = MigrationStatus.SUCCESS
            
            result.end_time = datetime.now(timezone.utc)
            
            audit_logger.log_security_event(
                event_type="database_migration_executed",
                details={
                    "migration_id": migration.revision_id,
                    "direction": "up",
                    "dry_run": dry_run,
                    "duration_seconds": result.duration_seconds
                },
                severity="info"
            )
            
        except Exception as e:
            result.status = MigrationStatus.FAILED
            result.error_message = str(e)
            result.end_time = datetime.now(timezone.utc)
            
            # Update failure metrics
            migration_status.labels(
                migration_id=migration.revision_id,
                environment=os.getenv("ENVIRONMENT", "unknown")
            ).set(0)
            
            logger.error("migration_execution_failed",
                        migration_id=migration.revision_id,
                        error=str(e))
        
        return result
    
    async def rollback_migration(self, target_revision: str, 
                               test_rollback: bool = True) -> MigrationResult:
        """Rollback to a specific migration revision"""
        
        start_time = datetime.now(timezone.utc)
        result = MigrationResult(
            migration_id=target_revision,
            status=MigrationStatus.RUNNING,
            direction=MigrationDirection.DOWN,
            start_time=start_time
        )
        
        try:
            # Get current revision
            current_revision = await self._get_current_revision()
            
            if current_revision == target_revision:
                logger.info("already_at_target_revision", revision=target_revision)
                result.status = MigrationStatus.SUCCESS
                result.end_time = datetime.now(timezone.utc)
                return result
            
            # Test rollback if requested
            if test_rollback:
                logger.info("testing_rollback", target_revision=target_revision)
                
                # This would involve testing the rollback in an isolated environment
                # For now, we'll do basic validation
                
                rollback_migrations = await self._get_rollback_migrations(
                    current_revision, target_revision
                )
                
                for migration in rollback_migrations:
                    if not migration.down_sql:
                        raise ValueError(f"No rollback SQL for migration {migration.revision_id}")
            
            # Execute rollback
            logger.info("executing_rollback", target_revision=target_revision)
            
            rollback_start = datetime.now()
            
            config = Config(self.alembic_config_path)
            command.downgrade(config, target_revision)
            
            duration = (datetime.now() - rollback_start).total_seconds()
            
            migration_duration.labels(
                migration_id=target_revision,
                direction="down"
            ).observe(duration)
            
            migration_rollback_count.labels(
                migration_id=target_revision,
                reason="manual"
            ).inc()
            
            result.duration_seconds = duration
            result.status = MigrationStatus.SUCCESS
            result.end_time = datetime.now(timezone.utc)
            
            # Update metrics
            migration_status.labels(
                migration_id=target_revision,
                environment=os.getenv("ENVIRONMENT", "unknown")
            ).set(-1)  # -1 indicates rollback
            
            audit_logger.log_security_event(
                event_type="database_migration_rolled_back",
                details={
                    "target_revision": target_revision,
                    "from_revision": current_revision,
                    "duration_seconds": duration
                },
                severity="medium"
            )
            
        except Exception as e:
            result.status = MigrationStatus.FAILED
            result.error_message = str(e)
            result.end_time = datetime.now(timezone.utc)
            
            logger.error("rollback_failed",
                        target_revision=target_revision,
                        error=str(e))
        
        # Log rollback result
        await self._log_migration_result(result)
        
        return result
    
    async def _get_pending_migrations(self, target_revision: Optional[str] = None) -> List[MigrationInfo]:
        """Get list of pending migrations"""
        try:
            config = Config(self.alembic_config_path)
            script_dir = ScriptDirectory.from_config(config)
            
            # Get current revision
            current_revision = await self._get_current_revision()
            
            # Get migration chain
            if target_revision:
                revisions = list(script_dir.walk_revisions(target_revision, current_revision))
            else:
                revisions = list(script_dir.walk_revisions("head", current_revision))
            
            migrations = []
            for revision in reversed(revisions):  # Execute in forward order
                if revision.revision != current_revision:
                    migration_info = await self._create_migration_info(revision)
                    migrations.append(migration_info)
            
            return migrations
            
        except Exception as e:
            logger.error("failed_to_get_pending_migrations", error=str(e))
            return []
    
    async def _get_rollback_migrations(self, from_revision: str, 
                                     to_revision: str) -> List[MigrationInfo]:
        """Get migrations needed for rollback"""
        try:
            config = Config(self.alembic_config_path)
            script_dir = ScriptDirectory.from_config(config)
            
            # Get migration chain for rollback
            revisions = list(script_dir.walk_revisions(from_revision, to_revision))
            
            migrations = []
            for revision in revisions:
                if revision.revision != to_revision:
                    migration_info = await self._create_migration_info(revision)
                    migrations.append(migration_info)
            
            return migrations
            
        except Exception as e:
            logger.error("failed_to_get_rollback_migrations", error=str(e))
            return []
    
    async def _create_migration_info(self, revision) -> MigrationInfo:
        """Create MigrationInfo from Alembic revision"""
        # Read migration file
        migration_file = Path(revision.path)
        migration_content = migration_file.read_text()
        
        # Extract UP and DOWN SQL (simplified - would need proper parsing)
        up_sql = self._extract_upgrade_sql(migration_content)
        down_sql = self._extract_downgrade_sql(migration_content)
        
        return MigrationInfo(
            revision_id=revision.revision,
            description=revision.doc or "No description",
            file_path=str(migration_file),
            up_sql=up_sql,
            down_sql=down_sql,
            dependencies=list(revision.dependencies or [])
        )
    
    def _extract_upgrade_sql(self, content: str) -> str:
        """Extract upgrade SQL from migration file"""
        # This is a simplified extraction - production would use AST parsing
        lines = content.split('\n')
        in_upgrade = False
        sql_lines = []
        
        for line in lines:
            if 'def upgrade():' in line:
                in_upgrade = True
                continue
            elif 'def downgrade():' in line:
                in_upgrade = False
                break
            elif in_upgrade and ('op.' in line or 'conn.execute' in line):
                sql_lines.append(line.strip())
        
        return '\n'.join(sql_lines)
    
    def _extract_downgrade_sql(self, content: str) -> str:
        """Extract downgrade SQL from migration file"""
        # This is a simplified extraction - production would use AST parsing
        lines = content.split('\n')
        in_downgrade = False
        sql_lines = []
        
        for line in lines:
            if 'def downgrade():' in line:
                in_downgrade = True
                continue
            elif in_downgrade and ('op.' in line or 'conn.execute' in line):
                sql_lines.append(line.strip())
        
        return '\n'.join(sql_lines)
    
    async def _get_current_revision(self) -> Optional[str]:
        """Get current database revision"""
        try:
            async with self.pool.acquire() as conn:
                # Check if alembic_version table exists
                table_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'alembic_version'
                    )
                """)
                
                if not table_exists:
                    return None
                
                # Get current version
                current_version = await conn.fetchval(
                    "SELECT version_num FROM alembic_version"
                )
                
                return current_version
                
        except Exception as e:
            logger.error("failed_to_get_current_revision", error=str(e))
            return None
    
    def _get_test_database_url(self) -> str:
        """Get test database URL for migration testing"""
        # This would be configured based on environment
        # For now, return a placeholder
        return os.getenv("TEST_DATABASE_URL", "postgresql://test:test@localhost/test_db")
    
    async def _log_migration_result(self, result: MigrationResult):
        """Log migration result to tracking table"""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO migration_execution_log 
                    (migration_id, direction, status, start_time, end_time, 
                     duration_seconds, error_message, test_results, rollback_sql)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, 
                result.migration_id,
                result.direction.value,
                result.status.value,
                result.start_time,
                result.end_time,
                result.duration_seconds,
                result.error_message,
                json.dumps(result.test_results) if result.test_results else None,
                result.rollback_sql
                )
                
        except Exception as e:
            logger.error("failed_to_log_migration_result", error=str(e))
    
    async def get_migration_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get migration execution history"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM migration_execution_log
                    ORDER BY created_at DESC
                    LIMIT $1
                """, limit)
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error("failed_to_get_migration_history", error=str(e))
            return []
    
    async def validate_migration_integrity(self) -> Dict[str, Any]:
        """Validate migration integrity and consistency"""
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        try:
            # Check Alembic configuration
            config = Config(self.alembic_config_path)
            script_dir = ScriptDirectory.from_config(config)
            
            # Validate migration chain
            try:
                revisions = list(script_dir.walk_revisions())
                validation_result["total_migrations"] = len(revisions)
            except Exception as e:
                validation_result["errors"].append(f"Migration chain validation failed: {str(e)}")
                validation_result["valid"] = False
            
            # Check database state
            current_revision = await self._get_current_revision()
            validation_result["current_revision"] = current_revision
            
            if not current_revision:
                validation_result["warnings"].append("No current revision found - database may not be initialized")
            
            # Additional integrity checks would go here
            
        except Exception as e:
            validation_result["errors"].append(f"Validation error: {str(e)}")
            validation_result["valid"] = False
        
        return validation_result