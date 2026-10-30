# Working on RenderBinder

This is a local ComfyUI media gallery and prompt manager. The same source runs on Windows and Linux. Start with [docs/cloud-development.md](docs/cloud-development.md) for reproducible setup and [docs/metadata-architecture.md](docs/metadata-architecture.md) for parser extension points.

## Setup and checks

- Python 3.13, Node 24, uv 0.12.8, pnpm 11.25.0; Python 3.11 is also covered by CI.
- Install FFmpeg/ffprobe, then run `bash scripts/setup.sh` on Linux. This installs locked core/development dependencies and builds the frontend.
- Run `bash scripts/check.sh` for Ruff, backend tests, diff unit tests, TypeScript, and the production frontend build.
- Install Chrome with `pnpm --dir frontend exec playwright install --with-deps chrome`, then run `uv run --locked python scripts/browser_checks.py`. This starts and stops its own QA server on 8766. Set `BROWSER_CHANNEL=chrome` on Linux or `msedge` on Windows.
- Unit tests use temporary files, generated media, and a fake semantic encoder. No ComfyUI server, GPU, models, credentials, or personal media are needed for default checks.
- Real semantic checks are opt-in: `uv sync --locked --extra semantic`, then `uv run --locked --extra semantic python tests/semantic_model_smoke.py --model bge-small`. These download model files. See the manual semantic workflow for CI.
- Keep lockfiles committed. After dependency changes run `uv lock` and/or `pnpm --dir frontend install`; keep the Windows `requirements*.txt` compatibility lists aligned with `pyproject.toml`.

## Layout

- `app/main.py`: FastAPI app, endpoints, source access checks, optional ComfyUI integration.
- `app/indexer.py`, `app/database.py`, `app/prompt_store.py`: watcher, SQLite/FTS, annotations, prompt documents.
- `app/media/`: container readers, thumbnails, probing, video playback/proxies.
- `app/metadata.py`, `app/conditioning.py`, `app/parsers/`: conservative graph extraction, output routing, format adapters and provenance.
- `app/semantic.py`: optional CPU model loading and persistent embedding caches.
- `frontend/src/`: React UI, metadata display, video player, semantic settings, prompt comparison worker.
- `tests/fixtures/`: synthetic execution graphs. `tests/prepare_*_qa.py` generates media locally. `scripts/browser_checks.py` owns browser-suite orchestration.

## Invariants

- Source media is read only. Never write originals, follow embedded file paths, or execute embedded/custom-node code.
- Keep application data, personal sources, databases, thumbnails, videos, model files, credentials and `.qa/` out of Git. Configure an isolated `GALLERY_DATA_DIR` for development/testing.
- One server process per data directory. The normal app defaults to port 8765; browser checks use 8766 and `.qa/data`. The browser runner resets generated QA settings/annotations and must never target a personal library.
- Generation is an explicit user action guarded by `confirm_generation: true`. Browsing/tests never enqueue generation; generation API tests mock the upstream service.
- Preserve literal prompt text and uncertainty. Never infer intentional emptiness from a blank extracted summary. Follow output ports when assigning positive/negative roles. Keep global and shot prompts separate and retain field/parser provenance.
- Increment `PARSER_VERSION` for common extraction/routing changes, adapter/reader versions for interpretation changes, or `SCHEMA_VERSION` for contract changes. Parser upgrades should reuse thumbnails and preserve favorites, tags, collections and reusable text embeddings.
- Every media/prompt/proxy endpoint must recheck source access. Keep 64-bit seeds as strings in JSON consumed by the UI.
- Use UTF-8 explicitly for text file I/O. Keep browser tests portable; use `tests/browser_helpers.cjs` instead of hardcoded browser locations.

When reporting changes, give the resulting behavior, relevant checks and any remaining limitations. Prefer focused regression tests for parsing and persistence changes.
