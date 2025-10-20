"""
Comprehensive unit tests for JWT Service
Tests token creation, validation, refresh, revocation, and session management
"""

import pytest
import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import jwt as pyjwt

from auth.jwt_service import JWTService
from auth_models import (
    UserContext, UserRole, Permission, AuthenticationError,
    get_permissions_for_roles
)


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing"""
    redis_mock = AsyncMock()
    # Mock Redis responses with proper byte encoding
    redis_mock.hgetall.return_value = {
        b"user_id": b"test-user-123",
        b"email": b"test@example.com",
        b"roles": b"['admin']",
        b"permissions": b"['read', 'write']",
        b"hotel_ids": b"['hotel-1', 'hotel-2']",
        b"created_at": b"2023-01-01T00:00:00",
        b"last_activity": b"2023-01-01T00:00:00",
        b"refresh_token_jti": b"refresh-jti-123"
    }
    redis_mock.get.return_value = b"session-123"
    redis_mock.exists.return_value = 0  # Not blacklisted
    redis_mock.ttl.return_value = 3600  # 1 hour TTL
    redis_mock.scan.return_value = (0, [])  # Empty scan result
    return redis_mock


@pytest.fixture
def user_context():
    """Sample user context for testing"""
    return UserContext(
        user_id="test-user-123",
        email="test@example.com",
        roles=[UserRole.ADMIN],
        permissions=get_permissions_for_roles([UserRole.ADMIN]),
        hotel_ids=["hotel-1", "hotel-2"],
        session_id="session-123",
        expires_at=datetime.utcnow() + timedelta(minutes=15)
    )


@pytest.fixture
def jwt_service(mock_redis):
    """JWT service instance for testing"""
    return JWTService(redis_client=mock_redis, secret_key="test-secret")


class TestJWTServiceInitialization:
    """Test JWT service initialization"""

    def test_init_with_secret_key(self, mock_redis):
        """Test initialization with provided secret key"""
        jwt_service = JWTService(redis_client=mock_redis, secret_key="test-secret")

        assert jwt_service.redis_client == mock_redis
        assert jwt_service.algorithm == "RS256"
        assert jwt_service.private_key == "test-secret"
        assert jwt_service.public_key == "test-secret"
        assert jwt_service.access_token_expire_minutes == 15
        assert jwt_service.refresh_token_expire_days == 7
        assert jwt_service.session_expire_hours == 24

    @patch('cryptography.hazmat.primitives.asymmetric.rsa.generate_private_key')
    def test_init_without_secret_key(self, mock_generate_key, mock_redis):
        """Test initialization with auto-generated RSA key pair"""
        # Mock RSA key generation
        mock_private_key = MagicMock()
        mock_public_key = MagicMock()
        mock_private_key.public_key.return_value = mock_public_key
        mock_private_key.private_bytes.return_value = b"mock-private-key"
        mock_public_key.public_bytes.return_value = b"mock-public-key"
        mock_generate_key.return_value = mock_private_key

        jwt_service = JWTService(redis_client=mock_redis)

        assert jwt_service.private_key == b"mock-private-key"
        assert jwt_service.public_key == b"mock-public-key"
        mock_generate_key.assert_called_once_with(public_exponent=65537, key_size=2048)


class TestTokenCreation:
    """Test JWT token creation functionality"""

    @pytest.mark.asyncio
    async def test_create_tokens_success(self, jwt_service, user_context, mock_redis):
        """Test successful token creation"""
        with patch('uuid.uuid4') as mock_uuid, \
             patch('jwt.encode') as mock_jwt_encode:

            # Mock UUID generation
            mock_uuid.side_effect = ["session-123", "access-jti-123", "refresh-jti-123"]
            mock_jwt_encode.side_effect = ["access-token-123", "refresh-token-123"]

            result = await jwt_service.create_tokens(user_context)

            # Verify token structure
            assert result["access_token"] == "access-token-123"
            assert result["refresh_token"] == "refresh-token-123"
            assert result["token_type"] == "bearer"
            assert result["expires_in"] == 900  # 15 minutes
            assert result["session_id"] == "session-123"

            # Verify Redis operations
            mock_redis.hset.assert_called_once()
            mock_redis.expire.assert_called_once()
            mock_redis.set.assert_called_once()

            # Verify JWT encoding calls
            assert mock_jwt_encode.call_count == 2

    @pytest.mark.asyncio
    async def test_create_tokens_redis_error(self, jwt_service, user_context, mock_redis):
        """Test token creation with Redis error"""
        mock_redis.hset.side_effect = Exception("Redis connection error")

        with pytest.raises(Exception, match="Redis connection error"):
            await jwt_service.create_tokens(user_context)


class TestTokenValidation:
    """Test JWT token validation functionality"""

    @pytest.mark.asyncio
    async def test_validate_token_success(self, jwt_service, mock_redis):
        """Test successful token validation"""
        mock_payload = {
            "sub": "test-user-123",
            "email": "test@example.com",
            "roles": ["admin"],
            "permissions": ["read", "write"],
            "hotel_ids": ["hotel-1", "hotel-2"],
            "exp": int((datetime.utcnow() + timedelta(minutes=15)).timestamp()),
            "jti": "access-jti-123",
            "session_id": "session-123"
        }

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            result = await jwt_service.validate_token("valid-token")

            assert isinstance(result, UserContext)
            assert result.user_id == "test-user-123"
            assert result.email == "test@example.com"
            assert UserRole.ADMIN in result.roles
            assert result.session_id == "session-123"

            # Verify Redis operations
            mock_redis.exists.assert_called_once_with("blacklist:access-jti-123")
            mock_redis.hgetall.assert_called_once_with("session:session-123")
            mock_redis.hset.assert_called_once()  # Update last activity

    @pytest.mark.asyncio
    async def test_validate_token_expired(self, jwt_service, mock_redis):
        """Test validation of expired token"""
        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.side_effect = pyjwt.ExpiredSignatureError("Token expired")

            with pytest.raises(AuthenticationError, match="Token has expired"):
                await jwt_service.validate_token("expired-token")

    @pytest.mark.asyncio
    async def test_validate_token_blacklisted(self, jwt_service, mock_redis):
        """Test validation of blacklisted token"""
        mock_payload = {
            "sub": "test-user-123",
            "jti": "blacklisted-jti",
            "session_id": "session-123"
        }

        mock_redis.exists.return_value = 1  # Token is blacklisted

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            with pytest.raises(AuthenticationError, match="Token has been revoked"):
                await jwt_service.validate_token("blacklisted-token")

    @pytest.mark.asyncio
    async def test_validate_token_session_not_found(self, jwt_service, mock_redis):
        """Test validation when session doesn't exist"""
        mock_payload = {
            "sub": "test-user-123",
            "jti": "access-jti-123",
            "session_id": "nonexistent-session"
        }

        mock_redis.exists.return_value = 0  # Not blacklisted
        mock_redis.hgetall.return_value = {}  # Session not found

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            with pytest.raises(AuthenticationError, match="Session not found or expired"):
                await jwt_service.validate_token("token-with-invalid-session")

    @pytest.mark.asyncio
    async def test_validate_token_invalid_format(self, jwt_service, mock_redis):
        """Test validation of malformed token"""
        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.side_effect = pyjwt.InvalidTokenError("Invalid token format")

            with pytest.raises(AuthenticationError, match="Invalid token"):
                await jwt_service.validate_token("malformed-token")


