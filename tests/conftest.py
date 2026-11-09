from pathlib import Path

import pytest

from regressguard.storage import Store


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    import socket

    def blocked(*args, **kwargs):
        raise AssertionError("Network forbidden in default tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    for key in (
        "OPENAI_API_KEY",
        "REGRESSGUARD_JUDGE_KEY",
        "REGRESSGUARD_JUDGE_MODEL",
        "REGRESSGUARD_WEBHOOK_URL",
        "REGRESSGUARD_EMBEDDING_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REGRESSGUARD_PROVIDER", "mock")
    monkeypatch.setenv("REGRESSGUARD_SEMANTIC_BACKEND", "tfidf")
    monkeypatch.setenv("REGRESSGUARD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def store():
    return Store()


@pytest.fixture
def root(tmp_path):
    """Engine tests use accepted fixtures, independent of a candidate prompt's quality."""
    import json
    import shutil

    import yaml

    source = Path(__file__).resolve().parents[1]
    root = tmp_path / "project"
    for name in ("regressguard", "api", "demo", "baselines", ".github"):
        shutil.copytree(source / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "suites").mkdir()
    for path in (root / "baselines").glob("*.json"):
        report = json.loads(path.read_text())["report"]
        suite = report["suite"]
        (root / "suites" / f"{suite['id']}.yml").write_text(yaml.safe_dump(suite))
        prompt = root / suite["feature"]["prompt"]
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt.write_text(report["prompt_text"])
    return root
