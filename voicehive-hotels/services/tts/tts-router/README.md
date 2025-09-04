# TTS Router Service

Intelligent text-to-speech routing with caching and multi-engine support.

## Overview

The TTS Router service provides a unified API for text-to-speech synthesis, intelligently routing requests between multiple TTS engines based on language, voice preferences, and availability. Features include:

- Multi-engine support (ElevenLabs, Azure Speech Service)
- Redis-based caching for performance
- Voice mapping per locale
- Emotion and parameter control
- Prometheus metrics

## API Endpoints

### Health Check
```
GET /health
```

### Metrics (Prometheus)
```
GET /metrics
```

### Speech Synthesis
```
POST /synthesize
Content-Type: application/json

{
  "text": "Welcome to the Grand Hotel. How may I assist you today?",
  "voice": "rachel",
  "language": "en-US",
  "speed": 1.0,
  "pitch": 1.0,
  "emotion": "friendly",
  "format": "mp3",
  "cache": true
}
```

Response:
```json
{
  "audio_base64": "base64_encoded_audio",
  "format": "mp3",
  "duration_ms": 2450,
  "cached": false,
  "voice_used": "rachel",
  "engine": "elevenlabs"
}
```

### List Available Voices
```
GET /voices?language=en-US
```

Response:
```json
{
  "voices": [
    {
      "id": "rachel",
      "name": "Rachel",
      "language": "en-US",
      "engine": "elevenlabs",
      "gender": "female",
      "preview_url": "https://..."
    },
    {
      "id": "en-US-JennyNeural",
      "name": "Jenny",
      "language": "en-US", 
      "engine": "azure",
      "gender": "female"
    }
  ]
}
```

## Voice Mapping

Default voice mapping per locale (configurable):

| Language | Engine | Voice ID | Notes |
|----------|---------|----------|--------|
| en-US | elevenlabs | rachel | Premium natural voice |
| en-GB | elevenlabs | charlotte | British accent |
| de-DE | azure | de-DE-KatjaNeural | German female |
| es-ES | elevenlabs | bella | Spanish female |
| fr-FR | azure | fr-FR-DeniseNeural | French female |
| it-IT | elevenlabs | alice | Italian female |

## Configuration

Environment variables:
- `ELEVENLABS_API_KEY`: ElevenLabs API key (required)
- `AZURE_SPEECH_KEY`: Azure Speech Service key (optional)
- `AZURE_SPEECH_REGION`: Azure region (default: westeurope)
- `REDIS_URL`: Redis connection URL (default: redis://localhost:6379)
- `CACHE_ENABLED`: Enable caching (default: true)
- `CACHE_TTL`: Cache TTL in seconds (default: 3600)

## Caching Strategy

- Audio files are cached with a hash of: text + voice + language + parameters
- Cache hit ratio tracked in metrics
- Automatic cache eviction based on TTL
- Optional cache bypass with `cache: false` in request

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ELEVENLABS_API_KEY=your_key_here
export REDIS_URL=redis://localhost:6379

# Start the service
python server.py
```

## Docker

```bash
# Build
docker build -t voicehive/tts-router .

# Run
docker run -p 9002:9002 \
  -e ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY \
  -e REDIS_URL=redis://redis:6379 \
  voicehive/tts-router
```

## Metrics

Prometheus metrics available at `/metrics`:
- `tts_synthesis_requests_total`: Total synthesis requests
- `tts_synthesis_duration_seconds`: Synthesis duration
- `tts_cache_hits_total`: Cache hit count
- `tts_cache_misses_total`: Cache miss count
- `tts_engine_errors_total`: Errors by engine

## Error Handling

Automatic fallback between engines:
1. Try primary engine for locale
2. Fallback to secondary engine
3. Return mock audio in development mode

Error responses:
```json
{
  "error": "Synthesis failed",
  "detail": "All engines unavailable",
  "fallback_attempted": true
}
```

## Voice Cloning

Voice cloning requires explicit consent:
```json
{
  "text": "Hello",
  "voice": "custom_voice_id",
  "voice_clone": {
    "consent_id": "consent_12345",
    "watermark": true
  }
}
```

## GDPR Compliance

- No text content is logged
- Cache keys use hashed values
- Metrics contain no PII
- EU-only deployment
