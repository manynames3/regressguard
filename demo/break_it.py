"""Break a copy of the fictional prompt and keep the failure in the normal DB."""

import copy
from pathlib import Path

from regressguard.reporting import markdown
from regressguard.runner import run
from regressguard.storage import Store, data_dir
from regressguard.suites import load_suite, prompt_text

if __name__ == "__main__":
    try:
        root = Path.cwd()
        suite = copy.deepcopy(load_suite(root / "suites/ticket-classifier.yml"))
        text = prompt_text(suite, root).replace(
            "Return JSON only with category and priority. No extra fields.\n", ""
        )
        suite.feature.prompt_version = "v2-deliberately-broken"
        report = run(suite, root, Store(), "latest", template=text)
        print(markdown(report))
        print(f"Alert log: {data_dir() / 'alerts.jsonl'}")
        raise SystemExit(report["exit_code"])
    except (ValueError, KeyError) as exc:
        print(f"Setup error: {exc}")
        raise SystemExit(2)
