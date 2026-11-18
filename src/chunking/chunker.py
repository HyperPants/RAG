from dataclasses import dataclass

from src.ingestion.loader import Document


@dataclass(frozen=True)
class Chunk:
    text: str
    location: str


def split_documents(documents: list[Document], size: int, overlap: int) -> list[Chunk]:
    if not 0 <= overlap < size:
        raise ValueError("Chunk overlap must be nonnegative and smaller than chunk size.")

    chunks = []
    for document in documents:
        text = " ".join(document.text.split())
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            excerpt = text[start:end].strip()
            if excerpt:
                chunks.append(Chunk(excerpt, document.location))
            if end == len(text):
                break
            start = end - overlap
    return chunks
