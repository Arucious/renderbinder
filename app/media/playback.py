"""Native playback where possible; one bounded CPU proxy job at a time otherwise."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

from .readers import INPUT_OPTIONS, executable


class Playback:
    def __init__(self, settings):
        self.settings = settings
        self.folder = settings.data_dir / "previews"
        self.folder.mkdir(exist_ok=True)
        self.jobs = {}
        self.queue = queue.Queue(maxsize=8)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.process = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="video-playback"
        )
        self.thread.start()

    def close(self):
        self.stop.set()
        with self.lock:
            if self.process:
                self.process.kill()
        if self.thread:
            self.thread.join(timeout=3)

    def target(self, item, compatible=False):
        path = Path(item["path"])
        stat = path.stat()
        if (stat.st_mtime_ns, stat.st_size) != (item["mtime_ns"], item["size"]):
            raise ValueError(
                "The video changed. Wait for indexing or rescan the library."
            )
        technical = json.loads(item["technical"])
        audio = technical.get("audio_codec")
        native = (
            path.suffix.lower() in {".mp4", ".m4v"}
            and technical.get("video_codec") == "h264"
            and audio in {None, "aac", "mp3"}
        ) or (
            path.suffix.lower() == ".webm"
            and technical.get("video_codec") in {"vp8", "vp9", "av1"}
            and audio in {None, "opus", "vorbis"}
        )
        native = native and not compatible
        key = hashlib.sha256(
            f"proxy-v1:{item['id']}:{stat.st_mtime_ns}:{stat.st_size}".encode()
        ).hexdigest()
        return key, path if native else self.folder / (key + ".mp4"), native

    def prepare(self, item, compatible=False, retry=False):
        key, target, native = self.target(item, compatible)
        if native or target.is_file():
            return {
                "state": "ready",
                "url": f"/api/images/{item['id']}/playback?compatible={str(compatible).lower()}",
                "proxy": not native,
            }
        with self.lock:
            if retry and self.jobs.get(key, {}).get("state") == "error":
                del self.jobs[key]
            if key not in self.jobs:
                if len(self.jobs) > 100:
                    self.jobs = {
                        k: v for k, v in self.jobs.items() if v["state"] == "processing"
                    }
                self.jobs[key] = {"state": "processing", "proxy": True}
                try:
                    self.queue.put_nowait((key, dict(item), target))
                except queue.Full:
                    del self.jobs[key]
                    return {
                        "state": "error",
                        "error": "Playback queue is full. Close this video and try again shortly.",
                    }
            return dict(self.jobs[key])

    def _run(self):
        while not self.stop.is_set():
            try:
                key, item, target = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            temp = target.with_suffix(".tmp")
            try:
                path = Path(item["path"])
                if not self.settings.allowed(path):
                    raise ValueError("Video source is no longer configured")
                self.target(item)
                command = [
                    executable("ffmpeg"),
                    "-nostdin",
                    "-v",
                    "error",
                    "-y",
                    *INPUT_OPTIONS,
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-vf",
                    f"scale=1280:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,fps={min(30, item.get('fps') or 30)}",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-threads",
                    "2",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "128k",
                    "-movflags",
                    "+faststart",
                    "-f",
                    "mp4",
                    str(temp),
                ]
                with self.lock:
                    if self.stop.is_set():
                        break
                    self.process = subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW
                        if os.name == "nt"
                        else 0,
                    )
                    process = self.process
                try:
                    _, error = process.communicate(timeout=600)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise ValueError("Playback conversion exceeded ten minutes")
                if process.returncode:
                    raise ValueError(
                        "Playback conversion failed: "
                        + error.decode("utf-8", errors="replace")[-400:]
                    )
                if not self.settings.allowed(path):
                    raise ValueError("Video source is no longer configured")
                self.target(item)
                temp.replace(target)
                with self.lock:
                    self.jobs.pop(key, None)
            except Exception as exc:
                with self.lock:
                    self.jobs[key] = {"state": "error", "error": str(exc)[:600]}
            finally:
                with self.lock:
                    self.process = None
                temp.unlink(missing_ok=True)
