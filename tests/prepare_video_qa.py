from pathlib import Path

from video_helpers import director_graph, save_video

folder = Path(__file__).resolve().parents[1] / ".qa" / "video-source"
save_video(
    folder / "director_a.mp4",
    director_graph(
        global_text="Video QA woodland continuity.",
        second="A fox runs toward a blue lake.",
    ),
)
save_video(
    folder / "director_b.mp4",
    director_graph(
        global_text="Video QA woodland continuity.",
        second="A fox runs toward a green lake.",
    ),
)
save_video(
    folder / "director_proxy.mkv",
    director_graph(
        global_text="Video QA woodland continuity.",
        second="A fox runs toward a golden lake.",
    ),
    codec="ffv1",
)
print(folder)
