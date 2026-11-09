"""Executed in an isolated process importing the PR base evaluator."""

import json
import sys
from pathlib import Path

from regressguard import runner
from regressguard.providers import Response
from regressguard.storage import Store
from regressguard.suites import Suite

if __name__ in ("__main__", "builtins"):
    package = json.load(sys.stdin)
    observations = {case["id"]: case for case in package["observations"]["cases"]}
    samples = iter(
        sample
        for case in package["suite"]["cases"]
        for sample in observations[case["id"]]["samples"]
    )

    def replay_response(*args):
        sample = next(samples)
        return Response(
            sample["output"],
            sample["model"],
            sample["tokens_used"],
            sample["usage_source"],
            sample.get("finish_reason"),
        )

    runner.generate_response = replay_response
    store = Store("sqlite:///replay.db")
    reference = package["reference"]
    store.save(reference)
    report = runner.run(
        Suite.model_validate(package["suite"]),
        Path.cwd(),
        store,
        reference["id"],
        reference["runs"],
        template=package["template"],
    )
    # Latency is generation latency from the candidate, not the replay function's duration.
    for old_case, new_case in zip(report["cases"], package["observations"]["cases"], strict=True):
        for old_sample, new_sample in zip(old_case["samples"], new_case["samples"], strict=True):
            old_sample["latency_ms"] = new_sample["latency_ms"]
    print(json.dumps(report))
