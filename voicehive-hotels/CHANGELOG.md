# VoiceHive Hotels Changelog

## [Sprint 1 - Day 1] - 2025-09-05

### Added
- **TTS Latency Metrics** - Prometheus histogram tracking P95 latency with appropriate buckets
  - `voicehive_tts_synthesis_duration_seconds{language,engine,cached}`
  - `voicehive_tts_synthesis_total{language,engine,status}`
  - `voicehive_tts_synthesis_errors{language,error_type}`
- **Safe Logging Adapter** - Unified logging that works with both structlog and stdlib
  - Handles special kwargs (exc_info, stack_info, stacklevel) correctly
  - Prevents runtime errors from incompatible logging calls
- **Comprehensive Test Suite**
  - `test_logging_adapter.py` - Validates safe logger behavior
  - `test_call_event_endpoint.py` - CallEvent webhook handling
  - `test_tenacity_retry.py` - Retry configuration
  - `test_tts_metrics.py` - TTS metrics instrumentation
- **Modular Architecture** (in progress)
  - Split app.py into: models.py, config.py, security.py, lifecycle.py
  - Created routers: webhook.py, gdpr.py

### Changed
- **CallEvent Model** - Fixed field naming to match schema
  - `event_type` → `event` in webhook handlers
  - timestamp now correctly uses float instead of string
  - Added required `room_name` field
- **Tenacity Retry Strategy** - Updated to current best practices
  - Replaced deprecated `wait_exponential_jitter` with `wait_random_exponential`
  - Added `reraise=True` for proper error propagation
- **Pydantic v2 Migration**
  - Updated validators from `@validator` to `@field_validator` with `@classmethod`
- **Logging Improvements**
  - All services now use SafeLogger adapter
  - Structured logging with event-first pattern
  - No more bare kwargs with stdlib logger

### Fixed
- Runtime errors from incompatible logging calls
- CallEvent creation bugs in webhook endpoints
- Deprecated Tenacity retry configurations
- Pydantic v1 deprecation warnings
- Circular import issues with PIIRedactor

### Removed
- Unused `call_external_service` function
- Unused imports (base64 in tts_client.py)
- Unused `default_voices` dictionary
- Redundant code to keep files under 500 lines

### Security
- All logging now properly redacts PII
- Webhook authentication validates Bearer tokens
- Encryption service uses Fernet symmetric encryption

### Performance
- TTS latency now tracked for SLO monitoring
- Redis caching in TTS Router reduces latency
- Proper retry strategies prevent cascade failures

## [Sprint 1 - Day 1 Morning] - 2025-09-05

### Added
- Complete TTS Router service with ElevenLabs/Azure routing
- NVIDIA Riva ASR proxy with streaming support
- LiveKit Agent with SIP participant handling
- Azure OpenAI GPT-4 integration with function calling
- PMS function definitions (check_availability, get_reservation, get_hotel_info)

### Infrastructure
- Docker containers for all services
- Prometheus metrics endpoints
- Health check endpoints
- EU region configuration

---

*For full sprint details, see `docs/sprints/sprint-1-day1-evening-update.md`*
