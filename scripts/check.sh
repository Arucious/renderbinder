#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -gt 1 || ($# -eq 1 && "$1" != "--browser") ]]; then
  echo "Usage: bash scripts/check.sh [--browser]" >&2
  exit 2
fi
uv run --locked ruff check app tests scripts
uv run --locked pytest -q
pnpm --dir frontend test
pnpm --dir frontend build
if [[ "${1:-}" == "--browser" ]]; then
  uv run --locked python scripts/browser_checks.py
fi
