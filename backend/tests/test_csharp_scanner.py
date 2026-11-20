import json

import httpx
import pytest

from app.core.codescan import Route, csharp_files, scan_sources
from app.services.csharp_scanner import CSharpScannerError, scan_csharp

ROUTES = {"filesScanned": 1, "routes": [
    {"method": "get", "path": "/books/{bookId}", "file": "BooksController.cs", "line": 42,
     "handler": "BooksController.Get", "doc": "Get a single book by id."},
]}


def test_csharp_files_are_routed_to_the_scanner_not_scanned_locally():
    files = {"Api/BooksController.cs": "class X {}", "Api/obj/Gen.cs": "", "app.py": "", "web/bin/x.cs": ""}
    assert csharp_files(files) == {"Api/BooksController.cs": "class X {}"}
    assert scan_sources({"Api/BooksController.cs": '[HttpGet("/x")] void X() {}'}) == []


def test_route_from_dict_normalizes():
    route = Route.from_dict({"method": "GET", "path": "books/{id}/", "file": "B.cs", "line": 3})
    assert (route.key, route.handler, route.doc) == ("GET /books/{id}", "", "")


def test_scan_csharp_posts_files_and_parses_routes():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=ROUTES)

    routes = scan_csharp({"BooksController.cs": "src"}, "http://scanner:8080/", transport=httpx.MockTransport(handler))

    assert seen == {"url": "http://scanner:8080/scan", "body": {"files": {"BooksController.cs": "src"}}}
    assert [(r.key, r.line, r.doc) for r in routes] == [("GET /books/{bookId}", 42, "Get a single book by id.")]


@pytest.mark.parametrize("handler, message", [
    (lambda _: httpx.Response(413, json={}), "HTTP 413"),
    (lambda _: httpx.Response(200, json={"unexpected": True}), "unexpected response"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r)), "unreachable"),
])
def test_scan_csharp_errors_are_wrapped(handler, message):
    with pytest.raises(CSharpScannerError, match=message):
        scan_csharp({"A.cs": ""}, "http://scanner", transport=httpx.MockTransport(handler))
