from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import warnings
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps

from ..metadata import MAX_METADATA, read_metadata

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".avif",
}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".m4v", ".avi"}


@dataclass
class MediaInfo:
    kind: str
    width: int
    height: int
    raw: dict
    duration: float | None = None
    fps: float | None = None
    technical: dict = field(default_factory=dict)


class MediaReader(Protocol):
    id: str
    version: int
    extensions: set[str]

    def read(self, path: Path, thumbnail: Path | None) -> MediaInfo: ...


class ImageReader:
    id, version, extensions = "pillow-image", 1, IMAGE_EXTENSIONS

    def read(self, path, thumbnail):
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                width, height = image.size
                raw = read_metadata(image)
                if thumbnail:
                    image.draft("RGB", (480, 480))
                    preview = ImageOps.exif_transpose(image)
                    preview.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    if preview.mode not in {"RGB", "RGBA"}:
                        preview = preview.convert(
                            "RGBA" if "transparency" in image.info else "RGB"
                        )
                    preview.save(thumbnail, format="WEBP", quality=78, method=3)
        return MediaInfo("image", width, height, raw)


def executable(name):
    value = os.environ.get("GALLERY_" + name.upper()) or shutil.which(name)
    if not value:
        raise ValueError(
            f"{name} is required for video support. Install FFmpeg with ffprobe and restart the gallery."
        )
    return value


def run_media(command, *, timeout=40):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Media processing timed out") from exc
    if result.returncode:
        raise ValueError(
            "Media decoder: " + result.stderr.decode("utf-8", errors="replace")[-600:]
        )
    return result.stdout


def finite(value):
    try:
        number = float(Fraction(str(value)))
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, ZeroDivisionError):
        return None


INPUT_OPTIONS = [
    "-protocol_whitelist",
    "file,pipe",
    "-format_whitelist",
    "mov,matroska,webm,avi",
]


class VideoReader:
    id, version, extensions = "ffmpeg-video", 1, VIDEO_EXTENSIONS

    def read(self, path, thumbnail):
        data = run_media(
            [
                executable("ffprobe"),
                "-v",
                "error",
                *INPUT_OPTIONS,
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
        if len(data) > MAX_METADATA:
            raise ValueError("Video metadata exceeds the 8 MiB limit")
        probe = json.loads(data)
        streams = probe.get("streams", [])
        video = next(
            (
                s
                for s in streams
                if s.get("codec_type") == "video"
                and not s.get("disposition", {}).get("attached_pic")
            ),
            None,
        )
        if not video:
            raise ValueError("No video stream found")
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if width <= 0 or height <= 0 or width * height > 100_000_000:
            raise ValueError(
                "Video dimensions are invalid or exceed the 100 megapixel limit"
            )
        duration = finite(probe.get("format", {}).get("duration")) or finite(
            video.get("duration")
        )
        fps = finite(video.get("avg_frame_rate")) or finite(video.get("r_frame_rate"))
        tags = {}
        for group in [probe.get("format", {}), *streams]:
            for key, value in group.get("tags", {}).items():
                tags.setdefault(key.lower(), value)
        # VideoHelperSuite stores a JSON metadata container in the comment tag.
        for value in list(tags.values()):
            if not isinstance(value, str) or not value.lstrip().startswith("{"):
                continue
            try:
                container = json.loads(value)
                if isinstance(container, dict):
                    for key in ("prompt", "workflow"):
                        if key in container:
                            tags.setdefault(key, container[key])
            except (ValueError, RecursionError):
                pass
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        technical = {
            "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name") if audio else None,
            "has_audio": audio is not None,
            "container": probe.get("format", {}).get("format_name"),
            "frame_count": finite(video.get("nb_frames")),
        }
        if thumbnail:
            seek = min(2.0, (duration or 0) * 0.1)
            command = [
                executable("ffmpeg"),
                "-nostdin",
                "-v",
                "error",
                "-y",
                *INPUT_OPTIONS,
                "-ss",
                str(seek),
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                "scale=480:480:force_original_aspect_ratio=decrease",
                "-c:v",
                "libwebp",
                "-f",
                "webp",
                str(thumbnail),
            ]
            run_media(command)
        return MediaInfo("video", width, height, tags, duration, fps, technical)


READERS: tuple[MediaReader, ...] = (ImageReader(), VideoReader())


def reader_for(path):
    return next(
        (reader for reader in READERS if path.suffix.lower() in reader.extensions), None
    )


def sidecar_paths(path):
    return list(
        dict.fromkeys(
            [
                path.with_name(path.name + ".json"),
                path.with_suffix(".json"),
                path.with_suffix(".workflow.json"),
                path.with_suffix(".timeline.json"),
            ]
        )
    )


def sidecar_signature(path):
    identity = []
    for candidate in sidecar_paths(path):
        if candidate.is_file() and not candidate.is_symlink():
            stat = candidate.stat()
            identity.append((candidate.name, stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()
