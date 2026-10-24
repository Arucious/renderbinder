#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in uv node pnpm ffmpeg ffprobe; do
  command -v "$tool" >/dev/null || { echo "Missing $tool; see docs/cloud-development.md" >&2; exit 1; }
done
uv sync --locked
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
echo "Setup complete. Run bash scripts/check.sh; add --browser for browser checks."
