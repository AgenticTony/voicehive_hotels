# Sprint 1: Core Voice Pipeline
**Duration**: 5 days (Week 2)  
**Start Date**: 2025-09-05  
**Goal**: End-to-end call flow with real AI services

## 🎯 Sprint Objectives

Build a functional voice AI receptionist that can:
1. Accept incoming calls via SIP/PSTN
2. Perform multilingual speech recognition
3. Process guest intents and query PMS data
4. Generate natural responses with TTS
5. Handle barge-in and call flow interruptions

## 📋 User Stories & Tasks

### 1. LiveKit Cloud Setup (Day 1)
**Story**: As a hotel, I want calls routed through a reliable media server with EU data residency

**Tasks**:
- [ ] Create LiveKit Cloud account with EU region
- [ ] Configure SIP trunk integration
- [ ] Set up LiveKit SDK authentication
- [ ] Create LiveKit Agent for call handling
- [ ] Implement WebRTC/SIP bridge configuration
- [ ] Test inbound/outbound call routing

**Acceptance Criteria**:
- Calls route successfully through LiveKit EU servers
- SIP trunk connected and tested
- Authentication tokens properly managed via Vault

### 2. NVIDIA Riva ASR Deployment (Day 1-2)
**Story**: As a guest, I want the system to understand my speech in multiple languages

**Tasks**:
- [ ] Deploy Riva server on GPU nodes
- [ ] Configure Parakeet/Canary models for multilingual support
- [ ] Create ASR proxy service (gRPC → HTTP)
- [ ] Implement language detection logic
- [ ] Add streaming transcription support
- [ ] Configure endpointing/VAD settings

**Acceptance Criteria**:
- ASR latency < 250ms TTFB
- Supports EN, DE, ES, FR, IT at minimum
- Accurate transcription with hotel domain vocabulary

### 3. Orchestrator Core Logic (Day 2-3)
**Story**: As a system, I need to coordinate between media, ASR, NLU, and TTS components

**Tasks**:
- [ ] Create FastAPI orchestrator service
- [ ] Implement LiveKit webhook handlers
- [ ] Add call state management (Redis)
- [ ] Integrate with PMS connector factory
- [ ] Create intent detection logic
- [ ] Add conversation context tracking

**Acceptance Criteria**:
- Orchestrator handles full call lifecycle
- PMS data retrieved successfully
- Intent routing works for common queries

### 4. LLM Integration (Day 3)
**Story**: As a guest, I want natural conversational responses to my questions

**Tasks**:
- [ ] Integrate Azure OpenAI GPT-4
- [ ] Create prompt templates for hotel context
- [ ] Implement function calling for PMS queries
- [ ] Add conversation memory
- [ ] Create fallback responses
- [ ] Add response validation/safety checks

**Acceptance Criteria**:
- Responses are concise and helpful
- PMS data correctly incorporated
- No hallucinations about hotel services

### 5. ElevenLabs TTS Integration (Day 3-4)
**Story**: As a hotel, I want guests to hear natural-sounding responses

**Tasks**:
- [ ] Set up ElevenLabs API integration
- [ ] Configure multilingual voice models
- [ ] Implement streaming TTS
- [ ] Add voice cloning consent workflow
- [ ] Create TTS caching layer
- [ ] Add fallback to Azure TTS

**Acceptance Criteria**:
- TTS latency < 250ms TTFB
- Natural prosody and pronunciation
- Voice matches language of caller

### 6. Barge-in & Call Control (Day 4)
**Story**: As a guest, I want to interrupt the system if it misunderstands

**Tasks**:
- [ ] Implement barge-in detection
- [ ] Add utterance cancellation logic
- [ ] Create phrase endpointing
- [ ] Handle call transfers
- [ ] Add hold/resume functionality
- [ ] Implement graceful hangup

**Acceptance Criteria**:
- Barge-in response < 100ms
- Clean audio interruption
- No audio artifacts or echoes

### 7. Monitoring & Observability (Day 4-5)
**Story**: As an operator, I need to monitor call quality and system health

**Tasks**:
- [ ] Add Prometheus metrics for call flow
- [ ] Create Grafana dashboard for voice pipeline
- [ ] Implement distributed tracing
- [ ] Add call recording with PII redaction
- [ ] Create quality scoring metrics
- [ ] Set up alerting rules

**Acceptance Criteria**:
- Real-time visibility into call metrics
- P95 latencies tracked per component
- Call recordings available for review

### 8. Integration Testing (Day 5)
**Story**: As a developer, I need confidence the system works end-to-end

**Tasks**:
- [ ] Create call simulation harness
- [ ] Add multilingual test scenarios
- [ ] Test error paths and fallbacks
- [ ] Load test with 10 concurrent calls
- [ ] Validate GDPR compliance
- [ ] Document call flows

**Acceptance Criteria**:
- All test scenarios pass
- System handles 10 concurrent calls
- Meets latency SLOs

## 📊 Sprint Metrics

### Technical Goals
- **P95 Round-trip latency**: ≤ 500ms
- **ASR TTFB**: ≤ 250ms  
- **TTS TTFB**: ≤ 250ms
- **Barge-in response**: ≤ 100ms
- **Concurrent calls**: 10+

### Quality Targets
- **Word Error Rate**: < 15% for supported languages
- **Intent Accuracy**: > 90% for common queries
- **Call Completion Rate**: > 85%
- **Mean Opinion Score**: > 4.0

## 🏗️ Architecture Decisions

1. **LiveKit Cloud** vs self-hosted: Cloud for reliability, EU region for compliance
2. **NVIDIA Riva** for ASR: Best multilingual accuracy with on-prem control  
3. **Azure OpenAI** for NLU: Function calling + low latency
4. **ElevenLabs** for TTS: Most natural voices, with Azure fallback
5. **Redis** for state: Fast call context storage
6. **gRPC** for Riva: Native protocol with streaming support

## 🚧 Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| GPU availability | High | Reserve instances, have CPU fallback |
| LiveKit latency | Medium | Use closest EU region, optimize codec |
| Model cold start | Medium | Keep models warm, use smaller variants |
| Language detection errors | Low | Implement confidence thresholds |

## 📦 Deliverables

1. **Working voice pipeline** handling real calls
2. **Multilingual support** for 5+ languages
3. **PMS integration** via connector SDK
4. **Call quality dashboard** in Grafana
5. **Integration test suite** with recordings
6. **Deployment runbook** for production

## 🎯 Definition of Done

- [ ] Successful multilingual call with PMS lookup
- [ ] All components deployed to Kubernetes  
- [ ] Monitoring dashboards operational
- [ ] Integration tests passing
- [ ] Documentation updated
- [ ] Security scan clean
- [ ] Sprint review demo prepared

## 👥 Team Allocation

- **Media/LiveKit**: Full stack engineer
- **ASR/TTS**: ML engineer  
- **Orchestrator**: Backend engineer
- **Integration**: DevOps engineer
- **Testing**: QA engineer

---

**Note**: Daily standups at 10 AM CET. Update JIRA/Linear tickets by EOD.
