# VoiceHive Hotels API Documentation

## Overview

Welcome to the VoiceHive Hotels API documentation. This comprehensive guide provides everything you need to integrate with our voice AI platform for hotel guest services.

## Quick Start

### 1. Authentication

Get started by obtaining your API credentials:

```bash
# Login to get JWT token
curl -X POST https://api.voicehive.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"your-email@example.com","password":"your-password"}'
```

### 2. Make Your First API Call

```bash
# List your hotels
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  https://api.voicehive.com/v1/hotels
```

### 3. Initiate a Call

```bash
# Start a voice interaction
curl -X POST https://api.voicehive.com/v1/calls \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "hotel_id": "hotel_123",
    "room_number": "101",
    "guest_phone": "+1234567890"
  }'
```

## Documentation Structure

### Core API Documentation

- **[Authentication Guide](authentication.md)** - Complete authentication and authorization guide
- **[API Endpoints Reference](endpoints.md)** - Detailed endpoint documentation with examples
- **[Rate Limiting](authentication.md#rate-limiting)** - Rate limiting policies and headers
- **[Error Handling](endpoints.md#error-responses)** - Standard error responses and codes

### Integration Guides

- **[Webhook Integration](../integrations/webhooks.md)** - Setting up webhook endpoints
- **[PMS Integration](../integrations/pms-connectors.md)** - Property Management System integration
- **[SDK Documentation](../sdks/)** - Official SDKs and libraries

### Security and Compliance

- **[Security Best Practices](../security/api-security.md)** - Security guidelines for API usage
- **[Data Privacy](../security/data-privacy.md)** - GDPR and data protection compliance
- **[Audit Logging](../security/audit-logging.md)** - Security audit and logging

## API Features

### 🔐 Secure Authentication

- JWT token-based authentication
- API key support for service-to-service communication
- Role-based access control (RBAC)
- Multi-factor authentication support

### 🚀 High Performance

- Sub-200ms response times
- Intelligent caching
- Connection pooling
- Rate limiting with burst support

### 🛡️ Enterprise Security

- End-to-end encryption
- PII redaction and data protection
- Comprehensive audit logging
- SOC 2 Type II compliance

### 📊 Real-time Monitoring

- Detailed metrics and analytics
- Real-time call status updates
- Performance monitoring
- Custom alerting

## Base URLs

| Environment    | Base URL                            | Purpose                             |
| -------------- | ----------------------------------- | ----------------------------------- |
| **Production** | `https://api.voicehive.com`         | Live production environment         |
| **Staging**    | `https://staging-api.voicehive.com` | Testing and validation              |
| **Sandbox**    | `https://sandbox-api.voicehive.com` | Development and integration testing |

## API Versioning

We use URL path versioning for our API:

- **Current Version**: `v1`
- **Base Path**: `/v1/`
- **Full URL**: `https://api.voicehive.com/v1/endpoint`

### Version Support Policy

- **Current Version (v1)**: Fully supported with new features
- **Previous Versions**: Supported for 12 months after deprecation notice
- **Deprecation Notice**: 6 months advance notice for breaking changes

## Common Use Cases

### 1. Hotel Guest Services

```python
# Python example: Handle guest room service request
import requests

# Authenticate
auth_response = requests.post('https://api.voicehive.com/auth/login', json={
    'email': 'hotel@example.com',
    'password': 'secure_password'
})
token = auth_response.json()['access_token']

# Initiate call for room service
call_response = requests.post('https://api.voicehive.com/v1/calls',
    headers={'Authorization': f'Bearer {token}'},
    json={
        'hotel_id': 'hotel_123',
        'room_number': '205',
        'call_type': 'room_service',
        'priority': 'normal'
    }
)

call_id = call_response.json()['id']
print(f"Call initiated: {call_id}")
```

### 2. Webhook Event Handling

```javascript
// Node.js example: Handle call completion webhook
const express = require("express");
const crypto = require("crypto");

const app = express();
app.use(express.json());

app.post("/webhooks/call-events", (req, res) => {
  // Verify webhook signature
  const signature = req.headers["x-webhook-signature"];
  const payload = JSON.stringify(req.body);
  const expectedSignature = crypto
    .createHmac("sha256", process.env.WEBHOOK_SECRET)
    .update(payload)
    .digest("hex");

  if (signature !== `sha256=${expectedSignature}`) {
    return res.status(401).send("Invalid signature");
  }

  // Process the event
  const { event_type, call_id, data } = req.body;

  if (event_type === "call.completed") {
    console.log(`Call ${call_id} completed:`, data.summary);
    // Update your system with call results
  }

  res.status(200).send("OK");
});
```

### 3. Real-time Call Monitoring

```python
# Python example: Monitor call status
import asyncio
import websockets
import json

async def monitor_calls():
    uri = "wss://api.voicehive.com/v1/calls/stream"
    headers = {"Authorization": "Bearer YOUR_JWT_TOKEN"}

    async with websockets.connect(uri, extra_headers=headers) as websocket:
        async for message in websocket:
            event = json.loads(message)
            print(f"Call {event['call_id']} status: {event['status']}")

            if event['status'] == 'completed':
                print(f"Summary: {event['summary']}")

# Run the monitor
asyncio.run(monitor_calls())
```

## SDK and Libraries

### Official SDKs

#### Python SDK

```bash
pip install voicehive-sdk
```

```python
from voicehive import VoiceHiveClient

client = VoiceHiveClient(
    api_key="your_api_key",
    base_url="https://api.voicehive.com"
)

# List hotels
hotels = client.hotels.list()

# Create a call
call = client.calls.create(
    hotel_id="hotel_123",
    room_number="101",
    guest_phone="+1234567890"
)
```

#### JavaScript/Node.js SDK

```bash
npm install @voicehive/sdk
```

```javascript
import { VoiceHiveClient } from "@voicehive/sdk";

const client = new VoiceHiveClient({
  apiKey: "your_api_key",
  baseUrl: "https://api.voicehive.com",
});

// List hotels
const hotels = await client.hotels.list();

// Create a call
const call = await client.calls.create({
  hotelId: "hotel_123",
  roomNumber: "101",
  guestPhone: "+1234567890",
});
```

### Community Libraries

- **PHP**: [voicehive/php-sdk](https://github.com/voicehive/php-sdk)
- **Ruby**: [voicehive/ruby-sdk](https://github.com/voicehive/ruby-sdk)
- **Go**: [voicehive/go-sdk](https://github.com/voicehive/go-sdk)
- **Java**: [voicehive/java-sdk](https://github.com/voicehive/java-sdk)

## Testing and Development

### Sandbox Environment

Use our sandbox environment for development and testing:

```bash
# Sandbox base URL
export VOICEHIVE_BASE_URL="https://sandbox-api.voicehive.com"

# Test credentials (sandbox only)
export VOICEHIVE_EMAIL="test@voicehive.com"
export VOICEHIVE_PASSWORD="sandbox123"
```

### Postman Collection

Import our Postman collection for easy API testing:

1. Download: [VoiceHive API Collection](./postman/VoiceHive-API.postman_collection.json)
2. Import into Postman
3. Set environment variables:
   - `base_url`: API base URL
   - `email`: Your email
   - `password`: Your password

### API Testing Tools

#### cURL Examples

```bash
# Set common variables
export BASE_URL="https://api.voicehive.com"
export TOKEN="your_jwt_token_here"

# Test authentication
curl -X POST $BASE_URL/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password"}'

# Test API endpoint
curl -H "Authorization: Bearer $TOKEN" \
  $BASE_URL/v1/hotels
```

#### HTTPie Examples

```bash
# Install HTTPie
pip install httpie

# Login
http POST api.voicehive.com/auth/login email=test@example.com password=password

# Use token
http GET api.voicehive.com/v1/hotels Authorization:"Bearer $TOKEN"
```

## Rate Limits and Quotas

### Default Rate Limits

| User Type      | Requests/Minute | Requests/Hour | Burst Limit |
| -------------- | --------------- | ------------- | ----------- |
| **Free Tier**  | 60              | 1,000         | 10          |
| **Pro Tier**   | 300             | 10,000        | 50          |
| **Enterprise** | 1,000           | 50,000        | 200         |
| **API Keys**   | 500             | 25,000        | 100         |

### Rate Limit Headers

All API responses include rate limit information:

```http
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1642857600
X-RateLimit-Retry-After: 30
```

### Handling Rate Limits

```python
import time
import requests

def make_api_request(url, headers):
    response = requests.get(url, headers=headers)

    if response.status_code == 429:
        # Rate limited - wait and retry
        retry_after = int(response.headers.get('Retry-After', 60))
        print(f"Rate limited. Waiting {retry_after} seconds...")
        time.sleep(retry_after)
        return make_api_request(url, headers)

    return response
```

## Error Handling

### Standard Error Format

All API errors follow a consistent format:

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

### Common Error Codes

| Code                   | HTTP Status | Description                       |
| ---------------------- | ----------- | --------------------------------- |
| `VALIDATION_ERROR`     | 400         | Invalid request data              |
| `AUTHENTICATION_ERROR` | 401         | Invalid or missing authentication |
| `AUTHORIZATION_ERROR`  | 403         | Insufficient permissions          |
| `NOT_FOUND`            | 404         | Resource not found                |
| `RATE_LIMIT_EXCEEDED`  | 429         | Rate limit exceeded               |
| `INTERNAL_ERROR`       | 500         | Internal server error             |

### Error Handling Best Practices

```python
def handle_api_response(response):
    if response.status_code == 200:
        return response.json()

    error_data = response.json().get('error', {})
    correlation_id = error_data.get('correlation_id')

    if response.status_code == 401:
        # Handle authentication error
        raise AuthenticationError(f"Authentication failed: {correlation_id}")
    elif response.status_code == 403:
        # Handle authorization error
        raise AuthorizationError(f"Access denied: {correlation_id}")
    elif response.status_code == 429:
        # Handle rate limiting
        retry_after = response.headers.get('Retry-After', 60)
        raise RateLimitError(f"Rate limited. Retry after {retry_after}s")
    else:
        # Handle other errors
        raise APIError(f"API error: {error_data.get('message')} ({correlation_id})")
```

## Monitoring and Analytics

### API Metrics

Monitor your API usage through our dashboard:

- **Request Volume**: Total requests per time period
- **Response Times**: Average and percentile response times
- **Error Rates**: Success/failure rates by endpoint
- **Rate Limit Usage**: Current usage vs. limits

### Custom Analytics

```python
# Track custom business metrics
client.analytics.track_event('call_completed', {
    'hotel_id': 'hotel_123',
    'call_duration': 180,
    'guest_satisfaction': 5,
    'resolution_type': 'room_service'
})
```

## Support and Resources

### Documentation

- **[API Reference](endpoints.md)** - Complete endpoint documentation
- **[Authentication Guide](authentication.md)** - Security and auth details
- **[Integration Examples](../examples/)** - Code examples and tutorials
- **[Troubleshooting Guide](../operations/troubleshooting-guide.md)** - Common issues and solutions

### Developer Support

- **Email**: developers@voicehive.com
- **Slack**: [VoiceHive Developer Community](https://voicehive-dev.slack.com)
- **GitHub**: [Issues and Feature Requests](https://github.com/voicehive/voicehive-hotels/issues)
- **Status Page**: [status.voicehive.com](https://status.voicehive.com)

### Enterprise Support

- **Dedicated Support**: Available for Enterprise customers
- **SLA**: 99.9% uptime guarantee
- **Response Times**:
  - Critical: < 1 hour
  - High: < 4 hours
  - Medium: < 24 hours

## Changelog and Updates

### Recent Updates

#### v1.2.0 (2025-01-22)

- ✨ Added real-time call monitoring via WebSocket
- 🔒 Enhanced security with MFA support
- 📊 Improved analytics and reporting
- 🐛 Fixed rate limiting edge cases

#### v1.1.0 (2025-01-15)

- ✨ Added webhook signature verification
- 🚀 Improved API response times by 30%
- 📝 Enhanced error messages and correlation IDs
- 🔧 Added new PMS connector for Opera

### Breaking Changes

We maintain backward compatibility and provide 6 months notice for breaking changes. Subscribe to our [developer newsletter](https://voicehive.com/developers/newsletter) for updates.

## Getting Started Checklist

- [ ] Sign up for a VoiceHive account
- [ ] Obtain API credentials
- [ ] Read the [Authentication Guide](authentication.md)
- [ ] Test API calls in sandbox environment
- [ ] Implement webhook endpoints
- [ ] Set up monitoring and error handling
- [ ] Deploy to production
- [ ] Monitor usage and performance

Ready to get started? [Create your account](https://app.voicehive.com/signup) and begin building amazing voice experiences for your hotel guests! 🚀
