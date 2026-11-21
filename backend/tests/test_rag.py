import json

import httpx
import pytest

from app.core.codescan import scan_sources
from app.core.parser import parse_spec
from app.core.rag import BM25Index, LLMConfig, answer, chunks_from_routes, chunks_from_spec, tokenize
from tests.conftest import EXAMPLES


def _index(spec_text: str) -> BM25Index:
    return BM25Index(chunks_from_spec(parse_spec(spec_text)))


def test_tokenize_splits_identifiers_and_drops_stopwords():
    assert tokenize("How do I get bookId by_genre?") == ["get", "book", "id", "genre"]


def test_retrieval_ranks_the_right_operation_first(spec_v1):
    index = _index(spec_v1)
    assert index.search("delete a book")[0].chunk.id == "op:DELETE /books/{bookId}"
    assert index.search("create a new book")[0].chunk.id == "op:POST /books"
    assert index.search("xyzzy") == []


def test_code_docstrings_become_chunks():
    routes = scan_sources({"mock_bookstore.py": (EXAMPLES / "mock_bookstore.py").read_text()})
    routes[0].doc = "Returns every book in the catalogue."
    chunks = chunks_from_routes(routes)
    assert len(chunks) == 1 and chunks[0].source == "code"


def test_extractive_answer_without_llm(spec_v1):
    result = answer(_index(spec_v1), "delete a book")
    assert result["mode"] == "extractive"
    assert result["sources"][0]["id"] == "op:DELETE /books/{bookId}"


def test_llm_answer_uses_openai_compatible_api(spec_v1):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Send DELETE [op:DELETE /books/{bookId}]"}}]})

    llm = LLMConfig(base_url="http://llm.test/v1", api_key="k", model="m")
    result = answer(_index(spec_v1), "delete a book", llm=llm, transport=httpx.MockTransport(handler))

    assert result["mode"] == "llm"
    assert result["answer"].startswith("Send DELETE")
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "m"
    assert "[op:DELETE /books/{bookId}]" in seen["body"]["messages"][1]["content"]


def test_llm_failure_falls_back_to_extractive(spec_v1):
    llm = LLMConfig(base_url="http://llm.test/v1", model="m")
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    assert answer(_index(spec_v1), "delete a book", llm=llm, transport=transport)["mode"] == "extractive"


def test_reciprocal_rank_fusion_rewards_agreement():
    from app.core.rag import Chunk, Hit, reciprocal_rank_fusion

    a, b, c = (Chunk(x, "operation", x, x) for x in "abc")
    keyword = [Hit(a, 9.0), Hit(b, 5.0)]
    semantic = [Hit(b, 0.9), Hit(c, 0.8)]

    fused = reciprocal_rank_fusion([keyword, semantic], k=60, limit=3)

    assert [h.chunk.id for h in fused] == ["b", "a", "c"]  # b appears in both lists
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert reciprocal_rank_fusion([[], []]) == []
