import json
import os
import shutil
import subprocess
import time


def director_graph(
    global_text="A consistent woodland setting.",
    first="A fox walks past a red cabin.",
    second="The fox looks toward a blue lake.",
):
    timeline = {
        "global_prompt": global_text,
        "mainTrackEnabled": True,
        "segments": [
            {"id": "first", "type": "text", "start": 0, "length": 12, "prompt": first},
            {
                "id": "second",
                "type": "text",
                "start": 12,
                "length": 24,
                "prompt": second,
            },
        ],
    }
    return {
        "checkpoint": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "ltx-video.safetensors"},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blur, artifacts", "clip": ["checkpoint", 1]},
        },
        "director": {
            "class_type": "LTXDirector",
            "inputs": {
                "model": ["checkpoint", 0],
                "clip": ["checkpoint", 1],
                "timeline_data": json.dumps(timeline),
                "local_prompts": first + "|" + second,
                "segment_lengths": "12,24",
                "frame_rate": 12,
                "start_frame": 0,
                "duration_frames": 36,
            },
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "positive": ["director", 1],
                "negative": ["negative", 0],
                "model": ["director", 0],
                "seed": 42,
                "steps": 8,
            },
        },
        "decode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["sampler", 0], "vae": ["checkpoint", 2]},
        },
        "create": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["decode", 0], "fps": 12},
        },
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["create", 0]}},
    }


def save_video(path, graph=None, *, codec="libx264"):
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        shutil.which("ffmpeg"),
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=12",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000",
        "-t",
        "3",
        "-c:v",
        codec,
        "-threads",
        "2",
        "-c:a",
        "aac",
    ]
    if graph is not None:
        command += [
            "-metadata",
            "prompt=" + json.dumps(graph),
            "-metadata",
            "workflow=" + json.dumps({"nodes": [], "links": []}),
        ]
    if path.suffix == ".mp4":
        command += ["-movflags", "use_metadata_tags+faststart"]
    subprocess.run(
        [*command, str(path)],
        check=True,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    stamp = time.time() - 3
    os.utime(path, (stamp, stamp))
    return path
