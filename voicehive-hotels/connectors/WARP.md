# 🌍 WARP.md — VoiceHive Hotels (Multilingual Receptionist)

## 🤖 Direct Instructions for Warp AI Agent

You MUST read this document fully before executing any task. Your primary goal is to assist in developing and maintaining this codebase according to the standards below.

***

## How to Interact

* **Context is Key**: Before adding or editing code, search the repo with **rg (ripgrep)** to find existing patterns and avoid duplication.
* **Think Step-by-Step**: Before coding, outline the steps, files, tests, and how changes fit the architecture.
* **Propose, Don't Assume**: If a request is unclear, propose 1–3 options with trade-offs.
* **Lint & Format**: After generating code, remind the user to run the linting/formatting commands in this doc.
* **Warp Integration**: Suggest saving complex command sequences as Warp Workflows or in the Team Notebook.

***

## 📚 MCP Documentation Workflow (REQUIRED)

### Before ANY Implementation:

1. **For PMS/API Integrations**:
   ```python
   # Example: Implementing Apaleo connector
   # FIRST: Check official docs
   ref_search_documentation(query="apaleo.dev API authentication")
   ref_search_documentation(query="apaleo reservation API")
   ref_read_url(url="https://api.apaleo.com/reference")
   ```

2. **For Libraries/Frameworks**:
   ```python
   # Example: Using LangChain
   # FIRST: Resolve library and get docs
   resolve-library-id(libraryName="langchain")
   get-library-docs(context7CompatibleLibraryID="/langchain/langchain", topic="agents")
   
   # Example: FastAPI implementation
   resolve-library-id(libraryName="fastapi")
   get-library-docs(context7CompatibleLibraryID="/tiangolo/fastapi", topic="websockets")
   ```

3. **For General Research**:
   ```python
   # Example: Best practices research
   tavily_search(query="PMS integration best practices 2024")
   tavily_extract(urls=["https://official-docs-url.com"])
   ```

### Documentation Priority Order:
1. **Official vendor docs** (apaleo.dev, mews.com/developers, etc.)
2. **Library official docs** via MCP tools
3. **GitHub repos** with `ref_search_documentation` + `ref_src=github`
4. **General web search** only for supplementary info

⚠️ **Never proceed without checking docs first!**

***

## Absolute Rules

* 🔍 **MANDATORY**: Before implementing ANY feature, use MCP tools to check official documentation:
  - For PMS integrations: Check vendor docs (e.g., `ref_search_documentation` for "apaleo.dev API")
  - For libraries/frameworks: Use `resolve-library-id` + `get-library-docs` (e.g., LangChain, FastAPI)
  - For general docs: Use `tavily_search` or `ref_read_url` for official sources
* ❌ **Never** commit secrets or PII. Use env vars + secret manager.
* ❌ **Never** break latency budgets or bypass observability.
* ❌ **Never** implement based on assumptions - verify with official docs first.
* ✅ **Always** reuse existing utilities/services; follow vertical slice boundaries.
* ✅ **CRITICAL**: Use `rg` for searches — **grep/find are forbidden**.
* ✅ GDPR: redact PII in logs/transcripts by default; EU data residency only.
* ✅ Voice cloning requires consent + watermark policy stored with artifacts.
* ✅ For connectors: Follow 80/20 pattern - maximize reuse of common code
* ✅ All new connectors must pass golden contract tests

***

## Agent Persona

You are a senior real-time systems engineer with expertise in:
* **Realtime Media**: LiveKit Agents, SIP/PSTN, barge-in/endpointing
* **Speech**: NVIDIA Riva (Parakeet/Canary), OpenVoice v2, XTTS-v2, ElevenLabs/Cartesia
* **Backend**: Python (FastAPI), gRPC/HTTP, Redis/Postgres, Helm/K8s
* **PMS Integration**: Connector framework, vertical APIs (Apaleo, Mews, Opera)
* **Observability**: Prometheus, Grafana, Loki, tracing

Priorities: **Correctness → Consistency → Clarity → Conciseness**.

***

## 🧘 Core Development Philosophy

