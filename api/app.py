import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from regressguard.runner import run
from regressguard.storage import Store
from regressguard.suites import discover

ROOT = Path(os.getenv("REGRESSGUARD_ROOT", Path.cwd())).resolve()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
run_lock = Lock()


@asynccontextmanager
async def lifespan(app):
    store = Store()
    app.state.store = store
    if os.getenv("REGRESSGUARD_SEED_BASELINES") == "1":
        for path in sorted((ROOT / "baselines").glob("*.json")):
            snapshot = json.loads(path.read_text())
            try:
                store.latest(snapshot["report"]["suite_id"])
            except KeyError:
                store.import_snapshot(snapshot)
    yield
    store.engine.dispose()


app = FastAPI(title="RegressGuard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite_id: str
    baseline: str | None = "latest"
    runs: int = Field(default=3, ge=1, le=20)


def get_run(request, run_id):
    try:
        return request.app.state.store.get(run_id)
    except KeyError:
        raise HTTPException(404, "Run not found")


@app.get("/api/suites")
def suites(request: Request):
    rows = []
    for suite, _ in discover(ROOT).values():
        try:
            baseline = request.app.state.store.latest(suite.id)["id"]
        except KeyError:
            baseline = None
        rows.append(
            {
                "id": suite.id,
                "name": suite.name,
                "cases": len(suite.cases),
                "critical": sum(c.severity == "critical" for c in suite.cases),
                "feature": suite.feature.model_dump(),
                "baseline": baseline,
            }
        )
    return rows


@app.post("/api/runs")
def trigger(body: Trigger, request: Request):
    catalog = discover(ROOT)
    if body.suite_id not in catalog:
        raise HTTPException(404, "Unknown suite ID")
    if not run_lock.acquire(blocking=False):
        raise HTTPException(409, "A run is already executing")
    try:
        try:
            report = run(
                catalog[body.suite_id][0], ROOT, request.app.state.store, body.baseline, body.runs
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse(report, status_code=200 if report["exit_code"] != 2 else 502)
    finally:
        run_lock.release()


@app.get("/api/runs")
def runs(
    request: Request,
    suite: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return request.app.state.store.list_runs(suite, limit, offset)


@app.get("/api/runs/{run_id}/report")
def report(run_id: str, request: Request):
    return get_run(request, run_id)


@app.middleware("http")
async def json_mutations(request: Request, call_next):
    if request.method == "POST" and not request.headers.get("content-type", "").startswith(
        "application/json"
    ):
        return JSONResponse({"detail": "application/json is required"}, status_code=415)
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "Cross-origin mutation is disabled"}, status_code=403)
    return await call_next(request)


@app.post("/api/runs/{run_id}/baseline")
def baseline(run_id: str, request: Request):
    get_run(request, run_id)
    try:
        return request.app.state.store.promote(run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/alerts")
def alerts(request: Request, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return request.app.state.store.alerts(limit, offset)


@app.get("/healthz")
def health(request: Request):
    request.app.state.store.list_runs(limit=1)
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, suite: str | None = None):
    catalog = suites(request)
    chosen = suite or (catalog[0]["id"] if catalog else None)
    history = request.app.state.store.list_runs(chosen)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"suites": catalog, "chosen": chosen, "runs": history},
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(run_id: str, request: Request):
    return templates.TemplateResponse(
        request=request, name="report.html", context={"run": get_run(request, run_id)}
    )
