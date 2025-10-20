# User Database Migration Guide

## Overview

This document describes the migration from mock user storage to a production PostgreSQL database for the VoiceHive Hotels Orchestrator.

## What Changed

### Before (Mock Implementation)
- Users stored in `MOCK_USERS` dictionary in memory
- No persistence across restarts
- Hardcoded credentials
- No session management
- No audit trail

### After (Production Database)
- PostgreSQL database with proper tables
- Persistent user storage
- Secure password hashing with bcrypt
- Session management with JWT integration
- Audit logging
- Role-based access control
- Multi-tenant hotel support

## Database Schema

### Core Tables

1. **users** - User accounts and authentication
   - `id` (UUID) - Primary key
   - `email` (unique) - User email address
   - `password_hash` - Bcrypt hashed password
   - `first_name`, `last_name` - Profile information
   - `active`, `email_verified` - Status flags
   - `failed_login_attempts`, `locked_until` - Security
   - Timestamps and audit fields

2. **roles** - Role definitions
   - `id` (UUID) - Primary key
   - `name` - Role name (enum: SYSTEM_ADMIN, HOTEL_ADMIN, etc.)
   - `permissions` - Array of permission strings
   - `active` - Status flag

3. **hotels** - Hotel information
   - `id` (string) - External PMS hotel ID
   - `name`, `brand` - Hotel information
   - `pms_type` - PMS system type (apaleo, mews, etc.)
   - `pms_config` - JSON configuration

4. **user_sessions** - Session management
   - `id` (UUID) - Primary key
   - `session_id` - Session identifier
   - `user_id` - Foreign key to users
   - `access_token_jti`, `refresh_token_jti` - JWT identifiers
   - Session metadata and expiration

### Association Tables
- **user_roles** - Many-to-many user-role relationships
- **user_hotels** - Many-to-many user-hotel relationships

## Migration Process

### Automatic Migration

The migration happens automatically during application startup:

1. **Database Connection**: App connects to PostgreSQL
2. **Table Creation**: All tables created if not exist
3. **Mock User Migration**: Original mock users migrated to database
4. **Index Creation**: Performance indexes created
5. **Security Setup**: Row-level security policies (optional)

### Manual Migration

To run the migration manually:

```bash
# From the orchestrator directory
python -m database.init_database --create-db --skip-security

# With all options
python -m database.init_database \
    --create-db \
    --skip-users \
    --skip-security

# Reset database (DANGEROUS - deletes all data)
python -m database.init_database --reset
```

### Migration Options

- `--create-db`: Create the database if it doesn't exist
- `--skip-users`: Skip migrating mock users
- `--skip-security`: Skip row-level security setup
- `--reset`: Drop all tables and recreate (DANGEROUS)

## Migrated Users

The following users are automatically migrated from the mock implementation:

1. **admin@voicehive-hotels.eu**
   - Role: SYSTEM_ADMIN
   - Password: `admin123` (change immediately)
   - Access: All hotels

2. **operator@voicehive-hotels.eu**
   - Role: HOTEL_ADMIN
   - Password: `operator123` (change immediately)
   - Access: All hotels

3. **manager@hotel1.com**
   - Role: HOTEL_STAFF
   - Password: `manager123` (change immediately)
   - Access: hotel-001 only

**⚠️ SECURITY WARNING**: Change all default passwords immediately after deployment!

## API Changes

### Backward Compatibility

The authentication API endpoints remain the same:
- `POST /auth/login` - Unchanged
- `POST /auth/refresh` - Unchanged
- `POST /auth/logout` - Unchanged
- `GET /auth/me` - Unchanged

### New Features

- **Password Security**: Automatic account locking after 5 failed attempts
- **Session Management**: Database-tracked sessions with proper expiration
- **Audit Trail**: All authentication events logged
- **Multi-tenant**: Users can be assigned to specific hotels

## Configuration

### Database Configuration

Update your configuration to include database settings:

