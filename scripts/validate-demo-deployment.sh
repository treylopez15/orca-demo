#!/usr/bin/env bash
# Quick checks for demo Docker deployment (run after: docker compose up -d --build).
# Expects DEMO_MODE=true on the server (synthetic analytics, simulated broadcast).
set -euo pipefail
BASE="${BASE_URL:-http://127.0.0.1:3000}"

echo "==> GET $BASE/health"
curl -fsS "$BASE/health" | python3 -m json.tool
echo ""

echo "==> GET $BASE/api/config"
curl -fsS "$BASE/api/config" | python3 -m json.tool
echo ""

echo "==> GET $BASE/api/analytics/summary (first keys only)"
curl -fsS "$BASE/api/analytics/summary" | python3 -c "import json,sys; d=json.load(sys.stdin); print('demo' in d, 'keys', sorted(list(d.keys()))[:12])"
echo ""

echo "==> POST $BASE/api/broadcast/send (demo simulated)"
curl -fsS -X POST "$BASE/api/broadcast/send" \
  -H "Content-Type: application/json" \
  -d '{"channel_ids":["C_APEX"],"message":"demo validation ping","as_announcement":false}' | python3 -m json.tool
echo ""

echo "Manual UI checks:"
echo "  - Open $BASE/ui/ and confirm header: Demo Environment — identifiers masked"
echo "  - Broadcast tab: send completes with simulated success message"
echo "  - Analytics: charts load; channel picker shows client-a-support / client-b-support where mapped"
echo "Done."
