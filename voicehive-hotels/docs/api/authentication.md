# VoiceHive Hotels API Authentication Guide

## Overview

The VoiceHive Hotels API uses a multi-layered authentication system supporting both JWT tokens for user authentication and API keys for service-to-service communication. All API endpoints require proper authentication unless explicitly marked as public.

## Authentication Methods

### 1. JWT Token Authentication

JWT tokens are used for user authentication and provide role-based access control.

#### Obtaining a JWT Token

**Endpoint:** `POST /auth/login`

**Request:**

```json
{
  "email": "user@example.com",
  "password": "secure_password"
}
```

**Response:**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "refresh_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "user_123",
    "email": "user@example.com",
    "roles": ["hotel_admin", "call_manager"]
  }
}
```

#### Using JWT Tokens

Include the JWT token in the Authorization header:

```http
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Example cURL:**

```bash
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     -H "Content-Type: application/json" \
     https://api.voicehive.com/v1/calls
```

#### Token Refresh

**Endpoint:** `POST /auth/refresh`

**Request:**

```json
{
  "refresh_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### 2. API Key Authentication

API keys are used for service-to-service communication and automated systems.

#### Using API Keys

Include the API key in the X-API-Key header:

```http
X-API-Key: vh_live_1234567890abcdef
```

**Example cURL:**

```bash
curl -H "X-API-Key: vh_live_1234567890abcdef" \
     -H "Content-Type: application/json" \
     https://api.voicehive.com/v1/webhooks/call-events
```

## Role-Based Access Control (RBAC)

### Available Roles

| Role           | Description             | Permissions                       |
| -------------- | ----------------------- | --------------------------------- |
| `super_admin`  | System administrator    | Full system access                |
| `hotel_admin`  | Hotel administrator     | Hotel management, user management |
| `call_manager` | Call operations manager | Call management, monitoring       |
| `agent`        | Call center agent       | Call handling, basic operations   |
| `readonly`     | Read-only access        | View-only permissions             |

### Permission Matrix

| Endpoint             | super_admin | hotel_admin | call_manager | agent | readonly |
| -------------------- | ----------- | ----------- | ------------ | ----- | -------- |
| `GET /calls`         | ✅          | ✅          | ✅           | ✅    | ✅       |
| `POST /calls`        | ✅          | ✅          | ✅           | ✅    | ❌       |
| `DELETE /calls/{id}` | ✅          | ✅          | ✅           | ❌    | ❌       |
| `GET /hotels`        | ✅          | ✅          | ✅           | ✅    | ✅       |
| `POST /hotels`       | ✅          | ✅          | ❌           | ❌    | ❌       |
| `GET /users`         | ✅          | ✅          | ❌           | ❌    | ❌       |
| `POST /users`        | ✅          | ✅          | ❌           | ❌    | ❌       |

## Error Responses

### Authentication Errors

**401 Unauthorized - Missing or Invalid Token:**

```json
{
  "error": {
    "code": "AUTHENTICATION_ERROR",
    "message": "Invalid or expired authentication token",
    "correlation_id": "req_123456789",
    "timestamp": "2025-01-22T10:30:00Z"
  }
}
```

**403 Forbidden - Insufficient Permissions:**

```json
{
  "error": {
    "code": "AUTHORIZATION_ERROR",
    "message": "Insufficient permissions for this operation",
    "correlation_id": "req_123456789",
    "timestamp": "2025-01-22T10:30:00Z"
  }
}
```

## Rate Limiting

All authenticated endpoints are subject to rate limiting:

- **Per User:** 60 requests per minute, 1000 per hour
- **Per API Key:** 100 requests per minute, 5000 per hour
- **Burst Limit:** 10 requests in 1 second

### Rate Limit Headers

```http
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1642857600
Retry-After: 30
```

### Rate Limit Exceeded Response

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded. Try again in 30 seconds",
    "correlation_id": "req_123456789",
    "timestamp": "2025-01-22T10:30:00Z",
    "details": {
      "retry_after": 30,
      "limit": 60,
      "window": "1 minute"
    }
  }
}
```

