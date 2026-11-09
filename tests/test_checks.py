import pytest

from regressguard.checks import Semantic, evaluate, strict_json
from regressguard.providers import Response
from regressguard.suites import Check


@pytest.mark.parametrize(
    "config,good,bad",
    [
        ({"type": "exact_match", "expected": "yes"}, "yes", "yes "),
        ({"type": "contains", "keywords": ["one", "two"]}, "one two", "one"),
        ({"type": "regex", "pattern": "^hello"}, "hello world", "no hello"),
        (
            {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "required": ["x"],
                    "additionalProperties": False,
                    "properties": {"x": {"const": 1}},
                },
            },
            '{"x":1}',
            '{"x":2}',
        ),
        (
            {"type": "semantic_similarity", "reference": "red cat", "threshold": 0.8},
            "red cat",
            "red",
        ),
    ],
)
def test_checks(config, good, bad):
    check = Check.model_validate(config)
    semantic = Semantic(["red cat"])
    assert evaluate(check, good, semantic)["status"] == "pass"
    assert evaluate(check, bad, semantic)["status"] == "fail"


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', 'prefix {"x":1}', "```{}"])
def test_strict_json(text):
    with pytest.raises(ValueError):
        strict_json(text)


def test_judge(monkeypatch):
    check = Check(type="llm_judge", rubric="accurate")
    assert evaluate(check, "answer", None)["status"] == "skipped"
    monkeypatch.setenv("REGRESSGUARD_JUDGE_MODEL", "test-model")
    monkeypatch.setenv("REGRESSGUARD_JUDGE_KEY", "test-key")
    for body, expected in [
        ('{"score":0.9,"rationale":"ok"}', "pass"),
        ('{"score":0.1,"rationale":"wrong"}', "fail"),
        ('{"score":2,"rationale":"wrong"}', "error"),
        ("broken", "error"),
    ]:
        monkeypatch.setattr(
            "regressguard.checks.chat", lambda *a, **k: Response(body, "test-model", 4, "provider")
        )
        assert evaluate(check, "answer", None)["status"] == expected


def test_semantic_edge_cases(monkeypatch):
    semantic = Semantic(["red cat"])
    assert semantic.score("", "red cat") == 0
    assert semantic.score("red cat", "red cat") == pytest.approx(1)
    monkeypatch.setenv("REGRESSGUARD_SEMANTIC_BACKEND", "embeddings")
    with pytest.raises(ValueError):
        Semantic(["red cat"])


def test_regex_timeout():
    check = Check(type="regex", pattern="(a+)+$")
    assert evaluate(check, "a" * 100000 + "!", None)["status"] == "error"


@pytest.mark.parametrize(
    "text",
    [
        '{"amount":1e999}',
        '{"amount":-1e999}',
        '{"nested":[1,{"amount":1e999}]}',
    ],
)
def test_json_numeric_overflow_is_quality_failure(text):
    check = Check.model_validate({"type": "json_schema", "schema": {"type": "object"}})
    with pytest.raises(ValueError, match="finite"):
        strict_json(text)
    assert evaluate(check, text, None)["status"] == "fail"


@pytest.mark.parametrize(
    "candidate",
    [
        "The refund was never approved.",
        "The refund was not approved.",
        "The refund was approved for 120 accounts.",
    ],
)
def test_semantic_contradiction_guards(candidate):
    reference = "The refund was approved."
    semantic = Semantic([reference])
    check = Check(type="semantic_similarity", reference=reference, threshold=0.8)
    result = evaluate(check, candidate, semantic)
    assert result["status"] == "fail"
    assert result["guard_failures"]


def test_tfidf_unknown_words_reduce_similarity():
    semantic = Semantic(["red cat"])
    assert semantic.score("red cat galaxy spacecraft", "red cat") < 0.8


def test_tfidf_new_reference_uses_same_feature_space():
    semantic = Semantic(["red cat"])
    assert semantic.score("new satellite", "new satellite") == pytest.approx(1)
