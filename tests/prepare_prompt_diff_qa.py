"""Two synthetic long prompts with a difference beyond the gallery's preview."""
import copy
import json
import os
import time
from pathlib import Path

from PIL import Image, PngImagePlugin

workspace = Path(__file__).resolve().parent.parent
folder = workspace / ".qa" / "prompt-diff-source"
folder.mkdir(parents=True, exist_ok=True)
graph = json.loads((workspace / "tests" / "fixtures" / "basic.json").read_text())
prefix = "Prompt comparison fixture. " + (
    "A small wooden cabin sits beside a mountain lake, with pine trees, soft clouds, "
    "and natural textures photographed on medium format film. "
) * 13
prefix += '\nLiteral metadata text: <script>window.promptDiffExecuted=true</script>\n'
for index, color in enumerate(["red", "blue"]):
    current = copy.deepcopy(graph)
    current["27"]["inputs"]["text"] = prefix + f"The hiker wears a {color} scarf."
    current["61"]["inputs"]["seed"] = 100 + index
    png = PngImagePlugin.PngInfo()
    png.add_text("prompt", json.dumps(current))
    path = folder / f"compare_{'a' if index == 0 else 'b'}.png"
    Image.new("RGB", (200, 160), color).save(path, pnginfo=png)
    stamp = time.time() - 10 - index
    os.utime(path, (stamp, stamp))
print(folder)
