from contextlib import closing
from dataclasses import dataclass
import heapq
import json
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
