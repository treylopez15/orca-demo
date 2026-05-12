#!/usr/bin/env bash
# Create .env from .env.example when missing (Docker Compose requires .env for env_file:).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example (edit before internal/production use)."
else
  echo ".env already exists; leaving unchanged."
fi
