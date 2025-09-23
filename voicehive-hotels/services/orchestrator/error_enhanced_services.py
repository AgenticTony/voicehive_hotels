"""
Enhanced service wrappers with comprehensive error handling and retry logic
"""

import asyncio
from typing import Any, Dict, Optional, Callable
from contextlib import asynccontextmanager

from error_models import (
    ExternalServiceError, PMSConnectorError, DatabaseError, 
    ErrorSeverity, ErrorCategory
)
from retry_utils import RetryableOperation, DEFAULT_RETRY_CONFIGS
from correlation_middleware import CorrelationIDLogger, get_correlation_id
from error_handler import graceful_degradation

logger = CorrelationIDLogger("error_enhanced_services")


class ErrorEnhancedTTSClient:
    """
    TTS client wrapper with comprehensive error handling
    """
    
    def __init__(self, original_client):
        self.original_client = original_client
        self.service_name = "tts_service"
    
    async def synthesize_speech(self, text: str, language: str = "en", **kwargs) -> Dict[str, Any]:
        """Synthesize speech with error handling and retry logic"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "synthesize_speech",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["tts_service"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_client.synthesize_speech,
                    text, language, **kwargs
                )
        
        except Exception as e:
            logger.error(
                "tts_synthesis_failed",
                text_length=len(text),
                language=language,
                error=str(e),
                correlation_id=correlation_id
            )
            
            # Attempt graceful degradation
            fallback_result = await graceful_degradation.handle_service_failure(
                self.service_name,
                "synthesize_speech",
                {"text": text, "language": language}
            )
            
            return fallback_result
    
    async def get_voices(self, language: str = "en") -> Dict[str, Any]:
        """Get available voices with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "get_voices",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["tts_service"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_client.get_voices,
                    language
                )
        
        except Exception as e:
            logger.error(
                "tts_get_voices_failed",
                language=language,
                error=str(e),
                correlation_id=correlation_id
            )
            
            # Return cached or default voices
            return {
                "voices": [],
                "fallback_active": True,
                "message": "Voice list temporarily unavailable"
            }
    
    async def health_check(self) -> bool:
        """Health check with error handling"""
        try:
            return await self.original_client.health_check()
        except Exception as e:
            logger.warning(
                "tts_health_check_failed",
                error=str(e),
                correlation_id=get_correlation_id()
            )
            return False


class ErrorEnhancedPMSConnector:
    """
    PMS connector wrapper with comprehensive error handling
    """
    
    def __init__(self, original_connector, connector_name: str):
        self.original_connector = original_connector
        self.connector_name = connector_name
        self.service_name = f"pms_connector_{connector_name}"
    
    async def get_guest_info(self, hotel_id: str, room_number: str, **kwargs) -> Dict[str, Any]:
        """Get guest information with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "get_guest_info",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["pms_connector"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_connector.get_guest_info,
                    hotel_id, room_number, **kwargs
                )
        
        except Exception as e:
            logger.error(
                "pms_get_guest_info_failed",
                hotel_id=hotel_id,
                room_number=room_number,
                connector=self.connector_name,
                error=str(e),
                correlation_id=correlation_id
            )
            
            # Attempt graceful degradation
            fallback_result = await graceful_degradation.handle_service_failure(
                "pms_connector",
                "get_guest_info",
                {"hotel_id": hotel_id, "room_number": room_number}
            )
            
            return fallback_result
    
    async def create_service_request(self, hotel_id: str, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create service request with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "create_service_request",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["pms_connector"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_connector.create_service_request,
                    hotel_id, request_data
                )
        
        except Exception as e:
            logger.error(
                "pms_create_service_request_failed",
                hotel_id=hotel_id,
                request_type=request_data.get("type"),
                connector=self.connector_name,
                error=str(e),
                correlation_id=correlation_id
            )
            
            # Attempt graceful degradation
            fallback_result = await graceful_degradation.handle_service_failure(
                "pms_connector",
                "create_service_request",
                {"hotel_id": hotel_id, "request_data": request_data}
            )
            
            return fallback_result
    
    async def update_room_status(self, hotel_id: str, room_number: str, status: str) -> Dict[str, Any]:
        """Update room status with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "update_room_status",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["pms_connector"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_connector.update_room_status,
                    hotel_id, room_number, status
                )
        
        except Exception as e:
            logger.error(
                "pms_update_room_status_failed",
                hotel_id=hotel_id,
                room_number=room_number,
                status=status,
                connector=self.connector_name,
                error=str(e),
                correlation_id=correlation_id
            )
            
            raise PMSConnectorError(
                connector=self.connector_name,
                message=f"Failed to update room status: {str(e)}",
                details={
                    "hotel_id": hotel_id,
                    "room_number": room_number,
                    "status": status,
                    "correlation_id": correlation_id
                }
            )


