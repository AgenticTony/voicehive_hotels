"""
User service for managing user authentication and operations
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.repository import UserRepository, SessionRepository
from database.models import User, UserSession
from database.connection import get_db_session
from auth_models import UserRole, Permission, UserContext
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.user_service")


class UserService:
    """Service for user management operations"""

    def __init__(self, db_session: AsyncSession):
        self.user_repo = UserRepository(db_session)
        self.session_repo = SessionRepository(db_session)

    async def authenticate_user(self, email: str, password: str) -> Optional[UserContext]:
        """
        Authenticate user and return UserContext if successful
        This replaces the MOCK_USERS authentication
        """
        try:
            # Authenticate with database
            user = await self.user_repo.authenticate_user(email, password)
            if not user:
                return None

            # Convert to UserContext for compatibility with existing code
            return self._user_to_context(user)

        except Exception as e:
            logger.error("authenticate_user_failed", email=email, error=str(e))
            return None

    def _user_to_context(self, user: User, session_id: Optional[str] = None) -> UserContext:
        """Convert User model to UserContext"""
        # Get permissions from roles
        permissions = []
        for role in user.roles:
            permissions.extend([Permission(perm) for perm in role.permissions])

        # Remove duplicates while preserving order
        seen = set()
        unique_permissions = []
        for perm in permissions:
            if perm not in seen:
                seen.add(perm)
                unique_permissions.append(perm)

        # Get role names
        role_names = [UserRole(role.name) for role in user.roles]

        # Get hotel IDs
        hotel_ids = [hotel.id for hotel in user.hotels] if user.hotels else None

        return UserContext(
            user_id=str(user.id),
            email=user.email,
            roles=role_names,
            permissions=unique_permissions,
            session_id=session_id or f"session_{user.id}",
            expires_at=None,  # Will be set by JWT service
            hotel_ids=hotel_ids
        )

    async def create_user(
        self,
        email: str,
        password: str,
        roles: List[UserRole],
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        hotel_ids: Optional[List[str]] = None,
        created_by: Optional[UUID] = None,
        email_verified: bool = False
    ) -> UserContext:
        """Create a new user"""
        try:
            user = await self.user_repo.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                roles=roles,
                hotel_ids=hotel_ids,
                created_by=created_by,
                email_verified=email_verified
            )

            logger.info(
                "user_created",
                user_id=str(user.id),
                email=user.email,
                roles=[role.name for role in user.roles]
            )

            return self._user_to_context(user)

        except Exception as e:
            logger.error("create_user_failed", email=email, error=str(e))
            raise

    async def get_user_by_email(self, email: str) -> Optional[UserContext]:
        """Get user by email"""
        try:
            user = await self.user_repo.get_user_by_email(email)
            if not user:
                return None

            return self._user_to_context(user)

        except Exception as e:
            logger.error("get_user_by_email_failed", email=email, error=str(e))
            return None

    async def get_user_by_id(self, user_id: str) -> Optional[UserContext]:
        """Get user by ID"""
        try:
            user = await self.user_repo.get_user_by_id(UUID(user_id))
            if not user:
                return None

            return self._user_to_context(user)

        except Exception as e:
            logger.error("get_user_by_id_failed", user_id=user_id, error=str(e))
            return None

    async def update_user(
        self,
        user_id: str,
        updates: Dict[str, Any],
        updated_by: Optional[str] = None
    ) -> Optional[UserContext]:
        """Update user"""
        try:
            updated_by_uuid = UUID(updated_by) if updated_by else None
            user = await self.user_repo.update_user(
                UUID(user_id),
                updates,
                updated_by_uuid
            )

            if not user:
                return None

            logger.info("user_updated", user_id=user_id, updates=list(updates.keys()))
            return self._user_to_context(user)

        except Exception as e:
            logger.error("update_user_failed", user_id=user_id, error=str(e))
            raise

    async def change_password(
        self,
        user_id: str,
        new_password: str,
        updated_by: Optional[str] = None
    ) -> bool:
        """Change user password"""
        try:
            updated_by_uuid = UUID(updated_by) if updated_by else None
            success = await self.user_repo.change_password(
                UUID(user_id),
                new_password,
                updated_by_uuid
            )

            if success:
                logger.info("password_changed", user_id=user_id)

            return success

        except Exception as e:
            logger.error("change_password_failed", user_id=user_id, error=str(e))
            raise

    async def delete_user(self, user_id: str) -> bool:
        """Delete (deactivate) user"""
        try:
            success = await self.user_repo.delete_user(UUID(user_id))

            if success:
                logger.info("user_deleted", user_id=user_id)

            return success

        except Exception as e:
            logger.error("delete_user_failed", user_id=user_id, error=str(e))
            raise

    async def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
        active_only: bool = True,
        hotel_id: Optional[str] = None
    ) -> List[UserContext]:
        """List users"""
        try:
            users = await self.user_repo.list_users(
                limit=limit,
                offset=offset,
                active_only=active_only,
                hotel_id=hotel_id
            )

            return [self._user_to_context(user) for user in users]

        except Exception as e:
            logger.error("list_users_failed", error=str(e))
            raise

    async def create_session(
        self,
        user_id: str,
        session_id: str,
        access_token_jti: str,
        refresh_token_jti: Optional[str],
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_fingerprint: Optional[str] = None
    ) -> UserSession:
        """Create user session"""
        try:
            session = await self.session_repo.create_session(
                user_id=UUID(user_id),
                session_id=session_id,
                access_token_jti=access_token_jti,
                refresh_token_jti=refresh_token_jti,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent,
                device_fingerprint=device_fingerprint
            )

            logger.info("session_created", user_id=user_id, session_id=session_id)
            return session

        except Exception as e:
            logger.error("create_session_failed", user_id=user_id, error=str(e))
            raise

    async def validate_session(self, jti: str) -> Optional[UserContext]:
        """Validate session by JWT ID"""
        try:
            session = await self.session_repo.get_session_by_jti(jti)
            if not session or not session.is_valid():
                return None

            # Touch session to update last accessed time
            session.touch()

            return self._user_to_context(session.user, session.session_id)

        except Exception as e:
            logger.error("validate_session_failed", jti=jti, error=str(e))
            return None

    async def revoke_session(self, session_id: str, reason: str = "manual") -> bool:
        """Revoke a session"""
        try:
            success = await self.session_repo.revoke_session(session_id, reason)

            if success:
                logger.info("session_revoked", session_id=session_id, reason=reason)

            return success

        except Exception as e:
            logger.error("revoke_session_failed", session_id=session_id, error=str(e))
            raise

    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions"""
        try:
            count = await self.session_repo.cleanup_expired_sessions()
            if count > 0:
                logger.info("expired_sessions_cleaned", count=count)
            return count

        except Exception as e:
            logger.error("cleanup_expired_sessions_failed", error=str(e))
            raise


