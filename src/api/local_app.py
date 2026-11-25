from contextlib import contextmanager
import os
import sys
from pathlib import Path

from openai import OpenAI

from src.api.routes import create_app
from src.embeddings.embedder import Embedder
from src.ingestion.indexer import Indexer
from src.llm.llm_client import LLMClient
from src.retrieval.retriever import Retriever
from src.utils.helpers import ROOT
from src.utils.settings import LocalSettings
from src.vectordb.vector_store import VectorStore


def user_data_directory() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Atlas"
    if local_app_data := os.getenv("LOCALAPPDATA"):
        return Path(local_app_data) / "Marginalia"
    return Path.home() / ".marginalia"


@contextmanager
def browser_app(config, *, database: Path, settings: LocalSettings, folder_picker=None):
    with OpenAI(api_key=settings.api_key) as client:
        models = config["models"]
        embedder = Embedder(client, models["embedding"])
        indexer = Indexer(embedder, VectorStore(database, embedder.model), **config["chunking"])
        retriever = Retriever(embedder, indexer.store, **config["retrieval"])
        yield create_app(
            retriever, LLMClient(client, models["answer"]), indexer,
            settings=settings, folder_picker=folder_picker,
            sync_provider=lambda: settings.folder_sync(ROOT, indexer),
        )
