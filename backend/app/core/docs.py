"""Generate Markdown documentation with request/response examples."""
from __future__ import annotations

import json
from collections import defaultdict

from app.core.parser import Operation, ParsedSpec
from app.core.schema import describe, example_for, flatten


def _example_path(op: Operation) -> str:
    path = op.path
    for p in op.parameters:
        if p.location == "path":
            path = path.replace("{" + p.name + "}", str(example_for(p.schema)))
    query = [f"{p.name}={example_for(p.schema)}" for p in op.parameters if p.location == "query" and p.required]
    return path + ("?" + "&".join(query) if query else "")


def _fields_table(schema: dict) -> list[str]:
    schema = flatten(schema)
    props = schema.get("properties", {})
    if not props:
        return []
    required = set(schema.get("required", []))
    lines = ["| Field | Type | Required | Notes |", "|---|---|---|---|"]
    for name, sub in props.items():
        notes = []
        for key in ("minimum", "maximum", "minLength", "maxLength", "pattern"):
            if key in sub:
                notes.append(f"{key}: {sub[key]}")
        if sub.get("description"):
            notes.append(sub["description"])
        lines.append(f"| `{name}` | {describe(sub)} | {'yes' if name in required else 'no'} | {'; '.join(notes)} |")
    return lines


def _operation_section(op: Operation, base_url: str) -> list[str]:
    title = op.summary or op.operation_id
    out = [f"### {title}", "", f"`{op.method.upper()} {op.path}`" + ("  **(deprecated)**" if op.deprecated else ""), ""]
    if op.description:
        out += [op.description, ""]

    if op.parameters:
        out += ["**Parameters**", "", "| Name | In | Type | Required |", "|---|---|---|---|"]
        for p in op.parameters:
            out.append(f"| `{p.name}` | {p.location} | {describe(p.schema)} | {'yes' if p.required else 'no'} |")
        out.append("")

    curl = f"curl -X {op.method.upper()} '{base_url}{_example_path(op)}'"
    if op.request_body:
        body = example_for(op.request_body.schema)
        out += [f"**Request body** ({op.request_body.content_type or 'application/json'}"
                f"{', required' if op.request_body.required else ''})", ""]
        out += _fields_table(op.request_body.schema) + [""]
        out += ["```json", json.dumps(body, indent=2), "```", ""]
        curl += f" \\\n  -H 'Content-Type: application/json' \\\n  -d '{json.dumps(body)}'"

    out += ["**Example**", "", "```bash", curl, "```", ""]

    if op.responses:
        out += ["**Responses**", ""]
        for code, schema in sorted(op.responses.items()):
            if schema:
                out += [f"- `{code}`: {describe(schema)}", "", "```json",
                        json.dumps(example_for(schema), indent=2), "```", ""]
            else:
                out.append(f"- `{code}`: no body")
        out.append("")
    return out


def generate_markdown(spec: ParsedSpec) -> str:
    base_url = spec.servers[0].rstrip("/") if spec.servers else "http://localhost"
    lines = [f"# {spec.title}", "", f"Version {spec.version} · OpenAPI {spec.openapi} · "
             f"{len(spec.operations)} operations", ""]

    by_tag: dict[str, list[Operation]] = defaultdict(list)
    for op in spec.operations:
        by_tag[op.tags[0] if op.tags else "default"].append(op)

    lines += ["## Endpoints", ""]
    for tag, ops in by_tag.items():
        lines.append(f"- **{tag}**: " + ", ".join(f"`{o.key}`" for o in ops))
    lines.append("")

    for tag, ops in by_tag.items():
        lines += [f"## {tag}", ""]
        for op in ops:
            lines += _operation_section(op, base_url)
    return "\n".join(lines).rstrip() + "\n"