class ErrorEnhancedDatabaseClient:
    """
    Database client wrapper with comprehensive error handling
    """
    
    def __init__(self, original_client):
        self.original_client = original_client
        self.service_name = "database"
    
    async def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute database query with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "execute_query",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["database"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_client.execute,
                    query, params or {}
                )
        
        except Exception as e:
            logger.error(
                "database_query_failed",
                query_hash=hash(query),
                error=str(e),
                correlation_id=correlation_id
            )
            
            raise DatabaseError(
                message=f"Database query failed: {str(e)}",
                operation="execute_query",
                details={
                    "query_hash": hash(query),
                    "correlation_id": correlation_id
                }
            )
    
    async def fetch_one(self, query: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Fetch single record with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "fetch_one",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["database"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_client.fetchrow,
                    query, params or {}
                )
        
        except Exception as e:
            logger.error(
                "database_fetch_one_failed",
                query_hash=hash(query),
                error=str(e),
                correlation_id=correlation_id
            )
            
            raise DatabaseError(
                message=f"Database fetch failed: {str(e)}",
                operation="fetch_one",
                details={
                    "query_hash": hash(query),
                    "correlation_id": correlation_id
                }
            )
    
    async def fetch_many(self, query: str, params: Optional[Dict[str, Any]] = None) -> list:
        """Fetch multiple records with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "fetch_many",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["database"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_client.fetch,
                    query, params or {}
                )
        
        except Exception as e:
            logger.error(
                "database_fetch_many_failed",
                query_hash=hash(query),
                error=str(e),
                correlation_id=correlation_id
            )
            
            raise DatabaseError(
                message=f"Database fetch failed: {str(e)}",
                operation="fetch_many",
                details={
                    "query_hash": hash(query),
                    "correlation_id": correlation_id
                }
            )


class ErrorEnhancedRedisClient:
    """
    Redis client wrapper with comprehensive error handling
    """
    
    def __init__(self, original_client):
        self.original_client = original_client
        self.service_name = "redis"
    
    async def get(self, key: str) -> Optional[str]:
        """Get value with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "get",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["redis"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_client.get,
                    key
                )
        
        except Exception as e:
            logger.warning(
                "redis_get_failed",
                key=key,
                error=str(e),
                correlation_id=correlation_id
            )
            return None
    
    async def set(self, key: str, value: str, expire: Optional[int] = None) -> bool:
        """Set value with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "set",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["redis"],
                correlation_id
            ) as op:
                if expire:
                    return await op.execute(
                        self.original_client.setex,
                        key, expire, value
                    )
                else:
                    return await op.execute(
                        self.original_client.set,
                        key, value
                    )
        
        except Exception as e:
            logger.error(
                "redis_set_failed",
                key=key,
                error=str(e),
                correlation_id=correlation_id
            )
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key with error handling"""
        correlation_id = get_correlation_id()
        
        try:
            async with RetryableOperation(
                "delete",
                self.service_name,
                DEFAULT_RETRY_CONFIGS["redis"],
                correlation_id
            ) as op:
                return await op.execute(
                    self.original_client.delete,
                    key
                )
        
        except Exception as e:
            logger.warning(
                "redis_delete_failed",
                key=key,
                error=str(e),
                correlation_id=correlation_id
            )
            return False


# Factory functions to create enhanced clients
def enhance_tts_client(original_client):
    """Create error-enhanced TTS client"""
    return ErrorEnhancedTTSClient(original_client)


def enhance_pms_connector(original_connector, connector_name: str):
    """Create error-enhanced PMS connector"""
    return ErrorEnhancedPMSConnector(original_connector, connector_name)


def enhance_database_client(original_client):
    """Create error-enhanced database client"""
    return ErrorEnhancedDatabaseClient(original_client)


def enhance_redis_client(original_client):
    """Create error-enhanced Redis client"""
    return ErrorEnhancedRedisClient(original_client)