"""
Webhook Security Module for VoiceHive Hotels
Provides signature verification and security for external webhook callbacks
"""

import hmac
import hashlib
import time
import base64
from typing import Dict, Optional, List, Tuple, Any
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, status
from pydantic import BaseModel, Field

from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.webhook_security")


class WebhookConfig(BaseModel):
    """Configuration for webhook security"""
    
    # Signature validation
    signature_header: str = Field(default="X-Signature-256")
    timestamp_header: str = Field(default="X-Timestamp")
    signature_algorithm: str = Field(default="sha256")
    
    # Timing validation
    max_timestamp_age: int = Field(default=300)  # 5 minutes
    
    # Rate limiting
    max_requests_per_minute: int = Field(default=100)
    max_requests_per_hour: int = Field(default=1000)
    
    # Content validation
    max_payload_size: int = Field(default=1048576)  # 1MB
    allowed_content_types: List[str] = Field(default=[
        "application/json",
        "application/x-www-form-urlencoded"
    ])
    
    # Security headers
    required_headers: List[str] = Field(default=[
        "User-Agent",
        "Content-Type"
    ])
    
    # Webhook sources configuration
    webhook_sources: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class WebhookSource(BaseModel):
    """Configuration for a specific webhook source"""
    
    name: str
    secret_key: str
    signature_header: Optional[str] = None
    timestamp_header: Optional[str] = None
    signature_format: str = Field(default="sha256={signature}")  # Format string
    ip_whitelist: Optional[List[str]] = None
    user_agent_pattern: Optional[str] = None
    custom_validation: Optional[str] = None  # Custom validation function name


