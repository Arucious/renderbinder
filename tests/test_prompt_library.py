import copy
import os

from conftest import save_image

from app.config import path_key
from app.database import Database, prompt_hash
from app.similarity import prepare_prompt, text_similarity


def test_similar_prompt_scores_use_complete_text_and_group_duplicate_images(
    library, graph
):
    root, _, db, indexer = library
    prefix = "A detailed woodland photograph with natural lighting. " * 30
    texts = [prefix + "A red coat.", prefix + "A blue coat.", prefix + "A blue coat."]
    for number, text in enumerate(texts):
        current = copy.deepcopy(graph)
        current["27"]["inputs"]["text"] = text
        save_image(root / f"variation{number}.png", current)
    indexer._scan()
    source = next(i for i in db.images()["items"] if i["filename"] == "variation0.png")
    results = db.similar_prompts(source["id"], [path_key(root)], mode="text")
    assert results["total"] == results["compared"] == len(results["items"]) == 1
    target = results["items"][0]
    assert target["image_count"] == 2
    assert target["positive"] == source["positive"]  # Identical 600-character previews.
    expected = text_similarity(
        prepare_prompt(texts[0])[0], prepare_prompt(texts[1])[0], 0
    )
    assert target["text_similarity"] == round(expected, 6) < 1


def test_prompt_groups_span_pages_and_link_to_all_matching_images(library, graph):
    root, _, db, indexer = library
    for n in range(5):
        current = copy.deepcopy(graph)
        if n >= 3:
            current["27"]["inputs"]["text"] = "A different forest prompt."
        # Different seeds and negative text do not split the same positive prompt.
        current["61"]["inputs"]["seed"] = n
        current["39"]["inputs"]["text"] = f"negative variation {n}"
        source = save_image(root / f"{n}.png", current)
        os.utime(source, (1_700_000_000 + n, 1_700_000_000 + n))
    save_image(root / "no_metadata.png")
    indexer._scan()
    first = db.images(unique_prompts=True, limit=1)
    second = db.images(unique_prompts=True, limit=1, offset=1)
    assert first["total"] == second["total"] == 2
    assert first["image_total"] == 5
    assert first["items"][0]["image_count"] == 2
    group = second["items"][0]
    assert group["image_count"] == 3
    assert group["filename"] == "2.png"  # Latest matching image is the representative.
    assert group["positive_hash"] != first["items"][0]["positive_hash"]
    images = db.images(prompt=group["positive_hash"])
    assert images["total"] == 3
    assert {i["filename"] for i in images["items"]} == {"0.png", "1.png", "2.png"}
    assert db.facets()["unique_prompts"] == 2
    assert (
        db.images()["total"] == 6
    )  # The regular gallery still includes metadata-free images.


def test_group_filters_apply_before_counts_and_representative_selection(library, graph):
    root, _, db, indexer = library
    first = save_image(root / "first.png", graph)
    other = copy.deepcopy(graph)
    other["11"]["inputs"]["ckpt_name"] = "other-model.safetensors"
    save_image(root / "second.png", other)
    indexer._scan()
    image = next(i for i in db.images()["items"] if i["filename"] == first.name)
    db.annotate([image["id"]], True, ["keep"])
    collection = db.create_collection("Chosen")
    db.collection_items(collection["id"], [image["id"]])
    all_prompts = db.images(unique_prompts=True)
    assert all_prompts["total"] == 1 and all_prompts["items"][0]["image_count"] == 2
    filtered = db.images(
        unique_prompts=True,
        favorite=True,
        tag="keep",
        collection=collection["id"],
        model="models/dream.safetensors",
    )
    assert filtered["total"] == filtered["image_total"] == 1
    assert filtered["items"][0]["id"] == image["id"]
    assert filtered["items"][0]["image_count"] == 1


def test_group_identity_uses_full_prompt_and_normalizes_only_edges_and_line_endings(
    library, graph
):
    root, _, db, indexer = library
    long_text = "shared text " * 80
    for n, text in enumerate(
        [
            long_text + "ending one",
            long_text + "ending two",
            "line one\nline two",
            "  line one\r\nline two  ",
        ]
    ):
        current = copy.deepcopy(graph)
        current["27"]["inputs"]["text"] = text
        save_image(root / f"{n}.png", current)
    indexer._scan()
    result = db.images(unique_prompts=True)
    assert result["total"] == 3
    assert sorted(i["image_count"] for i in result["items"]) == [1, 1, 2]
    assert prompt_hash("A CAT") != prompt_hash("a cat")
    assert prompt_hash("   ") is None


def test_existing_index_migrates_prompt_groups_and_preserves_annotations(
    library, graph
):
    root, settings, db, indexer = library
    save_image(root / "first.png", graph)
    save_image(root / "second.png", graph)
    indexer._scan()
    image = db.images()["items"][0]
    db.annotate([image["id"]], True, ["keep"])
    with db.write_lock, db.connect() as connection:
        connection.execute("DROP INDEX images_positive_hash")
        connection.execute("ALTER TABLE images DROP COLUMN positive_hash")
    migrated = Database(settings.data_dir)
    groups = migrated.images(unique_prompts=True)
    assert groups["total"] == 1 and groups["items"][0]["image_count"] == 2
    assert migrated.detail(image["id"])["favorite"]
    assert migrated.detail(image["id"])["tags"] == ["keep"]
