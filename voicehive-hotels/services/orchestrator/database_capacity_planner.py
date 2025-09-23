"""
Database Capacity Planning & Performance Dashboards for VoiceHive Hotels
Advanced database metrics collection and capacity planning system
"""

import asyncio
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import statistics
import numpy as np
from pathlib import Path

import asyncpg
from pydantic import BaseModel, Field

from prometheus_client import Gauge, Counter, Histogram, Summary, CollectorRegistry, generate_latest
from logging_adapter import get_safe_logger
from audit_logging import AuditLogger

logger = get_safe_logger("orchestrator.db_capacity")
audit_logger = AuditLogger("database_capacity")

# Prometheus metrics for capacity planning
db_capacity_usage = Gauge(
    'voicehive_db_capacity_usage_percent',
    'Database capacity usage percentage',
    ['database', 'metric_type']
)

db_growth_rate = Gauge(
    'voicehive_db_growth_rate_mb_per_day',
    'Database growth rate in MB per day',
    ['database', 'table']
)

db_performance_score = Gauge(
    'voicehive_db_performance_score',
    'Database performance score (0-100)',
    ['database', 'metric_category']
)

db_capacity_forecast = Gauge(
    'voicehive_db_capacity_forecast_days',
    'Days until capacity limit reached',
    ['database', 'forecast_type']
)

db_resource_utilization = Gauge(
    'voicehive_db_resource_utilization_percent',
    'Database resource utilization percentage',
    ['resource_type', 'database']
)

db_maintenance_recommendations = Counter(
    'voicehive_db_maintenance_recommendations_total',
    'Database maintenance recommendations',
    ['recommendation_type', 'priority']
)


class MetricType(str, Enum):
    """Database metric types"""
    STORAGE = "storage"
    CONNECTIONS = "connections"
    MEMORY = "memory"
    CPU = "cpu"
    IO = "io"
    QUERIES = "queries"


class ForecastType(str, Enum):
    """Capacity forecast types"""
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    SEASONAL = "seasonal"
    MACHINE_LEARNING = "ml"


class RecommendationType(str, Enum):
    """Maintenance recommendation types"""
    INDEX_OPTIMIZATION = "index_optimization"
    VACUUM_ANALYZE = "vacuum_analyze"
    PARTITION_MANAGEMENT = "partition_management"
    QUERY_OPTIMIZATION = "query_optimization"
    CAPACITY_EXPANSION = "capacity_expansion"
    ARCHIVAL = "archival"


@dataclass
class CapacityMetric:
    """Database capacity metric"""
    metric_type: MetricType
    current_value: float
    max_value: float
    unit: str
    timestamp: datetime
    
    @property
    def usage_percent(self) -> float:
        if self.max_value > 0:
            return (self.current_value / self.max_value) * 100
        return 0.0
    
    @property
    def is_critical(self) -> bool:
        return self.usage_percent > 90
    
    @property
    def is_warning(self) -> bool:
        return self.usage_percent > 75


@dataclass
class GrowthTrend:
    """Database growth trend analysis"""
    table_name: str
    current_size_mb: float
    growth_rate_mb_per_day: float
    growth_rate_percent_per_day: float
    forecast_30_days_mb: float
    forecast_90_days_mb: float
    confidence_score: float
    data_points: int
    
    @property
    def is_high_growth(self) -> bool:
        return self.growth_rate_percent_per_day > 5.0  # 5% per day


@dataclass
class PerformanceMetric:
    """Database performance metric"""
    metric_name: str
    current_value: float
    baseline_value: float
    threshold_warning: float
    threshold_critical: float
    unit: str
    timestamp: datetime
    
    @property
    def performance_score(self) -> float:
        """Calculate performance score (0-100)"""
        if self.current_value <= self.baseline_value:
            return 100.0
        elif self.current_value >= self.threshold_critical:
            return 0.0
        else:
            # Linear interpolation between baseline and critical
            range_total = self.threshold_critical - self.baseline_value
            range_current = self.current_value - self.baseline_value
            return max(0.0, 100.0 - (range_current / range_total * 100.0))
    
    @property
    def status(self) -> str:
        if self.current_value >= self.threshold_critical:
            return "critical"
        elif self.current_value >= self.threshold_warning:
            return "warning"
        else:
            return "normal"


@dataclass
class MaintenanceRecommendation:
    """Database maintenance recommendation"""
    recommendation_type: RecommendationType
    priority: int  # 1=high, 2=medium, 3=low
    description: str
    estimated_impact: str
    estimated_effort: str
    sql_commands: List[str] = field(default_factory=list)
    expected_benefit: Optional[str] = None
    risk_level: str = "low"  # low, medium, high
    
    @property
    def priority_text(self) -> str:
        return {1: "high", 2: "medium", 3: "low"}.get(self.priority, "unknown")