## Security Best Practices

### For Developers

1. **Store tokens securely** - Never store JWT tokens in localStorage, use httpOnly cookies
2. **Implement token refresh** - Handle token expiration gracefully
3. **Use HTTPS only** - Never send tokens over unencrypted connections
4. **Validate on server** - Always validate tokens server-side
5. **Handle errors properly** - Implement proper error handling for auth failures

### For API Key Management

1. **Rotate regularly** - Rotate API keys every 90 days
2. **Scope permissions** - Use least-privilege principle
3. **Monitor usage** - Track API key usage and set up alerts
4. **Secure storage** - Store API keys in secure configuration management
5. **Revoke unused keys** - Remove API keys that are no longer needed

## Code Examples

### Python (requests)

```python
import requests
import json

# JWT Authentication
def authenticate(email, password):
    response = requests.post(
        "https://api.voicehive.com/auth/login",
        json={"email": email, "password": password}
    )
    return response.json()["access_token"]

# Making authenticated requests
def get_calls(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.get(
        "https://api.voicehive.com/v1/calls",
        headers=headers
    )
    return response.json()

# API Key authentication
def webhook_handler(api_key, event_data):
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }
    response = requests.post(
        "https://api.voicehive.com/v1/webhooks/call-events",
        headers=headers,
        json=event_data
    )
    return response.status_code == 200
```

### JavaScript (fetch)

```javascript
// JWT Authentication
async function authenticate(email, password) {
  const response = await fetch("https://api.voicehive.com/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, password }),
  });
  const data = await response.json();
  return data.access_token;
}

// Making authenticated requests
async function getCalls(token) {
  const response = await fetch("https://api.voicehive.com/v1/calls", {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });
  return response.json();
}

// API Key authentication
async function sendWebhookEvent(apiKey, eventData) {
  const response = await fetch(
    "https://api.voicehive.com/v1/webhooks/call-events",
    {
      method: "POST",
      headers: {
        "X-API-Key": apiKey,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(eventData),
    }
  );
  return response.ok;
}
```

## Testing Authentication

### Using Postman

1. **Set up environment variables:**

   - `base_url`: `https://api.voicehive.com`
   - `jwt_token`: (will be set after login)

2. **Login request:**

   - Method: POST
   - URL: `{{base_url}}/auth/login`
   - Body: `{"email": "test@example.com", "password": "password"}`
   - Test script: `pm.environment.set("jwt_token", pm.response.json().access_token);`

3. **Authenticated request:**
   - Method: GET
   - URL: `{{base_url}}/v1/calls`
   - Headers: `Authorization: Bearer {{jwt_token}}`

### Using cURL

```bash
# Login and extract token
TOKEN=$(curl -s -X POST https://api.voicehive.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password"}' \
  | jq -r '.access_token')

# Use token for authenticated request
curl -H "Authorization: Bearer $TOKEN" \
     https://api.voicehive.com/v1/calls
```

## Troubleshooting

### Common Issues

1. **Token Expired**

   - Error: 401 with "Token expired" message
   - Solution: Use refresh token or re-authenticate

2. **Invalid Signature**

   - Error: 401 with "Invalid token signature"
   - Solution: Check token format and ensure it hasn't been modified

3. **Insufficient Permissions**

   - Error: 403 with "Insufficient permissions"
   - Solution: Check user roles and endpoint permissions

4. **Rate Limit Exceeded**
   - Error: 429 with retry-after header
   - Solution: Implement exponential backoff and respect rate limits

### Debug Mode

Enable debug logging to troubleshoot authentication issues:

```python
import logging
logging.getLogger('voicehive.auth').setLevel(logging.DEBUG)
```

## Support

For authentication-related issues:

- Check the troubleshooting guide above
- Review API logs with correlation IDs
- Contact support with specific error messages and correlation IDs
