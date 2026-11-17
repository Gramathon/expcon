"""Explicit synthetic classification data, generated once before freeze."""

import json
import random
from pathlib import Path


def generate(destination: Path):
    rng = random.Random(1729)
    rows = []
    for index in range(896):
        features = [rng.gauss(0, 1) for _ in range(4)]
        label = int(sum(x * w for x, w in zip(features, [1.5, -1.0, 0.5, 1.0])) > 0)
        if rng.random() < 0.08:
            label = 1 - label
        rows.append({"id": index, "x": features, "y": label})
    data = {
        "generator_seed": 1729,
        "label_flip_probability": 0.08,
        "split_rule": "first 640 train; remaining 256 test; no overlap",
        "train": rows[:640],
        "test": rows[640:],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    import sys

    generate(Path(sys.argv[1]))
