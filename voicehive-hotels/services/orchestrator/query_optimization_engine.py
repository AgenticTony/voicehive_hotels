"""
Advanced Database Query Optimization Engine for VoiceHive Hotels
Real-time query analysis, optimization, and performance monitoring
"""

import asyncio
import time
import json
import hashlib
from typing import Dict, List, Optional, Any, Tuple, Set, Union
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import re
import statistics

import asyncpg
from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger

try:
    from prometheus_client import Counter, Histogram, Gauge, Summary
except ImportError:
    # Mock Prometheus metrics if not available
    class MockMetric:
        def __init__(self, *args, **kwargs):
            pass
        def labels(self, **kwargs):
            return self
        def set(self, value):
            pass
        def inc(self, value=1):
            pass
        def observe(self, value):
            pass
    
    Counter = Histogram = Gauge = Summary = MockMetric

logger = get_safe_logger("orchestrator.query_optimization")

# Prometheus metrics for query optimization monitoring
query_execution_duration = Histogram(
    'voicehive_query_execution_duration_seconds',
    'Query execution duration',
    ['query_type', 'table', 'optimization_level'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

query_optimization_suggestions = Counter(
    'voicehive_query_optimization_suggestions_total',
    'Query optimization suggestions generated',
    ['suggestion_type', 'severity']
)

query_plan_cache_hits = Counter(
    'voicehive_query_plan_cache_hits_total',
    'Query plan cache hits',
    ['cache_type']
)

query_performance_score = Gauge(
    'voicehive_query_performance_score',
    'Query performance score (0-100)',
    ['query_hash']
)

slow_query_alerts = Counter(
    'voicehive_slow_query_alerts_total',
    'Slow query alerts generated',
    ['severity', 'table']
)

index_effectiveness = Gauge(
    'voicehive_index_effectiveness_ratio',
    'Index effectiveness ratio',
    ['table', 'index_name']
)


class QueryType(str, Enum):
    """Database query types"""
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    CREATE = "create"
    ALTER = "alter"
    DROP = "drop"
    ANALYZE = "analyze"
    VACUUM = "vacuum"
    UNKNOWN = "unknown"


class OptimizationLevel(str, Enum):
    """Query optimization levels"""
    NONE = "none"
    BASIC = "basic"
    ADVANCED = "advanced"
    AGGRESSIVE = "aggressive"


class SuggestionType(str, Enum):
    """Query optimization suggestion types"""
    ADD_INDEX = "add_index"
    MODIFY_QUERY = "modify_query"
    PARTITION_TABLE = "partition_table"
    UPDATE_STATISTICS = "update_statistics"
    REWRITE_QUERY = "rewrite_query"
    ADD_CONSTRAINT = "add_constraint"
    OPTIMIZE_JOIN = "optimize_join"
    USE_MATERIALIZED_VIEW = "use_materialized_view"


class SuggestionSeverity(str, Enum):
    """Optimization suggestion severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class QueryPlan:
    """Database query execution plan"""
    query_hash: str
    plan_json: Dict[str, Any]
    total_cost: float
    startup_cost: float
    rows: int
    width: int
    actual_time: Optional[float] = None
    actual_rows: Optional[int] = None
    loops: int = 1
    
    @property
    def cost_per_row(self) -> float:
        return self.total_cost / max(self.rows, 1)
    
    @property
    def is_expensive(self) -> bool:
        return self.total_cost > 1000 or (self.actual_time and self.actual_time > 1.0)


@dataclass
class QueryStats:
    """Query execution statistics"""
    query_hash: str
    query_text: str
    query_type: QueryType
    table_names: List[str]
    execution_count: int = 0
    total_time_ms: float = 0.0
    min_time_ms: float = float('inf')
    max_time_ms: float = 0.0
    avg_time_ms: float = 0.0
    std_dev_ms: float = 0.0
    rows_examined: int = 0
    rows_returned: int = 0
    last_executed: Optional[datetime] = None
    plan: Optional[QueryPlan] = None
    
    def add_execution(self, duration_ms: float, rows_examined: int = 0, rows_returned: int = 0):
        """Add a new execution to the statistics"""
        self.execution_count += 1
        self.total_time_ms += duration_ms
        self.min_time_ms = min(self.min_time_ms, duration_ms)
        self.max_time_ms = max(self.max_time_ms, duration_ms)
        self.avg_time_ms = self.total_time_ms / self.execution_count
        self.rows_examined += rows_examined
        self.rows_returned += rows_returned
        self.last_executed = datetime.now(timezone.utc)
    
    @property
    def is_slow(self) -> bool:
        return self.avg_time_ms > 1000  # 1 second threshold
    
    @property
    def performance_score(self) -> float:
        """Calculate performance score (0-100, higher is better)"""
        if self.execution_count == 0:
            return 0.0
        
        # Base score on average execution time
        time_score = max(0, 100 - (self.avg_time_ms / 10))  # 10ms = 99 points
        
        # Adjust for consistency (lower std dev is better)
        consistency_factor = 1.0
        if self.execution_count > 1:
            cv = self.std_dev_ms / max(self.avg_time_ms, 1)  # Coefficient of variation
            consistency_factor = max(0.5, 1.0 - cv)
        
        # Adjust for efficiency (rows returned vs examined)
        efficiency_factor = 1.0
        if self.rows_examined > 0:
            efficiency_factor = min(1.0, self.rows_returned / self.rows_examined)
        
        return min(100.0, time_score * consistency_factor * efficiency_factor)


@dataclass
class OptimizationSuggestion:
    """Query optimization suggestion"""
    suggestion_type: SuggestionType
    severity: SuggestionSeverity
    query_hash: str
    table_name: str
    description: str
    sql_statement: Optional[str] = None
    estimated_improvement: Optional[float] = None
    implementation_cost: str = "low"  # low, medium, high
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.suggestion_type,
            "severity": self.severity,
            "query_hash": self.query_hash,
            "table": self.table_name,
            "description": self.description,
            "sql": self.sql_statement,
            "estimated_improvement": self.estimated_improvement,
            "cost": self.implementation_cost,
            "created_at": self.created_at.isoformat()
        }


class QueryOptimizationConfig(BaseModel):
    """Configuration for query optimization engine"""
    # Analysis settings
    enable_real_time_analysis: bool = Field(True, description="Enable real-time query analysis")
    enable_plan_caching: bool = Field(True, description="Enable query plan caching")
    enable_automatic_optimization: bool = Field(False, description="Enable automatic optimization")
    
    # Performance thresholds
    slow_query_threshold_ms: float = Field(1000.0, description="Slow query threshold in ms")
    expensive_query_cost_threshold: float = Field(1000.0, description="Expensive query cost threshold")
    high_row_scan_threshold: int = Field(10000, description="High row scan threshold")
    
    # Monitoring settings
    stats_retention_hours: int = Field(24, description="Query stats retention in hours")
    plan_cache_size: int = Field(1000, description="Query plan cache size")
    analysis_interval_seconds: int = Field(300, description="Analysis interval in seconds")
    
    # Optimization settings
    max_suggestions_per_query: int = Field(5, description="Max suggestions per query")
    suggestion_confidence_threshold: float = Field(0.7, description="Suggestion confidence threshold")
    auto_create_indexes: bool = Field(False, description="Automatically create recommended indexes")
    
    # Alert settings
    enable_slow_query_alerts: bool = Field(True, description="Enable slow query alerts")
    alert_threshold_executions: int = Field(10, description="Min executions before alerting")
    
    # Database settings
    enable_pg_stat_statements: bool = Field(True, description="Use pg_stat_statements extension")
    enable_auto_explain: bool = Field(True, description="Use auto_explain extension")


class QueryAnalyzer:
    """Advanced query analysis and pattern recognition"""
    
    def __init__(self):
        self.query_patterns = {
            'missing_where_clause': re.compile(r'SELECT\s+.*\s+FROM\s+\w+(?!\s+WHERE)', re.IGNORECASE),
            'select_star': re.compile(r'SELECT\s+\*\s+FROM', re.IGNORECASE),
            'missing_limit': re.compile(r'SELECT\s+.*\s+FROM\s+\w+.*(?!LIMIT)', re.IGNORECASE),
            'cartesian_join': re.compile(r'FROM\s+\w+\s*,\s*\w+(?!\s+WHERE)', re.IGNORECASE),
            'subquery_in_select': re.compile(r'SELECT\s+.*\(\s*SELECT\s+.*\)\s*.*FROM', re.IGNORECASE),
            'or_conditions': re.compile(r'WHERE\s+.*\s+OR\s+.*', re.IGNORECASE),
            'function_in_where': re.compile(r'WHERE\s+.*\w+\s*\(.*\)\s*[=<>]', re.IGNORECASE),
            'like_leading_wildcard': re.compile(r"LIKE\s+['\"]%", re.IGNORECASE)
        }
    
    def analyze_query_text(self, query: str) -> Dict[str, Any]:
        """Analyze query text for potential issues"""
        analysis = {
            'query_type': self._detect_query_type(query),
            'table_names': self._extract_table_names(query),
            'potential_issues': [],
            'complexity_score': self._calculate_complexity_score(query),
            'estimated_selectivity': self._estimate_selectivity(query)
        }
        
        # Check for common anti-patterns
        for pattern_name, pattern in self.query_patterns.items():
            if pattern.search(query):
                analysis['potential_issues'].append(pattern_name)
        
        return analysis
    
    def _detect_query_type(self, query: str) -> QueryType:
        """Detect the type of SQL query"""
        query_upper = query.strip().upper()
        
        if query_upper.startswith('SELECT'):
            return QueryType.SELECT
        elif query_upper.startswith('INSERT'):
            return QueryType.INSERT
        elif query_upper.startswith('UPDATE'):
            return QueryType.UPDATE
        elif query_upper.startswith('DELETE'):
            return QueryType.DELETE
        elif query_upper.startswith('CREATE'):
            return QueryType.CREATE
        elif query_upper.startswith('ALTER'):
            return QueryType.ALTER
        elif query_upper.startswith('DROP'):
            return QueryType.DROP
        elif query_upper.startswith('ANALYZE'):
            return QueryType.ANALYZE
        elif query_upper.startswith('VACUUM'):
            return QueryType.VACUUM
        else:
            return QueryType.UNKNOWN
    
    def _extract_table_names(self, query: str) -> List[str]:
        """Extract table names from query"""
        # Simplified table name extraction
        # In production, use a proper SQL parser
        tables = []
        
        # FROM clause tables
        from_matches = re.findall(r'FROM\s+(\w+)', query, re.IGNORECASE)
        tables.extend(from_matches)
        
        # JOIN clause tables
        join_matches = re.findall(r'JOIN\s+(\w+)', query, re.IGNORECASE)
        tables.extend(join_matches)
        
        # UPDATE/INSERT/DELETE tables
        update_matches = re.findall(r'UPDATE\s+(\w+)', query, re.IGNORECASE)
        tables.extend(update_matches)
        
        insert_matches = re.findall(r'INSERT\s+INTO\s+(\w+)', query, re.IGNORECASE)
        tables.extend(insert_matches)
        
        delete_matches = re.findall(r'DELETE\s+FROM\s+(\w+)', query, re.IGNORECASE)
        tables.extend(delete_matches)
        
        return list(set(tables))  # Remove duplicates
    
    def _calculate_complexity_score(self, query: str) -> float:
        """Calculate query complexity score (0-100)"""
        score = 0.0
        
        # Base complexity factors
        score += len(re.findall(r'JOIN', query, re.IGNORECASE)) * 10
        score += len(re.findall(r'UNION', query, re.IGNORECASE)) * 15
        score += len(re.findall(r'SUBQUERY|\(SELECT', query, re.IGNORECASE)) * 20
        score += len(re.findall(r'GROUP BY', query, re.IGNORECASE)) * 5
        score += len(re.findall(r'ORDER BY', query, re.IGNORECASE)) * 3
        score += len(re.findall(r'HAVING', query, re.IGNORECASE)) * 8
        score += len(re.findall(r'CASE WHEN', query, re.IGNORECASE)) * 5
        
        # Query length factor
        score += len(query) / 100
        
        return min(100.0, score)
    
    def _estimate_selectivity(self, query: str) -> float:
        """Estimate query selectivity (0-1, lower is more selective)"""
        # Simplified selectivity estimation
        selectivity = 1.0
        
        # WHERE clause reduces selectivity
        if 'WHERE' in query.upper():
            selectivity *= 0.1  # Assume WHERE reduces to 10% of rows
            
            # Equality conditions are more selective
            eq_conditions = len(re.findall(r'=\s*[\'"]?\w+[\'"]?', query, re.IGNORECASE))
            selectivity *= (0.1 ** eq_conditions)
            
            # Range conditions are less selective
            range_conditions = len(re.findall(r'[<>]=?', query, re.IGNORECASE))
            selectivity *= (0.5 ** range_conditions)
            
            # LIKE conditions vary in selectivity
            like_conditions = len(re.findall(r'LIKE', query, re.IGNORECASE))
            selectivity *= (0.3 ** like_conditions)
        
        return max(0.001, min(1.0, selectivity))


class QueryOptimizationEngine:
    """Main query optimization engine"""
    
    def __init__(
        self,
        connection_pool,
        config: Optional[QueryOptimizationConfig] = None
    ):
        self.pool = connection_pool
        self.config = config or QueryOptimizationConfig()
        self.analyzer = QueryAnalyzer()
        
        # Query statistics and caching
        self.query_stats: Dict[str, QueryStats] = {}
        self.plan_cache: Dict[str, QueryPlan] = {}
        self.suggestions: Dict[str, List[OptimizationSuggestion]] = {}
        
        # Background tasks
        self.monitoring_tasks: List[asyncio.Task] = []
        
        # Performance tracking
        self.last_analysis_time = time.time()
        self.analysis_count = 0
    
    async def initialize(self):
        """Initialize the query optimization engine"""
        logger.info("initializing_query_optimization_engine")
        
        # Check for required extensions
        await self._check_database_extensions()
        
        # Start monitoring tasks
        if self.config.enable_real_time_analysis:
            task = asyncio.create_task(self._real_time_analysis_loop())
            self.monitoring_tasks.append(task)
        
        # Start periodic analysis
        task = asyncio.create_task(self._periodic_analysis_loop())
        self.monitoring_tasks.append(task)
        
        # Start cleanup task
        task = asyncio.create_task(self._cleanup_loop())
        self.monitoring_tasks.append(task)
        
        logger.info("query_optimization_engine_initialized",
                   tasks=len(self.monitoring_tasks))
    
    async def _check_database_extensions(self):
        """Check for required PostgreSQL extensions"""
        async with self.pool.acquire() as conn:
            try:
                # Check for pg_stat_statements
                result = await conn.fetchval(
                    "SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'"
                )
                
                if result and self.config.enable_pg_stat_statements:
                    logger.info("pg_stat_statements_available")
                else:
                    logger.warning("pg_stat_statements_not_available")
                
                # Check for auto_explain
                result = await conn.fetchval(
                    "SELECT setting FROM pg_settings WHERE name = 'shared_preload_libraries'"
                )
                
                if result and 'auto_explain' in result:
                    logger.info("auto_explain_available")
                else:
                    logger.warning("auto_explain_not_available")
            
            except Exception as e:
                logger.error("extension_check_failed", error=str(e))
    
    async def analyze_query(
        self,
        query: str,
        execution_time_ms: Optional[float] = None,
        rows_examined: int = 0,
        rows_returned: int = 0
    ) -> Dict[str, Any]:
        """Analyze a query and generate optimization suggestions"""
        start_time = time.time()
        
        try:
            # Generate query hash
            query_hash = hashlib.md5(query.encode()).hexdigest()
            
            # Analyze query text
            text_analysis = self.analyzer.analyze_query_text(query)
            
            # Get or create query stats
            if query_hash not in self.query_stats:
                self.query_stats[query_hash] = QueryStats(
                    query_hash=query_hash,
                    query_text=query,
                    query_type=text_analysis['query_type'],
                    table_names=text_analysis['table_names']
                )
            
            stats = self.query_stats[query_hash]
            
            # Update execution statistics
            if execution_time_ms is not None:
                stats.add_execution(execution_time_ms, rows_examined, rows_returned)
            
            # Get query plan if not cached
            if self.config.enable_plan_caching and query_hash not in self.plan_cache:
                plan = await self._get_query_plan(query)
                if plan:
                    self.plan_cache[query_hash] = plan
                    stats.plan = plan
            
            # Generate optimization suggestions
            suggestions = await self._generate_suggestions(stats, text_analysis)
            self.suggestions[query_hash] = suggestions
            
            # Update metrics
            query_performance_score.labels(query_hash=query_hash).set(stats.performance_score)
            
            if stats.is_slow and self.config.enable_slow_query_alerts:
                slow_query_alerts.labels(
                    severity="high" if stats.avg_time_ms > 5000 else "medium",
                    table=stats.table_names[0] if stats.table_names else "unknown"
                ).inc()
            
            # Record analysis duration
            analysis_duration = time.time() - start_time
            self.analysis_count += 1
            
            return {
                'query_hash': query_hash,
                'performance_score': stats.performance_score,
                'execution_stats': {
                    'count': stats.execution_count,
                    'avg_time_ms': stats.avg_time_ms,
                    'min_time_ms': stats.min_time_ms,
                    'max_time_ms': stats.max_time_ms
                },
                'text_analysis': text_analysis,
                'suggestions': [s.to_dict() for s in suggestions],
                'analysis_duration_ms': analysis_duration * 1000
            }
        
        except Exception as e:
            logger.error("query_analysis_failed", query_hash=query_hash, error=str(e))
            return {'error': str(e)}
    
    async def _get_query_plan(self, query: str) -> Optional[QueryPlan]:
        """Get query execution plan"""
        try:
            async with self.pool.acquire() as conn:
                # Get estimated plan
                plan_result = await conn.fetch(f"EXPLAIN (FORMAT JSON) {query}")
                
                if plan_result and len(plan_result) > 0:
                    plan_json = plan_result[0]['QUERY PLAN'][0]
                    
                    return QueryPlan(
                        query_hash=hashlib.md5(query.encode()).hexdigest(),
                        plan_json=plan_json,
                        total_cost=plan_json.get('Total Cost', 0),
                        startup_cost=plan_json.get('Startup Cost', 0),
                        rows=plan_json.get('Plan Rows', 0),
                        width=plan_json.get('Plan Width', 0)
                    )
        
        except Exception as e:
            logger.warning("query_plan_extraction_failed", error=str(e))
            return None
    
    async def _generate_suggestions(
        self,
        stats: QueryStats,
        text_analysis: Dict[str, Any]
    ) -> List[OptimizationSuggestion]:
        """Generate optimization suggestions for a query"""
        suggestions = []
        
        try:
            # Check for slow queries
            if stats.is_slow and stats.execution_count >= self.config.alert_threshold_executions:
                suggestions.extend(await self._suggest_slow_query_optimizations(stats, text_analysis))
            
            # Check for missing indexes
            if text_analysis['query_type'] == QueryType.SELECT:
                suggestions.extend(await self._suggest_index_optimizations(stats, text_analysis))
            
            # Check for query rewrite opportunities
            suggestions.extend(await self._suggest_query_rewrites(stats, text_analysis))
            
            # Check for table-level optimizations
            suggestions.extend(await self._suggest_table_optimizations(stats, text_analysis))
            
            # Sort by severity and estimated improvement
            suggestions.sort(key=lambda s: (
                {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}[s.severity],
                s.estimated_improvement or 0
            ), reverse=True)
            
            # Limit suggestions
            suggestions = suggestions[:self.config.max_suggestions_per_query]
            
            # Update metrics
            for suggestion in suggestions:
                query_optimization_suggestions.labels(
                    suggestion_type=suggestion.suggestion_type,
                    severity=suggestion.severity
                ).inc()
        
        except Exception as e:
            logger.error("suggestion_generation_failed", error=str(e))
        
        return suggestions
    
    async def _suggest_slow_query_optimizations(
        self,
        stats: QueryStats,
        text_analysis: Dict[str, Any]
    ) -> List[OptimizationSuggestion]:
        """Suggest optimizations for slow queries"""
        suggestions = []
        
        # High execution time suggests need for indexes
        if stats.avg_time_ms > self.config.slow_query_threshold_ms:
            for table in stats.table_names:
                suggestions.append(OptimizationSuggestion(
                    suggestion_type=SuggestionType.ADD_INDEX,
                    severity=SuggestionSeverity.HIGH,
                    query_hash=stats.query_hash,
                    table_name=table,
                    description=f"Add index to improve query performance on table {table}",
                    estimated_improvement=stats.avg_time_ms * 0.7,
                    implementation_cost="medium"
                ))
        
        # High complexity suggests query rewrite
        if text_analysis['complexity_score'] > 50:
            suggestions.append(OptimizationSuggestion(
                suggestion_type=SuggestionType.REWRITE_QUERY,
                severity=SuggestionSeverity.MEDIUM,
                query_hash=stats.query_hash,
                table_name=stats.table_names[0] if stats.table_names else "unknown",
                description="Consider rewriting complex query for better performance",
                estimated_improvement=stats.avg_time_ms * 0.3,
                implementation_cost="high"
            ))
        
        return suggestions
    
    async def _suggest_index_optimizations(
        self,
        stats: QueryStats,
        text_analysis: Dict[str, Any]
    ) -> List[OptimizationSuggestion]:
        """Suggest index-based optimizations"""
        suggestions = []
        
        # Check for missing WHERE clause indexes
        if 'missing_where_clause' not in text_analysis['potential_issues']:
            # Analyze WHERE conditions for index opportunities
            where_columns = self._extract_where_columns(stats.query_text)
            
            for table, columns in where_columns.items():
                if len(columns) == 1:
                    # Single column index
                    suggestions.append(OptimizationSuggestion(
                        suggestion_type=SuggestionType.ADD_INDEX,
                        severity=SuggestionSeverity.MEDIUM,
                        query_hash=stats.query_hash,
                        table_name=table,
                        description=f"Add single-column index on {table}.{columns[0]}",
                        sql_statement=f"CREATE INDEX CONCURRENTLY idx_{table}_{columns[0]} ON {table} ({columns[0]})",
                        estimated_improvement=stats.avg_time_ms * 0.5,
                        implementation_cost="low"
                    ))
                elif len(columns) > 1:
                    # Composite index
                    columns_str = ', '.join(columns)
                    suggestions.append(OptimizationSuggestion(
                        suggestion_type=SuggestionType.ADD_INDEX,
                        severity=SuggestionSeverity.HIGH,
                        query_hash=stats.query_hash,
                        table_name=table,
                        description=f"Add composite index on {table}({columns_str})",
                        sql_statement=f"CREATE INDEX CONCURRENTLY idx_{table}_{'_'.join(columns)} ON {table} ({columns_str})",
                        estimated_improvement=stats.avg_time_ms * 0.8,
                        implementation_cost="medium"
                    ))
        
        return suggestions
    
    async def _suggest_query_rewrites(
        self,
        stats: QueryStats,
        text_analysis: Dict[str, Any]
    ) -> List[OptimizationSuggestion]:
        """Suggest query rewrite optimizations"""
        suggestions = []
        
        # SELECT * optimization
        if 'select_star' in text_analysis['potential_issues']:
            suggestions.append(OptimizationSuggestion(
                suggestion_type=SuggestionType.MODIFY_QUERY,
                severity=SuggestionSeverity.LOW,
                query_hash=stats.query_hash,
                table_name=stats.table_names[0] if stats.table_names else "unknown",
                description="Replace SELECT * with specific column names",
                estimated_improvement=stats.avg_time_ms * 0.2,
                implementation_cost="low"
            ))
        
        # OR conditions optimization
        if 'or_conditions' in text_analysis['potential_issues']:
            suggestions.append(OptimizationSuggestion(
                suggestion_type=SuggestionType.REWRITE_QUERY,
                severity=SuggestionSeverity.MEDIUM,
                query_hash=stats.query_hash,
                table_name=stats.table_names[0] if stats.table_names else "unknown",
                description="Consider rewriting OR conditions using UNION for better index usage",
                estimated_improvement=stats.avg_time_ms * 0.4,
                implementation_cost="medium"
            ))
        
        # Function in WHERE clause
        if 'function_in_where' in text_analysis['potential_issues']:
            suggestions.append(OptimizationSuggestion(
                suggestion_type=SuggestionType.MODIFY_QUERY,
                severity=SuggestionSeverity.HIGH,
                query_hash=stats.query_hash,
                table_name=stats.table_names[0] if stats.table_names else "unknown",
                description="Avoid functions in WHERE clause to enable index usage",
                estimated_improvement=stats.avg_time_ms * 0.6,
                implementation_cost="medium"
            ))
        
        return suggestions
    
    async def _suggest_table_optimizations(
        self,
        stats: QueryStats,
        text_analysis: Dict[str, Any]
    ) -> List[OptimizationSuggestion]:
        """Suggest table-level optimizations"""
        suggestions = []
        
        # Large table scan suggestions
        if stats.rows_examined > self.config.high_row_scan_threshold:
            for table in stats.table_names:
                suggestions.append(OptimizationSuggestion(
                    suggestion_type=SuggestionType.PARTITION_TABLE,
                    severity=SuggestionSeverity.MEDIUM,
                    query_hash=stats.query_hash,
                    table_name=table,
                    description=f"Consider partitioning large table {table}",
                    estimated_improvement=stats.avg_time_ms * 0.5,
                    implementation_cost="high"
                ))
        
        # Statistics update suggestion
        if stats.execution_count > 100 and stats.std_dev_ms > stats.avg_time_ms * 0.5:
            suggestions.append(OptimizationSuggestion(
                suggestion_type=SuggestionType.UPDATE_STATISTICS,
                severity=SuggestionSeverity.LOW,
                query_hash=stats.query_hash,
                table_name=stats.table_names[0] if stats.table_names else "unknown",
                description="Update table statistics for better query planning",
                sql_statement=f"ANALYZE {stats.table_names[0] if stats.table_names else 'table_name'}",
                estimated_improvement=stats.avg_time_ms * 0.1,
                implementation_cost="low"
            ))
        
        return suggestions
    
    def _extract_where_columns(self, query: str) -> Dict[str, List[str]]:
        """Extract columns used in WHERE clauses"""
        columns_by_table = {}
        
        # Simplified extraction - in production use proper SQL parser
        import re
        
        # Match patterns like "table.column = value" or "column = value"
        where_patterns = re.findall(
            r'WHERE\s+.*?(?:(\w+)\.)?(\w+)\s*[=<>!]',
            query,
            re.IGNORECASE | re.DOTALL
        )
        
        for table, column in where_patterns:
            table = table or 'unknown_table'
            if table not in columns_by_table:
                columns_by_table[table] = []
            if column not in columns_by_table[table]:
                columns_by_table[table].append(column)
        
        return columns_by_table
    
    async def _real_time_analysis_loop(self):
        """Real-time query analysis loop"""
        while True:
            try:
                await asyncio.sleep(1)  # Check every second
                
                # Analyze recent queries from pg_stat_statements
                if self.config.enable_pg_stat_statements:
                    await self._analyze_pg_stat_statements()
                
            except Exception as e:
                logger.error("real_time_analysis_loop_error", error=str(e))
    
    async def _analyze_pg_stat_statements(self):
        """Analyze queries from pg_stat_statements"""
        try:
            async with self.pool.acquire() as conn:
                # Get recent slow queries
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
                WHERE mean_exec_time > $1
                AND calls >= $2
                ORDER BY mean_exec_time DESC 
                LIMIT 20
                """
                
                rows = await conn.fetch(
                    query,
                    self.config.slow_query_threshold_ms,
                    self.config.alert_threshold_executions
                )
                
                for row in rows:
                    query_text = row['query']
                    execution_time = row['mean_exec_time']
                    
                    # Analyze the query
                    await self.analyze_query(
                        query_text,
                        execution_time,
                        row['shared_blks_read'],
                        row['rows']
                    )
        
        except Exception as e:
            logger.warning("pg_stat_statements_analysis_failed", error=str(e))
    
    async def _periodic_analysis_loop(self):
        """Periodic comprehensive analysis"""
        while True:
            try:
                await asyncio.sleep(self.config.analysis_interval_seconds)
                
                # Comprehensive analysis of all tracked queries
                await self._comprehensive_analysis()
                
                self.last_analysis_time = time.time()
                
            except Exception as e:
                logger.error("periodic_analysis_loop_error", error=str(e))
    
    async def _comprehensive_analysis(self):
        """Perform comprehensive analysis of all queries"""
        try:
            logger.info("starting_comprehensive_query_analysis",
                       tracked_queries=len(self.query_stats))
            
            # Analyze performance trends
            performance_trends = self._analyze_performance_trends()
            
            # Generate system-wide recommendations
            system_recommendations = await self._generate_system_recommendations()
            
            # Update index effectiveness metrics
            await self._update_index_effectiveness()
            
            logger.info("comprehensive_analysis_completed",
                       trends=len(performance_trends),
                       recommendations=len(system_recommendations))
        
        except Exception as e:
            logger.error("comprehensive_analysis_failed", error=str(e))
    
    def _analyze_performance_trends(self) -> Dict[str, Any]:
        """Analyze performance trends across all queries"""
        trends = {
            'degrading_queries': [],
            'improving_queries': [],
            'consistently_slow': [],
            'high_variance': []
        }
        
        for query_hash, stats in self.query_stats.items():
            if stats.execution_count < 10:
                continue
            
            # Check for performance degradation
            # This would require historical data in a real implementation
            
            # Check for consistently slow queries
            if stats.is_slow and stats.std_dev_ms < stats.avg_time_ms * 0.2:
                trends['consistently_slow'].append(query_hash)
            
            # Check for high variance queries
            if stats.std_dev_ms > stats.avg_time_ms * 0.5:
                trends['high_variance'].append(query_hash)
        
        return trends
    
    async def _generate_system_recommendations(self) -> List[OptimizationSuggestion]:
        """Generate system-wide optimization recommendations"""
        recommendations = []
        
        # Analyze overall query patterns
        total_queries = len(self.query_stats)
        slow_queries = len([s for s in self.query_stats.values() if s.is_slow])
        
        if slow_queries > total_queries * 0.1:  # More than 10% slow queries
            recommendations.append(OptimizationSuggestion(
                suggestion_type=SuggestionType.UPDATE_STATISTICS,
                severity=SuggestionSeverity.HIGH,
                query_hash="system",
                table_name="all",
                description="High percentage of slow queries detected - consider updating all table statistics",
                sql_statement="ANALYZE;",
                estimated_improvement=None,
                implementation_cost="low"
            ))
        
        return recommendations
    
    async def _update_index_effectiveness(self):
        """Update index effectiveness metrics"""
        try:
            async with self.pool.acquire() as conn:
                # Get index usage statistics
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
                    # Calculate effectiveness ratio
                    scans = row['idx_scan']
                    reads = row['idx_tup_read'] or 1
                    effectiveness = min(scans / reads, 1.0) if reads > 0 else 0
                    
                    index_effectiveness.labels(
                        table=row['tablename'],
                        index_name=row['indexname']
                    ).set(effectiveness)
        
        except Exception as e:
            logger.error("index_effectiveness_update_failed", error=str(e))
    
    async def _cleanup_loop(self):
        """Clean up old statistics and cached data"""
        while True:
            try:
                await asyncio.sleep(3600)  # Clean up every hour
                
                cutoff_time = datetime.now(timezone.utc) - timedelta(
                    hours=self.config.stats_retention_hours
                )
                
                # Clean up old query stats
                old_queries = [
                    query_hash for query_hash, stats in self.query_stats.items()
                    if stats.last_executed and stats.last_executed < cutoff_time
                ]
                
                for query_hash in old_queries:
                    del self.query_stats[query_hash]
                    if query_hash in self.plan_cache:
                        del self.plan_cache[query_hash]
                    if query_hash in self.suggestions:
                        del self.suggestions[query_hash]
                
                # Limit plan cache size
                if len(self.plan_cache) > self.config.plan_cache_size:
                    # Remove oldest entries
                    sorted_plans = sorted(
                        self.plan_cache.items(),
                        key=lambda x: self.query_stats.get(x[0], QueryStats("", "", QueryType.UNKNOWN, [])).last_executed or datetime.min.replace(tzinfo=timezone.utc)
                    )
                    
                    for query_hash, _ in sorted_plans[:-self.config.plan_cache_size]:
                        del self.plan_cache[query_hash]
                
                if old_queries:
                    logger.info("query_stats_cleanup_completed", 
                               removed=len(old_queries))
            
            except Exception as e:
                logger.error("cleanup_loop_error", error=str(e))
    
    async def get_optimization_report(self) -> Dict[str, Any]:
        """Generate comprehensive optimization report"""
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_queries_tracked": len(self.query_stats),
                "slow_queries": len([s for s in self.query_stats.values() if s.is_slow]),
                "total_suggestions": sum(len(suggestions) for suggestions in self.suggestions.values()),
                "plan_cache_size": len(self.plan_cache),
                "analysis_count": self.analysis_count
            },
            "top_slow_queries": [],
            "optimization_suggestions": [],
            "performance_trends": self._analyze_performance_trends(),
            "system_health": {
                "avg_query_performance": 0.0,
                "query_consistency": 0.0
            }
        }
        
        # Get top slow queries
        slow_queries = sorted(
            [s for s in self.query_stats.values() if s.is_slow],
            key=lambda x: x.avg_time_ms,
            reverse=True
        )[:10]
        
        report["top_slow_queries"] = [
            {
                "query_hash": q.query_hash,
                "avg_time_ms": q.avg_time_ms,
                "execution_count": q.execution_count,
                "performance_score": q.performance_score,
                "table_names": q.table_names
            }
            for q in slow_queries
        ]
        
        # Get all suggestions
        all_suggestions = []
        for suggestions in self.suggestions.values():
            all_suggestions.extend([s.to_dict() for s in suggestions])
        
        # Sort by severity and estimated improvement
        all_suggestions.sort(
            key=lambda x: (
                {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}[x['severity']],
                x['estimated_improvement'] or 0
            ),
            reverse=True
        )
        
        report["optimization_suggestions"] = all_suggestions[:20]  # Top 20
        
        # Calculate system health metrics
        if self.query_stats:
            scores = [s.performance_score for s in self.query_stats.values()]
            report["system_health"]["avg_query_performance"] = statistics.mean(scores)
            
            if len(scores) > 1:
                report["system_health"]["query_consistency"] = 100 - (statistics.stdev(scores) / statistics.mean(scores) * 100)
        
        return report
    
    async def stop(self):
        """Stop the query optimization engine"""
        logger.info("stopping_query_optimization_engine")
        
        for task in self.monitoring_tasks:
            task.cancel()
        
        if self.monitoring_tasks:
            await asyncio.gather(*self.monitoring_tasks, return_exceptions=True)
        
        self.monitoring_tasks.clear()
        logger.info("query_optimization_engine_stopped")