KISS • YAGNI • Single Responsibility • Fail Fast • Twelve-Factor Config • Test What You Change.

***

## 🧱 Code Structure & Modularity

* **File limits**: ≤ 500 LOC; split modules if larger.
* **Function limits**: < 50 LOC; one responsibility.
* **Class limits**: < 100 LOC; single domain concern.
* **Line length**: ≤ 100 chars.

### Project Layout

```
voicehive-hotels/
├── infra/
│   ├── docker/
│   │   ├── docker-compose.yml    # Full stack local dev
│   │   └── env.example
│   ├── helm/
│   │   └── voicehive/
│   │       ├── Chart.yaml
│   │       ├── values.yaml
│   │       └── templates/
│   └── k8s/                      # Raw K8s manifests
│       ├── vault/                # HashiCorp Vault configs
│       └── gatekeeper/           # Policy enforcement
├── connectors/                   # PMS Integration Layer
│   ├── contracts.py             # Universal interface all PMS must implement
│   ├── factory.py               # Dynamic connector selection
│   ├── capability_matrix.yaml   # Vendor feature support matrix
│   └── adapters/                # Vendor-specific implementations
│       ├── apaleo/              # Modern REST API
│       ├── mews/                # Popular in Europe
│       ├── cloudbeds/           # Small/boutique hotels
│       ├── opera/               # Enterprise (Oracle OHIP)
│       └── siteminder/          # Channel manager
├── services/
│   ├── orchestrator/
│   │   └── app.py              # FastAPI, call logic, tools, policies
│   ├── asr/riva-proxy/
│   │   └── server.py           # gRPC proxy to Riva (Parakeet/Canary)
│   ├── tts/
│   │   ├── openvoice/
│   │   ├── xtts/
│   │   └── router/
│   │       └── server.py       # Policy-based mux; commercial fallback
│   └── media/livekit-agent/
│       └── agent.py            # SFU loop, barge-in, endpointing
├── ops/
│   ├── monitoring/             # Prometheus, Grafana, alerts
│   └── qa/call-replays/        # Call harness, samples, assertions
└── config/
    ├── prompts/               # LLM prompts for orchestrator
    ├── policies/              # Routing & quality policies
    └── dashboards/            # Grafana dashboard configs
```

***

## 🛠️ Development Environment & Quick Start Commands

### Prerequisites (macOS dev)

```bash
# ⚡ Warp Command Block: Install CLI tooling
brew install rg jq yq pre-commit just
pyenv install 3.11.9 && pyenv global 3.11.9
pipx install uv httpx uvicorn ruff black mypy
npm i -g pnpm@9
```

### GPU Host (Linux)

```bash
# ⚡ Warp Command Block: NVIDIA Container Toolkit
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure && sudo systemctl restart docker
```

### Development Setup

```bash
# ⚡ Warp Command Block: Initial setup (from parent directory)
make setup-dev              # Install dependencies, pre-commit hooks, create .env
cp .env.example .env        # Create local environment file

# ⚡ Warp Command Block: Start local stack
make up                     # Start Docker services (from parent directory)
docker compose -f infra/docker/docker-compose.yml up -d --build

# ⚡ Warp Command Block: Tail logs
docker compose logs -f orchestrator riva-proxy tts-router livekit connectors
make logs

# ⚡ Warp Command Block: Tear down
make down
docker compose -f infra/docker/docker-compose.yml down -v
```

### Riva (models & proxy)

```bash
# ⚡ Warp Command Block: Verify Riva proxy health
curl -s http://localhost:51051/health || true
```

### Call Replay & Smoke Tests

```bash
# ⚡ Warp Command Block: Replay multilingual calls
python ops/qa/call-replays/replay.py \
  --wav samples/hotel_de.wav --lang auto --expect-ttfb 250
python ops/qa/call-replays/replay.py \
  --wav samples/hotel_es.wav --lang auto --expect-ttfb 250
```

### K8s Deploy (Helm)

