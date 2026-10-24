import copy
import json
from pathlib import Path

import pytest
from conftest import save_image
from PIL import Image

from app.metadata import extract, read_metadata


def fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())


def test_connections_not_node_ids(graph):
    data = extract({"prompt": json.dumps(graph), "unknown_field": "preserved"})
    assert data["positive"] == "a glass cabin, cinematic lighting, alpine forest"
    assert data["negative"] == "blurry, watermark"
    assert data["settings"]["seed"] == ["18446744073709551615"]
    assert data["settings"]["cfg"] == [7.5]
    assert data["loras"][0]["strength_model"] == 0.7
    assert data["confidence"] == "high"
    assert data["raw"]["unknown_field"] == "preserved"
    unused = next(p for p in data["prompts"] if p["node_id"] == "999")
    assert unused["used"] is False
    assert "SECRET" not in data["positive"]


def test_custom_sampling_and_unknown_nodes():
    graph = fixture("custom")
    data = extract({"prompt": graph})
    assert "luminous garden" in data["positive"]
    assert data["settings"]["seed"] == ["9007199254740993"]
    assert data["settings"]["sampler"] == ["dpmpp_2m"]
    assert data["settings"]["scheduler"] == ["simple"]
    assert data["settings"]["steps"] == [20]
    assert data["models"] == ["flux.safetensors"]
    assert data["text_encoders"] == ["clip_l.safetensors", "t5xxl.safetensors"]
    assert data["prompt"]["alien"] == graph["alien"]
    assert data["negative"] == ""
    assert "cfg" not in data["settings"]


def test_krea2_grounded_edit_prompt_from_sampler_connection():
    graph = fixture("krea2_grounded_edit")
    data = extract({"prompt": graph})
    assert data["positive"] == graph["grounded-positive"]["inputs"]["prompt"]
    assert data["negative"] == ""
    assert data["confidence"] == "high"
    assert data["models"] == ["Krea2Realism_V1.safetensors"]
    assert "System instructions" not in data["positive"]
    assert "Disconnected" not in data["positive"]
    prompt = next(p for p in data["prompts"] if p["node_id"] == "grounded-positive")
    assert prompt["role"] == "positive" and prompt["used"] is True
    assert prompt["input"] == "prompt" and prompt["confidence"] == "high"
    unused = next(p for p in data["prompts"] if p["node_id"] == "unused")
    assert unused["used"] is False


def test_krea2_negative_prompt_and_linked_primitive():
    graph = fixture("krea2_grounded_edit")
    graph["grounded-negative"]["inputs"]["prompt"] = "blurred edges"
    graph["primitive"] = {
        "class_type": "PrimitiveString",
        "inputs": {"value": "a snowy cabin"},
    }
    graph["grounded-positive"]["inputs"]["prompt"] = ["primitive", 0]
    data = extract({"prompt": graph})
    assert data["positive"] == "a snowy cabin"
    assert data["negative"] == "blurred edges"


@pytest.mark.parametrize(
    "field", ["prompt", "instruction_text", "userCaption", "payload"]
)
def test_unknown_conditioning_node_discovers_prompt_without_class_mapping(field):
    graph = fixture("krea2_grounded_edit")
    encoder = graph["grounded-positive"]
    encoder["class_type"] = "VendorGroundedConditioning"
    text = encoder["inputs"].pop("prompt")
    encoder["inputs"][field] = text
    encoder["inputs"]["notes"] = (
        "These are sufficiently long internal notes that are not an image prompt."
    )
    encoder["inputs"]["cache_path"] = (
        "C:\\images with spaces\\cache files\\reference image.png"
    )
    encoder["inputs"]["mode"] = "balanced"
    data = extract({"prompt": graph})
    assert data["positive"] == text
    assert data["confidence"] == "partial"
    prompt = next(p for p in data["prompts"] if p["node_id"] == "grounded-positive")
    assert prompt["input"] == field and prompt["confidence"] == "inferred"
    assert prompt["discovery"] == (
        "conditioning_text" if field == "payload" else "conditioning_field"
    )
    assert any("heuristically" in w for w in data["warnings"])


