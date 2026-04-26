#!/usr/bin/env bash
set -euo pipefail

PORT=8001
LOCAL_URL="http://localhost:${PORT}"

cleanup() {
  if [[ -n "${RAG_PID:-}" ]] && kill -0 "$RAG_PID" 2>/dev/null; then
    kill "$RAG_PID" 2>/dev/null || true
  fi
  if [[ -n "${NGROK_PID:-}" ]] && kill -0 "$NGROK_PID" 2>/dev/null; then
    kill "$NGROK_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

# Kill anything listening on 8001 from previous runs.
lsof -ti tcp:"${PORT}" 2>/dev/null | xargs kill -9 2>/dev/null || true

# Start local RAG service.
uvicorn rag_service:app --host 0.0.0.0 --port "${PORT}" >/dev/null 2>&1 &
RAG_PID=$!

sleep 2

# Start ngrok tunnel.
ngrok http "${PORT}" >/dev/null 2>&1 &
NGROK_PID=$!

sleep 3

# Read public URL from ngrok local API.
PUBLIC_URL=""
for _ in {1..20}; do
  PUBLIC_URL="$(curl -s http://127.0.0.1:4040/api/tunnels | python3 -c 'import json,sys; data=json.load(sys.stdin); tunnels=data.get("tunnels", []); https=[t.get("public_url", "") for t in tunnels if str(t.get("public_url", "")).startswith("https://")]; print(https[0] if https else "")' 2>/dev/null || true)"
  if [[ -n "${PUBLIC_URL}" ]]; then
    break
  fi
  sleep 1
done

echo "RAG SERVICE STARTED"
echo "Local: ${LOCAL_URL}"
echo "Public: ${PUBLIC_URL}"
echo
echo "Set this in Railway:"
echo "RAG_SERVICE_URL=${PUBLIC_URL}"

# Keep both processes running in background until interrupted.
wait -n "$RAG_PID" "$NGROK_PID"
