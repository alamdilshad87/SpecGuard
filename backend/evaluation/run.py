"""Retrieval evaluation: how often does each retrieval mode find the right operation?

    cd backend
    python -m evaluation.run                 # real embeddings (downloads bge-small once)
    python -m evaluation.run --json          # machine-readable output
    python -m evaluation.run --embedder hashing   # fast, no model (for smoke tests only)

For every question the expected operation's rank is taken from each mode's top 10:

* recall@k - share of questions whose answer is in the top k
* MRR      - mean reciprocal rank (1/rank, 0 if not in the top 10)

The pipeline mirrors /ask: same chunks, same BM25, same RRF and candidate depth. Vector
search uses exact cosine similarity (what the API does outside PostgreSQL; pgvector's HNSW
index is approximate but exact at this corpus size).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.embeddings import Embedder, FastEmbedEmbedder, HashingEmbedder, cosine
from app.core.parser import parse_spec
from app.core.rag import BM25Index, Chunk, Hit, chunks_from_spec, reciprocal_rank_fusion
from app.services.retrieval import CANDIDATES

DATASET = Path(__file__).with_name("questions.yaml")
MODES = ("bm25", "vector", "hybrid")
DEPTH = 10  # ranks beyond this count as a miss
KS = (1, 3, 5)


@dataclass
class Question:
    q: str
    expected: str  # operation key, e.g. "POST /orders"
    type: str  # keyword | paraphrase

    @property
    def chunk_id(self) -> str:
        return f"op:{self.expected}"


def load_dataset(path: Path = DATASET) -> tuple[list[Chunk], list[Question]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    spec_text = (path.parent / data["spec"]).resolve().read_text(encoding="utf-8")
    questions = [Question(item["q"], item["expected"], item["type"]) for item in data["questions"]]
    return chunks_from_spec(parse_spec(spec_text)), questions


class Retrievers:
    """The three /ask retrieval modes over one fixed corpus, with document vectors cached."""

    def __init__(self, chunks: list[Chunk], embedder: Embedder) -> None:
        self.chunks = chunks
        self.bm25 = BM25Index(chunks)
        self.embedder = embedder
        self.vectors = embedder.embed_documents([f"{c.title}\n{c.text}" for c in chunks])

    def _dense(self, question: str, k: int) -> list[Hit]:
        query = self.embedder.embed_query(question)
        scored = sorted(zip(self.chunks, self.vectors), key=lambda cv: cosine(query, cv[1]), reverse=True)
        return [Hit(c, cosine(query, v)) for c, v in scored[:k]]

    def ranking(self, mode: str, question: str, k: int = DEPTH) -> list[str]:
        if mode == "bm25":
            hits = self.bm25.search(question, k)
        elif mode == "vector":
            hits = self._dense(question, k)
        else:
            hits = reciprocal_rank_fusion([self.bm25.search(question, CANDIDATES),
                                           self._dense(question, CANDIDATES)], limit=k)
        return [h.chunk.id for h in hits]


def rank_of(expected: str, ranking: list[str]) -> int | None:
    """1-based rank of the expected chunk, or None if absent."""
    return ranking.index(expected) + 1 if expected in ranking else None


def metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks) or 1
    out = {f"recall@{k}": sum(1 for r in ranks if r is not None and r <= k) / n for k in KS}
    out["mrr"] = sum(1 / r for r in ranks if r is not None) / n
    return out


def evaluate(embedder: Embedder, path: Path = DATASET) -> dict:
    chunks, questions = load_dataset(path)
    retrievers = Retrievers(chunks, embedder)
    per_question = []
    for question in questions:
        ranks = {mode: rank_of(question.chunk_id, retrievers.ranking(mode, question.q)) for mode in MODES}
        per_question.append({"q": question.q, "type": question.type, "expected": question.expected, "ranks": ranks})

    def summary(rows: list[dict]) -> dict:
        return {mode: metrics([r["ranks"][mode] for r in rows]) for mode in MODES}

    return {
        "embedder": embedder.name,
        "corpus_size": len(chunks),
        "questions": len(questions),
        "overall": summary(per_question),
        "by_type": {t: summary([r for r in per_question if r["type"] == t])
                    for t in sorted({r["type"] for r in per_question})},
        "per_question": per_question,
    }


def to_markdown(result: dict) -> str:
    counts = {t: sum(1 for r in result["per_question"] if r["type"] == t) for t in result["by_type"]}
    lines = [
        f"Corpus: {result['corpus_size']} operations · {result['questions']} questions · embedder `{result['embedder']}`",
        "",
        "| Questions | Mode | Recall@1 | Recall@3 | Recall@5 | MRR |",
        "|---|---|---|---|---|---|",
    ]
    groups = [("All", result["questions"], result["overall"])]
    groups += [(t.capitalize(), counts[t], result["by_type"][t]) for t in result["by_type"]]
    for name, n, summary in groups:
        for mode in MODES:
            m = summary[mode]
            lines.append(f"| {name} ({n}) | {mode} | {m['recall@1']:.0%} | {m['recall@3']:.0%} | "
                         f"{m['recall@5']:.0%} | {m['mrr']:.2f} |")
    return "\n".join(lines)


def misses(result: dict, mode: str, k: int = 5) -> list[str]:
    return [f"  [{r['type']}] {r['q']!r} -> expected {r['expected']} (rank {r['ranks'][mode] or '>' + str(DEPTH)})"
            for r in result["per_question"] if (r["ranks"][mode] or DEPTH + 1) > k]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--embedder", choices=["fastembed", "hashing"], default="fastembed")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    parser.add_argument("--misses", choices=MODES, help="also list questions this mode misses at k=5")
    args = parser.parse_args(argv)

    embedder: Embedder = FastEmbedEmbedder() if args.embedder == "fastembed" else HashingEmbedder()
    result = evaluate(embedder)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print(to_markdown(result))
        if args.misses:
            print(f"\nMissed by {args.misses} at k=5:")
            print("\n".join(misses(result, args.misses)) or "  none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
