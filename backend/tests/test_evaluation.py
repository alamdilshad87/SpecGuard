import pytest

from app.core.embeddings import HashingEmbedder
from evaluation.run import MODES, evaluate, load_dataset, metrics, rank_of, to_markdown


def test_every_expected_operation_exists_in_the_spec():
    chunks, questions = load_dataset()
    ids = {c.id for c in chunks}
    assert len(questions) >= 40
    assert {q.type for q in questions} == {"keyword", "paraphrase"}
    assert [q.expected for q in questions if q.chunk_id not in ids] == []


def test_rank_and_metrics():
    assert rank_of("b", ["a", "b", "c"]) == 2
    assert rank_of("z", ["a", "b"]) is None

    m = metrics([1, 2, 6, None])
    assert m["recall@1"] == 0.25
    assert m["recall@3"] == 0.5
    assert m["recall@5"] == 0.5
    assert m["mrr"] == pytest.approx((1 + 1 / 2 + 1 / 6) / 4)


def test_evaluate_produces_a_report_for_every_mode():
    result = evaluate(HashingEmbedder())  # no model download in tests
    assert set(result["overall"]) == set(MODES)
    assert set(result["by_type"]) == {"keyword", "paraphrase"}
    assert result["overall"]["bm25"]["recall@5"] > 0.5  # sanity: keyword search is not broken
    assert "| All (" in to_markdown(result)
