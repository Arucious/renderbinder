import copy
import hashlib
import json
import shutil

import pytest
from conftest import wait_for
from fastapi.testclient import TestClient
from video_helpers import director_graph, save_video

from app.config import path_key
from app.main import create_app
from app.media import reader_for
from app.parsers import parse_metadata

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg video integration tools are not installed",
)


def test_ltx_global_shots_separate_search_groups_and_shared_embedding_cache(library):
    root, _, db, indexer = library
    global_text = (
        "Woodland continuity: " + "A stable landscape and natural light. " * 24
    )
    first = director_graph(global_text=global_text)
    first["director"]["inputs"]["frame_rate"] = 6  # Export is retimed to 12 FPS.
    second = director_graph(
        global_text=global_text, second="The fox looks toward a green lake."
    )
    save_video(root / "one.mp4", first)
    save_video(root / "two.mp4", second)
    indexer._scan()
    assert indexer.status["error_count"] == 0
    assert db.images(media_kind="video")["total"] == 2
    assert db.images(media_kind="image")["total"] == 0
    detail = db.detail(db.images()["items"][0]["id"])
    assert detail["positive"] == global_text
    docs = detail["prompt_documents"]
    assert [d["scope"] for d in docs] == ["global", "shot", "shot"]
    assert docs[1]["start"] == 0 and docs[1]["end"] == 1
    assert docs[2]["start"] == 1 and docs[2]["end"] == 3
    assert detail["fps"] == 12 and detail["duration"] == pytest.approx(3, abs=0.1)
    groups = db.images(unique_prompts=True)
    assert groups["total"] == 4 and groups["image_total"] == 2
    assert (
        db.images(unique_prompts=True, prompt_scope="global")["items"][0]["image_count"]
        == 2
    )
    assert db.images(unique_prompts=True, q="green")["total"] == 1
    assert db.images(q="green", prompt_scope="global")["total"] == 0
    assert db.images(q="green", prompt_scope="shot")["total"] == 1
    assert len(db.embedding_prompts([path_key(root)])) == 4
    shot = db.images(unique_prompts=True, q="blue")["items"][0]
    source = db.prompts.text(shot["prompt_id"])
    assert source["scope"] == "shot"
    related = db.prompts.similar(source, [path_key(root)], mode="text")
    assert related["items"][0]["scope"] == "shot"
    assert "green" in related["items"][0]["positive"]
    assert all(item["scope"] == "shot" for item in related["items"])
    assert db.images(prompt=shot["positive_hash"])["total"] == 1


@pytest.mark.parametrize("zero_negative", [False, True])
def test_ltx_conditioning_chain_keeps_negative_separate(library, zero_negative):
    root, _, db, indexer = library
    graph = director_graph()
    if zero_negative:
        graph["negative"] = {
            "class_type": "ConditioningZeroOut",
            "inputs": {"conditioning": ["director", 1]},
        }
    graph["conditioning"] = {
        "class_type": "LTXVConditioning",
        "inputs": {
            "positive": ["director", 1],
            "negative": ["negative", 0],
            "frame_rate": ["director", 6],
        },
    }
    graph["guide"] = {
        "class_type": "LTXDirectorGuide",
        "inputs": {
            "positive": ["conditioning", 0],
            "negative": ["conditioning", 1],
            "model": ["director", 0],
            "latent": ["director", 2],
            "guide_data": ["director", 4],
            "motion_guide_data": ["director", 5],
        },
    }
    graph["crop"] = {
        "class_type": "LTXDirectorCropGuides",
        "inputs": {
            "positive": ["guide", 0],
            "negative": ["guide", 1],
            "latent": ["director", 2],
        },
    }
    graph["sampler"]["inputs"].update(positive=["crop", 0], negative=["crop", 1])
    save_video(root / "director-chain.mp4", graph)
    indexer._scan()
    assert indexer.status["error_count"] == 0
    detail = db.detail(db.images()["items"][0]["id"])
    assert detail["negative"] == ("" if zero_negative else "blur, artifacts")
    assert detail["metadata"]["negative_status"]["state"] == (
        "zeroed" if zero_negative else "present"
    )
    docs = detail["prompt_documents"]
    assert [d["scope"] for d in docs] == ["global", "shot", "shot"]
    assert docs[0]["text"] == "A consistent woodland setting."
    assert docs[1]["text"] == "A fox walks past a red cabin."
    assert detail["metadata"]["raw"]["prompt"]


