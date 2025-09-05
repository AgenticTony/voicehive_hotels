#!/bin/bash
# Script to run the two missing tests for VoiceHive Hotels

set -e

echo "Running missing tests for VoiceHive Hotels..."
echo "============================================"

# Change to project root
cd "$(dirname "$0")/.."

# Install test dependencies
echo "Installing test dependencies..."
pip install -r services/test-requirements.txt

# Run Riva streaming handshake test
echo ""
echo "1. Running Riva streaming handshake test..."
echo "-------------------------------------------"
cd services/asr/riva-proxy
python -m pytest test_streaming.py -v

# Run call events counter test  
echo ""
echo "2. Running call events counter test..."
echo "--------------------------------------"
cd ../../orchestrator/tests
python -m pytest test_call_events_counter.py -v

echo ""
echo "✅ All tests completed!"
echo ""
echo "Note: These tests use mocked dependencies, so they can run"
echo "without the actual Riva server or LiveKit being available."
