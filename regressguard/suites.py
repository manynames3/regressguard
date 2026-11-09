"""Validated, portable suite definitions. Paths are relative to the project root."""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import regex
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Check(Strict):
    type: Literal[
        "exact_match", "contains", "regex", "json_schema", "semantic_similarity", "llm_judge"
    ]
    expected: str | None = None
    keywords: list[str] = Field(default_factory=list)
    mode: Literal["all", "any"] = "all"
    case_sensitive: bool = True
    pattern: str | None = None
    schema_: dict | None = Field(default=None, alias="schema")
    reference: str | None = None
    threshold: float = Field(default=0.8, ge=0, le=1)
    preserve_facts: bool = True
    rubric: str | None = None
    rubric_version: str = "v1"

    @model_validator(mode="after")
    def validate_check(self):
        required = {
            "exact_match": self.expected is not None,
            "contains": bool(self.keywords) and all(self.keywords),
            "regex": self.pattern is not None,
            "json_schema": self.schema_ is not None,
            "semantic_similarity": bool(self.reference),
            "llm_judge": bool(self.rubric),
        }
        if not required[self.type]:
            raise ValueError(f"Missing configuration for {self.type}")
        if self.type == "regex":
            try:
                regex.compile(self.pattern)
            except regex.error as exc:
                raise ValueError("Invalid regex pattern") from exc
        if self.type == "json_schema":
            try:
                Draft202012Validator.check_schema(self.schema_)
            except SchemaError as exc:
                raise ValueError("Invalid JSON schema") from exc

            def local_refs(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in ("$ref", "$dynamicRef") and not value.startswith("#"):
                            raise ValueError("Only local JSON schema references are allowed")
                        local_refs(value)
                elif isinstance(node, list):
                    for item in node:
                        local_refs(item)

            local_refs(self.schema_)
        return self


class Case(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    input: str = Field(max_length=20000)
    expected_behavior: str
    severity: Literal["critical", "standard"] = "standard"
    checks: list[Check] = Field(min_length=1, max_length=20)


class Feature(Strict):
    prompt: str
    prompt_version: str
    model: str
    generation: dict[str, float | int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_generation(self):
        if set(self.generation) - {"temperature", "max_tokens", "top_p", "seed"}:
            raise ValueError("Unsupported generation parameter")
        if not 0 <= self.generation.get("temperature", 0) <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if not 1 <= self.generation.get("max_tokens", 120) <= 8192:
            raise ValueError("max_tokens must be between 1 and 8192")
        if not 0 < self.generation.get("top_p", 1) <= 1:
            raise ValueError("top_p must be in (0,1]")
        return self


class Policy(Strict):
    aggregate_drop_points: float = Field(default=5, ge=0, le=100)


class Suite(Strict):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    data_label: str
    feature: Feature
    policy: Policy = Field(default_factory=Policy)
    cases: list[Case] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case IDs")
        return self


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_suite(path):
    path = Path(path)
    if path.stat().st_size > 1_000_000:
        raise ValueError("Suite exceeds 1 MB")
    return Suite.model_validate(yaml.load(path.read_text(), Loader=UniqueLoader))


def prompt_text(suite, root):
    root = Path(root).resolve()
    path = (root / suite.feature.prompt).resolve()
    if not path.is_relative_to(root / "prompts") or not path.is_file():
        raise ValueError("Prompt must be a regular file under prompts/")
    if path.stat().st_size > 100_000:
        raise ValueError("Prompt exceeds 100 KB")
    text = path.read_bytes().decode()
    if "{{input}}" not in text or re.search(r"{{(?!input}}).*?}}", text):
        raise ValueError("Prompt requires only the literal {{input}} placeholder")
    return text


def discover(root):
    suites = {}
    for path in sorted((Path(root) / "suites").glob("*.y*ml")):
        suite = load_suite(path)
        prompt_text(suite, root)
        if suite.id in suites:
            raise ValueError(f"Duplicate suite ID: {suite.id}")
        suites[suite.id] = (suite, path)
    return suites
