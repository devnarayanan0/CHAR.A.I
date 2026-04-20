#!/usr/bin/env bash
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
RAG_PORT=8001
RAG_HOST="0.0.0.0"
TUNNEL_LOG_FILE="/tmp/cloudflare_tunnel_$$.log"
MAX_URL_WAIT=60
URL_RETRY_INTERVAL=2

# Cleanup function
cleanup() {
  echo ""
  echo -e "${YELLOW}⸻${NC}"
  echo "Shutting down..."
  
  if [[ -n "${RAG_PID:-}" ]] && kill -0 "$RAG_PID" 2>/dev/null; then
    echo "Stopping RAG server (PID: $RAG_PID)..."
    kill "$RAG_PID" 2>/dev/null || true
    wait "$RAG_PID" 2>/dev/null || true
  fi
  
  if [[ -n "${TUNNEL_PID:-}" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "Stopping Cloudflare tunnel (PID: $TUNNEL_PID)..."
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
  fi
  
  if [[ -f "$TUNNEL_LOG_FILE" ]]; then
    rm -f "$TUNNEL_LOG_FILE"
  fi
  
  echo "Done."
  exit 0
}

# Trap signals for cleanup
trap cleanup EXIT INT TERM

# Check if port is already in use
check_port_available() {
  if lsof -nP -iTCP:$RAG_PORT -sTCP:LISTEN >/dev/null 2>&1; then
    echo -e "${RED}Error: Port $RAG_PORT is already in use${NC}" >&2
    exit 1
  fi
}

# Check if command exists
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Validate dependencies
validate_dependencies() {
  if ! command_exists uvicorn; then
    echo -e "${RED}Error: uvicorn is not installed${NC}" >&2
    echo "Install it with: pip install uvicorn" >&2
    exit 1
  fi
  
  if ! command_exists cloudflared; then
    echo -e "${RED}Error: cloudflared is not installed${NC}" >&2
    echo "Install it with: brew install cloudflared" >&2
    exit 1
  fi
}

# Extract public URL from tunnel logs
extract_tunnel_url() {
  local timeout=$1
  local elapsed=0
  
  echo "Waiting for Cloudflare tunnel to establish..."
  
  while [[ $elapsed -lt $timeout ]]; do
    if [[ -f "$TUNNEL_LOG_FILE" ]]; then
      local url=$(grep -oP 'https://[a-z0-9\-]+\.trycloudflare\.com' "$TUNNEL_LOG_FILE" | head -1 || true)
      if [[ -n "$url" ]]; then
        echo "$url"
        return 0
      fi
    fi
    
    sleep "$URL_RETRY_INTERVAL"
    elapsed=$((elapsed + URL_RETRY_INTERVAL))
  done
  
  echo -e "${RED}Error: Could not extract tunnel URL after ${timeout}s${NC}" >&2
  return 1
}

# Main execution
main() {
  echo -e "${GREEN}⸻${NC}"
  echo "Starting RAG with Cloudflare Quick Tunnel..."
  echo -e "${GREEN}⸻${NC}"
  echo ""
  
  # Validate dependencies
  validate_dependencies
  
  # Check port availability
  check_port_available
  
  # Start RAG server
  echo -e "${YELLOW}Starting RAG server on port ${RAG_PORT}...${NC}"
  uvicorn rag_service:app --host "$RAG_HOST" --port "$RAG_PORT" >/dev/null 2>&1 &
  RAG_PID=$!
  echo -e "${GREEN}✓ RAG server started (PID: $RAG_PID)${NC}"
  
  # Give RAG server time to start
  sleep 2
  
  # Verify RAG server is running
  if ! kill -0 "$RAG_PID" 2>/dev/null; then
    echo -e "${RED}Error: RAG server failed to start${NC}" >&2
    exit 1
  fi
  
  # Start Cloudflare tunnel
  echo -e "${YELLOW}Starting Cloudflare Quick Tunnel...${NC}"
  cloudflared tunnel --url "http://localhost:${RAG_PORT}" >"$TUNNEL_LOG_FILE" 2>&1 &
  TUNNEL_PID=$!
  echo -e "${GREEN}✓ Cloudflare tunnel started (PID: $TUNNEL_PID)${NC}"
  
  # Extract and display public URL
  if ! PUBLIC_URL=$(extract_tunnel_url "$MAX_URL_WAIT"); then
    echo -e "${RED}Error: Failed to establish tunnel${NC}" >&2
    exit 1
  fi
  
  # Display final output
  echo ""
  echo -e "${GREEN}⸻${NC}"
  echo ""
  echo -e "${GREEN}RAG SERVER RUNNING${NC}"
  echo "LOCAL:  http://127.0.0.1:${RAG_PORT}"
  echo "PUBLIC: ${PUBLIC_URL}"
  echo ""
  echo -e "${YELLOW}COPY THIS INTO RAILWAY:${NC}"
  echo "RAG_SERVICE_URL=${PUBLIC_URL}"
  echo ""
  echo -e "${GREEN}⸻${NC}"
  echo ""
  
  # Keep processes alive
  echo "Press CTRL+C to stop..."
  
  # Monitor processes
  while kill -0 "$RAG_PID" 2>/dev/null && kill -0 "$TUNNEL_PID" 2>/dev/null; do
    sleep 1
  done
  
  # If we get here, one process died unexpectedly
  if ! kill -0 "$RAG_PID" 2>/dev/null; then
    echo -e "${RED}Error: RAG server crashed${NC}" >&2
    exit 1
  fi
  
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo -e "${RED}Error: Cloudflare tunnel crashed${NC}" >&2
    exit 1
  fi
}

# Run main function
main "$@"
