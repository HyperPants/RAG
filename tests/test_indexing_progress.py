from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from src.api.routes import create_app
from src.embeddings.embedder import Embedder
from src.ingestion.folder_sync import FolderSync
from src.ingestion.indexer import Indexer
from src.retrieval.retriever import Retriever
from src.vectordb.vector_store import VectorStore


@pytest.mark.parametrize("operation", ["ingest", "sync"])
def test_indexing_reports_completed_embedding_batches(tmp_path, operation):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "sample.txt").write_text("x" * 40, encoding="utf-8")
    entered_second_batch = Event()
    finish_second_batch = Event()

    def embed(model, input, encoding_format):
        if len(input) == 8:
            entered_second_batch.set()
            assert finish_second_batch.wait(timeout=10)
        return SimpleNamespace(data=[
            SimpleNamespace(index=index, embedding=[1.0])
            for index in range(len(input))
        ])

    provider = SimpleNamespace(embeddings=SimpleNamespace(create=embed))
    embedder = Embedder(provider, "test-model")
    store = VectorStore(tmp_path / "index.sqlite3", "test-model")
    indexer = Indexer(embedder, store, size=1, overlap=0)
    app = create_app(
        Retriever(embedder, store, 3), None, indexer, folder_sync=FolderSync(root, indexer),
    )
    progress_id = str(uuid4())
    progress_path = f"/indexing-progress/{progress_id}"
    request_params = {"files": {"files": ("sample.txt", b"x" * 40)}} if operation == "ingest" else {}
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(client.post, f"/{operation}?progress_id={progress_id}", **request_params)
        try:
            assert entered_second_batch.wait(timeout=10)
            assert client.get(progress_path).json() == {
                "stage": "embedding", "total": 1, "completed": 0, "filename": "sample.txt",
                "excerpts_done": 32, "excerpts_total": 40,
            }
        finally:
            finish_second_batch.set()
        assert pending.result(timeout=10).status_code == 200
        assert client.get(progress_path).json() is None
