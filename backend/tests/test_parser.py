import json

import pytest

from app.core.parser import SpecError, parse_spec
from app.core.schema import example_for, flatten


def test_parses_operations_and_merges_path_params(spec_v1):
    spec = parse_spec(spec_v1)
    ops = spec.operation_map()
    assert spec.title == "Bookstore API"
    assert set(ops) == {"GET /books", "POST /books", "GET /books/{bookId}", "DELETE /books/{bookId}"}
    # bookId is declared at path level and must reach both operations
    assert [p.name for p in ops["DELETE /books/{bookId}"].parameters] == ["bookId"]
    assert ops["POST /books"].request_body.required is True


def test_resolves_refs_and_flattens_allof(spec_v1):
    book = flatten(parse_spec(spec_v1).operation_map()["GET /books/{bookId}"].responses["200"])
    assert set(book["required"]) == {"title", "author", "id"}
    assert "price" in book["properties"]


def test_accepts_json_input():
    doc = {"openapi": "3.1.0", "info": {"title": "T", "version": "1"},
           "paths": {"/ping": {"get": {"responses": {"200": {"description": "ok"}}}}}}
    spec = parse_spec(json.dumps(doc))
    assert spec.operations[0].operation_id == "get_ping"


def test_recursive_schema_does_not_loop():
    doc = """
openapi: 3.0.0
info: {title: Tree, version: "1"}
paths:
  /nodes:
    get:
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Node"}
components:
  schemas:
    Node:
      type: object
      properties:
        children:
          type: array
          items: {$ref: "#/components/schemas/Node"}
"""
    schema = parse_spec(doc).operations[0].responses["200"]
    assert example_for(schema) == {"children": [None]}


@pytest.mark.parametrize("text,message", [
    ("", "empty"),
    ("swagger: '2.0'\npaths: {}", "Swagger 2.0"),
    ("openapi: 3.0.0\ninfo: {}", "paths"),
    ("[1, 2]", "object"),
])
def test_rejects_invalid_specs(text, message):
    with pytest.raises(SpecError, match=message):
        parse_spec(text)
