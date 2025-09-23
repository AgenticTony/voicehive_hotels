# VoiceHive Hotels Authentication & Authorization System

This document describes the comprehensive authentication and authorization system implemented for the VoiceHive Hotels Orchestrator service.

## Overview

The authentication system provides:

- **JWT-based user authentication** with Redis session management
- **API key authentication** for service-to-service communication
- **Role-based access control (RBAC)** with configurable permissions
- **Secure token management** with refresh and revocation capabilities
- **HashiCorp Vault integration** for API key storage
- **Comprehensive middleware** for request authentication and authorization

## Architecture Components

### 1. Authentication Models (`auth_models.py`)

Defines the core data structures:

- `UserContext`: Authenticated user information with roles and permissions
- `ServiceContext`: Authenticated service information with API key details
- `JWTPayload`: JWT token structure
- `UserRole`: Enumeration of available user roles
- `Permission`: Enumeration of system permissions
- Request/Response models for authentication endpoints

### 2. JWT Service (`jwt_service.py`)

Handles JWT token lifecycle:

- **Token Creation**: Generates access and refresh tokens
- **Token Validation**: Validates JWT signatures and expiration
- **Session Management**: Redis-based session storage
- **Token Refresh**: Secure token renewal mechanism
- **Token Revocation**: Blacklist-based token invalidation

### 3. Vault Client (`vault_client.py`)

Manages API keys using HashiCorp Vault:

- **API Key Generation**: Creates secure API keys
- **Key Storage**: Stores keys securely in Vault
- **Key Validation**: Validates API keys against stored hashes
- **Key Management**: List, revoke, and manage API keys
- **Mock Implementation**: Development-friendly mock client

### 4. Authentication Middleware (`auth_middleware.py`)

Provides request-level authentication:

- **Automatic Authentication**: Validates JWT tokens and API keys
- **Path-based Authorization**: Protects endpoints based on permissions
- **Security Headers**: Adds security headers to responses
- **Error Handling**: Standardized authentication error responses

### 5. Authentication Router (`routers/auth.py`)

Exposes authentication endpoints:

- `POST /auth/login`: User login with email/password
- `POST /auth/refresh`: Token refresh
- `POST /auth/logout`: User logout
- `POST /auth/api-keys`: Create API keys (admin only)
- `GET /auth/api-keys`: List API keys (admin only)
- `DELETE /auth/api-keys/{id}`: Revoke API keys (admin only)

## User Roles and Permissions

### Roles

- **ADMIN**: Full system access
- **OPERATOR**: Call and system monitoring access
- **HOTEL_MANAGER**: Hotel-specific management access
- **GUEST_SERVICE**: Basic call handling access
- **READONLY**: Read-only access to system information

### Permissions

- **Call Management**: `CALL_START`, `CALL_END`, `CALL_VIEW`, `CALL_MANAGE`
- **Hotel Management**: `HOTEL_CREATE`, `HOTEL_UPDATE`, `HOTEL_DELETE`, `HOTEL_VIEW`
- **System Administration**: `SYSTEM_CONFIG`, `SYSTEM_MONITOR`, `SYSTEM_ADMIN`
- **User Management**: `USER_CREATE`, `USER_UPDATE`, `USER_DELETE`, `USER_VIEW`

## Usage Examples

### 1. User Authentication

```bash
# Login
curl -X POST http://localhost:8080/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@voicehive-hotels.eu",
    "password": "admin123"
  }'

# Response
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9...",
  "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "user_id": "admin-001",
    "email": "admin@voicehive-hotels.eu",
    "roles": ["admin"],
    "permissions": ["call:start", "call:end", ...],
    "session_id": "uuid-session-id"
  }
}
```

### 2. Using JWT Tokens

```bash
# Access protected endpoint
curl -X POST http://localhost:8080/v1/call/start \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "caller_id": "+1234567890",
    "hotel_id": "hotel-001",
    "language": "en"
  }'
```

### 3. API Key Authentication

