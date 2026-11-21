# Retrieval evaluation results

Generated with `python -m evaluation.run`.

Corpus: 34 operations · 42 questions · embedder `BAAI/bge-small-en-v1.5`

| Questions | Mode | Recall@1 | Recall@3 | Recall@5 | MRR |
|---|---|---|---|---|---|
| All (42) | bm25 | 52% | 62% | 62% | 0.58 |
| All (42) | vector | 74% | 90% | 90% | 0.81 |
| All (42) | hybrid | 62% | 83% | 88% | 0.73 |
| Keyword (14) | bm25 | 100% | 100% | 100% | 1.00 |
| Keyword (14) | vector | 93% | 100% | 100% | 0.96 |
| Keyword (14) | hybrid | 100% | 100% | 100% | 1.00 |
| Paraphrase (28) | bm25 | 29% | 43% | 43% | 0.36 |
| Paraphrase (28) | vector | 64% | 86% | 86% | 0.74 |
| Paraphrase (28) | hybrid | 43% | 75% | 82% | 0.60 |
