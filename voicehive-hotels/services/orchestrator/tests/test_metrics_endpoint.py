import os
import sys
from pathlib import Path
import tempfile

import pytest
import httpx


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_prometheus_format():
    """Ensure /metrics returns Prometheus text format with correct content type."""
    # Ensure imports resolve from repo root
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root))

    # Create a minimal valid GDPR config for the app to load at import time
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
    with tempfile.NamedTemporaryFile("w", delete=False) as tf:
        tf.write(minimal_gdpr)
        config_path = tf.name

    os.environ["CONFIG_PATH"] = str(config_path)

    # Import after setting CONFIG_PATH so app reads the temp config
    from services.orchestrator.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "text/plain; version=0.0.4; charset=utf-8"

        # Body should include some default Python process metrics (even if service metrics are zero)
        assert "python_info" in resp.text

