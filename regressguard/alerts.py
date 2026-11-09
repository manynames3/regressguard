import json
import os

import httpx

from regressguard.storage import data_dir


def payload(report):
    failing = [
        d
        for d in report["deltas"]
        if d["critical_failure"] or (d["delta_points"] is not None and d["delta_points"] < 0)
    ]
    return {
        "text": f"RegressGuard FAIL · {report['suite_id']} · {report['id']}\n"
        f"{report['reason']}\n"
        f"Before: {json.dumps(report['baseline_target'])}\n"
        f"After: {json.dumps(report['target'])}\n"
        + "\n".join(
            f"{d['id']}: {d['old']}/{d['old_total']} → {d['new']}/{d['total']}" for d in failing
        )
    }


def deliver(store, report, body):
    state = {}
    try:
        with (data_dir() / "alerts.jsonl").open("a") as stream:
            stream.write(json.dumps(body) + "\n")
        state["local"] = "delivered"
    except OSError:
        state["local"] = "error"
    url = os.getenv("REGRESSGUARD_WEBHOOK_URL")
    state["webhook"] = "not_configured"
    if url:
        try:
            response = httpx.post(url, json=body, timeout=5, follow_redirects=False)
            response.raise_for_status()
            state["webhook"] = "delivered"
        except Exception:
            state["webhook"] = "error"
    store.delivery(report["id"], state)
