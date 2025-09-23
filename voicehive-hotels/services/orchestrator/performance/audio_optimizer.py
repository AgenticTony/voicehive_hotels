"""
Audio Memory Optimizer for VoiceHive Hotels Orchestrator
Optimizes memory usage in audio streaming components with intelligent buffering
"""

import asyncio
import gc
import weakref
from typing import Optional, Dict, List, Any, AsyncIterator, Callable, Union
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import io
import mmap
import tempfile
import os

try:
    import psutil
except ImportError:
    psutil = None

from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger

try:
    from prometheus_client import Gauge, Counter, Histogram
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
        def dec(self, value=1):
            pass
        def observe(self, value):
            pass
    
    Gauge = Counter = Histogram = MockMetric

logger = get_safe_logger("orchestrator.audio_memory")

# Prometheus metrics for audio memory monitoring
audio_memory_usage = Gauge(
    'voicehive_audio_memory_usage_bytes',
    'Audio memory usage in bytes',
    ['component', 'buffer_type']
)

audio_buffer_count = Gauge(
    'voicehive_audio_buffer_count',
    'Number of active audio buffers',
    ['component', 'buffer_type']
)

audio_memory_operations = Counter(
    'voicehive_audio_memory_operations_total',
    'Audio memory operations',
    ['component', 'operation', 'result']
)

audio_gc_collections = Counter(
    'voicehive_audio_gc_collections_total',
    'Audio garbage collections triggered',
    ['component', 'trigger']
)

audio_streaming_latency = Histogram(
    'voicehive_audio_streaming_latency_seconds',
    'Audio streaming operation latency',
    ['component', 'operation'],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)


class BufferType(str, Enum):
    """Types of audio buffers"""
    CIRCULAR = "circular"      # Circular buffer for streaming
    RING = "ring"             # Ring buffer with fixed size
    MEMORY_MAPPED = "memory_mapped"  # Memory-mapped file buffer
    COMPRESSED = "compressed"  # Compressed audio buffer
    CHUNKED = "chunked"       # Chunked streaming buffer


class CompressionType(str, Enum):
    """Audio compression types for memory optimization"""
    NONE = "none"
    GZIP = "gzip"
    LZ4 = "lz4"
    ZSTD = "zstd"


class AudioFormat(BaseModel):
    """Audio format specification"""
    sample_rate: int = Field(24000, description="Sample rate in Hz")
    channels: int = Field(1, description="Number of channels")
    bit_depth: int = Field(16, description="Bit depth")
    format: str = Field("pcm", description="Audio format (pcm, mp3, wav)")
    
    def bytes_per_second(self) -> int:
        """Calculate bytes per second for this format"""
        return (self.sample_rate * self.channels * self.bit_depth) // 8
    
    def bytes_per_sample(self) -> int:
        """Calculate bytes per sample"""
        return (self.channels * self.bit_depth) // 8


class BufferConfig(BaseModel):
    """Configuration for audio buffers"""
    # Buffer size settings
    max_buffer_size_mb: int = Field(10, description="Maximum buffer size in MB")
    chunk_size_bytes: int = Field(4096, description="Chunk size for streaming")
    prealloc_buffers: int = Field(5, description="Number of pre-allocated buffers")
    
    # Memory management
    enable_memory_mapping: bool = Field(True, description="Enable memory-mapped files for large buffers")
    memory_map_threshold_mb: int = Field(5, description="Threshold for using memory mapping")
    enable_compression: bool = Field(True, description="Enable buffer compression")
    compression_type: CompressionType = Field(CompressionType.LZ4, description="Compression algorithm")
    
    # Garbage collection
    gc_threshold_mb: int = Field(50, description="Memory threshold to trigger GC")
    gc_interval_seconds: int = Field(30, description="GC check interval")
    auto_gc_enabled: bool = Field(True, description="Enable automatic garbage collection")
    
    # Performance tuning
    buffer_pool_size: int = Field(10, description="Size of buffer pool")
    enable_zero_copy: bool = Field(True, description="Enable zero-copy operations where possible")
    prefetch_size_bytes: int = Field(8192, description="Prefetch size for streaming")


@dataclass
class BufferStats:
    """Statistics for audio buffers"""
    buffer_id: str
    buffer_type: BufferType
    size_bytes: int = 0
    capacity_bytes: int = 0
    usage_percent: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0
    is_compressed: bool = False
    is_memory_mapped: bool = False


