"""Real full-batch logistic regression; no hardcoded evaluation measurements."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def sigmoid(value):
    return 1.0 / (1.0 + math.exp(-max(-40, min(40, value))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text())
    data = json.loads(args.dataset.read_text())
    train, test = data["train"], data["test"]
    assert set(row["id"] for row in train).isdisjoint(row["id"] for row in test)
    parameters = contract["scientific_parameters"]
    weights, bias = [0.0] * 4, 0.0
    for _ in range(parameters["epochs"]):
        gradient, bias_gradient = [0.0] * 4, 0.0
        for row in train:
            residual = (
                sigmoid(sum(w * x for w, x in zip(weights, row["x"])) + bias) - row["y"]
            )
            for index in range(4):
                gradient[index] += residual * row["x"][index]
            bias_gradient += residual
        weights = [
            w - parameters["learning_rate"] * g / len(train)
            for w, g in zip(weights, gradient)
        ]
        bias -= parameters["learning_rate"] * bias_gradient / len(train)
    predictions = [
        {
            "id": row["id"],
            "y": row["y"],
            "probability": sigmoid(
                sum(w * x for w, x in zip(weights, row["x"])) + bias
            ),
        }
        for row in test
    ]
    accuracy = sum(
        int(row["probability"] >= 0.5) == row["y"] for row in predictions
    ) / len(test)
    loss = -sum(
        row["y"] * math.log(max(row["probability"], 1e-15))
        + (1 - row["y"]) * math.log(max(1 - row["probability"], 1e-15))
        for row in predictions
    ) / len(test)
    outputs = {
        "metrics.json": {
            "accuracy": accuracy,
            "log_loss": loss,
            "test_examples": len(test),
        },
        "model.json": {
            "weights": weights,
            "bias": bias,
            "epochs": parameters["epochs"],
            "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        },
        "predictions.json": {"predictions": predictions},
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    for name, value in outputs.items():
        (args.output_root / name).write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n"
        )
    print(json.dumps(outputs["metrics.json"], sort_keys=True))


if __name__ == "__main__":
    main()
