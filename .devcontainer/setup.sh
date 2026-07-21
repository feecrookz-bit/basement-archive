#!/usr/bin/env bash
# Devcontainer post-create: seed .env files and inject Codespaces secrets.
set -u

cp -n .env.example .env 2>/dev/null || true
cp -n sentinel/.env.example sentinel/.env 2>/dev/null || true

# If a HELIUS_API_KEY Codespaces secret is present and .env still has the
# empty placeholder, fill it in so `docker compose up` works with zero edits.
if [ -n "${HELIUS_API_KEY:-}" ] && grep -q '^HELIUS_API_KEY=$' .env; then
  sed -i "s|^HELIUS_API_KEY=$|HELIUS_API_KEY=${HELIUS_API_KEY}|" .env
  echo "devcontainer: HELIUS_API_KEY injected into .env from Codespaces secret"
fi