def test_heuristic_prompt_discovery_keeps_negative_role_and_does_not_guess_short_enums():
    graph = fixture("krea2_grounded_edit")
    graph["grounded-negative"]["class_type"] = "VendorConditioning"
    graph["grounded-negative"]["inputs"]["negative_prompt"] = "blurred edges"
    graph["grounded-positive"]["class_type"] = "VendorConditioning"
    graph["grounded-positive"]["inputs"].pop("prompt")
    graph["grounded-positive"]["inputs"]["mode"] = "balanced"
    data = extract({"prompt": graph})
    assert data["positive"] == ""
    assert data["negative"] == "blurred edges"


def test_multiple_conditioning_stages():
    data = extract({"prompt": fixture("multiple_stages")})
    assert (
        "wide mountain scene" in data["positive"]
        and "fine snow detail" in data["positive"]
    )
    assert "artifacts" in data["negative"] and "low quality" in data["negative"]
    assert len(data["stages"]) == 2
    assert data["settings"]["seed"] == ["123", "456"]
    assert len(data["models"]) == 2


def test_zeroed_conditioning_has_no_negative_text(graph):
    graph["zero"] = {
        "class_type": "ConditioningZeroOut",
        "inputs": {"conditioning": ["27", 0]},
    }
    graph["61"]["inputs"]["negative"] = ["zero", 0]
    data = extract({"prompt": graph})
    assert data["positive"] == graph["27"]["inputs"]["text"]
    assert data["negative"] == ""
    assert data["negative_status"]["state"] == "zeroed"
    assert data["negative_status"]["branches"][0]["sources"] == [
        {"node_id": "zero", "class_type": "ConditioningZeroOut", "state": "zeroed"}
    ]
    assert (
        next(p for p in data["prompts"] if p["node_id"] == "27")["role"] == "positive"
    )
    assert data["raw"]["prompt"]["zero"] == graph["zero"]


@pytest.mark.parametrize("text", ["", " \n\t"])
def test_explicit_empty_negative_encoder_is_distinct_from_unavailable(graph, text):
    graph["39"]["inputs"]["text"] = text
    data = extract({"prompt": graph})
    assert data["negative"] == ""
    assert data["negative_status"]["state"] == "empty"
    assert data["negative_status"]["branches"][0]["sources"][0]["input"] == "text"
    assert extract({})["negative_status"]["state"] == "unavailable"


def test_empty_linked_primitive_and_krea_encoder_have_evidence(graph):
    graph["39"]["class_type"] = "Krea2EditGroundedEncode"
    graph["39"]["inputs"] = {"prompt": ["blank", 0]}
    graph["blank"] = {"class_type": "PrimitiveStringMultiline", "inputs": {"value": ""}}
    assert extract({"prompt": graph})["negative_status"]["state"] == "empty"
    graph["blank"]["class_type"] = "CustomRuntimeStringGenerator"
    assert extract({"prompt": graph})["negative_status"]["state"] == "unavailable"


def test_absence_status_requires_all_negative_branches_to_be_known(graph):
    graph["zero"] = {
        "class_type": "ConditioningZeroOut",
        "inputs": {"conditioning": ["27", 0]},
    }
    graph["39"]["inputs"]["text"] = ""
    graph["combine"] = {
        "class_type": "ConditioningCombine",
        "inputs": {"conditioning_1": ["39", 0], "conditioning_2": ["zero", 0]},
    }
    graph["61"]["inputs"]["negative"] = ["combine", 0]
    assert extract({"prompt": graph})["negative_status"]["state"] == "empty_and_zeroed"
    graph["39"]["class_type"] = "VendorTextEncode"
    assert extract({"prompt": graph})["negative_status"]["state"] == "unavailable"
    # A cycle is not evidence of an intentionally absent prompt.
    graph["combine"]["inputs"]["conditioning_1"] = ["combine", 0]
    assert extract({"prompt": graph})["negative_status"]["state"] == "unavailable"


