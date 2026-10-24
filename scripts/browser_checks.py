"""Run the synthetic browser suite with an owned, isolated QA server on port 8766."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / ".qa"
DATA = QA / "data"


def run(*args, env):
    print("Running:", " ".join(str(arg) for arg in args), flush=True)
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="Include BGE downloads and real-model UI checks (install the semantic extra first)",
    )
    args = parser.parse_args()
    for tool in ("node", "ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            parser.error(f"{tool} is required; see docs/cloud-development.md")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8766)) == 0:
            parser.error(
                "Port 8766 is in use; stop the QA server before running this command"
            )
    DATA.mkdir(parents=True, exist_ok=True)
    # This directory is generated test data. Never reuse personal source settings.
    (DATA / "config.json").write_text(
        json.dumps({"roots": [], "comfy_url": "http://127.0.0.1:8188"}),
        encoding="utf-8",
    )
    (DATA / "semantic.json").write_text(
        json.dumps({"enabled": False}), encoding="utf-8"
    )
    # A previous suite may have retained favorites/tags for paths that reappear.
    # Reset only the generated QA annotations, even while its source list is empty.
    with sqlite3.connect(DATA / "library.sqlite3") as library:
        for table in ("collection_items", "collections", "annotations"):
            if library.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                library.execute(f"DELETE FROM {table}")
    duplicate = QA / "sources" / "experiments" / "qa_duplicate_prompt.png"
    duplicate.unlink(missing_ok=True)
    env = {
        **os.environ,
        "GALLERY_DATA_DIR": str(DATA),
        "GALLERY_TEST_SEMANTIC": "1" if args.semantic else "0",
    }
    for script in (
        "prepare_browser_qa.py",
        "prepare_prompt_diff_qa.py",
        "prepare_negative_status_qa.py",
        "prepare_video_qa.py",
    ):
        run(sys.executable, ROOT / "tests" / script, env=env)
    suites = [
        "browser_smoke.cjs",
        "browser_prompt_groups.cjs",
        "browser_prompt_diff.cjs",
        "browser_negative_status.cjs",
    ]
    if args.semantic:
        suites.append("browser_semantic.cjs")
    suites.append("browser_video.cjs")
    log_path = QA / "browser-server.log"
    with log_path.open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8766",
                "--no-access-log",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 30
            while True:
                if server.poll() is not None:
                    raise RuntimeError(f"QA server exited; inspect {log_path}")
                try:
                    with urlopen(
                        "http://127.0.0.1:8766/api/settings", timeout=1
                    ) as response:
                        settings = json.load(response)
                    if Path(settings["data_dir"]).resolve() != DATA.resolve():
                        raise RuntimeError(
                            "Unexpected data directory; refusing to run browser checks"
                        )
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() > deadline:
                        raise RuntimeError(
                            f"QA server did not become ready; inspect {log_path}"
                        ) from None
                    time.sleep(0.2)
            for suite in suites:
                run("node", ROOT / "tests" / suite, env=env)
        finally:
            if os.name == "nt" and server.poll() is None:
                # A Windows venv executable can spawn a second Python process.
                # Stop the owned tree so the child cannot retain the QA port.
                subprocess.run(
                    ["taskkill", "/PID", str(server.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            elif server.poll() is None:
                server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
    print(
        f"Browser checks passed. Synthetic screenshots and server log: {QA}", flush=True
    )


if __name__ == "__main__":
    main()
