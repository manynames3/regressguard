import copy
import os
from pathlib import Path

from sqlalchemy import JSON, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from regressguard.comparison import score
from regressguard.suites import digest


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    suite: Mapped[str] = mapped_column(String(120), index=True)
    timestamp: Mapped[str] = mapped_column(String(40), index=True)
    report: Mapped[dict] = mapped_column(JSON)


class Baseline(Base):
    __tablename__ = "baselines"
    suite: Mapped[str] = mapped_column(String(120), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36))


class Alert(Base):
    __tablename__ = "alerts"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    delivery: Mapped[dict] = mapped_column(JSON)


def data_dir():
    path = Path(os.getenv("REGRESSGUARD_DATA_DIR", "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


class Store:
    def __init__(self, url=None):
        url = url or os.getenv("DATABASE_URL") or f"sqlite:///{data_dir() / 'regressguard.db'}"
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30}
            if url.startswith("sqlite")
            else {},
        )
        Base.metadata.create_all(self.engine)

    def get(self, run_id):
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            if not run:
                raise KeyError("Run not found")
            return copy.deepcopy(run.report)

    def latest(self, suite):
        with Session(self.engine) as session:
            pointer = session.get(Baseline, suite)
            if not pointer:
                raise KeyError("No promoted baseline; collect and promote a reference run first")
            return self.get(pointer.run_id)

    def save(self, report, payload=None):
        with Session(self.engine) as session, session.begin():
            row = session.get(Run, report["id"])
            if row and row.report.get("status") == "complete":
                raise ValueError("Completed runs are immutable")
            session.merge(
                Run(
                    id=report["id"],
                    suite=report["suite_id"],
                    timestamp=report["timestamp"],
                    report=report,
                )
            )
            if payload is not None and session.get(Alert, report["id"]) is None:
                session.add(Alert(run_id=report["id"], payload=payload, delivery={}))

    def list_runs(self, suite=None, limit=50, offset=0):
        with Session(self.engine) as session:
            query = select(Run).order_by(Run.timestamp.desc(), Run.id.desc())
            if suite:
                query = query.where(Run.suite == suite)
            return [row.report for row in session.scalars(query.limit(limit).offset(offset))]

    def promote(self, run_id):
        report = self.get(run_id)
        if report["status"] != "complete" or report["verdict"] not in ("pass", "warn"):
            raise ValueError("Only completed, nonfailing runs can become baselines")
        with Session(self.engine) as session, session.begin():
            session.merge(Baseline(suite=report["suite_id"], run_id=run_id))
        return report

    def alerts(self, limit=50, offset=0):
        with Session(self.engine) as session:
            return [
                {"run_id": a.run_id, "payload": a.payload, "delivery": a.delivery}
                for a in session.scalars(
                    select(Alert).order_by(Alert.run_id).limit(limit).offset(offset)
                )
            ]

    def delivery(self, run_id, state):
        with Session(self.engine) as session, session.begin():
            session.get(Alert, run_id).delivery = state

    def import_snapshot(self, snapshot):
        report = validate_snapshot(snapshot)
        try:
            existing = self.get(report["id"])
        except KeyError:
            self.save(report)
        else:
            if export_snapshot(existing) != snapshot:
                raise ValueError("Run ID collision")
        self.promote(report["id"])
        return report


def export_snapshot(report):
    report = copy.deepcopy(report)
    for case in report["cases"]:
        case.pop("samples", None)
    report.pop("prompt_diff", None)
    return {"schema_version": 1, "report": report, "sha256": digest(report)}


def validate_snapshot(snapshot):
    from regressguard.suites import Suite

    report = snapshot["report"]
    if snapshot["schema_version"] != 1 or snapshot["sha256"] != digest(report):
        raise ValueError("Snapshot schema/hash mismatch")
    suite = Suite.model_validate(report["suite"])
    import hashlib
    import uuid

    uuid.UUID(report["id"])
    if report["status"] != "complete" or report["suite_id"] != suite.id:
        raise ValueError("Snapshot must contain a completed matching suite")
    if type(report["runs"]) is not int or not 1 <= report["runs"] <= 20:
        raise ValueError("Invalid repetition count")
    definition = report["contract"]
    # Preserve the serialized contract of historical evaluator versions.
    expected_cases = sorted(report["suite"]["cases"], key=lambda c: c["id"])
    if (
        definition["suite_id"] != suite.id
        or definition["cases"] != expected_cases
        or definition["runs"] != report["runs"]
        or definition["policy"] != suite.policy.model_dump()
    ):
        raise ValueError("Snapshot suite/contract mismatch")
    if report["prompt_hash"] != hashlib.sha256(report["prompt_text"].encode()).hexdigest():
        raise ValueError("Snapshot prompt hash mismatch")
    if report["target"] != {
        "prompt_version": suite.feature.prompt_version,
        "model": suite.feature.model,
        "generation": suite.feature.generation,
    }:
        raise ValueError("Snapshot target mismatch")
    cases = report["cases"]
    if {c["id"] for c in cases} != {c.id for c in suite.cases} or len(cases) != len(suite.cases):
        raise ValueError("Snapshot cases mismatch")
    if report["contract_hash"] != digest(report["contract"]):
        raise ValueError("Snapshot contract mismatch")
    for case in cases:
        if type(case["total"]) is not int or case["total"] != report["runs"]:
            raise ValueError("Invalid attempt counts")
        if type(case["passed"]) is not int or not 0 <= case["passed"] <= case["total"]:
            raise ValueError("Invalid pass counts")
        original = next(c for c in suite.cases if c.id == case["id"])
        if case["severity"] != original.severity:
            raise ValueError("Severity mismatch")
        if original.severity == "critical" and case["passed"] != case["total"]:
            raise ValueError("Critical baseline failure")
    if report["aggregate_score"] != float(score(cases)) or report["verdict"] not in (
        "pass",
        "warn",
    ):
        raise ValueError("Snapshot score/verdict mismatch")
    return report
