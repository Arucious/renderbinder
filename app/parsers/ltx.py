from __future__ import annotations

import json
import math

from ..graph import active_nodes


def number(value):
    return (
        float(value)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def object_value(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            return {}
    return value if isinstance(value, dict) else {}


class LTXDirectorParser:
    id, version = "ltx-director", 1
    classes = {
        "LTXDirector",
        "PromptRelayEncodeTimeline",
        "LTXSequencer",
        "PromptRelayEncode",
    }

    def parse(self, metadata, info):
        graph = metadata.get("prompt") or {}
        graph = {
            str(k): n
            for k, n in graph.items()
            if isinstance(n, dict) and isinstance(n.get("inputs"), dict)
        }
        active = active_nodes(graph)

        def literal(value, seen=None):
            seen = seen or set()
            if isinstance(value, str):
                return value
            if isinstance(value, list) and len(value) == 2:
                key = str(value[0])
                if key in seen or key not in graph:
                    return None
                node = graph[key]
                if node.get("class_type", "").lower() in {
                    "primitivestring",
                    "primitivestringmultiline",
                    "string",
                    "stringconstant",
                    "string literal",
                }:
                    fields = node["inputs"]
                    return literal(
                        fields.get("value", fields.get("text", fields.get("string"))),
                        seen | {key},
                    )
            return None

        contexts = [
            (key, node["inputs"], "prompt")
            for key, node in graph.items()
            if key in active and node.get("class_type") in self.classes
        ]
        # Visual-workflow-only exports: identify the timeline by its explicit schema,
        # never by a guessed widget index or arbitrary descriptive strings.
        if not contexts:
            workflow_nodes = (metadata.get("workflow") or {}).get("nodes", [])
            if not isinstance(workflow_nodes, list):
                workflow_nodes = []
            for node in workflow_nodes:
                if not isinstance(node, dict) or node.get("type") not in self.classes:
                    continue
                for index, value in enumerate(node.get("widgets_values", [])):
                    timeline = object_value(value)
                    if (
                        isinstance(timeline.get("segments"), list)
                        and "global_prompt" in timeline
                    ):
                        contexts.append(
                            (
                                str(node.get("id")),
                                {"timeline_data": timeline},
                                f"workflow.widgets_values[{index}]",
                            )
                        )
        standalone = metadata["raw"].get("ltx_timeline")
        if isinstance(standalone, dict):
            contexts.append(
                ("timeline", {"timeline_data": standalone}, "sidecar.timeline")
            )
        if not contexts:
            return None
        documents = []
        for key, inputs, source in contexts:
            timeline = object_value(inputs.get("timeline_data"))
            retake = timeline.get("retakeMode") is True
            global_text = literal(inputs.get("global_prompt"))
            unresolved_global = (
                isinstance(inputs.get("global_prompt"), list) and global_text is None
            )
            if unresolved_global:
                metadata["warnings"].append(
                    f"LTX Director #{key}: connected global prompt could not be resolved without executing its node. Timeline text was not substituted."
                )
            elif not global_text:
                global_text = timeline.get(
                    "retake_global_prompt" if retake else "global_prompt", ""
                )
            provenance = {
                "parser": self.id,
                "version": self.version,
                "node_id": key,
                "source": source,
            }

            def add(doc_id, scope, text, label, field, **values):
                if isinstance(text, str) and text.strip():
                    documents.append(
                        {
                            "key": f"{key}:{doc_id}",
                            "scope": scope,
                            "text": text,
                            "label": label,
                            "start": None,
                            "end": None,
                            "provenance": {**provenance, "field": field},
                            **values,
                        }
                    )

            add(
                "global",
                "global",
                global_text,
                "Global prompt",
                "global_prompt"
                if literal(inputs.get("global_prompt"))
                else "timeline_data.retake_global_prompt"
                if retake
                else "timeline_data.global_prompt",
            )
            # Saved playback rate controls seeking when an exporter retimes frames.
            fps = info.fps or number(inputs.get("frame_rate"))
            origin = number(inputs.get("start_frame")) or 0
            duration = number(inputs.get("duration_frames"))
            locals_text = literal(inputs.get("local_prompts"))
            lengths_text = literal(inputs.get("segment_lengths"))
            if isinstance(inputs.get("local_prompts"), list) and locals_text is None:
                metadata["warnings"].append(
                    f"LTX Director #{key}: connected shot prompts could not be resolved without executing their node."
                )
                continue
            if locals_text is not None and locals_text.strip():
                texts = locals_text.split("|")
                try:
                    lengths = [
                        float(v.strip()) for v in (lengths_text or "").split(",")
                    ]
                    timed = (
                        len(lengths) == len(texts)
                        and all(math.isfinite(v) and v > 0 for v in lengths)
                        and fps
                        and fps > 0
                    )
                except ValueError:
                    lengths, timed = [], False
                cursor = 0.0
                for index, text in enumerate(texts):
                    end = cursor + lengths[index] if timed else None
                    add(
                        f"shot:{index}",
                        "shot",
                        text,
                        f"Shot {index + 1}",
                        f"local_prompts[{index}]",
                        start=cursor / fps if timed else None,
                        end=end / fps if timed else None,
                        timeline_start_frame=origin + cursor if timed else None,
                        timeline_end_frame=origin + end if timed else None,
                    )
                    if timed:
                        cursor = end
            elif retake and isinstance(timeline.get("retakePrompt"), str):
                start, length = (
                    number(timeline.get("retakeStart")),
                    number(timeline.get("retakeLength")),
                )
                add(
                    "retake",
                    "shot",
                    timeline["retakePrompt"],
                    "Retake prompt",
                    "timeline_data.retakePrompt",
                    start=max(0, start - origin) / fps
                    if fps and start is not None
                    else None,
                    end=max(0, start + length - origin) / fps
                    if fps and start is not None and length is not None
                    else None,
                )
            elif timeline.get("mainTrackEnabled", True):
                segments = timeline.get("segments", [])
                if not isinstance(segments, list):
                    segments = []
                segments = sorted(
                    (s for s in segments if isinstance(s, dict)),
                    key=lambda s: number(s.get("start")) or 0,
                )
                for index, segment in enumerate(segments):
                    if segment.get("isEndFrame") or segment.get(
                        "type", "image"
                    ) not in {"image", "video", "text", "prompt"}:
                        continue
                    start, length = (
                        number(segment.get("start")),
                        number(segment.get("length")),
                    )
                    end = (
                        start + length
                        if start is not None and length is not None
                        else None
                    )
                    if (
                        start is not None
                        and end is not None
                        and (
                            end <= origin
                            or duration is not None
                            and start >= origin + duration
                        )
                    ):
                        continue
                    clipped_start = max(start, origin) if start is not None else None
                    clipped_end = (
                        min(end, origin + duration)
                        if end is not None and duration is not None
                        else end
                    )
                    add(
                        f"segment:{segment.get('id', index)}",
                        "shot",
                        segment.get("prompt"),
                        f"Shot {index + 1}",
                        f"timeline_data.segments[{index}].prompt",
                        start=(clipped_start - origin) / fps
                        if fps and clipped_start is not None
                        else None,
                        end=(clipped_end - origin) / fps
                        if fps and clipped_end is not None
                        else None,
                        timeline_start_frame=start,
                        timeline_end_frame=end,
                    )
        return documents