class DatabaseMetricsCollector:
    """Comprehensive database metrics collection"""
    
    def __init__(self, connection_pool):
        self.pool = connection_pool
        self.metrics_history: Dict[str, List[Dict]] = {}
        
    async def collect_all_metrics(self) -> Dict[str, Any]:
        """Collect comprehensive database metrics"""
        metrics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "capacity_metrics": {},
            "performance_metrics": {},
            "resource_utilization": {},
            "table_statistics": {},
            "index_statistics": {},
            "query_statistics": {}
        }
        
        try:
            async with self.pool.acquire() as conn:
                # Collect capacity metrics
                metrics["capacity_metrics"] = await self._collect_capacity_metrics(conn)
                
                # Collect performance metrics
                metrics["performance_metrics"] = await self._collect_performance_metrics(conn)
                
                # Collect resource utilization
                metrics["resource_utilization"] = await self._collect_resource_utilization(conn)
                
                # Collect table statistics
                metrics["table_statistics"] = await self._collect_table_statistics(conn)
                
                # Collect index statistics
                metrics["index_statistics"] = await self._collect_index_statistics(conn)
                
                # Collect query statistics
                metrics["query_statistics"] = await self._collect_query_statistics(conn)
            
            # Store metrics history
            self._store_metrics_history(metrics)
            
            # Update Prometheus metrics
            await self._update_prometheus_metrics(metrics)
            
        except Exception as e:
            logger.error("failed_to_collect_metrics", error=str(e))
            metrics["error"] = str(e)
        
        return metrics
    
    async def _collect_capacity_metrics(self, conn) -> Dict[str, CapacityMetric]:
        """Collect database capacity metrics"""
        capacity_metrics = {}
        
        try:
            # Database size and limits
            db_size_query = """
            SELECT 
                pg_database_size(current_database()) as current_size,
                setting::bigint * 1024 as max_size
            FROM pg_settings 
            WHERE name = 'shared_buffers'
            """
            
            db_size_result = await conn.fetchrow(db_size_query)
            if db_size_result:
                capacity_metrics["storage"] = CapacityMetric(
                    metric_type=MetricType.STORAGE,
                    current_value=db_size_result["current_size"] / (1024 * 1024),  # MB
                    max_value=db_size_result["max_size"] / (1024 * 1024),  # MB
                    unit="MB",
                    timestamp=datetime.now(timezone.utc)
                )
            
            # Connection usage
            conn_query = """
            SELECT 
                count(*) as current_connections,
                setting::int as max_connections
            FROM pg_stat_activity, pg_settings
            WHERE pg_settings.name = 'max_connections'
            GROUP BY setting
            """
            
            conn_result = await conn.fetchrow(conn_query)
            if conn_result:
                capacity_metrics["connections"] = CapacityMetric(
                    metric_type=MetricType.CONNECTIONS,
                    current_value=conn_result["current_connections"],
                    max_value=conn_result["max_connections"],
                    unit="connections",
                    timestamp=datetime.now(timezone.utc)
                )
            
            # WAL usage
            wal_query = """
            SELECT 
                pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0') / 1024 / 1024 as wal_size_mb
            """
            
            wal_result = await conn.fetchval(wal_query)
            if wal_result:
                capacity_metrics["wal"] = CapacityMetric(
                    metric_type=MetricType.STORAGE,
                    current_value=wal_result,
                    max_value=1024,  # Assume 1GB limit for WAL
                    unit="MB",
                    timestamp=datetime.now(timezone.utc)
                )
            
            # Tablespace usage
            tablespace_query = """
            SELECT 
                spcname,
                pg_size_pretty(pg_tablespace_size(spcname)) as size
            FROM pg_tablespace
            """
            
            tablespace_results = await conn.fetch(tablespace_query)
            for ts in tablespace_results:
                # This would need more sophisticated parsing of pg_size_pretty output
                pass
            
        except Exception as e:
            logger.error("failed_to_collect_capacity_metrics", error=str(e))
        
        return capacity_metrics
    
    async def _collect_performance_metrics(self, conn) -> Dict[str, PerformanceMetric]:
        """Collect database performance metrics"""
        performance_metrics = {}
        
        try:
            # Query performance
            query_perf_query = """
            SELECT 
                avg(mean_exec_time) as avg_query_time,
                max(mean_exec_time) as max_query_time,
                count(*) as total_queries
            FROM pg_stat_statements
            WHERE calls > 10
            """
            
            try:
                query_perf = await conn.fetchrow(query_perf_query)
                if query_perf and query_perf["avg_query_time"]:
                    performance_metrics["avg_query_time"] = PerformanceMetric(
                        metric_name="avg_query_time",
                        current_value=query_perf["avg_query_time"],
                        baseline_value=100.0,  # 100ms baseline
                        threshold_warning=500.0,  # 500ms warning
                        threshold_critical=1000.0,  # 1s critical
                        unit="ms",
                        timestamp=datetime.now(timezone.utc)
                    )
            except Exception:
                # pg_stat_statements might not be available
                pass
            
            # Cache hit ratio
            cache_hit_query = """
            SELECT 
                sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) * 100 as cache_hit_ratio
            FROM pg_statio_user_tables
            WHERE heap_blks_hit + heap_blks_read > 0
            """
            
            cache_hit = await conn.fetchval(cache_hit_query)
            if cache_hit:
                performance_metrics["cache_hit_ratio"] = PerformanceMetric(
                    metric_name="cache_hit_ratio",
                    current_value=cache_hit,
                    baseline_value=95.0,  # 95% baseline
                    threshold_warning=90.0,  # 90% warning
                    threshold_critical=85.0,  # 85% critical
                    unit="percent",
                    timestamp=datetime.now(timezone.utc)
                )
            
            # Index usage ratio
            index_usage_query = """
            SELECT 
                sum(idx_scan) / (sum(idx_scan) + sum(seq_scan)) * 100 as index_usage_ratio
            FROM pg_stat_user_tables
            WHERE idx_scan + seq_scan > 0
            """
            
            index_usage = await conn.fetchval(index_usage_query)
            if index_usage:
                performance_metrics["index_usage_ratio"] = PerformanceMetric(
                    metric_name="index_usage_ratio",
                    current_value=index_usage,
                    baseline_value=90.0,  # 90% baseline
                    threshold_warning=70.0,  # 70% warning
                    threshold_critical=50.0,  # 50% critical
                    unit="percent",
                    timestamp=datetime.now(timezone.utc)
                )
            
            # Lock contention
            lock_query = """
            SELECT count(*) as waiting_locks
            FROM pg_locks
            WHERE NOT granted
            """
            
            waiting_locks = await conn.fetchval(lock_query)
            if waiting_locks is not None:
                performance_metrics["lock_contention"] = PerformanceMetric(
                    metric_name="lock_contention",
                    current_value=waiting_locks,
                    baseline_value=0.0,
                    threshold_warning=5.0,
                    threshold_critical=10.0,
                    unit="locks",
                    timestamp=datetime.now(timezone.utc)
                )
            
        except Exception as e:
            logger.error("failed_to_collect_performance_metrics", error=str(e))
        
        return performance_metrics
    
    async def _collect_resource_utilization(self, conn) -> Dict[str, float]:
        """Collect database resource utilization"""
        resource_metrics = {}
        
        try:
            # CPU usage (approximate from pg_stat_activity)
            cpu_query = """
            SELECT 
                count(*) filter (where state = 'active') as active_queries,
                count(*) as total_connections
            FROM pg_stat_activity
            WHERE datname = current_database()
            """
            
            cpu_result = await conn.fetchrow(cpu_query)
            if cpu_result and cpu_result["total_connections"] > 0:
                cpu_utilization = (cpu_result["active_queries"] / cpu_result["total_connections"]) * 100
                resource_metrics["cpu_utilization"] = min(cpu_utilization, 100.0)
            
            # Memory usage (shared buffers hit ratio)
            memory_query = """
            SELECT 
                (sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read) + 1)) * 100 as memory_efficiency
            FROM pg_statio_user_tables
            """
            
            memory_efficiency = await conn.fetchval(memory_query)
            if memory_efficiency:
                resource_metrics["memory_efficiency"] = memory_efficiency
            
            # I/O utilization (blocks read vs hit)
            io_query = """
            SELECT 
                sum(heap_blks_read) as blocks_read,
                sum(heap_blks_hit) as blocks_hit
            FROM pg_statio_user_tables
            """
            
            io_result = await conn.fetchrow(io_query)
            if io_result and (io_result["blocks_read"] + io_result["blocks_hit"]) > 0:
                total_blocks = io_result["blocks_read"] + io_result["blocks_hit"]
                io_utilization = (io_result["blocks_read"] / total_blocks) * 100
                resource_metrics["io_utilization"] = io_utilization
            
        except Exception as e:
            logger.error("failed_to_collect_resource_utilization", error=str(e))
        
        return resource_metrics
    
    async def _collect_table_statistics(self, conn) -> Dict[str, Dict[str, Any]]:
        """Collect detailed table statistics"""
        table_stats = {}
        
        try:
            table_query = """
            SELECT 
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
                pg_total_relation_size(schemaname||'.'||tablename) as size_bytes,
                n_tup_ins,
                n_tup_upd,
                n_tup_del,
                n_live_tup,
                n_dead_tup,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze,
                vacuum_count,
                autovacuum_count,
                analyze_count,
                autoanalyze_count
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            """
            
            tables = await conn.fetch(table_query)
            
            for table in tables:
                table_name = table["tablename"]
                table_stats[table_name] = {
                    "schema": table["schemaname"],
                    "size_pretty": table["size"],
                    "size_bytes": table["size_bytes"],
                    "live_tuples": table["n_live_tup"],
                    "dead_tuples": table["n_dead_tup"],
                    "inserts": table["n_tup_ins"],
                    "updates": table["n_tup_upd"],
                    "deletes": table["n_tup_del"],
                    "last_vacuum": table["last_vacuum"].isoformat() if table["last_vacuum"] else None,
                    "last_analyze": table["last_analyze"].isoformat() if table["last_analyze"] else None,
                    "vacuum_count": table["vacuum_count"],
                    "analyze_count": table["analyze_count"],
                    "dead_tuple_ratio": (table["n_dead_tup"] / max(table["n_live_tup"], 1)) * 100
                }
            
        except Exception as e:
            logger.error("failed_to_collect_table_statistics", error=str(e))
        
        return table_stats
    
    async def _collect_index_statistics(self, conn) -> Dict[str, Dict[str, Any]]:
        """Collect index usage statistics"""
        index_stats = {}
        
        try:
            index_query = """
            SELECT 
                schemaname,
                tablename,
                indexname,
                idx_scan,
                idx_tup_read,
                idx_tup_fetch,
                pg_size_pretty(pg_relation_size(indexrelid)) as size,
                pg_relation_size(indexrelid) as size_bytes
            FROM pg_stat_user_indexes
            ORDER BY idx_scan DESC
            """
            
            indexes = await conn.fetch(index_query)
            
            for index in indexes:
                index_name = index["indexname"]
                index_stats[index_name] = {
                    "schema": index["schemaname"],
                    "table": index["tablename"],
                    "scans": index["idx_scan"],
                    "tuples_read": index["idx_tup_read"],
                    "tuples_fetched": index["idx_tup_fetch"],
                    "size_pretty": index["size"],
                    "size_bytes": index["size_bytes"],
                    "usage_ratio": (index["idx_scan"] / max(index["idx_tup_read"], 1)) * 100 if index["idx_tup_read"] else 0
                }
            
        except Exception as e:
            logger.error("failed_to_collect_index_statistics", error=str(e))
        
        return index_stats
    
    async def _collect_query_statistics(self, conn) -> Dict[str, Any]:
        """Collect query performance statistics"""
        query_stats = {}
        
        try:
            # Try to get pg_stat_statements data
            query_query = """
            SELECT 
                count(*) as total_queries,
                avg(mean_exec_time) as avg_execution_time,
                max(mean_exec_time) as max_execution_time,
                sum(calls) as total_calls,
                sum(total_exec_time) as total_execution_time
            FROM pg_stat_statements
            """
            
            try:
                query_result = await conn.fetchrow(query_query)
                if query_result:
                    query_stats = {
                        "total_unique_queries": query_result["total_queries"],
                        "avg_execution_time_ms": query_result["avg_execution_time"],
                        "max_execution_time_ms": query_result["max_execution_time"],
                        "total_calls": query_result["total_calls"],
                        "total_execution_time_ms": query_result["total_execution_time"]
                    }
            except Exception:
                # pg_stat_statements not available
                query_stats["error"] = "pg_stat_statements extension not available"
            
            # Get slow queries if available
            slow_queries_query = """
            SELECT 
                query,
                calls,
                mean_exec_time,
                total_exec_time
            FROM pg_stat_statements
            WHERE mean_exec_time > 1000  -- Queries slower than 1 second
            ORDER BY mean_exec_time DESC
            LIMIT 10
            """
            
            try:
                slow_queries = await conn.fetch(slow_queries_query)
                query_stats["slow_queries"] = [
                    {
                        "query": row["query"][:200] + "..." if len(row["query"]) > 200 else row["query"],
                        "calls": row["calls"],
                        "avg_time_ms": row["mean_exec_time"],
                        "total_time_ms": row["total_exec_time"]
                    }
                    for row in slow_queries
                ]
            except Exception:
                pass
            
        except Exception as e:
            logger.error("failed_to_collect_query_statistics", error=str(e))
            query_stats["error"] = str(e)
        
        return query_stats
    
    def _store_metrics_history(self, metrics: Dict[str, Any]):
        """Store metrics in history for trend analysis"""
        timestamp = metrics["timestamp"]
        
        # Store key metrics for trend analysis
        for metric_type, metric_data in metrics.items():
            if metric_type not in self.metrics_history:
                self.metrics_history[metric_type] = []
            
            # Keep only last 30 days of data
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            self.metrics_history[metric_type] = [
                m for m in self.metrics_history[metric_type]
                if datetime.fromisoformat(m["timestamp"]) > cutoff_date
            ]
            
            # Add current metrics
            self.metrics_history[metric_type].append({
                "timestamp": timestamp,
                "data": metric_data
            })
    
    async def _update_prometheus_metrics(self, metrics: Dict[str, Any]):
        """Update Prometheus metrics"""
        try:
            database_name = "voicehive"  # Would be configurable
            
            # Update capacity metrics
            for metric_name, capacity_metric in metrics.get("capacity_metrics", {}).items():
                if isinstance(capacity_metric, CapacityMetric):
                    db_capacity_usage.labels(
                        database=database_name,
                        metric_type=metric_name
                    ).set(capacity_metric.usage_percent)
            
            # Update performance metrics
            for metric_name, perf_metric in metrics.get("performance_metrics", {}).items():
                if isinstance(perf_metric, PerformanceMetric):
                    db_performance_score.labels(
                        database=database_name,
                        metric_category=metric_name
                    ).set(perf_metric.performance_score)
            
            # Update resource utilization
            for resource_type, utilization in metrics.get("resource_utilization", {}).items():
                db_resource_utilization.labels(
                    resource_type=resource_type,
                    database=database_name
                ).set(utilization)
            
        except Exception as e:
            logger.error("failed_to_update_prometheus_metrics", error=str(e))


