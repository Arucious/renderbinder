"""Explicit, optional real-model smoke test. Downloads the chosen model if missing."""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.semantic import SentenceEncoder, validate_config  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", choices=["bge-small", "embeddinggemma2"], default="bge-small"
    )
    parser.add_argument("--cache", type=Path, default=Path(".qa/models"))
    args = parser.parse_args()
    start = time.monotonic()
    encoder = SentenceEncoder(
        validate_config({"model": args.model}), args.cache.resolve(), download=True
    )
    print(f"Loaded {args.model} in {time.monotonic() - start:.2f}s", flush=True)
    start = time.monotonic()
    vectors = [
        encoder.encode(text, lambda: False)[0]
        for text in [
            "A dog playing outdoors on a green lawn.",
            "A canine enjoying a grassy field.",
            "A photograph of a distant galaxy.",
        ]
    ]
    similar = float(vectors[0] @ vectors[1])
    unrelated = float(vectors[0] @ vectors[2])
    assert similar > unrelated + 0.1, (similar, unrelated)
    long = encoder.encode(
        "A photograph of woodland. " * 250 + "The last detail is a red cabin.",
        lambda: False,
    )
    print(
        {
            "model": args.model,
            "key": encoder.key,
            "device": str(encoder.model.device),
            "dimensions": len(vectors[0]),
            "related": round(similar, 4),
            "unrelated": round(unrelated, 4),
            "long_prompt_chunks": len(long),
            "inference_seconds": round(time.monotonic() - start, 2),
        },
        flush=True,
    )
