import argparse
import json
import os
import subprocess
from pathlib import Path

import yaml
from sqlalchemy.exc import SQLAlchemyError

from regressguard.reporting import markdown
from regressguard.runner import run
from regressguard.storage import Store, export_snapshot
from regressguard.suites import load_suite


def main():
    parser = argparse.ArgumentParser(prog="regressguard")
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--suite", required=True)
    execute.add_argument("--baseline")
    execute.add_argument("--runs", type=int, default=3)
    execute.add_argument("--json", action="store_true")
    promote = sub.add_parser("baseline")
    promote.add_argument("--run", required=True)
    promote.add_argument("--export")
    gate = sub.add_parser("ci")
    gate.add_argument("--base", required=True)
    gate.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    try:
        if args.command == "ci":
            from regressguard.ci import gate

            code = gate(Path.cwd(), args.base, args.head)
        elif args.command == "baseline":
            report = Store().promote(args.run)
            if args.export:
                Path(args.export).write_text(json.dumps(export_snapshot(report), indent=2) + "\n")
            print(f"Promoted {report['id']} for {report['suite_id']}")
            code = 0
        else:
            report = run(load_suite(args.suite), Path.cwd(), Store(), args.baseline, args.runs)
            print(json.dumps(report, indent=2) if args.json else markdown(report))
            if report["verdict"] == "fail":
                print(f"Alert log: {os.getenv('REGRESSGUARD_DATA_DIR', 'data')}/alerts.jsonl")
            code = report["exit_code"]
    except (
        ValueError,
        KeyError,
        OSError,
        yaml.YAMLError,
        SQLAlchemyError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"RegressGuard setup error: {exc}")
        code = 2
    raise SystemExit(code)
