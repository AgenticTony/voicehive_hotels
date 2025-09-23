"""
Backpressure Handling for Streaming Audio Operations
Manages flow control and prevents resource exhaustion during high-load scenarios
"""

import asyncio
import time
from typing import Dict, Optional, Callable, Any, AsyncGenerator
from dataclasses import dataclass
from enum import Enum
import weakref

import redis.asyncio as aioredis
from pydantic import BaseModel

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.backpressure")


class BackpressureStrategy(str, Enum):
    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    BLOCK = "block"
    ADAPTIVE = "adaptive"


@dataclass
class BackpressureConfig:
    """Backpressure configuration"""
    max_queue_size: int = 1000
    max_memory_mb: int = 100
    strategy: BackpressureStrategy = BackpressureStrategy.ADAPTIVE
    timeout_seconds: float = 30.0
    warning_threshold: float = 0.8  # Warn when queue is 80% full
    adaptive_threshold: float = 0.9  # Switch strategies when 90% full


class BackpressureStats(BaseModel):
    """Backpressure statistics"""
    current_queue_size: int
    max_queue_size: int
    current_memory_mb: float
    max_memory_mb: float
    total_processed: int
    total_dropped: int
    total_blocked: int
    average_processing_time: float
    strategy: BackpressureStrategy


