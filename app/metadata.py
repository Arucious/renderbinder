"""Conservative graph extraction. Raw fields are retained; missing values stay missing."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any

from PIL import Image

from .conditioning import ConditioningRoutes, is_text_encoder
from .graph import is_output

MAX_METADATA = 8 * 1024 * 1024
MAX_NODES = 5000
PARSER_VERSION = 7
PROMPT_INPUTS = {
    "text",
    "text_g",
    "text_l",
    "prompt",
    "positive",
    "negative",
    "string",
    "value",
    "t5xxl",
    "clip_l",
}
TEXT_FIELD_WORDS = {
    "prompt",
    "text",
    "caption",
    "description",
    "instruction",
    "content",
    "message",
}
NON_PROMPT_WORDS = {
    "system",
    "filename",
    "path",
    "directory",
    "folder",
    "model",
    "checkpoint",
    "lora",
    "vae",
    "seed",
    "sampler",
    "scheduler",
    "format",
    "device",
    "note",
    "notes",
    "comment",
    "title",
    "label",
    "url",
    "key",
    "token",
}
SAMPLER_FIELDS = {
    "seed": ("seed", "noise_seed"),
    "steps": ("steps",),
    "cfg": ("cfg", "cfg_scale"),
    "sampler": ("sampler_name",),
    "scheduler": ("scheduler",),
    "denoise": ("denoise",),
    "start_at_step": ("start_at_step",),
    "end_at_step": ("end_at_step",),
}


def digest(value: Any) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, bytes):
        # EXIF UserComment can be prefixed with an eight-byte character code.
        for prefix, encoding in [
            (b"ASCII\x00\x00\x00", "ascii"),
            (b"UNICODE\x00", "utf-16"),
        ]:
            if value.startswith(prefix):
                return value[8:].decode(encoding, errors="replace")
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return {"encoding": "base64", "data": base64.b64encode(value).decode()}
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    return str(value)


def _reject_constant(value: str):
    raise ValueError(f"Non-standard JSON constant: {value}")


def _field_words(key: str) -> set[str]:
    return set(
        re.findall(r"[a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower())
    )


def _descriptive_text(text: str) -> bool:
    """A conservative last resort on an actual conditioning path, never all metadata."""
    if text.lstrip().startswith(("{", "[")):
        try:
            if isinstance(json.loads(text), (dict, list)):
                return False
        except (ValueError, RecursionError):
            pass
    return (
        len(text.strip()) >= 35
        and len(re.findall(r"[^\W_]+", text, flags=re.UNICODE)) >= 6
        and not re.match(r"^(?:[a-zA-Z]:[\\/]|[\\/]|https?://)", text.strip())
        and not re.search(
            r"\.(?:safetensors|ckpt|gguf|png|jpe?g|webp|json|pt|pth)$",
            text.strip(),
            flags=re.IGNORECASE,
        )
    )


def read_metadata(image: Image.Image) -> dict:
    raw = {str(k): _safe(v) for k, v in image.info.items()}
    try:
        exif = image.getexif()
        if exif:
            raw["exif"] = {str(k): _safe(v) for k, v in exif.items()}
            try:
                raw["exif_ifd"] = {
                    str(k): _safe(v) for k, v in exif.get_ifd(34665).items()
                }
            except (KeyError, ValueError, TypeError):
                pass
    except (ValueError, OSError, SyntaxError):
        pass
    if len(json.dumps(raw, ensure_ascii=False).encode()) > MAX_METADATA:
        raise ValueError("Embedded metadata exceeds the 8 MiB safety limit")
    # JPEG and WebP exporters commonly put the same JSON container in EXIF.
    containers = [raw.get("comment"), raw.get("description"), raw.get("xmp")]
    for group in (raw.get("exif", {}), raw.get("exif_ifd", {})):
        containers.extend(group.get(key) for key in ("270", "37510"))
    for value in containers:
        if isinstance(value, str):
            try:
                parsed = json.loads(
                    value.strip("\x00 \n\r"), parse_constant=_reject_constant
                )
                if isinstance(parsed, dict):
                    for key in ("prompt", "workflow"):
                        if key in parsed and key not in raw:
                            raw[key] = parsed[key]
                    if "prompt" not in raw and any(
                        isinstance(n, dict) and "class_type" in n
                        for n in parsed.values()
                    ):
                        raw["prompt"] = parsed
            except (ValueError, RecursionError):
                pass
    return raw


def extract(raw: dict) -> dict:
    warnings: list[str] = []

    def json_field(key: str):
        value = raw.get(key)
        if isinstance(value, str):
            try:
                value = json.loads(value, parse_constant=_reject_constant)
            except (ValueError, RecursionError):
                warnings.append(
                    f"The {key} field is not valid JSON; the original text is available in raw metadata."
                )
                return None
        return value if isinstance(value, dict) else None

    prompt, workflow = json_field("prompt"), json_field("workflow")
    if prompt and isinstance(prompt.get("prompt"), dict):
        prompt = prompt["prompt"]
    graph = {
        str(k): n
        for k, n in (prompt or {}).items()
        if isinstance(n, dict)
        and isinstance(n.get("class_type"), str)
        and isinstance(n.get("inputs"), dict)
    }
    if len(graph) > MAX_NODES:
        warnings.append(
            "Graph exceeds the 5,000 node extraction limit. Original metadata is preserved."
        )
        graph = {}

    routes = ConditioningRoutes(graph, workflow)
    link = routes.is_link

    def upstream(starts):
        seen, todo = set(), list(starts)
        while todo:
            node_id = str(todo.pop())
            if node_id in seen or node_id not in graph:
                continue
            seen.add(node_id)
            todo.extend(
                str(v[0]) for key, v in graph[node_id]["inputs"].items() if link(v)
            )
        return seen

    def literal(value, depth=0):
        if not link(value):
            return value
        if depth > 12:
            return None
        node = graph[str(value[0])]
        cls = node["class_type"].lower()
        # Only known pass-through primitives; do not evaluate arbitrary custom code.
        if cls in {
            "primitivenode",
            "primitiveint",
            "primitivefloat",
            "primitivestring",
            "primitivestringmultiline",
            "string literal",
            "integer",
            "float",
            "string",
        }:
            for k in ("value", "text", "string", "int", "float"):
                if k in node["inputs"]:
                    return literal(node["inputs"][k], depth + 1)
        return None

    outputs = [k for k, n in graph.items() if is_output(n["class_type"])]
    active = upstream(outputs) if outputs else set(graph)
    if len(outputs) > 1:
        warnings.append(
            "Multiple image outputs are embedded. Fields describe their combined reachable graph; the producing branch cannot be proven from this image alone."
        )
    if graph and not outputs:
        warnings.append(
            "No recognized image output node. Execution relevance is unknown."
        )
    stages, prompts, field_roles, negative_inputs = [], [], {}, []
    samplers = [
        (k, n)
        for k, n in graph.items()
        if k in active
        and "sampler" in n["class_type"].lower()
        and n["class_type"].lower() != "ksamplerselect"
    ]
    # BasicGuider/CFGGuider supply conditioning for advanced custom sampling.
    conditioning_nodes = samplers + [
        (k, n)
        for k, n in graph.items()
        if k in active
        and (
            "guider" in n["class_type"].lower()
            or n["class_type"].lower()
            in {
                "randomnoise",
                "basicscheduler",
                "karrasscheduler",
                "exponentialscheduler",
                "ksamplerselect",
                "alignyourstepsscheduler",
            }
        )
    ]
    for node_id, node in conditioning_nodes:
        stage = {
            "node_id": node_id,
            "class_type": node["class_type"],
            "settings": {},
            "positive_nodes": [],
            "negative_nodes": [],
        }
        for field, aliases in SAMPLER_FIELDS.items():
            for key in aliases:
                if key in node["inputs"]:
                    value = literal(node["inputs"][key])
                    if (
                        value is not None
                        and isinstance(value, (str, int, float))
                        and not isinstance(value, bool)
                    ):
                        # A 64-bit seed must survive JavaScript's 53-bit integer limit.
                        stage["settings"][field] = (
                            str(value) if field == "seed" else value
                        )
                    break
        for role, keys in (
            ("positive", ("positive", "conditioning")),
            ("negative", ("negative",)),
        ):
            for key in keys:
                value = node["inputs"].get(key)
                if role == "negative" and (
                    key in node["inputs"]
                    or "positive" in node["inputs"]
                    or node["class_type"].lower()
                    in {"ksampler", "ksampleradvanced", "samplercustom", "cfgguider"}
                ):
                    negative_inputs.append((node_id, value))
                if link(value):
                    ancestors = routes.trace(value)
                    stage[f"{role}_nodes"].extend(sorted(ancestors))
                    for ancestor, fields in ancestors.items():
                        for field in fields:
                            field_roles.setdefault((ancestor, field), set()).add(role)
        stages.append(stage)
    for node_id, port in sorted(routes.unresolved):
        warnings.append(
            f"Prompt routing for {node_id} ({graph[node_id]['class_type']}) output {port} "
            "is unknown; its positive and negative inputs were not combined. Original metadata is retained."
        )
    role_nodes = {node_id for node_id, _ in field_roles}
    for node_id, node in graph.items():
        cls = node["class_type"].lower()
        known = (
            is_text_encoder(cls)
            or cls in {"string", "string literal", "primitivestring", "primitivenode"}
            or cls == "krea2editgroundedencode"
        )
        # Custom prompt nodes are retained as candidates, with explicitly lower confidence.
        has_roles = node_id in role_nodes
        # Names are hints, not requirements: unfamiliar conditioning nodes can
        # carry prompts under entirely different names. Graph evidence limits
        # fuzzy discovery to inputs contributing to positive/negative branches.
        candidate = (
            known or "prompt" in cls or "text" in cls or "string" in cls or has_roles
        )
        if not candidate:
            continue
        for key, value in node["inputs"].items():
            roles = field_roles.get((node_id, key), set())
            words = _field_words(key)
            if not words.isdisjoint(NON_PROMPT_WORDS):
                continue
            text = literal(value)
            if not isinstance(text, str) or not text.strip():
                continue
            recognized_input = key in PROMPT_INPUTS
            named_text = not words.isdisjoint(TEXT_FIELD_WORDS)
            if not recognized_input and not (
                roles and (named_text or _descriptive_text(text))
            ):
                continue
            role = (
                next(iter(roles))
                if len(roles) == 1
                else "both"
                if roles
                else "unassigned"
            )
            title = (
                node.get("_meta", {}).get("title", node["class_type"])
                if isinstance(node.get("_meta", {}), dict)
                else node["class_type"]
            )
            prompts.append(
                {
                    "node_id": node_id,
                    "class_type": node["class_type"],
                    "title": str(title),
                    "input": key,
                    "text": text,
                    "role": role,
                    "used": (node_id in active) if outputs else None,
                    "confidence": "high"
                    if known and recognized_input and roles and outputs
                    else "inferred",
                    "discovery": "recognized_encoder"
                    if known and recognized_input
                    else "conditioning_field"
                    if recognized_input or named_text
                    else "conditioning_text",
                }
            )

    models, loras, vaes, encoders, parameters, sources = [], [], [], [], {}, {}
    for node_id, node in graph.items():
        if node_id not in active:
            continue
        inp, cls = node["inputs"], node["class_type"].lower()
        for key in ("ckpt_name", "unet_name", "model_name"):
            value = literal(inp.get(key))
            if isinstance(value, str) and (
                key != "model_name"
                or any(t in cls for t in ("loader", "checkpoint", "unet"))
            ):
                if value not in models:
                    models.append(value)
                sources.setdefault("model", []).append(node_id)
        for key in ("lora_name", "lora"):
            value = literal(inp.get(key))
            if isinstance(value, str) and "lora" in cls:
                loras.append(
                    {
                        "name": value,
                        "strength_model": literal(
                            inp.get("strength_model", inp.get("strength"))
                        ),
                        "strength_clip": literal(inp.get("strength_clip")),
                        "node_id": node_id,
                    }
                )
        value = literal(inp.get("vae_name"))
        if isinstance(value, str):
            vaes.append(value)
        for key in ("clip_name", "clip_name1", "clip_name2", "clip_name3", "t5_name"):
            value = literal(inp.get(key))
            if isinstance(value, str):
                encoders.append(value)
        # Preserve all scalar inputs as available additional settings, with node provenance.
        scalar = {
            k: v for k, v in inp.items() if isinstance(v, (str, int, float, bool))
        }
        parameters[node_id] = {"class_type": node["class_type"], "inputs": scalar}
    settings: dict[str, list] = {}
    for stage in stages:
        for key, value in stage["settings"].items():
            if value not in settings.setdefault(key, []):
                settings[key].append(value)
                sources.setdefault(key, []).append(stage["node_id"])
    positive = list(
        dict.fromkeys(
            p["text"]
            for p in prompts
            if p["role"] in {"positive", "both"} and p["used"] is not False
        )
    )
    negative = list(
        dict.fromkeys(
            p["text"]
            for p in prompts
            if p["role"] in {"negative", "both"} and p["used"] is not False
        )
    )
    inferred_prompts = any(
        p["confidence"] == "inferred"
        and p["used"] is not False
        and p["role"] != "unassigned"
        for p in prompts
    )
    if inferred_prompts:
        warnings.append(
            "Some prompt text was discovered heuristically on conditioning paths. "
            "It is stored input text; custom-node runtime transformations could not be verified."
        )
    if workflow and not graph:
        warnings.append(
            "Only the visual workflow is available. Widget values are preserved but are not assumed to be executed prompts or settings."
        )
    if not prompt and not workflow:
        warnings.append(
            "No readable ComfyUI execution graph or workflow is embedded in this image."
        )
    generated_at = None
    for value in [
        raw.get("creation_time"),
        raw.get("date:create"),
        raw.get("exif_ifd", {}).get("36867"),
    ]:
        if not isinstance(value, str):
            continue
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.tzinfo:
                generated_at = date.timestamp()
                break
            warnings.append(
                "Embedded date has no timezone; sorting uses file modification time."
            )
        except ValueError:
            pass
    # API graph identity excludes seeds only; preserves node ids, connections and prompts.
    normalized = json.loads(json.dumps(graph))
    for node in normalized.values():
        for key in ("seed", "noise_seed"):
            if key in node["inputs"]:
                node["inputs"][key] = "<seed>"
    negative_status = routes.negative_status(
        negative_inputs, literal, "\n\n".join(negative)
    )
    if not outputs and not negative:
        negative_status["state"] = "unavailable"
    return {
        "positive": "\n\n".join(positive),
        "negative": "\n\n".join(negative),
        "negative_status": negative_status,
        "prompts": prompts,
        "stages": stages,
        "models": models,
        "loras": loras,
        "vaes": list(dict.fromkeys(vaes)),
        "text_encoders": list(dict.fromkeys(encoders)),
        "settings": settings,
        "sources": sources,
        "additional_parameters": parameters,
        "confidence": "high"
        if graph and outputs and len(outputs) == 1 and positive and not inferred_prompts
        else "partial"
        if graph or workflow
        else "unavailable",
        "warnings": warnings,
        "prompt": prompt,
        "workflow": workflow,
        "raw": raw,
        "workflow_hash": digest(graph) if graph else digest(workflow),
        "configuration_hash": digest(normalized) if graph else None,
        "generated_at": generated_at,
    }