def test_one_missing_stage_does_not_make_empty_negative_claim(graph):
    graph["39"]["inputs"]["text"] = ""
    graph["second"] = copy.deepcopy(graph["61"])
    del graph["second"]["inputs"]["negative"]
    graph["61"]["inputs"]["latent_image"] = ["second", 0]
    assert extract({"prompt": graph})["negative_status"]["state"] == "unavailable"
    del graph["second"]
    del graph["91"]
    assert extract({"prompt": graph})["negative_status"]["state"] == "unavailable"


def test_real_negative_prompt_remains_present(graph):
    data = extract({"prompt": graph})
    assert data["negative_status"]["state"] == "present"
    assert data["negative"] == "blurry, watermark"


def test_partial_encoder_or_combined_input_remains_unavailable(graph):
    graph["39"]["class_type"] = "CLIPTextEncodeFlux"
    graph["39"]["inputs"] = {"clip_l": ""}  # Missing the other text field.
    assert extract({"prompt": graph})["negative_status"]["state"] == "unavailable"
    graph["39"]["inputs"]["t5xxl"] = ""
    assert extract({"prompt": graph})["negative_status"]["state"] == "empty"
    graph["combine"] = {
        "class_type": "ConditioningCombine",
        "inputs": {"conditioning_1": ["39", 0]},
    }
    graph["61"]["inputs"]["negative"] = ["combine", 0]
    assert extract({"prompt": graph})["negative_status"]["state"] == "unavailable"


def test_same_text_really_connected_to_both_roles_is_retained(graph):
    graph["61"]["inputs"]["negative"] = ["27", 0]
    data = extract({"prompt": graph})
    assert data["positive"] == data["negative"] == graph["27"]["inputs"]["text"]
    assert next(p for p in data["prompts"] if p["node_id"] == "27")["role"] == "both"


@pytest.mark.parametrize(
    "class_type",
    [
        "LTXDirectorGuide",
        "LTXDirectorCropGuides",
        "LTXVConditioning",
        "ControlNetApplyAdvanced",
    ],
)
@pytest.mark.parametrize("swapped", [False, True])
def test_paired_conditioning_outputs_preserve_actual_port_connections(
    graph, class_type, swapped
):
    original = copy.deepcopy(graph["61"]["inputs"])
    graph["pair"] = {
        "class_type": class_type,
        "inputs": {
            "positive": original["positive"],
            "negative": original["negative"],
            # Ancillary model/latent/guide data must not import their prompt branches.
            "guide_data": ["999", 0],
            "motion_guide_data": ["999", 0],
            "latent": ["61", 0],
            "model": ["11", 0],
        },
    }
    graph["61"]["inputs"].update(
        positive=["pair", int(swapped)], negative=["pair", int(not swapped)]
    )
    data = extract({"prompt": graph})
    expected_positive, expected_negative = (
        graph[original[role][0]]["inputs"]["text"] for role in ("positive", "negative")
    )
    assert data["positive"] == (expected_negative if swapped else expected_positive)
    assert data["negative"] == (expected_positive if swapped else expected_negative)
    assert "SECRET" not in data["negative"]


def test_unknown_paired_node_uses_matching_workflow_port_schema(graph):
    graph["pair"] = {
        "class_type": "VendorEncodePair",
        "inputs": {
            "positive_prompt": "sunlit forest",
            "negative_prompt": "blur, artifacts",
        },
    }
    graph["61"]["inputs"].update(positive=["pair", 1], negative=["pair", 0])
    workflow = {
        "nodes": [
            {
                "id": "pair",
                "type": "VendorEncodePair",
                "outputs": [
                    {"name": "negative", "type": "CONDITIONING"},
                    {"name": "positive", "type": "CONDITIONING"},
                ],
            }
        ]
    }
    data = extract({"prompt": graph, "workflow": workflow})
    assert data["positive"] == "sunlit forest"
    assert data["negative"] == "blur, artifacts"
    # A schema belonging to another type must not authorize guessed routing.
    workflow["nodes"][0]["type"] = "AnotherNode"
    data = extract({"prompt": graph, "workflow": workflow})
    assert data["positive"] == data["negative"] == ""
    assert any("routing" in w for w in data["warnings"])


