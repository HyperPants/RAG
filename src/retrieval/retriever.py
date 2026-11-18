from src.embeddings.embedder import Embedder
from src.vectordb.vector_store import SearchHit, VectorStore


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore, top_k: int):
        if top_k < 1:
            raise ValueError("Retrieval top_k must be positive.")
        self.embedder = embedder
        self.store = store
        self.top_k = top_k

    def retrieve(self, question: str) -> list[SearchHit]:
        if not self.store.has_chunks():
            return []
        return self.store.search(self.embedder.embed([question])[0], self.top_k)
