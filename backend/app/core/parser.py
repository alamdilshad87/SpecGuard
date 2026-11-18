"""Parse OpenAPI 3.x documents into a flat, normalized model.

Everything downstream (docs, diff, test generation) works on this model
instead of the raw document, so $ref handling lives in one place.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

import yaml

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")


class SpecError(ValueError):
    """Raised when a document is not a usable OpenAPI 3.x spec."""


@dataclass
class Parameter:
    name: str
    location: str  # path | query | header | cookie
    required: bool
    schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class RequestBody:
    required: bool
    content_type: str
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class Operation:
    method: str
    path: str
    operation_id: str
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    request_body: RequestBody | None = None
    # status code -> response schema (empty dict when the response has no body)
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    deprecated: bool = False

    @property
    def key(self) -> str:
        return f"{self.method.upper()} {self.path}"


@dataclass
class ParsedSpec:
    title: str
    version: str
    openapi: str
    servers: list[str]
    operations: list[Operation]

    def operation_map(self) -> dict[str, Operation]:
        return {op.key: op for op in self.operations}


def load_document(text: str) -> dict[str, Any]:
    """Load a JSON or YAML document from text."""
    text = text.strip()
    if not text:
        raise SpecError("Spec is empty")
    try:
        doc = json.loads(text) if text.startswith("{") else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SpecError(f"Could not parse spec: {exc}") from exc
    if not isinstance(doc, dict):
        raise SpecError("Spec must be a JSON or YAML object")
    return doc


def _resolve_pointer(doc: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise SpecError(f"Only local $refs are supported, got {ref!r}")
    node: Any = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise SpecError(f"Unresolvable $ref {ref!r}")
        node = node[part]
    return node


def resolve_refs(doc: dict[str, Any], node: Any, _stack: tuple[str, ...] = ()) -> Any:
    """Return a copy of ``node`` with local $refs inlined.

    Recursive schemas are cut off at the point of recursion and replaced
    with ``{"$recursive": ref}`` so callers never loop forever.
    """
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if ref in _stack:
                return {"$recursive": ref}
            target = _resolve_pointer(doc, ref)
            return resolve_refs(doc, copy.deepcopy(target), _stack + (ref,))
        return {k: resolve_refs(doc, v, _stack) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_refs(doc, item, _stack) for item in node]
    return node


def _json_schema(content: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Pick the JSON media type if present, else the first one."""
    if not content:
        return "", {}
    for media_type in ("application/json", "application/problem+json"):
        if media_type in content:
            return media_type, content[media_type].get("schema", {}) or {}
    media_type, media = next(iter(content.items()))
    return media_type, (media or {}).get("schema", {}) or {}


def _make_operation_id(method: str, path: str) -> str:
    cleaned = path.strip("/").replace("/", "_").replace("{", "").replace("}", "") or "root"
    return f"{method}_{cleaned}"


def parse_spec(text: str) -> ParsedSpec:
    raw = load_document(text)
    version = str(raw.get("openapi", ""))
    if not version.startswith("3."):
        if "swagger" in raw:
            raise SpecError("Swagger 2.0 is not supported yet. Convert the spec to OpenAPI 3.x first.")
        raise SpecError("Missing or unsupported 'openapi' version; expected 3.x")
    if not isinstance(raw.get("paths"), dict):
        raise SpecError("Spec has no 'paths' object")

    doc = resolve_refs(raw, raw)
    info = doc.get("info", {}) or {}
    servers = [s.get("url", "") for s in doc.get("servers", []) or [] if isinstance(s, dict)]

    operations: list[Operation] = []
    for path, path_item in doc["paths"].items():
        if not isinstance(path_item, dict):
            continue
        shared_params = path_item.get("parameters", []) or []
        for method in HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue

            # Operation-level parameters override path-level ones with the same name+location.
            merged: dict[tuple[str, str], dict[str, Any]] = {}
            for p in list(shared_params) + list(op.get("parameters", []) or []):
                if isinstance(p, dict) and "name" in p and "in" in p:
                    merged[(p["name"], p["in"])] = p
            params = [
                Parameter(
                    name=p["name"],
                    location=p["in"],
                    required=bool(p.get("required", p["in"] == "path")),
                    schema=p.get("schema", {}) or {},
                    description=p.get("description", ""),
                )
                for p in merged.values()
            ]

            body = None
            rb = op.get("requestBody")
            if isinstance(rb, dict):
                content_type, schema = _json_schema(rb.get("content", {}) or {})
                body = RequestBody(required=bool(rb.get("required", False)), content_type=content_type, schema=schema)

            responses: dict[str, dict[str, Any]] = {}
            for code, resp in (op.get("responses", {}) or {}).items():
                if isinstance(resp, dict):
                    _, schema = _json_schema(resp.get("content", {}) or {})
                    responses[str(code)] = schema

            operations.append(
                Operation(
                    method=method,
                    path=path,
                    operation_id=op.get("operationId") or _make_operation_id(method, path),
                    summary=op.get("summary", ""),
                    description=op.get("description", ""),
                    tags=list(op.get("tags", []) or []),
                    parameters=params,
                    request_body=body,
                    responses=responses,
                    deprecated=bool(op.get("deprecated", False)),
                )
            )

    return ParsedSpec(
        title=info.get("title", "Untitled API"),
        version=str(info.get("version", "")),
        openapi=version,
        servers=servers,
        operations=operations,
    )
