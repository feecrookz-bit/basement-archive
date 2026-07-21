#!/usr/bin/env bash
# Runs on EVERY Codespace start: bring the tracker up and publish its port
# so Helius webhooks (and remote helpers) can reach it. Best-effort — any
# failure leaves a hint instead of breaking the codespace.
set -u
cd "$(dirname "$0")/.." || exit 0

# tracker stack up (no-op if already running); logs to /tmp/compose-up.log
nohup docker compose up -d --build >/tmp/compose-up.log 2>&1 &

# publish port 8000 (needed for Helius webhook delivery). gh inside a
# codespace usually carries enough scope; if not, the Ports panel click
# remains the fallback.
if command -v gh >/dev/null 2>&1 && [ -n "${CODESPACE_NAME:-}" ]; then
  ok=""
  for _ in 1 2 3; do
    if gh codespace ports visibility 8000:public -c "$CODESPACE_NAME" 2>/tmp/port-vis.log; then
      ok=1; echo "poststart: port 8000 is now PUBLIC"; break
    fi
    sleep 5
  done
  [ -z "$ok" ] && echo "poststart: could not set port visibility automatically" \
    "(see /tmp/port-vis.log) — set port 8000 to Public in the Ports panel"
fi
