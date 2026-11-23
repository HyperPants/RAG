from src.embeddings.embedder import Embedder
from src.vectordb.vector_store import SearchHit, VectorStore

RRF_K = 60


class Retriever:
    def __init__(
        self, embedder: Embedder, store: VectorStore, top_k: int,
        *, mode: str = "vector", candidate_k: int = 20,
    ):
        if top_k < 1 or candidate_k < 1:
            raise ValueError("Retrieval limits must be positive.")
        if mode not in {"hybrid", "vector"}:
            raise ValueError("Retrieval mode must be hybrid or vector.")
        self.embedder = embedder
        self.store = store
        self.top_k = top_k
        self.mode = mode
        self.candidate_k = max(top_k, candidate_k)

    def retrieve(self, question: str) -> list[SearchHit]:
        if not self.store.has_chunks():
            return []
        vector = self.embedder.embed([question])[0]
        if self.mode == "vector":
            return self.store.search(vector, self.top_k)

        semantic_hits = self.store.search(vector, self.candidate_k)
        keyword_hits = self.store.search_keywords(question, vector, self.candidate_k)
        hits = {}
        scores = {}
        for rank, hit in enumerate(semantic_hits, 1):
            key = (hit.source, hit.ordinal)
            hits[key] = hit
            scores[key] = 1 / (RRF_K + rank)
        for rank, (hit, exact_match) in enumerate(keyword_hits, 1):
            key = (hit.source, hit.ordinal)
            hits[key] = hit
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_K + rank)
            if exact_match:
                # A complete identifier should outrank partial keyword or semantic matches.
                scores[key] += 2 / (RRF_K + 1)

        ordered = sorted(scores, key=lambda key: (-scores[key], -hits[key].score, key))
        return [hits[key] for key in ordered[:self.top_k]]