# Migration helpers for transitioning from mock users
async def migrate_mock_users_to_database():
    """
    Migrate the existing MOCK_USERS to the database
    This should be run once during deployment
    """
    from database.connection import get_db_session

    # Import the mock users from the old implementation
    MOCK_USERS = {
        "admin@voicehive-hotels.eu": {
            "user_id": "admin-001",
            "email": "admin@voicehive-hotels.eu",
            "password": "admin123",  # Will be hashed
            "roles": [UserRole.SYSTEM_ADMIN],
            "hotel_ids": None,
            "active": True
        },
        "operator@voicehive-hotels.eu": {
            "user_id": "operator-001",
            "email": "operator@voicehive-hotels.eu",
            "password": "operator123",
            "roles": [UserRole.HOTEL_ADMIN],
            "hotel_ids": None,
            "active": True
        },
        "manager@hotel1.com": {
            "user_id": "manager-001",
            "email": "manager@hotel1.com",
            "password": "manager123",
            "roles": [UserRole.HOTEL_STAFF],
            "hotel_ids": ["hotel-001"],
            "active": True
        }
    }

    try:
        async with get_db_session() as session:
            user_service = UserService(session)

            logger.info("starting_mock_user_migration", count=len(MOCK_USERS))

            for email, user_data in MOCK_USERS.items():
                try:
                    # Check if user already exists
                    existing_user = await user_service.get_user_by_email(email)
                    if existing_user:
                        logger.info("user_already_exists_skipping", email=email)
                        continue

                    # Create user
                    user_context = await user_service.create_user(
                        email=user_data["email"],
                        password=user_data["password"],
                        roles=user_data["roles"],
                        hotel_ids=user_data.get("hotel_ids"),
                        email_verified=True  # Mark as verified for migration
                    )

                    logger.info("mock_user_migrated", email=email, user_id=user_context.user_id)

                except Exception as e:
                    logger.error("mock_user_migration_failed", email=email, error=str(e))
                    # Continue with other users

            logger.info("mock_user_migration_completed")

    except Exception as e:
        logger.error("mock_user_migration_error", error=str(e))
        raise


# Dependency injection function for FastAPI
async def get_user_service(db_session: AsyncSession = None) -> UserService:
    """Get UserService instance for dependency injection"""
    if db_session is None:
        # This should not happen in normal usage, but provides a fallback
        from database.connection import get_db_session
        async with get_db_session() as session:
            return UserService(session)

    return UserService(db_session)