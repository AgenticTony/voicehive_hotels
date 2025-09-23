"""
Performance Optimization Integration for VoiceHive Hotels
Integrates all performance optimization components into a unified system
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger

# Import all performance optimization components
from redis_cluster_manager import RedisClusterManager, RedisClusterConfig, CacheWarmingManager, CacheWarmingConfig
from cache_invalidation_manager import CacheInvalidationManager, CacheInvalidationConfig, CacheEvent
from query_optimization_engine import QueryOptimizationEngine, QueryOptimizationConfig
from memory_optimization_manager import MemoryOptimizationManager, MemoryOptimizationConfig
from performance_benchmarking_system import PerformanceBenchmarkingSystem, BenchmarkConfig, BenchmarkScenario, BenchmarkType, LoadPattern

try:
    from prometheus_client import Counter, Histogram, Gauge, Info
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
    
    Counter = Histogram = Gauge = Info = MockMetric

logger = get_safe_logger("orchestrator.performance_integration")

# Prometheus metrics for integration monitoring
performance_optimization_status = Gauge(
    'voicehive_performance_optimization_status',
    'Performance optimization system status',
    ['component', 'status']
)

performance_optimization_actions = Counter(
    'voicehive_performance_optimization_actions_total',
    'Performance optimization actions taken',
    ['component', 'action', 'trigger']
)

performance_health_score = Gauge(
    'voicehive_performance_health_score',
    'Overall performance health score (0-100)',
    ['component']
)

performance_optimization_info = Info(
    'voicehive_performance_optimization_info',
    'Performance optimization system information'
)


class OptimizationPriority(str, Enum):
    """Optimization priority levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ComponentStatus(str, Enum):
    """Component status levels"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    OFFLINE = "offline"


@dataclass
class OptimizationAction:
    """Performance optimization action"""
    component: str
    action: str
    priority: OptimizationPriority
    description: str
    estimated_impact: float
    execution_time_estimate: int  # seconds
    dependencies: List[str]
    auto_execute: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "action": self.action,
            "priority": self.priority,
            "description": self.description,
            "estimated_impact": self.estimated_impact,
            "execution_time_estimate": self.execution_time_estimate,
            "dependencies": self.dependencies,
            "auto_execute": self.auto_execute
        }


class PerformanceOptimizationConfig(BaseModel):
    """Master configuration for performance optimization system"""
    # Component enablement
    enable_redis_cluster: bool = Field(True, description="Enable Redis cluster optimization")
    enable_cache_invalidation: bool = Field(True, description="Enable cache invalidation management")
    enable_query_optimization: bool = Field(True, description="Enable query optimization")
    enable_memory_optimization: bool = Field(True, description="Enable memory optimization")
    enable_benchmarking: bool = Field(True, description="Enable performance benchmarking")
    
    # Integration settings
    optimization_interval_seconds: int = Field(300, description="Optimization check interval")
    health_check_interval_seconds: int = Field(60, description="Health check interval")
    auto_optimization_enabled: bool = Field(True, description="Enable automatic optimizations")
    
    # Thresholds
    critical_performance_threshold: float = Field(30.0, description="Critical performance score threshold")
    warning_performance_threshold: float = Field(60.0, description="Warning performance score threshold")
    
    # Component configurations
    redis_cluster_config: RedisClusterConfig = Field(default_factory=RedisClusterConfig)
    cache_warming_config: CacheWarmingConfig = Field(default_factory=CacheWarmingConfig)
    cache_invalidation_config: CacheInvalidationConfig = Field(default_factory=CacheInvalidationConfig)
    query_optimization_config: QueryOptimizationConfig = Field(default_factory=QueryOptimizationConfig)
    memory_optimization_config: MemoryOptimizationConfig = Field(default_factory=MemoryOptimizationConfig)
    benchmark_config: BenchmarkConfig = Field(default_factory=BenchmarkConfig)


class PerformanceOptimizationSystem:
    """Unified performance optimization system"""
    
    def __init__(
        self,
        config: Optional[PerformanceOptimizationConfig] = None,
        connection_pool=None
    ):
        self.config = config or PerformanceOptimizationConfig()
        self.connection_pool = connection_pool
        
        # Component managers
        self.redis_cluster_manager: Optional[RedisClusterManager] = None
        self.cache_warming_manager: Optional[CacheWarmingManager] = None
        self.cache_invalidation_manager: Optional[CacheInvalidationManager] = None
        self.query_optimization_engine: Optional[QueryOptimizationEngine] = None
        self.memory_optimization_manager: Optional[MemoryOptimizationManager] = None
        self.benchmarking_system: Optional[PerformanceBenchmarkingSystem] = None
        
        # System state
        self.component_status: Dict[str, ComponentStatus] = {}
        self.pending_actions: List[OptimizationAction] = []
        self.executed_actions: List[Dict[str, Any]] = []
        
        # Background tasks
        self.optimization_tasks: List[asyncio.Task] = []
        
        # Statistics
        self.stats = {
            'optimizations_executed': 0,
            'performance_improvements': 0,
            'issues_detected': 0,
            'uptime_seconds': 0
        }
        
        self.start_time = time.time()
    
    async def initialize(self):
        """Initialize all performance optimization components"""
        logger.info("initializing_performance_optimization_system")
        
        try:
            # Initialize Redis Cluster Manager
            if self.config.enable_redis_cluster:
                self.redis_cluster_manager = RedisClusterManager(self.config.redis_cluster_config)
                if await self.redis_cluster_manager.initialize():
                    self.component_status['redis_cluster'] = ComponentStatus.HEALTHY
                    logger.info("redis_cluster_manager_initialized")
                    
                    # Initialize cache warming
                    self.cache_warming_manager = CacheWarmingManager(
                        self.redis_cluster_manager,
                        self.config.cache_warming_config
                    )
                    await self.cache_warming_manager.start_warming()
                    
                    # Initialize cache invalidation
                    self.cache_invalidation_manager = CacheInvalidationManager(
                        self.redis_cluster_manager,
                        self.config.cache_invalidation_config
                    )
                    await self.cache_invalidation_manager.start()
                    
                    self.component_status['cache_management'] = ComponentStatus.HEALTHY
                else:
                    self.component_status['redis_cluster'] = ComponentStatus.OFFLINE
                    logger.warning("redis_cluster_manager_initialization_failed")
            
            # Initialize Query Optimization Engine
            if self.config.enable_query_optimization and self.connection_pool:
                self.query_optimization_engine = QueryOptimizationEngine(
                    self.connection_pool,
                    self.config.query_optimization_config
                )
                await self.query_optimization_engine.initialize()
                self.component_status['query_optimization'] = ComponentStatus.HEALTHY
                logger.info("query_optimization_engine_initialized")
            
            # Initialize Memory Optimization Manager
            if self.config.enable_memory_optimization:
                self.memory_optimization_manager = MemoryOptimizationManager(
                    self.config.memory_optimization_config
                )
                await self.memory_optimization_manager.start()
                self.component_status['memory_optimization'] = ComponentStatus.HEALTHY
                logger.info("memory_optimization_manager_initialized")
            
            # Initialize Benchmarking System
            if self.config.enable_benchmarking:
                self.benchmarking_system = PerformanceBenchmarkingSystem(
                    self.config.benchmark_config
                )
                await self.benchmarking_system.start()
                self.component_status['benchmarking'] = ComponentStatus.HEALTHY
                logger.info("benchmarking_system_initialized")
            
            # Register cache managers with memory optimizer
            if self.memory_optimization_manager and self.redis_cluster_manager:
                self.memory_optimization_manager.register_cache_manager(
                    self._clear_redis_cache
                )
            
            # Start background tasks
            await self._start_background_tasks()
            
            # Update system info
            performance_optimization_info.info({
                'version': '1.0.0',
                'components': ','.join(self.component_status.keys()),
                'auto_optimization': str(self.config.auto_optimization_enabled),
                'start_time': datetime.now(timezone.utc).isoformat()
            })
            
            logger.info("performance_optimization_system_initialized",
                       components=list(self.component_status.keys()))
        
        except Exception as e:
            logger.error("performance_optimization_system_initialization_failed", error=str(e))
            raise
    
    async def _start_background_tasks(self):
        """Start background optimization and monitoring tasks"""
        # Health monitoring task
        task = asyncio.create_task(self._health_monitoring_loop())
        self.optimization_tasks.append(task)
        
        # Optimization coordination task
        if self.config.auto_optimization_enabled:
            task = asyncio.create_task(self._optimization_coordination_loop())
            self.optimization_tasks.append(task)
        
        # Performance analysis task
        task = asyncio.create_task(self._performance_analysis_loop())
        self.optimization_tasks.append(task)
        
        # Statistics update task
        task = asyncio.create_task(self._statistics_update_loop())
        self.optimization_tasks.append(task)
    
    async def _health_monitoring_loop(self):
        """Monitor health of all components"""
        while True:
            try:
                await asyncio.sleep(self.config.health_check_interval_seconds)
                
                # Check Redis cluster health
                if self.redis_cluster_manager:
                    cluster_stats = await self.redis_cluster_manager.get_cluster_stats()
                    if 'error' in cluster_stats:
                        self.component_status['redis_cluster'] = ComponentStatus.CRITICAL
                    else:
                        healthy_nodes = sum(
                            1 for node in cluster_stats.get('nodes', {}).values()
                            if node.get('failures', 0) == 0
                        )
                        total_nodes = len(cluster_stats.get('nodes', {}))
                        
                        if healthy_nodes < total_nodes * 0.5:
                            self.component_status['redis_cluster'] = ComponentStatus.CRITICAL
                        elif healthy_nodes < total_nodes * 0.8:
                            self.component_status['redis_cluster'] = ComponentStatus.WARNING
                        else:
                            self.component_status['redis_cluster'] = ComponentStatus.HEALTHY
                
                # Check memory optimization health
                if self.memory_optimization_manager:
                    memory_health = self.memory_optimization_manager.get_health_status()
                    if memory_health['status'] == 'critical':
                        self.component_status['memory_optimization'] = ComponentStatus.CRITICAL
                    elif memory_health['status'] == 'warning':
                        self.component_status['memory_optimization'] = ComponentStatus.WARNING
                    else:
                        self.component_status['memory_optimization'] = ComponentStatus.HEALTHY
                
                # Update component status metrics
                for component, status in self.component_status.items():
                    performance_optimization_status.labels(
                        component=component,
                        status=status
                    ).set(1 if status == ComponentStatus.HEALTHY else 0)
                
            except Exception as e:
                logger.error("health_monitoring_loop_error", error=str(e))
    
    async def _optimization_coordination_loop(self):
        """Coordinate optimization actions across components"""
        while True:
            try:
                await asyncio.sleep(self.config.optimization_interval_seconds)
                
                # Analyze current performance state
                performance_analysis = await self._analyze_system_performance()
                
                # Generate optimization recommendations
                recommendations = await self._generate_optimization_recommendations(performance_analysis)
                
                # Execute high-priority automatic optimizations
                for action in recommendations:
                    if action.auto_execute and action.priority in [OptimizationPriority.CRITICAL, OptimizationPriority.HIGH]:
                        await self._execute_optimization_action(action)
                
                # Store remaining recommendations
                self.pending_actions.extend([
                    action for action in recommendations 
                    if not action.auto_execute
                ])
                
                # Limit pending actions to prevent memory growth
                self.pending_actions = self.pending_actions[-100:]
                
            except Exception as e:
                logger.error("optimization_coordination_loop_error", error=str(e))
    
    async def _performance_analysis_loop(self):
        """Analyze performance trends and detect issues"""
        while True:
            try:
                await asyncio.sleep(600)  # Every 10 minutes
                
                # Collect performance data from all components
                performance_data = await self._collect_performance_data()
                
                # Analyze trends and detect anomalies
                issues = await self._detect_performance_issues(performance_data)
                
                # Log significant issues
                for issue in issues:
                    self.stats['issues_detected'] += 1
                    logger.warning("performance_issue_detected", **issue)
                
                # Calculate overall health scores
                health_scores = await self._calculate_health_scores(performance_data)
                
                # Update health score metrics
                for component, score in health_scores.items():
                    performance_health_score.labels(component=component).set(score)
                
            except Exception as e:
                logger.error("performance_analysis_loop_error", error=str(e))
    
    async def _statistics_update_loop(self):
        """Update system statistics"""
        while True:
            try:
                await asyncio.sleep(60)  # Every minute
                
                # Update uptime
                self.stats['uptime_seconds'] = int(time.time() - self.start_time)
                
                # Clean up old executed actions
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                self.executed_actions = [
                    action for action in self.executed_actions
                    if datetime.fromisoformat(action['timestamp']) > cutoff_time
                ]
                
            except Exception as e:
                logger.error("statistics_update_loop_error", error=str(e))
    
    async def _analyze_system_performance(self) -> Dict[str, Any]:
        """Analyze current system performance across all components"""
        analysis = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'overall_health': 'unknown',
            'component_health': {},
            'performance_metrics': {},
            'bottlenecks': [],
            'recommendations': []
        }
        
        try:
            # Redis cluster analysis
            if self.redis_cluster_manager:
                cluster_stats = await self.redis_cluster_manager.get_cluster_stats()
                analysis['component_health']['redis_cluster'] = {
                    'status': self.component_status.get('redis_cluster', ComponentStatus.OFFLINE),
                    'memory_usage_mb': cluster_stats.get('total_memory_used', 0) / (1024 * 1024),
                    'total_keys': cluster_stats.get('total_keys', 0),
                    'cluster_size': cluster_stats.get('cluster_size', 0)
                }
            
            # Memory optimization analysis
            if self.memory_optimization_manager:
                memory_report = self.memory_optimization_manager.get_memory_report()
                analysis['component_health']['memory_optimization'] = {
                    'status': self.component_status.get('memory_optimization', ComponentStatus.OFFLINE),
                    'current_memory_mb': memory_report['current_memory']['rss_mb'],
                    'detected_leaks': len(memory_report['detected_leaks']),
                    'fragmentation_ratio': memory_report['current_memory']['fragmentation_ratio']
                }
            
            # Query optimization analysis
            if self.query_optimization_engine:
                query_report = await self.query_optimization_engine.get_optimization_report()
                analysis['component_health']['query_optimization'] = {
                    'status': self.component_status.get('query_optimization', ComponentStatus.OFFLINE),
                    'slow_queries': query_report['summary']['slow_queries'],
                    'total_suggestions': query_report['summary']['total_suggestions'],
                    'avg_performance': query_report['system_health']['avg_query_performance']
                }
            
            # Benchmarking analysis
            if self.benchmarking_system:
                benchmark_report = self.benchmarking_system.get_performance_report()
                analysis['component_health']['benchmarking'] = {
                    'status': self.component_status.get('benchmarking', ComponentStatus.OFFLINE),
                    'recent_benchmarks': benchmark_report['summary']['recent_benchmarks'],
                    'regressions_detected': benchmark_report['summary']['regressions_detected']
                }
            
            # Calculate overall health
            health_scores = []
            for component_health in analysis['component_health'].values():
                if component_health['status'] == ComponentStatus.HEALTHY:
                    health_scores.append(100)
                elif component_health['status'] == ComponentStatus.WARNING:
                    health_scores.append(60)
                elif component_health['status'] == ComponentStatus.CRITICAL:
                    health_scores.append(20)
                else:
                    health_scores.append(0)
            
            if health_scores:
                avg_health = sum(health_scores) / len(health_scores)
                if avg_health >= 80:
                    analysis['overall_health'] = 'healthy'
                elif avg_health >= 60:
                    analysis['overall_health'] = 'warning'
                else:
                    analysis['overall_health'] = 'critical'
        
        except Exception as e:
            logger.error("system_performance_analysis_failed", error=str(e))
            analysis['error'] = str(e)
        
        return analysis
    
    async def _generate_optimization_recommendations(
        self,
        performance_analysis: Dict[str, Any]
    ) -> List[OptimizationAction]:
        """Generate optimization recommendations based on performance analysis"""
        recommendations = []
        
        try:
            # Redis cluster optimizations
            redis_health = performance_analysis.get('component_health', {}).get('redis_cluster', {})
            if redis_health.get('status') == ComponentStatus.WARNING:
                if redis_health.get('memory_usage_mb', 0) > 1000:  # High memory usage
                    recommendations.append(OptimizationAction(
                        component='redis_cluster',
                        action='clear_expired_keys',
                        priority=OptimizationPriority.HIGH,
                        description='Clear expired keys to reduce memory usage',
                        estimated_impact=20.0,
                        execution_time_estimate=30,
                        dependencies=[],
                        auto_execute=True
                    ))
            
            # Memory optimizations
            memory_health = performance_analysis.get('component_health', {}).get('memory_optimization', {})
            if memory_health.get('status') == ComponentStatus.CRITICAL:
                recommendations.append(OptimizationAction(
                    component='memory_optimization',
                    action='force_garbage_collection',
                    priority=OptimizationPriority.CRITICAL,
                    description='Force garbage collection to free memory',
                    estimated_impact=30.0,
                    execution_time_estimate=10,
                    dependencies=[],
                    auto_execute=True
                ))
            
            if memory_health.get('detected_leaks', 0) > 0:
                recommendations.append(OptimizationAction(
                    component='memory_optimization',
                    action='investigate_memory_leaks',
                    priority=OptimizationPriority.HIGH,
                    description=f"Investigate {memory_health.get('detected_leaks')} detected memory leaks",
                    estimated_impact=40.0,
                    execution_time_estimate=300,
                    dependencies=[],
                    auto_execute=False
                ))
            
            # Query optimizations
            query_health = performance_analysis.get('component_health', {}).get('query_optimization', {})
            if query_health.get('slow_queries', 0) > 10:
                recommendations.append(OptimizationAction(
                    component='query_optimization',
                    action='create_recommended_indexes',
                    priority=OptimizationPriority.MEDIUM,
                    description=f"Create indexes for {query_health.get('slow_queries')} slow queries",
                    estimated_impact=50.0,
                    execution_time_estimate=120,
                    dependencies=[],
                    auto_execute=False
                ))
            
            # Overall system optimizations
            if performance_analysis.get('overall_health') == 'critical':
                recommendations.append(OptimizationAction(
                    component='system',
                    action='comprehensive_optimization',
                    priority=OptimizationPriority.CRITICAL,
                    description='Perform comprehensive system optimization',
                    estimated_impact=60.0,
                    execution_time_estimate=600,
                    dependencies=['memory_optimization', 'redis_cluster'],
                    auto_execute=False
                ))
        
        except Exception as e:
            logger.error("optimization_recommendations_generation_failed", error=str(e))
        
        return recommendations
    
    async def _execute_optimization_action(self, action: OptimizationAction) -> Dict[str, Any]:
        """Execute a specific optimization action"""
        start_time = time.time()
        result = {
            'action': action.to_dict(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'success': False,
            'duration_seconds': 0,
            'impact_achieved': 0.0,
            'error': None
        }
        
        try:
            logger.info("executing_optimization_action",
                       component=action.component,
                       action=action.action,
                       priority=action.priority)
            
            # Execute based on component and action
            if action.component == 'redis_cluster' and action.action == 'clear_expired_keys':
                if self.redis_cluster_manager:
                    # Clear expired keys pattern
                    deleted = await self.redis_cluster_manager.invalidate_by_pattern("*:expired:*")
                    result['impact_achieved'] = min(action.estimated_impact, deleted * 0.1)
                    result['success'] = True
            
            elif action.component == 'memory_optimization' and action.action == 'force_garbage_collection':
                if self.memory_optimization_manager:
                    optimization_result = await self.memory_optimization_manager.force_optimization()
                    result['impact_achieved'] = optimization_result.get('memory_saved_mb', 0) * 2
                    result['success'] = True
            
            elif action.component == 'system' and action.action == 'comprehensive_optimization':
                # Execute multiple optimizations
                total_impact = 0.0
                
                if self.memory_optimization_manager:
                    memory_result = await self.memory_optimization_manager.force_optimization()
                    total_impact += memory_result.get('memory_saved_mb', 0) * 2
                
                if self.redis_cluster_manager:
                    deleted = await self.redis_cluster_manager.invalidate_by_pattern("*:temp:*")
                    total_impact += deleted * 0.1
                
                result['impact_achieved'] = min(action.estimated_impact, total_impact)
                result['success'] = True
            
            # Update metrics
            performance_optimization_actions.labels(
                component=action.component,
                action=action.action,
                trigger='automatic' if action.auto_execute else 'manual'
            ).inc()
            
            self.stats['optimizations_executed'] += 1
            if result['success']:
                self.stats['performance_improvements'] += 1
            
            result['duration_seconds'] = time.time() - start_time
            
            logger.info("optimization_action_completed",
                       component=action.component,
                       action=action.action,
                       success=result['success'],
                       impact=result['impact_achieved'],
                       duration=result['duration_seconds'])
        
        except Exception as e:
            result['error'] = str(e)
            result['duration_seconds'] = time.time() - start_time
            logger.error("optimization_action_failed",
                        component=action.component,
                        action=action.action,
                        error=str(e))
        
        # Store execution result
        self.executed_actions.append(result)
        
        return result
    
    async def _collect_performance_data(self) -> Dict[str, Any]:
        """Collect performance data from all components"""
        data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'components': {}
        }
        
        try:
            # Collect Redis cluster data
            if self.redis_cluster_manager:
                cluster_stats = await self.redis_cluster_manager.get_cluster_stats()
                data['components']['redis_cluster'] = cluster_stats
            
            # Collect memory optimization data
            if self.memory_optimization_manager:
                memory_report = self.memory_optimization_manager.get_memory_report()
                data['components']['memory_optimization'] = memory_report
            
            # Collect query optimization data
            if self.query_optimization_engine:
                query_report = await self.query_optimization_engine.get_optimization_report()
                data['components']['query_optimization'] = query_report
            
            # Collect benchmarking data
            if self.benchmarking_system:
                benchmark_report = self.benchmarking_system.get_performance_report()
                data['components']['benchmarking'] = benchmark_report
        
        except Exception as e:
            logger.error("performance_data_collection_failed", error=str(e))
            data['error'] = str(e)
        
        return data
    
    async def _detect_performance_issues(self, performance_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Detect performance issues from collected data"""
        issues = []
        
        try:
            # Check Redis cluster issues
            redis_data = performance_data.get('components', {}).get('redis_cluster', {})
            if redis_data.get('total_memory_used', 0) > 2 * 1024 * 1024 * 1024:  # 2GB
                issues.append({
                    'component': 'redis_cluster',
                    'issue': 'high_memory_usage',
                    'severity': 'warning',
                    'description': f"Redis cluster using {redis_data.get('total_memory_used', 0) / (1024*1024*1024):.1f}GB memory"
                })
            
            # Check memory issues
            memory_data = performance_data.get('components', {}).get('memory_optimization', {})
            if memory_data.get('current_memory', {}).get('rss_mb', 0) > 1024:  # 1GB
                issues.append({
                    'component': 'memory_optimization',
                    'issue': 'high_memory_usage',
                    'severity': 'warning',
                    'description': f"Process using {memory_data.get('current_memory', {}).get('rss_mb', 0):.1f}MB memory"
                })
            
            if len(memory_data.get('detected_leaks', [])) > 0:
                issues.append({
                    'component': 'memory_optimization',
                    'issue': 'memory_leaks_detected',
                    'severity': 'critical',
                    'description': f"{len(memory_data.get('detected_leaks', []))} memory leaks detected"
                })
            
            # Check query performance issues
            query_data = performance_data.get('components', {}).get('query_optimization', {})
            if query_data.get('summary', {}).get('slow_queries', 0) > 20:
                issues.append({
                    'component': 'query_optimization',
                    'issue': 'many_slow_queries',
                    'severity': 'warning',
                    'description': f"{query_data.get('summary', {}).get('slow_queries', 0)} slow queries detected"
                })
        
        except Exception as e:
            logger.error("performance_issue_detection_failed", error=str(e))
        
        return issues
    
    async def _calculate_health_scores(self, performance_data: Dict[str, Any]) -> Dict[str, float]:
        """Calculate health scores for each component"""
        scores = {}
        
        try:
            # Redis cluster health score
            redis_data = performance_data.get('components', {}).get('redis_cluster', {})
            if redis_data:
                score = 100.0
                
                # Deduct for high memory usage
                memory_gb = redis_data.get('total_memory_used', 0) / (1024 * 1024 * 1024)
                if memory_gb > 2:
                    score -= min(30, (memory_gb - 2) * 10)
                
                # Deduct for failed nodes
                total_nodes = len(redis_data.get('nodes', {}))
                failed_nodes = sum(
                    1 for node in redis_data.get('nodes', {}).values()
                    if node.get('failures', 0) > 0
                )
                if failed_nodes > 0:
                    score -= (failed_nodes / total_nodes) * 50
                
                scores['redis_cluster'] = max(0, score)
            
            # Memory optimization health score
            memory_data = performance_data.get('components', {}).get('memory_optimization', {})
            if memory_data:
                score = 100.0
                
                # Deduct for high memory usage
                memory_mb = memory_data.get('current_memory', {}).get('rss_mb', 0)
                if memory_mb > 512:
                    score -= min(40, (memory_mb - 512) / 512 * 40)
                
                # Deduct for memory leaks
                leak_count = len(memory_data.get('detected_leaks', []))
                if leak_count > 0:
                    score -= min(50, leak_count * 10)
                
                scores['memory_optimization'] = max(0, score)
            
            # Query optimization health score
            query_data = performance_data.get('components', {}).get('query_optimization', {})
            if query_data:
                avg_performance = query_data.get('system_health', {}).get('avg_query_performance', 100)
                scores['query_optimization'] = max(0, avg_performance)
            
            # Overall system health score
            if scores:
                scores['system'] = sum(scores.values()) / len(scores)
        
        except Exception as e:
            logger.error("health_score_calculation_failed", error=str(e))
        
        return scores
    
    async def _clear_redis_cache(self) -> Dict[str, Any]:
        """Clear Redis cache (registered with memory optimizer)"""
        if self.redis_cluster_manager:
            try:
                # Clear temporary and expired keys
                deleted_temp = await self.redis_cluster_manager.invalidate_by_pattern("*:temp:*")
                deleted_expired = await self.redis_cluster_manager.invalidate_by_pattern("*:expired:*")
                
                return {
                    'cleared_temp_keys': deleted_temp,
                    'cleared_expired_keys': deleted_expired,
                    'total_cleared': deleted_temp + deleted_expired
                }
            except Exception as e:
                logger.error("redis_cache_clear_failed", error=str(e))
                return {'error': str(e)}
        
        return {'error': 'Redis cluster manager not available'}
    
    async def execute_manual_optimization(self, action_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a manual optimization action"""
        try:
            action = OptimizationAction(
                component=action_dict['component'],
                action=action_dict['action'],
                priority=OptimizationPriority(action_dict.get('priority', 'medium')),
                description=action_dict.get('description', ''),
                estimated_impact=action_dict.get('estimated_impact', 0.0),
                execution_time_estimate=action_dict.get('execution_time_estimate', 60),
                dependencies=action_dict.get('dependencies', []),
                auto_execute=False
            )
            
            return await self._execute_optimization_action(action)
        
        except Exception as e:
            logger.error("manual_optimization_execution_failed", error=str(e))
            return {'error': str(e)}
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime_seconds': self.stats['uptime_seconds'],
            'component_status': dict(self.component_status),
            'statistics': self.stats,
            'pending_actions': len(self.pending_actions),
            'recent_actions': self.executed_actions[-10:],  # Last 10 actions
            'configuration': {
                'auto_optimization_enabled': self.config.auto_optimization_enabled,
                'optimization_interval_seconds': self.config.optimization_interval_seconds,
                'enabled_components': [
                    comp for comp, enabled in [
                        ('redis_cluster', self.config.enable_redis_cluster),
                        ('cache_invalidation', self.config.enable_cache_invalidation),
                        ('query_optimization', self.config.enable_query_optimization),
                        ('memory_optimization', self.config.enable_memory_optimization),
                        ('benchmarking', self.config.enable_benchmarking)
                    ] if enabled
                ]
            }
        }
    
    def get_pending_actions(self) -> List[Dict[str, Any]]:
        """Get list of pending optimization actions"""
        return [action.to_dict() for action in self.pending_actions]
    
    async def stop(self):
        """Stop the performance optimization system"""
        logger.info("stopping_performance_optimization_system")
        
        # Cancel background tasks
        for task in self.optimization_tasks:
            task.cancel()
        
        if self.optimization_tasks:
            await asyncio.gather(*self.optimization_tasks, return_exceptions=True)
        
        # Stop component managers
        if self.cache_invalidation_manager:
            await self.cache_invalidation_manager.stop()
        
        if self.cache_warming_manager:
            await self.cache_warming_manager.stop_warming()
        
        if self.redis_cluster_manager:
            await self.redis_cluster_manager.close()
        
        if self.query_optimization_engine:
            await self.query_optimization_engine.stop()
        
        if self.memory_optimization_manager:
            await self.memory_optimization_manager.stop()
        
        if self.benchmarking_system:
            await self.benchmarking_system.stop()
        
        logger.info("performance_optimization_system_stopped")


# Global performance optimization system instance
_performance_system: Optional[PerformanceOptimizationSystem] = None


def get_performance_optimization_system(
    config: Optional[PerformanceOptimizationConfig] = None,
    connection_pool=None
) -> PerformanceOptimizationSystem:
    """Get or create global performance optimization system"""
    global _performance_system
    
    if _performance_system is None:
        _performance_system = PerformanceOptimizationSystem(config, connection_pool)
        logger.info("global_performance_optimization_system_created")
    
    return _performance_system


async def initialize_performance_optimization(
    config: Optional[PerformanceOptimizationConfig] = None,
    connection_pool=None
) -> PerformanceOptimizationSystem:
    """Initialize performance optimization system with default configuration"""
    system = get_performance_optimization_system(config, connection_pool)
    await system.initialize()
    
    logger.info("performance_optimization_system_initialized_successfully")
    return system