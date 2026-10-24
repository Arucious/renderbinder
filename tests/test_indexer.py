import copy
import hashlib
import json
from pathlib import Path

from conftest import save_image, wait_for
from PIL import Image, ImageOps

from app.config import path_key
from app.database import Database
from app.metadata import PARSER_VERSION


def test_incremental_index_cache_and_no_source_writes(library, graph):
    root, settings, db, indexer = library
    source = save_image(root / "sub" / "one.png", graph)
    before = (hashlib.sha256(source.read_bytes()).digest(), source.stat().st_mtime_ns)
    indexer._scan()
    assert indexer.status["indexed"] == 1
    item = db.images()["items"][0]
    detail = db.detail(item["id"])
    assert detail["width"] == 128 and detail["height"] == 96
    with Image.open(settings.thumbnails / detail["thumbnail"]) as thumb:
        assert max(thumb.size) <= 480
    indexer._scan()
    assert indexer.status["unchanged"] == 1 and indexer.status["indexed"] == 0
    assert db.images()["total"] == 1
    assert before == (
        hashlib.sha256(source.read_bytes()).digest(),
        source.stat().st_mtime_ns,
    )


def test_search_and_combined_filters(library, graph):
    root, _, db, indexer = library
    save_image(root / "landscape" / "one.png", graph)
    save_image(root / "two.png")
    indexer._scan()
    item = db.images(q="cinematic lighting")["items"][0]
    db.annotate([item["id"]], True, ["golden hour", "inspiration"])
    assert (
        db.images(
            q="lighting alpine",
            favorite=True,
            model="models/dream.safetensors",
            lora="detail.safetensors",
            seed="18446744073709551615",
            tag="inspiration",
        )["total"]
        == 1
    )
    assert db.images(q="cinematic lighting", exact=True)["total"] == 1
    assert db.images(q="cinematic alpine", exact=True)["total"] == 0
    assert db.images(q="golden inspiration")["total"] == 1
    assert db.images(q="SECRET")["total"] == 0
    assert db.images(q='" OR * - : ()')["total"] == 0
    assert db.images(folder=path_key(root / "landscape"))["total"] == 1
    assert db.images(limit=1, offset=1)["total"] == 2
    assert len(db.images(limit=1, offset=1)["items"]) == 1


def test_parser_upgrade_refreshes_krea2_search_and_reuses_thumbnail(
    library, monkeypatch
):
    root, settings, db, indexer = library
    graph = json.loads(
        (Path(__file__).parent / "fixtures" / "krea2_grounded_edit.json").read_text()
    )
    source = save_image(root / "krea2.png", graph)
    original_bytes = source.read_bytes()
    indexer._scan()
    item = db.images()["items"][0]
    db.annotate([item["id"]], True, ["keep-this-tag"])
    collection = db.create_collection("Keepers")
    db.collection_items(collection["id"], [item["id"]])
    # Simulate the old empty-prompt record, without changing its source file.
    with db.write_lock, db.connect() as connection:
        connection.execute(
            "UPDATE images SET positive='',version=?", (PARSER_VERSION - 1,)
        )
        connection.execute("UPDATE search SET positive=''")
    assert db.images(q="snowy")["total"] == 0
    before = db.detail(item["id"])
    thumbnail = settings.thumbnails / before["thumbnail"]
    thumb_stat = thumbnail.stat().st_mtime_ns

    def no_pixel_decode(*args, **kwargs):
        raise AssertionError("Metadata-only updates must reuse the cached thumbnail")

    monkeypatch.setattr(ImageOps, "exif_transpose", no_pixel_decode)
    indexer._scan()
    assert indexer.status["error_count"] == 0 and indexer.status["indexed"] == 1
    detail = db.detail(item["id"])
    assert detail["positive"] == graph["grounded-positive"]["inputs"]["prompt"]
    assert detail["version"] == PARSER_VERSION
    assert (
        db.images(
            q="snowy", favorite=True, tag="keep-this-tag", collection=collection["id"]
        )["total"]
        == 1
    )
    assert thumbnail.stat().st_mtime_ns == thumb_stat
    assert source.read_bytes() == original_bytes


def test_modifications_deletions_and_annotation_rebuild(library, graph):
    root, settings, db, indexer = library
    path = save_image(root / "one.png", graph)
    indexer._scan()
    item = db.images()["items"][0]
    db.annotate([item["id"]], True, ["kept"])
    collection = db.create_collection("Keepers")
    db.collection_items(collection["id"], [item["id"]])
    changed = copy.deepcopy(graph)
    changed["27"]["inputs"]["text"] = "modified orchard"
    save_image(path, changed, color="red")
    indexer._scan()
    assert db.images(q="orchard")["total"] == 1 and db.images(q="alpine")["total"] == 0
    indexer._scan(rebuild=True)
    detail = db.detail(item["id"])
    assert detail["favorite"] and detail["tags"] == ["kept"]
    assert detail["collections"] == [collection["id"]]
    assert db.images(q="kept", collection=collection["id"])["total"] == 1
    # A process restart opens the existing databases; no reindex is necessary to browse.
    reopened = Database(settings.data_dir)
    assert reopened.images()["total"] == 1
    path.unlink()
    indexer._scan()
    assert db.images()["total"] == 0
    assert db.facets()["collections"][0]["count"] == 0
    save_image(path, graph)
    indexer._scan()
    assert db.detail(item["id"])["favorite"]