```yaml
database:
  host: localhost
  port: 5432
  database: voicehive_hotels
  username: voicehive_user
  password: secure_password
  ssl_mode: require  # prefer, require, verify-ca, verify-full
  pool_size: 10
  max_overflow: 20
```

### Environment Variables

```bash
# Database connection
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=voicehive_hotels
DATABASE_USER=voicehive_user
DATABASE_PASSWORD=secure_password
DATABASE_SSL_MODE=require

# Connection pooling
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
```

## Monitoring

### Health Checks

The `/healthz` endpoint now includes database connectivity:

```json
{
  "status": "healthy",
  "database": {
    "status": "healthy",
    "pool_stats": {
      "size": 10,
      "checked_in": 8,
      "checked_out": 2,
      "overflow": 0
    }
  }
}
```

### Metrics

New Prometheus metrics:
- `voicehive_database_connections_total`
- `voicehive_user_login_attempts_total`
- `voicehive_user_sessions_active`

### Logging

All database operations are logged with structured logging:

```json
{
  "event": "user_authenticated",
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "email": "user@example.com",
  "roles": ["HOTEL_STAFF"],
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Security Features

### Password Security
- Bcrypt hashing with salt
- Minimum 8 character passwords
- Password change tracking
- Failed attempt monitoring
- Account locking (15 minutes after 5 failures)

### Session Security
- JWT-based authentication
- Session tracking in database
- Automatic session cleanup
- IP address and user agent logging
- Device fingerprinting

### Database Security
- Row-level security policies
- Connection encryption (SSL)
- Parameterized queries (SQL injection prevention)
- Connection pooling with timeouts

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   ```
   Solution: Check database configuration and connectivity
   ```

2. **Tables Not Created**
   ```
   Solution: Ensure database user has CREATE privileges
   ```

3. **Migration Failed**
   ```
   Solution: Check logs for specific errors, run manual migration
   ```

4. **Authentication Not Working**
   ```
   Solution: Verify users were migrated, check password hashes
   ```

### Debug Commands

```bash
# Test database connection
python -c "from database.connection import get_database_health; import asyncio; print(asyncio.run(get_database_health()))"

# Check user count
python -c "from database.repository import UserRepository; from database.connection import get_db_session; import asyncio; async def count(): async with get_db_session() as db: repo = UserRepository(db); users = await repo.list_users(); print(f'Users: {len(users)}'); asyncio.run(count())"

# Test authentication
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@voicehive-hotels.eu", "password": "admin123"}'
```

### Log Analysis

Look for these log events:
- `database_initialized`
- `database_tables_created`
- `mock_user_migration_completed`
- `user_authenticated`
- `database_connection_test_passed`

## Performance Considerations

### Connection Pooling
- Default pool size: 10 connections
- Max overflow: 20 connections
- Pool timeout: 30 seconds
- Connection recycling: 1 hour

### Indexes
- Email lookup: `idx_users_email_active`
- Session lookup: `idx_user_sessions_active`
- JWT lookup: Unique constraints on JTI fields

### Query Optimization
- Use of `selectinload` for relationships
- Pagination for user lists
- Efficient session validation

## Rollback Plan

If issues occur, you can temporarily rollback to mock users:

1. **Emergency Rollback**:
   - Comment out database initialization in `app.py`
   - Restore original `routers/auth.py` from git
   - Restart service

2. **Planned Rollback**:
   - Export users from database first
   - Follow emergency rollback steps
   - Plan re-migration

## Next Steps

1. **Change Default Passwords** immediately
2. **Set up Database Backups**
3. **Configure Monitoring Alerts**
4. **Review Security Policies**
5. **Test User Creation/Management**
6. **Plan Password Rotation**

## Related Documentation

- [Database Performance Optimization](./DATABASE_PERFORMANCE_README.md)
- [Authentication Architecture](../authentication/AUTH_ARCHITECTURE.md)
- [Security Guidelines](../security/SECURITY_GUIDELINES.md)