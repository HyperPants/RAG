from contextlib import closing
import sqlite3
from types import SimpleNamespace

from src.chunking.chunker import Chunk
from src.retrieval.retriever import Retriever
from src.vectordb.vector_store import VectorStore


def test_backfill_replace_and_delete_keyword_entries(tmp_path):
    path = tmp_path / "existing.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""
            CREATE TABLE chunks (
                model TEXT, source TEXT, ordinal INTEGER, location TEXT,
                content TEXT, vector TEXT, PRIMARY KEY (model, source, ordinal)
            )
        """)
        connection.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)", [
            ("model", "contract.pdf", 0, "page 4", "Рок плаћања је 30 дана.", "[1.0]"),
            ("other", "contract.pdf", 0, "page 9", "Plaćanje po prijemu.", "[1.0]"),
        ])

    store = VectorStore(path, "model")
    hits = store.search_keywords("placanja", [1.0], 10)
    assert [(hit.location, hit.text) for hit, _ in hits] == [("page 4", "Рок плаћања је 30 дана.")]
    assert len(VectorStore(path, "model").search_keywords("placanja", [1.0], 10)) == 1

    store.replace("contract.pdf", [Chunk("Iznos: 200", "Sheet Troškovi · row 12")], [[1.0]])
    assert store.search_keywords("placanja", [1.0], 10) == []
    assert store.search_keywords("troskovi", [1.0], 10)[0][0].location == "Sheet Troškovi · row 12"
    assert store.delete_document("contract.pdf")
    assert store.search_keywords("troskovi", [1.0], 10) == []
    assert VectorStore(path, "other").search_keywords("плаћање", [1.0], 10)[0][0].location == "page 9"


def test_hybrid_prioritizes_exact_references_and_keeps_semantic_matches(tmp_path):
    store = VectorStore(tmp_path / "vectors.sqlite3", "model")
    store.replace("wrong.pdf", [Chunk("UG 42 or 2025", "page 1")], [[1.0, 0.0]])
    store.replace("right.pdf", [Chunk("УГ-42/2025", "page 7")], [[0.0, 1.0]])
    store.replace("budget.xlsx", [Chunk("Iznos [C12]: 200", "Sheet Troškovi · row 12")], [[0.0, 1.0]])
    store.replace("terms.docx", [Chunk("Invoices are due within thirty days.", "Payment · Paragraph 4")], [[1.0, 0.0]])

    embedder = SimpleNamespace(embed=lambda texts: [[1.0, 0.0] for _ in texts])
    baseline = Retriever(embedder, store, top_k=1)
    hybrid = Retriever(embedder, store, top_k=1, mode="hybrid", candidate_k=4)

    assert baseline.retrieve("UG-42/2025")[0].source != "right.pdf"
    match = hybrid.retrieve('Tražim "UG-42/2025" (ugovor)')[0]
    assert (match.source, match.location, match.text, match.score) == (
        "right.pdf", "page 7", "УГ-42/2025", 0.0,
    )
    assert hybrid.retrieve("Koliki je iznos u C12?")[0].source == "budget.xlsx"
    assert hybrid.retrieve("Kada dospeva uplata?")[0].source == "terms.docx"
    assert hybrid.retrieve("?!")[0] == baseline.retrieve("?!")[0]