class CapacityPlanner:
    """Database capacity planning and forecasting"""
    
    def __init__(self, metrics_collector: DatabaseMetricsCollector):
        self.metrics_collector = metrics_collector
        
    async def analyze_growth_trends(self) -> Dict[str, GrowthTrend]:
        """Analyze database growth trends"""
        growth_trends = {}
        
        try:
            # Get historical table size data
            table_history = self.metrics_collector.metrics_history.get("table_statistics", [])
            
            if len(table_history) < 7:  # Need at least a week of data
                logger.warning("insufficient_data_for_growth_analysis", 
                             data_points=len(table_history))
                return growth_trends
            
            # Analyze each table
            table_names = set()
            for history_point in table_history:
                if "data" in history_point:
                    table_names.update(history_point["data"].keys())
            
            for table_name in table_names:
                trend = await self._calculate_table_growth_trend(table_name, table_history)
                if trend:
                    growth_trends[table_name] = trend
            
        except Exception as e:
            logger.error("failed_to_analyze_growth_trends", error=str(e))
        
        return growth_trends
    
    async def _calculate_table_growth_trend(self, table_name: str, 
                                          history: List[Dict]) -> Optional[GrowthTrend]:
        """Calculate growth trend for a specific table"""
        try:
            # Extract size data points
            data_points = []
            
            for history_point in history:
                if "data" in history_point and table_name in history_point["data"]:
                    timestamp = datetime.fromisoformat(history_point["timestamp"])
                    size_bytes = history_point["data"][table_name].get("size_bytes", 0)
                    
                    if size_bytes > 0:
                        data_points.append({
                            "timestamp": timestamp,
                            "size_mb": size_bytes / (1024 * 1024)
                        })
            
            if len(data_points) < 3:
                return None
            
            # Sort by timestamp
            data_points.sort(key=lambda x: x["timestamp"])
            
            # Calculate growth rate using linear regression
            timestamps = [(dp["timestamp"] - data_points[0]["timestamp"]).days for dp in data_points]
            sizes = [dp["size_mb"] for dp in data_points]
            
            if len(timestamps) < 2:
                return None
            
            # Simple linear regression
            n = len(timestamps)
            sum_x = sum(timestamps)
            sum_y = sum(sizes)
            sum_xy = sum(x * y for x, y in zip(timestamps, sizes))
            sum_x2 = sum(x * x for x in timestamps)
            
            if n * sum_x2 - sum_x * sum_x == 0:
                return None
            
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
            
            # Growth rate in MB per day
            growth_rate_mb_per_day = slope
            
            # Current size
            current_size_mb = sizes[-1]
            
            # Growth rate percentage
            growth_rate_percent_per_day = (growth_rate_mb_per_day / max(current_size_mb, 1)) * 100
            
            # Forecasts
            forecast_30_days = current_size_mb + (growth_rate_mb_per_day * 30)
            forecast_90_days = current_size_mb + (growth_rate_mb_per_day * 90)
            
            # Confidence score based on R-squared
            mean_size = statistics.mean(sizes)
            ss_tot = sum((y - mean_size) ** 2 for y in sizes)
            ss_res = sum((sizes[i] - (slope * timestamps[i] + (sum_y - slope * sum_x) / n)) ** 2 
                        for i in range(n))
            
            r_squared = 1 - (ss_res / max(ss_tot, 1))
            confidence_score = max(0, min(100, r_squared * 100))
            
            return GrowthTrend(
                table_name=table_name,
                current_size_mb=current_size_mb,
                growth_rate_mb_per_day=growth_rate_mb_per_day,
                growth_rate_percent_per_day=growth_rate_percent_per_day,
                forecast_30_days_mb=forecast_30_days,
                forecast_90_days_mb=forecast_90_days,
                confidence_score=confidence_score,
                data_points=len(data_points)
            )
            
        except Exception as e:
            logger.error("failed_to_calculate_growth_trend", 
                        table=table_name, error=str(e))
            return None
    
    async def generate_capacity_forecast(self, forecast_type: ForecastType = ForecastType.LINEAR) -> Dict[str, Any]:
        """Generate capacity forecast"""
        forecast = {
            "forecast_type": forecast_type.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database_forecasts": {},
            "table_forecasts": {},
            "recommendations": []
        }
        
        try:
            # Analyze growth trends
            growth_trends = await self.analyze_growth_trends()
            
            # Generate forecasts for each table
            for table_name, trend in growth_trends.items():
                table_forecast = await self._generate_table_forecast(trend, forecast_type)
                forecast["table_forecasts"][table_name] = table_forecast
                
                # Update Prometheus metrics
                if table_forecast.get("days_to_capacity_limit"):
                    db_capacity_forecast.labels(
                        database="voicehive",
                        forecast_type=forecast_type.value
                    ).set(table_forecast["days_to_capacity_limit"])
                
                db_growth_rate.labels(
                    database="voicehive",
                    table=table_name
                ).set(trend.growth_rate_mb_per_day)
            
            # Generate overall database forecast
            forecast["database_forecasts"] = await self._generate_database_forecast(growth_trends)
            
            # Generate capacity recommendations
            forecast["recommendations"] = await self._generate_capacity_recommendations(growth_trends)
            
        except Exception as e:
            logger.error("failed_to_generate_capacity_forecast", error=str(e))
            forecast["error"] = str(e)
        
        return forecast
    
    async def _generate_table_forecast(self, trend: GrowthTrend, 
                                     forecast_type: ForecastType) -> Dict[str, Any]:
        """Generate forecast for a specific table"""
        forecast = {
            "current_size_mb": trend.current_size_mb,
            "growth_rate_mb_per_day": trend.growth_rate_mb_per_day,
            "growth_rate_percent_per_day": trend.growth_rate_percent_per_day,
            "confidence_score": trend.confidence_score,
            "forecasts": {}
        }
        
        # Generate forecasts for different time periods
        time_periods = [7, 30, 90, 180, 365]
        
        for days in time_periods:
            if forecast_type == ForecastType.LINEAR:
                forecasted_size = trend.current_size_mb + (trend.growth_rate_mb_per_day * days)
            elif forecast_type == ForecastType.EXPONENTIAL:
                # Simple exponential growth
                daily_growth_factor = 1 + (trend.growth_rate_percent_per_day / 100)
                forecasted_size = trend.current_size_mb * (daily_growth_factor ** days)
            else:
                # Default to linear
                forecasted_size = trend.current_size_mb + (trend.growth_rate_mb_per_day * days)
            
            forecast["forecasts"][f"{days}_days"] = {
                "size_mb": forecasted_size,
                "size_gb": forecasted_size / 1024,
                "growth_mb": forecasted_size - trend.current_size_mb
            }
        
        # Calculate days to capacity limits (assuming various limits)
        capacity_limits_gb = [10, 50, 100, 500, 1000]  # Different capacity thresholds
        
        for limit_gb in capacity_limits_gb:
            limit_mb = limit_gb * 1024
            
            if trend.growth_rate_mb_per_day > 0:
                days_to_limit = (limit_mb - trend.current_size_mb) / trend.growth_rate_mb_per_day
                
                if days_to_limit > 0 and days_to_limit < 1000:  # Reasonable timeframe
                    forecast[f"days_to_{limit_gb}gb"] = int(days_to_limit)
        
        return forecast
    
    async def _generate_database_forecast(self, growth_trends: Dict[str, GrowthTrend]) -> Dict[str, Any]:
        """Generate overall database forecast"""
        database_forecast = {
            "total_current_size_mb": 0,
            "total_growth_rate_mb_per_day": 0,
            "high_growth_tables": [],
            "forecasts": {}
        }
        
        # Aggregate statistics
        for table_name, trend in growth_trends.items():
            database_forecast["total_current_size_mb"] += trend.current_size_mb
            database_forecast["total_growth_rate_mb_per_day"] += trend.growth_rate_mb_per_day
            
            if trend.is_high_growth:
                database_forecast["high_growth_tables"].append({
                    "table": table_name,
                    "growth_rate_percent": trend.growth_rate_percent_per_day,
                    "current_size_mb": trend.current_size_mb
                })
        
        # Generate database-level forecasts
        time_periods = [30, 90, 180, 365]
        
        for days in time_periods:
            forecasted_size = (database_forecast["total_current_size_mb"] + 
                             (database_forecast["total_growth_rate_mb_per_day"] * days))
            
            database_forecast["forecasts"][f"{days}_days"] = {
                "size_mb": forecasted_size,
                "size_gb": forecasted_size / 1024,
                "growth_mb": forecasted_size - database_forecast["total_current_size_mb"]
            }
        
        return database_forecast
    
    async def _generate_capacity_recommendations(self, growth_trends: Dict[str, GrowthTrend]) -> List[MaintenanceRecommendation]:
        """Generate capacity planning recommendations"""
        recommendations = []
        
        try:
            # Check for high-growth tables
            for table_name, trend in growth_trends.items():
                if trend.is_high_growth:
                    recommendations.append(MaintenanceRecommendation(
                        recommendation_type=RecommendationType.CAPACITY_EXPANSION,
                        priority=1,
                        description=f"Table {table_name} is growing at {trend.growth_rate_percent_per_day:.1f}% per day",
                        estimated_impact="Prevent storage capacity issues",
                        estimated_effort="Medium - requires capacity planning",
                        expected_benefit="Avoid service disruption from storage limits",
                        risk_level="medium"
                    ))
                
                # Check if table needs archival
                if trend.current_size_mb > 10000:  # 10GB threshold
                    recommendations.append(MaintenanceRecommendation(
                        recommendation_type=RecommendationType.ARCHIVAL,
                        priority=2,
                        description=f"Consider archiving old data from large table {table_name} ({trend.current_size_mb:.0f}MB)",
                        estimated_impact="Reduce storage usage and improve performance",
                        estimated_effort="High - requires data archival strategy",
                        expected_benefit="Reduced storage costs and improved query performance",
                        risk_level="low"
                    ))
            
            # Check overall database growth
            total_growth_rate = sum(trend.growth_rate_mb_per_day for trend in growth_trends.values())
            
            if total_growth_rate > 1000:  # 1GB per day
                recommendations.append(MaintenanceRecommendation(
                    recommendation_type=RecommendationType.CAPACITY_EXPANSION,
                    priority=1,
                    description=f"Database growing at {total_growth_rate:.0f}MB per day - plan capacity expansion",
                    estimated_impact="Ensure adequate storage capacity",
                    estimated_effort="High - requires infrastructure planning",
                    expected_benefit="Prevent service outages from storage exhaustion",
                    risk_level="high"
                ))
            
        except Exception as e:
            logger.error("failed_to_generate_capacity_recommendations", error=str(e))
        
        return recommendations


