from collections.abc import Callable
from hashlib import file_digest
import logging
from pathlib import Path
from threading import Lock
from typing import BinaryIO

from src.chunking.chunker import Chunk, split_documents
from src.embeddings.embedder import Embedder
from src.ingestion.document import Document
from src.ingestion.loader import load_documents, load_file
from src.ingestion.progress import IndexProgress
from src.vectordb.vector_store import VectorStore


class DuplicateUpload(Exception):
    def __init__(self, source: str):
        super().__init__(source)
        self.source = source


class Indexer:
    def __init__(self, embedder: Embedder, store: VectorStore, size: int, overlap: int):
        self.embedder = embedder
        self.store = store
        self.size = size
        self.overlap = overlap
        self.upload_lock = Lock()

    def index_source(self, source: str) -> int:
        identifier, documents = load_documents(source)
        return self._index(identifier, self._chunks(documents))

    def index_upload(
        self, filename: str, stream: BinaryIO, *, allow_duplicate: bool = False,
        progress: IndexProgress | None = None,
    ) -> int:
        digest = file_digest(stream, "sha256").hexdigest()
        stream.seek(0)

        with self.upload_lock:
            if not allow_duplicate and (match := self.store.find_upload(digest)) is not None:
                raise DuplicateUpload(match)

            documents = load_file(stream, Path(filename).suffix.lower())
            chunks = self._chunks(documents)
            if not allow_duplicate and (match := self.store.find_matching_chunks(chunks)) is not None:
                raise DuplicateUpload(match)
            return self._index(f"uploads/{digest}/{filename}", chunks, progress)

    def index_synced_file(
        self, source: str, stream: BinaryIO, suffix: str, digest: str,
        previous_digest: str | None, check_current: Callable[[], None],
        progress: IndexProgress | None = None,
    ) -> None:
        with self.upload_lock:
            chunks = self._chunks(load_file(stream, suffix))
            check_current()
            vectors = self._embed_chunks(chunks, progress)
            check_current()
            self.store.replace(source, chunks, vectors, sync_digest=digest, previous_digest=previous_digest)
            logging.info("Indexed %d chunks from a synchronized file", len(chunks))

    def _chunks(self, documents: list[Document]) -> list[Chunk]:
        chunks = split_documents(documents, self.size, self.overlap)
        if not chunks:
            raise ValueError("No extractable text.")
        return chunks

    def _embed_chunks(self, chunks: list[Chunk], progress: IndexProgress | None) -> list[list[float]]:
        texts = [
            f"{chunk.location}\n{chunk.text}" if chunk.embed_location else chunk.text
            for chunk in chunks
        ]
        if progress is None:
            return self.embedder.embed(texts)
        vectors = self.embedder.embed(texts, on_batch=progress.embedding)
        progress.saving()
        return vectors

    def _index(self, source: str, chunks: list[Chunk], progress: IndexProgress | None = None) -> int:
        vectors = self._embed_chunks(chunks, progress)
        self.store.replace(source, chunks, vectors)
        logging.info("Indexed %d chunks", len(chunks))
        return len(chunks)
