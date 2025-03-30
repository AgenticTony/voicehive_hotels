# Acuity Voice Agent

A Node.js application that integrates Acuity Scheduling API with voice AI agents using OAuth2 authentication.

## Features

- OAuth 2.0 authentication with Acuity Scheduling
- Token management (refresh, expiry, revocation)
- API endpoints for booking appointments
- Availability checking
- Appointment type listing
- Secure integration with Retell AI or other voice agents

## Tech Stack

- Node.js with Express
- MongoDB for data storage
- Acuity Scheduling API
- OAuth 2.0 for API authentication

## Setup

1. Clone the repository:

   ```
   git clone <repository-url>
   cd acuity-voice-agent
   ```

2. Install dependencies:

   ```
   npm install
   ```

3. Create a `.env` file based on `.env.example`:

   ```
   cp .env.example .env
   ```

4. Edit the `.env` file with your credentials:

   - Acuity Scheduling OAuth2 credentials (client ID, client secret)
   - MongoDB URI
   - JWT secret (for token generation)
   - Retell API key (for voice agent integration)

5. Start the server:
   ```
   npm start
   ```

For development mode with automatic restarts:

```
npm run dev
```

## OAuth2 Flow

This application uses the OAuth2 authorization code flow to authenticate with Acuity Scheduling:

1. A user/client initiates the OAuth2 flow by calling `/oauth/authorize`
2. They are redirected to Acuity's authorization page
3. After authorizing, they are redirected back to the callback URL
4. The application exchanges the authorization code for an access token
5. The token is stored and used for API calls
6. The application handles token refreshing automatically

## API Endpoints

### OAuth

- **GET /oauth/authorize** - Generate an authorization URL for Acuity OAuth flow
- **GET /oauth/callback** - Callback endpoint for OAuth flow
- **POST /oauth/disconnect** - Revoke an OAuth token

### API (Authenticated)

- **POST /api/book** - Book an appointment
- **GET /api/appointment-types** - Get available appointment types
- **GET /api/availability** - Check availability for an appointment type

## Authentication

All API endpoints are protected with API key authentication. Include the Retell API key in the `x-api-key` header.

## Client Identifier

Each client that connects to Acuity Scheduling will have a unique `client_identifier` which is used to associate with their OAuth token. This identifier is passed in all API requests to determine which Acuity account to use.

## Development

For running tests:

```
npm test
```

## License

ISC
