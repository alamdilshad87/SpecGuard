import io
import zipfile

from app.config import settings
from app.core.codescan import Route
from app.routers import insights
from app.services.csharp_scanner import CSharpScannerError
from tests.conftest import EXAMPLES

DOCUMENTED_APP = '''
from fastapi import FastAPI
app = FastAPI()

@app.get("/books")
def list_books():
    """Books are returned sorted by publication year, newest first."""

@app.post("/books")
def create_book():
    pass

@app.get("/books/{book_id}")
def get_book(book_id: int):
    pass

@app.delete("/books/{book_id}")
def delete_book(book_id: int):
    pass
'''


def _version(client, spec: str, label: str = "v1") -> dict:
    project = client.post("/projects", json={"name": f"Bookstore {label}"}).json()
    return client.post(f"/projects/{project['id']}/versions", json={"label": label, "content": spec}).json()


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def test_lint_endpoints(client, spec_v1):
    version = _version(client, spec_v1)
    assert client.get(f"/versions/{version['id']}/lint").json()["valid"] is True

    raw = client.post("/analyze/lint", json={"content": "openapi: 3.0.0\ninfo: {}\npaths: {}"}).json()
    assert raw["valid"] is False
    assert client.post("/analyze/lint", json={"content": "[1, 2"}).status_code == 422


def test_scan_reports_drift_and_is_stored(client, spec_v2):
    version = _version(client, spec_v2, "v2")
    source = (EXAMPLES / "mock_bookstore.py").read_bytes()

    response = client.post(f"/versions/{version['id']}/scans",
                           files=[("files", ("mock_bookstore.py", source, "text/x-python"))])
    assert response.status_code == 201
    scan = response.json()
    assert scan["in_sync"] is False
    assert scan["report"]["summary"] == {"matched": 3, "undocumented": 1, "unimplemented": 1}

    history = client.get(f"/versions/{version['id']}/scans").json()
    assert [s["id"] for s in history] == [scan["id"]]


def test_scan_accepts_zip_and_skips_unsupported_files(client, spec_v1):
    version = _version(client, spec_v1)
    archive = _zip({"src/app.py": DOCUMENTED_APP, "src/README.md": "docs", "node_modules/x.js": "router.get('/x')"})

    scan = client.post(f"/versions/{version['id']}/scans",
                       files=[("files", ("src.zip", archive, "application/zip"))]).json()
    assert scan["files_scanned"] == 1
    assert scan["in_sync"] is True


def test_scan_rejects_empty_and_oversized_uploads(client, spec_v1, monkeypatch):
    version = _version(client, spec_v1)
    url = f"/versions/{version['id']}/scans"

    assert client.post(url, files=[("files", ("notes.txt", b"hi", "text/plain"))]).status_code == 422
    assert client.post(url, files=[("files", ("bad.zip", b"not a zip", "application/zip"))]).status_code == 422

    monkeypatch.setattr(insights, "MAX_SOURCE_BYTES", 10)
    big = client.post(url, files=[("files", ("app.py", DOCUMENTED_APP.encode(), "text/x-python"))])
    assert big.status_code == 413


def test_ask_uses_spec_and_scanned_docstrings(client, spec_v1):
    version = _version(client, spec_v1)
    url = f"/versions/{version['id']}/ask"

    before = client.post(url, json={"question": "how do I delete a book?"}).json()
    assert before["mode"] == "extractive"
    assert before["sources"][0]["id"] == "op:DELETE /books/{bookId}"

    client.post(f"/versions/{version['id']}/scans", files=[("files", ("app.py", DOCUMENTED_APP.encode(), "text/x-python"))])
    after = client.post(url, json={"question": "what order are books sorted in?", "use_llm": False}).json()
    assert after["sources"][0]["source"] == "code"
    assert "publication year" in after["answer"]

    assert client.post(url, json={"question": ""}).status_code == 422
    assert client.post("/versions/9999/ask", json={"question": "x"}).status_code == 404


# ---------------------------------------------------------------- C# via the .NET scanner

CS_CONTROLLER = (EXAMPLES / "BookstoreApi" / "BooksController.cs").read_bytes()
CS_ROUTES = [
    Route("get", "/books", "BooksController.cs", 24, "BooksController.List", "List books, optionally filtered by genre."),
    Route("post", "/books", "BooksController.cs", 32, "BooksController.Create", ""),
    Route("get", "/books/{bookId}", "BooksController.cs", 41, "BooksController.Get", ""),
    Route("delete", "/books/{bookId}", "BooksController.cs", 46, "BooksController.Delete", ""),
]


def _cs_upload(*extra):
    return [("files", ("BooksController.cs", CS_CONTROLLER, "text/plain")), *extra]


def test_csharp_files_are_scanned_by_the_dotnet_service(client, spec_v2, monkeypatch):
    calls = []

    def fake_scan(files, base_url, timeout):
        calls.append((sorted(files), base_url))
        return CS_ROUTES

    monkeypatch.setattr(settings, "csharp_scanner_url", "http://scanner:8080")
    monkeypatch.setattr(insights, "scan_csharp", fake_scan)
    version = _version(client, spec_v2, "v2")

    scan = client.post(f"/versions/{version['id']}/scans", files=_cs_upload()).json()

    assert calls == [(["BooksController.cs"], "http://scanner:8080")]
    assert scan["report"]["summary"] == {"matched": 3, "undocumented": 1, "unimplemented": 1}
    assert scan["report"]["warnings"] == []

    answer = client.post(f"/versions/{version['id']}/ask", json={"question": "filter books by genre", "use_llm": False}).json()
    assert any(s["source"] == "code" for s in answer["sources"])


def test_mixed_upload_survives_scanner_outage(client, spec_v1, monkeypatch):
    def failing_scan(files, base_url, timeout):
        raise CSharpScannerError("C# scanner unreachable: ConnectError")

    monkeypatch.setattr(settings, "csharp_scanner_url", "http://scanner:8080")
    monkeypatch.setattr(insights, "scan_csharp", failing_scan)
    version = _version(client, spec_v1)

    scan = client.post(f"/versions/{version['id']}/scans",
                       files=_cs_upload(("files", ("app.py", DOCUMENTED_APP.encode(), "text/x-python")))).json()

    assert scan["in_sync"] is True  # the Python routes alone cover the spec
    assert scan["report"]["warnings"] == ["Skipped 1 C# file(s): C# scanner unreachable: ConnectError"]


def test_csharp_only_upload_needs_a_working_scanner(client, spec_v1, monkeypatch):
    version = _version(client, spec_v1)
    url = f"/versions/{version['id']}/scans"

    monkeypatch.setattr(settings, "csharp_scanner_url", "")
    assert client.post(url, files=_cs_upload()).status_code == 503

    def failing_scan(files, base_url, timeout):
        raise CSharpScannerError("C# scanner returned HTTP 500")

    monkeypatch.setattr(settings, "csharp_scanner_url", "http://scanner:8080")
    monkeypatch.setattr(insights, "scan_csharp", failing_scan)
    response = client.post(url, files=_cs_upload())
    assert response.status_code == 502
    assert response.json()["detail"] == "C# scanner returned HTTP 500"
