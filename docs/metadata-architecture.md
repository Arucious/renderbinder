# Media and metadata extension points

The gallery indexes media files and their prompt documents separately. A file can have no prompts, one image prompt, or a global prompt plus several shots. Existing `/api/images` URLs and the `images` SQLite table are retained for compatibility; they now represent media records. New clients can use `/api/media` and `/api/prompts`.

## Ingestion layers

1. **Reader registry:** `app/media/readers.py` declares `READERS`. Each reader owns extensions, a stable ID and version, container probing, and thumbnail creation. Readers return `MediaInfo`: kind, measured dimensions, duration/FPS where available, technical properties, and embedded raw metadata. Pillow handles images; FFmpeg/ffprobe handle video. A reader never interprets workflow node IDs.
2. **Source resolution:** `app/parsers/pipeline.py` discovers exact-name JSON sidecars next to the media. It merges recognized workflow envelopes, records source paths and conflicts, and enforces a combined 8 MiB metadata limit. It never follows paths mentioned inside a workflow or timeline.
3. **Workflow adapters:** the existing conservative Comfy graph extractor supplies common fields. `PARSERS` registers specialized workflow adapters in priority order. An adapter returns `None` when it does not handle the workflow, or a list of documents when it does, including an empty list for a recognized workflow with no recoverable literal prompts. The first matching specialized adapter supplies the prompt documents. Other original fields remain in raw metadata.
4. **Normalized documents:** `app/parsers/schema.py` validates document keys, scope, literal text, labels, finite timestamps, and provenance. `app/prompt_store.py` persists them, maintains their FTS index, groups repeated text, and ranks related prompts. UI expansion, comparison, and embeddings consume documents without knowing their source format.

## Document contract

An adapter emits records such as:

```json
{
  "key": "director-node:shot:1",
  "scope": "shot",
  "label": "Shot 2",
  "text": "A fox runs toward a blue lake.",
  "start": 1.0,
  "end": 3.0,
  "provenance": {
    "parser": "ltx-director",
    "version": 1,
    "node_id": "director-node",
    "source": "prompt",
    "field": "local_prompts[1]"
  }
}
```

`key` identifies the field/shot within its file and must remain stable across prompt edits. `start` and `end` are seconds relative to the exported clip; use null when timing cannot be established. Extra adapter context, such as original timeline frame ranges, is retained in normalized metadata and under persisted document provenance. Never put inferred runtime text in a literal prompt field without identifying the uncertainty.

The persistent document ID combines the media path identity with this key. **Group identity includes scope and normalized text**: image prompts, global prompts, and shot prompts remain separate even when the words are identical. Normalization only strips outer whitespace and normalizes line endings. Counts represent distinct files, so repeating one prompt several times in the same video does not inflate its file count.

**Embedding identity uses text alone**, together with the embedding model revision and chunking configuration. Identical text can share an embedding across scopes without merging its library records. Similarity defaults to the source document's scope. The document endpoint also accepts `same_scope=false` for clients that explicitly want cross-type results. Exact diffs compare the complete selected documents, including two different shots from the same file.

## LTX Director adapter

Common prompt extraction traces individual `(node, output port)` connections and assigns roles to contributing input fields. `app/conditioning.py` contains output routing rules for known transforms, including LTX Guide/Crop/Conditioning and ControlNet. Matching visual-workflow output names/types can resolve unfamiliar positive/negative pairs. An ambiguous pair is left unresolved with a warning instead of combining both branches. Resource links (models, latents, guides, images, and audio) do not supply prompt text. `ConditioningZeroOut` stops text propagation because it clears the encoded conditioning. Structured JSON is not treated as prose by fallback prompt discovery; its format adapter handles explicit prompt fields.