```bash
# ⚡ Warp Command Block: Install/upgrade Helm release
helm upgrade --install voicehive infra/helm/voicehive \
  -n voicehive --create-namespace \
  -f infra/helm/voicehive/values.yaml

# ⚡ Warp Command Block: Watch rollout
kubectl -n voicehive rollout status deploy/tts-router
kubectl -n voicehive rollout status deploy/orchestrator
kubectl -n voicehive rollout status deploy/connectors
```

### Observability

```bash
# ⚡ Warp Command Block: Open dashboards
open http://localhost:3000   # Grafana
open http://localhost:9090   # Prometheus
```

### Testing Commands
```bash
# ⚡ Warp Command Block: Run all tests
make test                   # Type checking, linting, security scan, unit tests
uv run pytest -q           # Quick test run
pytest --cov=connectors --cov=services --cov-report=xml

# ⚡ Warp Command Block: Connector-specific tests
make test-connectors        # Run all connector tests
make test-connector VENDOR=apaleo     # Test specific vendor
pytest connectors/tests/golden_contract/ -v   # Golden contract tests

# ⚡ Warp Command Block: Voice & call tests
python ops/qa/call-replays/replay.py --wav samples/long_reply_en.wav --interrupt 3.2  # Barge-in
curl -s :9000/speak -H 'Content-Type: application/json' \
  -d '{"text":"Hello","lang":"de-DE","force":"commercial"}' | jq .

# ⚡ Warp Command Block: Integration tests (requires real credentials)
APALEO_TEST_CLIENT_ID=xxx APALEO_TEST_CLIENT_SECRET=yyy pytest connectors/tests/integration/ -m integration
pytest -m "not integration"  # Skip integration tests
```

### Code Quality

```bash
# ⚡ Warp Command Block: Linting and formatting
make lint                   # Run ruff, mypy, hadolint, prettier
make format                 # Black, isort, prettier
make pre-commit             # Run all pre-commit hooks

# ⚡ Warp Command Block: Individual tools
ruff check services connectors    # Fast Python linter
ruff format services connectors   # Format with ruff
black services/ connectors/       # Code formatter
mypy services connectors --strict # Type checking
prettier -w .                     # Format YAML/JSON/MD
```

***

## 📋 Style & Conventions

* **Python**: PEP8, `ruff` + `black`, `mypy --strict` (where feasible), Pydantic v2.
* **TypeScript** (if present): ESLint + Prettier, `tsc --noEmit`.
* **HTTP**: set timeouts, retries with jitter; circuit breakers.
* **Config**: everything overridable via env; no hard-coded constants.
* **Naming**: `snake_case` vars, `PascalCase` classes, `UPPER_SNAKE_CASE` consts, `{action}_at` timestamps.

### Connector Management
```bash
# Create new connector
make new-connector VENDOR=newpms    # Generate connector scaffold

# Validate connector
make validate-connector VENDOR=apaleo   # Run golden contract + capability check
```

## Architecture Overview

```
VoiceHive Hotels PMS Connector Framework (80/20 Pattern)
├── Core Framework (80% - Shared by all connectors)
│   ├── contracts.py         → Universal PMSConnector protocol & domain models
│   ├── factory.py           → Dynamic connector discovery & instantiation
│   └── capability_matrix.yaml → Feature support matrix per vendor
│
├── Vendor Adapters (20% - Vendor-specific logic)
│   └── adapters/
│       ├── apaleo/          → Modern REST API (quick win)
│       ├── mews/            → Popular in Europe
│       ├── cloudbeds/       → Small/boutique hotels
│       ├── opera/           → Enterprise (Oracle OHIP)
│       └── siteminder/      → Channel manager
│
└── Utilities
    ├── utils/
    │   ├── vault_client.py  → HashiCorp Vault integration
    │   ├── pii_redactor.py  → GDPR compliance
    │   └── logging.py       → Structured logging
    └── tests/golden_contract/  → Universal behavior tests
```

### Data Flow
```
External PMS API → Vendor Adapter → BaseConnector → Normalized Models → VoiceHive Core
     (XML/JSON)      (Transform)     (Validate)      (contracts.py)      (Async ops)
```

