import contextlib
import io
import json
import shutil
import subprocess

from regressguard.ci import gate
from regressguard.runner import run
from regressguard.storage import Store
from regressguard.suites import discover


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root).decode().strip()


def repository(root, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("suites", "prompts", "baselines"):
        shutil.copytree(root / name, repo / name)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Regression fixture")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "accepted fixtures")
    return repo, git(repo, "rev-parse", "HEAD")


def quiet_gate(repo, base):
    with contextlib.redirect_stdout(io.StringIO()):
        return gate(repo, base, "HEAD")


def test_ci_broken_prompt_and_edited_answers(root, tmp_path, monkeypatch):
    repo, base = repository(root, tmp_path)
    monkeypatch.setenv("REGRESSGUARD_CI_OUTPUT", str(tmp_path / "ci"))
    prompt = repo / "prompts/classifier/v1.txt"
    prompt.write_text(prompt.read_text().replace("Return JSON only", "Return plain text"))
    suite = repo / "suites/ticket-classifier.yml"
    suite.write_text(suite.read_text().replace("severity: critical", "severity: standard"))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "broken target and weakened checks")
    assert quiet_gate(repo, base) != 0
    output = json.loads((tmp_path / "ci/report.json").read_text())
    assert output["reports"][0]["verdict"] == "fail"
    assert any(d["critical_failure"] for d in output["reports"][0]["deltas"])


def test_ci_clean_docs_and_missing_reference(root, tmp_path, monkeypatch):
    repo, base = repository(root, tmp_path)
    monkeypatch.setenv("REGRESSGUARD_CI_OUTPUT", str(tmp_path / "ci"))
    (repo / "README.md").write_text("docs")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "docs")
    assert quiet_gate(repo, base) == 0
    prompt = repo / "prompts/classifier/v1.txt"
    prompt.write_text(prompt.read_text() + "\nKeep the same format.")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "benign prompt change")
    assert quiet_gate(repo, base) == 0
    (repo / "suites/ticket-classifier.yml").unlink()
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "remove suite")
    assert quiet_gate(repo, base) == 2


def test_ci_baseline_substitution(root, tmp_path, monkeypatch):
    repo, base = repository(root, tmp_path)
    monkeypatch.setenv("REGRESSGUARD_CI_OUTPUT", str(tmp_path / "ci"))
    prompt = repo / "prompts/classifier/v1.txt"
    prompt.write_text("Classify {{input}}")
    snapshot = repo / "baselines/ticket-classifier.json"
    body = json.loads(snapshot.read_text())
    body["report"]["prompt_text"] = prompt.read_text()
    snapshot.write_text(json.dumps(body))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "substitute baseline")
    assert quiet_gate(repo, base) != 0


def test_ci_new_suite_requires_replayed_snapshot(root, tmp_path, monkeypatch):
    repo, base = repository(root, tmp_path)
    monkeypatch.setenv("REGRESSGUARD_CI_OUTPUT", str(tmp_path / "ci"))
    path = repo / "suites/summarizer.yml"
    path.write_text(path.read_text().replace("id: summarizer", "id: new-summary", 1))
    (repo / "suites/ticket-classifier.yml").touch()
    from regressguard.storage import export_snapshot

    suite = discover(repo)["new-summary"][0]
    report = run(suite, repo, Store())
    (repo / "baselines/new-summary.json").write_text(json.dumps(export_snapshot(report)))
    # Keep the old suite as well.
    shutil.copy(root / "suites/summarizer.yml", repo / "suites/old-summary.yml")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "new suite with evidence")
    assert quiet_gate(repo, base) == 0


def test_base_evaluator_scores_candidate_outputs(root, tmp_path, monkeypatch):
    repo, _ = repository(root, tmp_path)
    monkeypatch.setenv("REGRESSGUARD_CI_OUTPUT", str(tmp_path / "ci"))
    for name in ("regressguard", "demo"):
        shutil.copytree(root / name, repo / name, ignore=shutil.ignore_patterns("__pycache__"))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "accepted evaluator")
    base = git(repo, "rev-parse", "HEAD")
    prompt = repo / "prompts/classifier/v1.txt"
    prompt.write_text("Classify {{input}}")
    (repo / "regressguard/checks.py").write_text("# proposed evaluator implementation change")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "prompt and evaluator change")
    assert quiet_gate(repo, base) == 1
    result = json.loads((tmp_path / "ci/report.json").read_text())
    assert result["reports"][0]["scorer_revision"] == "accepted-base"


def test_workflow_contract(root):
    import yaml

    from regressguard.suites import UniqueLoader

    workflow = yaml.load(
        (root / ".github/workflows/regression-gate.yml").read_text(), Loader=UniqueLoader
    )
    jobs = workflow["jobs"]
    assert "postgres" in jobs["postgres"]["services"]
    steps = jobs["gate"]["steps"]
    assert any("regressguard ci" in step.get("run", "") for step in steps)
    assert any(step.get("if") == "always()" for step in steps)
    assert jobs["gate"]["name"] == "RegressGuard gate"
