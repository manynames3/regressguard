from fastapi.testclient import TestClient

from api.app import app


def test_api_and_html(monkeypatch, root):
    monkeypatch.setattr("api.app.ROOT", root)
    monkeypatch.setenv("REGRESSGUARD_SEED_BASELINES", "1")
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert len(client.get("/api/suites").json()) == 2
        response = client.post("/api/runs", json={"suite_id": "ticket-classifier"})
        assert response.status_code == 200
        result = response.json()
        assert result["verdict"] == "pass"
        assert client.get(f"/api/runs/{result['id']}/report").json() == result
        assert client.post(f"/api/runs/{result['id']}/baseline", json={}).status_code == 200
        assert "Prompt and model change" in client.get(f"/runs/{result['id']}").text
        assert "Run history" in client.get("/").text
        assert client.get("/api/alerts").json() == []
        assert client.get("/api/runs/missing/report").status_code == 404
        assert client.post("/api/runs", json={"suite_id": "../../file"}).status_code == 404
        assert (
            client.post("/api/runs", json={"suite_id": "summarizer", "runs": 0}).status_code == 422
        )
    with TestClient(app) as client:
        assert client.get("/api/suites").json()[1]["baseline"] == result["id"]