### Key Files to Understand First
1. `contracts.py` - Domain models (Reservation, GuestProfile, etc.) and PMSConnector protocol
2. `factory.py` - How connectors are discovered and instantiated
3. `adapters/apaleo/connector.py` - Reference implementation showing patterns
4. `tests/golden_contract/test_base_contract.py` - Expected behavior all connectors must implement

## Adding a New Connector

### 1. Research Vendor API Documentation (MANDATORY)
```python
# REQUIRED: Before ANY code, check official docs
ref_search_documentation(query="newpms developer API")
ref_search_documentation(query="newpms authentication oauth")
ref_search_documentation(query="newpms reservation endpoints")
# Read the full API reference
ref_read_url(url="https://developer.newpms.com/api-reference")
```

### 2. Generate Scaffold
```bash
make new-connector VENDOR=newpms
# Creates connectors/adapters/newpms/ directory structure
```

### 3. Update Capability Matrix
```yaml
# capability_matrix.yaml
vendors:
  newpms:
    display_name: "New PMS System"
    capabilities:
      availability: true
      rates: true
      reservations: true
      # ... define what this PMS supports
```

### 4. Implement Connector
```python
# adapters/newpms/connector.py
from connectors.contracts import BaseConnector, Capabilities

class NewPMSConnector(BaseConnector):
    vendor_name = "newpms"
    
    capabilities = {
        Capabilities.AVAILABILITY.value: True,
        # ... match capability_matrix.yaml
    }
    
    async def get_availability(self, hotel_id, start, end, room_type=None):
        # Transform vendor-specific response to AvailabilityGrid
        pass
```

### 5. Create Golden Contract Tests
```python
# tests/golden_contract/test_newpms.py
from connectors.tests.golden_contract.base import GoldenContractTestSuite

class TestNewPMSGoldenContract(GoldenContractTestSuite):
    vendor = "newpms"
    
    @pytest.fixture
    def test_config(self):
        return {
            "api_key": "test_key",
            "base_url": "https://sandbox.newpms.com"
        }
```

### 6. Test Until Green
```bash
# Run golden contract tests
pytest connectors/tests/golden_contract/test_newpms.py -v

# Validate against capability matrix
make validate-connector VENDOR=newpms
```

***

## 🧪 Testing Strategy

### Test Layers

1. **Unit Tests** - Pure functions, data transformations, intent handlers
   ```bash
   pytest connectors/tests/test_factory.py -v
   pytest services/tests/ -v
   ```

2. **Golden Contract Tests** - Universal behavior all connectors must pass
   ```bash
   pytest connectors/tests/golden_contract/ -v
   ```

3. **Contract Tests** - gRPC stubs (Riva), REST (TTS engines), SFU hooks
   ```bash
   pytest services/tests/contracts/ -v
   ```

4. **Integration Tests** - Real API calls (requires credentials)
   ```bash
   pytest -m integration
   ```

5. **E2E Tests** - Call replay harness with multilingual WAVs + noise scenarios
   ```bash
   python ops/qa/call-replays/replay.py --all
   ```

6. **Load Tests** - 10–100 concurrent synthetic calls; assert SLOs
   ```bash
   locust -f tests/load/locustfile.py --headless --users 100 --spawn-rate 10
   ```

### Test Layers
1. **Unit Tests** - Pure functions, data transformations
   ```bash
   pytest connectors/tests/test_factory.py -v
   ```

2. **Golden Contract Tests** - Universal behavior all connectors must pass
   ```bash
   pytest connectors/tests/golden_contract/ -v
   ```

3. **Integration Tests** - Real API calls (requires credentials)
   ```bash
   pytest connectors/tests/integration/ -m integration
   ```

### Running Tests
```bash
# Fast tests only (no external calls)
pytest -m "not integration"

# Specific test method
pytest connectors/tests/golden_contract/test_base_contract.py::TestConnectorCapabilities::test_health_check

# With coverage
pytest --cov=connectors --cov-report=html
```

***

## 🚨 Error Handling

* Wrap all external calls (ASR/TTS/SFU/CRM/PMS) with try/except + structured logs.
* Retry transient errors (backoff with jitter); never infinite retry.
* Domain exceptions:

