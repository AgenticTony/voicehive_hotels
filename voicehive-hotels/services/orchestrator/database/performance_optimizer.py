"""
Database Performance & Reliability Optimizer for VoiceHive Hotels
Comprehensive database indexing, monitoring, and optimization system
"""

import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import json
import hashlib
from pathlib import Path

import asyncpg
from sqlalchemy import text, MetaData, Table, Column, Index
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel, Field

from prometheus_client import Gauge, Counter, Histogram, Summary
from logging_adapter import get_safe_logger
from audit_logging import AuditLogger

logger = get_safe_logger("orchestrator.db_performance")
audit_logger = AuditLogger("database_performance")

# Prometheus metrics for database performance monitoring
db_query_duration = Histogram(
    'voicehive_db_query_duration_seconds',
    'Database query execution time',
    ['query_type', 'table', 'operation'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

db_slow_queries = Counter(
    'voicehive_db_slow_queries_total',
    'Number of slow database queries',
    ['query_type', 'table', 'threshold']
)

db_connection_pool_size = Gauge(
    'voicehive_db_connection_pool_size',
    'Database connection pool size',
    ['pool_name', 'status']
)

db_index_usage = Gauge(
    'voicehive_db_index_usage_ratio',
    'Database index usage ratio',
    ['table', 'index_name']
)

db_table_size = Gauge(
    'voicehive_db_table_size_bytes',
    'Database table size in bytes',
    ['table', 'schema']
)

db_query_cache_hits = Counter(
    'voicehive_db_query_cache_hits_total',
    'Database query cache hits',
    ['cache_type']
)

db_backup_status = Gauge(
    'voicehive_db_backup_status',
    'Database backup status (1=success, 0=failure)',
    ['backup_type']
)

db_migration_status = Gauge(
    'voicehive_db_migration_status',
    'Database migration status (1=success, 0=failure)',
    ['migration_version']
)


class QueryType(str, Enum):
    """Database query types for monitoring"""
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    DDL = "ddl"
    MAINTENANCE = "maintenance"


class IndexType(str, Enum):
    """Database index types"""
    BTREE = "btree"
    HASH = "hash"
    GIN = "gin"
    GIST = "gist"
    BRIN = "brin"
    PARTIAL = "partial"
    UNIQUE = "unique"
    COMPOSITE = "composite"


@dataclass
class IndexRecommendation:
    """Database index recommendation"""
    table_name: str
    columns: List[str]
    index_type: IndexType
    estimated_benefit: float
    query_patterns: List[str]
    creation_sql: str
    priority: int = field(default=1)  # 1=high, 2=medium, 3=low
    
    def __post_init__(self):
        """Generate index name and creation SQL"""
        if not hasattr(self, 'index_name'):
            column_names = '_'.join(self.columns)
            self.index_name = f"idx_{self.table_name}_{column_names}"
        
        if not self.creation_sql:
            columns_str = ', '.join(self.columns)
            self.creation_sql = f"CREATE INDEX CONCURRENTLY {self.index_name} ON {self.table_name} ({columns_str})"


@dataclass
class QueryPerformanceStats:
    """Query performance statistics"""
    query_hash: str
    query_text: str
    execution_count: int
    total_time_ms: float
    avg_time_ms: float
    max_time_ms: float
    min_time_ms: float
    rows_examined: int
    rows_returned: int
    table_scans: int
    index_scans: int
    last_executed: datetime
    
    @property
    def is_slow(self) -> bool:
        """Check if query is considered slow"""
        return self.avg_time_ms > 1000  # 1 second threshold


class DatabaseIndexStrategy:
    """Comprehensive database indexing strategy"""
    
    def __init__(self, connection_pool):
        self.pool = connection_pool
        self.index_recommendations: List[IndexRecommendation] = []
        self.existing_indexes: Dict[str, List[str]] = {}
        
    async def analyze_query_patterns(self) -> List[IndexRecommendation]:
        """Analyze query patterns and recommend indexes"""
        recommendations = []
        
        async with self.pool.acquire() as conn:
            # Get slow queries from pg_stat_statements
            slow_queries = await self._get_slow_queries(conn)
            
            # Analyze each slow query for index opportunities
            for query_stats in slow_queries:
                query_recommendations = await self._analyze_query_for_indexes(
                    conn, query_stats
                )
                recommendations.extend(query_recommendations)
            
            # Get missing indexes from pg_stat_user_tables
            missing_indexes = await self._find_missing_indexes(conn)
            recommendations.extend(missing_indexes)
            
            # Prioritize recommendations
            recommendations = self._prioritize_recommendations(recommendations)
        
        self.index_recommendations = recommendations
        return recommendations
    
    async def _get_slow_queries(self, conn) -> List[QueryPerformanceStats]:
        """Get slow queries from pg_stat_statements"""
        query = """
        SELECT 
            queryid,
            query,
            calls,
            total_exec_time,
            mean_exec_time,
            max_exec_time,
            min_exec_time,
            rows,
            shared_blks_hit,
            shared_blks_read
        FROM pg_stat_statements 
        WHERE mean_exec_time > 100  -- Queries slower than 100ms
        ORDER BY mean_exec_time DESC 
        LIMIT 50
        """
        
        try:
            rows = await conn.fetch(query)
            stats = []
            
            for row in rows:
                stats.append(QueryPerformanceStats(
                    query_hash=str(row['queryid']),
                    query_text=row['query'],
                    execution_count=row['calls'],
                    total_time_ms=row['total_exec_time'],
                    avg_time_ms=row['mean_exec_time'],
                    max_time_ms=row['max_exec_time'],
                    min_time_ms=row['min_exec_time'],
                    rows_examined=row['shared_blks_read'],
                    rows_returned=row['rows'],
                    table_scans=0,  # Would need additional analysis
                    index_scans=row['shared_blks_hit'],
                    last_executed=datetime.now(timezone.utc)
                ))
            
            return stats
            
        except Exception as e:
            logger.warning("pg_stat_statements_not_available", error=str(e))
            return []
    
    async def _analyze_query_for_indexes(self, conn, query_stats: QueryPerformanceStats) -> List[IndexRecommendation]:
        """Analyze a specific query for index opportunities"""
        recommendations = []
        query_text = query_stats.query_text.lower()
        
        # Simple pattern matching for common index opportunities
        # In production, this would use a proper SQL parser
        
        # WHERE clause analysis
        if 'where' in query_text:
            where_columns = self._extract_where_columns(query_text)
            for table, columns in where_columns.items():
                if len(columns) == 1:
                    # Single column index
                    recommendations.append(IndexRecommendation(
                        table_name=table,
                        columns=columns,
                        index_type=IndexType.BTREE,
                        estimated_benefit=query_stats.avg_time_ms * 0.7,
                        query_patterns=[query_stats.query_hash],
                        creation_sql="",
                        priority=1 if query_stats.avg_time_ms > 1000 else 2
                    ))
                elif len(columns) > 1:
                    # Composite index
                    recommendations.append(IndexRecommendation(
                        table_name=table,
                        columns=columns,
                        index_type=IndexType.COMPOSITE,
                        estimated_benefit=query_stats.avg_time_ms * 0.8,
                        query_patterns=[query_stats.query_hash],
                        creation_sql="",
                        priority=1
                    ))
        
        # ORDER BY analysis
        if 'order by' in query_text:
            order_columns = self._extract_order_by_columns(query_text)
            for table, columns in order_columns.items():
                recommendations.append(IndexRecommendation(
                    table_name=table,
                    columns=columns,
                    index_type=IndexType.BTREE,
                    estimated_benefit=query_stats.avg_time_ms * 0.5,
                    query_patterns=[query_stats.query_hash],
                    creation_sql="",
                    priority=2
                ))
        
        # JOIN analysis
        if 'join' in query_text:
            join_columns = self._extract_join_columns(query_text)
            for table, columns in join_columns.items():
                recommendations.append(IndexRecommendation(
                    table_name=table,
                    columns=columns,
                    index_type=IndexType.BTREE,
                    estimated_benefit=query_stats.avg_time_ms * 0.6,
                    query_patterns=[query_stats.query_hash],
                    creation_sql="",
                    priority=1
                ))
        
        return recommendations
    
    def _extract_where_columns(self, query_text: str) -> Dict[str, List[str]]:
        """Extract columns used in WHERE clauses"""
        # Simplified extraction - in production use proper SQL parser
        columns_by_table = {}
        
        # Basic pattern matching for WHERE conditions
        import re
        
        # Match patterns like "table.column = value" or "column = value"
        where_patterns = re.findall(
            r'where\s+(?:(\w+)\.)?(\w+)\s*[=<>!]',
            query_text,
            re.IGNORECASE
        )
        
        for table, column in where_patterns:
            table = table or 'unknown_table'
            if table not in columns_by_table:
                columns_by_table[table] = []
            if column not in columns_by_table[table]:
                columns_by_table[table].append(column)
        
        return columns_by_table
    
    def _extract_order_by_columns(self, query_text: str) -> Dict[str, List[str]]:
        """Extract columns used in ORDER BY clauses"""
        columns_by_table = {}
        
        import re
        order_patterns = re.findall(
            r'order\s+by\s+(?:(\w+)\.)?(\w+)',
            query_text,
            re.IGNORECASE
        )
        
        for table, column in order_patterns:
            table = table or 'unknown_table'
            if table not in columns_by_table:
                columns_by_table[table] = []
            if column not in columns_by_table[table]:
                columns_by_table[table].append(column)
        
        return columns_by_table
    
    def _extract_join_columns(self, query_text: str) -> Dict[str, List[str]]:
        """Extract columns used in JOIN conditions"""
        columns_by_table = {}
        
        import re
        join_patterns = re.findall(
            r'join\s+\w+\s+(?:as\s+)?(\w+)\s+on\s+(?:\w+\.)?(\w+)\s*=\s*(?:(\w+)\.)?(\w+)',
            query_text,
            re.IGNORECASE
        )
        
        for table1, col1, table2, col2 in join_patterns:
            # Add both sides of the join
            if table1 not in columns_by_table:
                columns_by_table[table1] = []
            if col1 not in columns_by_table[table1]:
                columns_by_table[table1].append(col1)
            
            if table2:
                if table2 not in columns_by_table:
                    columns_by_table[table2] = []
                if col2 not in columns_by_table[table2]:
                    columns_by_table[table2].append(col2)
        
        return columns_by_table
    
    async def _find_missing_indexes(self, conn) -> List[IndexRecommendation]:
        """Find missing indexes based on table statistics"""
        recommendations = []
        
        # Get tables with high sequential scan ratios
        query = """
        SELECT 
            schemaname,
            tablename,
            seq_scan,
            seq_tup_read,
            idx_scan,
            idx_tup_fetch,
            n_tup_ins + n_tup_upd + n_tup_del as modifications
        FROM pg_stat_user_tables
        WHERE seq_scan > 0
        ORDER BY seq_tup_read DESC
        LIMIT 20
        """
        
        try:
            rows = await conn.fetch(query)
            
            for row in rows:
                table_name = row['tablename']
                seq_scans = row['seq_scan']
                idx_scans = row['idx_scan'] or 0
                
                # High sequential scan ratio indicates missing indexes
                if seq_scans > 0 and (idx_scans / (seq_scans + idx_scans)) < 0.1:
                    # Get frequently queried columns for this table
                    frequent_columns = await self._get_frequent_columns(conn, table_name)
                    
                    if frequent_columns:
                        recommendations.append(IndexRecommendation(
                            table_name=table_name,
                            columns=frequent_columns[:3],  # Top 3 columns
                            index_type=IndexType.BTREE,
                            estimated_benefit=seq_scans * 100,  # Rough estimate
                            query_patterns=[],
                            creation_sql="",
                            priority=2
                        ))
            
        except Exception as e:
            logger.error("failed_to_analyze_missing_indexes", error=str(e))
        
        return recommendations
    
    async def _get_frequent_columns(self, conn, table_name: str) -> List[str]:
        """Get frequently queried columns for a table"""
        # This would require more sophisticated analysis in production
        # For now, return common column patterns
        
        try:
            # Get table schema to identify likely indexed columns
            query = """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = $1
            AND column_name IN ('id', 'created_at', 'updated_at', 'user_id', 'status', 'type')
            ORDER BY ordinal_position
            """
            
            rows = await conn.fetch(query, table_name)
            return [row['column_name'] for row in rows]
            
        except Exception:
            return ['id', 'created_at']  # Safe defaults
    
    def _prioritize_recommendations(self, recommendations: List[IndexRecommendation]) -> List[IndexRecommendation]:
        """Prioritize index recommendations by benefit and impact"""
        
        # Remove duplicates
        unique_recommendations = {}
        for rec in recommendations:
            key = f"{rec.table_name}_{'-'.join(rec.columns)}"
            if key not in unique_recommendations or rec.estimated_benefit > unique_recommendations[key].estimated_benefit:
                unique_recommendations[key] = rec
        
        # Sort by priority and estimated benefit
        sorted_recommendations = sorted(
            unique_recommendations.values(),
            key=lambda x: (x.priority, -x.estimated_benefit)
        )
        
        return sorted_recommendations[:20]  # Top 20 recommendations
    
    async def create_recommended_indexes(self, recommendations: Optional[List[IndexRecommendation]] = None) -> Dict[str, bool]:
        """Create recommended indexes"""
        if not recommendations:
            recommendations = self.index_recommendations
        
        results = {}
        
        async with self.pool.acquire() as conn:
            for rec in recommendations:
                try:
                    # Check if index already exists
                    if await self._index_exists(conn, rec.index_name):
                        logger.info("index_already_exists", index_name=rec.index_name)
                        results[rec.index_name] = True
                        continue
                    
                    # Create index concurrently to avoid blocking
                    logger.info("creating_index", 
                              index_name=rec.index_name,
                              table=rec.table_name,
                              columns=rec.columns)
                    
                    await conn.execute(rec.creation_sql)
                    results[rec.index_name] = True
                    
                    # Log successful creation
                    audit_logger.log_security_event(
                        event_type="database_index_created",
                        details={
                            "index_name": rec.index_name,
                            "table_name": rec.table_name,
                            "columns": rec.columns,
                            "estimated_benefit": rec.estimated_benefit
                        },
                        severity="info"
                    )
                    
                except Exception as e:
                    logger.error("failed_to_create_index",
                               index_name=rec.index_name,
                               error=str(e))
                    results[rec.index_name] = False
        
        return results
    
    async def _index_exists(self, conn, index_name: str) -> bool:
        """Check if an index already exists"""
        query = """
        SELECT 1 FROM pg_indexes 
        WHERE indexname = $1
        """
        
        result = await conn.fetchval(query, index_name)
        return result is not None


class QueryPerformanceMonitor:
    """Real-time query performance monitoring"""
    
    def __init__(self, connection_pool):
        self.pool = connection_pool
        self.slow_query_threshold_ms = 1000
        self.monitoring_enabled = True
        self.query_cache = {}
        
    async def start_monitoring(self):
        """Start continuous query performance monitoring"""
        logger.info("starting_query_performance_monitoring")
        
        while self.monitoring_enabled:
            try:
                await self._collect_performance_metrics()
                await self._check_slow_queries()
                await self._update_index_usage_stats()
                await asyncio.sleep(30)  # Monitor every 30 seconds
                
            except Exception as e:
                logger.error("query_monitoring_error", error=str(e))
                await asyncio.sleep(60)  # Longer sleep on error
    
    async def _collect_performance_metrics(self):
        """Collect database performance metrics"""
        async with self.pool.acquire() as conn:
            # Connection pool metrics
            pool_stats = await self._get_connection_pool_stats(conn)
            for stat_name, value in pool_stats.items():
                db_connection_pool_size.labels(
                    pool_name="default",
                    status=stat_name
                ).set(value)
            
            # Table size metrics
            table_sizes = await self._get_table_sizes(conn)
            for table_name, size_bytes in table_sizes.items():
                db_table_size.labels(
                    table=table_name,
                    schema="public"
                ).set(size_bytes)
    
    async def _get_connection_pool_stats(self, conn) -> Dict[str, int]:
        """Get connection pool statistics"""
        try:
            # PostgreSQL connection stats
            query = """
            SELECT 
                state,
                count(*) as count
            FROM pg_stat_activity 
            WHERE datname = current_database()
            GROUP BY state
            """
            
            rows = await conn.fetch(query)
            stats = {}
            
            for row in rows:
                state = row['state'] or 'unknown'
                stats[state] = row['count']
            
            return stats
            
        except Exception as e:
            logger.error("failed_to_get_connection_stats", error=str(e))
            return {}
    
    async def _get_table_sizes(self, conn) -> Dict[str, int]:
        """Get table sizes in bytes"""
        try:
            query = """
            SELECT 
                tablename,
                pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
            FROM pg_tables 
            WHERE schemaname = 'public'
            """
            
            rows = await conn.fetch(query)
            return {row['tablename']: row['size_bytes'] for row in rows}
            
        except Exception as e:
            logger.error("failed_to_get_table_sizes", error=str(e))
            return {}
    
    async def _check_slow_queries(self):
        """Check for slow queries and alert"""
        async with self.pool.acquire() as conn:
            try:
                # Get currently running slow queries
                query = """
                SELECT 
                    pid,
                    now() - pg_stat_activity.query_start AS duration,
                    query,
                    state
                FROM pg_stat_activity 
                WHERE (now() - pg_stat_activity.query_start) > interval '%s milliseconds'
                AND state = 'active'
                """ % self.slow_query_threshold_ms
                
                slow_queries = await conn.fetch(query)
                
                for query_info in slow_queries:
                    duration_ms = query_info['duration'].total_seconds() * 1000
                    
                    # Record slow query metric
                    db_slow_queries.labels(
                        query_type="unknown",
                        table="unknown",
                        threshold=str(self.slow_query_threshold_ms)
                    ).inc()
                    
                    # Log slow query
                    logger.warning("slow_query_detected",
                                 pid=query_info['pid'],
                                 duration_ms=duration_ms,
                                 query=query_info['query'][:200])  # Truncate long queries
                
            except Exception as e:
                logger.error("failed_to_check_slow_queries", error=str(e))
    
    async def _update_index_usage_stats(self):
        """Update index usage statistics"""
        async with self.pool.acquire() as conn:
            try:
                query = """
                SELECT 
                    schemaname,
                    tablename,
                    indexname,
                    idx_scan,
                    idx_tup_read,
                    idx_tup_fetch
                FROM pg_stat_user_indexes
                WHERE idx_scan > 0
                """
                
                rows = await conn.fetch(query)
                
                for row in rows:
                    # Calculate index usage ratio
                    scans = row['idx_scan']
                    reads = row['idx_tup_read'] or 1
                    usage_ratio = min(scans / reads, 1.0) if reads > 0 else 0
                    
                    db_index_usage.labels(
                        table=row['tablename'],
                        index_name=row['indexname']
                    ).set(usage_ratio)
                
            except Exception as e:
                logger.error("failed_to_update_index_stats", error=str(e))
    
    def stop_monitoring(self):
        """Stop query performance monitoring"""
        self.monitoring_enabled = False
        logger.info("query_performance_monitoring_stopped")


class DatabasePerformanceOptimizer:
    """Main database performance optimization coordinator"""
    
    def __init__(self, connection_pool):
        self.pool = connection_pool
        self.index_strategy = DatabaseIndexStrategy(connection_pool)
        self.query_monitor = QueryPerformanceMonitor(connection_pool)
        self.optimization_tasks = []
        
    async def initialize(self):
        """Initialize the database performance optimizer"""
        logger.info("initializing_database_performance_optimizer")
        
        # Start query monitoring
        monitor_task = asyncio.create_task(self.query_monitor.start_monitoring())
        self.optimization_tasks.append(monitor_task)
        
        # Schedule periodic optimization
        optimization_task = asyncio.create_task(self._periodic_optimization())
        self.optimization_tasks.append(optimization_task)
        
        logger.info("database_performance_optimizer_initialized")
    
    async def _periodic_optimization(self):
        """Run periodic database optimization"""
        while True:
            try:
                # Run optimization every hour
                await asyncio.sleep(3600)
                
                logger.info("starting_periodic_database_optimization")
                
                # Analyze and create recommended indexes
                recommendations = await self.index_strategy.analyze_query_patterns()
                
                if recommendations:
                    logger.info("found_index_recommendations", count=len(recommendations))
                    
                    # Create high-priority indexes automatically
                    high_priority = [r for r in recommendations if r.priority == 1]
                    if high_priority:
                        results = await self.index_strategy.create_recommended_indexes(high_priority)
                        logger.info("created_high_priority_indexes", results=results)
                
                # Update table statistics
                await self._update_table_statistics()
                
                logger.info("periodic_database_optimization_completed")
                
            except Exception as e:
                logger.error("periodic_optimization_error", error=str(e))
    
    async def _update_table_statistics(self):
        """Update table statistics for query planner"""
        async with self.pool.acquire() as conn:
            try:
                # Get all user tables
                tables_query = """
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public'
                """
                
                tables = await conn.fetch(tables_query)
                
                for table in tables:
                    table_name = table['tablename']
                    
                    # Update statistics for each table
                    await conn.execute(f"ANALYZE {table_name}")
                    
                    logger.debug("updated_table_statistics", table=table_name)
                
                logger.info("updated_all_table_statistics", count=len(tables))
                
            except Exception as e:
                logger.error("failed_to_update_statistics", error=str(e))
    
    async def get_performance_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report"""
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "index_recommendations": [],
            "slow_queries": [],
            "table_stats": {},
            "connection_pool_stats": {},
            "optimization_suggestions": []
        }
        
        try:
            # Get index recommendations
            recommendations = await self.index_strategy.analyze_query_patterns()
            report["index_recommendations"] = [
                {
                    "table": rec.table_name,
                    "columns": rec.columns,
                    "type": rec.index_type,
                    "estimated_benefit": rec.estimated_benefit,
                    "priority": rec.priority
                }
                for rec in recommendations
            ]
            
            # Get performance metrics
            async with self.pool.acquire() as conn:
                # Connection stats
                report["connection_pool_stats"] = await self.query_monitor._get_connection_pool_stats(conn)
                
                # Table sizes
                report["table_stats"] = await self.query_monitor._get_table_sizes(conn)
            
            # Generate optimization suggestions
            report["optimization_suggestions"] = self._generate_optimization_suggestions(report)
            
        except Exception as e:
            logger.error("failed_to_generate_performance_report", error=str(e))
            report["error"] = str(e)
        
        return report
    
    def _generate_optimization_suggestions(self, report: Dict[str, Any]) -> List[str]:
        """Generate optimization suggestions based on report data"""
        suggestions = []
        
        # Check for large tables without indexes
        for table, size_bytes in report.get("table_stats", {}).items():
            if size_bytes > 100 * 1024 * 1024:  # 100MB
                suggestions.append(f"Consider partitioning large table: {table} ({size_bytes // (1024*1024)}MB)")
        
        # Check for high-priority index recommendations
        high_priority_indexes = [
            rec for rec in report.get("index_recommendations", [])
            if rec["priority"] == 1
        ]
        
        if high_priority_indexes:
            suggestions.append(f"Create {len(high_priority_indexes)} high-priority indexes to improve performance")
        
        # Check connection pool utilization
        conn_stats = report.get("connection_pool_stats", {})
        active_connections = conn_stats.get("active", 0)
        idle_connections = conn_stats.get("idle", 0)
        
        if active_connections > idle_connections * 2:
            suggestions.append("Consider increasing connection pool size - high active connection ratio")
        
        return suggestions
    
    async def shutdown(self):
        """Shutdown the performance optimizer"""
        logger.info("shutting_down_database_performance_optimizer")
        
        # Stop monitoring
        self.query_monitor.stop_monitoring()
        
        # Cancel optimization tasks
        for task in self.optimization_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self.optimization_tasks:
            await asyncio.gather(*self.optimization_tasks, return_exceptions=True)
        
        logger.info("database_performance_optimizer_shutdown_complete")