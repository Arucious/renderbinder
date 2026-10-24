import copy
import hashlib
import json
import re

import pytest
from conftest import save_image, wait_for

from app.config import path_key
from app.semantic import SemanticIndex, chunk_text, effective_config, validate_config

np = pytest.importorskip("numpy")


class OffsetTokenizer:
    def __call__(self, text, add_special_tokens=True, **kwargs):
        matches = list(re.finditer(r"\S+", text))
        return {
            "input_ids": list(range(len(matches) + (2 if add_special_tokens else 0))),
            "offset_mapping": [(m.start(), m.end()) for m in matches],
        }


def test_chunking_retains_whole_prompt_and_tail_with_prefix():
    text = "  " + " ".join(f"word{i}" for i in range(1500)) + " ENDING EDIT\n"
    tokenizer = OffsetTokenizer()
    chunks = chunk_text(text, tokenizer, 128, "task: sentence similarity | query: ")
    assert len(chunks) > 10
    assert chunks[0].startswith("  word0")
    assert chunks[-1].endswith("ENDING EDIT\n")
    assert all(
        len(tokenizer("task: sentence similarity | query: " + c)["input_ids"]) <= 128
        for c in chunks
    )
    assert all(f"word{i}" in " ".join(chunks) for i in range(1500))


class FakeEncoder:
    calls = []

    def __init__(self, config, cache, *, download):
        identity = effective_config(config)
        self.key = hashlib.sha256(
            json.dumps(
                {k: identity[k] for k in ("model_id", "prefix", "max_tokens")}
            ).encode()
        ).hexdigest()

    def encode(self, text, cancelled):
        self.calls.append(text)
        if cancelled():
            raise InterruptedError
        if "dog" in text or "canine" in text:
            return np.array([[1, 0, 0]], dtype=np.float32)
        return np.array([[0, 1, 0]], dtype=np.float32)


def populate(library, graph):
    root, settings, db, indexer = library
    for name, text in [
        ("a", "A dog playing in the park."),
        ("duplicate", "A dog playing in the park."),
        ("b", "A canine enjoying a grassy field."),
        ("c", "A photograph of a distant galaxy."),
    ]:
        current = copy.deepcopy(graph)
        current["27"]["inputs"]["text"] = text
        save_image(root / f"{name}.png", current)
    indexer._scan()
    FakeEncoder.calls = []
    manager = SemanticIndex(settings, db, encoder_factory=FakeEncoder)
    config = validate_config({"enabled": True})
    manager.configure(config)
    return manager, config


def test_cache_survives_restart_model_switch_and_rebuild(library, graph):
    manager, config = populate(library, graph)
    _, settings, db, indexer = library
    manager._index(config, manager.generation, True)
    assert manager.snapshot()["completed"] == 3
    assert len(FakeEncoder.calls) == 3  # Duplicate images use the same embedding.
    restarted = SemanticIndex(settings, db, encoder_factory=FakeEncoder)
    restarted._index(config, 0, False)
    assert len(FakeEncoder.calls) == 3
    other = validate_config({**config, "model": "embeddinggemma2"})
    restarted.configure(other)
    restarted._index(other, restarted.generation, True)
    assert len(FakeEncoder.calls) == 6
    restarted.configure(config)
    restarted._index(config, restarted.generation, False)
    assert len(FakeEncoder.calls) == 6
    db.rebuild()
    indexer._scan()
    restarted._index(config, restarted.generation, False)
    assert len(FakeEncoder.calls) == 6
    changed = copy.deepcopy(graph)
    changed["27"]["inputs"]["text"] = "A dog sitting near a lake."
    save_image(library[0] / "new.png", changed)
    indexer._scan()
    restarted._index(config, restarted.generation, False)
    assert len(FakeEncoder.calls) == 7


def test_semantic_ranking_groups_results_and_respects_roots(library, graph):
    manager, config = populate(library, graph)
    manager._index(config, manager.generation, True)
    root, _, db, _ = library
    source = next(i for i in db.images()["items"] if i["filename"] == "a.png")
    scores = manager.similarities(source["positive_hash"])
    results = db.similar_prompts(
        source["id"], [path_key(root)], mode="semantic", semantic_scores=scores
    )
    assert [i["filename"] for i in results["items"]] == ["b.png"]
    assert results["items"][0]["semantic_similarity"] == 1
    assert results["compared"] == 2
    assert all(i["positive_hash"] != source["positive_hash"] for i in results["items"])
    assert db.similar_prompts(source["id"], [], semantic_scores=scores) is None
    manager.configure({**config, "enabled": False})
    assert manager.similarities(source["positive_hash"]) == {}


def test_pause_retains_completed_cache_and_stale_job_cannot_commit(library, graph):
    manager, config = populate(library, graph)

    class CancellingEncoder(FakeEncoder):
        def encode(self, text, cancelled):
            vectors = super().encode(text, cancelled)
            manager.cancel()
            return vectors

    manager.encoder_factory = CancellingEncoder
    with pytest.raises(InterruptedError):
        manager._index(config, manager.generation, True)
    with manager.connect() as connection:
        assert connection.execute("SELECT count(*) FROM embeddings").fetchone()[0] == 0
    assert manager.snapshot()["state"] == "paused"


def test_failed_model_does_not_block_gallery_or_retry_download_loop(library, graph):
    manager, config = populate(library, graph)
    attempts = []

    def broken(*args, **kwargs):
        attempts.append(1)
        raise ValueError("Unsupported model")

    manager.encoder_factory = broken
    manager.start()
    try:
        wait_for(lambda: manager.snapshot()["state"] == "error")
        assert "Unsupported model" in manager.snapshot()["error"]
        assert library[2].images()["total"] == 4
        assert attempts == [1]
    finally:
        manager.close()


def test_missing_saved_model_folder_does_not_prevent_gallery_startup(library, tmp_path):
    _, settings, db, _ = library
    missing = tmp_path / "model_removed_after_setup"
    (settings.data_dir / "semantic.json").write_text(
        json.dumps({"enabled": True, "model": "custom", "custom_model": str(missing)})
    )
    manager = SemanticIndex(settings, db)
    assert manager.snapshot()["config"]["custom_model"] == str(missing)
    assert db.images()["total"] == 0


def test_custom_config_validation_and_prefix_preservation(tmp_path):
    for target in [
        "",
        "../unknown",
        "https://example.com/model",
        str(tmp_path / "missing"),
    ]:
        with pytest.raises(ValueError):
            validate_config(
                {"enabled": True, "model": "custom", "custom_model": target}
            )
    local = validate_config(
        {
            "enabled": True,
            "model": "custom",
            "custom_model": str(tmp_path),
            "prefix": "query: ",
        }
    )
    assert effective_config(local)["prefix"] == "query: "
    assert (
        effective_config(validate_config({"model": "embeddinggemma2"}))["max_tokens"]
        == 8192
    )