class BackpressureHandler:
    """
    Handles backpressure for streaming operations with multiple strategies
    """
    
    def __init__(
        self, 
        name: str,
        config: BackpressureConfig,
        redis_client: Optional[aioredis.Redis] = None
    ):
        self.name = name
        self.config = config
        self.redis = redis_client
        
        # Queue management
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=config.max_queue_size)
        self.processing_tasks: Dict[str, asyncio.Task] = {}
        
        # Statistics
        self.stats = {
            'total_processed': 0,
            'total_dropped': 0,
            'total_blocked': 0,
            'processing_times': [],
            'memory_usage': 0.0
        }
        
        # Adaptive strategy state
        self.current_strategy = config.strategy
        self.last_strategy_change = time.time()
        
        # Memory tracking
        self._tracked_objects = weakref.WeakSet()
        
        logger.info("backpressure_handler_created", name=name, config=config)
    
    async def submit_task(
        self, 
        task_id: str, 
        coro: Callable,
        *args, 
        **kwargs
    ) -> Optional[asyncio.Task]:
        """
        Submit a task for processing with backpressure handling
        """
        current_size = self.queue.qsize()
        memory_usage = await self._estimate_memory_usage()
        
        # Check if we're approaching limits
        size_ratio = current_size / self.config.max_queue_size
        memory_ratio = memory_usage / self.config.max_memory_mb
        
        # Log warning if approaching thresholds
        if size_ratio >= self.config.warning_threshold or memory_ratio >= self.config.warning_threshold:
            logger.warning(
                "backpressure_warning",
                name=self.name,
                queue_size=current_size,
                memory_mb=memory_usage,
                size_ratio=size_ratio,
                memory_ratio=memory_ratio
            )
        
        # Apply backpressure strategy
        if size_ratio >= 1.0 or memory_ratio >= 1.0:
            return await self._handle_backpressure(task_id, coro, *args, **kwargs)
        
        # Adaptive strategy adjustment
        if self.config.strategy == BackpressureStrategy.ADAPTIVE:
            await self._adjust_strategy(size_ratio, memory_ratio)
        
        # Submit task normally
        try:
            task_data = {
                'id': task_id,
                'coro': coro,
                'args': args,
                'kwargs': kwargs,
                'submitted_at': time.time()
            }
            
            await asyncio.wait_for(
                self.queue.put(task_data),
                timeout=self.config.timeout_seconds
            )
            
            # Start processing if not already running
            if task_id not in self.processing_tasks:
                task = asyncio.create_task(self._process_task(task_data))
                self.processing_tasks[task_id] = task
                return task
            
        except asyncio.TimeoutError:
            self.stats['total_blocked'] += 1
            logger.warning("backpressure_task_blocked", name=self.name, task_id=task_id)
            return None
        except Exception as e:
            logger.error("backpressure_submit_error", name=self.name, task_id=task_id, error=str(e))
            return None
    
    async def _handle_backpressure(
        self, 
        task_id: str, 
        coro: Callable, 
        *args, 
        **kwargs
    ) -> Optional[asyncio.Task]:
        """Handle backpressure based on configured strategy"""
        
        if self.current_strategy == BackpressureStrategy.DROP_OLDEST:
            return await self._drop_oldest_and_submit(task_id, coro, *args, **kwargs)
        
        elif self.current_strategy == BackpressureStrategy.DROP_NEWEST:
            self.stats['total_dropped'] += 1
            logger.info("backpressure_dropped_newest", name=self.name, task_id=task_id)
            return None
        
        elif self.current_strategy == BackpressureStrategy.BLOCK:
            return await self._block_and_submit(task_id, coro, *args, **kwargs)
        
        elif self.current_strategy == BackpressureStrategy.ADAPTIVE:
            # Use drop_oldest for high memory, block for high queue
            memory_ratio = (await self._estimate_memory_usage()) / self.config.max_memory_mb
            if memory_ratio > 0.95:
                return await self._drop_oldest_and_submit(task_id, coro, *args, **kwargs)
            else:
                return await self._block_and_submit(task_id, coro, *args, **kwargs)
        
        return None
    
    async def _drop_oldest_and_submit(
        self, 
        task_id: str, 
        coro: Callable, 
        *args, 
        **kwargs
    ) -> Optional[asyncio.Task]:
        """Drop oldest task and submit new one"""
        try:
            # Remove oldest task from queue
            if not self.queue.empty():
                dropped_task = await asyncio.wait_for(self.queue.get(), timeout=0.1)
                self.stats['total_dropped'] += 1
                logger.info(
                    "backpressure_dropped_oldest", 
                    name=self.name, 
                    dropped_id=dropped_task.get('id', 'unknown'),
                    new_id=task_id
                )
            
            # Submit new task
            return await self.submit_task(task_id, coro, *args, **kwargs)
            
        except asyncio.TimeoutError:
            logger.warning("backpressure_no_task_to_drop", name=self.name)
            return None
    
    async def _block_and_submit(
        self, 
        task_id: str, 
        coro: Callable, 
        *args, 
        **kwargs
    ) -> Optional[asyncio.Task]:
        """Block until space is available and submit"""
        try:
            # Wait for space with timeout
            start_time = time.time()
            
            while self.queue.qsize() >= self.config.max_queue_size:
                await asyncio.sleep(0.1)
                if time.time() - start_time > self.config.timeout_seconds:
                    self.stats['total_blocked'] += 1
                    logger.warning("backpressure_block_timeout", name=self.name, task_id=task_id)
                    return None
            
            # Submit task
            return await self.submit_task(task_id, coro, *args, **kwargs)
            
        except Exception as e:
            logger.error("backpressure_block_error", name=self.name, error=str(e))
            return None
    
    async def _adjust_strategy(self, size_ratio: float, memory_ratio: float):
        """Adjust strategy based on current conditions (adaptive mode)"""
        now = time.time()
        
        # Don't change strategy too frequently
        if now - self.last_strategy_change < 10:  # 10 second cooldown
            return
        
        old_strategy = self.current_strategy
        
        if memory_ratio > 0.95:
            self.current_strategy = BackpressureStrategy.DROP_OLDEST
        elif size_ratio > 0.95:
            self.current_strategy = BackpressureStrategy.BLOCK
        else:
            self.current_strategy = self.config.strategy
        
        if old_strategy != self.current_strategy:
            self.last_strategy_change = now
            logger.info(
                "backpressure_strategy_changed",
                name=self.name,
                old_strategy=old_strategy,
                new_strategy=self.current_strategy,
                size_ratio=size_ratio,
                memory_ratio=memory_ratio
            )
    
    async def _process_task(self, task_data: Dict[str, Any]):
        """Process a single task"""
        task_id = task_data['id']
        start_time = time.time()
        
        try:
            coro = task_data['coro']
            args = task_data['args']
            kwargs = task_data['kwargs']
            
            # Execute the coroutine
            if asyncio.iscoroutinefunction(coro):
                result = await coro(*args, **kwargs)
            else:
                result = coro(*args, **kwargs)
            
            # Update statistics
            processing_time = time.time() - start_time
            self.stats['total_processed'] += 1
            self.stats['processing_times'].append(processing_time)
            
            # Keep only recent processing times for average calculation
            if len(self.stats['processing_times']) > 1000:
                self.stats['processing_times'] = self.stats['processing_times'][-500:]
            
            logger.debug(
                "backpressure_task_completed",
                name=self.name,
                task_id=task_id,
                processing_time=processing_time
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "backpressure_task_error",
                name=self.name,
                task_id=task_id,
                error=str(e)
            )
            raise
        finally:
            # Clean up
            if task_id in self.processing_tasks:
                del self.processing_tasks[task_id]
    
    async def _estimate_memory_usage(self) -> float:
        """Estimate current memory usage in MB"""
        try:
            import psutil
            import os
            
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            return memory_info.rss / (1024 * 1024)  # Convert to MB
            
        except ImportError:
            # Fallback: estimate based on queue size and average object size
            queue_size = self.queue.qsize()
            estimated_mb = queue_size * 0.1  # Assume 0.1 MB per queued item
            return estimated_mb
        except Exception as e:
            logger.warning("memory_estimation_failed", error=str(e))
            return 0.0
    
    async def get_stats(self) -> BackpressureStats:
        """Get current backpressure statistics"""
        processing_times = self.stats['processing_times']
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0.0
        
        return BackpressureStats(
            current_queue_size=self.queue.qsize(),
            max_queue_size=self.config.max_queue_size,
            current_memory_mb=await self._estimate_memory_usage(),
            max_memory_mb=self.config.max_memory_mb,
            total_processed=self.stats['total_processed'],
            total_dropped=self.stats['total_dropped'],
            total_blocked=self.stats['total_blocked'],
            average_processing_time=avg_processing_time,
            strategy=self.current_strategy
        )
    
    async def shutdown(self):
        """Gracefully shutdown the backpressure handler"""
        logger.info("backpressure_handler_shutdown_started", name=self.name)
        
        # Cancel all processing tasks
        for task_id, task in self.processing_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                logger.debug("backpressure_task_cancelled", task_id=task_id)
        
        # Clear queue
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        logger.info("backpressure_handler_shutdown_completed", name=self.name)