### Voice/Media Exceptions
```python
ASREngineError       # ASR failures (Riva/Voxtral)
TTSEngineError       # TTS failures (OpenVoice/XTTS/Commercial)
MediaBridgeError     # LiveKit/SFU issues
```

### Connector Exceptions
```python
PMSError                    # Base exception
├── AuthenticationError     # Invalid credentials/expired tokens  
├── RateLimitError         # API limits (has retry_after attribute)
├── ValidationError        # Invalid data sent to PMS
├── NotFoundError          # Resource doesn't exist
└── PMSClientError         # Generic PMS communication error
```

### Standard Pattern
```python
from connectors import PMSError, RateLimitError, get_connector

try:
    async with get_connector("apaleo", config) as conn:
        reservation = await conn.create_reservation(draft)
except RateLimitError as e:
    # Retry with backoff
    await asyncio.sleep(e.retry_after or 60)
    # Retry operation
except ValidationError as e:
    # Log and fix data
    logger.error(f"Invalid data: {e.field}")
except PMSError as e:
    # Generic PMS error
    logger.error(f"PMS operation failed", error=str(e))
```

***

## 🗝️ Data & Compliance

* **PII classes**: name, phone, email, room #, payment tokens → redact; store salted hashes for linking.
* **Consent**: JSON record per voice clone (timestamp, voice_id, sample hash, IP, user-agent).
* **Retention**: default 30 days (audio), 90 days (transcripts); client-override allowed.
* **Access**: RBAC; supervisors view redacted transcripts + aligned audio.
* **GDPR**: All PII automatically redacted in logs via `pii_redactor.py`
* **EU Data Residency**: Required for all customer data

***

## 🔍 Search Command Requirements

**Use ripgrep exclusively**

```bash
# ⚡ Warp Command Block: Search examples
rg -n "(reservation|concierge|tts|livekit|riva|openvoice|xtts|router)" services/ infra/
rg -n "@app\.post\(\"/speak\"\)" services/tts/router -S
rg -n "class .*Agent|barge|endpoint" services/media -S
rg -n "lang|locale|voice_id" services/
rg -n "PMSConnector|BaseConnector" connectors/
rg -n "get_availability|create_reservation" connectors/adapters/
```

❌ Do **NOT** use `grep` or `find`.

***

## ⚙️ Latency Budgets (P95)

| Stage | Budget (ms) |
|-------|------------|
| SFU hop | 60 |
| ASR TTFB | 250 |
| LLM/tools | 120 |
| TTS TTFB | 250 |
| **Round-trip** | **≤ 500** |

Barge-in/endpointing must honor interrupts ≤ **100 ms**.

***

## 🛰️ Feature Flags & Routing

* `QUALITY_MODE`: `cost_saver|balanced|premium`
* `LANG_ROUTE`: per-locale engine map (e.g., `en-GB→commercial`, `de-DE→openvoice`)
* `ASR_ENGINE`: `parakeet|canary|voxtral`
* `CLONE_ALLOWED`: `true|false` per client/line
* `PMS_VENDOR`: Dynamic selection via capability matrix

***

## 🧩 Orchestrator Guidelines (Prompts/Tools)

* Prefer deterministic tools (PMS inventory, hours, directions) before free text.
* Keep replies concise; confirm intent; support code-switching mid-sentence.
* Persist `lang` across the call; avoid re-detect unless confidence drops.
* Use PMS connector factory for all hotel data operations.

## Configuration & Secrets

### HashiCorp Vault Integration
```python
# Production: Secrets from Vault
config = {
    "hotel_id": "HOTEL01",
    # Secrets auto-loaded from Vault path:
    # voicehive/connectors/apaleo/HOTEL01
}

# Development: Environment variables
APALEO_CLIENT_ID=xxx
APALEO_CLIENT_SECRET=yyy
VOICEHIVE_ENV=development  # Uses DevelopmentVaultClient
```

