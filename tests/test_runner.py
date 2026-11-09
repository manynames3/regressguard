import copy
import json
import os
import subprocess
import sys

import pytest

from regressguard.comparison import compare
from regressguard.runner import run
from regressguard.storage import export_snapshot, validate_snapshot
from regressguard.suites import digest, load_suite


def fixture_cases():
    return [{"id": str(i), "severity": "standard", "passed": 3, "total": 3} for i in range(20)]


def test_policy_boundaries():
    base = fixture_cases()
    cases = copy.deepcopy(base)
    assert compare(cases, {"cases": base}, 5)["verdict"] == "pass"
    cases[0]["passed"] = 0
    assert compare(cases, {"cases": base}, 5)["verdict"] == "warn"
    cases[1]["passed"] = 2
    assert compare(cases, {"cases": base}, 5)["verdict"] == "fail"
    cases = copy.deepcopy(base)
    cases[0].update(severity="critical", passed=2)
    assert compare(cases, {"cases": base}, 5)["verdict"] == "fail"
    assert compare(cases, {"cases": base}, 5, incomplete=True)["exit_code"] == 2


def test_runner_baseline_break_and_restore(root, store):
    suite = load_suite(root / "suites/ticket-classifier.yml")
    baseline = run(suite, root, store)
    assert baseline["exit_code"] == 0
    store.promote(baseline["id"])
    store.promote(baseline["id"])
    assert store.latest(suite.id)["id"] == baseline["id"]
    broken = run(suite, root, store, "latest", template="Classify {{input}}")
    assert broken["exit_code"] == 1
    assert len(store.alerts()) == 1
    assert (
        json.loads(
            (
                __import__("pathlib").Path(os.environ["REGRESSGUARD_DATA_DIR"]) / "alerts.jsonl"
            ).read_text()
        )
        == store.alerts()[0]["payload"]
    )
    assert run(suite, root, store, "latest")["exit_code"] == 0
    with pytest.raises(ValueError):
        store.promote(broken["id"])
    suite.cases[0].input = "changed"
    with pytest.raises(ValueError, match="Incompatible"):
        run(suite, root, store, "latest")


def test_snapshot_roundtrip(root, store):
    suite = load_suite(root / "suites/ticket-classifier.yml")
    report = run(suite, root, store)
    snapshot = export_snapshot(report)
    assert "samples" not in snapshot["report"]["cases"][0]
    store.import_snapshot(snapshot)
    assert store.latest(suite.id)["id"] == report["id"]
    snapshot["report"]["cases"][0]["passed"] = 10
    snapshot["sha256"] = digest(snapshot["report"])
    with pytest.raises(ValueError):
        validate_snapshot(snapshot)


def test_unscored_and_provider_error(root, store, monkeypatch):
    suite = load_suite(root / "suites/summarizer.yml")
    suite.cases = suite.cases[:1]
    suite.cases[0].checks = [suite.cases[0].checks[-1]]
    assert run(suite, root, store)["exit_code"] == 2
    monkeypatch.setattr(
        "regressguard.runner.generate_response", lambda *a: (_ for _ in ()).throw(TimeoutError())
    )
    result = run(suite, root, store)
    assert result["status"] == "incomplete"
    assert all("latency_ms" in s for s in result["cases"][0]["samples"])
    with pytest.raises(ValueError):
        store.promote(result["id"])


def test_cli_process_exit_codes(root, store):
    suite = load_suite(root / "suites/ticket-classifier.yml")
    report = run(suite, root, store)
    store.promote(report["id"])
    command = [
        sys.executable,
        "-m",
        "regressguard",
        "run",
        "--suite",
        "suites/ticket-classifier.yml",
        "--baseline",
        "latest",
    ]
    assert subprocess.run(command, cwd=root, capture_output=True).returncode == 0
    broken = subprocess.run([sys.executable, "demo/break_it.py"], cwd=root, capture_output=True)
    assert broken.returncode == 1
    assert "Return JSON" in broken.stdout.decode()
    assert subprocess.run(command[:-1] + ["missing"], cwd=root, capture_output=True).returncode == 2


def test_generation_no_answer_key(root, store):
    suite = load_suite(root / "suites/ticket-classifier.yml")
    first = run(suite, root, store)
    suite.cases[0].checks[0].schema_["properties"]["category"]["const"] = "wrong"
    second = run(suite, root, store)
    assert first["cases"][0]["samples"][0]["output"] == second["cases"][0]["samples"][0]["output"]
    assert second["cases"][0]["passed"] == 0


def test_alert_delivery_failure_preserves_verdict(root, store, monkeypatch):
    suite = load_suite(root / "suites/ticket-classifier.yml")
    reference = run(suite, root, store)
    store.promote(reference["id"])
    monkeypatch.setenv("REGRESSGUARD_WEBHOOK_URL", "https://example.invalid/webhook")
    observed = []

    def failure(*args, **kwargs):
        observed.append(kwargs["json"])
        raise TimeoutError()

    monkeypatch.setattr("regressguard.alerts.httpx.post", failure)
    report = run(suite, root, store, "latest", template="Classify {{input}}")
    assert report["exit_code"] == 1
    assert observed == [store.alerts()[0]["payload"]]
    assert store.alerts()[0]["delivery"] == {"local": "delivered", "webhook": "error"}


def test_baseline_reference_is_frozen_during_execution(root, store, monkeypatch):
    from regressguard.providers import generate_response

    suite = load_suite(root / "suites/ticket-classifier.yml")
    original = run(suite, root, store)
    replacement = run(suite, root, store)
    store.promote(original["id"])

    def concurrent_promotion(*args):
        store.promote(replacement["id"])
        return generate_response(*args)

    monkeypatch.setattr("regressguard.runner.generate_response", concurrent_promotion)
    observed = run(suite, root, store, "latest")
    assert observed["baseline_id"] == original["id"]
    assert store.latest(suite.id)["id"] == replacement["id"]


def test_historical_snapshot_remains_inspectable_but_cannot_compare(root, store):
    suite = load_suite(root / "suites/ticket-classifier.yml")
    report = run(suite, root, store)
    historical = export_snapshot(report)
    old = historical["report"]
    old["contract"]["evaluator_version"] = "1"
    old["contract"]["semantic"]["algorithm"] = "suite-reference-tfidf-v1"
    for collection in (old["suite"]["cases"], old["contract"]["cases"]):
        for case in collection:
            for check in case["checks"]:
                check.pop("preserve_facts")
    old["contract_hash"] = digest(old["contract"])
    historical["sha256"] = digest(old)
    assert validate_snapshot(historical)["id"] == report["id"]
    # New UUID avoids replacing the original immutable run.
    import uuid

    old["id"] = str(uuid.uuid4())
    historical["sha256"] = digest(old)
    store.import_snapshot(historical)
    with pytest.raises(ValueError, match="Incompatible"):
        run(suite, root, store, "latest")
