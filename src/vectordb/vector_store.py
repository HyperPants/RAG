from contextlib import closing
from dataclasses import dataclass
import heapq
import json
from itertools import groupby
from math import hypot, sumprod
from pathlib import Path
import sqlite3

from src.chunking.chunker import Chunk


@dataclass(frozen=True)
class SearchHit:
    source: str
    location: str
    text: str
    score: float


@dataclass(frozen=True)
class IndexedDocument:
    source: str
    chunks: int


def normalize(vector: list[float]) -> list[float]:
    length = hypot(*vector)
    if not length:
        raise ValueError("Cannot search with a zero-length embedding.")
    return [value / length for value in vector]


class VectorStore:
    def __init__(self, path: Path, model: str):
        self.path = path
        self.model = model
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    model TEXT, source TEXT, ordinal INTEGER, location TEXT,
                    content TEXT, vector TEXT, PRIMARY KEY (model, source, ordinal)
                )
            """)

    def replace(self, source: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        rows = [
            (self.model, source, index, chunk.location, chunk.text, json.dumps(normalize(vector)))
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("DELETE FROM chunks WHERE model = ? AND source = ?", (self.model, source))
            connection.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?)", rows)

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

    def delete_document(self, source: str) -> bool:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            result = connection.execute(
                "DELETE FROM chunks WHERE model = ? AND source = ?", (self.model, source),
            )
            return result.rowcount > 0

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
                "SELECT source, location, content, vector FROM chunks WHERE model = ?", (self.model,),
            )
            hits = (
                SearchHit(source, location, content, sumprod(query, json.loads(stored)))
                for source, location, content, stored in rows
            )
            return heapq.nlargest(limit, hits, key=lambda hit: hit.score)
