"""Measure a fixed evaluator on fictional labeled outputs; select thresholds on development only."""

import argparse
import hashlib
import json
from pathlib import Path

from regressguard import checks
from regressguard.checks import Semantic, evaluate
from regressguard.runner import EVALUATOR_VERSION
from regressguard.suites import Check, digest


def load_dataset(path, split):
    body = json.loads(path.read_text())
    if body["schema_version"] != 1 or body["split"] != split:
        raise ValueError("Dataset schema/split mismatch")
    cases = body["cases"]
    if len({c["id"] for c in cases}) != len(cases) or not cases:
        raise ValueError("Dataset IDs must be unique and nonempty")
    for case in cases:
        if type(case["acceptable"]) is not bool or not all(
            isinstance(case[field], str) and case[field]
            for field in ("id", "reference", "candidate", "reason")
        ):
            raise ValueError("Invalid labeled case")
    return body


def measure(dataset, threshold, semantic, preserve_facts):
    counts = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0}
    rows = []
    for case in dataset["cases"]:
        check = Check(
            type="semantic_similarity",
            reference=case["reference"],
            threshold=threshold,
            preserve_facts=preserve_facts,
        )
        result = evaluate(check, case["candidate"], semantic)
        if result["status"] not in ("pass", "fail"):
            raise ValueError("Calibration evaluator did not complete")
        flagged = result["status"] == "fail"
        key = (
            ("false_positive" if case["acceptable"] else "true_positive")
            if flagged
            else ("true_negative" if case["acceptable"] else "false_negative")
        )
        counts[key] += 1
        rows.append({**case, "classification": key, "evaluation": result})
    good = counts["true_negative"] + counts["false_positive"]
    bad = counts["true_positive"] + counts["false_negative"]
    return {
        "threshold": threshold,
        "preserve_facts": preserve_facts,
        "counts": counts,
        "false_alarm_rate": counts["false_positive"] / good if good else None,
        "miss_rate": counts["false_negative"] / bad if bad else None,
        "cases": rows,
    }


def calibration(directory):
    development = load_dataset(directory / "development.json", "development")
    # Fit the representation on development references only. Holdout never affects fitting/selection.
    semantic = Semantic([c["reference"] for c in development["cases"]])
    sweeps = [measure(development, t / 100, semantic, True) for t in (60, 70, 80, 90, 95)]
    selected = min(
        sweeps,
        key=lambda r: (
            r["counts"]["false_positive"] + r["counts"]["false_negative"],
            r["counts"]["false_negative"],
            abs(r["threshold"] - 0.8),
        ),
    )
    holdout = load_dataset(directory / "holdout.json", "holdout")
    overlap = {(c["reference"], c["candidate"]) for c in development["cases"]} & {
        (c["reference"], c["candidate"]) for c in holdout["cases"]
    }
    if overlap:
        raise ValueError("Development and holdout contain identical pairs")
    return {
        "schema_version": 1,
        "data_label": "fictional_sample",
        "evaluator_version": EVALUATOR_VERSION,
        "implementation_sha256": hashlib.sha256(Path(checks.__file__).read_bytes()).hexdigest(),
        "semantic": semantic.identity,
        "development_sha256": digest(development),
        "holdout_sha256": digest(holdout),
        "selection": "Minimize development errors, then misses, then distance from 0.8",
        "development_sweep": sweeps,
        "selected_threshold": selected["threshold"],
        "holdout": measure(holdout, selected["threshold"], semantic, True),
        "holdout_cosine_only": measure(holdout, selected["threshold"], semantic, False),
    }


def render(report):
    lines = [
        "# Fictional evaluator calibration",
        "",
        "Authored synthetic challenge pairs. These results measure these fixtures only.",
        f"Evaluator {report['evaluator_version']}; selected threshold {report['selected_threshold']}.",
        "Representation and threshold use development data only.",
        "",
        "| Mode | Correctly flagged | Missed bad output | False alarm | Correctly accepted |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("holdout", "holdout_cosine_only"):
        c = report[name]["counts"]
        lines.append(
            f"| {name} | {c['true_positive']} | {c['false_negative']} | "
            f"{c['false_positive']} | {c['true_negative']} |"
        )
    lines += ["", "## Every held-out error", ""]
    for case in report["holdout"]["cases"]:
        if case["classification"] in ("false_positive", "false_negative"):
            lines += [
                f"- **{case['id']} — {case['classification']}**. {case['reason']}",
                f"  Reference: {case['reference']}",
                f"  Candidate: {case['candidate']}",
            ]
    lines += [
        "",
        "Negation counts cannot resolve scope or antonyms. Lexical similarity can reject "
        "valid paraphrases. Use task-specific assertions or a calibrated judge for those contracts.",
        "",
        f"Development SHA-256 {report['development_sha256']}",
        f"Holdout SHA-256 {report['holdout_sha256']}",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", type=Path, default=Path("demo/datasets"))
    parser.add_argument("--output", type=Path, default=Path("data/calibration"))
    args = parser.parse_args()
    report = calibration(args.datasets)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.output / "report.md").write_text(render(report))
    print(render(report))


if __name__ == "__main__":
    main()
