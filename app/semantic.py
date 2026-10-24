"""Optional CPU embeddings, resumable indexing, and model-specific disk caches."""

from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .config import PROJECT, path_key

PRESETS = {
    "bge-small": {
        "name": "BGE-small-en-v1.5",
        "model_id": "BAAI/bge-small-en-v1.5",
        "backend": "torch",
        "max_tokens": 512,
        "prefix": "",
        "description": "Small English model. 384 dimensions, 512 tokens per chunk. MIT license.",
    },
    "embeddinggemma2": {
        "name": "EmbeddingGemma 2",
        "model_id": "google/embeddinggemma-2",
        "backend": "torch",
        "max_tokens": 8192,
        "prefix": "task: sentence similarity | query: ",
        "description": "Longer context and multilingual text. 270M text parameters, 768 dimensions. Apache 2.0. Larger download and CPU workload.",
    },
}
DEFAULT_CONFIG = {
    "enabled": False,
    "model": "bge-small",
    "custom_model": "",
    "revision": "main",
    "backend": "torch",
    "prefix": "",
    "max_tokens": 512,
    "threads": min(4, os.cpu_count() or 1),
}
CACHE_POLICY = "overlap-offset-chunks-v1"


def validate_config(value: dict, *, check_paths=True) -> dict:
    value = {**DEFAULT_CONFIG, **value}
    if value["model"] not in {*PRESETS, "custom"}:
        raise ValueError("Choose a supported semantic model")
    if value["backend"] != "torch":
        raise ValueError("Custom models must use the PyTorch CPU backend")
    if not 128 <= value["max_tokens"] <= 8192 or not 1 <= value["threads"] <= 8:
        raise ValueError("Use 128–8192 tokens per chunk and 1–8 CPU threads")
    value["custom_model"] = value["custom_model"].strip()
    value["revision"] = value["revision"].strip() or "main"
    if value["model"] == "custom" and value["enabled"]:
        target = value["custom_model"]
        if Path(target).is_absolute():
            if check_paths and not Path(target).is_dir():
                raise ValueError("The local model folder does not exist")
        elif (
            not re.fullmatch(r"[a-zA-Z0-9][\w.-]*/[a-zA-Z0-9][\w.-]*", target)
            or ".." in target
            or "--" in target
        ):
            raise ValueError(
                "Enter an absolute model folder or a Hugging Face owner/model ID"
            )
    return {key: value[key] for key in DEFAULT_CONFIG}


def effective_config(config: dict) -> dict:
    if config["model"] in PRESETS:
        preset = PRESETS[config["model"]]
        return {
            **config,
            **{k: preset[k] for k in ("model_id", "backend", "max_tokens", "prefix")},
        }
    return {**config, "model_id": config["custom_model"]}


