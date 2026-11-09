"""Exercise real loopback HTTP for the compatible client and webhook.

The local server returns scripted fictional responses. It is not an LLM.
This separate integration command leaves the default pytest suite network-free.
"""

import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import httpx

from regressguard.checks import evaluate
from regressguard.providers import chat
from regressguard.runner import run
from regressguard.storage import Store
from regressguard.suites import Check, load_suite


def main():
    received_alerts = []
    received_models = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/alert":
                received_alerts.append(body)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
                return
            assert self.path == "/v1/chat/completions"
            assert self.headers["Authorization"] == "Bearer loopback-only"
            assert set(body) <= {"model", "messages", "temperature", "max_tokens", "top_p", "seed"}
            model = body["model"]
            received_models.append(model)
            if model == "loopback/unauthorized":
                self.send_response(401)
                self.end_headers()
                return
            if model == "loopback/malformed":
                envelope = {"unexpected": "envelope"}
            else:
                text = json.dumps(
                    {
                        "category": "technical",
                        "priority": "normal" if model == "loopback/regressed" else "urgent",
                    }
                )
                if model == "loopback/judge":
                    text = json.dumps({"score": 0.9, "rationale": "Scripted transport fixture."})
                envelope = {
                    "model": model + "-resolved",
                    "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                }
                if model != "loopback/no-usage":
                    envelope["usage"] = {"total_tokens": 12}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(envelope).encode())

    with (
        HTTPServer(("127.0.0.1", 0), Handler) as server,
        tempfile.TemporaryDirectory() as directory,
    ):
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        os.environ.update(
            OPENAI_BASE_URL=base + "/v1",
            OPENAI_API_KEY="loopback-only",
            REGRESSGUARD_PROVIDER="openai",
            REGRESSGUARD_SEMANTIC_BACKEND="tfidf",
            REGRESSGUARD_WEBHOOK_URL=base + "/alert",
            REGRESSGUARD_DATA_DIR=directory,
        )
        try:
            suite = load_suite("suites/ticket-classifier.yml")
            suite.cases = [case for case in suite.cases if case.id == "shared-outage"]
            suite.feature.model = "loopback/healthy"
            store = Store(f"sqlite:///{Path(directory) / 'smoke.db'}")
            reference = run(suite, Path.cwd(), store)
            assert reference["verdict"] == "pass"
            store.promote(reference["id"])
            suite.feature.model = "loopback/regressed"
            candidate = run(suite, Path.cwd(), store, reference["id"])
            assert candidate["exit_code"] == 1
            alert = store.alerts()[0]
            assert received_alerts == [alert["payload"]]
            assert alert["delivery"] == {"local": "delivered", "webhook": "delivered"}
            logged = json.loads((Path(directory) / "alerts.jsonl").read_text())
            assert logged == received_alerts[0]
            assert "loopback-only" not in json.dumps(candidate) + json.dumps(alert)
            response = chat("loopback/no-usage", [], {})
            assert response.tokens_used is None and response.usage_source == "unavailable"
            for model, error in (
                ("loopback/unauthorized", httpx.HTTPStatusError),
                ("loopback/malformed", KeyError),
            ):
                try:
                    chat(model, [], {})
                except error:
                    pass
                else:
                    raise AssertionError(f"{model} should fail")
            os.environ.update(
                REGRESSGUARD_JUDGE_MODEL="loopback/judge", REGRESSGUARD_JUDGE_KEY="loopback-only"
            )
            judge = evaluate(Check(type="llm_judge", rubric="Scripted fixture"), "candidate", None)
            assert judge["status"] == "pass" and judge["tokens_used"] == 12
            assert received_models.count("loopback/healthy") == 3
            assert received_models.count("loopback/regressed") == 3
            print(
                "Loopback HTTP passed: generation, baseline comparison, judge, missing usage, "
                "HTTP 401, malformed envelope and identical webhook/SQL/JSONL payload."
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)


if __name__ == "__main__":
    main()