class TestTokenRefresh:
    """Test JWT token refresh functionality"""

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, jwt_service, mock_redis):
        """Test successful token refresh"""
        mock_refresh_payload = {
            "sub": "test-user-123",
            "session_id": "session-123",
            "type": "refresh",
            "exp": int((datetime.utcnow() + timedelta(days=7)).timestamp()),
            "jti": "refresh-jti-123"
        }

        with patch('jwt.decode') as mock_jwt_decode, \
             patch('jwt.encode') as mock_jwt_encode, \
             patch('uuid.uuid4') as mock_uuid:

            mock_jwt_decode.return_value = mock_refresh_payload
            mock_jwt_encode.return_value = "new-access-token"
            mock_uuid.return_value = "new-access-jti"

            result = await jwt_service.refresh_token("valid-refresh-token")

            assert result["access_token"] == "new-access-token"
            assert result["token_type"] == "bearer"
            assert result["expires_in"] == 900  # 15 minutes

            # Verify Redis operations
            mock_redis.get.assert_called_once_with("refresh_token:refresh-jti-123")
            mock_redis.hgetall.assert_called_once_with("session:session-123")

    @pytest.mark.asyncio
    async def test_refresh_token_wrong_type(self, jwt_service, mock_redis):
        """Test refresh with wrong token type"""
        mock_payload = {
            "sub": "test-user-123",
            "type": "access",  # Wrong type
            "jti": "access-jti-123"
        }

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            with pytest.raises(AuthenticationError, match="Invalid token type"):
                await jwt_service.refresh_token("access-token-as-refresh")

    @pytest.mark.asyncio
    async def test_refresh_token_not_found(self, jwt_service, mock_redis):
        """Test refresh when refresh token is not found"""
        mock_payload = {
            "sub": "test-user-123",
            "type": "refresh",
            "jti": "nonexistent-refresh-jti"
        }

        mock_redis.get.return_value = None  # Refresh token not found

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            with pytest.raises(AuthenticationError, match="Refresh token not found or expired"):
                await jwt_service.refresh_token("nonexistent-refresh-token")

    @pytest.mark.asyncio
    async def test_refresh_token_expired(self, jwt_service, mock_redis):
        """Test refresh with expired refresh token"""
        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.side_effect = pyjwt.ExpiredSignatureError("Refresh token expired")

            with pytest.raises(AuthenticationError, match="Refresh token has expired"):
                await jwt_service.refresh_token("expired-refresh-token")


