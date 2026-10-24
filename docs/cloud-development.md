# Cloud and Linux development

A fresh clone contains all source, synthetic graph fixtures, dependency lockfiles, build commands, test runners and GitHub Actions workflows. The default checks run locally within the checkout using generated data. ComfyUI, a GPU, a personal output directory and model downloads are optional.

## Toolchain

Use Python 3.13 (`.python-version`), Node 24 (`.node-version`), uv 0.12.8 and pnpm 11.25.0 (`frontend/package.json`). CI also tests Python 3.11. Install FFmpeg with ffprobe for the video integration tests.

For an Ubuntu environment with Node and Python already available:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
python3 -m pip install uv==0.12.8
npm install --global pnpm@11.25.0
bash scripts/setup.sh
bash scripts/check.sh
```

If system Python is externally managed, install uv using its [official installer](https://docs.astral.sh/uv/getting-started/installation/) or a dedicated tool environment. Network access is needed for initial package/browser installation. Downloads use PyPI, the public npm registry, and the official browser repositories; the optional semantic extra also uses the PyTorch CPU index. `uv.lock` and `frontend/pnpm-lock.yaml` contain exact resolutions and hashes. The default uv sync includes development tools and NumPy for fake-encoder tests, while the semantic stack remains an optional extra.

## Run or preview

```bash
export GALLERY_DATA_DIR="$PWD/.qa/dev-data"
uv run --locked python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

The production frontend is served at http://127.0.0.1:8765 after setup/build. For Vite's dev server, use `pnpm --dir frontend dev` in a second terminal; it proxies `/api` to the backend. Keep one backend process per data directory. Use `GALLERY_DATA_DIR` to separate each environment's state. Start from an empty config; sources are selected in the UI.

To populate a preview with synthetic media, run `uv run --locked python tests/prepare_browser_qa.py` and add the absolute `.qa/sources` path through Settings & sources. Video fixtures come from `tests/prepare_video_qa.py`. The example config uses illustrative paths only. For a remote preview, configure the development environment's port forwarding and accepted hostname with `GALLERY_ALLOWED_HOSTS`; retain loopback binding unless your environment provides an appropriate authenticated boundary. The app itself has no login system.

## Browser checks

```bash
pnpm --dir frontend exec playwright install --with-deps chrome
uv run --locked python scripts/browser_checks.py
# Or include all ordinary checks:
bash scripts/check.sh --browser
```

The runner prepares fixtures, resets generated QA configuration, starts its own server on 8766, waits for readiness, runs suites in order and stops the process afterward. It refuses to run if 8766 is already in use. Tests verify the QA data-directory identity before making changes. The normal library on 8765 and `.gallery` are separate.

Chrome is the default on Linux and Edge on Windows. Set `BROWSER_CHANNEL` to select another installed Playwright channel; H.264/AAC playback checks require a browser with those codecs ([Playwright browser documentation](https://playwright.dev/docs/browsers#google-chrome--microsoft-edge)). `PLAYWRIGHT_MODULE` can override the project dependency for a preinstalled runtime. Screenshots, generated media and logs stay under ignored `.qa/`. The suites cover sources, grouping, exact seed copy, annotations/collections, full-prompt expansion, exact diffs, negative absence states, native video decoding/playback, shot seeking, scope search and compatible MKV playback. Default similarity checks use text matching.

## Optional real-model tests

```bash
uv sync --locked --extra semantic
uv run --locked --extra semantic python tests/semantic_model_smoke.py --model bge-small
# Larger model; downloads more data:
uv run --locked --extra semantic python tests/semantic_model_smoke.py --model embeddinggemma2
# Full UI checks including real BGE embeddings and a local custom model folder:
uv run --locked --extra semantic python scripts/browser_checks.py --semantic
```

CPU-only torch/torchvision wheels are selected on Linux and Windows. Model caches and embeddings are never checked in. The manual **Optional semantic model smoke** GitHub workflow runs one selected model; default push/PR CI does not download models.

## CI and changes

`.github/workflows/ci.yml` runs Ruff/backend integration tests on Python 3.11/3.13 plus frontend diff tests, TypeScript/production build and all default browser suites on Ubuntu. FFmpeg and Chrome are provisioned. Failed browser runs upload only synthetic screenshots and the QA server log. Jobs have bounded timeouts and read-only repository permissions.

`pyproject.toml` and `uv.lock` are the reproducible Python project definition. `requirements*.txt` remain compatible with the Windows launcher and should be kept aligned. Node installs use pnpm's frozen lockfile. After changing dependencies, update the corresponding lockfile and run the checks. Original data lives outside the repository and is not needed to reproduce tests. See [AGENTS.md](../AGENTS.md) and [metadata architecture](metadata-architecture.md) for invariants and extension rules.
