from __future__ import annotations

import json
from typing import Protocol

from pydantic import ValidationError

from ..media import sidecar_paths
from ..metadata import MAX_METADATA, PARSER_VERSION, _reject_constant, extract
from .ltx import LTXDirectorParser
from .schema import PromptDocument


class WorkflowParser(Protocol):
    id: str
    version: int

    def parse(self, metadata, info) -> list[dict] | None: ...


PARSERS: tuple[WorkflowParser, ...] = (LTXDirectorParser(),)
SCHEMA_VERSION = 1


def merge_sidecars(path, info, allowed):
    raw = dict(info.raw)
    provenance, warnings = [], []
    for candidate in sidecar_paths(path):
        if not candidate.is_file() or candidate.is_symlink() or not allowed(candidate):
            continue
        try:
            if candidate.stat().st_size > MAX_METADATA:
                raise ValueError("exceeds the 8 MiB metadata limit")
            container = json.loads(
                candidate.read_text(encoding="utf-8-sig"),
                parse_constant=_reject_constant,
            )
            if not isinstance(container, dict):
                raise ValueError("expected a JSON object")
            provenance.append({"path": str(candidate), "role": "sidecar"})
            raw.setdefault("sidecars", {})[candidate.name] = container
            fields = container
            if isinstance(container.get("extra_pnginfo"), dict):
                fields = {**container, **container["extra_pnginfo"]}
            if "nodes" in container and "links" in container:
                fields = {"workflow": container}
            elif any(
                isinstance(n, dict) and "class_type" in n for n in container.values()
            ):
                fields = {"prompt": container}
            elif (
                isinstance(container.get("segments"), list)
                and "global_prompt" in container
            ):
                fields = {"ltx_timeline": container}
            for key in ("prompt", "workflow", "ltx_timeline"):
                if key in fields:
                    if key in raw and raw[key] != fields[key]:
                        warnings.append(
                            f"{candidate.name}: {key} differs from the embedded metadata; embedded metadata takes priority."
                        )
                    raw.setdefault(key, fields[key])
        except (ValueError, OSError, RecursionError) as exc:
            warnings.append(f"{candidate.name}: sidecar metadata unavailable ({exc}).")
    if len(json.dumps(raw, ensure_ascii=False).encode()) > MAX_METADATA:
        raise ValueError("Combined metadata exceeds the 8 MiB limit")
    return raw, provenance, warnings


def parse_metadata(path, info, allowed):
    raw, sources, warnings = merge_sidecars(path, info, allowed)
    metadata = extract(raw)
    metadata["warnings"].extend(warnings)
    metadata["schema_version"] = SCHEMA_VERSION
    metadata["media"] = {
        "kind": info.kind,
        "duration": info.duration,
        "fps": info.fps,
        **info.technical,
    }
    metadata["metadata_sources"] = [
        {"role": "embedded", "reader": "container"},
        *sources,
    ]
    metadata["parsers"] = [{"id": "comfy-graph", "version": PARSER_VERSION}]
    documents = None
    for parser in PARSERS:
        parsed = parser.parse(metadata, info)
        if parsed is not None:
            documents = parsed
            metadata["parsers"].append({"id": parser.id, "version": parser.version})
            break
    if documents is None:
        scope = "global" if info.kind == "video" else "positive"
        documents = (
            [
                {
                    "key": "positive",
                    "scope": scope,
                    "text": metadata["positive"],
                    "label": "Global prompt"
                    if scope == "global"
                    else "Positive prompt",
                    "start": None,
                    "end": None,
                    "provenance": {
                        "parser": "comfy-graph",
                        "version": PARSER_VERSION,
                        "field": "positive",
                    },
                }
            ]
            if metadata["positive"].strip()
            else []
        )
    else:
        # Compatibility summary contains global text only. Shot text has its own records.
        metadata["positive"] = "\n\n".join(
            d["text"] for d in documents if d["scope"] == "global"
        )
    normalized = []
    for document in documents:
        try:
            normalized.append(PromptDocument.model_validate(document).model_dump())
        except ValidationError:
            metadata["warnings"].append(
                "A parser returned an invalid prompt document. Original metadata has been retained."
            )
    metadata["documents"] = normalized
    metadata["metadata_sources"][0]["reader"] = (
        "ffmpeg-video" if info.kind == "video" else "pillow-image"
    )
    return metadata
