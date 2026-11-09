import os
from dataclasses import dataclass

import httpx

from demo.mock import generate


@dataclass
class Response:
    text: str
    model: str
    tokens_used: int | None
    usage_source: str
    finish_reason: str | None = None


def chat(model, messages, generation, *, judge=False):
    key_name = "REGRESSGUARD_JUDGE_KEY" if judge else "OPENAI_API_KEY"
    key = os.environ.get(key_name)
    if not key:
        raise ValueError(f"{key_name} is required")
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    response = httpx.post(
        base + "/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": messages, **generation},
        timeout=30,
        follow_redirects=False,
    )
    response.raise_for_status()
    body = response.json()
    choice = body["choices"][0]
    text = choice["message"]["content"]
    if not isinstance(text, str) or not isinstance(body["model"], str):
        raise ValueError("Malformed provider envelope")
    tokens = body.get("usage", {}).get("total_tokens")
    if tokens is not None and (type(tokens) is not int or tokens < 0):
        raise ValueError("Invalid provider usage")
    return Response(
        text,
        body["model"],
        tokens,
        "provider" if tokens is not None else "unavailable",
        choice.get("finish_reason"),
    )


def generate_response(feature, template, text, attempt, provider):
    if provider == "mock":
        output = generate(feature.model, template, text, feature.generation, attempt)
        return Response(
            output,
            feature.model,
            len((template + text + output).split()),
            "mock_whitespace_estimate",
            "stop",
        )
    if provider != "openai":
        raise ValueError("Provider must be mock or openai")
    return chat(
        feature.model,
        [
            {"role": "system", "content": template.replace("{{input}}", "")},
            {"role": "user", "content": text},
        ],
        feature.generation,
    )
