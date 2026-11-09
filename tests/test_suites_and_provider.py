import httpx
import pytest

from regressguard.providers import chat
from regressguard.suites import Check, load_suite, prompt_text


def test_suite_validation(tmp_path, root):
    path = tmp_path / "bad.yml"
    path.write_text("id: one\nid: two")
    with pytest.raises(ValueError, match="Duplicate"):
        load_suite(path)
    suite = load_suite(root / "suites/ticket-classifier.yml")
    suite.feature.prompt = "../secret"
    with pytest.raises(ValueError):
        prompt_text(suite, root)
    with pytest.raises(ValueError):
        Check.model_validate({"type": "json_schema", "schema": {"$ref": "https://invalid"}})
    with pytest.raises(ValueError):
        Check.model_validate({"type": "contains", "keywords": []})


def test_real_provider_mock_transport(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def transport(request):
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "model": "resolved-model",
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr("regressguard.providers.httpx.post", client.post)
    result = chat("alias", [{"role": "user", "content": "hi"}], {})
    assert result.model == "resolved-model"
    assert result.tokens_used is None

    def bad(request):
        return httpx.Response(401)

    monkeypatch.setattr(
        "regressguard.providers.httpx.post", httpx.Client(transport=httpx.MockTransport(bad)).post
    )
    with pytest.raises(httpx.HTTPStatusError):
        chat("alias", [], {})


def test_generation_parameter_validation(root):
    suite = load_suite(root / "suites/ticket-classifier.yml")
    from regressguard.suites import Suite

    body = suite.model_dump(by_alias=True)
    body["feature"]["generation"]["temperature"] = float("nan")
    with pytest.raises(ValueError):
        Suite.model_validate(body)


@pytest.mark.parametrize(
    "config",
    [
        {"type": "regex", "pattern": "["},
        {"type": "json_schema", "schema": {"type": "not-a-type"}},
    ],
)
def test_bad_checks_are_validation_errors(config):
    with pytest.raises(ValueError):
        Check.model_validate(config)
