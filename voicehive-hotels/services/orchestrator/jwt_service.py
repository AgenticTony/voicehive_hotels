"""
JWT Service for VoiceHive Hotels Orchestrator
Handles JWT token creation, validation, and management with Redis session store
"""

import jwt as pyjwt
import uuid
import aioredis
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from auth_models import (
    JWTPayload, UserContext, AuthenticationError, 
    UserRole, get_permissions_for_roles
)
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.jwt_service")


class JWTService:
    """JWT token management service with Redis session store"""
    
    def __init__(self, redis_url: str, secret_key: Optional[str] = None):
        self.redis_url = redis_url
        self.redis_pool = None
        self.algorithm = "RS256"
        
        # Generate RSA key pair for JWT signing
        if secret_key:
            # In production, load from Vault
            self.private_key = secret_key
            self.public_key = secret_key
        else:
            # Generate new key pair for development
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
            self.private_key = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            self.public_key = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
        
        # Token expiration times
        self.access_token_expire_minutes = 15
        self.refresh_token_expire_days = 7
        self.session_expire_hours = 24
    
    async def initialize(self):
        """Initialize Redis connection pool"""
        self.redis_pool = aioredis.ConnectionPool.from_url(
            self.redis_url,
            max_connections=20,
            retry_on_timeout=True
        )
        logger.info("jwt_service_initialized", redis_url=self.redis_url)
    
    async def get_redis(self) -> aioredis.Redis:
        """Get Redis connection from pool"""
        if not self.redis_pool:
            await self.initialize()
        return aioredis.Redis(connection_pool=self.redis_pool)
    
    async def create_tokens(self, user_context: UserContext) -> Dict[str, Any]:
        """Create access and refresh tokens for a user"""
        now = datetime.utcnow()
        session_id = str(uuid.uuid4())
        
        # Create JWT payload
        payload = JWTPayload(
            sub=user_context.user_id,
            email=user_context.email,
            roles=[role.value for role in user_context.roles],
            permissions=[perm.value for perm in user_context.permissions],
            hotel_ids=user_context.hotel_ids,
            iat=int(now.timestamp()),
            exp=int((now + timedelta(minutes=self.access_token_expire_minutes)).timestamp()),
            jti=str(uuid.uuid4()),
            session_id=session_id
        )
        
        # Create access token
        access_token = pyjwt.encode(
            payload.model_dump(),
            self.private_key,
            algorithm=self.algorithm
        )
        
        # Create refresh token
        refresh_payload = {
            "sub": user_context.user_id,
            "session_id": session_id,
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=self.refresh_token_expire_days)).timestamp()),
            "jti": str(uuid.uuid4())
        }
        
        refresh_token = pyjwt.encode(
            refresh_payload,
            self.private_key,
            algorithm=self.algorithm
        )
        
        # Store session in Redis
        redis = await self.get_redis()
        session_data = {
            "user_id": user_context.user_id,
            "email": user_context.email,
            "roles": [role.value for role in user_context.roles],
            "permissions": [perm.value for perm in user_context.permissions],
            "hotel_ids": user_context.hotel_ids or [],
            "created_at": now.isoformat(),
            "last_activity": now.isoformat(),
            "refresh_token_jti": refresh_payload["jti"]
        }
        
        await redis.hset(
            f"session:{session_id}",
            mapping=session_data
        )
        await redis.expire(f"session:{session_id}", self.session_expire_hours * 3600)
        
        # Store refresh token mapping
        await redis.set(
            f"refresh_token:{refresh_payload['jti']}",
            session_id,
            ex=self.refresh_token_expire_days * 24 * 3600
        )
        
        logger.info(
            "tokens_created",
            user_id=user_context.user_id,
            session_id=session_id,
            access_token_exp=payload.exp,
            refresh_token_exp=refresh_payload["exp"]
        )
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.access_token_expire_minutes * 60,
            "session_id": session_id
        }
    
    async def validate_token(self, token: str) -> UserContext:
        """Validate JWT access token and return user context"""
        try:
            # Decode and validate token
            payload = pyjwt.decode(
                token,
                self.public_key,
                algorithms=[self.algorithm],
                options={"verify_exp": True}
            )
            
            # Check if token is blacklisted
            redis = await self.get_redis()
            is_blacklisted = await redis.exists(f"blacklist:{payload['jti']}")
            if is_blacklisted:
                raise AuthenticationError("Token has been revoked")
            
            # Validate session exists and is active
            session_data = await redis.hgetall(f"session:{payload['session_id']}")
            if not session_data:
                raise AuthenticationError("Session not found or expired")
            
            # Update last activity
            await redis.hset(
                f"session:{payload['session_id']}",
                "last_activity",
                datetime.utcnow().isoformat()
            )
            
            # Create user context
            user_context = UserContext(
                user_id=payload["sub"],
                email=payload["email"],
                roles=[UserRole(role) for role in payload["roles"]],
                permissions=get_permissions_for_roles([UserRole(role) for role in payload["roles"]]),
                session_id=payload["session_id"],
                expires_at=datetime.fromtimestamp(payload["exp"]),
                hotel_ids=payload.get("hotel_ids")
            )
            
            return user_context
            
        except pyjwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except pyjwt.InvalidTokenError as e:
            raise AuthenticationError(f"Invalid token: {str(e)}")
        except Exception as e:
            logger.error("token_validation_error", error=str(e))
            raise AuthenticationError("Token validation failed")
    
    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access token using refresh token"""
        try:
            # Decode refresh token
            payload = pyjwt.decode(
                refresh_token,
                self.public_key,
                algorithms=[self.algorithm],
                options={"verify_exp": True}
            )
            
            if payload.get("type") != "refresh":
                raise AuthenticationError("Invalid token type")
            
            # Check if refresh token is valid
            redis = await self.get_redis()
            session_id = await redis.get(f"refresh_token:{payload['jti']}")
            if not session_id:
                raise AuthenticationError("Refresh token not found or expired")
            
            session_id = session_id.decode('utf-8')
            
            # Get session data
            session_data = await redis.hgetall(f"session:{session_id}")
            if not session_data:
                raise AuthenticationError("Session not found or expired")
            
            # Recreate user context
            user_context = UserContext(
                user_id=session_data[b"user_id"].decode('utf-8'),
                email=session_data[b"email"].decode('utf-8'),
                roles=[UserRole(role) for role in eval(session_data[b"roles"].decode('utf-8'))],
                permissions=get_permissions_for_roles([UserRole(role) for role in eval(session_data[b"roles"].decode('utf-8'))]),
                session_id=session_id,
                expires_at=datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes),
                hotel_ids=eval(session_data[b"hotel_ids"].decode('utf-8')) if session_data.get(b"hotel_ids") else None
            )
            
            # Create new access token (keep same refresh token)
            now = datetime.utcnow()
            new_payload = JWTPayload(
                sub=user_context.user_id,
                email=user_context.email,
                roles=[role.value for role in user_context.roles],
                permissions=[perm.value for perm in user_context.permissions],
                hotel_ids=user_context.hotel_ids,
                iat=int(now.timestamp()),
                exp=int((now + timedelta(minutes=self.access_token_expire_minutes)).timestamp()),
                jti=str(uuid.uuid4()),
                session_id=session_id
            )
            
            access_token = pyjwt.encode(
                new_payload.model_dump(),
                self.private_key,
                algorithm=self.algorithm
            )
            
            logger.info(
                "token_refreshed",
                user_id=user_context.user_id,
                session_id=session_id,
                new_exp=new_payload.exp
            )
            
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": self.access_token_expire_minutes * 60
            }
            
        except pyjwt.ExpiredSignatureError:
            raise AuthenticationError("Refresh token has expired")
        except pyjwt.InvalidTokenError as e:
            raise AuthenticationError(f"Invalid refresh token: {str(e)}")
        except Exception as e:
            logger.error("token_refresh_error", error=str(e))
            raise AuthenticationError("Token refresh failed")
    
    async def revoke_token(self, token: str):
        """Revoke a JWT token by adding it to blacklist"""
        try:
            payload = pyjwt.decode(
                token,
                self.public_key,
                algorithms=[self.algorithm],
                options={"verify_exp": False}  # Don't verify expiration for revocation
            )
            
            redis = await self.get_redis()
            
            # Add token to blacklist until its natural expiration
            ttl = max(0, payload["exp"] - int(datetime.utcnow().timestamp()))
            if ttl > 0:
                await redis.set(f"blacklist:{payload['jti']}", "1", ex=ttl)
            
            logger.info("token_revoked", jti=payload["jti"], user_id=payload["sub"])
            
        except Exception as e:
            logger.error("token_revocation_error", error=str(e))
            raise AuthenticationError("Token revocation failed")
    
    async def logout_session(self, session_id: str):
        """Logout a specific session"""
        redis = await self.get_redis()
        
        # Get session data to find refresh token
        session_data = await redis.hgetall(f"session:{session_id}")
        if session_data:
            # Remove refresh token
            refresh_token_jti = session_data.get(b"refresh_token_jti")
            if refresh_token_jti:
                await redis.delete(f"refresh_token:{refresh_token_jti.decode('utf-8')}")
        
        # Remove session
        await redis.delete(f"session:{session_id}")
        
        logger.info("session_logged_out", session_id=session_id)
    
    async def logout_all_sessions(self, user_id: str):
        """Logout all sessions for a user"""
        redis = await self.get_redis()
        
        # Find all sessions for user (this is a simplified approach)
        # In production, you might want to maintain a user->sessions mapping
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match="session:*", count=100)
            
            for key in keys:
                session_data = await redis.hgetall(key)
                if session_data and session_data.get(b"user_id", b"").decode('utf-8') == user_id:
                    session_id = key.decode('utf-8').split(':')[1]
                    await self.logout_session(session_id)
            
            if cursor == 0:
                break
        
        logger.info("all_sessions_logged_out", user_id=user_id)
    
    async def cleanup_expired_sessions(self):
        """Cleanup expired sessions (should be run periodically)"""
        redis = await self.get_redis()
        
        cursor = 0
        cleaned_count = 0
        
        while True:
            cursor, keys = await redis.scan(cursor, match="session:*", count=100)
            
            for key in keys:
                # Redis TTL will handle expiration, but we can do additional cleanup here
                ttl = await redis.ttl(key)
                if ttl == -2:  # Key doesn't exist
                    cleaned_count += 1
            
            if cursor == 0:
                break
        
        logger.info("session_cleanup_completed", cleaned_sessions=cleaned_count)
        return cleaned_count