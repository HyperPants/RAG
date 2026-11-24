from collections.abc import Callable

from openai import OpenAI


class Embedder:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def embed(
        self, texts: list[str], *, on_batch: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        if on_batch is not None:
            on_batch(0, len(texts))
        vectors = []
        for start in range(0, len(texts), 32):
            response = self.client.embeddings.create(
                model=self.model, input=texts[start:start + 32], encoding_format="float",
            )
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
            if on_batch is not None:
                on_batch(min(start + 32, len(texts)), len(texts))
        return vectors