```bash
# Create API key (admin only)
curl -X POST http://localhost:8080/auth/api-keys \
  -H "Authorization: Bearer admin-jwt-token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "TTS Service Key",
    "service_name": "tts-router",
    "permissions": ["call:view", "hotel:view"],
    "expires_days": 90
  }'

# Use API key
curl -X GET http://localhost:8080/v1/call/status \
  -H "X-API-Key: vhh_generated-api-key-here"
```

### 4. Protecting Routes with Decorators

```python
from fastapi import APIRouter, Depends
from auth_middleware import require_permissions, require_roles, Permission

router = APIRouter()

@router.get("/admin/users")
async def list_users(
    auth_context = Depends(require_permissions(Permission.USER_VIEW))
):
    # Only users with USER_VIEW permission can access
    return {"users": [...]}

@router.post("/admin/config")
async def update_config(
    user_context = Depends(require_roles("admin"))
):
    # Only admin role can access
    return {"status": "updated"}
```

## Configuration

### Environment Variables

```bash
# Redis for session storage
REDIS_URL=redis://localhost:6379

# HashiCorp Vault for API keys
VAULT_ADDR=http://localhost:8200
VAULT_TOKEN=your-vault-token

# Environment
ENVIRONMENT=production  # or development
```

### Mock Users (Development)

The system includes mock users for development:

- `admin@voicehive-hotels.eu` / `admin123` (Admin role)
- `operator@voicehive-hotels.eu` / `operator123` (Operator role)
- `manager@hotel1.com` / `manager123` (Hotel Manager role)

## Security Features

### JWT Security

- **RS256 Algorithm**: Asymmetric key signing
- **Short Expiration**: 15-minute access tokens
- **Refresh Tokens**: 7-day refresh tokens
- **Session Tracking**: Redis-based session management
- **Token Revocation**: Blacklist support

### API Key Security

- **Secure Generation**: Cryptographically secure random keys
- **Hash Storage**: Only hashes stored, never plain keys
- **Vault Integration**: Secure storage in HashiCorp Vault
- **Expiration Support**: Configurable key expiration
- **Permission Scoping**: Fine-grained permission control

### Middleware Security

- **Path Protection**: Automatic endpoint protection
- **Security Headers**: HSTS, CSP, XSS protection
- **Rate Limiting Ready**: Integration points for rate limiting
- **Audit Logging**: Comprehensive authentication logging

## Testing

Run the authentication system test:

```bash
cd voicehive-hotels/services/orchestrator
python test_auth_system.py
```

This will test:

- User authentication
- JWT token creation and validation
- Token refresh mechanism
- API key creation and validation
- Permission system
- Session management

## Production Deployment

### 1. HashiCorp Vault Setup

```bash
# Enable KV v2 secrets engine
vault secrets enable -version=2 kv

# Create policies for API key management
vault policy write api-key-policy - <<EOF
path "secret/data/api-keys/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
path "secret/data/service-configs/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
EOF
```

### 2. Redis Configuration

Ensure Redis is configured with:

- Persistence enabled
- Appropriate memory limits
- Security (AUTH, TLS if needed)

### 3. Environment Setup

```bash
# Production environment variables
export ENVIRONMENT=production
export REDIS_URL=redis://redis-cluster:6379
export VAULT_ADDR=https://vault.internal:8200
export VAULT_TOKEN=production-vault-token
```

## Monitoring and Observability

The authentication system provides structured logging for:

- Authentication attempts (success/failure)
- Token creation and validation
- API key usage
- Permission checks
- Session management events

All logs include correlation IDs and relevant context for debugging and security monitoring.

## Security Considerations

1. **Token Storage**: Never store JWT tokens in localStorage in browsers
2. **API Key Rotation**: Regularly rotate API keys
3. **Session Management**: Monitor for suspicious session activity
4. **Vault Security**: Secure Vault deployment with proper policies
5. **Redis Security**: Secure Redis with authentication and encryption
6. **Audit Logging**: Monitor authentication logs for security events

## Future Enhancements

- Multi-factor authentication (MFA)
- OAuth2/OIDC integration
- Advanced rate limiting per user/service
- Geolocation-based access controls
- Advanced audit and compliance reporting
