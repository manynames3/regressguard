import difflib
import hashlib
import os
import subprocess
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from regressguard import alerts
from regressguard.checks import Semantic, evaluate
from regressguard.comparison import compare
from regressguard.providers import generate_response
from regressguard.suites import digest, prompt_text

EVALUATOR_VERSION = "2"


def contract(suite, runs, semantic, judge):
    return {
        "suite_id": suite.id,
        "cases": sorted([c.model_dump(by_alias=True) for c in suite.cases], key=lambda c: c["id"]),
        "policy": suite.policy.model_dump(),
        "runs": runs,
        "semantic": semantic.identity,
        "judge": judge,
        "evaluator_version": EVALUATOR_VERSION,
    }


def git_info(root):
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True))
        return {"sha": sha, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"sha": None, "dirty": None}


def run(suite, root, store, baseline=None, runs=3, *, template=None):
    if not 1 <= runs <= 20:
        raise ValueError("runs must be between 1 and 20")
    text = prompt_text(suite, root) if template is None else template
    semantic = Semantic(
        [ch.reference for case in suite.cases for ch in case.checks if ch.reference]
    )
    judge = os.getenv("REGRESSGUARD_JUDGE_MODEL") if os.getenv("REGRESSGUARD_JUDGE_KEY") else None
    definition = contract(suite, runs, semantic, judge)
    reference = None
    if baseline:
        reference = store.latest(suite.id) if baseline == "latest" else store.get(baseline)
        if reference["suite_id"] != suite.id:
            raise ValueError("Baseline belongs to another suite")
        if reference["contract_hash"] != digest(definition):
            changed = [k for k in definition if definition[k] != reference["contract"].get(k)]
            raise ValueError("Incompatible baseline contract: " + ", ".join(changed))
    provider = os.getenv("REGRESSGUARD_PROVIDER", "mock")
    report = {
        "id": str(uuid.uuid4()),
        "suite_id": suite.id,
        "suite_name": suite.name,
        "data_label": suite.data_label,
        "timestamp": datetime.now(UTC).isoformat(),
        "status": "running",
        "verdict": "incomplete",
        "exit_code": 2,
        "suite": suite.model_dump(by_alias=True),
        "contract": definition,
        "contract_hash": digest(definition),
        "runs": runs,
        "git": git_info(root),
        "provider": provider,
        "prompt_text": text,
        "prompt_hash": hashlib.sha256(text.encode()).hexdigest(),
        "target": {
            "prompt_version": suite.feature.prompt_version,
            "model": suite.feature.model,
            "generation": suite.feature.generation,
        },
        "baseline_id": reference["id"] if reference else None,
        "baseline_target": reference["target"] if reference else None,
        "cases": [],
    }
    store.save(report)
    incomplete = skipped = False
    for case in suite.cases:
        result = {
            "id": case.id,
            "severity": case.severity,
            "expected_behavior": case.expected_behavior,
            "passed": 0,
            "total": runs,
            "samples": [],
        }
        for attempt in range(runs):
            start = time.monotonic()
            sample = {
                "attempt": attempt,
                "output": None,
                "tokens_used": None,
                "usage_source": "unavailable",
                "checks": [],
            }
            try:
                response = generate_response(suite.feature, text, case.input, attempt, provider)
                sample["latency_ms"] = (time.monotonic() - start) * 1000
                sample.update(asdict(response))
                sample["output"] = sample.pop("text")
                if len(response.text) > 100_000:
                    raise ValueError("Response exceeds supported limit")
                sample["checks"] = [evaluate(ch, response.text, semantic) for ch in case.checks]
                active = [c for c in sample["checks"] if c["status"] != "skipped"]
                skipped |= len(active) != len(sample["checks"])
                incomplete |= not active or any(c["status"] == "error" for c in active)
                passed = bool(active) and all(c["status"] == "pass" for c in active)
                result["passed"] += int(passed)
            except Exception as exc:
                incomplete = True
                sample["error"] = f"{type(exc).__name__}: generation failed"
                sample["output"] = (sample["output"] or "")[:100_000]
            sample.setdefault("latency_ms", (time.monotonic() - start) * 1000)
            result["samples"].append(sample)
        report["cases"].append(result)
    report.update(
        compare(
            report["cases"],
            reference,
            suite.policy.aggregate_drop_points,
            incomplete=incomplete,
            skipped=skipped,
        )
    )
    report["status"] = "incomplete" if incomplete else "complete"
    report["ended_at"] = datetime.now(UTC).isoformat()
    report["prompt_diff"] = "".join(
        difflib.unified_diff(
            (reference["prompt_text"] if reference else "").splitlines(True),
            text.splitlines(True),
            fromfile="baseline",
            tofile="candidate",
        )
    )
    body = alerts.payload(report) if report["verdict"] == "fail" else None
    store.save(report, body)
    if body:
        alerts.deliver(store, report, body)
    return report
