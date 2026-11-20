import pytest

from app.core.lint import lint
from app.core.parser import SpecError

BROKEN = """
openapi: 3.0.3
info: {title: Broken}
paths:
  /items/{itemId}:
    get:
      operationId: getItem
      responses:
        "404": {description: missing}
  /items/{id}/tags:
    parameters:
      - {name: itemId, in: path, required: true, schema: {type: string}}
    get:
      operationId: getItem
      summary: Tags
      requestBody:
        content:
          application/json:
            schema: {type: object}
      responses: {}
"""


def test_bookstore_spec_has_no_errors(spec_v1):
    report = lint(spec_v1)
    assert report["valid"] is True
    assert report["summary"]["error"] == 0


def test_reports_structural_problems():
    report = lint(BROKEN)
    messages = {(i["level"], i["location"], i["message"]) for i in report["issues"]}

    assert report["valid"] is False
    assert ("error", "info.version", "Missing required field info.version") in messages
    assert ("error", "GET /items/{itemId}", "Path parameter 'itemId' is not declared") in messages
    assert ("error", "GET /items/{id}/tags", "Path parameter 'itemId' does not appear in the path template") in messages
    assert ("error", "GET /items/{id}/tags", "No responses defined") in messages
    assert ("warning", "GET /items/{itemId}", "No success (2xx) response defined") in messages
    assert ("warning", "GET /items/{id}/tags", "GET with a request body is discouraged") in messages
    assert ("error", "operationId:getItem", "operationId used 2 times; must be unique") in messages


def test_unresolvable_ref_is_reported():
    spec = """
openapi: 3.0.3
info: {title: T, version: "1"}
paths:
  /a:
    get:
      responses:
        "200": {$ref: "#/components/responses/Missing"}
"""
    report = lint(spec)
    assert any(i["location"] == "$ref" for i in report["issues"])


def test_unloadable_document_raises():
    with pytest.raises(SpecError):
        lint("")
