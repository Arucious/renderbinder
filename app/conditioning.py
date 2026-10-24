"""Trace text dependencies through individual conditioning outputs, without execution."""

from __future__ import annotations

import re

# These nodes preserve each conditioning branch independently. Ports not listed
# carry models/latents/etc. and must not contribute prompt text.
PAIRED_OUTPUTS = {
    "controlnetapplyadvanced",
    "ltxvconditioning",
    "ltxdirectorguide",
    "ltxdirectorcropguides",
}
OUTPUT_INPUTS = {
    **{name: {0: ("positive",), 1: ("negative",)} for name in PAIRED_OUTPUTS},
    "conditioningzeroout": {},
    "ltxdirector": {1: ("global_prompt", "local_prompts")},
}
# Only transforms whose text behavior is known can prove an intentional absence.
# An unfamiliar node may generate text even when its stored inputs are empty.
TEXT_PASSTHROUGHS = {
    **{name: () for name in PAIRED_OUTPUTS},
    "conditioningcombine": ("conditioning_1", "conditioning_2"),
    "conditioningaverage": ("conditioning_to", "conditioning_from"),
}
EMPTY_TEXT_ENCODERS = {
    "cliptextencode": ("text",),
    "cliptextencodesdxl": ("text_g", "text_l"),
    "cliptextencodesdxlrefiner": ("text",),
    "cliptextencodeflux": ("clip_l", "t5xxl"),
    "krea2editgroundedencode": ("prompt",),
}
NON_TEXT_LINK_WORDS = {
    "clip",
    "model",
    "vae",
    "samples",
    "latent",
    "image",
    "images",
    "pixels",
    "video",
    "audio",
    "sigmas",
    "noise",
    "sampler",
    "guide",
    "mask",
    "control",
    "controlnet",
    "frame",
    "fps",
    "seed",
    "steps",
    "strength",
    "scheduler",
}
TEXT_LINK_FIELDS = {
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
NON_TEXT_OUTPUTS = {
    "MODEL",
    "CLIP",
    "VAE",
    "LATENT",
    "IMAGE",
    "AUDIO",
    "VIDEO",
    "MASK",
    "GUIDE_DATA",
    "MOTION_GUIDE_DATA",
    "FLOAT",
    "INT",
    "BOOLEAN",
    "CONTROL_NET",
    "SAMPLER",
    "SIGMAS",
    "NOISE",
    "GUIDER",
}


def words(name: str) -> set[str]:
    return set(
        re.findall(r"[a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower())
    )


def polarity(name: str) -> str | None:
    found = words(name) & {"positive", "negative"}
    return next(iter(found)) if len(found) == 1 else None


def is_text_encoder(class_type: str) -> bool:
    cls = class_type.lower()
    return (
        "textencode" in cls or "text encode" in cls or cls == "krea2editgroundedencode"
    )


def combined_state(states) -> str:
    states = set(states)
    if "present" in states:
        return "present"
    if not states or "unavailable" in states:
        return "unavailable"
    return next(iter(states)) if len(states) == 1 else "empty_and_zeroed"


class ConditioningRoutes:
    def __init__(self, graph: dict, workflow: dict | None):
        self.graph = graph
        self.unresolved: set[tuple[str, int]] = set()
        self.outputs = {}
        nodes = (workflow or {}).get("nodes", [])
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id"))
            if node_id in graph and node.get("type") == graph[node_id]["class_type"]:
                outputs = node.get("outputs")
                if isinstance(outputs, list):
                    self.outputs[node_id] = outputs

    def is_link(self, value):
        return (
            isinstance(value, list)
            and len(value) == 2
            and str(value[0]) in self.graph
            and isinstance(value[1], int)
            and not isinstance(value[1], bool)
            and value[1] >= 0
        )

    def inputs(self, node_id: str, port: int) -> tuple[str, ...]:
        node = self.graph[node_id]
        inputs = node["inputs"]
        cls = node["class_type"].lower()
        if cls in OUTPUT_INPUTS:
            return tuple(
                key for key in OUTPUT_INPUTS[cls].get(port, ()) if key in inputs
            )

        paired = {polarity(key) for key in inputs} >= {"positive", "negative"}
        schema = self.outputs.get(node_id, [])
        output = schema[port] if port < len(schema) else None
        if isinstance(output, dict):
            # Workflow port descriptions are evidence only for this exact node/type.
            # Resource outputs may reach the same encoder as conditioning outputs.
            output_type = output.get("type")
            if isinstance(output_type, str) and output_type.upper() in NON_TEXT_OUTPUTS:
                return ()
            role = polarity(str(output.get("name", "")))
            if paired and role:
                return tuple(key for key in inputs if polarity(key) == role)
        if paired:
            # Unknown multi-output routing cannot be inferred from input order or
            # the sampler role (a positive output can intentionally feed negative).
            self.unresolved.add((node_id, port))
            return ()
        return tuple(
            key
            for key, value in inputs.items()
            if not self.is_link(value)
            or key in TEXT_LINK_FIELDS
            or words(key).isdisjoint(NON_TEXT_LINK_WORDS)
        )

    def trace(self, start) -> dict[str, set[str]]:
        """Return contributing input fields, retaining output port identity at every hop."""
        seen, fields = set(), {}
        todo = [(str(start[0]), start[1])]
        while todo:
            node_id, port = todo.pop()
            if (node_id, port) in seen:
                continue
            seen.add((node_id, port))
            selected = self.inputs(node_id, port)
            fields.setdefault(node_id, set()).update(selected)
            for key in selected:
                value = self.graph[node_id]["inputs"][key]
                if self.is_link(value):
                    todo.append((str(value[0]), value[1]))
        return fields

    def negative_status(self, starts, literal, text: str) -> dict:
        """Explain absent text only when every contributing branch is understood."""
        cache, visiting = {}, set()

        def describe(value, depth=0):
            if not self.is_link(value):
                return "unavailable", []
            node_id, port = str(value[0]), value[1]
            key = (node_id, port)
            if key in visiting or depth > 64:
                return "unavailable", []
            if key in cache:
                return cache[key]
            node = self.graph[node_id]
            cls = node["class_type"].lower()
            source = {"node_id": node_id, "class_type": node["class_type"]}
            if cls == "conditioningzeroout" and port == 0:
                return "zeroed", [{**source, "state": "zeroed"}]
            selected = self.inputs(node_id, port)
            if cls in EMPTY_TEXT_ENCODERS and port == 0:
                evidence = []
                for field in EMPTY_TEXT_ENCODERS[cls]:
                    value = (
                        literal(node["inputs"].get(field))
                        if field in selected
                        else None
                    )
                    state = (
                        "unavailable"
                        if not isinstance(value, str)
                        else "present"
                        if value.strip()
                        else "empty"
                    )
                    evidence.append({**source, "input": field, "state": state})
                return combined_state(e["state"] for e in evidence), evidence
            if cls not in TEXT_PASSTHROUGHS:
                return "unavailable", [{**source, "state": "unavailable"}]
            required = TEXT_PASSTHROUGHS[cls] or selected
            if not required or any(
                not self.is_link(node["inputs"].get(field)) for field in required
            ):
                return "unavailable", [{**source, "state": "unavailable"}]
            visiting.add(key)
            children = [
                describe(node["inputs"][field], depth + 1)
                for field in selected
                if self.is_link(node["inputs"][field])
            ]
            visiting.remove(key)
            evidence = {
                (item["node_id"], item.get("input"), item["state"]): item
                for _, sources in children
                for item in sources
            }
            result = (
                combined_state(state for state, _ in children),
                list(evidence.values()),
            )
            cache[key] = result
            return result

        branches = []
        for stage_id, value in starts:
            state, sources = describe(value)
            branches.append(
                {"stage_node_id": stage_id, "state": state, "sources": sources}
            )
        return {
            "state": "present"
            if text.strip()
            else combined_state(b["state"] for b in branches),
            "branches": branches,
        }