class CircularAudioBuffer:
    """Memory-efficient circular buffer for audio streaming"""
    
    def __init__(
        self,
        buffer_id: str,
        capacity_bytes: int,
        audio_format: AudioFormat,
        config: BufferConfig
    ):
        self.buffer_id = buffer_id
        self.capacity_bytes = capacity_bytes
        self.audio_format = audio_format
        self.config = config
        
        # Buffer state
        self._buffer: Optional[bytearray] = None
        self._write_pos = 0
        self._read_pos = 0
        self._size = 0
        self._lock = asyncio.Lock()
        
        # Memory mapping
        self._temp_file: Optional[tempfile.NamedTemporaryFile] = None
        self._mmap: Optional[mmap.mmap] = None
        
        # Statistics
        self.stats = BufferStats(
            buffer_id=buffer_id,
            buffer_type=BufferType.CIRCULAR,
            capacity_bytes=capacity_bytes
        )
        
        # Initialize buffer
        self._initialize_buffer()
    
    def _initialize_buffer(self):
        """Initialize the buffer storage"""
        try:
            # Use memory mapping for large buffers
            if (self.config.enable_memory_mapping and 
                self.capacity_bytes > self.config.memory_map_threshold_mb * 1024 * 1024):
                
                self._temp_file = tempfile.NamedTemporaryFile(delete=False)
                self._temp_file.write(b'\x00' * self.capacity_bytes)
                self._temp_file.flush()
                
                self._mmap = mmap.mmap(
                    self._temp_file.fileno(),
                    self.capacity_bytes,
                    access=mmap.ACCESS_WRITE
                )
                
                self.stats.is_memory_mapped = True
                logger.debug("circular_buffer_memory_mapped", buffer_id=self.buffer_id)
                
            else:
                # Use regular bytearray
                self._buffer = bytearray(self.capacity_bytes)
                logger.debug("circular_buffer_memory_allocated", buffer_id=self.buffer_id)
            
            # Update metrics
            audio_memory_usage.labels(
                component="circular_buffer",
                buffer_type="audio"
            ).inc(self.capacity_bytes)
            
            audio_buffer_count.labels(
                component="circular_buffer",
                buffer_type="audio"
            ).inc()
            
        except Exception as e:
            logger.error("circular_buffer_init_failed", buffer_id=self.buffer_id, error=str(e))
            raise
    
    async def write(self, data: bytes) -> int:
        """Write data to circular buffer"""
        if not data:
            return 0
        
        start_time = datetime.now(timezone.utc)
        
        async with self._lock:
            try:
                data_len = len(data)
                available_space = self.capacity_bytes - self._size
                
                if data_len > available_space:
                    # Buffer overflow - overwrite oldest data
                    bytes_to_overwrite = data_len - available_space
                    self._read_pos = (self._read_pos + bytes_to_overwrite) % self.capacity_bytes
                    self._size = self.capacity_bytes
                else:
                    self._size += data_len
                
                # Write data (may wrap around)
                bytes_written = 0
                remaining = data_len
                
                while remaining > 0:
                    # Calculate how much we can write before wrapping
                    chunk_size = min(remaining, self.capacity_bytes - self._write_pos)
                    
                    # Write chunk
                    if self._mmap:
                        self._mmap[self._write_pos:self._write_pos + chunk_size] = \
                            data[bytes_written:bytes_written + chunk_size]
                    else:
                        self._buffer[self._write_pos:self._write_pos + chunk_size] = \
                            data[bytes_written:bytes_written + chunk_size]
                    
                    bytes_written += chunk_size
                    remaining -= chunk_size
                    self._write_pos = (self._write_pos + chunk_size) % self.capacity_bytes
                
                # Update statistics
                self.stats.size_bytes = self._size
                self.stats.usage_percent = (self._size / self.capacity_bytes) * 100
                self.stats.last_accessed = datetime.now(timezone.utc)
                self.stats.access_count += 1
                
                # Record metrics
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                audio_streaming_latency.labels(
                    component="circular_buffer",
                    operation="write"
                ).observe(duration)
                
                audio_memory_operations.labels(
                    component="circular_buffer",
                    operation="write",
                    result="success"
                ).inc()
                
                return data_len
                
            except Exception as e:
                logger.error("circular_buffer_write_error", buffer_id=self.buffer_id, error=str(e))
                audio_memory_operations.labels(
                    component="circular_buffer",
                    operation="write",
                    result="error"
                ).inc()
                return 0
    
    async def read(self, size: int) -> bytes:
        """Read data from circular buffer"""
        start_time = datetime.now(timezone.utc)
        
        async with self._lock:
            try:
                if self._size == 0:
                    return b''
                
                # Limit read size to available data
                read_size = min(size, self._size)
                result = bytearray(read_size)
                
                bytes_read = 0
                remaining = read_size
                
                while remaining > 0:
                    # Calculate how much we can read before wrapping
                    chunk_size = min(remaining, self.capacity_bytes - self._read_pos)
                    
                    # Read chunk
                    if self._mmap:
                        result[bytes_read:bytes_read + chunk_size] = \
                            self._mmap[self._read_pos:self._read_pos + chunk_size]
                    else:
                        result[bytes_read:bytes_read + chunk_size] = \
                            self._buffer[self._read_pos:self._read_pos + chunk_size]
                    
                    bytes_read += chunk_size
                    remaining -= chunk_size
                    self._read_pos = (self._read_pos + chunk_size) % self.capacity_bytes
                
                self._size -= read_size
                
                # Update statistics
                self.stats.size_bytes = self._size
                self.stats.usage_percent = (self._size / self.capacity_bytes) * 100
                self.stats.last_accessed = datetime.now(timezone.utc)
                self.stats.access_count += 1
                
                # Record metrics
                duration = (datetime.now(timezone.utc) - start_time).total_seconds()
                audio_streaming_latency.labels(
                    component="circular_buffer",
                    operation="read"
                ).observe(duration)
                
                audio_memory_operations.labels(
                    component="circular_buffer",
                    operation="read",
                    result="success"
                ).inc()
                
                return bytes(result)
                
            except Exception as e:
                logger.error("circular_buffer_read_error", buffer_id=self.buffer_id, error=str(e))
                audio_memory_operations.labels(
                    component="circular_buffer",
                    operation="read",
                    result="error"
                ).inc()
                return b''
    
    async def peek(self, size: int) -> bytes:
        """Peek at data without consuming it"""
        async with self._lock:
            if self._size == 0:
                return b''
            
            # Similar to read but don't advance read position
            read_size = min(size, self._size)
            result = bytearray(read_size)
            
            bytes_read = 0
            remaining = read_size
            temp_read_pos = self._read_pos
            
            while remaining > 0:
                chunk_size = min(remaining, self.capacity_bytes - temp_read_pos)
                
                if self._mmap:
                    result[bytes_read:bytes_read + chunk_size] = \
                        self._mmap[temp_read_pos:temp_read_pos + chunk_size]
                else:
                    result[bytes_read:bytes_read + chunk_size] = \
                        self._buffer[temp_read_pos:temp_read_pos + chunk_size]
                
                bytes_read += chunk_size
                remaining -= chunk_size
                temp_read_pos = (temp_read_pos + chunk_size) % self.capacity_bytes
            
            return bytes(result)
    
    def available_bytes(self) -> int:
        """Get number of bytes available for reading"""
        return self._size
    
    def free_space(self) -> int:
        """Get number of bytes available for writing"""
        return self.capacity_bytes - self._size
    
    def is_full(self) -> bool:
        """Check if buffer is full"""
        return self._size >= self.capacity_bytes
    
    def is_empty(self) -> bool:
        """Check if buffer is empty"""
        return self._size == 0
    
    async def clear(self):
        """Clear buffer contents"""
        async with self._lock:
            self._read_pos = 0
            self._write_pos = 0
            self._size = 0
            
            self.stats.size_bytes = 0
            self.stats.usage_percent = 0.0
    
    async def close(self):
        """Close buffer and cleanup resources"""
        async with self._lock:
            try:
                # Update metrics
                audio_memory_usage.labels(
                    component="circular_buffer",
                    buffer_type="audio"
                ).dec(self.capacity_bytes)
                
                audio_buffer_count.labels(
                    component="circular_buffer",
                    buffer_type="audio"
                ).dec()
                
                # Cleanup memory mapping
                if self._mmap:
                    self._mmap.close()
                    self._mmap = None
                
                if self._temp_file:
                    self._temp_file.close()
                    try:
                        os.unlink(self._temp_file.name)
                    except OSError:
                        pass
                    self._temp_file = None
                
                # Clear buffer
                self._buffer = None
                
                logger.debug("circular_buffer_closed", buffer_id=self.buffer_id)
                
            except Exception as e:
                logger.error("circular_buffer_close_error", buffer_id=self.buffer_id, error=str(e))


