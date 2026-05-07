#!/usr/bin/env bash
# Zopedia Setup Script
# Usage: bash scripts/setup.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Setting up Zopedia in $ROOT"

# ── Backend ────────────────────────────────────────────────────────
echo ""
echo "=== Backend Setup ==="

cd "$ROOT/backend"

# Create Python virtual environment if needed
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Created Python virtual environment"
fi

source .venv/bin/activate

# Install Python dependencies
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "Python dependencies installed"

# ── Frontend ───────────────────────────────────────────────────────
echo ""
echo "=== Frontend Setup ==="

cd "$ROOT/frontend"
if [ ! -d "node_modules" ]; then
    npm install --no-audit --no-fund
    echo "Frontend dependencies installed"
fi

# Build frontend
npm run build
echo "Frontend built"

# ── Default env ────────────────────────────────────────────────────
echo ""
echo "=== Environment Configuration ==="
echo ""
echo "Set these environment variables before starting:"
echo ""
echo "  export ZOPEDIA_LLM_BASE_URL=https://api.openai.com/v1"
echo "  export ZOPEDIA_LLM_API_KEY=sk-..."
echo "  export ZOPEDIA_LLM_MODEL=gpt-4o"
echo "  export ZOPEDIA_WIKI_VAULT=./wiki_data     # default, optional"
echo "  export ZOPEDIA_AUTH_DISABLED=true          # default"
echo ""
echo "Then start:"
echo "  cd backend && python main.py"
echo ""
echo "Zopedia will be available at http://localhost:8000"
