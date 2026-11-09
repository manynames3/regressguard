"""Integration smoke for an explicitly configured PostgreSQL database."""

import json
from pathlib import Path

from regressguard.runner import run
from regressguard.storage import Store
from regressguard.suites import Suite

# Persistence tests use accepted evidence, so feature PRs are decided by the gate.
reference = json.loads(Path("baselines/ticket-classifier.json").read_text())["report"]
suite = Suite.model_validate(reference["suite"])
store = Store()
report = run(suite, Path.cwd(), store, template=reference["prompt_text"])
assert report["exit_code"] == 0
store.promote(report["id"])
assert store.latest(report["suite_id"])["id"] == report["id"]
assert run(suite, Path.cwd(), store, "latest", template=reference["prompt_text"])["exit_code"] == 0
print("PostgreSQL run, promotion, retrieval and comparison passed")
