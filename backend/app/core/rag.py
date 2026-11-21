"""Retrieval-augmented question answering over a spec (and optionally its source code).

Each operation becomes a chunk describing its parameters, request body and responses;
route docstrings from scanned code become extra chunks. Chunks are ranked with BM25.

``answer`` then either

* sends the top chunks to an LLM (any OpenAI-compatible ``/chat/completions`` endpoint)
  with instructions to answer only from them and cite chunk ids, or
* returns an extractive answer built from the best chunk when no LLM is configured or
  the call fails, so the feature always works offline.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.codescan import Route
from app.core.parser import Operation, ParsedSpec
from app.core.schema import describe, flatten

SYSTEM_PROMPT = (
    "You answer questions about an HTTP API using ONLY the documentation excerpts provided. "
    "If the excerpts do not contain the answer, say you don't know. "
    "Cite the ids of the excerpts you used in square brackets, e.g. [op:GET /books]."
)

_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i if in is it of on or that the this to what "
    "when where which who why with you your".split()
)


# ---------------------------------------------------------------- chunks

@dataclass
class Chunk:
    id: str
    source: str  # operation | code
    title: str
    text: str


def _fields(schema: dict[str, Any]) -> list[str]:
    schema = flatten(schema)
    if schema.get("type") == "array" or "items" in schema:
        schema = flatten(schema.get("items", {}))
    required = set(schema.get("required", []))
    return [
        f"{name} ({describe(sub)}{', required' if name in required else ''})"
        + (f": {sub['description']}" if sub.get("description") else "")
        for name, sub in (schema.get("properties") or {}).items()
    ]


def operation_text(op: Operation) -> str:
    lines = [f"{op.key} (operationId {op.operation_id})"]
    if op.summary:
        lines.append(op.summary)
    if op.description:
        lines.append(op.description)
    if op.tags:
        lines.append("Tags: " + ", ".join(op.tags))
    if op.deprecated:
        lines.append("This operation is deprecated.")
    for p in op.parameters:
        req = "required" if p.required else "optional"
        lines.append(f"Parameter {p.name} in {p.location}, {req}, {describe(p.schema)}"
                     + (f": {p.description}" if p.description else ""))
    if op.request_body:
        req = "required" if op.request_body.required else "optional"
        lines.append(f"Request body ({op.request_body.content_type}, {req}) fields: "
                     + (", ".join(_fields(op.request_body.schema)) or "none"))
    for code, schema in op.responses.items():
        fields = _fields(schema)
        lines.append(f"Response {code}" + (f" fields: {', '.join(fields)}" if fields else ""))
    return "\n".join(lines)


def chunks_from_spec(spec: ParsedSpec) -> list[Chunk]:
    return [Chunk(f"op:{op.key}", "operation", op.summary or op.key, operation_text(op))
            for op in spec.operations]


def chunks_from_routes(routes: list[Route]) -> list[Chunk]:
    return [
        Chunk(f"code:{r.file}:{r.line}", "code", f"{r.key} in {r.file}",
              f"{r.key} implemented by {r.handler} in {r.file} line {r.line}\n{r.doc}")
        for r in routes if r.doc
    ]


# ---------------------------------------------------------------- BM25

def tokenize(text: str) -> list[str]:
    """Lowercase word tokens; camelCase and snake_case are split (``bookId`` -> book, id)."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS]


@dataclass
class Hit:
    chunk: Chunk
    score: float


@dataclass
class BM25Index:
    """Okapi BM25 ranking over a fixed list of chunks."""

    chunks: list[Chunk]
    k1: float = 1.5
    b: float = 0.75
    _tf: list[Counter[str]] = field(init=False, repr=False)
    _len: list[int] = field(init=False, repr=False)
    _idf: dict[str, float] = field(init=False, repr=False)
    _avg_len: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        docs = [tokenize(f"{c.title} {c.text}") for c in self.chunks]
        self._tf = [Counter(d) for d in docs]
        self._len = [len(d) for d in docs]
        self._avg_len = (sum(self._len) / len(docs)) if docs else 0.0
        df: Counter[str] = Counter(term for tf in self._tf for term in tf)
        n = len(docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 4) -> list[Hit]:
        terms = tokenize(query)
        scored = []
        for i, tf in enumerate(self._tf):
            norm = self.k1 * (1 - self.b + self.b * self._len[i] / (self._avg_len or 1))
            score = sum(self._idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm) for t in terms if t in tf)
            if score > 0:
                scored.append(Hit(self.chunks[i], score))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]


# ---------------------------------------------------------------- answers

@dataclass
class LLMConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: float = 30.0

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)


def build_prompt(question: str, hits: list[Hit]) -> list[dict[str, str]]:
    context = "\n\n---\n\n".join(f"[{h.chunk.id}]\n{h.chunk.text}" for h in hits)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Documentation excerpts:\n\n{context}\n\nQuestion: {question}"},
    ]


def llm_complete(messages: list[dict[str, str]], config: LLMConfig,
                 transport: httpx.BaseTransport | None = None) -> str:
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    with httpx.Client(timeout=config.timeout, transport=transport) as client:
        resp = client.post(f"{config.base_url.rstrip('/')}/chat/completions", headers=headers,
                           json={"model": config.model, "messages": messages, "max_tokens": 800})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def reciprocal_rank_fusion(rankings: list[list[Hit]], k: int = 60, limit: int = 4) -> list[Hit]:
    """Merge ranked lists by rank, not score: each list adds ``1 / (k + rank)`` per chunk.

    BM25 scores and cosine similarities live on different scales, so adding them directly
    lets one retriever dominate. RRF only uses positions, which makes it robust and
    parameter-light (k=60 is the value from the original paper).
    """
    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk.id] = scores.get(hit.chunk.id, 0.0) + 1.0 / (k + rank)
            chunks[hit.chunk.id] = hit.chunk
    best = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:limit]
    return [Hit(chunks[cid], scores[cid]) for cid in best]


def answer(index: BM25Index, question: str, k: int = 4, llm: LLMConfig | None = None,
           transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """BM25-only convenience wrapper around :func:`answer_from_hits`."""
    return answer_from_hits(question, index.search(question, k), llm, transport)


def answer_from_hits(question: str, hits: list[Hit], llm: LLMConfig | None = None,
                     transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    sources = [{"id": h.chunk.id, "title": h.chunk.title, "source": h.chunk.source,
                "score": round(h.score, 3)} for h in hits]
    if not hits:
        return {"answer": "No relevant documentation found.", "mode": "none", "sources": []}

    if llm is not None and llm.enabled:
        try:
            text = llm_complete(build_prompt(question, hits), llm, transport)
            return {"answer": text, "mode": "llm", "sources": sources}
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            pass  # fall back to the extractive answer below

    best = hits[0].chunk
    return {"answer": f"Most relevant: {best.title}\n\n{best.text}", "mode": "extractive", "sources": sources}