class DatabaseCapacityManager:
    """Main database capacity planning and monitoring coordinator"""
    
    def __init__(self, connection_pool):
        self.pool = connection_pool
        self.metrics_collector = DatabaseMetricsCollector(connection_pool)
        self.capacity_planner = CapacityPlanner(self.metrics_collector)
        self.monitoring_task: Optional[asyncio.Task] = None
        
    async def initialize(self):
        """Initialize capacity manager"""
        logger.info("initializing_database_capacity_manager")
        
        # Start continuous monitoring
        self.monitoring_task = asyncio.create_task(self._continuous_monitoring())
        
        logger.info("database_capacity_manager_initialized")
    
    async def _continuous_monitoring(self):
        """Continuous capacity monitoring"""
        while True:
            try:
                # Collect metrics every 5 minutes
                await asyncio.sleep(300)
                
                logger.debug("collecting_capacity_metrics")
                
                # Collect all metrics
                metrics = await self.metrics_collector.collect_all_metrics()
                
                # Generate capacity forecast daily
                current_hour = datetime.now().hour
                if current_hour == 2:  # 2 AM daily forecast
                    logger.info("generating_daily_capacity_forecast")
                    
                    forecast = await self.capacity_planner.generate_capacity_forecast()
                    
                    # Log high-priority recommendations
                    for rec in forecast.get("recommendations", []):
                        if rec.priority == 1:
                            logger.warning("high_priority_capacity_recommendation",
                                         type=rec.recommendation_type.value,
                                         description=rec.description)
                
            except Exception as e:
                logger.error("capacity_monitoring_error", error=str(e))
                await asyncio.sleep(60)  # Shorter sleep on error
    
    async def get_capacity_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive capacity dashboard data"""
        dashboard_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "current_metrics": {},
            "growth_analysis": {},
            "capacity_forecast": {},
            "recommendations": [],
            "alerts": []
        }
        
        try:
            # Get current metrics
            dashboard_data["current_metrics"] = await self.metrics_collector.collect_all_metrics()
            
            # Get growth analysis
            growth_trends = await self.capacity_planner.analyze_growth_trends()
            dashboard_data["growth_analysis"] = {
                table_name: {
                    "current_size_mb": trend.current_size_mb,
                    "growth_rate_mb_per_day": trend.growth_rate_mb_per_day,
                    "growth_rate_percent_per_day": trend.growth_rate_percent_per_day,
                    "forecast_30_days_mb": trend.forecast_30_days_mb,
                    "confidence_score": trend.confidence_score,
                    "is_high_growth": trend.is_high_growth
                }
                for table_name, trend in growth_trends.items()
            }
            
            # Get capacity forecast
            dashboard_data["capacity_forecast"] = await self.capacity_planner.generate_capacity_forecast()
            
            # Generate alerts
            dashboard_data["alerts"] = await self._generate_capacity_alerts(
                dashboard_data["current_metrics"],
                growth_trends
            )
            
        except Exception as e:
            logger.error("failed_to_get_dashboard_data", error=str(e))
            dashboard_data["error"] = str(e)
        
        return dashboard_data
    
    async def _generate_capacity_alerts(self, current_metrics: Dict[str, Any], 
                                      growth_trends: Dict[str, GrowthTrend]) -> List[Dict[str, Any]]:
        """Generate capacity-related alerts"""
        alerts = []
        
        try:
            # Check capacity metrics for critical levels
            for metric_name, capacity_metric in current_metrics.get("capacity_metrics", {}).items():
                if isinstance(capacity_metric, CapacityMetric):
                    if capacity_metric.is_critical:
                        alerts.append({
                            "type": "critical",
                            "category": "capacity",
                            "message": f"{metric_name.title()} usage is critical: {capacity_metric.usage_percent:.1f}%",
                            "metric": metric_name,
                            "current_value": capacity_metric.current_value,
                            "max_value": capacity_metric.max_value,
                            "usage_percent": capacity_metric.usage_percent
                        })
                    elif capacity_metric.is_warning:
                        alerts.append({
                            "type": "warning",
                            "category": "capacity",
                            "message": f"{metric_name.title()} usage is high: {capacity_metric.usage_percent:.1f}%",
                            "metric": metric_name,
                            "current_value": capacity_metric.current_value,
                            "max_value": capacity_metric.max_value,
                            "usage_percent": capacity_metric.usage_percent
                        })
            
            # Check performance metrics
            for metric_name, perf_metric in current_metrics.get("performance_metrics", {}).items():
                if isinstance(perf_metric, PerformanceMetric):
                    if perf_metric.status == "critical":
                        alerts.append({
                            "type": "critical",
                            "category": "performance",
                            "message": f"{metric_name.replace('_', ' ').title()} is critical: {perf_metric.current_value:.1f} {perf_metric.unit}",
                            "metric": metric_name,
                            "current_value": perf_metric.current_value,
                            "threshold": perf_metric.threshold_critical,
                            "performance_score": perf_metric.performance_score
                        })
                    elif perf_metric.status == "warning":
                        alerts.append({
                            "type": "warning",
                            "category": "performance",
                            "message": f"{metric_name.replace('_', ' ').title()} is degraded: {perf_metric.current_value:.1f} {perf_metric.unit}",
                            "metric": metric_name,
                            "current_value": perf_metric.current_value,
                            "threshold": perf_metric.threshold_warning,
                            "performance_score": perf_metric.performance_score
                        })
            
            # Check growth trends
            for table_name, trend in growth_trends.items():
                if trend.is_high_growth:
                    alerts.append({
                        "type": "warning",
                        "category": "growth",
                        "message": f"Table {table_name} is growing rapidly: {trend.growth_rate_percent_per_day:.1f}% per day",
                        "table": table_name,
                        "growth_rate_percent": trend.growth_rate_percent_per_day,
                        "current_size_mb": trend.current_size_mb,
                        "forecast_30_days_mb": trend.forecast_30_days_mb
                    })
            
        except Exception as e:
            logger.error("failed_to_generate_capacity_alerts", error=str(e))
        
        return alerts
    
    async def export_prometheus_metrics(self) -> str:
        """Export all metrics in Prometheus format"""
        try:
            # Collect current metrics to update Prometheus gauges
            await self.metrics_collector.collect_all_metrics()
            
            # Generate Prometheus metrics output
            return generate_latest().decode('utf-8')
            
        except Exception as e:
            logger.error("failed_to_export_prometheus_metrics", error=str(e))
            return f"# Error exporting metrics: {str(e)}\n"
    
    async def shutdown(self):
        """Shutdown capacity manager"""
        logger.info("shutting_down_database_capacity_manager")
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("database_capacity_manager_shutdown_complete")