class BackpressureManager:
    """Manages multiple backpressure handlers"""
    
    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self.redis = redis_client
        self.handlers: Dict[str, BackpressureHandler] = {}
    
    def create_handler(
        self, 
        name: str, 
        config: Optional[BackpressureConfig] = None
    ) -> BackpressureHandler:
        """Create a new backpressure handler"""
        if config is None:
            config = BackpressureConfig()
        
        handler = BackpressureHandler(name, config, self.redis)
        self.handlers[name] = handler
        
        logger.info("backpressure_handler_created", name=name)
        return handler
    
    def get_handler(self, name: str) -> Optional[BackpressureHandler]:
        """Get existing backpressure handler"""
        return self.handlers.get(name)
    
    async def get_all_stats(self) -> Dict[str, BackpressureStats]:
        """Get statistics for all handlers"""
        stats = {}
        for name, handler in self.handlers.items():
            stats[name] = await handler.get_stats()
        return stats
    
    async def shutdown_all(self):
        """Shutdown all handlers"""
        for handler in self.handlers.values():
            await handler.shutdown()
        self.handlers.clear()
        logger.info("all_backpressure_handlers_shutdown")


# Decorator for applying backpressure to streaming functions
def with_backpressure(
    handler_name: str,
    config: Optional[BackpressureConfig] = None,
    manager: Optional[BackpressureManager] = None
):
    """Decorator to apply backpressure handling to streaming functions"""
    
    def decorator(func):
        async def wrapper(*args, **kwargs):
            if manager is None:
                # Create a simple handler for this function
                handler = BackpressureHandler(
                    handler_name, 
                    config or BackpressureConfig()
                )
            else:
                handler = manager.get_handler(handler_name)
                if handler is None:
                    handler = manager.create_handler(handler_name, config)
            
            task_id = f"{func.__name__}_{int(time.time() * 1000)}"
            task = await handler.submit_task(task_id, func, *args, **kwargs)
            
            if task:
                return await task
            else:
                raise Exception(f"Task {task_id} was dropped due to backpressure")
        
        return wrapper
    return decorator