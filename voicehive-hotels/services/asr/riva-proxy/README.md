# NVIDIA Riva ASR Proxy Service

HTTP/WebSocket proxy for NVIDIA Riva speech recognition with EU compliance.

## Overview

This service provides a simplified HTTP/WebSocket API wrapper around NVIDIA Riva's gRPC-based ASR service, enabling:
- Offline (batch) transcription
- Real-time streaming transcription via WebSocket
- Automatic language detection
- Prometheus metrics and health monitoring

## API Endpoints

### Health Check
```
GET /health
```

### Metrics (Prometheus)
```
GET /metrics
```

### Offline Transcription
```
POST /transcribe
Content-Type: application/json

{
  "audio_data": "base64_encoded_audio",
  "language": "en-US",
  "sample_rate": 16000,
  "encoding": "LINEAR16",
  "enable_punctuation": true
}
```

Response:
```json
{
  "transcript": "Hello, I would like to make a reservation",
  "confidence": 0.95,
  "language": "en-US",
  "processing_time_ms": 145.2
}
```

### Streaming Transcription (WebSocket)
```
WS /transcribe-stream
```

Protocol:
1. Connect to WebSocket
2. Send configuration:
```json
{
  "type": "config",
  "language": "en-US",
  "sample_rate": 16000
}
```

3. Stream audio chunks:
```json
{
  "type": "audio",
  "audio": "base64_encoded_chunk"
}
```

4. Receive transcriptions:
```json
{
  "type": "partial",
  "transcript": "Hello, I would",
  "confidence": 0.92,
  "is_final": false,
  "language": "en-US"
}
```

5. End stream:
```json
{
  "type": "end_of_stream"
}
```

### Language Detection
```
POST /detect-language
Content-Type: application/json

{
  "audio_data": "base64_encoded_audio",
  "sample_rate": 16000
}
```

Response:
```json
{
  "detected_language": "de-DE",
  "confidence": 0.87,
  "alternatives": [
    {"language": "nl-NL", "confidence": 0.12},
    {"language": "en-US", "confidence": 0.08}
  ]
}
```

### Supported Languages
```
GET /supported-languages
```

## Configuration

Environment variables:
- `RIVA_SERVER_HOST`: Riva server hostname (default: "riva-server")
- `RIVA_SERVER_PORT`: Riva server gRPC port (default: 50051)

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Start the service
python server.py
```

## Docker

```bash
# Build
docker build -t voicehive/riva-proxy .

# Run
docker run -p 51051:51051 \
  -e RIVA_SERVER_HOST=riva.example.com \
  voicehive/riva-proxy
```

## Metrics

Prometheus metrics available at `/metrics`:
- `asr_requests_total`: Total ASR requests by language, type, and status
- `asr_request_duration_seconds`: Request duration histogram
- `asr_active_streams`: Number of active streaming connections

## Error Handling

All errors return standard HTTP status codes with JSON error messages:
```json
{
  "error": "Transcription failed",
  "detail": "Riva server connection timeout"
}
```

## GDPR Compliance

- No audio data is persisted
- All logs use structured format without PII
- Metrics contain no personally identifiable information
- EU region deployment only
