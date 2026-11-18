"""Helpers for working with JSON Schema fragments from OpenAPI specs."""
from __future__ import annotations

from typing import Any


def flatten(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Merge ``allOf`` branches into a single object schema.

    ``oneOf``/``anyOf`` are reduced to their first branch, which is enough
    for documentation and for generating one valid example.
    """
    if not schema:
        return {}
    schema = dict(schema)

    if "allOf" in schema:
        merged: dict[str, Any] = {k: v for k, v in schema.items() if k != "allOf"}
        props: dict[str, Any] = dict(merged.get("properties", {}))
        required: list[str] = list(merged.get("required", []))
        for part in schema["allOf"]:
            part = flatten(part)
            props.update(part.get("properties", {}))
            for name in part.get("required", []):
                if name not in required:
                    required.append(name)
            for key, value in part.items():
                if key not in ("properties", "required"):
                    merged.setdefault(key, value)
        merged["properties"] = props
        if required:
            merged["required"] = required
        merged.setdefault("type", "object")
        schema = merged

    for key in ("oneOf", "anyOf"):
        if key in schema and schema[key]:
            first = flatten(schema[key][0])
            rest = {k: v for k, v in schema.items() if k != key}
            return {**first, **rest}

    if "properties" in schema:
        schema["properties"] = {name: flatten(sub) for name, sub in schema["properties"].items()}
    if "items" in schema and isinstance(schema["items"], dict):
        schema["items"] = flatten(schema["items"])
    return schema


def schema_type(schema: dict[str, Any]) -> str:
    schema = flatten(schema)
    if "type" in schema:
        t = schema["type"]
        # OpenAPI 3.1 allows a list of types, e.g. ["string", "null"]
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), "string")
        return str(t)
    if "properties" in schema:
        return "object"
    if "items" in schema:
        return "array"
    if "enum" in schema and schema["enum"]:
        return type(schema["enum"][0]).__name__.replace("str", "string").replace("int", "integer")
    return "any"


def describe(schema: dict[str, Any]) -> str:
    """Short human-readable type, e.g. ``array<integer>`` or ``string (email)``."""
    schema = flatten(schema)
    if "$recursive" in schema:
        return "object (recursive)"
    t = schema_type(schema)
    if t == "array":
        return f"array<{describe(schema.get('items', {}))}>"
    if "enum" in schema:
        return f"{t} enum[{', '.join(map(str, schema['enum']))}]"
    if schema.get("format"):
        return f"{t} ({schema['format']})"
    return t


_FORMAT_EXAMPLES = {
    "email": "user@example.com",
    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "date": "2026-01-01",
    "date-time": "2026-01-01T00:00:00Z",
    "uri": "https://example.com",
    "ipv4": "127.0.0.1",
}


def example_for(schema: dict[str, Any], depth: int = 0) -> Any:
    """Build one value that satisfies ``schema`` (best effort)."""
    schema = flatten(schema)
    if depth > 6 or "$recursive" in schema:
        return None
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if schema.get("enum"):
        return schema["enum"][0]

    t = schema_type(schema)
    if t == "object":
        return {
            name: example_for(sub, depth + 1)
            for name, sub in schema.get("properties", {}).items()
        }
    if t == "array":
        count = max(1, int(schema.get("minItems", 1)))
        return [example_for(schema.get("items", {}), depth + 1) for _ in range(count)]
    if t == "integer":
        low = schema.get("minimum", 1)
        return int(low) if isinstance(low, (int, float)) else 1
    if t == "number":
        low = schema.get("minimum", 1.0)
        return float(low) if isinstance(low, (int, float)) else 1.0
    if t == "boolean":
        return True
    if t == "string":
        if schema.get("format") in _FORMAT_EXAMPLES:
            return _FORMAT_EXAMPLES[schema["format"]]
        min_len = int(schema.get("minLength", 0))
        value = "sample"
        if len(value) < min_len:
            value = value + "x" * (min_len - len(value))
        max_len = schema.get("maxLength")
        if isinstance(max_len, int):
            value = value[:max_len]
        return value
    return "sample"


def wrong_type_value(schema: dict[str, Any]) -> Any:
    """A value of the wrong type, for negative tests."""
    t = schema_type(schema)
    return {"string": 12345, "integer": "not-a-number", "number": "not-a-number",
            "boolean": "not-a-boolean", "array": "not-an-array", "object": "not-an-object"}.get(t, None)
