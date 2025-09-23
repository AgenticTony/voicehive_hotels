"""
Performance Optimization module for VoiceHive Hotels Orchestrator

This module provides performance optimization capabilities including connection pooling,
intelligent caching, memory optimization, and performance monitoring and benchmarking.
"""

from .connection_pools import ConnectionPoolManager
from .caching import IntelligentCache, CacheInvalidationManager
from .memory_optimizer import MemoryOptimizationManager
from .audio_optimizer import AudioMemoryOptimizer
from .benchmarking import PerformanceBenchmarkingSystem
from .monitor import PerformanceMonitor

__all__ = [
    # Connection Management
    "ConnectionPoolManager",
    
    # Caching
    "IntelligentCache",
    "CacheInvalidationManager",
    
    # Memory Optimization
    "MemoryOptimizationManager",
    "AudioMemoryOptimizer",
    
    # Performance Analysis
    "PerformanceBenchmarkingSystem",
    "PerformanceMonitor",
]