def test_sidecar_changes_update_prompts_without_touching_original_or_thumbnail(library):
    root, settings, db, indexer = library
    source = save_video(root / "sidecar.mp4")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    sidecar = source.with_name(source.name + ".json")
    sidecar.write_text(json.dumps({"prompt": director_graph()}))
    indexer._scan()
    item = db.images()["items"][0]
    db.annotate([item["id"]], True, ["keep"])
    thumb = settings.thumbnails / db.detail(item["id"])["thumbnail"]
    stamp = thumb.stat().st_mtime_ns
    sidecar.write_text(
        json.dumps({"prompt": director_graph(first="A horse walks beside the cabin.")})
    )
    indexer._scan()
    assert db.images(q="horse")["total"] == 1
    assert db.detail(item["id"])["favorite"]
    assert thumb.stat().st_mtime_ns == stamp
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    sidecar.unlink()
    indexer._scan()
    assert db.images(unique_prompts=True)["total"] == 0
    assert db.images(q="horse")["total"] == 0


def test_timeline_visual_export_offset_and_disconnected_nodes(library):
    root, _, _, _ = library
    graph = director_graph()
    graph["unused"] = copy.deepcopy(graph["director"])
    graph["unused"]["inputs"]["local_prompts"] = "UNUSED SECRET"
    path = save_video(root / "timeline.mp4", graph)
    info = reader_for(path).read(path, None)
    parsed = parse_metadata(path, info, lambda _: True)
    assert "SECRET" not in " ".join(d["text"] for d in parsed["documents"])
    timeline = json.loads(graph["director"]["inputs"]["timeline_data"])
    timeline["segments"][0]["start"] = 24
    timeline["segments"][1]["start"] = 36
    # Workflow-only timeline JSON is identified by schema, not widget position.
    info.raw = {
        "workflow": {
            "nodes": [
                {
                    "id": 123,
                    "type": "LTXDirector",
                    "widgets_values": ["unrelated", json.dumps(timeline)],
                }
            ],
            "links": [],
        }
    }
    docs = parse_metadata(path, info, lambda _: True)["documents"]
    assert docs[0]["scope"] == "global"
    assert docs[1]["start"] == 2 and docs[2]["start"] == 3


def test_video_api_playback_range_proxy_and_revoked_access(tmp_path):
    app = create_app(tmp_path / "data", watch=False)
    root = tmp_path / "source"
    root.mkdir()
    app.state.settings.update([str(root)], "http://127.0.0.1:8188")
    native = save_video(root / "native.mp4", director_graph())
    save_video(root / "proxy.mkv", director_graph(), codec="ffv1")
    app.state.indexer._scan()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        items = client.get("/api/images?media_kind=video").json()["items"]
        assert len(items) == 2
        item = next(i for i in items if i["filename"] == native.name)
        ready = client.post(f"/api/images/{item['id']}/playback").json()
        assert ready["state"] == "ready" and not ready["proxy"]
        stream = client.get(ready["url"], headers={"Range": "bytes=0-99"})
        assert stream.status_code == 206 and stream.content == native.read_bytes()[:100]
        assert stream.headers["content-type"] == "video/mp4"
        assert client.get("/api/media?media_kind=video").json()["total"] == 2
        assert client.get("/api/prompts?prompt_scope=shot").json()["total"] == 2
        assert (
            len(client.get(f"/api/media/{item['id']}").json()["prompt_documents"]) == 3
        )

        def compatible_ready():
            status = client.post(
                f"/api/media/{item['id']}/playback?compatible=true"
            ).json()
            assert status["state"] != "error", status
            return status["state"] == "ready" and status["proxy"]

        wait_for(compatible_ready, timeout=30)
        assert (
            client.get(
                f"/api/media/{item['id']}/playback?compatible=true",
                headers={"Range": "bytes=0-63"},
            ).status_code
            == 206
        )
        doc = client.get("/api/images/" + item["id"]).json()["prompt_documents"][1]
        assert client.get("/api/prompts/" + doc["prompt_id"]).json()["scope"] == "shot"
        assert (
            client.get(
                "/api/prompts/" + doc["prompt_id"] + "/similar-prompts"
            ).status_code
            == 200
        )
        proxy = next(i for i in items if i["filename"] == "proxy.mkv")

        def proxy_ready():
            status = client.post(f"/api/images/{proxy['id']}/playback").json()
            assert status["state"] != "error", status
            return status["state"] == "ready"

        wait_for(proxy_ready, timeout=30)
        converted = client.get(
            f"/api/images/{proxy['id']}/playback", headers={"Range": "bytes=0-63"}
        )
        assert converted.status_code == 206 and len(converted.content) == 64
        assert client.get("/api/capabilities").json()["video_available"]
        client.put(
            "/api/settings", json={"roots": [], "comfy_url": "http://127.0.0.1:8188"}
        )
        assert client.get(ready["url"]).status_code == 404
        assert client.get(f"/api/images/{proxy['id']}/playback").status_code == 404
        assert (
            client.get(f"/api/media/{item['id']}/playback?compatible=true").status_code
            == 404
        )
        assert client.get("/api/prompts/" + doc["prompt_id"]).status_code == 404
        assert (
            client.get(
                "/api/prompts/" + doc["prompt_id"] + "/similar-prompts"
            ).status_code
            == 404
        )


