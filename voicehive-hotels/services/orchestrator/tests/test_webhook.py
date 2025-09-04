import os
import sys
from pathlib import Path
import pytest
import httpx

@pytest.mark.asyncio
async def test_webhook_endpoints_with_bearer_and_metrics(tmp_path):
    # Ensure imports resolve from repo root
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root))

    # Minimal GDPR config
    minimal_gdpr = """
regions:
  allowed: ["eu-west-1"]
  services:
    livekit: {region: "eu-west-1"}
    twilio: {region: "eu-west-1"}
    azure_openai: {region: "eu-west-1"}
    elevenlabs: {region: "eu-west-1"}
pii_handling:
  categories:
    medium_sensitivity: []
retention:
  defaults:
    metadata:
      days: 1
"""
    cfg = tmp_path / "gdpr.yaml"
    cfg.write_text(minimal_gdpr)
    os.environ["CONFIG_PATH"] = str(cfg)
    os.environ["LIVEKIT_WEBHOOK_KEY"] = "test-key"

    from services.orchestrator.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"Authorization": "Bearer test-key"}
        payload = {"event": "agent_ready", "room_name": "test-room"}

        # Alias route expected by agent
        r_alias = await client.post("/call/event", json=payload, headers=headers)
        assert r_alias.status_code == 200

        # Webhook route
        r_webhook = await client.post("/v1/livekit/webhook", json={"event_type": "call_started", "call_sid": "abc"}, headers=headers)
        assert r_webhook.status_code in (200, 202)

        # Transcription route
        r_tx = await client.post("/v1/livekit/transcription", params={
            "call_sid": "abc",
            "text": "hello",
            "language": "en",
            "confidence": 0.9,
            "is_final": True,
        }, headers=headers)
        assert r_tx.status_code in (200, 202)

        # Metrics
        m = await client.get("/metrics")
        assert m.status_code == 200
        assert m.headers.get("content-type") == "text/plain; version=0.0.4; charset=utf-8"
