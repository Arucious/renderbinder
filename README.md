# Latent Library

A local ComfyUI image and video gallery and prompt manager for Windows. FastAPI, SQLite/FTS5, Pillow, Watchdog, React, TypeScript, and Vite. Source media is read only. Browsing, extraction, and inference run locally; optional semantic models download during setup.

For Linux, cloud agents, locked installs and CI, see [cloud development](docs/cloud-development.md). Repository instructions are in [AGENTS.md](AGENTS.md).

## Run on Windows

Prerequisites: **Python 3.11+** and **Node.js 22+ with npm**. [Python downloads](https://www.python.org/downloads/windows/) · [Node.js downloads](https://nodejs.org/en/download). The script also supports existing `uv` and `pnpm`, including the bundled Codex Node runtime in this workspace.

Double-click **start.cmd**, or run:

```powershell
cd C:\dev\comfyui-metadata-binder
.\start.ps1
```

If PowerShell blocks scripts, use `start.cmd` or `powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1`. Startup creates `.venv`, installs packages, builds the frontend, and starts **http://127.0.0.1:8765**. Initial package installation needs internet; subsequent runs reuse dependency stamps and built assets. Keep the startup window open; **Ctrl+C** stops the server/watcher. Options: `-NoBrowser`, `-Port 8877`, and `-SkipInstall`. Use one server process per data directory, without multiple Uvicorn workers.

### Connect sources

Open **Settings & sources**, enter one existing absolute directory per line, and click **Save & scan folders**. Subfolders are scanned in the background and overlapping sources are combined. Newly generated, changed, moved, and deleted files are detected automatically. **Rescan library** performs incremental reconciliation. No personal folders are scanned automatically and ComfyUI need not be installed in a particular location.

Alternatively, copy `config.example.json` to `.gallery/config.json` before starting. `GALLERY_DATA_DIR` selects another persistent data directory. Application data is excluded from indexing.

Images: PNG, JPEG, WebP, GIF/TIFF (first frame), BMP, and AVIF when supported by Pillow. Videos: MP4, WebM, MOV, MKV, M4V, and AVI with FFmpeg/ffprobe installed. Files without readable metadata can still appear in the gallery.

## Using the library

- **All media** shows images/videos. Search matches typed words across extracted prompts, filenames, all identified models, LoRAs, and tags. FTS5 treats punctuation as separators, without interpreting user text as operators or SQL. **Exact substring** matches the full phrase case-insensitively.
- Combine source, folder, media type, prompt type, model, LoRA, exact seed, date, tag, favorite, collection, workflow, and configuration filters. Folder filters include descendants. **Last 7 days** includes today and six preceding local dates. Sorting uses a timezone-aware embedded generation date when available, otherwise file modification time.
- Choose grid/list view, thumbnail size, date/filename/resolution/model sort, and date/model/workflow grouping. Group headings describe the current paginated page of 60 files. Cards load cached thumbnails rather than originals.
- Open a file for its image preview/video player, full prompts, conditioning stages, generation fields, tags, collections, source path, provenance, and raw JSON. Image originals load only on inspection or explicit download.
- Negative prompts distinguish explicitly empty text and zeroed conditioning from unavailable metadata. Mixed empty/zeroed stages are identified together; uncertain branches remain unavailable.
- **Prompt library** groups identical text before pagination, separately for image/global/shot prompts. Counts represent distinct files. Model, seed, or negative prompt differences do not split an identical positive prompt. Outer whitespace and line endings are normalized; case/internal formatting remain significant.
- **Expand prompt** loads complete text beyond the 600-character preview, on demand and without opening an image. The expanded text is reused while the card remains mounted. **Copy prompt** retrieves full text too. **View images/videos** opens all matching files.
- Select two prompt groups across searches/pages, including two shots from the same video, then **Compare prompts**. Removals are red and additions green, with exact whitespace/punctuation. **Swap A and B**, **Jump to changes**, and copy controls are available. The first changes scroll into view. [jsdiff](https://github.com/kpdecker/jsdiff) runs in a local Web Worker; large/extensively different text falls back to a labeled full-text replacement when the detailed diff exceeds its limit.
- **Find similar prompts** searches distinct prompts in the same type across configured sources. Choose **Meaning & text**, **Meaning**, or **Text**, then **Compare variation**. Scores rank relatedness, not a percentage of identical text. Text matching needs no model. Text scoring above 100,000 characters uses a labeled beginning/middle/end sample; semantic chunks include the full prompt.
- **Sources** updates without reloading, including empty folders and changes from other tabs. Virtual collections are separate. Card selection can favorite, replace tags, or add up to 60 displayed files to collections. **Set tags replaces** existing tags. Select 2–4 files to compare generation fields; use the prompt differ for individual shots.
- Collections/tags are virtual. Deleting collections never deletes source files. There is no source-file deletion endpoint.

## Video and LTX Director

Video cards have cached frame previews, a video badge, and duration. Use **Filters → Media type** to show videos. Open one for playback, audio controls, and seeking. Compatible H.264 MP4 and supported WebM streams play directly. Other codecs/containers get a cached H.264/AAC MP4 copy made in the background. **Prepare compatible playback** is available if the browser rejects a native stream. Copies are limited to 1280 pixels and at most 30 FPS. Original downloads preserve source quality and embedded metadata; source videos are never rewritten.

Install **FFmpeg and ffprobe** on PATH for video support, then restart the gallery. `GALLERY_FFMPEG`/`GALLERY_FFPROBE` can override their paths. **Settings & sources → Media & metadata formats** lists readers, parsers, versions, and video tool availability.

LTX Director has separate **global** and **shot** documents. Shots show saved time ranges when recoverable, with **Seek to shot**, copy, and similarity controls. Missing global text/timing remains unavailable. The library's **Prompt type** filter separates image/global/shot records; searching a shot does not bring in every prompt from its parent video. Similarity stays within the same type and the differ compares complete selected documents.

Metadata can come from container tags, ComfyUI save nodes, VideoHelperSuite JSON comments, or exact-name sidecars: `clip.mp4.json`, `clip.json`, `clip.workflow.json`, and `clip.timeline.json`. Sidecars may contain an API graph, visual workflow, LTX timeline, or `{prompt, workflow}` envelope. Embedded recognized fields take priority; sidecars fill missing values and conflicts are reported. Sidecar changes/deletions refresh metadata while reusing unchanged thumbnails. **Metadata** shows sources/versions/fields; **Raw JSON** retains original data.

Media readers, workflow adapters, and prompt documents have separate versioned registries and a validated schema. Future formats can be added without expanding the image extractor or adding format-specific database columns. See [the metadata architecture and extension guide](docs/metadata-architecture.md).

## Optional semantic matching

Run `.\install-semantic.ps1` once and restart. In **Settings & sources → Prompt similarity**, enable matching, select a model, and click **Save model & build embeddings**. Missing files download from Hugging Face on this action. Startup uses cached files. After setup, CPU inference/ranking run locally and prompts are not sent to a service. Browsing/text matching work during indexing. Errors appear in settings; saving retries setup. Pausing takes effect after the current download or text chunk, preserving completed embeddings; saving resumes it.

- **BGE-small-en-v1.5:** English, 384 dimensions, 512-token chunks, MIT. [Model card](https://huggingface.co/BAAI/bge-small-en-v1.5).
- **EmbeddingGemma 2:** multilingual, 768 dimensions, 8,192-token chunks, Apache 2.0. Loads its 270M-parameter text model without vision/audio encoders, using FP32 on CPU. The shared checkpoint is a larger download. This integration compares prompt text, not video imagery. [Model card](https://ai.google.dev/gemma/docs/embeddinggemma/model_card_2).
- **Custom:** a Hub `owner/model` ID or absolute local folder. Requires a Sentence Transformers text encoder with `modules.json`, safetensors weights, and a fast tokenizer with offsets. Use the author's symmetric-similarity prefix when needed, such as `query: ` for E5, applied equally to all prompts. Custom Python modeling code, GGUF, and generic generation models are unsupported. Private/gated repositories need credentials configured outside the app. Resource use depends on model size; one model loads at a time with 1–8 CPU threads.

Both presets use PyTorch on CPU. Optional requirements include modern Transformers and the processor dependency needed for EmbeddingGemma 2 text-only loading. Current ONNX dependency constraints conflict with this runtime, so ONNX is not used here.

Embeddings are cached by text, resolved model revision, prefix, and chunking configuration. Switching models preserves separate caches; editing text computes only its new embedding. The background worker checks for new prompts every ten seconds and resumes completed work after restarts/index rebuilds. Local model identity uses file names/sizes/modification times when loaded: save settings after replacing local files. Pin a Hub commit for a reproducible remote revision.

Long prompts use overlapping tokenizer-aware chunks, including the tail. Normalized chunks use symmetric best-chunk cosine matching. Hybrid ranking uses 65% semantic and 35% text similarity, with text fallback until embeddings are ready. Embeddings can overlook negation, numbers, colors, or trigger names: inspect the exact diff. Neither preset is specifically trained on these image/video prompt styles.

## Metadata extraction and limits

ComfyUI's `prompt` API execution graph and `workflow` visual graph are distinct formats. [SaveImage documentation](https://github.com/Comfy-Org/docs/blob/main/built-in-nodes/SaveImage.mdx) · [Video save nodes](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_video.py).

The common parser follows connections from recognized save/preview outputs without hardcoded node IDs. It supports common CLIP encoders including SDXL/Flux, Krea2 grounded editing (`Krea2EditGroundedEncode.inputs.prompt`), conditioning chains, KSampler/Advanced, Basic/CFGGuider, RandomNoise, KSamplerSelect, BasicScheduler, checkpoint/UNet loaders, LoRA loaders, VAE loaders, and CLIP loaders. JPEG/WebP EXIF descriptions, user comments, and JSON comments are inspected. Raw fields, unknown nodes, per-stage values, and source fields are retained.

Unknown encoders can use graph-aware prompt discovery on conditioning paths, recognizing text/caption/instruction fields including camelCase and descriptive text under unknown names. Such results are **inferred**. System instructions, notes, paths, filenames, short enums, and disconnected text are excluded from positive/negative search. Parser upgrades reuse unchanged thumbnails and preserve user annotations.

- **Graph linked** describes recognized connections to one output, not proven runtime values. **Partial extraction** marks ambiguity/heuristics. Missing values remain unavailable, defaults are never invented, and multiple distinct models/settings remain visible.
- Disconnected text remains inspectable but is excluded from positive/negative extraction. Unknown outputs make relevance uncertain; multiple outputs produce a warning because the exact producing branch may not be identifiable.
- Text generators, wildcard expansion, string transforms, remote lookups, and other custom code are never executed. Saved graphs may omit runtime output. Unresolved connected LTX text inputs are not replaced silently with stale timeline text. Arbitrary visual-workflow widget layouts are not guessed.
- Unknown LoRA stacks/loaders may require raw inspection. Resolution is measured from media, and implicit checkpoint VAE/CLIP names are not fabricated.
- Extracted seeds use strings to preserve 64-bit precision in JavaScript. Original JSON downloads retain numeric values. Metadata is limited to 8 MiB and graphs to 5,000 nodes. Corrupt files and decompression bombs are reported.
- Workflow grouping fingerprints the API/visual graph. **Find this configuration across seeds** ignores only seed/noise_seed, preserving node IDs, connections, text, and other settings; it does not prove equivalence across differently structured workflows.
- Paths/timestamps/embedded fields are not evidence of authorship. Dates without timezones are retained but not used as proven generation times.

## ComfyUI integration

ComfyUI may remain offline for indexing/browsing. Download an original/workflow and drop it into ComfyUI to recover its saved graph. **Workflow** exports the original visual workflow; **API graph** is available as appropriate. Opening ComfyUI does not silently import or execute anything.

**Run saved graph in ComfyUI** uses [`POST /prompt`](https://github.com/Comfy-Org/ComfyUI/blob/master/openapi.yaml), with an explicit checkbox and **Queue generation** click. The backend requires `confirm_generation: true`. Saved seeds remain intact, but identical output depends on installed models/nodes/versions and determinism. Browsing, playback, exports, and opening ComfyUI never queue generation. Its URL is restricted to a local HTTP origin without redirects.

## Persistence and reliability

Default data lives in `.gallery/`:

| File | Purpose |
| --- | --- |
| `config.json` | Source folders and local ComfyUI origin |
| `index.sqlite3` | Rebuildable media metadata, prompt documents, fingerprints, FTS indexes |
| `library.sqlite3` | Favorites, tags, collections, membership |
| `thumbnails/` | Image/video WebP previews, at most 480 px per side |
| `previews/` | Rebuildable compatible video playback copies |
| `semantic.json` | Semantic model and CPU settings |
| `embeddings.sqlite3` | Reusable model-specific embeddings |
| `models/` | Model files for offline inference |

Back up **library.sqlite3 and config.json** while stopped, plus semantic.json to retain model preferences. Keep the whole directory for a full backup; running SQLite databases also require handling WAL files correctly. Annotation identity is the normalized absolute path: it survives reindexing/reappearance at that path but does not follow external renames. Absent-file annotations/collections remain preserved while absent files disappear from visible counts.

One worker serializes indexing. SQLite uses WAL, write locks, parameterized queries, and per-operation connections. Incremental scans compare file size, nanosecond mtime, reader/parser versions, sidecars, and thumbnails. Unchanged media is not decoded again. Identical files at different paths remain separate records. Media metadata and prompt documents update atomically.

Filesystem events are debounced and stability is checked before/after indexing. Writes in progress retry with backoff. A five-minute reconciliation recovers missed events; unavailable watchers retry sooner. Cancelling/incomplete scans or inaccessible folders never prune unseen files. Completed scans remove absent media/documents but preserve annotations. Source removal immediately revokes original, prompt, and cached playback access.

Thumbnail/proxy writes are atomic. Replaced thumbnails are removed; deleted-file/rebuild leftovers may remain as harmless cache. To reclaim space, stop the app and remove only its `thumbnails/` or `previews/` cache directory, then restart/rescan. Originals are unaffected. Rebuilding metadata preserves library.sqlite3 and semantic caches.

The server binds to **127.0.0.1**, validates Host/Origin, sets a restrictive CSP, and serves files only through allowed indexed IDs. Scans skip symlinks/junctions and application data. Sidecar/workflow references do not authorize arbitrary path reads. Video decoders restrict protocols to local file/pipe and supported container demuxers. Metadata renders as text. There is no authentication: keep the service on loopback. Remote hosting needs its own authentication/network controls; `GALLERY_ALLOWED_HOSTS` sets accepted hostnames.

## Development and tests

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
cd frontend
npm install
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

`npm run dev` starts Vite on http://127.0.0.1:5173 with `/api` proxied to 8765. FastAPI serves production assets. For reproducible installs use `uv sync --locked` and `pnpm --dir frontend install --frozen-lockfile`; both lockfiles are committed. See [cloud development](docs/cloud-development.md) for the complete Linux setup and CI commands.

Run `.venv\Scripts\python.exe -m pytest -q`, then `npm test` and `npm run build` in `frontend`. Diff tests need Node 22.6+ for TypeScript stripping. Tests use generated media/temporary directories and cover extraction, FTS, filters, grouping, exact seeds, caches, byte preservation, annotations, cancellation, Watchdog events, source revocation, and API validation. Video tests require FFmpeg/ffprobe and skip if absent. Semantic tests use a fake encoder when optional packages exist and never download models. The generation API test is mocked. Tests do not modify the configured ComfyUI output directory.

Explicit real-model checks are `.venv\Scripts\python.exe tests\semantic_model_smoke.py --model bge-small` or `--model embeddinggemma2`. These download into `.qa/models` and encode synthetic text only.

### Isolated browser checks

The portable entry point is `uv run --locked python scripts/browser_checks.py`. It generates fixtures and owns the isolated QA server. Install the browser first as described in [cloud development](docs/cloud-development.md). Add `--semantic` for real BGE checks. For individual suites with a manually managed QA server:

`tests/prepare_browser_qa.py` creates `.qa/sources`. Start a separate server on **8766** with `GALLERY_DATA_DIR` set to the absolute `.qa/data` path. With Playwright installed or `PLAYWRIGHT_MODULE` pointing to a package, run:

```powershell
node tests/browser_smoke.cjs
node tests/browser_prompt_groups.cjs
.\.venv\Scripts\python.exe tests/prepare_prompt_diff_qa.py
node tests/browser_prompt_diff.cjs
node tests/browser_semantic.cjs
.\.venv\Scripts\python.exe tests/prepare_video_qa.py
node tests/browser_video.cjs
.\.venv\Scripts\python.exe tests/prepare_negative_status_qa.py
node tests/browser_negative_status.cjs
```

Checks use headless Edge on Windows or Chrome on Linux, save screenshots in `.qa/`, and refuse to mutate data outside `.qa/data`. Coverage includes desktop/mobile layout, group navigation, expansion caching, exact diff/copy/swap, literal markup, live sources, playback/time advancement, shot seeking, two shots from one file, MKV proxies, negative absence states, and provenance. Real BGE/custom-model checks are opt-in: run `browser_semantic.cjs` explicitly or the runner with `--semantic`; set `GALLERY_TEST_SEMANTIC=1` to include embeddings in a standalone video check. Browser checks never queue generation.
