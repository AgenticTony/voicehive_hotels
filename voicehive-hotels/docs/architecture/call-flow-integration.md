# VoiceHive Hotels - Call Flow Integration

## Current Integration Status (Sprint 1)

### Call Flow Architecture

```
┌─────────────────┐
│   SIP/PSTN      │
│   Provider      │
└────────┬────────┘
         │
         │ Inbound Call
         ▼
┌─────────────────┐      ┌─────────────────┐
│  LiveKit Cloud  │      │  Orchestrator   │
│   (EU Region)   │      │   Service       │
│                 │      │                 │
│ ┌─────────────┐ │      │ ┌─────────────┐ │
│ │  SIP Room   │ │◄────►│ │CallManager  │ │
│ └─────────────┘ │      │ └─────────────┘ │
│                 │      │                 │
└────────┬────────┘      └────────┬────────┘
         │                         │
         │ WebRTC                  │ HTTP/WebSocket
         ▼                         ▼
┌─────────────────┐      ┌─────────────────┐
│  LiveKit Agent  │      │    Redis        │
│                 │      │  (Call State)   │
│ - Audio Stream  │      └─────────────────┘
│ - Event Handler │               
│ - Webhook Send  │               
└────────┬────────┘               
         │                        
         │ Webhook Events         
         ▼                        
    /v1/livekit/webhook          
    /v1/livekit/transcription    
```

### Event Flow Sequence

1. **Call Initiation**
   ```
   SIP Provider → LiveKit Cloud → Create Room → Spawn Agent
   ```

2. **Agent Ready**
   ```
   LiveKit Agent → POST /v1/livekit/webhook
   {
     "event_type": "agent_ready",
     "call_sid": "room_name",
     "data": {
       "room_name": "...",
       "hotel_id": "..."
     }
   }
   ```

3. **Call Started**
   ```
   LiveKit Agent → POST /v1/livekit/webhook
   {
     "event_type": "call_started",
     "call_sid": "...",
     "data": {
       "participant_sid": "...",
       "is_sip": true
     }
   }
   ```

4. **Audio Streaming**
   ```
   LiveKit Agent → Audio Frames → Riva ASR (pending)
   ```

5. **Transcription**
   ```
   LiveKit Agent → POST /v1/livekit/transcription
   {
     "call_sid": "...",
     "text": "Hello, I need a room",
     "language": "en",
     "confidence": 0.95,
     "is_final": true
   }
   
   Response:
   {
     "status": "processed",
     "call_sid": "...",
     "intent_detected": "request_info"
   }
   ```

6. **Call End**
   ```
   LiveKit Agent → POST /v1/livekit/webhook
   {
     "event_type": "call_ended",
     "call_sid": "...",
     "data": {
       "reason": "participant_disconnected"
     }
   }
   ```

### Integration Points

#### Completed ✅
- LiveKit Agent webhook notifications
- Orchestrator webhook endpoints
- CallManager event processing
- Redis state storage integration
- Basic intent recognition

#### Pending 🔄
- Riva ASR gRPC connection
- Azure OpenAI GPT-4 integration
- ElevenLabs TTS streaming
- Audio frame processing
- Response playback to caller

### Security & Compliance

- **Data Residency**: All services in EU regions
- **Encryption**: TLS for all HTTP/WebSocket connections
- **PII Handling**: Call metadata hashed/encrypted
- **Audit Logging**: Structured JSON logs for all events
- **GDPR**: 30-day retention for metadata, 7-day for recordings

### Next Steps

1. Complete Riva ASR deployment and gRPC integration
2. Implement LLM response generation in CallManager
3. Add TTS streaming from ElevenLabs
4. Create audio playback pipeline in LiveKit Agent
5. Implement proper error handling and retries
6. Add comprehensive metrics and monitoring

### Testing Strategy

1. **Unit Tests**: CallManager, intent recognition
2. **Integration Tests**: Webhook flows, state transitions
3. **Load Tests**: Concurrent webhook processing
4. **End-to-End**: Full call flow with mock services
