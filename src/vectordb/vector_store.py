from contextlib import closing
from dataclasses import dataclass
import heapq
import json
from itertools import groupby
from math import hypot, sumprod
from pathlib import Path
import sqlite3

from src.chunking.chunker import Chunk
from src.vectordb.keywords import keyword_query, keyword_row


@dataclass(frozen=True)
class SearchHit:
    source: str
    location: str
    text: str
    score: float
    ordinal: int = 0


@dataclass(frozen=True)
class IndexedDocument:
    source: str
    chunks: int


def normalize(vector: list[float]) -> list[float]:
    length = hypot(*vector)
    if not length:
        raise ValueError("Cannot search with a zero-length embedding.")
    return [value / length for value in vector]


class SyncConflict(ValueError):
    pass


class VectorStore:
    def __init__(self, path: Path, model: str):
        self.path = path
        self.model = model
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    model TEXT, source TEXT, ordinal INTEGER, location TEXT,
                    content TEXT, vector TEXT, PRIMARY KEY (model, source, ordinal)
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS synced_documents (
                    model TEXT NOT NULL, source TEXT NOT NULL, digest TEXT NOT NULL,
                    PRIMARY KEY (model, source)
                )
            """)

            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chunk_keywords'",
            ).fetchone() is None:
                connection.execute("CREATE VIRTUAL TABLE chunk_keywords USING fts5(body, context, identifiers, model UNINDEXED, source UNINDEXED, ordinal UNINDEXED)")
                self._index_keywords(connection, "SELECT model, source, ordinal, location, content FROM chunks")

    @staticmethod
    def _index_keywords(connection: sqlite3.Connection, query: str, params: tuple = ()) -> None:
        rows = connection.execute(query, params)
        connection.executemany(
            "INSERT INTO chunk_keywords(body, context, identifiers, model, source, ordinal) VALUES (?, ?, ?, ?, ?, ?)",
            (keyword_row(*row) for row in rows),
        )

    def _delete_source(self, connection: sqlite3.Connection, source: str) -> bool:
        params = (self.model, source)
        connection.execute(
            "DELETE FROM chunk_keywords WHERE model = ? AND source = ?",
            params,
        )
        return connection.execute("DELETE FROM chunks WHERE model = ? AND source = ?", params).rowcount > 0

    def synced_documents(self, prefix: str) -> dict[str, str]:
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT source, digest FROM synced_documents WHERE model = ? AND source GLOB ?",
                (self.model, prefix + "*"),
            )
            return dict(rows)

    def _sync_digest(self, connection: sqlite3.Connection, source: str) -> str | None:
        row = connection.execute(
            "SELECT digest FROM synced_documents WHERE model = ? AND source = ?",
            (self.model, source),
        ).fetchone()
        return row[0] if row else None

    def replace(
        self, source: str, chunks: list[Chunk], vectors: list[list[float]], *,
        sync_digest: str | None = None, previous_digest: str | None = None,
    ) -> None:
        rows = [
            (self.model, source, index, chunk.location, chunk.text, json.dumps(normalize(vector)))
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        with closing(sqlite3.connect(self.path)) as connection, connection:
            if sync_digest is not None:
                connection.execute("BEGIN IMMEDIATE")
                if self._sync_digest(connection, source) != previous_digest:
                    raise SyncConflict("The index changed during synchronization. Try again.")
                connection.execute(
                    "INSERT OR REPLACE INTO synced_documents VALUES (?, ?, ?)",
                    (self.model, source, sync_digest),
                )
            self._delete_source(connection, source)
            connection.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)", rows)
            self._index_keywords(
                connection,
                "SELECT model, source, ordinal, location, content FROM chunks WHERE model = ? AND source = ?",
                (self.model, source),
            )

    def move_synced_document(self, donor: str, source: str, digest: str) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._sync_digest(connection, donor) != digest or self._sync_digest(connection, source) is not None:
                raise SyncConflict("The index changed during synchronization. Try again.")
            result = connection.execute(
                "UPDATE chunks SET source = ? WHERE model = ? AND source = ?",
                (source, self.model, donor),
            )
            if not result.rowcount:
                raise SyncConflict("The indexed copy is unavailable. Try again.")
            self._delete_source(connection, donor)
            connection.execute(
                "UPDATE synced_documents SET source = ? WHERE model = ? AND source = ?",
                (source, self.model, donor),
            )
            self._index_keywords(
                connection,
                "SELECT model, source, ordinal, location, content FROM chunks WHERE model = ? AND source = ?",
                (self.model, source),
            )

    def discard_synced_duplicate(
        self, source: str, expected_digest: str, kept_source: str, kept_digest: str,
    ) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if (
                self._sync_digest(connection, kept_source) != kept_digest
                or self._sync_digest(connection, source) != expected_digest
            ):
                raise SyncConflict("The index changed during synchronization. Try again.")
            self._delete_source(connection, source)
            connection.execute(
                "DELETE FROM synced_documents WHERE model = ? AND source = ?", (self.model, source),
            )

    def find_upload(self, digest: str) -> str | None:
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT source FROM chunks WHERE model = ? AND ordinal = 0 AND source GLOB ? LIMIT 1",
                (self.model, f"uploads/{digest}/*"),
            ).fetchone()
            return row[0] if row else None

    def find_matching_chunks(self, chunks: list[Chunk]) -> str | None:
        expected = [(chunk.location, chunk.text) for chunk in chunks]
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("""
                SELECT source, location, content
                FROM chunks
                WHERE model = ? AND source IN (
                    SELECT source FROM chunks
                    WHERE model = ? AND ordinal = 0 AND location = ? AND content = ?
                )
                ORDER BY source, ordinal
            """, (self.model, self.model, *expected[0]))
            for source, group in groupby(rows, key=lambda row: row[0]):
                if [(location, text) for _, location, text in group] == expected:
                    return source
        return None

    def delete_document(self, source: str, *, expected_digest: str | None = None) -> bool:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if expected_digest is not None and self._sync_digest(connection, source) != expected_digest:
                return False
            connection.execute(
                "DELETE FROM synced_documents WHERE model = ? AND source = ?", (self.model, source),
            )
            return self._delete_source(connection, source)

    def list_documents(self) -> list[IndexedDocument]:
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("""
                SELECT source, COUNT(*)
                FROM chunks
                WHERE model = ?
                GROUP BY source
                ORDER BY source COLLATE NOCASE, source
            """, (self.model,))
            return [IndexedDocument(source, count) for source, count in rows]

    def has_chunks(self) -> bool:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                "SELECT 1 FROM chunks WHERE model = ? LIMIT 1", (self.model,),
            ).fetchone() is not None

    def search(self, vector: list[float], limit: int) -> list[SearchHit]:
        query = normalize(vector)
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(
                "SELECT source, location, content, vector, ordinal FROM chunks WHERE model = ? ORDER BY source, ordinal", (self.model,),
            )
            hits = (
                SearchHit(source, location, content, sumprod(query, json.loads(stored)), ordinal)
                for source, location, content, stored, ordinal in rows
            )
            return heapq.nlargest(limit, hits, key=lambda hit: hit.score)


    def search_keywords(self, question: str, vector: list[float], limit: int) -> list[tuple[SearchHit, bool]]:
        expression, references = keyword_query(question)
        if not expression:
            return []

        query = normalize(vector)
        # Each reference comes from the tokenizer, and its SQL value is bound separately.
        exact_match = " OR ".join("instr(' ' || identifiers || ' ', ?) > 0" for _ in references) or "0"
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(f"""
                SELECT c.source, c.location, c.content, c.vector, c.ordinal,
                       CASE WHEN {exact_match} THEN 1 ELSE 0 END AS exact
                FROM chunk_keywords
                JOIN chunks AS c ON c.model = chunk_keywords.model
                    AND c.source = chunk_keywords.source AND c.ordinal = chunk_keywords.ordinal
                WHERE chunk_keywords MATCH ? AND c.model = ?
                ORDER BY exact DESC, bm25(chunk_keywords, 1.0, 1.5, 2.0), c.source, c.ordinal
                LIMIT ?
            """, (*(f" {token} " for token in references), expression, self.model, limit))
            return [
                (SearchHit(source, location, content, sumprod(query, json.loads(stored)), ordinal), bool(exact))
                for source, location, content, stored, ordinal, exact in rows
            ]
