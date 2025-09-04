# VoiceHive Hotels API Documentation

## Overview

VoiceHive Hotels provides REST APIs for voice system integration and monitoring.

## Base URLs

- **Production**: `https://api.voicehive-hotels.eu`
- **Staging**: `https://api-staging.voicehive-hotels.eu`
- **Development**: `http://localhost:8080`

## Authentication

All API requests require authentication via API key:

```bash
curl -H "X-API-Key: vh_your_api_key_here" \
  https://api.voicehive-hotels.eu/v1/health
```

## Rate Limits

- **Standard tier**: 100 requests/minute
- **Premium tier**: 1000 requests/minute
- **Enterprise**: Unlimited

## Endpoints

### Health Check
```
GET /healthz
```

Returns system health status and regional compliance.

**Response:**
```json
{
  "status": "healthy",
  "region": "eu-west-1",
  "version": "1.0.0",
  "gdpr_compliant": true,
  "services": {
    "livekit": "eu-west-1 (valid)",
    "twilio": "frankfurt (valid)",
    "azure_openai": "westeurope (valid)",
    "elevenlabs": "eu (valid)"
  }
}
```

### Start Call
```
POST /v1/call/start
```

Initiates a new voice call session.

**Request:**
```json
{
  "caller_id": "+441234567890",
  "hotel_id": "HOTEL_001",
  "language": "auto"
}
```

**Response:**
```json
{
  "call_id": "call_2024-01-15T10:30:00Z_HOTEL_001",
  "session_token": "eyJ0eXAiOi...",
  "websocket_url": "wss://livekit-eu.voicehive-hotels.eu/ws",
  "region": "eu-west-1",
  "encryption_key_id": "kms-HOTEL_001"
}
```

### PMS Connector Status
```
GET /v1/connectors/{vendor}/status
```

Check PMS connector health.

**Response:**
```json
{
  "vendor": "apaleo",
  "status": "connected",
  "last_sync": "2024-01-15T10:25:00Z",
  "capabilities": {
    "availability": true,
    "reservations": true,
    "guest_profiles": true
  }
}
```

### GDPR Consent
```
POST /v1/gdpr/consent
```

Record GDPR consent for voice processing.

**Request:**
```json
{
  "hotel_id": "HOTEL_001",
  "purpose": "voice_cloning",
  "consent": true
}
```

### Data Deletion Request
```
POST /v1/gdpr/deletion-request
```

Request deletion of personal data.

**Request:**
```json
{
  "hotel_id": "HOTEL_001",
  "caller_id": "+441234567890"
}
```

## Error Codes

| Code | Description |
|------|-------------|
| 400 | Bad Request - Invalid parameters |
| 401 | Unauthorized - Invalid API key |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found - Resource doesn't exist |
| 429 | Too Many Requests - Rate limit exceeded |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

## Webhooks

Configure webhooks for real-time events:

### Call Started
```json
{
  "event": "call.started",
  "call_id": "call_123",
  "hotel_id": "HOTEL_001",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Call Ended
```json
{
  "event": "call.ended",
  "call_id": "call_123",
  "duration_seconds": 120,
  "outcome": "completed",
  "timestamp": "2024-01-15T10:32:00Z"
}
```

## SDKs

- **Python**: `pip install voicehive-hotels`
- **Node.js**: `npm install @voicehive/hotels`
- **Go**: `go get github.com/voicehive/hotels-go`

## OpenAPI Specification

Download the full OpenAPI 3.0 specification:
- [openapi.yaml](https://api.voicehive-hotels.eu/openapi.yaml)
- [Swagger UI](https://api.voicehive-hotels.eu/docs)
