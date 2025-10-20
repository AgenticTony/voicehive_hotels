# Circuit Breaker Integration Analysis for VoiceHive Hotels

## Executive Summary

This analysis identifies PMS connector implementations, ASR service clients, database connections, and external HTTP calls that require circuit breaker protection in the VoiceHive Hotels codebase.

**Key Finding:** Circuit breaker infrastructure exists but is not consistently applied to all critical external service calls.

---

## 1. PMS Connector Implementations

### 1.1 Apaleo Connector (Primary Implementation)

**File:** `/connectors/adapters/apaleo/connector.py`

**HTTP Client:** `httpx.AsyncClient`

**Key Methods Requiring Circuit Breaker:**

| Method | External Service | Risk Level |
|--------|-----------------|-----------|
| `_authenticate()` | OAuth2 Token Service | CRITICAL |
| `_request()` | Apaleo REST APIs | CRITICAL |
| `get_availability()` | `/availability/v1/unit-groups` | HIGH |
| `quote_rate()` | `/rateplan/v1/rate-plans` | HIGH |
| `create_reservation()` | `/booking/v1/bookings` | CRITICAL |
| `get_reservation()` | `/booking/v1/bookings` | HIGH |
| `modify_reservation()` | `/booking/v1/bookings` (PATCH) | HIGH |
| `cancel_reservation()` | `/booking/v1/bookings` (PATCH) | HIGH |
| `search_guest()` | `/booking/v1/bookings` (query) | MEDIUM |
| `get_guest_profile()` | Booking search chain | MEDIUM |
| `stream_arrivals()` | `/booking/v1/bookings` (query) | MEDIUM |
| `stream_in_house()` | `/booking/v1/bookings` (query) | MEDIUM |
| `get_folio_from_reservation()` | `/finance/v1/folios` | HIGH |
| `authorize_payment()` | `/finance/v1/folios/{id}/payments` | CRITICAL |
| `capture_payment()` | `/finance/v1/folios/{id}/payments` | CRITICAL |
| `refund_payment()` | `/finance/v1/folios/{id}/refunds` | CRITICAL |

**Current Protection:**
- Has retry logic with `@retry(stop_after_attempt(3), wait=wait_exponential(...))`
- Rate limiting handling (429 detection)
- Token refresh mechanism
- **MISSING:** Circuit breaker for cascading failure prevention

**Current Retry Strategy:**
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
async def _request(self, method: str, path: str, **kwargs):
```

**Issue:** Retry logic only helps with transient failures. During sustained outages, continuous retries waste resources and increase response times.

---

### 1.2 Other PMS Connectors (Not Yet Implemented)

**Expected Files:**
- `connectors/adapters/mews/connector.py` (Not found)
- `connectors/adapters/opera/connector.py` (Not found)

**Status:** Only Apaleo implemented; Mews and Oracle OPERA planned but not yet created.

---

## 2. ASR (Automatic Speech Recognition) Service Implementations

### 2.1 NVIDIA Riva ASR Proxy

**File:** `/services/asr/riva-proxy/server.py`

**Service Connection:** gRPC to Riva Server

**Key Methods Requiring Circuit Breaker:**

| Method | External Service | Risk Level |
|--------|-----------------|-----------|
| `_connect_to_riva()` | Riva gRPC Server | CRITICAL |
| `_ensure_connection()` | Riva Connection Check | HIGH |
| `transcribe_offline()` | Riva ASR Service | CRITICAL |
| `detect_language()` | Riva Language Detection | HIGH |
| `transcribe_stream()` (WebSocket) | Riva Streaming | CRITICAL |

**Current Protection:**
- Connection health checking
- Reconnection attempts on failure (in `transcribe_offline` and `detect_language`)
- **MISSING:** Circuit breaker for preventing cascading failures

**Example Current Pattern:**
```python
try:
    response = self.asr_service.offline_recognize(audio_bytes, config)
