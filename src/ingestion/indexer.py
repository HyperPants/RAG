from hashlib import file_digest
import logging
from pathlib import Path
from typing import BinaryIO

from src.chunking.chunker import split_documents
from src.embeddings.embedder import Embedder
from src.ingestion.loader import Document, load_documents, load_file
from src.vectordb.vector_store import VectorStore


class Indexer:
    def __init__(self, embedder: Embedder, store: VectorStore, size: int, overlap: int):
        self.embedder = embedder
        self.store = store
        self.size = size
        self.overlap = overlap

    def index_source(self, source: str) -> int:
        identifier, documents = load_documents(source)
        return self._index(identifier, documents)

    def index_upload(self, filename: str, stream: BinaryIO) -> int:
        digest = file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        documents = load_file(stream, Path(filename).suffix.lower())
        return self._index(f"uploads/{digest}/{filename}", documents)

    def _index(self, source: str, documents: list[Document]) -> int:
        chunks = split_documents(documents, self.size, self.overlap)
        if not chunks:
            raise ValueError("No extractable text.")
        vectors = self.embedder.embed([chunk.text for chunk in chunks])
        self.store.replace(source, chunks, vectors)
        logging.info("Indexed %d chunks", len(chunks))
        return len(chunks)
