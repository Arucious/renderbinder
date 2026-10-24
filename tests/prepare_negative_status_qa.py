"""Create synthetic negative-conditioning fixtures outside the personal library."""

import copy
import json
from pathlib import Path

from PIL import Image, PngImagePlugin

workspace = Path(__file__).resolve().parent.parent
source = workspace / ".qa" / "negative-status-source"
source.mkdir(parents=True, exist_ok=True)
base = json.loads((workspace / "tests/fixtures/basic.json").read_text(encoding="utf-8"))
for state in ("present", "empty", "zeroed", "empty_and_zeroed", "unavailable"):
    graph = copy.deepcopy(base)
    if state in {"empty", "empty_and_zeroed"}:
        graph["39"]["inputs"]["text"] = ""
    if state in {"zeroed", "empty_and_zeroed"}:
        graph["zero"] = {
            "class_type": "ConditioningZeroOut",
            "inputs": {"conditioning": ["27", 0]},
        }
        graph["61"]["inputs"]["negative"] = ["zero", 0]
    if state == "empty_and_zeroed":
        graph["combine"] = {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["39", 0], "conditioning_2": ["zero", 0]},
        }
        graph["61"]["inputs"]["negative"] = ["combine", 0]
    png = PngImagePlugin.PngInfo()
    if state != "unavailable":
        png.add_text("prompt", json.dumps(graph))
    Image.new("RGB", (128, 96), color="slategray").save(
        source / f"negative_{state}.png", pnginfo=png
    )
print(source)