class AudioBufferPool:
    """Pool of reusable audio buffers"""
    
    def __init__(self, config: BufferConfig):
        self.config = config
        self._available_buffers: List[CircularAudioBuffer] = []
        self._active_buffers: Dict[str, CircularAudioBuffer] = {}
        self._lock = asyncio.Lock()
        self._buffer_counter = 0
        
    async def initialize(self, audio_format: AudioFormat):
        """Initialize buffer pool with pre-allocated buffers"""
        async with self._lock:
            for i in range(self.config.prealloc_buffers):
                buffer_id = f"pool_buffer_{i}"
                buffer = CircularAudioBuffer(
                    buffer_id=buffer_id,
                    capacity_bytes=self.config.max_buffer_size_mb * 1024 * 1024,
                    audio_format=audio_format,
                    config=self.config
                )
                self._available_buffers.append(buffer)
        
        logger.info("audio_buffer_pool_initialized", count=self.config.prealloc_buffers)
    
    async def acquire_buffer(
        self,
        audio_format: AudioFormat,
        capacity_bytes: Optional[int] = None
    ) -> CircularAudioBuffer:
        """Acquire buffer from pool or create new one"""
        async with self._lock:
            # Try to reuse available buffer
            if self._available_buffers:
                buffer = self._available_buffers.pop()
                await buffer.clear()  # Reset buffer state
                self._active_buffers[buffer.buffer_id] = buffer
                return buffer
            
            # Create new buffer if pool is empty
            self._buffer_counter += 1
            buffer_id = f"dynamic_buffer_{self._buffer_counter}"
            
            capacity = capacity_bytes or (self.config.max_buffer_size_mb * 1024 * 1024)
            
            buffer = CircularAudioBuffer(
                buffer_id=buffer_id,
                capacity_bytes=capacity,
                audio_format=audio_format,
                config=self.config
            )
            
            self._active_buffers[buffer_id] = buffer
            return buffer
    
    async def release_buffer(self, buffer: CircularAudioBuffer):
        """Release buffer back to pool"""
        async with self._lock:
            if buffer.buffer_id in self._active_buffers:
                del self._active_buffers[buffer.buffer_id]
                
                # Return to pool if we have space
                if len(self._available_buffers) < self.config.buffer_pool_size:
                    await buffer.clear()
                    self._available_buffers.append(buffer)
                else:
                    # Pool is full, close the buffer
                    await buffer.close()
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get buffer pool statistics"""
        async with self._lock:
            return {
                'available_buffers': len(self._available_buffers),
                'active_buffers': len(self._active_buffers),
                'total_buffers': len(self._available_buffers) + len(self._active_buffers),
                'pool_capacity': self.config.buffer_pool_size
            }
    
    async def close_all(self):
        """Close all buffers in pool"""
        async with self._lock:
            # Close available buffers
            for buffer in self._available_buffers:
                await buffer.close()
            self._available_buffers.clear()
            
            # Close active buffers
            for buffer in self._active_buffers.values():
                await buffer.close()
            self._active_buffers.clear()
        
        logger.info("audio_buffer_pool_closed")


class AudioStreamProcessor:
    """Optimized audio stream processor with memory management"""
    
    def __init__(self, config: BufferConfig):
        self.config = config
        self.buffer_pool = AudioBufferPool(config)
        self._active_streams: Dict[str, Dict[str, Any]] = {}
        self._gc_task: Optional[asyncio.Task] = None
        
    async def initialize(self):
        """Initialize audio stream processor"""
        # Initialize buffer pool with default format
        default_format = AudioFormat()
        await self.buffer_pool.initialize(default_format)
        
        # Start garbage collection task
        if self.config.auto_gc_enabled:
            self._gc_task = asyncio.create_task(self._gc_loop())
        
        logger.info("audio_stream_processor_initialized")
    
    async def create_stream(
        self,
        stream_id: str,
        audio_format: AudioFormat,
        buffer_size_mb: Optional[int] = None
    ) -> CircularAudioBuffer:
        """Create new audio stream with optimized buffer"""
        capacity_bytes = (buffer_size_mb or self.config.max_buffer_size_mb) * 1024 * 1024
        
        buffer = await self.buffer_pool.acquire_buffer(audio_format, capacity_bytes)
        
        self._active_streams[stream_id] = {
            'buffer': buffer,
            'audio_format': audio_format,
            'created_at': datetime.now(timezone.utc),
            'last_activity': datetime.now(timezone.utc)
        }
        
        logger.info("audio_stream_created", stream_id=stream_id, format=audio_format.dict())
        return buffer
    
    async def get_stream_buffer(self, stream_id: str) -> Optional[CircularAudioBuffer]:
        """Get buffer for existing stream"""
        stream_info = self._active_streams.get(stream_id)
        if stream_info:
            stream_info['last_activity'] = datetime.now(timezone.utc)
            return stream_info['buffer']
        return None
    
    async def close_stream(self, stream_id: str):
        """Close audio stream and release resources"""
        stream_info = self._active_streams.pop(stream_id, None)
        if stream_info:
            buffer = stream_info['buffer']
            await self.buffer_pool.release_buffer(buffer)
            logger.info("audio_stream_closed", stream_id=stream_id)
    
    async def process_audio_chunk(
        self,
        stream_id: str,
        audio_data: bytes,
        process_func: Optional[Callable[[bytes], bytes]] = None
    ) -> bytes:
        """Process audio chunk with memory optimization"""
        start_time = datetime.now(timezone.utc)
        
        try:
            buffer = await self.get_stream_buffer(stream_id)
            if not buffer:
                raise ValueError(f"Stream {stream_id} not found")
            
            # Write to buffer
            await buffer.write(audio_data)
            
            # Process if function provided
            if process_func:
                # Read data for processing
                processed_data = process_func(audio_data)
                
                # Clear buffer and write processed data
                await buffer.clear()
                await buffer.write(processed_data)
                
                result = processed_data
            else:
                result = audio_data
            
            # Record metrics
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            audio_streaming_latency.labels(
                component="stream_processor",
                operation="process_chunk"
            ).observe(duration)
            
            return result
            
        except Exception as e:
            logger.error("audio_chunk_processing_error", stream_id=stream_id, error=str(e))
            audio_memory_operations.labels(
                component="stream_processor",
                operation="process_chunk",
                result="error"
            ).inc()
            return b''
    
    async def stream_audio_chunks(
        self,
        stream_id: str,
        chunk_size: Optional[int] = None
    ) -> AsyncIterator[bytes]:
        """Stream audio chunks from buffer"""
        buffer = await self.get_stream_buffer(stream_id)
        if not buffer:
            return
        
        chunk_size = chunk_size or self.config.chunk_size_bytes
        
        while True:
            chunk = await buffer.read(chunk_size)
            if not chunk:
                await asyncio.sleep(0.01)  # Small delay to prevent busy waiting
                continue
            
            yield chunk
    
    async def get_memory_usage(self) -> Dict[str, Any]:
        """Get current memory usage statistics"""
        if psutil is None:
            return {
                'process_memory_mb': 0.0,
                'active_streams': len(self._active_streams),
                'buffer_pool': await self.buffer_pool.get_stats(),
                'gc_collections': [0, 0, 0]
            }
        
        process = psutil.Process()
        memory_info = process.memory_info()
        
        pool_stats = await self.buffer_pool.get_stats()
        
        return {
            'process_memory_mb': memory_info.rss / 1024 / 1024,
            'active_streams': len(self._active_streams),
            'buffer_pool': pool_stats,
            'gc_collections': gc.get_count()
        }
    
    async def _gc_loop(self):
        """Background garbage collection loop"""
        while True:
            try:
                await asyncio.sleep(self.config.gc_interval_seconds)
                
                # Check memory usage
                memory_usage = await self.get_memory_usage()
                current_memory_mb = memory_usage['process_memory_mb']
                
                if current_memory_mb > self.config.gc_threshold_mb:
                    # Trigger garbage collection
                    collected = gc.collect()
                    
                    audio_gc_collections.labels(
                        component="stream_processor",
                        trigger="memory_threshold"
                    ).inc()
                    
                    logger.info(
                        "audio_gc_triggered",
                        memory_mb=current_memory_mb,
                        threshold_mb=self.config.gc_threshold_mb,
                        collected=collected
                    )
                
                # Clean up inactive streams
                await self._cleanup_inactive_streams()
                
            except Exception as e:
                logger.error("audio_gc_loop_error", error=str(e))
    
    async def _cleanup_inactive_streams(self):
        """Clean up streams that haven't been active recently"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        inactive_streams = []
        
        for stream_id, stream_info in self._active_streams.items():
            if stream_info['last_activity'] < cutoff_time:
                inactive_streams.append(stream_id)
        
        for stream_id in inactive_streams:
            await self.close_stream(stream_id)
            logger.info("inactive_stream_cleaned", stream_id=stream_id)
    
    async def close(self):
        """Close audio stream processor"""
        # Cancel GC task
        if self._gc_task:
            self._gc_task.cancel()
        
        # Close all active streams
        for stream_id in list(self._active_streams.keys()):
            await self.close_stream(stream_id)
        
        # Close buffer pool
        await self.buffer_pool.close_all()
        
        logger.info("audio_stream_processor_closed")


