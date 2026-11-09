"""Gate against reviewed base-tree evidence, independent of runtime database caches."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from regressguard.reporting import markdown
from regressguard.runner import EVALUATOR_VERSION, run
from regressguard.storage import Store, validate_snapshot
from regressguard.suites import discover, prompt_text


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


def tree(root, ref, destination):
    git(root, "rev-parse", "--verify", ref + "^{commit}")
    names = git(root, "ls-tree", "-rz", ref).split(b"\0")
    # Materialize evaluation files and the reviewed base evaluator into an isolated directory.
    for entry in names:
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, _, oid = metadata.split()
        path = Path(os.fsdecode(raw_path))
        if path.parts[0] not in ("suites", "prompts", "baselines", "regressguard", "demo"):
            continue
        if mode not in (b"100644", b"100755") or path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid evaluation tree entry")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git(root, "cat-file", "blob", oid.decode()))


def verify_proposed(suite, root, store):
    snapshot = json.loads((root / "baselines" / f"{suite.id}.json").read_text())
    reference = validate_snapshot(snapshot)
    report = run(suite, root, store, runs=reference["runs"])
    if reference["contract_hash"] != report["contract_hash"]:
        raise ValueError("Proposed baseline contract differs from suite")
    if (
        reference["prompt_text"] != prompt_text(suite, root)
        or reference["target"] != report["target"]
    ):
        raise ValueError("Proposed baseline must replay the proposed target")

    def counts(r):
        return sorted((c["id"], c["passed"], c["total"]) for c in r["cases"])

    if counts(reference) != counts(report) or report["exit_code"]:
        raise ValueError("Proposed baseline replay failed")
    return report


def accepted_replay(suite, new_root, old_root, reference):
    """Generate with candidate code, score the outputs with the reviewed base evaluator."""
    candidate_store = Store(f"sqlite:///{new_root / 'candidate.db'}")
    observations = run(suite, new_root, candidate_store, runs=reference["runs"])
    if any(s.get("error") for c in observations["cases"] for s in c["samples"]):
        return observations, observations
    accepted_definition = suite.model_dump(by_alias=True)
    accepted_definition["cases"] = reference["contract"]["cases"]
    package = {
        "suite": accepted_definition,
        "reference": reference,
        "template": prompt_text(suite, new_root),
        "observations": observations,
    }
    source = Path(__file__).with_name("replay.py").read_text()
    env = {**os.environ, "PYTHONPATH": str(old_root)}
    process = subprocess.run(
        [sys.executable, "-c", source],
        cwd=old_root,
        input=json.dumps(package),
        text=True,
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )
    if process.returncode:
        raise ValueError("Accepted evaluator replay failed: " + process.stderr[-1000:])
    report = json.loads(process.stdout)
    report["git"] = observations["git"]
    report["scorer_revision"] = "accepted-base"
    return report, observations


def gate(root, base, head):
    # A local invocation has the same offline contract as the PR job.
    os.environ["REGRESSGUARD_PROVIDER"] = "mock"
    os.environ["REGRESSGUARD_SEMANTIC_BACKEND"] = "tfidf"
    os.environ.pop("REGRESSGUARD_JUDGE_MODEL", None)
    reports, errors = [], []
    base_sha = git(root, "rev-parse", "--verify", base + "^{commit}").decode().strip()
    head_sha = git(root, "rev-parse", "--verify", head + "^{commit}").decode().strip()
    changed = {
        os.fsdecode(p)
        for p in git(root, "diff", "--name-only", "--no-renames", "-z", base_sha, head_sha).split(
            b"\0"
        )
        if p
    }
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        old_root, new_root = temp / "base", temp / "head"
        old_root.mkdir()
        new_root.mkdir()
        tree(root, base_sha, old_root)
        tree(root, head_sha, new_root)
        old, new = discover(old_root), discover(new_root)
        all_suites = changed and any(
            p.startswith(("regressguard/", "demo/", ".github/workflows/"))
            or p in ("uv.lock", "pyproject.toml")
            for p in changed
        )
        known = set()
        selected = set()
        for suite_id in old.keys() | new.keys():
            deps = {f"baselines/{suite_id}.json"}
            for catalog, location in ((old, old_root), (new, new_root)):
                if suite_id in catalog:
                    suite, path = catalog[suite_id]
                    deps |= {str(path.relative_to(location)), suite.feature.prompt}
            known |= deps
            if all_suites or deps & changed:
                selected.add(suite_id)
        for path in changed:
            if path.startswith(("prompts/", "suites/", "baselines/")) and path not in known:
                errors.append(f"Unmapped evaluation file: {path}")
        store = Store(f"sqlite:///{temp / 'ci.db'}")
        for suite_id in sorted(selected):
            try:
                if suite_id not in new:
                    raise ValueError("Suite removal requires a reviewed retirement policy")
                candidate = new[suite_id][0]
                if suite_id in old:
                    accepted = old[suite_id][0].model_copy(deep=True)
                    snapshot = json.loads((old_root / "baselines" / f"{suite_id}.json").read_text())
                    reference = store.import_snapshot(snapshot)
                    accepted.feature = candidate.feature
                    if (old_root / "regressguard/runner.py").is_file():
                        report, proposed = accepted_replay(accepted, new_root, old_root, reference)
                    else:
                        report = run(accepted, new_root, store, reference["id"], reference["runs"])
                    reports.append(report)
                    if (old_root / "regressguard/runner.py").is_file() and changed & {
                        "regressguard/checks.py",
                        "regressguard/comparison.py",
                    }:
                        reports.append(proposed)
                    # The old lane always executes even when new checks/answers were edited.
                    if (
                        old[suite_id][0].model_dump(exclude={"feature"})
                        != candidate.model_dump(exclude={"feature"})
                        or f"baselines/{suite_id}.json" in changed
                        or reference["contract"]["evaluator_version"] != EVALUATOR_VERSION
                    ):
                        reports.append(verify_proposed(candidate, new_root, store))
                else:
                    reports.append(verify_proposed(candidate, new_root, store))
            except Exception as exc:
                errors.append(f"{suite_id}: {type(exc).__name__}: {str(exc)[:300]}")
    summary = f"# RegressGuard gate\nBase {base_sha}\nTested {head_sha}\n\n"
    summary += "\n\n".join(markdown(r) for r in reports)
    summary += "\n\n" + "\n".join("ERROR: " + e for e in errors)
    if not selected and not errors:
        summary += "No affected suites."
    print(summary)
    output = Path(os.getenv("REGRESSGUARD_CI_OUTPUT", "data/ci"))
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(
            {
                "base": base_sha,
                "tested": head_sha,
                "pr_head": os.getenv("PR_HEAD_SHA"),
                "reports": reports,
                "errors": errors,
            },
            indent=2,
        )
    )
    (output / "summary.md").write_text(summary)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(summary[:500_000])
    return (
        2
        if errors or any(r["exit_code"] == 2 for r in reports)
        else int(any(r["exit_code"] == 1 for r in reports))
    )
