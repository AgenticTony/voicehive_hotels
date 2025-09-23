# VoiceHive Hotels API Endpoints Reference

## Base URL

- **Production:** `https://api.voicehive.com`
- **Staging:** `https://staging-api.voicehive.com`
- **Development:** `http://localhost:8000`

## Common Headers

All requests should include:

```http
Content-Type: application/json
Authorization: Bearer <jwt_token> OR X-API-Key: <api_key>
X-Correlation-ID: <optional_correlation_id>
```

## Authentication Endpoints

### POST /auth/login

Authenticate user and obtain JWT token.

**Request:**

```json
{
  "email": "user@example.com",
  "password": "secure_password"
}
```

**Response (200):**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 900,
  "refresh_token": "eyJhbGciOiJSUzI1NiIs...",
  "user": {
    "id": "user_123",
    "email": "user@example.com",
    "roles": ["hotel_admin"]
  }
}
```

### POST /auth/refresh

Refresh JWT token using refresh token.

**Request:**

```json
{
  "refresh_token": "eyJhbGciOiJSUzI1NiIs..."
}
```

**Response (200):**

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 900
}
```

### POST /auth/logout

Invalidate current JWT token.

**Response (200):**

```json
{
  "message": "Successfully logged out"
}
```

## Call Management Endpoints

### GET /v1/calls

List calls with optional filtering.

**Query Parameters:**

- `hotel_id` (string): Filter by hotel ID
- `status` (string): Filter by call status (active, completed, failed)
- `start_date` (ISO 8601): Filter calls after this date
- `end_date` (ISO 8601): Filter calls before this date
- `limit` (integer): Number of results (default: 50, max: 100)
- `offset` (integer): Pagination offset (default: 0)

**Response (200):**