The routing follows the [LTX Guide/Crop implementation](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/blob/main/ltx_director_guide.py) and [ComfyUI's ConditioningZeroOut/ControlNet implementations](https://github.com/Comfy-Org/ComfyUI/blob/master/nodes.py).

`negative_status` distinguishes `present`, `empty`, `zeroed`, `empty_and_zeroed`, and `unavailable`. Its `branches` record each sampler/guider's negative input and the encoder fields or zeroing nodes that establish the state. Empty/zeroed claims require all contributing branches to be understood: explicit blank text in a supported encoder, `ConditioningZeroOut`, and known text-preserving transforms. Unknown nodes, unresolved strings, missing inputs, cycles, or absent output relevance remain unavailable. A blank summary alone never proves intentional absence. Extend `EMPTY_TEXT_ENCODERS` or `TEXT_PASSTHROUGHS` only after verifying the node's behavior.

`app/parsers/ltx.py` recognizes LTX Director/Prompt Relay graph nodes. It considers nodes reachable from recognized save/preview outputs. Direct literal fields and supported primitive string links are resolved; custom nodes are never executed.

- A nonempty literal `global_prompt` input takes priority. Otherwise the global text comes from `timeline_data.global_prompt`, or `retake_global_prompt` in retake mode. An unresolved connected input does not silently substitute potentially stale timeline text.
- Saved API `local_prompts` is the canonical shot conditioning sequence. The adapter splits its `|` delimiters and uses matching comma-separated `segment_lengths` plus a known frame rate for timing. Empty prompts are not invented from a runtime fallback. Missing or inconsistent lengths leave timing unavailable.
- When canonical local text is absent, explicit timeline segments can supply shot prompts. Frame ranges are clipped to the exported interval and converted to clip-relative seconds. Retake prompt fields and workflow-only timeline JSON are also handled. Workflow-only JSON is recognized by its field schema, never a hardcoded widget position.
- Global text stays in the compatibility positive summary. Shot text is indexed in its own documents; it is never concatenated into that global summary.

The [LTX Director source](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI/blob/main/ltx_director.py) defines these fields. [ComfyUI's video save nodes](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_video.py) embed workflow/prompt JSON in container tags. VideoHelperSuite's JSON comment envelope is also recognized.

## Source precedence and updates

Sidecar names are `clip.mp4.json`, `clip.json`, `clip.workflow.json`, and `clip.timeline.json`, in that order. Supported envelopes are `{prompt, workflow}`, an API graph itself, a visual workflow itself, or LTX timeline JSON. Embedded recognized fields take priority; sidecars fill missing fields. Conflicts and unreadable sidecars are visible as metadata warnings. Every readable sidecar is preserved in raw metadata. Files must remain inside configured sources; symlink sidecars and references to other files are not followed.

The index fingerprint includes media size/mtime, sidecar names/sizes/mtimes, the schema version, and all registered reader/adapter IDs and versions. Changes to sidecars enqueue their associated media, including dotted file names. Parser upgrades reuse an unchanged file's thumbnail. The metadata index and prompt FTS records update together in a transaction; favorites and collections remain in the separate library database.

Incremental scans and the normal filesystem reconciliation also detect sidecar changes. A scan that is cancelled or cannot enumerate a source does not prune unseen files. Deleting media cascades to its prompt records and FTS entries. Embeddings remain reusable cache entries and do not grant access to files from removed sources.

## Adding a reader or adapter

- For a new container/media type, implement the `MediaReader` protocol, return `MediaInfo`, and register it in `READERS`. Extensions are discovered from the registry at startup. Technical format-specific values belong in the technical JSON object. Increment the reader version when interpretation changes. Add an appropriate preview/playback component if the type is not an image or video.
- For a new workflow/metadata format, implement `WorkflowParser.parse(metadata, info)` and register it in `PARSERS` before less specific adapters. It can populate common normalized fields such as models/settings and must return validated prompt documents when applicable. Keep opaque fields in raw metadata, record parser/field provenance, and increment the adapter version when extraction changes. Do not add engine-specific columns to SQLite.
- Change `SCHEMA_VERSION` for a normalized contract change. Change `PARSER_VERSION` for common Comfy graph extraction changes. Registry versions automatically invalidate metadata fingerprints without invalidating text embeddings whose content is unchanged.
- Add verified output-to-input mappings to `app/conditioning.py` when a new transform requires branch routing or erases text. Increment the common `PARSER_VERSION` so existing cached summaries and search records are repaired.
- Register only application-controlled parser code. This is an internal extension interface, not permission to load executable plugins from media files.

Use synthetic fixture files to test source precedence, unsupported fields, scope grouping, timestamps, cache reuse, source revocation, and byte preservation. The video integration tests require FFmpeg/ffprobe and skip when they are absent. Browser checks exercise actual decoding and seeking in Edge.

## Playback and cache

Native H.264/AAC MP4 and supported WebM streams play directly through range-capable local endpoints. Other codecs/containers, or an explicit compatible-playback request, use a cached H.264/AAC MP4 proxy limited to 1280 pixels and at most 30 FPS. One CPU conversion runs at a time with a bounded queue; it has a ten-minute timeout. The original file is never rewritten. Proxy identity includes the media fingerprint and conversion recipe version.

`POST /api/media/{id}/playback` prepares playback; its JSON response is ready, processing, or error. A ready response provides a stream URL. `GET /api/media/{id}/playback` streams bytes with range support. `compatible=true` explicitly requests a proxy; `retry=true` on preparation retries a failed job. Every request rechecks configured-source access, including requests for cached proxies. FFmpeg is restricted to local file/pipe protocols and supported container demuxers.

Data files added by these features are rebuildable prompt tables/FTS in `index.sqlite3`, video thumbnails in `thumbnails/`, and playback proxies in `previews/`. `semantic.json`, `models/`, and `embeddings.sqlite3` retain the existing semantic matching settings and caches.
