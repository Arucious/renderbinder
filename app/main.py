from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import PROJECT, Settings, path_key
from .database import Database
from .indexer import Indexer
from .media import READERS
from .media.playback import Playback
from .metadata import PARSER_VERSION
from .parsers.pipeline import PARSERS, SCHEMA_VERSION
from .semantic import SemanticIndex


class SettingsInput(BaseModel):
    roots: list[str] = Field(max_length=32)
    comfy_url: str = Field(default="http://127.0.0.1:8188", max_length=200)


class AnnotationInput(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=500)
    favorite: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=100)


class CollectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CollectionItems(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=500)
    remove: bool = False


class QueueInput(BaseModel):
    confirm_generation: Literal[True]


class SemanticInput(BaseModel):
    enabled: bool = False
    model: Literal["bge-small", "embeddinggemma2", "custom"] = "bge-small"
    custom_model: str = Field(default="", max_length=1000)
    revision: str = Field(default="main", max_length=100)
    backend: Literal["torch"] = "torch"
    prefix: str = Field(default="", max_length=500)
    max_tokens: int = Field(default=512, ge=128, le=8192)
    threads: int = Field(default=4, ge=1, le=8)


def create_app(data_dir: Path | None = None, *, watch: bool = True):
    settings = Settings(data_dir)
    db = Database(settings.data_dir)
    indexer = Indexer(settings, db)
    semantic = SemanticIndex(settings, db)
    playback = Playback(settings)

    @asynccontextmanager
    async def lifespan(app):
        semantic.start()
        playback.start()
        if watch:
            indexer.start()
        yield
        if watch:
            indexer.close()
        semantic.close()
        playback.close()

    app = FastAPI(title="RenderBinder", version="1.0.0", lifespan=lifespan)
    app.state.settings, app.state.db, app.state.indexer = settings, db, indexer
    app.state.semantic = semantic
    app.state.playback = playback
    allowed_hosts = os.environ.get(
        "GALLERY_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]"
    ).split(",")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse(
                {"detail": "Cross-origin requests are not allowed"}, status_code=403
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; worker-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api/") and not request.url.path.endswith(
            ("/thumbnail", "/original")
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    def image_or_404(image_id: str, *, file_only: bool = False):
        item = db.file(image_id) if file_only else db.detail(image_id)
        if not item or not settings.allowed(Path(item["path"])):
            raise HTTPException(
                404, "Image not found in the configured source directories"
            )
        return item

    @app.get("/api/settings")
    def get_settings():
        return settings.public()

    @app.get("/api/capabilities")
    def capabilities():
        import shutil

        return {
            "metadata_schema": SCHEMA_VERSION,
            "readers": [
                {"id": r.id, "version": r.version, "extensions": sorted(r.extensions)}
                for r in READERS
            ],
            "parsers": [
                {"id": "comfy-graph", "version": PARSER_VERSION},
                *[{"id": p.id, "version": p.version} for p in PARSERS],
            ],
            "video_available": all(
                os.environ.get("GALLERY_" + name.upper()) or shutil.which(name)
                for name in ("ffmpeg", "ffprobe")
            ),
        }

    @app.put("/api/settings")
    def put_settings(value: SettingsInput):
        try:
            settings.update(value.roots, value.comfy_url)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        indexer.request_scan(rewatch=True)
        indexer.revision += 1
        return settings.public()

    @app.get("/api/status")
    def status():
        return indexer.snapshot()

    @app.get("/api/semantic")
    def semantic_status():
        return semantic.snapshot()

    @app.put("/api/semantic/settings")
    def semantic_settings(value: SemanticInput):
        try:
            return semantic.configure(value.model_dump())
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/semantic/cancel")
    def cancel_semantic():
        return semantic.cancel()

    @app.post("/api/scans")
    def scan(rebuild: bool = False):
        indexer.request_scan(rebuild=rebuild)
        return {"queued": True}

    @app.post("/api/scans/cancel")
    def cancel():
        indexer.cancel_scan()
        return {"cancel_requested": True}

    @app.get("/api/facets")
    def facets():
        return db.facets()

    @app.get("/api/media")
    @app.get("/api/prompts")
    @app.get("/api/images")
    def images(
        request: Request,
        q: str = Query("", max_length=500),
        exact: bool = False,
        root: str = "",
        folder: str = "",
        model: str = "",
        lora: str = "",
        seed: str = Query("", max_length=100),
        tag: str = "",
        favorite: bool = False,
        collection: str = "",
        after: date | None = None,
        before: date | None = None,
        sort: Literal["date", "filename", "resolution", "model"] = "date",
        direction: Literal["asc", "desc"] = "desc",
        group: Literal["", "date", "model", "workflow"] = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(60, ge=1, le=120),
        workflow: str = "",
        configuration: str = "",
        prompt: str = Query("", max_length=64, pattern=r"^(?:[0-9a-f]{64})?$"),
        unique_prompts: bool = False,
        media_kind: str = Query("", max_length=40, pattern=r"^(?:[a-z][a-z0-9_-]*)?$"),
        prompt_scope: str = Query(
            "", max_length=40, pattern=r"^(?:[a-z][a-z0-9_-]*)?$"
        ),
    ):
        # Date filters use the local calendar, matching the displayed dates; 'before' includes that day.
        after_ts = datetime.combine(after, dt_time.min).timestamp() if after else None
        before_ts = (
            datetime.combine(before + timedelta(days=1), dt_time.min).timestamp()
            if before
            else None
        )
        return db.images(
            q=q,
            exact=exact,
            root=path_key(root) if root else "",
            folder=path_key(folder) if folder else "",
            model=model,
            lora=lora,
            seed=seed,
            tag=tag,
            favorite=favorite,
            collection=collection,
            after=after_ts,
            before=before_ts,
            sort=sort,
            direction=direction,
            group=group,
            offset=offset,
            limit=limit,
            workflow=workflow,
            configuration=configuration,
            prompt=prompt,
            unique_prompts=unique_prompts or request.url.path == "/api/prompts",
            media_kind=media_kind,
            prompt_scope=prompt_scope,
        )

    @app.get("/api/media/{image_id}")
    @app.get("/api/images/{image_id}")
    def detail(image_id: str):
        return image_or_404(image_id)

    @app.get("/api/images/{image_id}/prompt")
    def prompt_text(image_id: str):
        item = db.prompt_text(image_id)
        if not item or not settings.allowed(Path(item["path"])):
            raise HTTPException(
                404, "Prompt not found in the configured source directories"
            )
        return {key: item[key] for key in ("id", "positive_hash", "positive")}

    @app.get("/api/images/{image_id}/similar-prompts")
    def similar_prompts(
        image_id: str,
        limit: int = Query(12, ge=1, le=30),
        minimum: float = Query(0.45, ge=0, le=1),
        mode: Literal["hybrid", "semantic", "text"] = "hybrid",
    ):
        image_or_404(image_id, file_only=True)
        source = db.prompts.text(image_id=image_id)
        scores = (
            semantic.similarities(source["text_hash"])
            if mode != "text" and source
            else {}
        )
        result = db.similar_prompts(
            image_id,
            [path_key(root) for root in settings.roots],
            limit=limit,
            minimum=minimum,
            semantic_scores=scores,
            mode=mode,
        )
        if result is None:
            raise HTTPException(
                404, "Prompt not found in the configured source directories"
            )
        return {**result, "semantic": semantic.snapshot()}

    def prompt_or_404(prompt_id):
        source = db.prompts.text(prompt_id)
        if not source or not settings.allowed(Path(source["path"])):
            raise HTTPException(
                404, "Prompt not found in the configured source directories"
            )
        return source

    @app.get("/api/prompts/{prompt_id}")
    def prompt_document(prompt_id: str):
        source = prompt_or_404(prompt_id)
        return {
            key: source[key]
            for key in (
                "id",
                "prompt_id",
                "positive_hash",
                "text_hash",
                "positive",
                "scope",
                "label",
                "start",
                "end",
            )
        }

    @app.get("/api/prompts/{prompt_id}/similar-prompts")
    def similar_document(
        prompt_id: str,
        limit: int = Query(12, ge=1, le=30),
        minimum: float = Query(0.45, ge=0, le=1),
        mode: Literal["hybrid", "semantic", "text"] = "hybrid",
        same_scope: bool = True,
    ):
        source = prompt_or_404(prompt_id)
        scores = semantic.similarities(source["text_hash"]) if mode != "text" else {}
        result = db.prompts.similar(
            source,
            [path_key(root) for root in settings.roots],
            limit=limit,
            minimum=minimum,
            mode=mode,
            semantic_scores=scores,
            same_scope=same_scope,
        )
        if result is None:
            raise HTTPException(404, "Prompt source is no longer configured")
        return {**result, "semantic": semantic.snapshot()}

    @app.post("/api/media/{image_id}/playback")
    @app.post("/api/images/{image_id}/playback")
    def prepare_playback(image_id: str, compatible: bool = False, retry: bool = False):
        item = image_or_404(image_id, file_only=True)
        if item["media_kind"] != "video":
            raise HTTPException(400, "This file is not a video")
        try:
            return playback.prepare(item, compatible, retry)
        except (OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/media/{image_id}/playback")
    @app.get("/api/images/{image_id}/playback")
    def stream_playback(image_id: str, compatible: bool = False):
        item = image_or_404(image_id, file_only=True)
        if item["media_kind"] != "video":
            raise HTTPException(400, "This file is not a video")
        try:
            _, target, native = playback.target(item, compatible)
        except (OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        if not target.is_file():
            raise HTTPException(404, "Video playback is not prepared yet")
        return FileResponse(
            target,
            media_type="video/webm"
            if native and target.suffix.lower() == ".webm"
            else "video/mp4",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/media/{image_id}/thumbnail")
    @app.get("/api/images/{image_id}/thumbnail")
    def thumbnail(image_id: str):
        image = image_or_404(image_id, file_only=True)
        path = settings.thumbnails / image["thumbnail"]
        if not path.is_file():
            raise HTTPException(
                404, "Thumbnail unavailable. Rescan to regenerate the cache."
            )
        return FileResponse(
            path,
            media_type="image/webp",
            headers={"Cache-Control": "private, max-age=60"},
        )

    @app.get("/api/media/{image_id}/original")
    @app.get("/api/images/{image_id}/original")
    def original(image_id: str, download: bool = False):
        image = image_or_404(image_id, file_only=True)
        path = Path(image["path"])
        if not path.is_file() or not settings.allowed(path):
            raise HTTPException(
                404, "Original file no longer exists in an allowed directory"
            )
        return FileResponse(
            path,
            filename=image["filename"] if download else None,
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/media/{image_id}/workflow")
    @app.get("/api/images/{image_id}/workflow")
    def workflow(
        image_id: str, kind: Literal["workflow", "prompt", "raw"] = "workflow"
    ):
        image = image_or_404(image_id)
        value = image["metadata"].get(kind)
        if value is None:
            raise HTTPException(404, f"No readable {kind} JSON is embedded")
        return JSONResponse(
            value,
            headers={
                "Content-Disposition": f'attachment; filename="{image_id}-{kind}.json"'
            },
        )

    @app.post("/api/images/{image_id}/reveal")
    def reveal(image_id: str):
        image = image_or_404(image_id, file_only=True)
        path = Path(image["path"])
        if not path.is_file():
            raise HTTPException(404, "Original file no longer exists")
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
        return {"opened": True}

    @app.patch("/api/annotations")
    def annotations(value: AnnotationInput):
        tags = None
        if value.tags is not None:
            tags = list(dict.fromkeys(t.strip() for t in value.tags if t.strip()))
            if any(len(t) > 80 for t in tags):
                raise HTTPException(400, "Tags must be 80 characters or fewer")
        db.annotate(value.image_ids, value.favorite, tags)
        indexer.revision += 1
        return {"updated": True}

    @app.post("/api/collections")
    def create_collection(value: CollectionInput):
        name = value.name.strip()
        if not name:
            raise HTTPException(400, "Enter a collection name")
        try:
            result = db.create_collection(name)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                409, "A collection with this name already exists"
            ) from exc
        indexer.revision += 1
        return result

    @app.patch("/api/collections/{collection_id}")
    def collection_items(collection_id: str, value: CollectionItems):
        try:
            db.collection_items(collection_id, value.image_ids, value.remove)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        indexer.revision += 1
        return {"updated": True}

    @app.delete("/api/collections/{collection_id}")
    def delete_collection(collection_id: str):
        db.delete_collection(collection_id)
        indexer.revision += 1
        return {"deleted": True}

    @app.post("/api/images/{image_id}/queue")
    async def queue_generation(image_id: str, value: QueueInput):
        image = image_or_404(image_id)
        prompt = image["metadata"].get("prompt")
        if not prompt or not any(
            isinstance(n, dict) and "class_type" in n for n in prompt.values()
        ):
            raise HTTPException(400, "No API execution graph is available to submit")
        # Validate the persisted URL too, in case the config was edited manually.
        from urllib.parse import urlparse

        target = urlparse(settings.comfy_url)
        if (
            target.scheme != "http"
            or target.hostname not in {"localhost", "127.0.0.1", "::1"}
            or target.username
            or target.password
            or target.path not in {"", "/"}
            or target.query
            or target.fragment
        ):
            raise HTTPException(
                400, "ComfyUI must be configured with a local HTTP origin"
            )
        try:
            async with httpx.AsyncClient(
                timeout=20, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.post(
                    settings.comfy_url + "/prompt",
                    json={
                        "prompt": prompt,
                        "extra_data": {
                            "extra_pnginfo": {
                                "workflow": image["metadata"].get("workflow")
                            }
                        },
                    },
                )
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, "Could not reach the local ComfyUI API") from exc
        if response.status_code != 200:
            raise HTTPException(
                400,
                {
                    "message": "ComfyUI rejected the saved graph. Check models and installed custom nodes.",
                    "response": result,
                },
            )
        return result

    dist = PROJECT / "frontend" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Unknown API endpoint")
        if (dist / "index.html").exists():
            return FileResponse(dist / "index.html")
        return JSONResponse(
            {
                "message": "Build the frontend first: see README.md or run start.ps1",
                "api": "/api/status",
            },
            status_code=503,
        )

    return app


app = create_app()
