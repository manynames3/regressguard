import copy
import json

from demo.calibrate import calibration, measure, render
from regressguard.checks import Semantic


def test_calibration_is_reproducible_and_exposes_errors(root):
    directory = root / "demo/datasets"
    first = calibration(directory)
    assert first == calibration(directory)
    assert sum(first["holdout"]["counts"].values()) == 24
    assert first["holdout"]["counts"]["false_negative"] > 0
    assert first["holdout"]["counts"]["false_positive"] > 0
    assert "entity-swap" in render(first)
    assert len(first["development_sweep"]) == 5


def test_holdout_labels_cannot_change_threshold(root, tmp_path):
    import shutil

    shutil.copytree(root / "demo/datasets", tmp_path / "datasets")
    original = calibration(tmp_path / "datasets")
    path = tmp_path / "datasets/holdout.json"
    data = json.loads(path.read_text())
    for case in data["cases"]:
        case["acceptable"] = not case["acceptable"]
    path.write_text(json.dumps(data))
    changed = calibration(tmp_path / "datasets")
    assert changed["selected_threshold"] == original["selected_threshold"]
    assert changed["semantic"] == original["semantic"]
    assert changed["holdout_sha256"] != original["holdout_sha256"]


def test_confusion_counts_follow_labels():
    dataset = {
        "cases": [
            {"id": "yes", "reference": "red cat", "candidate": "red cat", "acceptable": True},
            {"id": "no", "reference": "red cat", "candidate": "satellite", "acceptable": False},
        ]
    }
    result = measure(copy.deepcopy(dataset), 0.8, Semantic(["red cat"]), True)
    assert result["counts"] == {
        "true_positive": 1,
        "false_positive": 0,
        "true_negative": 1,
        "false_negative": 0,
    }