class WebhookSecurityManager:
    """Manages webhook security validation"""
    
    def __init__(self, config: WebhookConfig):
        self.config = config
        self.sources: Dict[str, WebhookSource] = {}
        self.request_counts: Dict[str, List[datetime]] = {}
    
    def register_webhook_source(self, source: WebhookSource):
        """Register a webhook source with its configuration"""
        self.sources[source.name] = source
        logger.info(
            "webhook_source_registered",
            source=source.name,
            signature_header=source.signature_header or self.config.signature_header
        )
    
    def verify_webhook(self, request: Request, source_name: str, payload: bytes) -> bool:
        """
        Verify webhook authenticity and security
        
        Args:
            request: FastAPI request object
            source_name: Name of the webhook source
            payload: Raw request payload
            
        Returns:
            True if webhook is valid and secure
            
        Raises:
            HTTPException: If verification fails
        """
        
        # Get source configuration
        source = self.sources.get(source_name)
        if not source:
            logger.error("webhook_source_not_found", source=source_name)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown webhook source: {source_name}"
            )
        
        try:
            # 1. Rate limiting check
            self._check_rate_limits(request, source_name)
            
            # 2. IP whitelist check
            if source.ip_whitelist:
                self._check_ip_whitelist(request, source)
            
            # 3. User agent validation
            if source.user_agent_pattern:
                self._check_user_agent(request, source)
            
            # 4. Required headers check
            self._check_required_headers(request)
            
            # 5. Content type validation
            self._check_content_type(request)
            
            # 6. Payload size validation
            self._check_payload_size(payload)
            
            # 7. Timestamp validation
            self._check_timestamp(request, source)
            
            # 8. Signature verification
            self._verify_signature(request, source, payload)
            
            # 9. Custom validation if configured
            if source.custom_validation:
                self._run_custom_validation(request, source, payload)
            
            logger.info(
                "webhook_verified",
                source=source_name,
                client_ip=self._get_client_ip(request),
                user_agent=request.headers.get("User-Agent", "unknown")
            )
            
            return True
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "webhook_verification_error",
                source=source_name,
                error=str(e),
                client_ip=self._get_client_ip(request)
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook verification failed"
            )
    
    def _check_rate_limits(self, request: Request, source_name: str):
        """Check rate limits for webhook requests"""
        client_ip = self._get_client_ip(request)
        key = f"{source_name}:{client_ip}"
        
        now = datetime.utcnow()
        
        # Initialize if not exists
        if key not in self.request_counts:
            self.request_counts[key] = []
        
        # Clean old entries
        cutoff_minute = now - timedelta(minutes=1)
        cutoff_hour = now - timedelta(hours=1)
        
        self.request_counts[key] = [
            ts for ts in self.request_counts[key] 
            if ts > cutoff_hour
        ]
        
        # Count recent requests
        minute_count = sum(1 for ts in self.request_counts[key] if ts > cutoff_minute)
        hour_count = len(self.request_counts[key])
        
        # Check limits
        if minute_count >= self.config.max_requests_per_minute:
            logger.warning(
                "webhook_rate_limit_exceeded",
                source=source_name,
                client_ip=client_ip,
                minute_count=minute_count,
                limit=self.config.max_requests_per_minute
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded"
            )
        
        if hour_count >= self.config.max_requests_per_hour:
            logger.warning(
                "webhook_hourly_limit_exceeded",
                source=source_name,
                client_ip=client_ip,
                hour_count=hour_count,
                limit=self.config.max_requests_per_hour
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Hourly rate limit exceeded"
            )
        
        # Record this request
        self.request_counts[key].append(now)
    
    def _check_ip_whitelist(self, request: Request, source: WebhookSource):
        """Check if request IP is in whitelist"""
        client_ip = self._get_client_ip(request)
        
        if client_ip not in source.ip_whitelist:
            logger.warning(
                "webhook_ip_not_whitelisted",
                source=source.name,
                client_ip=client_ip,
                whitelist=source.ip_whitelist
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="IP address not authorized"
            )
    
    def _check_user_agent(self, request: Request, source: WebhookSource):
        """Check user agent pattern"""
        import re
        
        user_agent = request.headers.get("User-Agent", "")
        pattern = re.compile(source.user_agent_pattern)
        
        if not pattern.match(user_agent):
            logger.warning(
                "webhook_invalid_user_agent",
                source=source.name,
                user_agent=user_agent,
                expected_pattern=source.user_agent_pattern
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid User-Agent"
            )
    
    def _check_required_headers(self, request: Request):
        """Check that all required headers are present"""
        missing_headers = []
        
        for header in self.config.required_headers:
            if header not in request.headers:
                missing_headers.append(header)
        
        if missing_headers:
            logger.warning(
                "webhook_missing_headers",
                missing_headers=missing_headers
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required headers: {', '.join(missing_headers)}"
            )
    
    def _check_content_type(self, request: Request):
        """Check content type is allowed"""
        content_type = request.headers.get("Content-Type", "").split(";")[0]
        
        if content_type not in self.config.allowed_content_types:
            logger.warning(
                "webhook_invalid_content_type",
                content_type=content_type,
                allowed=self.config.allowed_content_types
            )
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Content type '{content_type}' not allowed"
            )
    
    def _check_payload_size(self, payload: bytes):
        """Check payload size limits"""
        if len(payload) > self.config.max_payload_size:
            logger.warning(
                "webhook_payload_too_large",
                size=len(payload),
                max_size=self.config.max_payload_size
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Payload too large"
            )
    
    def _check_timestamp(self, request: Request, source: WebhookSource):
        """Check timestamp to prevent replay attacks"""
        timestamp_header = source.timestamp_header or self.config.timestamp_header
        timestamp_str = request.headers.get(timestamp_header)
        
        if not timestamp_str:
            logger.warning(
                "webhook_missing_timestamp",
                source=source.name,
                header=timestamp_header
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing timestamp header: {timestamp_header}"
            )
        
        try:
            # Parse timestamp (assuming Unix timestamp)
            timestamp = int(timestamp_str)
            request_time = datetime.fromtimestamp(timestamp)
            now = datetime.utcnow()
            
            age = (now - request_time).total_seconds()
            
            if age > self.config.max_timestamp_age:
                logger.warning(
                    "webhook_timestamp_too_old",
                    source=source.name,
                    age=age,
                    max_age=self.config.max_timestamp_age
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Request timestamp too old"
                )
            
            if age < -60:  # Allow 1 minute clock skew
                logger.warning(
                    "webhook_timestamp_future",
                    source=source.name,
                    age=age
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Request timestamp in future"
                )
                
        except ValueError:
            logger.warning(
                "webhook_invalid_timestamp",
                source=source.name,
                timestamp=timestamp_str
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid timestamp format"
            )
    
    def _verify_signature(self, request: Request, source: WebhookSource, payload: bytes):
        """Verify webhook signature"""
        signature_header = source.signature_header or self.config.signature_header
        signature = request.headers.get(signature_header)
        
        if not signature:
            logger.warning(
                "webhook_missing_signature",
                source=source.name,
                header=signature_header
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing signature header: {signature_header}"
            )
        
        # Calculate expected signature
        expected_signature = self._calculate_signature(source, payload, request)
        
        # Compare signatures (constant time comparison)
        if not hmac.compare_digest(signature, expected_signature):
            logger.warning(
                "webhook_signature_mismatch",
                source=source.name,
                provided_signature=signature[:20] + "...",  # Log partial for debugging
                client_ip=self._get_client_ip(request)
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid signature"
            )
    
    def _calculate_signature(self, source: WebhookSource, payload: bytes, request: Request) -> str:
        """Calculate expected signature for payload"""
        
        # Get timestamp for signature calculation
        timestamp_header = source.timestamp_header or self.config.timestamp_header
        timestamp = request.headers.get(timestamp_header, "")
        
        # Create signature payload (payload + timestamp for replay protection)
        signature_payload = payload + timestamp.encode('utf-8')
        
        # Calculate HMAC
        signature_bytes = hmac.new(
            source.secret_key.encode('utf-8'),
            signature_payload,
            hashlib.sha256
        ).digest()
        
        # Format according to source configuration
        signature_hex = signature_bytes.hex()
        
        # Apply format string (e.g., "sha256={signature}")
        return source.signature_format.format(signature=signature_hex)
    
    def _run_custom_validation(self, request: Request, source: WebhookSource, payload: bytes):
        """Run custom validation function if configured"""
        # This would import and run a custom validation function
        # For now, just log that custom validation would run
        logger.info(
            "webhook_custom_validation",
            source=source.name,
            function=source.custom_validation
        )
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request"""
        # Check for forwarded headers first
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to direct connection
        if hasattr(request, "client") and request.client:
            return request.client.host
        
        return "unknown"


# Webhook verification decorator
def verify_webhook(source_name: str, security_manager: WebhookSecurityManager):
    """Decorator to verify webhook requests"""
    
    def decorator(func):
        async def wrapper(request: Request, *args, **kwargs):
            # Read payload
            payload = await request.body()
            
            # Verify webhook
            security_manager.verify_webhook(request, source_name, payload)
            
            # Call original function
            return await func(request, *args, **kwargs)
        
        return wrapper
    return decorator


# Common webhook source configurations
def create_github_webhook_source(name: str, secret: str) -> WebhookSource:
    """Create GitHub webhook source configuration"""
    return WebhookSource(
        name=name,
        secret_key=secret,
        signature_header="X-Hub-Signature-256",
        signature_format="sha256={signature}",
        user_agent_pattern=r"GitHub-Hookshot/.*"
    )


def create_stripe_webhook_source(name: str, secret: str) -> WebhookSource:
    """Create Stripe webhook source configuration"""
    return WebhookSource(
        name=name,
        secret_key=secret,
        signature_header="Stripe-Signature",
        timestamp_header="Stripe-Timestamp",
        signature_format="t={timestamp},v1={signature}",
        user_agent_pattern=r"Stripe/.*"
    )


def create_twilio_webhook_source(name: str, secret: str) -> WebhookSource:
    """Create Twilio webhook source configuration"""
    return WebhookSource(
        name=name,
        secret_key=secret,
        signature_header="X-Twilio-Signature",
        user_agent_pattern=r"TwilioProxy/.*"
    )


# Example usage
if __name__ == "__main__":
    # Test webhook security
    config = WebhookConfig()
    manager = WebhookSecurityManager(config)
    
    # Register some webhook sources
    github_source = create_github_webhook_source("github", "secret123")
    manager.register_webhook_source(github_source)
    
    stripe_source = create_stripe_webhook_source("stripe", "whsec_secret456")
    manager.register_webhook_source(stripe_source)
    
    print("Webhook security manager initialized with sources:")
    for source_name in manager.sources:
        print(f"  - {source_name}")