def test_watch_sidecar_json_edits_and_deletions(library):
    root, _, db, indexer = library
    source = save_video(root / "watched.v1.mp4")
    indexer.start()
    try:
        wait_for(lambda: db.images()["total"] == 1)
        sidecar = source.with_suffix(".json")
        sidecar.write_text(
            json.dumps(
                {"prompt": director_graph(first="A unique zebra walks forward.")}
            )
        )
        wait_for(lambda: db.images(q="zebra")["total"] == 1)
        sidecar.unlink()
        wait_for(lambda: db.images(q="zebra")["total"] == 0)
    finally:
        indexer.close()


def test_same_text_keeps_scope_identity_but_reuses_text_embedding(library):
    from conftest import save_image

    root, _, db, indexer = library
    text = "The same descriptive woodland prompt."
    save_image(
        root / "scopes.png", director_graph(global_text=text, first=text, second=text)
    )
    indexer._scan()
    groups = db.images(unique_prompts=True)
    assert groups["total"] == 2
    assert {p["scope"] for p in groups["items"]} == {"global", "shot"}
    assert groups["items"][0]["positive_hash"] != groups["items"][1]["positive_hash"]
    assert len(db.embedding_prompts([path_key(root)])) == 1


def test_videohelper_comment_metadata_container(tmp_path, monkeypatch):
    from app.media import readers

    graph = director_graph()
    container = {"prompt": graph, "workflow": {"nodes": [], "links": []}}
    probe = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 320,
                "height": 180,
                "avg_frame_rate": "12/1",
            }
        ],
        "format": {"duration": "3", "tags": {"COMMENT": json.dumps(container)}},
    }
    monkeypatch.setattr(
        readers, "run_media", lambda *args, **kwargs: json.dumps(probe).encode()
    )
    path = tmp_path / "comment.mp4"
    info = readers.VideoReader().read(path, None)
    metadata = parse_metadata(path, info, lambda _: True)
    assert len(metadata["documents"]) == 3
    assert metadata["prompt"] == graph


def test_unresolved_connected_global_does_not_substitute_stale_timeline(library):
    from conftest import save_image

    root, _, db, indexer = library
    graph = director_graph(global_text="STALE timeline global text")
    graph["generator"] = {"class_type": "UnknownDynamicTextGenerator", "inputs": {}}
    graph["director"]["inputs"]["global_prompt"] = ["generator", 0]
    save_image(root / "dynamic.png", graph)
    indexer._scan()
    detail = db.detail(db.images()["items"][0]["id"])
    assert all(d["scope"] == "shot" for d in detail["prompt_documents"])
    assert any(
        "connected global prompt" in warning
        for warning in detail["metadata"]["warnings"]
    )