```json
{
  "calls": [
    {
      "id": "call_123",
      "hotel_id": "hotel_456",
      "room_number": "101",
      "guest_name": "John Doe",
      "status": "active",
      "started_at": "2025-01-22T10:30:00Z",
      "duration": 120,
      "transcript": "Hello, I'd like to request room service...",
      "pii_redacted": true
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### POST /v1/calls

Initiate a new call.

**Request:**

```json
{
  "hotel_id": "hotel_456",
  "room_number": "101",
  "guest_phone": "+1234567890",
  "call_type": "room_service",
  "priority": "normal"
}
```

**Response (201):**

```json
{
  "id": "call_123",
  "hotel_id": "hotel_456",
  "room_number": "101",
  "status": "initiated",
  "created_at": "2025-01-22T10:30:00Z",
  "livekit_room": "room_abc123",
  "livekit_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

### GET /v1/calls/{call_id}

Get details of a specific call.

**Response (200):**

```json
{
  "id": "call_123",
  "hotel_id": "hotel_456",
  "room_number": "101",
  "guest_name": "John Doe",
  "status": "completed",
  "started_at": "2025-01-22T10:30:00Z",
  "ended_at": "2025-01-22T10:35:00Z",
  "duration": 300,
  "transcript": "Hello, I'd like to request room service...",
  "summary": "Guest requested room service for dinner",
  "actions_taken": [
    {
      "type": "room_service_order",
      "details": "Dinner order placed",
      "timestamp": "2025-01-22T10:32:00Z"
    }
  ],
  "pii_redacted": true
}
```

### PATCH /v1/calls/{call_id}

Update call status or metadata.

**Request:**

```json
{
  "status": "completed",
  "summary": "Guest requested room service",
  "actions_taken": [
    {
      "type": "room_service_order",
      "details": "Dinner order placed"
    }
  ]
}
```

**Response (200):**

```json
{
  "id": "call_123",
  "status": "completed",
  "updated_at": "2025-01-22T10:35:00Z"
}
```

### DELETE /v1/calls/{call_id}

Cancel or delete a call.

**Response (204):** No content

## Hotel Management Endpoints

### GET /v1/hotels

List hotels accessible to the authenticated user.

**Response (200):**

```json
{
  "hotels": [
    {
      "id": "hotel_456",
      "name": "Grand Plaza Hotel",
      "address": "123 Main St, City, State 12345",
      "phone": "+1234567890",
      "pms_type": "apaleo",
      "status": "active",
      "created_at": "2025-01-01T00:00:00Z"
    }
  ]
}
```

### POST /v1/hotels

Create a new hotel configuration.

**Request:**

```json
{
  "name": "Grand Plaza Hotel",
  "address": "123 Main St, City, State 12345",
  "phone": "+1234567890",
  "pms_type": "apaleo",
  "pms_config": {
    "api_url": "https://api.apaleo.com",
    "client_id": "client_123",
    "client_secret": "secret_456"
  }
}
```

**Response (201):**

```json
{
  "id": "hotel_456",
  "name": "Grand Plaza Hotel",
  "status": "active",
  "created_at": "2025-01-22T10:30:00Z"
}
```

### GET /v1/hotels/{hotel_id}

Get hotel details and configuration.

**Response (200):**

```json
{
  "id": "hotel_456",
  "name": "Grand Plaza Hotel",
  "address": "123 Main St, City, State 12345",
  "phone": "+1234567890",
  "pms_type": "apaleo",
  "status": "active",
  "room_count": 150,
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-22T10:30:00Z"
}
```

## Webhook Endpoints

### POST /v1/webhooks/call-events

Receive call event notifications (API key authentication required).

**Request:**

```json
{
  "event_type": "call.completed",
  "call_id": "call_123",
  "hotel_id": "hotel_456",
  "timestamp": "2025-01-22T10:35:00Z",
  "data": {
    "duration": 300,
    "transcript": "Hello, I'd like to request room service...",
    "summary": "Guest requested room service"
  }
}
```

**Response (200):**

```json
{
  "received": true,
  "processed_at": "2025-01-22T10:35:01Z"
}
```

### POST /v1/webhooks/pms-events

Receive PMS system event notifications.

**Request:**

```json
{
  "event_type": "reservation.created",
  "hotel_id": "hotel_456",
  "reservation_id": "res_789",
  "timestamp": "2025-01-22T10:30:00Z",
  "data": {
    "guest_name": "John Doe",
    "room_number": "101",
    "check_in": "2025-01-22",
    "check_out": "2025-01-25"
  }
}
```

## Monitoring Endpoints

### GET /health

System health check (no authentication required).

**Response (200):**

```json
{
  "status": "healthy",
  "timestamp": "2025-01-22T10:30:00Z",
  "services": {
    "database": "healthy",
    "redis": "healthy",
    "vault": "healthy",
    "livekit": "healthy",
    "tts": "healthy",
    "asr": "healthy"
  },
  "version": "1.0.0"
}
```

### GET /metrics

Prometheus metrics (API key authentication required).

**Response (200):**

```
# HELP voicehive_calls_total Total number of calls
# TYPE voicehive_calls_total counter
voicehive_calls_total{status="completed"} 1234
voicehive_calls_total{status="failed"} 56

# HELP voicehive_call_duration_seconds Call duration in seconds
# TYPE voicehive_call_duration_seconds histogram
voicehive_call_duration_seconds_bucket{le="30"} 100
voicehive_call_duration_seconds_bucket{le="60"} 250
voicehive_call_duration_seconds_bucket{le="120"} 400
```

## User Management Endpoints

### GET /v1/users

List users (admin access required).

**Query Parameters:**

- `role` (string): Filter by user role
- `hotel_id` (string): Filter by hotel association
- `active` (boolean): Filter by active status

**Response (200):**

```json
{
  "users": [
    {
      "id": "user_123",
      "email": "user@example.com",
      "roles": ["hotel_admin"],
      "hotel_ids": ["hotel_456"],
      "active": true,
      "created_at": "2025-01-01T00:00:00Z",
      "last_login": "2025-01-22T09:00:00Z"
    }
  ]
}
```

### POST /v1/users

Create a new user (admin access required).

**Request:**

```json
{
  "email": "newuser@example.com",
  "password": "secure_password",
  "roles": ["call_manager"],
  "hotel_ids": ["hotel_456"],
  "active": true
}
```

**Response (201):**

```json
{
  "id": "user_789",
  "email": "newuser@example.com",
  "roles": ["call_manager"],
  "created_at": "2025-01-22T10:30:00Z"
}
```

## Error Responses

All endpoints may return these standard error responses:

### 400 Bad Request

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request data",
    "correlation_id": "req_123456789",
    "timestamp": "2025-01-22T10:30:00Z",
    "details": {
      "field": "email",
      "issue": "Invalid email format"
    }
  }
}
```

### 401 Unauthorized

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

### 403 Forbidden

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

### 404 Not Found

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource not found",
    "correlation_id": "req_123456789",
    "timestamp": "2025-01-22T10:30:00Z"
  }
}
```

