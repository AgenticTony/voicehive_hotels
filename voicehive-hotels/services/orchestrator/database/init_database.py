"""
Database initialization script for VoiceHive Hotels
Creates tables and migrates mock users to PostgreSQL
"""

import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from database.models import Base
from database.connection import db_manager, initialize_database
from user_service import migrate_mock_users_to_database
from config import get_config
from logging_adapter import get_safe_logger

logger = get_safe_logger("orchestrator.database.init")


async def create_database_if_not_exists():
    """Create the database if it doesn't exist"""
    config = get_config()
    db_config = config.database

    # Connect to postgres database to create the target database
    postgres_url = (
        f"postgresql+asyncpg://"
        f"{db_config.username}:{db_config.password}@"
        f"{db_config.host}:{db_config.port}/postgres"
    )

    if db_config.ssl_mode != "disable":
        postgres_url += f"?sslmode={db_config.ssl_mode}"

    try:
        engine = create_async_engine(postgres_url)

        async with engine.begin() as conn:
            # Check if database exists
            result = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": db_config.database}
            )

            if not result.fetchone():
                # Create database
                await conn.execute(text("COMMIT"))  # End transaction
                await conn.execute(
                    text(f"CREATE DATABASE {db_config.database}")
                )
                logger.info("database_created", database=db_config.database)
            else:
                logger.info("database_already_exists", database=db_config.database)

        await engine.dispose()

    except Exception as e:
        logger.error("create_database_failed", database=db_config.database, error=str(e))
        raise


async def create_tables():
    """Create all database tables"""
    try:
        # Initialize database connection
        await initialize_database()

        # Create all tables
        async with db_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("database_tables_created")

    except Exception as e:
        logger.error("create_tables_failed", error=str(e))
        raise


async def create_extensions():
    """Create required PostgreSQL extensions"""
    try:
        async with db_manager.get_session() as session:
            # Create UUID extension for UUID generation
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))

            # Create pgcrypto extension for advanced encryption functions
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS \"pgcrypto\""))

            await session.commit()

        logger.info("database_extensions_created")

    except Exception as e:
        logger.error("create_extensions_failed", error=str(e))
        raise


async def create_indexes():
    """Create additional indexes for performance"""
    try:
        async with db_manager.get_session() as session:
            # Additional indexes for performance
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_users_email_active ON users(email) WHERE active = true",
                "CREATE INDEX IF NOT EXISTS idx_users_last_login ON users(last_login_at) WHERE last_login_at IS NOT NULL",
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_active ON user_sessions(user_id, active) WHERE active = true",
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at) WHERE active = true",
                "CREATE INDEX IF NOT EXISTS idx_user_roles_user_id ON user_roles(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_hotels_user_id ON user_hotels(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_roles_active ON roles(name) WHERE active = true",
            ]

            for index_sql in indexes:
                await session.execute(text(index_sql))

            await session.commit()

        logger.info("database_indexes_created")

    except Exception as e:
        logger.error("create_indexes_failed", error=str(e))
        raise


async def setup_database_security():
    """Set up database-level security"""
    try:
        async with db_manager.get_session() as session:
            # Enable row level security on sensitive tables
            security_settings = [
                "ALTER TABLE users ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY",

                # Create policies for user data access
                """
                CREATE POLICY user_own_data ON users
                FOR SELECT
                TO voicehive_app
                USING (id = current_setting('app.current_user_id')::uuid)
                """,

                """
                CREATE POLICY user_own_sessions ON user_sessions
                FOR ALL
                TO voicehive_app
                USING (user_id = current_setting('app.current_user_id')::uuid)
                """,
            ]

            for sql in security_settings:
                try:
                    await session.execute(text(sql))
                except Exception as e:
                    # Some policies might already exist, log but continue
                    logger.warning("security_setting_skipped", sql=sql[:50], error=str(e))

            await session.commit()

        logger.info("database_security_configured")

    except Exception as e:
        logger.error("setup_database_security_failed", error=str(e))
        # Don't raise - security is optional for basic functionality


async def verify_database_setup():
    """Verify that the database is properly set up"""
    try:
        async with db_manager.get_session() as session:
            # Test basic operations
            test_queries = [
                "SELECT COUNT(*) FROM users",
                "SELECT COUNT(*) FROM roles",
                "SELECT COUNT(*) FROM hotels",
                "SELECT COUNT(*) FROM user_sessions",
            ]

            for query in test_queries:
                result = await session.execute(text(query))
                count = result.scalar()
                logger.info("table_verified", query=query, count=count)

        logger.info("database_verification_completed")
        return True

    except Exception as e:
        logger.error("database_verification_failed", error=str(e))
        return False


async def initialize_production_database(
    create_db: bool = False,
    migrate_users: bool = True,
    skip_security: bool = False
):
    """
    Complete database initialization for production

    Args:
        create_db: Create the database if it doesn't exist
        migrate_users: Migrate mock users to database
        skip_security: Skip security setup (for development)
    """
    try:
        logger.info("starting_database_initialization")

        # Step 1: Create database if needed
        if create_db:
            await create_database_if_not_exists()

        # Step 2: Initialize connection
        await initialize_database()

        # Step 3: Create extensions
        await create_extensions()

        # Step 4: Create tables
        await create_tables()

        # Step 5: Create performance indexes
        await create_indexes()

        # Step 6: Set up security (optional)
        if not skip_security:
            await setup_database_security()

        # Step 7: Migrate mock users
        if migrate_users:
            await migrate_mock_users_to_database()

        # Step 8: Verify setup
        success = await verify_database_setup()

        if success:
            logger.info("database_initialization_completed_successfully")
        else:
            logger.error("database_initialization_verification_failed")
            raise Exception("Database verification failed")

    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))
        raise


async def reset_database():
    """Reset database by dropping and recreating all tables (DANGEROUS)"""
    logger.warning("resetting_database_all_data_will_be_lost")

    try:
        await initialize_database()

        async with db_manager.engine.begin() as conn:
            # Drop all tables
            await conn.run_sync(Base.metadata.drop_all)
            logger.info("all_tables_dropped")

            # Recreate all tables
            await conn.run_sync(Base.metadata.create_all)
            logger.info("all_tables_recreated")

        # Recreate indexes and migrate users
        await create_indexes()
        await migrate_mock_users_to_database()

        logger.info("database_reset_completed")

    except Exception as e:
        logger.error("database_reset_failed", error=str(e))
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Initialize VoiceHive Hotels database")
    parser.add_argument("--create-db", action="store_true", help="Create database if it doesn't exist")
    parser.add_argument("--skip-users", action="store_true", help="Skip user migration")
    parser.add_argument("--skip-security", action="store_true", help="Skip security setup")
    parser.add_argument("--reset", action="store_true", help="Reset database (DANGEROUS)")

    args = parser.parse_args()

    async def main():
        if args.reset:
            await reset_database()
        else:
            await initialize_production_database(
                create_db=args.create_db,
                migrate_users=not args.skip_users,
                skip_security=args.skip_security
            )

    asyncio.run(main())