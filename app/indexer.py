from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import threading
import time
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import EXTENSIONS, Settings, inside, path_key
from .database import Database
from .media import READERS, reader_for, sidecar_signature
from .metadata import PARSER_VERSION
from .parsers import parse_metadata
from .parsers.pipeline import PARSERS, SCHEMA_VERSION

log = logging.getLogger(__name__)


class Events(FileSystemEventHandler):
    def __init__(self, indexer):
        self.indexer = indexer

    def on_any_event(self, event):
        if event.event_type not in {
            "created",
            "modified",
            "deleted",
            "moved",
            "closed",
        }:
            return
        if event.is_directory:
            if event.event_type in {"created", "deleted", "moved"} and (
                self.indexer.settings.allowed(Path(event.src_path))
                or (
                    getattr(event, "dest_path", None)
                    and self.indexer.settings.allowed(Path(event.dest_path))
                )
            ):
                self.indexer.directory_change()
            return
        self.indexer.enqueue(Path(event.src_path))
        if getattr(event, "dest_path", None):
            self.indexer.enqueue(Path(event.dest_path))


class Indexer:
    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db
        self.lock = threading.RLock()
        self.commands = queue.Queue()
        self.pending: dict[str, tuple[Path, float, int]] = {}
        self.stop = threading.Event()
        self.cancel = threading.Event()
        self.observer = None
        self.thread = None
        self.revision = 0
        self.dir_due = 0.0
        self.reconcile_due = time.monotonic() + 300
        self.status = {
            "running": False,
            "scanned": 0,
            "indexed": 0,
            "unchanged": 0,
            "removed": 0,
            "errors": [],
            "error_count": 0,
            "current": "",
            "cancelled": False,
            "watching": False,
            "started_at": None,
            "finished_at": None,
        }

    def snapshot(self):
        with self.lock:
            return {
                **self.status,
                "errors": list(self.status["errors"]),
                "pending": len(self.pending),
                "revision": self.revision,
            }

    def start(self):
        self.thread = threading.Thread(
            target=self._run, name="gallery-indexer", daemon=True
        )
        self.thread.start()
        self.request_scan(rewatch=True)

    def close(self):
        self.stop.set()
        self.cancel.set()
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=10)
        if self.thread:
            self.thread.join(timeout=15)

    def request_scan(self, rebuild=False, rewatch=False):
        self.cancel.set()
        self.commands.put(("scan", rebuild, rewatch))

    def cancel_scan(self):
        self.cancel.set()
        # Drop queued scans too, so cancel means cancel even just after requesting a scan.
        while True:
            try:
                self.commands.get_nowait()
            except queue.Empty:
                break

    def enqueue(self, path: Path, attempt=0, delay=1.5):
        if path.suffix.lower() == ".json":
            base = path.with_suffix("")
            bases = [base]
            if base.suffix.lower() in {".timeline", ".workflow"}:
                bases.append(base.with_suffix(""))
            for candidate in dict.fromkeys(
                [
                    base,
                    *(b.with_name(b.name + ext) for b in bases for ext in EXTENSIONS),
                ]
            ):
                if candidate.suffix.lower() in EXTENSIONS and candidate.is_file():
                    self.enqueue(candidate, attempt, delay)
            return
        if path.suffix.lower() not in EXTENSIONS or not self.settings.allowed(path):
            return
        with self.lock:
            if len(self.pending) > 50000:
                self.dir_due = time.monotonic() + 3
                return
            self.pending[path_key(path)] = (path, time.monotonic() + delay, attempt)

    def directory_change(self):
        with self.lock:
            self.dir_due = time.monotonic() + 2

    def _error(self, path, exc):
        message = f"{path}: {exc}"
        log.warning(message)
        with self.lock:
            self.status["error_count"] += 1
            self.status["errors"] = (self.status["errors"] + [message])[-30:]

    def _watch(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=10)
        observer = Observer()
        watched = 0
        for root in list(self.settings.roots):
            try:
                observer.schedule(Events(self), str(root), recursive=True)
                watched += 1
            except OSError as exc:
                self._error(root, exc)
        try:
            observer.start()
            self.observer = observer
            self.status["watching"] = watched > 0
        except OSError as exc:
            self._error("File watcher", exc)
            self.status["watching"] = False

    def _run(self):
        while not self.stop.is_set():
            try:
                _, rebuild, rewatch = self.commands.get(timeout=0.2)
                self.cancel.clear()
                self._scan(rebuild, rewatch)
            except queue.Empty:
                pass
            except Exception as exc:
                self._error("Scan", exc)
                self.status["running"] = False
            if self.stop.is_set():
                break
            with self.lock:
                now = time.monotonic()
                due = [
                    (key, item) for key, item in self.pending.items() if item[1] <= now
                ][:100]
                for key, _ in due:
                    self.pending.pop(key, None)
                dir_due = self.dir_due and self.dir_due <= now
                if dir_due:
                    self.dir_due = 0
            for _, (path, _, attempt) in due:
                try:
                    root = next(
                        (r for r in self.settings.roots if inside(path, r)), None
                    )
                    if root and self.settings.allowed(path):
                        if path.exists():
                            self._index(path, root, None)
                        else:
                            self.db.remove(path_key(path))
                            self.revision += 1
                except (
                    OSError,
                    ValueError,
                    UnidentifiedImageError,
                    Image.DecompressionBombError,
                    Image.DecompressionBombWarning,
                ) as exc:
                    if attempt < 5:
                        self.enqueue(path, attempt + 1, min(30, 2 ** (attempt + 1)))
                    else:
                        self._error(path, exc)
                except Exception as exc:
                    self._error(path, exc)
            if dir_due:
                self.request_scan(rewatch=not self.status["watching"])
            elif time.monotonic() >= self.reconcile_due and self.settings.roots:
                # Reconcile dropped events, and retry unavailable drives/watchers.
                self.request_scan(rewatch=True)
                self.reconcile_due = time.monotonic() + (
                    300 if self.status["watching"] else 30
                )

    def _scan(self, rebuild=False, rewatch=False):
        self.status.update(
            running=True,
            scanned=0,
            indexed=0,
            unchanged=0,
            removed=0,
            errors=[],
            error_count=0,
            current="",
            cancelled=False,
            started_at=time.time(),
            finished_at=None,
        )
        if rewatch:
            self._watch()
        roots = list(self.settings.roots)
        self.db.restrict_roots([path_key(root) for root in roots])
        if rebuild:
            self.db.rebuild()
            self.revision += 1
        try:
            for root in roots:
                token, complete = uuid.uuid4().hex, True
                stack = [root]
                while stack and not self.cancel.is_set() and not self.stop.is_set():
                    folder = stack.pop()
                    self.status["current"] = str(folder)
                    try:
                        with os.scandir(folder) as entries:
                            for entry in entries:
                                if self.cancel.is_set() or self.stop.is_set():
                                    break
                                path = Path(entry.path)
                                if entry.is_symlink() or not self.settings.allowed(
                                    path
                                ):
                                    continue
                                if entry.is_dir(follow_symlinks=False):
                                    # Windows junctions are also intentionally not traversed.
                                    if not (
                                        hasattr(path, "is_junction")
                                        and path.is_junction()
                                    ):
                                        stack.append(path)
                                elif (
                                    entry.is_file(follow_symlinks=False)
                                    and path.suffix.lower() in EXTENSIONS
                                ):
                                    self.status["scanned"] += 1
                                    self.db.seen(path_key(path), token)
                                    try:
                                        changed = self._index(path, root, token)
                                        self.status[
                                            "indexed" if changed else "unchanged"
                                        ] += 1
                                    except (
                                        OSError,
                                        ValueError,
                                        UnidentifiedImageError,
                                        Image.DecompressionBombError,
                                        Image.DecompressionBombWarning,
                                    ) as exc:
                                        self._error(path, exc)
                                        self.enqueue(path)
                                    except Exception as exc:
                                        self._error(path, exc)
                    except OSError as exc:
                        complete = False
                        self._error(folder, exc)
                if complete and not self.cancel.is_set() and not self.stop.is_set():
                    removed = self.db.prune(path_key(root), token)
                    self.status["removed"] += removed
                    if removed:
                        self.revision += 1
        finally:
            self.status.update(
                running=False,
                current="",
                cancelled=self.cancel.is_set(),
                finished_at=time.time(),
            )

    def _index(self, path: Path, root: Path, token: str | None):
        if not self.settings.allowed(path):
            return False
        stat = path.stat()
        key = path_key(path)
        existing = self.db.fingerprint(key)
        dependencies = hashlib.sha256(
            json.dumps(
                [
                    sidecar_signature(path),
                    SCHEMA_VERSION,
                    [(r.id, r.version) for r in READERS],
                    [(p.id, p.version) for p in PARSERS],
                ]
            ).encode()
        ).hexdigest()
        reuse_thumbnail = bool(
            existing
            and existing["mtime_ns"] == stat.st_mtime_ns
            and existing["size"] == stat.st_size
            and (self.settings.thumbnails / existing["thumbnail"]).exists()
        )
        if (
            reuse_thumbnail
            and existing["version"] == PARSER_VERSION
            and existing.get("metadata_fingerprint") == dependencies
        ):
            return False
        if stat.st_size == 0 or time.time_ns() - stat.st_mtime_ns < 750_000_000:
            raise OSError("Media file is still being written; retrying")
        image_id = hashlib.sha256(key.encode()).hexdigest()[:32]
        thumb = (
            existing["thumbnail"]
            if reuse_thumbnail
            else f"{image_id}-{stat.st_mtime_ns}-{stat.st_size}.webp"
        )
        temp = self.settings.thumbnails / (thumb + ".tmp")
        try:
            reader = reader_for(path)
            if reader is None:
                return False
            info = reader.read(path, None if reuse_thumbnail else temp)
            width, height = info.width, info.height
            metadata = parse_metadata(path, info, self.settings.allowed)
            after = path.stat()
            if (after.st_mtime_ns, after.st_size) != (stat.st_mtime_ns, stat.st_size):
                raise OSError("Image changed while indexing; retrying")
            current_dependencies = hashlib.sha256(
                json.dumps(
                    [
                        sidecar_signature(path),
                        SCHEMA_VERSION,
                        [(r.id, r.version) for r in READERS],
                        [(p.id, p.version) for p in PARSERS],
                    ]
                ).encode()
            ).hexdigest()
            if current_dependencies != dependencies:
                raise OSError("Sidecar changed while indexing; retrying")
            if not reuse_thumbnail:
                temp.replace(self.settings.thumbnails / thumb)
            row = {
                "id": image_id,
                "path_key": key,
                "path": str(path.resolve()),
                "root": path_key(root),
                "folder": path_key(path.parent),
                "filename": path.name,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "created_at": getattr(stat, "st_birthtime", stat.st_ctime),
                "modified_at": stat.st_mtime,
                "sort_date": metadata["generated_at"] or stat.st_mtime,
                "generated_at": metadata["generated_at"],
                "width": width,
                "height": height,
                "model": metadata["models"][0] if metadata["models"] else None,
                "models": json.dumps(metadata["models"]),
                "loras": json.dumps(
                    list(dict.fromkeys(l["name"] for l in metadata["loras"]))
                ),
                "seeds": json.dumps(
                    [str(s) for s in metadata["settings"].get("seed", [])]
                ),
                "positive": metadata["positive"],
                "negative": metadata["negative"],
                "metadata": json.dumps(metadata, ensure_ascii=False),
                "confidence": metadata["confidence"],
                "workflow_hash": metadata["workflow_hash"],
                "configuration_hash": metadata["configuration_hash"],
                "thumbnail": thumb,
                "version": PARSER_VERSION,
                "last_seen": token,
                "media_kind": info.kind,
                "duration": info.duration,
                "fps": info.fps,
                "technical": json.dumps(info.technical),
                "metadata_fingerprint": dependencies,
            }
            self.db.upsert(row)
            if existing and existing["thumbnail"] != thumb:
                (self.settings.thumbnails / existing["thumbnail"]).unlink(
                    missing_ok=True
                )
            self.revision += 1
            return True
        finally:
            temp.unlink(missing_ok=True)
