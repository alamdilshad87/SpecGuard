import httpx

from app.core.parser import parse_spec
from app.core.runner import run_tests, status_matches
from app.core.testgen import generate_tests


def test_generates_all_categories(spec_v1):
    cases = generate_tests(parse_spec(spec_v1))
    names = {c.name for c in cases}
    assert {c.category for c in cases} == {"positive", "negative", "edge"}
    assert "Body missing required field 'title'" in names
    assert "Query param 'limit' above maximum (101)" in names
    assert "Body field 'title' at maxLength (200)" in names
    # Every operation gets a positive test
    assert sum(c.category == "positive" for c in cases) == 4


def test_path_params_are_filled(spec_v1):
    cases = generate_tests(parse_spec(spec_v1))
    assert all("{" not in c.path for c in cases)


def test_status_matching():
    assert status_matches(201, ["201"])
    assert status_matches(204, ["2XX"])
    assert not status_matches(500, ["400", "422"])


def _fake_bookstore(request: httpx.Request) -> httpx.Response:
    """A tiny well-behaved implementation of bookstore v1 for runner tests."""
    if request.url.path == "/books" and request.method == "GET":
        limit = request.url.params.get("limit")
        genre = request.url.params.get("genre")
        if limit is not None and (not limit.isdigit() or not 1 <= int(limit) <= 100):
            return httpx.Response(400)
        if genre is not None and genre not in ("fiction", "science", "history"):
            return httpx.Response(400)
        return httpx.Response(200, json=[])
    if request.url.path == "/books" and request.method == "POST":
        try:
            body = httpx.Response(200, content=request.content).json()
        except Exception:
            return httpx.Response(400)
        ok = (isinstance(body, dict)
              and isinstance(body.get("title"), str) and 1 <= len(body["title"]) <= 200
              and isinstance(body.get("author"), str)
              and (("price" not in body) or (isinstance(body["price"], (int, float)) and body["price"] >= 0))
              and body.get("genre", "fiction") in ("fiction", "science", "history"))
        return httpx.Response(201, json={**body, "id": 1}) if ok else httpx.Response(400)
    if request.url.path.startswith("/books/"):
        book_id = request.url.path.rsplit("/", 1)[1]
        if not book_id.isdigit():
            return httpx.Response(404)
        return httpx.Response(200 if request.method == "GET" else 204)
    return httpx.Response(404)


def test_runner_against_compliant_server(spec_v1):
    cases = generate_tests(parse_spec(spec_v1))
    report = run_tests(cases, "http://bookstore.test", transport=httpx.MockTransport(_fake_bookstore))
    failed = [r["name"] for r in report["results"] if not r["passed"]]
    assert failed == []
    assert report["pass_rate"] == 100.0


def test_runner_reports_connection_errors(spec_v1):
    def broken(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    cases = generate_tests(parse_spec(spec_v1))[:2]
    report = run_tests(cases, "http://down.test", transport=httpx.MockTransport(broken))
    assert report["passed"] == 0
    assert "ConnectError" in report["results"][0]["error"]
