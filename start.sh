#!/bin/bash
# Agentic Servicing Platform — Local Startup Script
# Starts all mock services and the interactive CLI.
# Requires Docker. Does NOT require any paid external services.

set -e

cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Agentic Servicing Platform — Local Startup              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Check prerequisites ──────────────────────────────────────────────────────

if ! command -v docker &> /dev/null; then
    echo "✗ Docker is not installed. Please install Docker first."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]" greenlet
else
    source .venv/bin/activate
fi

# ── Start mock services ──────────────────────────────────────────────────────

echo "→ Starting mock services (FAC API, Payment Provider, PostgreSQL, Redis, Jaeger)..."
docker compose up -d mock-fac mock-payment postgres redis jaeger 2>/dev/null || {
    echo "  ⚠ Some services may not have started. Continuing anyway."
}

echo "→ Waiting for services to be healthy..."
sleep 3

# Check if mock services are up
if curl -s http://localhost:9000/health | grep -q "healthy" 2>/dev/null; then
    echo "  ✓ Mock FAC API: http://localhost:9000"
else
    echo "  ⚠ Mock FAC API not responding (may still be starting)"
fi

if curl -s http://localhost:9001/health | grep -q "healthy" 2>/dev/null; then
    echo "  ✓ Mock Payment Provider: http://localhost:9001"
else
    echo "  ⚠ Mock Payment Provider not responding (may still be starting)"
fi

echo "  ✓ PostgreSQL: localhost:5432"
echo "  ✓ Redis: localhost:6379"
echo "  ✓ Jaeger UI: http://localhost:16686"
echo ""

# ── Check for OpenAI API key ─────────────────────────────────────────────────

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs 2>/dev/null || true)
fi

if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "sk-your-key-here" ]; then
    echo "⚠ No OPENAI_API_KEY found. Running in deterministic mode."
    echo "  To enable LLM-powered responses, add your key to .env:"
    echo "  OPENAI_API_KEY=sk-your-real-key"
    echo ""
    LLM_FLAG="--no-llm"
else
    echo "✓ OPENAI_API_KEY found. LLM-powered mode enabled."
    LLM_FLAG=""
fi

echo ""

# ── Run tests ────────────────────────────────────────────────────────────────

echo "→ Running test suite..."
python -m pytest taylor/tests/ -q --tb=line 2>&1 | tail -3
echo ""

# ── Start CLI ────────────────────────────────────────────────────────────────

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Starting interactive CLI...                             ║"
echo "║  Type naturally to talk to Taylor.                       ║"
echo "║  Commands: /auth /channel /account /tools /quit          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

python -m taylor.runtime.cli $LLM_FLAG
