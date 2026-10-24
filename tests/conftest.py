import json
import os
import time
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from app.config import Settings
from app.database import Database
from app.indexer import Indexer


@pytest.fixture
def graph():
    return json.loads((Path(__file__).parent / "fixtures" / "basic.json").read_text())


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    settings = Settings(tmp_path / "data")
    settings.update([str(root)], "http://127.0.0.1:8188")
    db = Database(settings.data_dir)
    return root, settings, db, Indexer(settings, db)


def save_image(path, graph=None, *, color="olive", workflow=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    png = PngImagePlugin.PngInfo()
    if graph is not None:
        png.add_text("prompt", json.dumps(graph))
    if workflow is not None:
        png.add_text("workflow", json.dumps(workflow))
    Image.new("RGB", (128, 96), color).save(path, pnginfo=png)
    stamp = time.time() - 3
    os.utime(path, (stamp, stamp))
    return path


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for filesystem indexer")
