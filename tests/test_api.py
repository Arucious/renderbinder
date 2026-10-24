from pathlib import Path

import pytest
from conftest import save_image
from fastapi.testclient import TestClient

from app.main import create_app
from app.metadata import PARSER_VERSION


@pytest.fixture
def client(tmp_path, graph):
    app = create_app(tmp_path / "data", watch=False)
    root = tmp_path / "source"
    root.mkdir()
    app.state.settings.update([str(root)], "http://127.0.0.1:8188")
    save_image(root / "test.png", graph, workflow={"nodes": [], "links": []})
    app.state.indexer._scan()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def test_end_to_end_browse_export_annotations(client):
    assert client.get("/api/capabilities").json()["parsers"][0] == {
        "id": "comfy-graph",
        "version": PARSER_VERSION,
    }
    response = client.get("/api/images", params={"q": "cinematic"})
    assert response.status_code == 200
    image_id = response.json()["items"][0]["id"]
    detail = client.get(f"/api/images/{image_id}").json()
    assert detail["metadata"]["settings"]["seed"] == ["18446744073709551615"]
    assert detail["metadata"]["negative_status"]["state"] == "present"
    assert "18446744073709551615" in detail["raw_json"]
    thumb = client.get(f"/api/images/{image_id}/thumbnail")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    original = client.get(f"/api/images/{image_id}/original?download=true")
    assert original.content == Path(detail["path"]).read_bytes()
    assert "attachment" in original.headers["content-disposition"]
    assert client.get(f"/api/images/{image_id}/workflow").json() == {
        "nodes": [],
        "links": [],
    }
    assert (
        client.patch(
            "/api/annotations",
            json={
                "image_ids": [image_id],
                "favorite": True,
                "tags": ["custom", " custom "],
            },
        ).status_code
        == 200
    )
    assert (
        client.get("/api/images", params={"q": "custom", "favorite": True}).json()[
            "total"
        ]
        == 1
    )
    collection = client.post("/api/collections", json={"name": "Explorations"}).json()
    assert (
        client.patch(
            f"/api/collections/{collection['id']}", json={"image_ids": [image_id]}
        ).status_code
        == 200
    )
    assert (
        client.get("/api/images", params={"collection": collection["id"]}).json()[
            "total"
        ]
        == 1
    )
    assert client.delete(f"/api/collections/{collection['id']}").status_code == 200