class TestTokenRevocation:
    """Test JWT token revocation functionality"""

    @pytest.mark.asyncio
    async def test_revoke_token_success(self, jwt_service, mock_redis):
        """Test successful token revocation"""
        mock_payload = {
            "sub": "test-user-123",
            "jti": "token-to-revoke",
            "exp": int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
        }

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            await jwt_service.revoke_token("token-to-revoke")

            # Verify token was added to blacklist
            mock_redis.set.assert_called_once()
            call_args = mock_redis.set.call_args
            assert call_args[0][0] == "blacklist:token-to-revoke"
            assert call_args[0][1] == "1"
            assert "ex" in call_args[1]  # TTL was set

    @pytest.mark.asyncio
    async def test_revoke_token_already_expired(self, jwt_service, mock_redis):
        """Test revoking an already expired token"""
        mock_payload = {
            "sub": "test-user-123",
            "jti": "expired-token",
            "exp": int((datetime.utcnow() - timedelta(minutes=10)).timestamp())  # Already expired
        }

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            await jwt_service.revoke_token("expired-token")

            # Should not add to blacklist since already expired
            mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_token_decode_error(self, jwt_service, mock_redis):
        """Test token revocation with decode error"""
        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.side_effect = pyjwt.InvalidTokenError("Invalid token")

            with pytest.raises(AuthenticationError, match="Token revocation failed"):
                await jwt_service.revoke_token("invalid-token")


class TestSessionManagement:
    """Test session management functionality"""

    @pytest.mark.asyncio
    async def test_logout_session_success(self, jwt_service, mock_redis):
        """Test successful session logout"""
        await jwt_service.logout_session("session-123")

        # Verify Redis operations
        mock_redis.hgetall.assert_called_once_with("session:session-123")
        mock_redis.delete.assert_called_with("refresh_token:refresh-jti-123")
        mock_redis.delete.assert_called_with("session:session-123")

    @pytest.mark.asyncio
    async def test_logout_session_not_found(self, jwt_service, mock_redis):
        """Test logout of non-existent session"""
        mock_redis.hgetall.return_value = {}  # Session not found

        await jwt_service.logout_session("nonexistent-session")

        # Should still try to delete session
        mock_redis.delete.assert_called_with("session:nonexistent-session")

    @pytest.mark.asyncio
    async def test_logout_all_sessions_success(self, jwt_service, mock_redis):
        """Test logging out all sessions for a user"""
        # Mock scan results
        mock_redis.scan.side_effect = [
            (1, [b"session:session-1", b"session:session-2"]),
            (0, [b"session:session-3"])  # Last batch
        ]

        # Mock session data for user
        def mock_hgetall(key):
            if key == b"session:session-1":
                return {b"user_id": b"test-user-123"}
            elif key == b"session:session-2":
                return {b"user_id": b"other-user-456"}  # Different user
            elif key == b"session:session-3":
                return {b"user_id": b"test-user-123"}
            return {}

        mock_redis.hgetall.side_effect = mock_hgetall

        await jwt_service.logout_all_sessions("test-user-123")

        # Should scan for sessions and logout matching ones
        assert mock_redis.scan.call_count == 2
        # Should check session data for each found session
        assert mock_redis.hgetall.call_count >= 3

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, jwt_service, mock_redis):
        """Test cleanup of expired sessions"""
        # Mock scan results
        mock_redis.scan.side_effect = [
            (1, [b"session:session-1", b"session:session-2"]),
            (0, [])  # Last batch is empty
        ]

        # Mock TTL responses
        def mock_ttl(key):
            if key == b"session:session-1":
                return 3600  # Still active
            elif key == b"session:session-2":
                return -2  # Expired (doesn't exist)
            return -1

        mock_redis.ttl.side_effect = mock_ttl

        result = await jwt_service.cleanup_expired_sessions()

        assert result == 1  # One expired session found
        assert mock_redis.scan.call_count == 2
        assert mock_redis.ttl.call_count == 2


class TestErrorHandling:
    """Test error handling scenarios"""

    @pytest.mark.asyncio
    async def test_redis_connection_error_on_validation(self, jwt_service, mock_redis):
        """Test token validation with Redis connection error"""
        mock_payload = {
            "sub": "test-user-123",
            "jti": "access-jti-123",
            "session_id": "session-123"
        }

        mock_redis.exists.side_effect = Exception("Redis connection failed")

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            with pytest.raises(AuthenticationError, match="Token validation failed"):
                await jwt_service.validate_token("token-with-redis-error")

    @pytest.mark.asyncio
    async def test_redis_connection_error_on_refresh(self, jwt_service, mock_redis):
        """Test token refresh with Redis connection error"""
        mock_payload = {
            "sub": "test-user-123",
            "type": "refresh",
            "jti": "refresh-jti-123"
        }

        mock_redis.get.side_effect = Exception("Redis connection failed")

        with patch('jwt.decode') as mock_jwt_decode:
            mock_jwt_decode.return_value = mock_payload

            with pytest.raises(AuthenticationError, match="Token refresh failed"):
                await jwt_service.refresh_token("refresh-token-with-redis-error")


if __name__ == "__main__":
    pytest.main([__file__])