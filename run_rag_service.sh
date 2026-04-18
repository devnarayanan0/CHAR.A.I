#!/usr/bin/env bash
set -euo pipefail

echo "Starting RAG service..."

uvicorn rag_service:app --host 0.0.0.0 --port 8001 >/tmp/rag_service.log 2>&1 &
RAG_PID=$!

cleanup() {
  kill "$RAG_PID" 2>/dev/null || true
  kill "$NGROK_PID" 2>/dev/null || true
}

trap cleanup EXIT

echo "Starting ngrok..."
ngrok http 8001 >/tmp/ngrok.log 2>&1 &
NGROK_PID=$!

echo "Waiting for ngrok tunnel..."
NGROK_URL=""
for _ in {1..30}; do
  NGROK_JSON=$(curl -s http://127.0.0.1:4040/api/tunnels || true)
  NGROK_URL=$(printf "%s" "$NGROK_JSON" | python -c 'import json, sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    raise SystemExit(0)

for tunnel in data.get("tunnels", []):
    url = tunnel.get("public_url", "")
    if url.startswith("https://"):
        print(url)
        break')
  if [[ -n "$NGROK_URL" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$NGROK_URL" ]]; then
  echo "Failed to get ngrok public URL"
  exit 1
fi

echo
echo "RAG is publicly accessible at:"
echo "$NGROK_URL"
echo
echo "Azure setting:"
echo "RAG_SERVICE_URL=$NGROK_URL"
echo

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  export RAG_SERVICE_URL="$NGROK_URL"
fi

wait "$RAG_PID"