def test_parser_upgrade_repairs_negative_and_search_without_rewriting_media(
    library, graph
):
    root, settings, db, indexer = library
    graph["zero"] = {
        "class_type": "ConditioningZeroOut",
        "inputs": {"conditioning": ["27", 0]},
    }
    graph["61"]["inputs"]["negative"] = ["zero", 0]
    source = save_image(root / "zero-negative.png", graph)
    original = source.read_bytes()
    indexer._scan()
    item = db.images()["items"][0]
    db.annotate([item["id"]], True, ["keep"])
    detail = db.detail(item["id"])
    thumbnail = settings.thumbnails / detail["thumbnail"]
    stamp = thumbnail.stat().st_mtime_ns
    # Simulate a cached extraction from before output routing and zeroing were respected.
    with db.write_lock, db.connect() as connection:
        connection.execute(
            "UPDATE images SET negative='UnrelatedNegativeSentinel',version=?",
            (PARSER_VERSION - 1,),
        )
        connection.execute("UPDATE search SET negative='UnrelatedNegativeSentinel'")
    assert db.images(q="UnrelatedNegativeSentinel")["total"] == 1
    indexer._scan()
    assert indexer.status["error_count"] == 0 and indexer.status["indexed"] == 1
    detail = db.detail(item["id"])
    assert detail["negative"] == ""
    assert db.images(q="UnrelatedNegativeSentinel")["total"] == 0
    assert detail["metadata"]["negative"] == ""
    assert detail["metadata"]["negative_status"]["state"] == "zeroed"
    assert detail["metadata"]["documents"][0]["provenance"]["version"] == PARSER_VERSION
    assert detail["favorite"] and detail["tags"] == ["keep"]
    assert source.read_bytes() == original
    assert thumbnail.stat().st_mtime_ns == stamp


def test_missing_root_does_not_prune(library, graph):
    root, _, db, indexer = library
    save_image(root / "one.png", graph)
    indexer._scan()
    moved = root.with_name("unavailable")
    root.rename(moved)
    indexer._scan()
    assert db.images()["total"] == 1
    assert indexer.status["error_count"] > 0


def test_cancelled_scan_does_not_prune(library, graph, monkeypatch):
    root, _, db, indexer = library
    for n in range(3):
        save_image(root / f"{n}.png", graph)
    indexer._scan()
    original = indexer._index

    def cancel(*args):
        result = original(*args)
        indexer.cancel.set()
        return result

    monkeypatch.setattr(indexer, "_index", cancel)
    indexer._scan()
    assert db.images()["total"] == 3 and indexer.status["cancelled"]


def test_bad_or_incomplete_files_do_not_block_scan(library, graph):
    root, _, db, indexer = library
    (root / "bad.png").write_bytes(b"not an image")
    (root / "partial.png").touch()
    save_image(root / "good.png", graph)
    indexer._scan()
    assert db.images()["total"] == 1 and indexer.status["error_count"] == 2
    assert indexer.snapshot()["pending"] == 2


def test_watchdog_create_modify_move_delete(library, graph):
    root, _, db, indexer = library
    indexer.start()
    try:
        wait_for(lambda: indexer.status["watching"] and indexer.status["finished_at"])
        path = save_image(root / "watch.png", graph)
        wait_for(lambda: db.images()["total"] == 1)
        graph["27"]["inputs"]["text"] = "updated by watcher"
        save_image(path, graph, color="orange")
        wait_for(lambda: db.images(q="updated watcher")["total"] == 1)
        new = root / "renamed.png"
        path.rename(new)
        wait_for(
            lambda: (
                len(items := db.images()["items"]) == 1
                and items[0]["filename"] == "renamed.png"
            )
        )
        new.unlink()
        wait_for(lambda: db.images()["total"] == 0)
    finally:
        indexer.close()


def test_watchdog_recovers_file_that_was_incomplete(library, graph):
    root, _, db, indexer = library
    partial = root / "not-finished.png"
    partial.touch()
    indexer.start()
    try:
        wait_for(lambda: bool(indexer.status["finished_at"]))
        assert db.images()["total"] == 0
        save_image(partial, graph)
        wait_for(lambda: db.images()["total"] == 1)
        assert db.images(q="cinematic")["total"] == 1
    finally:
        indexer.close()


def test_scan_does_not_follow_outside_symlinks(library, tmp_path, graph):
    root, settings, db, indexer = library
    outside = save_image(tmp_path / "outside.png", graph)
    assert not settings.allowed(outside)
    try:
        (root / "link.png").symlink_to(outside)
    except OSError:
        return  # Windows may not permit symlinks without developer mode.
    indexer._scan()
    assert db.images()["total"] == 0


def test_multiple_models_are_searchable(library):
    import json
    from pathlib import Path

    root, _, db, indexer = library
    graph = json.loads(
        (Path(__file__).parent / "fixtures" / "multiple_stages.json").read_text()
    )
    save_image(root / "stages.png", graph)
    indexer._scan()
    assert db.images(model="refiner.safetensors")["total"] == 1
    assert db.images(q="refiner")["total"] == 1
    assert db.images(q="refiner.safetensors", exact=True)["total"] == 1
    assert len(db.facets()["models"]) == 2
