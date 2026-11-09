"""Fictional, reproducible model behaviors for exercising release decisions.

Scenarios select a model variant, keeping inputs, checks and policy identical.
The provider sees the model ID and input, never case IDs or expected answers.
"""

import argparse
import json
from pathlib import Path

from regressguard.runner import run
from regressguard.storage import Store
from regressguard.suites import load_suite


def execute_scenarios(root, store, runs=3):
    suite = load_suite(root / "suites/ticket-classifier.yml")
    reference = run(suite, root, store, runs=runs)
    store.promote(reference["id"])
    results = {"reference": reference}
    suite.feature.model = "mock/ticket-classifier-intermittent"
    results["intermittent"] = run(suite, root, store, reference["id"], runs)
    suite.feature.model = "mock/ticket-classifier-tradeoff-base"
    reference = run(suite, root, store, runs=runs)
    store.promote(reference["id"])
    results["tradeoff_reference"] = reference
    suite.feature.model = "mock/ticket-classifier-tradeoff-candidate"
    results["masked_critical"] = run(suite, root, store, reference["id"], runs)
    # Restore the healthy reference so the demo doesn't leave a weakened baseline selected.
    store.promote(results["reference"]["id"])
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/scenarios.json")
    args = parser.parse_args()
    reports = execute_scenarios(Path.cwd(), Store())
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reports, indent=2) + "\n")
    for name, report in reports.items():
        print(
            f"{name}: {report['verdict']} · {report['aggregate_score']:.2f} · "
            f"delta {report['aggregate_delta']} · run {report['id']}"
        )
    intermittent = reports["intermittent"]
    masked = reports["masked_critical"]
    if (
        intermittent["verdict"] != "fail"
        or masked["verdict"] != "fail"
        or masked["aggregate_delta"] <= 0
    ):
        raise SystemExit("Scenario verification failed")
    print(f"Both regressions blocked. Full evidence: {path}")


if __name__ == "__main__":
    main()
