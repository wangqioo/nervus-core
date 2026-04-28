#!/bin/bash
# Ping /health on all app containers via Caddy
# Usage: bash tests/test_apps.sh [BASE_URL]
# BASE_URL defaults to http://localhost:8900

BASE="${1:-http://localhost:8900}"
PASS=0; FAIL=0

# app-id → caddy-route-prefix (Caddyfile short names)
declare -A ROUTES=(
  [calorie-tracker]="calorie"
  [meeting-notes]="meeting"
  [knowledge-base]="knowledge"
  [life-memory]="life"
  [sense]="sense"
  [photo-scanner]="photo"
  [personal-notes]="notes"
  [pdf-extractor]="pdf"
  [video-transcriber]="video"
  [rss-reader]="rss"
  [calendar]="calendar"
  [reminder]="reminder"
  [status-sense]="status-sense"
  [workflow-viewer]="workflow"
  [file-manager]="file-manager"
  [model-manager]="model-manager"
)

echo ""
echo "App health checks (via Caddy at $BASE)"
echo "────────────────────────────────────────────"

for app in "${!ROUTES[@]}"; do
  route="${ROUTES[$app]}"
  url="$BASE/api/$route/health"
  status=$(curl -sf -m 5 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
  if [ "$status" = "200" ]; then
    echo "  [PASS] $app  (/api/$route/)"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $app  (/api/$route/)  → HTTP $status"
    FAIL=$((FAIL + 1))
  fi
done

echo "────────────────────────────────────────────"
echo "  $PASS passed / $FAIL failed"
echo ""

[ $FAIL -eq 0 ] && exit 0 || exit 1
