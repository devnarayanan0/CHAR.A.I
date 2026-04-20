#!/usr/bin/env bash
set -euo pipefail

TUNNEL_NAME="rag-tunnel"
RAG_PUBLIC_URL="https://rag.yourdomain.com"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Error: cloudflared is not installed. Install it first (brew install cloudflared)." >&2
  exit 1
fi

if ! command -v uvicorn >/dev/null 2>&1; then
  echo "Error: uvicorn is not installed in the current environment." >&2
  exit 1
fi

cleanup() {
  if [[ -n "${RAG_PID:-}" ]]; then
    kill "$RAG_PID" 2>/dev/null || true
  fi
  if [[ -n "${TUNNEL_PID:-}" ]]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "----------------------------------------"
echo "RAG SERVER RUNNING"
echo "LOCAL:  http://127.0.0.1:8001"
echo "PUBLIC: ${RAG_PUBLIC_URL}"
echo
echo "SET THIS IN RAILWAY:"
echo "RAG_SERVICE_URL=${RAG_PUBLIC_URL}"
echo "----------------------------------------"

echo "Starting RAG FastAPI service on port 8001..."
uvicorn rag_service:app --host 0.0.0.0 --port 8001 &
RAG_PID=$!

echo "Starting Cloudflare Tunnel (${TUNNEL_NAME})..."
cloudflared tunnel run "$TUNNEL_NAME" &
TUNNEL_PID=$!

set +e
wait -n "$RAG_PID" "$TUNNEL_PID"
EXIT_CODE=$?
set -e

if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
  echo "Cloudflare tunnel not running" >&2
fi

if ! kill -0 "$RAG_PID" 2>/dev/null; then
  echo "RAG server process exited" >&2
fi

exit "$EXIT_CODE"
