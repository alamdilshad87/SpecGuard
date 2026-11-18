from app.core.diff import compare
from app.core.parser import parse_spec


def _rules(result, severity):
    return {(c["rule"], c["operation"], c["location"]) for c in result["changes"] if c["severity"] == severity}


def test_identical_specs_have_no_changes(spec_v1):
    result = compare(parse_spec(spec_v1), parse_spec(spec_v1))
    assert result["changes"] == []
    assert result["is_breaking"] is False


def test_detects_breaking_changes(spec_v1, spec_v2):
    result = compare(parse_spec(spec_v1), parse_spec(spec_v2))
    breaking = _rules(result, "breaking")
    assert ("operation-removed", "DELETE /books/{bookId}", "operation") in breaking
    assert ("required-parameter-added", "GET /books", "query.storeId") in breaking
    assert ("constraint-tightened", "GET /books", "query.limit") in breaking
    assert ("enum-value-removed", "GET /books", "query.genre") in breaking
    assert ("type-changed", "GET /books/{bookId}", "path.bookId") in breaking
    assert ("required-field-added", "POST /books", "body.isbn") in breaking
    assert ("response-field-removed", "POST /books", "response.201.price") in breaking
    assert result["is_breaking"] is True


def test_additions_are_not_breaking(spec_v1, spec_v2):
    info = _rules(compare(parse_spec(spec_v1), parse_spec(spec_v2)), "info")
    assert ("operation-added", "GET /authors", "operation") in info
    assert ("response-field-added", "POST /books", "response.201.isbn") in info


def test_direction_matters_for_enums():
    base = """
openapi: 3.0.0
info: {{title: T, version: "1"}}
paths:
  /x:
    post:
      requestBody:
        content:
          application/json:
            schema: {{type: object, properties: {{kind: {{type: string, enum: {req}}}}}}}
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {{type: object, properties: {{kind: {{type: string, enum: {resp}}}}}}}
"""
    old = parse_spec(base.format(req="[a, b]", resp="[a, b]"))
    new = parse_spec(base.format(req="[a, b, c]", resp="[a, b, c]"))
    result = compare(old, new)
    by_location = {c["location"]: c["severity"] for c in result["changes"]}
    # Accepting a new value is safe; returning a new value may surprise strict clients.
    assert by_location["body.kind"] == "info"
    assert by_location["response.200.kind"] == "warning"
    assert result["is_breaking"] is False