def chunk_text(text, tokenizer, max_tokens: int, prefix: str) -> list[str]:
    """Slice original text at tokenizer offsets, retaining the complete tail."""
    overhead = len(tokenizer(prefix, add_special_tokens=True)["input_ids"]) + 8
    width = max_tokens - overhead
    if width < 32:
        raise ValueError("The model prefix leaves too little room for prompt text")
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        truncation=False,
        return_offsets_mapping=True,
        verbose=False,
    )
    offsets = encoded["offset_mapping"]
    if not offsets:
        return [text]
    overlap = min(64, width // 4)
    chunks = []
    start = 0
    while start < len(offsets):
        end = min(len(offsets), start + width)
        left = 0 if start == 0 else offsets[start][0]
        right = len(text) if end == len(offsets) else offsets[end][0]
        chunk = text[left:right]
        # Boundaries can retokenize differently, so verify every actual encoder input.
        while (
            len(tokenizer(prefix + chunk, add_special_tokens=True)["input_ids"])
            > max_tokens
        ):
            end -= 1
            if end <= start:
                raise ValueError("The tokenizer could not produce a bounded text chunk")
            right = offsets[end][0]
            chunk = text[left:right]
        chunks.append(chunk)
        if end == len(offsets):
            break
        start = max(start + 1, end - overlap)
    return chunks


class SentenceEncoder:
    def __init__(self, config: dict, cache: Path, *, download: bool):
        import torch
        from huggingface_hub import hf_hub_download, snapshot_download
        from sentence_transformers import SentenceTransformer

        config = effective_config(config)
        torch.set_num_threads(config["threads"])
        target = config["model_id"]
        if Path(target).is_absolute():
            folder = Path(target).resolve()
            identity = [
                (str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns)
                for p in sorted(folder.rglob("*"))
                if p.is_file()
            ]
            revision = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        else:
            module_file = hf_hub_download(
                target,
                "modules.json",
                revision=config["revision"],
                cache_dir=str(cache),
                local_files_only=not download,
            )
            patterns = ["*.json", "*.txt", "*.model", "*.tiktoken", "*.jinja"]
            patterns += ["*.safetensors"]
            folder = Path(
                snapshot_download(
                    target,
                    revision=Path(module_file).parent.name,
                    cache_dir=str(cache),
                    allow_patterns=patterns,
                    local_files_only=not download,
                )
            )
            revision = folder.name
        if not (folder / "modules.json").is_file():
            raise ValueError(
                "Choose a Sentence Transformers model folder containing modules.json"
            )
        kwargs = {
            "device": "cpu",
            "backend": config["backend"],
            "trust_remote_code": False,
            "local_files_only": True,
            "model_kwargs": {"torch_dtype": torch.float32, "use_safetensors": True},
        }
        if config["model"] == "embeddinggemma2":
            if (
                "embedding_gemma2"
                not in __import__(
                    "transformers"
                ).models.auto.configuration_auto.CONFIG_MAPPING
            ):
                raise ValueError(
                    "EmbeddingGemma 2 requires a Transformers release with embedding_gemma2 support. Upgrade requirements-semantic.txt."
                )
            kwargs["config_kwargs"] = {"vision_config": None, "audio_config": None}
        self.model = SentenceTransformer(str(folder), **kwargs)
        self.tokenizer = self.model.tokenizer
        if not getattr(self.tokenizer, "is_fast", False):
            raise ValueError(
                "This model needs a fast tokenizer with character offsets for full-prompt chunking"
            )
        self.max_tokens = min(int(self.model.max_seq_length), config["max_tokens"])
        self.prefix = config["prefix"]
        self.key = hashlib.sha256(
            json.dumps(
                {
                    "model": target,
                    "revision": revision,
                    "backend": config["backend"],
                    "max_tokens": self.max_tokens,
                    "prefix": self.prefix,
                    "policy": CACHE_POLICY,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def encode(self, text: str, cancelled) -> object:
        import numpy as np

        chunks = chunk_text(text, self.tokenizer, self.max_tokens, self.prefix)
        vectors = []
        for chunk in chunks:
            if cancelled():
                raise InterruptedError
            vectors.append(
                self.model.encode(
                    [chunk],
                    prompt=self.prefix,
                    batch_size=1,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )[0]
            )
        result = np.asarray(vectors, dtype=np.float32)
        if (
            result.ndim != 2
            or not 1 <= result.shape[1] <= 16384
            or not np.isfinite(result).all()
        ):
            raise ValueError("The model returned invalid sentence embeddings")
        norms = np.linalg.norm(result, axis=1, keepdims=True)
        if (norms <= 0).any():
            raise ValueError("The model returned empty sentence embeddings")
        return result / norms


class SemanticIndex:
    def __init__(self, settings, db, *, encoder_factory=SentenceEncoder):
        self.settings, self.db = settings, db
        self.file = settings.data_dir / "semantic.json"
        self.path = settings.data_dir / "embeddings.sqlite3"
        self.cache = settings.data_dir / "models"
        self.config = validate_config(
            json.loads(self.file.read_text()) if self.file.exists() else {},
            check_paths=False,
        )
        self.lock = threading.RLock()
        self.wake, self.stop = threading.Event(), threading.Event()
        self.generation = 0
        self.download = False
        self.paused = False
        self.encoder_factory = encoder_factory
        self.encoder = None
        self.encoder_config = None
        self.encoder_generation = None
        self.thread = None
        self.progress = {
            "state": "idle" if self.config["enabled"] else "disabled",
            "completed": 0,
            "total": 0,
            "error": "",
            "model_key": None,
        }
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS embeddings (model_key TEXT NOT NULL, prompt_hash TEXT NOT NULL, dimensions INTEGER NOT NULL, chunks INTEGER NOT NULL, vectors BLOB NOT NULL, PRIMARY KEY(model_key,prompt_hash))"
            )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            with connection:
                yield connection
        finally:
            connection.close()

    def snapshot(self):
        with self.lock:
            return {
                **self.progress,
                "config": dict(self.config),
                "presets": PRESETS,
                "available": importlib.util.find_spec("sentence_transformers")
                is not None,
                "install_command": f'& "{PROJECT / "install-semantic.ps1"}"'
                if os.name == "nt"
                else "uv sync --locked --extra semantic",
            }

    def start(self):
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="semantic-index"
        )
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=3)

    def configure(self, value: dict):
        value = validate_config(value)
        with self.lock:
            temp = self.file.with_suffix(".tmp")
            temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
            temp.replace(self.file)
            self.config = value
            self.generation += 1
            self.download, self.paused = value["enabled"], False
            self.progress.update(
                state="queued" if value["enabled"] else "disabled",
                error="",
                completed=0,
                total=0,
                model_key=None,
            )
        self.wake.set()
        return self.snapshot()

    def cancel(self):
        with self.lock:
            self.generation += 1
            self.paused = True
            self.progress.update(state="paused", error="")
        self.wake.set()
        return self.snapshot()

    def _run(self):
        while not self.stop.is_set():
            self.wake.clear()
            with self.lock:
                config, generation, download = (
                    dict(self.config),
                    self.generation,
                    self.download,
                )
                active = config["enabled"] and not self.paused
                self.download = False
            if not active:
                self.encoder = self.encoder_config = None
                gc.collect()
            else:
                try:
                    self._index(config, generation, download)
                except InterruptedError:
                    pass
                except Exception as exc:
                    with self.lock:
                        if generation == self.generation:
                            self.progress.update(
                                state="error",
                                error=f"{type(exc).__name__}: {exc}"[:1200],
                            )
                            self.paused = True
            if not self.wake.is_set():
                self.wake.wait(10)

    def _index(self, config, generation, download):
        def cancelled():
            return self.stop.is_set() or generation != self.generation

        def progress(**values):
            with self.lock:
                if cancelled():
                    raise InterruptedError
                self.progress.update(**values)

        if self.encoder_config != config or self.encoder_generation != generation:
            self.encoder = self.encoder_config = None
            gc.collect()
            progress(state="loading", error="")
            self.encoder = self.encoder_factory(config, self.cache, download=download)
            self.encoder_config = config
            self.encoder_generation = generation
        if cancelled():
            raise InterruptedError
        encoder = self.encoder
        prompts = self.db.embedding_prompts([path_key(r) for r in self.settings.roots])
        with self.connect() as connection:
            cached = {
                r[0]
                for r in connection.execute(
                    "SELECT prompt_hash FROM embeddings WHERE model_key=?",
                    (encoder.key,),
                )
            }
        completed = sum(p["positive_hash"] in cached for p in prompts)
        progress(
            state="indexing" if completed < len(prompts) else "ready",
            total=len(prompts),
            completed=completed,
            model_key=encoder.key,
        )
        for prompt in prompts:
            if cancelled():
                raise InterruptedError
            if prompt["positive_hash"] in cached:
                continue
            vectors = encoder.encode(prompt["positive"], cancelled)
            if cancelled():
                raise InterruptedError
            with self.connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?)",
                    (
                        encoder.key,
                        prompt["positive_hash"],
                        vectors.shape[1],
                        vectors.shape[0],
                        vectors.astype("<f4").tobytes(),
                    ),
                )
            completed += 1
            progress(completed=completed)
        progress(state="ready")

    def similarities(self, source_hash: str) -> dict[str, float]:
        with self.lock:
            if not self.config["enabled"] or self.progress["state"] != "ready":
                return {}
            key = self.progress["model_key"]
        import numpy as np

        with self.connect() as connection:
            source = connection.execute(
                "SELECT dimensions,chunks,vectors FROM embeddings WHERE model_key=? AND prompt_hash=?",
                (key, source_hash),
            ).fetchone()
            if not source:
                with self.lock:
                    if self.progress["model_key"] == key and self.config["enabled"]:
                        self.progress["state"] = "indexing"
                        self.wake.set()
                return {}
            a = np.frombuffer(source[2], dtype="<f4").reshape(source[1], source[0])
            scores = {}
            for target_hash, dimensions, chunks, blob in connection.execute(
                "SELECT prompt_hash,dimensions,chunks,vectors FROM embeddings WHERE model_key=?",
                (key,),
            ):
                if dimensions != source[0]:
                    continue
                b = np.frombuffer(blob, dtype="<f4").reshape(chunks, dimensions)
                matrix = a @ b.T
                scores[target_hash] = max(
                    0.0,
                    min(
                        1.0,
                        float(
                            (matrix.max(axis=0).mean() + matrix.max(axis=1).mean()) / 2
                        ),
                    ),
                )
        with self.lock:
            return (
                scores
                if self.progress["model_key"] == key and self.config["enabled"]
                else {}
            )
