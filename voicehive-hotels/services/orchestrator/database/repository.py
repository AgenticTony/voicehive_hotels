"""
User repository for database operations
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, update, delete
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.exc import IntegrityError, NoResultFound

from database.models import User, Role, Hotel, UserSession
from auth_models import UserRole, Permission, UserContext
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.database.repository")


class UserRepository:
    """Repository for user database operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(
        self,
        email: str,
        password: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        roles: Optional[List[UserRole]] = None,
        hotel_ids: Optional[List[str]] = None,
        created_by: Optional[UUID] = None,
        email_verified: bool = False
    ) -> User:
        """Create a new user"""
        try:
            # Create user
            user = User(
                email=email.lower().strip(),
                first_name=first_name,
                last_name=last_name,
                email_verified=email_verified,
                created_by=created_by,
                updated_by=created_by
            )
            user.set_password(password)

            self.session.add(user)
            await self.session.flush()  # Get user ID

            # Assign roles
            if roles:
                await self._assign_roles_to_user(user.id, roles, created_by)

            # Assign hotels
            if hotel_ids:
                await self._assign_hotels_to_user(user.id, hotel_ids, created_by)

            await self.session.commit()

            # Reload with relationships
            return await self.get_user_by_id(user.id)

        except IntegrityError as e:
            await self.session.rollback()
            if "email" in str(e):
                raise ValueError(f"User with email {email} already exists")
            raise ValueError(f"Database integrity error: {str(e)}")

        except Exception as e:
            await self.session.rollback()
            logger.error("user_creation_failed", email=email, error=str(e))
            raise

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email with all relationships loaded"""
        try:
            stmt = (
                select(User)
                .options(
                    selectinload(User.roles),
                    selectinload(User.hotels),
                    selectinload(User.sessions)
                )
                .where(User.email == email.lower().strip())
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error("get_user_by_email_failed", email=email, error=str(e))
            raise

    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID with all relationships loaded"""
        try:
            stmt = (
                select(User)
                .options(
                    selectinload(User.roles),
                    selectinload(User.hotels),
                    selectinload(User.sessions)
                )
                .where(User.id == user_id)
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error("get_user_by_id_failed", user_id=str(user_id), error=str(e))
            raise

    async def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate user and return user object if successful"""
        try:
            user = await self.get_user_by_email(email)
            if not user:
                logger.warning("authentication_failed_user_not_found", email=email)
                return None

            # Check if user can login
            if not user.can_login():
                logger.warning(
                    "authentication_failed_user_cannot_login",
                    email=email,
                    active=user.active,
                    email_verified=user.email_verified,
                    locked=user.is_locked()
                )
                return None

            # Verify password
            if not user.verify_password(password):
                # Increment failed login attempts
                await self._handle_failed_login(user)
                logger.warning("authentication_failed_invalid_password", email=email)
                return None

            # Successful login - reset failed attempts and update last login
            await self._handle_successful_login(user)

            logger.info("user_authenticated_successfully", email=email, user_id=str(user.id))
            return user

        except Exception as e:
            logger.error("authentication_error", email=email, error=str(e))
            raise

    async def _handle_failed_login(self, user: User) -> None:
        """Handle failed login attempt"""
        user.failed_login_attempts += 1

        # Lock account after 5 failed attempts for 15 minutes
        if user.failed_login_attempts >= 5:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            logger.warning(
                "user_account_locked",
                email=user.email,
                failed_attempts=user.failed_login_attempts
            )

        user.updated_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def _handle_successful_login(self, user: User) -> None:
        """Handle successful login"""
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def update_user(
        self,
        user_id: UUID,
        updates: Dict[str, Any],
        updated_by: Optional[UUID] = None
    ) -> Optional[User]:
        """Update user fields"""
        try:
            user = await self.get_user_by_id(user_id)
            if not user:
                return None

            # Update allowed fields
            allowed_fields = {
                'first_name', 'last_name', 'active', 'email_verified'
            }

            for field, value in updates.items():
                if field in allowed_fields and hasattr(user, field):
                    setattr(user, field, value)

            user.updated_by = updated_by
            user.updated_at = datetime.now(timezone.utc)

            await self.session.commit()
            return await self.get_user_by_id(user_id)

        except Exception as e:
            await self.session.rollback()
            logger.error("update_user_failed", user_id=str(user_id), error=str(e))
            raise

    async def change_password(
        self,
        user_id: UUID,
        new_password: str,
        updated_by: Optional[UUID] = None
    ) -> bool:
        """Change user password"""
        try:
            user = await self.get_user_by_id(user_id)
            if not user:
                return False

            user.set_password(new_password)
            user.updated_by = updated_by
            user.updated_at = datetime.now(timezone.utc)

            await self.session.commit()

            logger.info("password_changed", user_id=str(user_id))
            return True

        except Exception as e:
            await self.session.rollback()
            logger.error("change_password_failed", user_id=str(user_id), error=str(e))
            raise

    async def delete_user(self, user_id: UUID) -> bool:
        """Soft delete user (set active=False)"""
        try:
            user = await self.get_user_by_id(user_id)
            if not user:
                return False

            user.active = False
            user.updated_at = datetime.now(timezone.utc)

            # Revoke all active sessions
            await self._revoke_user_sessions(user_id, "user_deleted")

            await self.session.commit()

            logger.info("user_deleted", user_id=str(user_id), email=user.email)
            return True

        except Exception as e:
            await self.session.rollback()
            logger.error("delete_user_failed", user_id=str(user_id), error=str(e))
            raise

    async def list_users(
        self,
        limit: int = 100,
        offset: int = 0,
        active_only: bool = True,
        hotel_id: Optional[str] = None
    ) -> List[User]:
        """List users with pagination and filtering"""
        try:
            stmt = (
                select(User)
                .options(
                    selectinload(User.roles),
                    selectinload(User.hotels)
                )
                .limit(limit)
                .offset(offset)
                .order_by(User.created_at.desc())
            )

            if active_only:
                stmt = stmt.where(User.active == True)

            if hotel_id:
                stmt = stmt.join(User.hotels).where(Hotel.id == hotel_id)

            result = await self.session.execute(stmt)
            return result.scalars().all()

        except Exception as e:
            logger.error("list_users_failed", error=str(e))
            raise

    async def _assign_roles_to_user(
        self,
        user_id: UUID,
        role_names: List[UserRole],
        assigned_by: Optional[UUID] = None
    ) -> None:
        """Assign roles to user"""
        for role_name in role_names:
            role = await self._get_or_create_role(role_name)

            # Check if user already has this role
            stmt = select(User).where(User.id == user_id).options(selectinload(User.roles))
            result = await self.session.execute(stmt)
            user = result.scalar_one()

            if role not in user.roles:
                user.roles.append(role)

    async def _assign_hotels_to_user(
        self,
        user_id: UUID,
        hotel_ids: List[str],
        assigned_by: Optional[UUID] = None
    ) -> None:
        """Assign hotels to user"""
        for hotel_id in hotel_ids:
            hotel = await self._get_or_create_hotel(hotel_id)

            # Check if user already assigned to this hotel
            stmt = select(User).where(User.id == user_id).options(selectinload(User.hotels))
            result = await self.session.execute(stmt)
            user = result.scalar_one()

            if hotel not in user.hotels:
                user.hotels.append(hotel)

    async def _get_or_create_role(self, role_name: UserRole) -> Role:
        """Get existing role or create new one"""
        stmt = select(Role).where(Role.name == role_name.value)
        result = await self.session.execute(stmt)
        role = result.scalar_one_or_none()

        if not role:
            # Import here to avoid circular imports
            from auth_models import ROLE_PERMISSIONS

            role = Role(
                name=role_name.value,
                display_name=role_name.value.replace('_', ' ').title(),
                permissions=[perm.value for perm in ROLE_PERMISSIONS.get(role_name, [])],
                description=f"Auto-created role for {role_name.value}"
            )
            self.session.add(role)
            await self.session.flush()

        return role

    async def _get_or_create_hotel(self, hotel_id: str) -> Hotel:
        """Get existing hotel or create placeholder"""
        stmt = select(Hotel).where(Hotel.id == hotel_id)
        result = await self.session.execute(stmt)
        hotel = result.scalar_one_or_none()

        if not hotel:
            hotel = Hotel(
                id=hotel_id,
                name=f"Hotel {hotel_id}",
                pms_type="unknown",
                active=True
            )
            self.session.add(hotel)
            await self.session.flush()

        return hotel

    async def _revoke_user_sessions(self, user_id: UUID, reason: str) -> None:
        """Revoke all active sessions for a user"""
        stmt = (
            update(UserSession)
            .where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.active == True,
                    UserSession.revoked == False
                )
            )
            .values(
                revoked=True,
                revoked_at=datetime.now(timezone.utc),
                revoke_reason=reason
            )
        )
        await self.session.execute(stmt)


class SessionRepository:
    """Repository for user session operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(
        self,
        user_id: UUID,
        session_id: str,
        access_token_jti: str,
        refresh_token_jti: Optional[str],
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_fingerprint: Optional[str] = None
    ) -> UserSession:
        """Create a new user session"""
        try:
            session_obj = UserSession(
                session_id=session_id,
                user_id=user_id,
                access_token_jti=access_token_jti,
                refresh_token_jti=refresh_token_jti,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent,
                device_fingerprint=device_fingerprint
            )

            self.session.add(session_obj)
            await self.session.commit()

            logger.info(
                "session_created",
                user_id=str(user_id),
                session_id=session_id,
                expires_at=expires_at.isoformat()
            )

            return session_obj

        except Exception as e:
            await self.session.rollback()
            logger.error("create_session_failed", user_id=str(user_id), error=str(e))
            raise

    async def get_session_by_jti(self, jti: str) -> Optional[UserSession]:
        """Get session by JWT ID"""
        try:
            stmt = (
                select(UserSession)
                .options(joinedload(UserSession.user))
                .where(
                    or_(
                        UserSession.access_token_jti == jti,
                        UserSession.refresh_token_jti == jti
                    )
                )
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error("get_session_by_jti_failed", jti=jti, error=str(e))
            raise

    async def revoke_session(self, session_id: str, reason: str = "manual") -> bool:
        """Revoke a specific session"""
        try:
            stmt = (
                update(UserSession)
                .where(UserSession.session_id == session_id)
                .values(
                    revoked=True,
                    revoked_at=datetime.now(timezone.utc),
                    revoke_reason=reason
                )
            )
            result = await self.session.execute(stmt)
            await self.session.commit()

            if result.rowcount > 0:
                logger.info("session_revoked", session_id=session_id, reason=reason)
                return True
            return False

        except Exception as e:
            await self.session.rollback()
            logger.error("revoke_session_failed", session_id=session_id, error=str(e))
            raise

    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions"""
        try:
            now = datetime.now(timezone.utc)
            stmt = delete(UserSession).where(UserSession.expires_at < now)
            result = await self.session.execute(stmt)
            await self.session.commit()

            count = result.rowcount
            if count > 0:
                logger.info("expired_sessions_cleaned", count=count)

            return count

        except Exception as e:
            await self.session.rollback()
            logger.error("cleanup_expired_sessions_failed", error=str(e))
            raise