def test_structured_metadata_is_not_fuzzy_prompt_text(graph):
    graph["vendor"] = {
        "class_type": "VendorConditioning",
        "inputs": {
            "conditioning": ["27", 0],
            "timeline_data": json.dumps(
                {
                    "segments": [
                        {"prompt": "unrelated shot text", "imageFile": "reference.png"}
                    ],
                    "settings": "several other words to pass the old prose heuristic",
                }
            ),
        },
    }
    graph["61"]["inputs"]["positive"] = ["vendor", 0]
    data = extract({"prompt": graph})
    assert data["positive"] == graph["27"]["inputs"]["text"]
    assert "timeline_data" not in {p["input"] for p in data["prompts"]}
    # JSON deliberately supplied as an encoder's prompt remains a valid prompt.
    text = '{"scene": "a glass cabin in an alpine forest"}'
    graph["27"]["inputs"]["text"] = text
    assert extract({"prompt": graph})["positive"] == text


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"prompt": "{bad json"},
        {
            "workflow": {
                "nodes": [{"id": 1, "widgets_values": ["not necessarily a prompt"]}]
            }
        },
    ],
)
def test_missing_or_malformed_does_not_invent(raw):
    data = extract(raw)
    assert data["positive"] == data["negative"] == ""
    assert data["settings"] == {}
    assert data["warnings"]
    assert data["raw"] == raw


def test_cycle_and_malicious_metadata(graph):
    graph["11"]["inputs"]["cycle"] = ["91", 0]
    graph["27"]["inputs"]["text"] = '<script>alert("x")</script>'
    graph["27"]["_meta"] = ["malformed title"]
    data = extract({"prompt": graph})
    assert data["positive"] == '<script>alert("x")</script>'


def test_multiple_outputs_and_unknown_relevance(graph):
    graph["92"] = {"class_type": "PreviewImage", "inputs": {"images": ["72", 0]}}
    assert extract({"prompt": graph})["confidence"] == "partial"
    del graph["92"], graph["91"]
    data = extract({"prompt": graph})
    assert all(p["used"] is None for p in data["prompts"])


def test_hashes_and_seed_independent_configuration(graph):
    first = extract({"prompt": graph})
    other = copy.deepcopy(graph)
    other["61"]["inputs"]["seed"] = 10
    second = extract({"prompt": other})
    assert first["workflow_hash"] != second["workflow_hash"]
    assert first["configuration_hash"] == second["configuration_hash"]
    other["61"]["inputs"]["steps"] = 100
    assert (
        first["configuration_hash"] != extract({"prompt": other})["configuration_hash"]
    )


def test_png_metadata_roundtrip(tmp_path, graph):
    path = save_image(
        tmp_path / "source.png", graph, workflow={"nodes": [], "links": []}
    )
    with Image.open(path) as image:
        data = extract(read_metadata(image))
    assert data["prompt"] == graph
    assert data["workflow"] == {"nodes": [], "links": []}


@pytest.mark.parametrize("suffix,format", [("jpg", "JPEG"), ("webp", "WEBP")])
def test_exif_metadata(tmp_path, graph, suffix, format):
    exif = Image.Exif()
    exif[37510] = (
        b"ASCII\x00\x00\x00"
        + json.dumps({"prompt": graph, "workflow": {"nodes": []}}).encode()
    )
    path = tmp_path / f"test.{suffix}"
    Image.new("RGB", (40, 30)).save(path, format=format, exif=exif)
    with Image.open(path) as image:
        data = extract(read_metadata(image))
    assert data["prompt"] == graph
    assert data["positive"]


def test_date_without_timezone_is_not_invented():
    assert extract({"creation_time": "2026-10-20T10:00:00"})["generated_at"] is None
    assert (
        extract({"creation_time": "2026-10-20T10:00:00Z"})["generated_at"] is not None
    )


def test_non_standard_json_is_preserved_without_breaking_api():
    raw = {"prompt": '{"node":{"class_type":"KSampler","inputs":{"cfg":NaN}}}'}
    data = extract(raw)
    assert data["prompt"] is None
    assert data["raw"] == raw and data["settings"] == {}