### Local Development
```bash
# 1. Copy example environment
cp .env.example .env

# 2. Add your test credentials
# APALEO_CLIENT_ID=your_sandbox_id
# APALEO_CLIENT_SECRET=your_sandbox_secret

# 3. Run with mock data
python connectors/examples/factory_usage.py

# 4. Or use mock connector
from connectors.contracts import MockConnector
connector = MockConnector(config)
```

### Vault Paths
- Production: `voicehive/connectors/{vendor}/{hotel_id}`
- Staging: `voicehive-staging/connectors/{vendor}/{hotel_id}`
- Development: Uses environment variables or `.env` file

### Security Notes
- Never commit credentials to git
- Use `SecretStr` type from Pydantic v2 (see MODERNIZATION_PLAN.md)
- Vault tokens auto-rotate every 24 hours
- PII is automatically redacted in logs via `pii_redactor.py`

***

## 🧭 Runbooks (Common Tasks)

### Voice & Call Management

```bash
# ⚡ Barge-in verification (expect cancel)
python ops/qa/call-replays/replay.py --wav samples/long_reply_en.wav --interrupt 3.2

# ⚡ Force TTS fallback (commercial)
curl -s :9000/speak -H 'Content-Type: application/json' \
  -d '{"text":"Hello","lang":"de-DE","force":"commercial"}' | jq .

# ⚡ Blue/green deploy
kubectl set image deploy/tts-router router=ghcr.io/voicehive/tts-router:1.2.3
kubectl rollout status deploy/tts-router
```

### Connector Management

```bash
# ⚡ Verify setup
python connectors/verify_setup.py

# ⚡ Check what's available
python -c "from connectors import list_available_connectors; print(list_available_connectors())"

# ⚡ Find connectors with webhooks
python -c "from connectors import find_connectors_with_capability; print(find_connectors_with_capability('webhooks'))"

# ⚡ Test connector health
curl -s http://localhost:8080/connectors/apaleo/health | jq .

# ⚡ Run example
python connectors/examples/factory_usage.py
```

## Monitoring & Debugging

- All API calls are logged with timing: `duration_ms`, `status_code`
- Correlation IDs track requests across services
- Failed operations include `vendor`, `operation`, `error` fields
- Rate limit hits log `retry_after` seconds

Enable debug logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

***

## 📦 Make/Just Targets

```makefile
.PHONY: up down logs lint format test typecheck seed
up: ; docker compose -f infra/docker/docker-compose.yml up -d --build
down: ; docker compose -f infra/docker/docker-compose.yml down -v
logs: ; docker compose logs -f orchestrator riva-proxy tts-router livekit
lint: ; ruff check services connectors && prettier -w .
format: ; ruff format services connectors && prettier -w .
test: ; pytest -q
typecheck: ; mypy services connectors || true
seed: ; python ops/qa/seed.py
verify-all: ; python connectors/verify_setup.py
new-connector: ; python tools/generate-connector.py --vendor $(VENDOR)
```

***

## 🧾 Conventional Commits

```bash
feat(tts): add OpenVoice speaker enrollment
fix(asr): handle code-switching mid-utterance  
feat(connectors): add Cloudbeds PMS integration
fix(connectors): handle OAuth token refresh for Mews
chore(ci): bump ruff and pre-commit hooks
```

***

## ⚠️ Important Notes

* NEVER assume; clarify before coding (or propose options).
* ALWAYS verify file paths/modules before edits.
* Keep WARP.md updated when adding models, policies, or services.
* All features must emit metrics/logs/traces and have tests.
* For connectors: Document vendor-specific quirks in the adapter
* Update capability matrix with accurate feature support

***

## ✅ Acceptance Gates (merge-ready)

* P95 RTT ≤ 500 ms; barge-in success ≥ 98% on smoke tests.
* WER within +10% of human baseline per language on our hotel set.
* MOS proxy ≥ 4.2 (EN), ≥ 4.0 (others) on internal panel.
* All new connectors must pass golden contract tests.
* No secrets in diff; CI green; dashboards updated.

<citations>
  <document>
      <document_type>WARP_DRIVE_NOTEBOOK</document_type>
      <document_id>8EfDKVhEYyoFyf400AVE6w</document_id>
  </document>
</citations>