def test_local_security_and_validation(client):
    assert (
        client.post(
            "/api/scans", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.get("/api/images", headers={"Host": "evil.example"}).status_code == 400
    )
    assert client.get("/api/images?limit=10000").status_code == 422
    assert client.get("/api/images?after=garbage").status_code == 422
    assert client.get("/api/images?sort=metadata;DROP").status_code == 422
    assert client.get("/api/not-found").status_code == 404
    assert client.get("/api/images/missing/original").status_code == 404
    assert (
        client.put(
            "/api/settings", json={"roots": [], "comfy_url": "https://external.example"}
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/settings",
            json={"roots": ["relative"], "comfy_url": "http://localhost:8188"},
        ).status_code
        == 400
    )
    image_id = client.get("/api/images").json()["items"][0]["id"]
    assert client.post(f"/api/images/{image_id}/queue", json={}).status_code == 422
    assert (
        client.post(
            f"/api/images/{image_id}/queue", json={"confirm_generation": False}
        ).status_code
        == 422
    )


def test_removed_root_revokes_media_immediately(client):
    image_id = client.get("/api/images").json()["items"][0]["id"]
    client.put(
        "/api/settings", json={"roots": [], "comfy_url": "http://127.0.0.1:8188"}
    )
    assert client.get(f"/api/images/{image_id}/original").status_code == 404
    assert client.get(f"/api/images/{image_id}/thumbnail").status_code == 404
    assert client.get(f"/api/images/{image_id}/prompt").status_code == 404
    assert client.get(f"/api/images/{image_id}/similar-prompts").status_code == 404


def test_semantic_settings_and_text_fallback(client):
    status = client.get("/api/semantic").json()
    assert status["state"] == "disabled"
    assert {"bge-small", "embeddinggemma2"} <= status["presets"].keys()
    assert (
        client.put(
            "/api/semantic/settings",
            json={"enabled": True, "model": "custom", "custom_model": "relative"},
        ).status_code
        == 400
    )
    assert (
        client.put("/api/semantic/settings", json={"model": "bad"}).status_code == 422
    )
    assert (
        client.put("/api/semantic/settings", json={"threads": 100}).status_code == 422
    )
    assert (
        client.put(
            "/api/semantic/settings",
            json={"enabled": False, "model": "embeddinggemma2"},
        ).json()["config"]["model"]
        == "embeddinggemma2"
    )
    image_id = client.get("/api/images").json()["items"][0]["id"]
    result = client.get(f"/api/images/{image_id}/similar-prompts").json()
    assert result["method"] == "text" and result["items"] == []
    assert (
        client.get(f"/api/images/{image_id}/similar-prompts?mode=invalid").status_code
        == 422
    )


def test_full_prompt_endpoint_is_not_truncated_and_does_not_load_metadata(
    client, graph, monkeypatch
):
    long_prompt = (
        "A detailed cabin photograph. " * 70
        + "Distinct ending beyond the gallery preview."
    )
    graph["27"]["inputs"]["text"] = long_prompt
    source = Path(client.app.state.settings.roots[0]) / "long_prompt.png"
    save_image(source, graph)
    client.app.state.indexer._scan()
    image = client.get("/api/images", params={"q": "long_prompt.png"}).json()["items"][
        0
    ]
    assert len(image["positive"]) == 600

    def no_metadata(*args, **kwargs):
        raise AssertionError("Reading full prompt text should not deserialize metadata")

    monkeypatch.setattr(client.app.state.db, "detail", no_metadata)
    result = client.get(f"/api/images/{image['id']}/prompt")
    assert result.status_code == 200
    assert result.json() == {
        "id": image["id"],
        "positive_hash": image["positive_hash"],
        "positive": long_prompt,
    }
    assert client.get("/api/images/missing/prompt").status_code == 404


def test_source_filter_normalizes_absolute_path(client):
    settings = client.get("/api/settings").json()
    assert (
        client.get("/api/images", params={"root": settings["roots"][0]}).json()["total"]
        == 1
    )


def test_prompt_library_api_and_group_filter(client):
    groups = client.get("/api/images", params={"unique_prompts": True}).json()
    assert groups["total"] == groups["image_total"] == 1
    group = groups["items"][0]
    assert group["image_count"] == 1
    assert (
        client.get("/api/images", params={"prompt": group["positive_hash"]}).json()[
            "total"
        ]
        == 1
    )
    assert (
        client.get("/api/images", params={"prompt": "not-a-valid-hash"}).status_code
        == 422
    )


def test_source_change_is_visible_without_new_images(client, tmp_path):
    initial = client.get("/api/settings").json()
    revision = client.get("/api/status").json()["revision"]
    empty_root = tmp_path / "empty-library"
    empty_root.mkdir()
    result = client.put(
        "/api/settings",
        json={
            "roots": initial["roots"] + [str(empty_root)],
            "comfy_url": initial["comfy_url"],
        },
    )
    assert result.status_code == 200
    assert str(empty_root) in client.get("/api/settings").json()["roots"]
    assert client.get("/api/status").json()["revision"] > revision


def test_explicit_generation_submission_preserves_original_graph(client, monkeypatch):
    import httpx

    captured = []
    real_client = httpx.AsyncClient

    def handle(request):
        import json

        captured.append(json.loads(request.content))
        assert str(request.url) == "http://127.0.0.1:8188/prompt"
        return httpx.Response(
            200, json={"prompt_id": "mock-generation", "node_errors": {}}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    image_id = client.get("/api/images").json()["items"][0]["id"]
    # Ordinary browsing and export never call the ComfyUI client.
    client.get(f"/api/images/{image_id}")
    client.get(f"/api/images/{image_id}/workflow")
    assert captured == []
    result = client.post(
        f"/api/images/{image_id}/queue", json={"confirm_generation": True}
    )
    assert result.status_code == 200
    assert result.json()["prompt_id"] == "mock-generation"
    assert captured[0]["prompt"]["61"]["inputs"]["seed"] == 18446744073709551615
