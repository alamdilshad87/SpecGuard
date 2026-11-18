"""Generate positive, negative and edge-case API tests from a parsed spec."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core.parser import Operation, ParsedSpec
from app.core.schema import example_for, flatten, schema_type, wrong_type_value

Category = Literal["positive", "negative", "edge"]

CLIENT_ERROR = ["400", "404", "409", "422"]


@dataclass
class TestCase:
    id: str
    name: str
    category: Category
    operation: str
    method: str
    path: str
    query: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    expected_status: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _success_codes(op: Operation) -> list[str]:
    codes = sorted(c for c in op.responses if c.startswith("2"))
    return codes or ["2XX"]


def _error_codes(op: Operation) -> list[str]:
    # Documented 4xx codes, plus 400/422 which frameworks use for validation errors.
    documented = {c for c in op.responses if c.startswith("4")}
    return sorted(documented | {"400", "422"}) if documented else CLIENT_ERROR


class _Builder:
    def __init__(self, op: Operation) -> None:
        self.op = op
        self.path_values = {p.name: example_for(p.schema) for p in op.parameters if p.location == "path"}
        self.query = {p.name: example_for(p.schema) for p in op.parameters if p.location == "query" and p.required}
        self.headers = {p.name: str(example_for(p.schema)) for p in op.parameters
                        if p.location == "header" and p.required}
        self.body = example_for(op.request_body.schema) if op.request_body else None
        self.cases: list[TestCase] = []

    def path(self, overrides: dict[str, Any] | None = None) -> str:
        values = {**self.path_values, **(overrides or {})}
        result = self.op.path
        for name, value in values.items():
            result = result.replace("{" + name + "}", str(value))
        return result

    def add(self, name: str, category: Category, expected: list[str], *, path: str | None = None,
            query: dict | None = None, body: Any = "__default__", headers: dict | None = None) -> None:
        self.cases.append(TestCase(
            id=f"{self.op.operation_id}-{len(self.cases) + 1}",
            name=name,
            category=category,
            operation=self.op.key,
            method=self.op.method.upper(),
            path=path if path is not None else self.path(),
            query=self.query if query is None else query,
            headers=self.headers if headers is None else headers,
            body=copy.deepcopy(self.body) if body == "__default__" else body,
            expected_status=expected,
        ))


def _bound_cases(b: _Builder, label: str, schema: dict[str, Any], apply) -> None:
    """Add edge cases at the limits of a numeric or string schema.

    ``apply(value)`` returns the kwargs for ``_Builder.add`` with the value set.
    """
    schema = flatten(schema)
    t = schema_type(schema)
    ok, bad = _success_codes(b.op), _error_codes(b.op)
    if t in ("integer", "number"):
        step = 1 if t == "integer" else 0.01
        if isinstance(schema.get("minimum"), (int, float)):
            low = schema["minimum"]
            b.add(f"{label} at minimum ({low})", "edge", ok, **apply(low))
            b.add(f"{label} below minimum ({low - step})", "negative", bad, **apply(low - step))
        if isinstance(schema.get("maximum"), (int, float)):
            high = schema["maximum"]
            b.add(f"{label} at maximum ({high})", "edge", ok, **apply(high))
            b.add(f"{label} above maximum ({high + step})", "negative", bad, **apply(high + step))
    elif t == "string" and "enum" not in schema:
        if isinstance(schema.get("maxLength"), int):
            n = schema["maxLength"]
            b.add(f"{label} at maxLength ({n})", "edge", ok, **apply("a" * n))
            b.add(f"{label} over maxLength ({n + 1})", "negative", bad, **apply("a" * (n + 1)))
        if isinstance(schema.get("minLength"), int) and schema["minLength"] > 0:
            n = schema["minLength"]
            b.add(f"{label} under minLength ({n - 1})", "negative", bad, **apply("a" * (n - 1)))
    if schema.get("enum"):
        b.add(f"{label} not in enum", "negative", bad, **apply("__not_a_valid_value__"))


def generate_for_operation(op: Operation) -> list[TestCase]:
    b = _Builder(op)
    ok, bad = _success_codes(op), _error_codes(op)

    b.add("Valid request returns success", "positive", ok)

    # Path parameters
    for p in op.parameters:
        if p.location != "path":
            continue
        wrong = wrong_type_value(p.schema)
        if schema_type(p.schema) in ("integer", "number") and wrong is not None:
            b.add(f"Path param '{p.name}' with wrong type", "negative", bad, path=b.path({p.name: wrong}))

    # Query parameters
    for p in op.parameters:
        if p.location != "query":
            continue
        if p.required:
            q = {k: v for k, v in b.query.items() if k != p.name}
            b.add(f"Missing required query param '{p.name}'", "negative", bad, query=q)
        wrong = wrong_type_value(p.schema)
        if schema_type(p.schema) in ("integer", "number", "boolean") and wrong is not None:
            b.add(f"Query param '{p.name}' with wrong type", "negative", bad, query={**b.query, p.name: wrong})
        _bound_cases(b, f"Query param '{p.name}'", p.schema,
                     lambda v, name=p.name: {"query": {**b.query, name: v}})

    # Request body
    if op.request_body:
        schema = flatten(op.request_body.schema)
        if op.request_body.required:
            b.add("Missing request body", "negative", bad, body=None)
        if schema_type(schema) == "object" and isinstance(b.body, dict):
            for name in schema.get("required", []):
                body = {k: v for k, v in b.body.items() if k != name}
                b.add(f"Body missing required field '{name}'", "negative", bad, body=body)
            for name, sub in schema.get("properties", {}).items():
                wrong = wrong_type_value(sub)
                if wrong is not None:
                    b.add(f"Body field '{name}' with wrong type", "negative", bad, body={**b.body, name: wrong})
                _bound_cases(b, f"Body field '{name}'", sub,
                             lambda v, name=name: {"body": {**b.body, name: v}})

    return b.cases


def generate_tests(spec: ParsedSpec) -> list[TestCase]:
    cases: list[TestCase] = []
    for op in spec.operations:
        cases.extend(generate_for_operation(op))
    return cases
