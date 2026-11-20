"""Structural lint for OpenAPI 3.x documents.

``parse_spec`` only rejects documents it cannot use at all. The linter goes further and
reports problems that make a spec misleading or hard to consume: undeclared path
parameters, duplicate operationIds, operations without a success response, and so on.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.core.parser import HTTP_METHODS, SpecError, load_document, resolve_refs

Level = Literal["error", "warning"]


@dataclass
class Issue:
    level: Level
    location: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _params(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in node.get("parameters", []) or [] if isinstance(p, dict)]


def lint_document(doc: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []

    def add(level: Level, location: str, message: str) -> None:
        issues.append(Issue(level, location, message))

    if not str(doc.get("openapi", "")).startswith("3."):
        add("error", "openapi", "Only OpenAPI 3.x is supported")
    info = doc.get("info") or {}
    for key in ("title", "version"):
        if not info.get(key):
            add("error", f"info.{key}", f"Missing required field info.{key}")
    if not isinstance(doc.get("paths"), dict) or not doc["paths"]:
        add("error", "paths", "Spec defines no paths")
        return issues

    try:
        resolved = resolve_refs(doc, doc)
    except SpecError as exc:
        add("error", "$ref", str(exc))
        return issues

    operation_ids: Counter[str] = Counter()
    for path, item in resolved["paths"].items():
        if not path.startswith("/"):
            add("error", f"paths.{path}", "Path must start with '/'")
        if not isinstance(item, dict):
            continue
        template_params = set(re.findall(r"\{([^}]+)\}", path))
        shared = _params(item)
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            loc = f"{method.upper()} {path}"
            params = shared + _params(op)

            if op.get("operationId"):
                operation_ids[op["operationId"]] += 1
            else:
                add("warning", loc, "Missing operationId")
            if not op.get("summary") and not op.get("description"):
                add("warning", loc, "Missing summary and description")

            declared = {p.get("name") for p in params if p.get("in") == "path"}
            for name in sorted(template_params - declared):
                add("error", loc, f"Path parameter '{name}' is not declared")
            for name in sorted(n for n in declared - template_params if n):
                add("error", loc, f"Path parameter '{name}' does not appear in the path template")
            for p in params:
                if p.get("in") == "path" and p.get("required") is not True:
                    add("error", loc, f"Path parameter '{p.get('name')}' must be required: true")

            responses = op.get("responses") or {}
            if not responses:
                add("error", loc, "No responses defined")
            elif not any(str(code).startswith("2") or code == "default" for code in responses):
                add("warning", loc, "No success (2xx) response defined")
            if method in ("get", "delete", "head") and op.get("requestBody"):
                add("warning", loc, f"{method.upper()} with a request body is discouraged")

    for operation_id, count in operation_ids.items():
        if count > 1:
            add("error", f"operationId:{operation_id}", f"operationId used {count} times; must be unique")
    return issues


def lint(text: str) -> dict[str, Any]:
    """Lint spec text. Documents that cannot be loaded at all raise ``SpecError``."""
    issues = lint_document(load_document(text))
    errors = sum(1 for i in issues if i.level == "error")
    return {
        "valid": errors == 0,
        "summary": {"error": errors, "warning": len(issues) - errors},
        "issues": [i.to_dict() for i in issues],
    }
