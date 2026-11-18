"""Detect breaking changes between two versions of an API spec.

Requests and responses follow opposite rules: a server may start *accepting*
more (new optional fields, wider enums) and *returning* more (new response
fields) without breaking clients, but not the reverse.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.core.parser import Operation, ParsedSpec
from app.core.schema import flatten, schema_type

Severity = Literal["breaking", "warning", "info"]
Direction = Literal["request", "response"]


@dataclass
class Change:
    severity: Severity
    rule: str
    operation: str
    location: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class _Collector:
    def __init__(self) -> None:
        self.changes: list[Change] = []

    def add(self, severity: Severity, rule: str, op: str, location: str, message: str) -> None:
        self.changes.append(Change(severity, rule, op, location, message))


# Constraints where a larger value accepts less (min*) or more (max*)
_LOWER_BOUNDS = ("minimum", "minLength", "minItems", "exclusiveMinimum")
_UPPER_BOUNDS = ("maximum", "maxLength", "maxItems", "exclusiveMaximum")


def _compare_schema(c: _Collector, op: str, where: str, old: dict[str, Any], new: dict[str, Any],
                    direction: Direction, depth: int = 0) -> None:
    old, new = flatten(old), flatten(new)
    if depth > 8 or not old or not new:
        return

    old_t, new_t = schema_type(old), schema_type(new)
    if old_t != new_t and "any" not in (old_t, new_t):
        c.add("breaking", "type-changed", op, where, f"Type changed from {old_t} to {new_t}")
        return

    # Enums
    old_enum, new_enum = old.get("enum"), new.get("enum")
    if old_enum and new_enum:
        removed = [v for v in old_enum if v not in new_enum]
        added = [v for v in new_enum if v not in old_enum]
        if removed:
            sev: Severity = "breaking" if direction == "request" else "warning"
            c.add(sev, "enum-value-removed", op, where, f"Enum values removed: {', '.join(map(str, removed))}")
        if added:
            sev = "warning" if direction == "response" else "info"
            c.add(sev, "enum-value-added", op, where, f"Enum values added: {', '.join(map(str, added))}")
    elif new_enum and not old_enum and direction == "request":
        c.add("breaking", "enum-added", op, where, "Value is now restricted to an enum")

    # Numeric/length constraints only matter for what clients send
    if direction == "request":
        for key in _LOWER_BOUNDS:
            o, n = old.get(key), new.get(key)
            if isinstance(n, (int, float)) and not isinstance(n, bool) and (o is None or n > o):
                c.add("breaking", "constraint-tightened", op, where, f"{key} raised from {o} to {n}")
        for key in _UPPER_BOUNDS:
            o, n = old.get(key), new.get(key)
            if isinstance(n, (int, float)) and not isinstance(n, bool) and (o is None or n < o):
                c.add("breaking", "constraint-tightened", op, where, f"{key} lowered from {o} to {n}")
        if new.get("pattern") and new.get("pattern") != old.get("pattern"):
            c.add("warning", "pattern-changed", op, where, f"Pattern changed to {new['pattern']!r}")

    if old_t == "object":
        old_props, new_props = old.get("properties", {}), new.get("properties", {})
        old_req, new_req = set(old.get("required", [])), set(new.get("required", []))
        for name in old_props:
            field = f"{where}.{name}"
            if name not in new_props:
                if direction == "response":
                    c.add("breaking", "response-field-removed", op, field, "Field removed from response")
                else:
                    c.add("warning", "request-field-removed", op, field,
                          "Field removed from request; clients still sending it may be rejected")
                continue
            if direction == "request" and name in new_req and name not in old_req:
                c.add("breaking", "field-became-required", op, field, "Optional field is now required")
            if direction == "response" and name in old_req and name not in new_req:
                c.add("warning", "response-field-optional", op, field, "Field may now be missing from responses")
            _compare_schema(c, op, field, old_props[name], new_props[name], direction, depth + 1)
        for name in new_props:
            if name in old_props:
                continue
            field = f"{where}.{name}"
            if direction == "request" and name in new_req:
                c.add("breaking", "required-field-added", op, field, "New required field in request")
            elif direction == "request":
                c.add("info", "optional-field-added", op, field, "New optional field in request")
            else:
                c.add("info", "response-field-added", op, field, "New field in response")

    if old_t == "array":
        _compare_schema(c, op, f"{where}[]", old.get("items", {}), new.get("items", {}), direction, depth + 1)


def _compare_operation(c: _Collector, old: Operation, new: Operation) -> None:
    op = new.key
    if new.deprecated and not old.deprecated:
        c.add("info", "operation-deprecated", op, "operation", "Operation marked as deprecated")

    old_params = {(p.name, p.location): p for p in old.parameters}
    new_params = {(p.name, p.location): p for p in new.parameters}
    for key, p in old_params.items():
        where = f"{p.location}.{p.name}"
        if key not in new_params:
            sev: Severity = "breaking" if p.location == "path" else "warning"
            c.add(sev, "parameter-removed", op, where, "Parameter removed")
            continue
        np = new_params[key]
        if np.required and not p.required:
            c.add("breaking", "parameter-became-required", op, where, "Optional parameter is now required")
        _compare_schema(c, op, where, p.schema, np.schema, "request")
    for key, p in new_params.items():
        if key in old_params:
            continue
        where = f"{p.location}.{p.name}"
        if p.required:
            c.add("breaking", "required-parameter-added", op, where, "New required parameter")
        else:
            c.add("info", "optional-parameter-added", op, where, "New optional parameter")

    if old.request_body and new.request_body:
        if new.request_body.required and not old.request_body.required:
            c.add("breaking", "body-became-required", op, "body", "Request body is now required")
        if old.request_body.content_type and new.request_body.content_type \
                and old.request_body.content_type != new.request_body.content_type:
            c.add("breaking", "content-type-changed", op, "body",
                  f"Content type changed from {old.request_body.content_type} to {new.request_body.content_type}")
        _compare_schema(c, op, "body", old.request_body.schema, new.request_body.schema, "request")
    elif new.request_body and not old.request_body and new.request_body.required:
        c.add("breaking", "body-added", op, "body", "Operation now requires a request body")
    elif old.request_body and not new.request_body:
        c.add("warning", "body-removed", op, "body", "Request body removed")

    for code, old_schema in old.responses.items():
        if code not in new.responses:
            sev = "breaking" if code.startswith("2") else "info"
            c.add(sev, "response-removed", op, f"response.{code}", f"Response {code} removed")
            continue
        _compare_schema(c, op, f"response.{code}", old_schema, new.responses[code], "response")
    for code in new.responses:
        if code not in old.responses:
            c.add("info", "response-added", op, f"response.{code}", f"Response {code} added")


def compare(old: ParsedSpec, new: ParsedSpec) -> dict[str, Any]:
    c = _Collector()
    old_ops, new_ops = old.operation_map(), new.operation_map()

    for key, op in old_ops.items():
        if key not in new_ops:
            c.add("breaking", "operation-removed", key, "operation", "Operation removed")
        else:
            _compare_operation(c, op, new_ops[key])
    for key in new_ops:
        if key not in old_ops:
            c.add("info", "operation-added", key, "operation", "Operation added")

    order = {"breaking": 0, "warning": 1, "info": 2}
    changes = sorted(c.changes, key=lambda ch: (order[ch.severity], ch.operation, ch.location))
    counts = {s: sum(1 for ch in changes if ch.severity == s) for s in order}
    return {
        "from_version": old.version,
        "to_version": new.version,
        "summary": counts,
        "is_breaking": counts["breaking"] > 0,
        "changes": [ch.to_dict() for ch in changes],
    }