except Exception as riva_error:
    logger.warning("Riva call failed, attempting reconnection")
    self.connection_healthy = False
    self._ensure_connection()
    response = self.asr_service.offline_recognize(audio_bytes, config)
```

**Issue:** Retry on reconnection can still lead to resource exhaustion during extended outages.

---

### 2.2 NVIDIA Granary ASR Proxy

**File:** `/services/asr/granary-proxy/server.py`

**Service Connection:** Local NeMo Model (In-process, not external)

**Key Methods:**

| Method | Risk Level | Note |
|--------|-----------|------|
| `_load_model()` | MEDIUM | Model loading, not external call |
| `_ensure_model_loaded()` | MEDIUM | Reload mechanism |
| `transcribe_offline()` | LOW | No external service |
| `detect_language()` | LOW | No external service |

**Current Protection:** Not needed for external calls (model is in-process)

---

## 3. Database Connection Management

### 3.1 PostgreSQL Database Connection

**File:** `/services/orchestrator/database/connection.py`

**Connection Type:** SQLAlchemy AsyncPg

**Key Configuration:**
```python
self.engine = create_async_engine(
    database_url,
    poolclass=QueuePool,
    pool_size=db_config.pool_size,
    max_overflow=db_config.max_overflow,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args={
        "statement_timeout": "30000",  # 30 seconds
        "lock_timeout": "10000",        # 10 seconds
        "idle_in_transaction_session_timeout": "300000",
    }
)
```

**Current Protection:**
- Connection pooling with queue-based management
- Pre-ping to validate connections
- Statement timeouts at DB level
- **MISSING:** Application-level circuit breaker for connection exhaustion

**Risk Areas:**
- Pool exhaustion during high load
- Cascading failures when DB is slow/unresponsive
- No automatic fallback mechanism

---

## 4. Existing Circuit Breaker Implementation

### 4.1 Circuit Breaker Framework

**File:** `/services/orchestrator/circuit_breaker.py`

**Features Implemented:**
- States: CLOSED, OPEN, HALF_OPEN (Hystrix pattern)
- Configurable failure threshold (default: 5)
- Recovery timeout with exponential backoff (default: 60s)
- Redis persistence for distributed systems
- Fallback function support
- Request timeout protection
- Decorator pattern for easy application

**Test Coverage:**
- File: `/services/orchestrator/tests/test_circuit_breaker.py`
- Tests: State transitions, failure tracking, recovery, timeout handling

**Current Usage Locations:**
- Framework exists but appears to be underutilized
- Not applied to Apaleo connector critical operations
- Not applied to ASR service connections
- Not applied to database operations

---

## 5. Service Client HTTP Patterns

### 5.1 TTS Client

**File:** `/services/orchestrator/tts_client.py`

**HTTP Client:** `httpx.AsyncClient`

**Key Method:**
```python
async def synthesize(
    self,
    text: str,
    language: str = "en-US",
    voice_id: Optional[str] = None,
    ...
) -> TTSSynthesisResponse:
```

**Current Protection:**
- Retry logic: `@retry(stop_after_attempt(3), wait=wait_random_exponential(...))`
- Timeout: 30 seconds
- **MISSING:** Circuit breaker

**HTTP Call Pattern:**
```python
response = await self.http_client.post(
    f"{self.tts_url}/synthesize",
    json=request.model_dump()
)
```

---

### 5.2 Vault Client (Secret Management)

**File:** `/services/orchestrator/vault_client.py`

**Purpose:** Retrieve secrets from HashiCorp Vault

**HTTP Operations:**
- Token authentication
- Secret retrieval
- Secret rotation

**Current Protection:** Needs investigation (not fully analyzed)

---

## 6. Database Query Operations

### 6.1 Repository Layer

**File:** `/services/orchestrator/database/repository.py`

**Operations:**
- User CRUD operations
- Authentication state queries
- Session management

**Risk Level:** MEDIUM - Database queries are often the first to fail under load

**Current Protection:**
- SQLAlchemy connection pooling
- Transaction management
- **MISSING:** Circuit breaker at application layer

---

## 7. External HTTP Calls Summary

### High-Risk, Unprotected External Calls:

| Service | Endpoint | Current Protection | Circuit Breaker Needed |
|---------|----------|-------------------|----------------------|
| Apaleo | `/identity.apaleo.com` (auth) | Retry | YES - CRITICAL |
| Apaleo | `/api.apaleo.com/*` (all APIs) | Retry | YES - CRITICAL |
| Riva ASR | gRPC service | Reconnect | YES - CRITICAL |
| TTS Router | `/synthesize` | Retry | YES - HIGH |
| Vault | `/auth/token/renew` | Unknown | YES - HIGH |

---

## 8. Recommended Circuit Breaker Integration

### 8.1 Priority 1: Apaleo Connector (CRITICAL)

**File to Modify:** `/connectors/adapters/apaleo/connector.py`

**Recommended Implementation:**
```python
from circuit_breaker import CircuitBreaker, CircuitBreakerConfig

# At class initialization
self._auth_breaker = CircuitBreaker(
    CircuitBreakerConfig(
        name="apaleo_auth",
        failure_threshold=3,
        recovery_timeout=60,
        timeout=30.0,
        expected_exception=(AuthenticationError, httpx.HTTPError)
    )
)

self._api_breaker = CircuitBreaker(
    CircuitBreakerConfig(
        name="apaleo_api",
        failure_threshold=5,
        recovery_timeout=120,
        timeout=30.0,
        expected_exception=(PMSError, httpx.HTTPError, RateLimitError)
    )
)

# Wrap critical methods
async def _request(self, method: str, path: str, **kwargs):
    return await self._api_breaker.call(
        self._do_request, method, path, **kwargs
    )
```

### 8.2 Priority 2: ASR Service Connections (CRITICAL)

**File to Modify:** `/services/asr/riva-proxy/server.py`

```python
class ASRService:
    def __init__(self):
        self._connection_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="riva_connection",
                failure_threshold=3,
                recovery_timeout=30,
                timeout=10.0,
                expected_exception=(Exception,)
            )
        )
        self._transcribe_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="riva_transcription",
                failure_threshold=5,
                recovery_timeout=60,
                timeout=30.0,
                expected_exception=(Exception,)
            )
        )
```

### 8.3 Priority 3: TTS Client (HIGH)

**File to Modify:** `/services/orchestrator/tts_client.py`

```python
class TTSClient:
    def __init__(self):
        self._synthesis_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="tts_synthesis",
                failure_threshold=5,
                recovery_timeout=60,
                timeout=30.0,
                expected_exception=(httpx.HTTPError,)
            )
        )
```

### 8.4 Priority 4: Database Connections (MEDIUM)

**File to Modify:** `/services/orchestrator/database/connection.py`

```python
class DatabaseManager:
    def __init__(self):
        self._query_breaker = CircuitBreaker(
            CircuitBreakerConfig(
                name="database_query",
                failure_threshold=10,
                recovery_timeout=30,
                timeout=30.0,
                expected_exception=(SQLAlchemyError,)
            )
        )

    async def execute_query(self, query):
        return await self._query_breaker.call(
            self._do_execute_query, query
        )
```

---

## 9. Testing Requirements

### 9.1 Unit Tests Needed:

1. **Circuit Breaker Activation:**
   - Verify breaker opens after failure threshold
   - Verify fallback function is called when circuit is open
   - Verify recovery timeout is respected

2. **Service Degradation:**
   - When Apaleo is down, verify graceful degradation
   - When ASR is down, verify alternative handling
   - When TTS is down, verify request rejection with appropriate error

3. **Metrics Collection:**
   - Track circuit breaker state transitions
   - Track failure rates before opening
   - Track recovery success rates

### 9.2 Integration Tests Needed:

1. **Cascade Prevention:**
   - Simulate downstream service failures
   - Verify upstream services don't cascade failures
   - Verify graceful error responses to clients

2. **Recovery Testing:**
   - Simulate temporary service outages
   - Verify automatic recovery after timeout
   - Verify successful reconnection in HALF_OPEN state

---

## 10. Configuration Recommendations

### 10.1 Environment Variables to Add:

```bash
# Apaleo Circuit Breaker
APALEO_CIRCUIT_FAILURE_THRESHOLD=5
APALEO_CIRCUIT_RECOVERY_TIMEOUT=120
APALEO_CIRCUIT_TIMEOUT=30.0

# ASR Circuit Breaker
ASR_CIRCUIT_FAILURE_THRESHOLD=3
ASR_CIRCUIT_RECOVERY_TIMEOUT=60
ASR_CIRCUIT_TIMEOUT=30.0

# TTS Circuit Breaker
TTS_CIRCUIT_FAILURE_THRESHOLD=5
TTS_CIRCUIT_RECOVERY_TIMEOUT=60
TTS_CIRCUIT_TIMEOUT=30.0

# Database Circuit Breaker
DB_CIRCUIT_FAILURE_THRESHOLD=10
DB_CIRCUIT_RECOVERY_TIMEOUT=30
DB_CIRCUIT_TIMEOUT=30.0
```

---

## 11. File Structure Summary

### PMS Connector Files:
```
/connectors/adapters/
├── apaleo/
│   ├── __init__.py
│   └── connector.py (REQUIRES CIRCUIT BREAKER)
├── mews/
│   └── connector.py (NOT YET IMPLEMENTED)
└── opera/
    └── connector.py (NOT YET IMPLEMENTED)
```

### ASR Service Files:
```
/services/asr/
├── riva-proxy/
│   ├── server.py (REQUIRES CIRCUIT BREAKER)
│   └── test_streaming.py
└── granary-proxy/
    ├── server.py (LOCAL MODEL - NO EXTERNAL CALLS)
    └── Dockerfile
```

### Orchestrator Service Files:
```
/services/orchestrator/
├── circuit_breaker.py (EXISTING FRAMEWORK)
├── tts_client.py (REQUIRES CIRCUIT BREAKER)
├── vault_client.py (REQUIRES CIRCUIT BREAKER)
├── database/
│   ├── connection.py (REQUIRES CIRCUIT BREAKER)
│   ├── models.py
│   └── repository.py
└── tests/
    └── test_circuit_breaker.py (EXISTING TESTS)
```

---

## 12. Action Items

### Immediate (Week 1):
1. Apply circuit breaker to Apaleo `_request()` method
2. Apply circuit breaker to Riva ASR connection
3. Add monitoring/alerting for circuit breaker state changes

### Short-term (Week 2-3):
1. Apply circuit breaker to TTS client
2. Apply circuit breaker to database queries
3. Implement comprehensive integration tests

### Medium-term (Week 4-6):
1. Implement distributed tracing for circuit breaker events
2. Add circuit breaker dashboard/metrics
3. Document runbooks for circuit breaker recovery

### Long-term (Week 7+):
1. Implement Mews connector with circuit breaker
2. Implement Oracle OPERA connector with circuit breaker
3. Add machine learning-based adaptive circuit breaker thresholds

---

## 13. References

**Circuit Breaker Implementation:** `/services/orchestrator/circuit_breaker.py`
- Classes: `CircuitBreaker`, `CircuitBreakerManager`, `CircuitState`
- Configuration: `CircuitBreakerConfig`
- Statistics: `CircuitBreakerStats`

**Existing Test Suite:** `/services/orchestrator/tests/test_circuit_breaker.py`
- Test patterns and fixtures ready to extend

**Integration Examples:**
- Apaleo connector shows current retry pattern
- TTS client shows httpx usage pattern
- Database connection shows SQLAlchemy pattern