### 429 Too Many Requests

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

### 500 Internal Server Error

```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "An unexpected error occurred",
    "correlation_id": "req_123456789",
    "timestamp": "2025-01-22T10:30:00Z"
  }
}
```

## Rate Limits

| Endpoint Category | Authenticated Users | API Keys | Burst Limit |
| ----------------- | ------------------- | -------- | ----------- |
| Authentication    | 10/min              | N/A      | 5/sec       |
| Call Management   | 60/min              | 100/min  | 10/sec      |
| Hotel Management  | 30/min              | 50/min   | 5/sec       |
| Webhooks          | N/A                 | 1000/min | 50/sec      |
| Monitoring        | 120/min             | 500/min  | 20/sec      |

## Pagination

List endpoints support pagination using `limit` and `offset` parameters:

- `limit`: Number of items to return (default: 50, max: 100)
- `offset`: Number of items to skip (default: 0)

Response includes pagination metadata:

```json
{
  "data": [...],
  "total": 1000,
  "limit": 50,
  "offset": 100,
  "has_more": true
}
```

## Filtering and Sorting

Many list endpoints support filtering and sorting:

**Filtering:**

- Use query parameters matching field names
- Support for exact matches and ranges
- Date ranges using `start_date` and `end_date`

**Sorting:**

- Use `sort` parameter with field name
- Add `-` prefix for descending order
- Example: `?sort=-created_at` for newest first

## Webhooks

### Security

All webhook requests include:

- `X-Webhook-Signature`: HMAC-SHA256 signature
- `X-Webhook-Timestamp`: Unix timestamp
- `X-Webhook-ID`: Unique webhook delivery ID

### Retry Policy

Failed webhook deliveries are retried:

- Immediate retry
- 1 minute later
- 5 minutes later
- 30 minutes later
- 2 hours later
- 6 hours later

### Event Types

- `call.initiated`
- `call.connected`
- `call.completed`
- `call.failed`
- `reservation.created`
- `reservation.updated`
- `reservation.cancelled`

## SDK Examples

### Python SDK

```python
from voicehive import VoiceHiveClient

client = VoiceHiveClient(
    api_key="vh_live_1234567890abcdef",
    base_url="https://api.voicehive.com"
)

# List calls
calls = client.calls.list(hotel_id="hotel_456", limit=10)

# Create call
call = client.calls.create(
    hotel_id="hotel_456",
    room_number="101",
    guest_phone="+1234567890"
)

# Get call details
call_details = client.calls.get("call_123")
```

### JavaScript SDK

```javascript
import { VoiceHiveClient } from "@voicehive/sdk";

const client = new VoiceHiveClient({
  apiKey: "vh_live_1234567890abcdef",
  baseUrl: "https://api.voicehive.com",
});

// List calls
const calls = await client.calls.list({
  hotelId: "hotel_456",
  limit: 10,
});

// Create call
const call = await client.calls.create({
  hotelId: "hotel_456",
  roomNumber: "101",
  guestPhone: "+1234567890",
});
```
