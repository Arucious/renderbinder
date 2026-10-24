"""Generate synthetic test images in .qa/sources; never scans personal directories."""

import copy
import json
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw, PngImagePlugin

workspace = Path(__file__).resolve().parent.parent
source = workspace / ".qa" / "sources"
source.mkdir(parents=True, exist_ok=True)
graph = json.loads((workspace / "tests" / "fixtures" / "basic.json").read_text())
names = [
    "Alpine stillness",
    "Amber horizon",
    "Quiet geometry",
    "Forest after rain",
    "Glasshouse at dusk",
    "Soft reflections",
    "Desert observatory",
    "Evening passage",
    "Mountain archive",
    "Paper cities",
    "Lunar garden",
    "Ocean studies",
]
for n, name in enumerate(names):
    folder = source / ("landscapes" if n < 8 else "experiments")
    folder.mkdir(exist_ok=True)
    image = Image.new("RGB", (800, 640))
    draw = ImageDraw.Draw(image)
    colors = [(62, 84, 84), (164, 110, 70), (102, 89, 106), (50, 74, 61)]
    r, g, b = colors[n % len(colors)]
    for y in range(640):
        factor = 0.4 + y / 900
        draw.line(
            (0, y, 800, y), fill=(int(r * factor), int(g * factor), int(b * factor))
        )
    draw.ellipse((460, 65, 560, 165), fill=(211, 181, 136))
    draw.polygon(
        [
            (0, 640),
            (0, 470),
            (200, 210 + n * 9),
            (420, 490),
            (610, 320),
            (800, 460),
            (800, 640),
        ],
        fill=(29 + n, 42 + n, 39 + n),
    )
    draw.polygon([(170, 490), (315, 370), (460, 490)], fill=(203, 171, 129))
    draw.rectangle((195, 490, 430, 610), fill=(171, 142, 108))
    draw.rectangle((225, 485, 395, 610), fill=(74, 94, 92))
    draw.line((310, 485, 310, 610), fill=(167, 143, 113), width=5)
    metadata = PngImagePlugin.PngInfo()
    current = copy.deepcopy(graph)
    current["27"]["inputs"]["text"] = (
        f"{name.lower()}, cinematic lighting, alpine forest, medium format photography, soft atmosphere"
    )
    current["61"]["inputs"]["seed"] += n
    current["61"]["inputs"]["steps"] += n % 3
    if n > 7:
        current["11"]["inputs"]["ckpt_name"] = "flux-dev.safetensors"
    metadata.add_text("prompt", json.dumps(current))
    metadata.add_text(
        "workflow",
        json.dumps(
            {
                "nodes": [{"id": 11, "type": "CheckpointLoaderSimple"}],
                "links": [],
                "test_fixture": True,
            }
        ),
    )
    path = folder / (name.lower().replace(" ", "_") + f"_{n + 1:05}.png")
    image.save(path, pnginfo=metadata)
    stamp = time.time() - 180 - n * 3600
    os.utime(path, (stamp, stamp))
print(source)