class AudioMemoryOptimizer:
    """Main audio memory optimization coordinator"""
    
    def __init__(self, config: Optional[BufferConfig] = None):
        self.config = config or BufferConfig()
        self.stream_processor = AudioStreamProcessor(self.config)
        self._initialized = False
        
    async def initialize(self):
        """Initialize audio memory optimizer"""
        if self._initialized:
            return
        
        await self.stream_processor.initialize()
        self._initialized = True
        
        logger.info("audio_memory_optimizer_initialized")
    
    async def create_optimized_stream(
        self,
        stream_id: str,
        audio_format: AudioFormat,
        buffer_size_mb: Optional[int] = None
    ) -> CircularAudioBuffer:
        """Create memory-optimized audio stream"""
        if not self._initialized:
            await self.initialize()
        
        return await self.stream_processor.create_stream(
            stream_id, audio_format, buffer_size_mb
        )
    
    async def process_audio_data(
        self,
        stream_id: str,
        audio_data: bytes,
        process_func: Optional[Callable[[bytes], bytes]] = None
    ) -> bytes:
        """Process audio data with memory optimization"""
        return await self.stream_processor.process_audio_chunk(
            stream_id, audio_data, process_func
        )
    
    async def get_audio_stream(self, stream_id: str) -> AsyncIterator[bytes]:
        """Get optimized audio stream"""
        async for chunk in self.stream_processor.stream_audio_chunks(stream_id):
            yield chunk
    
    async def close_stream(self, stream_id: str):
        """Close audio stream"""
        await self.stream_processor.close_stream(stream_id)
    
    async def get_optimization_stats(self) -> Dict[str, Any]:
        """Get audio memory optimization statistics"""
        return await self.stream_processor.get_memory_usage()
    
    async def force_garbage_collection(self) -> int:
        """Force garbage collection and return collected objects"""
        collected = gc.collect()
        
        audio_gc_collections.labels(
            component="optimizer",
            trigger="manual"
        ).inc()
        
        logger.info("manual_gc_triggered", collected=collected)
        return collected
    
    async def close(self):
        """Close audio memory optimizer"""
        await self.stream_processor.close()
        self._initialized = False
        
        logger.info("audio_memory_optimizer_closed")


