"""Discover HTTP routes in source code and compare them with a spec (drift detection).

Supported sources:

* Python - FastAPI (``@app.get``, ``APIRouter(prefix=...)``) and Flask (``@app.route``,
  ``Blueprint(url_prefix=...)``), parsed with the ``ast`` module.
* JavaScript / TypeScript - Express-style ``router.get('/path', ...)`` calls, matched with
  a regex that skips common HTTP clients such as ``axios``.
* C# - ASP.NET Core controllers and minimal APIs. These are analysed with Roslyn by the
  separate .NET scanner service (``scanner-dotnet/``); this module only routes ``.cs``
  files to it via :func:`csharp_files` and turns its output back into :class:`Route` objects.

Routes and spec operations are matched on their *shape*: ``/books/{book_id}`` in code and
``/books/{bookId}`` in the spec are the same endpoint.
"""
from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from app.core.parser import ParsedSpec

METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
PYTHON_SUFFIXES = {".py"}
JS_SUFFIXES = {".js", ".ts", ".mjs", ".cjs"}
CSHARP_SUFFIXES = {".cs"}
SUPPORTED_SUFFIXES = PYTHON_SUFFIXES | JS_SUFFIXES | CSHARP_SUFFIXES
SKIP_DIRS_CSHARP = {"bin", "obj"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build"}
HTTP_CLIENTS = {"axios", "http", "https", "fetch", "request", "client", "api", "supertest"}


@dataclass
class Route:
    method: str
    path: str
    file: str
    line: int
    handler: str = ""
    doc: str = ""

    @property
    def key(self) -> str:
        return f"{self.method.upper()} {self.path}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"key": self.key}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Route":
        return cls(method=str(data["method"]).lower(), path=normalize_path(str(data["path"])),
                   file=str(data.get("file", "")), line=int(data.get("line", 0)),
                   handler=str(data.get("handler", "")), doc=str(data.get("doc", "")))


def normalize_path(path: str) -> str:
    """Convert framework path params (``<int:id>``, ``:id``) to OpenAPI style ``{id}``."""
    path = re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", path)
    path = re.sub(r"(?<=/):([A-Za-z_]\w*)", r"{\1}", path)
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") if len(path) > 1 else path


def shape(method: str, path: str) -> str:
    """Matching key that ignores parameter names: ``GET /books/{}``."""
    return f"{method.upper()} {re.sub(r'{[^}]*}', '{}', normalize_path(path))}"


def _join(prefix: str, path: str) -> str:
    return normalize_path(prefix.rstrip("/") + "/" + path.lstrip("/") if prefix else path)


def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _router_prefixes(tree: ast.AST) -> dict[str, str]:
    """Map ``router = APIRouter(prefix="/x")`` / ``bp = Blueprint(..., url_prefix="/x")`` names to prefixes."""
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name not in ("APIRouter", "Blueprint"):
            continue
        prefix = next((_const_str(kw.value) or "" for kw in node.value.keywords
                       if kw.arg in ("prefix", "url_prefix")), "")
        for target in node.targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix
    return prefixes


def scan_python(source: str, filename: str) -> list[Route]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    prefixes = _router_prefixes(tree)
    routes: list[Route] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args):
                continue
            path = _const_str(dec.args[0])
            if path is None:
                continue
            owner = dec.func.value.id if isinstance(dec.func.value, ast.Name) else ""
            attr = dec.func.attr
            if attr in METHODS:
                methods = [attr]
            elif attr == "route":  # Flask: methods=[...] defaults to GET
                methods = ["get"]
                for kw in dec.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        methods = [m.lower() for m in map(_const_str, kw.value.elts) if m]
            else:
                continue
            full_path = _join(prefixes.get(owner, ""), path)
            doc = ast.get_docstring(node) or ""
            routes += [Route(m, full_path, filename, node.lineno, node.name, doc) for m in methods]
    return routes


_JS_ROUTE = re.compile(
    r"""(?P<owner>\w+)\s*\.\s*(?P<method>get|post|put|delete|patch|head|options)\s*\(\s*"""
    r"""(?P<q>['"`])(?P<path>/[^'"`]*)(?P=q)""",
    re.IGNORECASE,
)


def scan_js(source: str, filename: str) -> list[Route]:
    routes = []
    for m in _JS_ROUTE.finditer(source):
        if m.group("owner").lower() in HTTP_CLIENTS:
            continue  # outgoing requests, not route definitions
        line = source.count("\n", 0, m.start()) + 1
        routes.append(Route(m.group("method").lower(), normalize_path(m.group("path")), filename, line))
    return routes


def is_scannable(filename: str) -> bool:
    p = PurePosixPath(filename.replace("\\", "/"))
    skip = SKIP_DIRS | SKIP_DIRS_CSHARP if p.suffix in CSHARP_SUFFIXES else SKIP_DIRS
    return p.suffix in SUPPORTED_SUFFIXES and not skip.intersection(p.parts)


def csharp_files(files: dict[str, str]) -> dict[str, str]:
    """The ``.cs`` files that should be sent to the .NET scanner."""
    return {name: text for name, text in files.items()
            if PurePosixPath(name).suffix in CSHARP_SUFFIXES and is_scannable(name)}


def scan_sources(files: dict[str, str]) -> list[Route]:
    """Scan Python and JS/TS files in ``{filename: source}``; C# files are skipped here."""
    routes: list[Route] = []
    for filename in sorted(files):
        suffix = PurePosixPath(filename).suffix
        if not is_scannable(filename) or suffix in CSHARP_SUFFIXES:
            continue
        scanner = scan_python if suffix in PYTHON_SUFFIXES else scan_js
        routes += scanner(files[filename], filename)
    return routes


def compare_with_spec(routes: list[Route], spec: ParsedSpec) -> dict[str, Any]:
    spec_ops = {shape(op.method, op.path): op for op in spec.operations}
    code_routes: dict[str, Route] = {}
    for route in routes:
        code_routes.setdefault(shape(route.method, route.path), route)

    matched = [
        {"operation": spec_ops[k].key, "route": code_routes[k].to_dict()}
        for k in sorted(spec_ops.keys() & code_routes.keys())
    ]
    undocumented = [code_routes[k].to_dict() for k in sorted(code_routes.keys() - spec_ops.keys())]
    unimplemented = [
        {"operation": spec_ops[k].key, "operation_id": spec_ops[k].operation_id}
        for k in sorted(spec_ops.keys() - code_routes.keys())
    ]
    return {
        "in_sync": not undocumented and not unimplemented,
        "summary": {"matched": len(matched), "undocumented": len(undocumented), "unimplemented": len(unimplemented)},
        "matched": matched,
        "undocumented_in_spec": undocumented,
        "not_implemented_in_code": unimplemented,
    }
