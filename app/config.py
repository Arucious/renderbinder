from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .media import READERS

EXTENSIONS = set().union(*(reader.extensions for reader in READERS))
PROJECT = Path(__file__).resolve().parent.parent


def path_key(path: Path | str) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


class Settings:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = (
            data_dir or Path(os.environ.get("GALLERY_DATA_DIR", PROJECT / ".gallery"))
        ).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails = self.data_dir / "thumbnails"
        self.thumbnails.mkdir(exist_ok=True)
        self.file = self.data_dir / "config.json"
        self.lock = threading.RLock()
        self.roots: list[Path] = []
        self.comfy_url = "http://127.0.0.1:8188"
        if self.file.exists():
            data = json.loads(self.file.read_text(encoding="utf-8"))
            self.roots = [Path(p).resolve() for p in data.get("roots", [])]
            self.comfy_url = data.get("comfy_url", self.comfy_url)

    def allowed(self, path: Path) -> bool:
        return not inside(path, self.data_dir) and any(
            inside(path, root) for root in self.roots
        )

    def public(self) -> dict:
        return {
            "roots": [str(p) for p in self.roots],
            "comfy_url": self.comfy_url,
            "data_dir": str(self.data_dir),
            "extensions": sorted(EXTENSIONS),
        }

    def update(self, roots: list[str], comfy_url: str) -> None:
        from urllib.parse import urlparse

        url = urlparse(comfy_url)
        if (
            url.scheme != "http"
            or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "ComfyUI URL must be a local HTTP origin, for example http://127.0.0.1:8188"
            )
        try:
            _ = url.port
        except ValueError as exc:
            raise ValueError("Invalid ComfyUI port") from exc
        resolved: list[Path] = []
        for value in roots:
            p = Path(value).expanduser()
            if not p.is_absolute() or not p.is_dir():
                raise ValueError(
                    f"Directory does not exist or is not an absolute path: {value}"
                )
            p = p.resolve()
            if inside(p, self.data_dir):
                raise ValueError(
                    "The application data folder cannot be an image source"
                )
            if not any(inside(p, other) for other in resolved):
                resolved = [other for other in resolved if not inside(other, p)] + [p]
        with self.lock:
            payload = {
                "roots": [str(p) for p in resolved],
                "comfy_url": comfy_url.rstrip("/"),
            }
            temp = self.file.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temp.replace(self.file)
            self.roots, self.comfy_url = resolved, payload["comfy_url"]