# Global audio memory optimizer instance
_audio_optimizer: Optional[AudioMemoryOptimizer] = None


def get_audio_memory_optimizer(
    config: Optional[BufferConfig] = None
) -> AudioMemoryOptimizer:
    """Get or create global audio memory optimizer"""
    global _audio_optimizer
    
    if _audio_optimizer is None:
        _audio_optimizer = AudioMemoryOptimizer(config)
        logger.info("global_audio_memory_optimizer_created")
    
    return _audio_optimizer


# Convenience functions
async def create_audio_stream(
    stream_id: str,
    sample_rate: int = 24000,
    channels: int = 1,
    bit_depth: int = 16,
    buffer_size_mb: int = 5
) -> CircularAudioBuffer:
    """Create optimized audio stream with default settings"""
    optimizer = get_audio_memory_optimizer()
    
    audio_format = AudioFormat(
        sample_rate=sample_rate,
        channels=channels,
        bit_depth=bit_depth
    )
    
    return await optimizer.create_optimized_stream(
        stream_id, audio_format, buffer_size_mb
    )


async def optimize_audio_processing(
    stream_id: str,
    audio_data: bytes,
    compression_func: Optional[Callable[[bytes], bytes]] = None
) -> bytes:
    """Process audio data with automatic optimization"""
    optimizer = get_audio_memory_optimizer()
    return await optimizer.process_audio_data(stream_id, audio_data, compression_func)