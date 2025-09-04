# Sprint 1 Quick Reference Card 🎙️

## Current Focus: Core Voice Pipeline

### Day 1 Priorities 🎯
1. **LiveKit Cloud Setup** - EU region, SIP trunk
2. **NVIDIA Riva Deployment** - GPU nodes, model serving
3. **Project Structure** - Create service directories

### Key Components 🔧

#### LiveKit Agent
```bash
# Location
services/media/livekit-agent/
├── agent.py          # Main agent logic
├── requirements.txt  # Dependencies
├── Dockerfile        # Container definition
└── config.yaml       # LiveKit settings

# Key Features
- SIP/PSTN bridge
- WebRTC handling  
- Audio streaming
- Event webhooks
```

#### Riva ASR Service
```bash
# Location  
services/asr/riva-proxy/
├── server.py         # gRPC to HTTP proxy
├── models.py         # Request/response models
├── language.py       # Language detection
└── streaming.py      # Audio streaming logic

# Models
- Parakeet (EN) - Fastest
- Canary (Multilingual) - Most accurate
```

#### Orchestrator Updates
```bash
# Location
services/orchestrator/
├── app.py            # Main FastAPI app
├── call_manager.py   # Call state management
├── intents.py        # Intent detection
└── llm_client.py     # Azure OpenAI integration

# New Endpoints
POST /call/start      # Initialize call
POST /call/event      # LiveKit webhooks
POST /call/end        # Cleanup call
```

### Environment Variables 🔐

```bash
# LiveKit Cloud (Project-specific URL)
LIVEKIT_URL=wss://<project>.livekit.cloud  # Get from LiveKit Cloud dashboard
LIVEKIT_API_KEY=<from-vault>
LIVEKIT_API_SECRET=<from-vault>
LIVEKIT_WEBHOOK_KEY=<from-vault>

# SIP Region Configuration
# For EU region: {sip_subdomain}.eu.sip.livekit.cloud
LIVEKIT_SIP_REGION=eu

# NVIDIA Riva
RIVA_SERVER_HOST=riva-server.voicehive.svc.cluster.local
RIVA_SERVER_PORT=50051
RIVA_MODEL_NAME=canary-1.0

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://voicehive-eu.openai.azure.com
AZURE_OPENAI_KEY=<from-vault>
AZURE_OPENAI_DEPLOYMENT=gpt-4-turbo

# ElevenLabs
ELEVENLABS_API_KEY=<from-vault>
ELEVENLABS_VOICE_ID=<multilingual-model>

# Redis
REDIS_URL=redis://redis.voicehive.svc.cluster.local:6379
```

### Common Commands 🛠️

```bash
# LiveKit Testing
livekit-cli create-room --url $LIVEKIT_URL --api-key $LIVEKIT_API_KEY
livekit-cli list-participants --room test-room

# Riva Health Check
grpcurl -plaintext riva-server:50051 nvidia.riva.health.v1.Health/Check

# Test Call Flow
python tools/call-simulator/simulate_voice.py \
  --sip-uri "sip:test@voicehive.eu" \
  --audio-file "samples/hotel_booking_en.wav"

# Monitor GPU Usage
kubectl exec -n voicehive deployment/riva-server -- nvidia-smi

# Check Orchestrator Logs
kubectl logs -n voicehive deployment/orchestrator -f | jq .
```

### Architecture Flow 📐

```
[Caller] → [SIP/PSTN] → [LiveKit Cloud EU]
                              ↓
                        [LiveKit Agent]
                              ↓
                    [Audio Stream Split]
                         ↙          ↘
                [Riva ASR]          [VAD/Endpointing]
                     ↓                      ↓
              [Transcription]         [Barge-in Signal]
                     ↓                      ↓
                        [Orchestrator]
                         ↙     ↓     ↘
              [PMS Query] [Azure AI] [Context]
                         ↘     ↓     ↙
                          [Response]
                              ↓
                        [ElevenLabs TTS]
                              ↓
                        [LiveKit Agent]
                              ↓
                          [Caller]
```

### Sprint 1 Checklist ✓

#### Day 1 ☐
- [ ] LiveKit account created
- [ ] SIP trunk configured
- [ ] GPU nodes provisioned
- [ ] Riva container deployed
- [ ] Basic agent skeleton

#### Day 2 ☐
- [ ] Riva models loaded
- [ ] ASR proxy working
- [ ] Orchestrator skeleton
- [ ] Redis deployed
- [ ] Call state management

#### Day 3 ☐
- [ ] Azure OpenAI integrated
- [ ] Intent detection working
- [ ] ElevenLabs connected
- [ ] Basic conversation flow

#### Day 4 ☐
- [ ] Barge-in implemented
- [ ] Monitoring added
- [ ] Grafana dashboard
- [ ] Error handling

#### Day 5 ☐
- [ ] Integration tests
- [ ] Load testing (10 calls)
- [ ] Documentation complete
- [ ] Demo prepared

### Key Metrics 📊

Track these in Prometheus/Grafana:

```promql
# ASR Latency
histogram_quantile(0.95, asr_request_duration_seconds_bucket)

# TTS Latency  
histogram_quantile(0.95, tts_request_duration_seconds_bucket)

# Active Calls
active_calls_total

# Call Success Rate
sum(rate(call_completed_total[5m])) / sum(rate(call_started_total[5m]))
```

### Troubleshooting 🔍

**LiveKit Connection Issues**
```bash
# Check agent logs
kubectl logs -n voicehive deployment/livekit-agent -f

# Verify webhook endpoint
curl -X POST http://orchestrator:8080/call/event \
  -H "Authorization: Bearer $LIVEKIT_WEBHOOK_KEY"
```

**Riva Performance**
```bash
# Check model status
grpcurl -plaintext riva-server:50051 nvidia.riva.asr.RivaSpeechRecognition/List

# Monitor GPU memory
watch -n 1 'kubectl exec -n voicehive deployment/riva-server -- nvidia-smi'
```

**Call Quality Issues**
- Check network latency to LiveKit EU
- Verify audio codec settings (Opus preferred)
- Monitor packet loss and jitter
- Review barge-in threshold settings

### Important Notes 📝

1. **EU Data Residency**: Ensure LiveKit room is created in EU region
2. **GPU Scheduling**: Use node selectors for Riva pods
3. **Secrets**: All API keys via Vault, not hardcoded
4. **Monitoring**: Add metrics for every external call
5. **Testing**: Record sample calls for regression tests

---

**Remember**: Check `docs/sprints/sprint-1-status.md` for latest updates!
