import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import httpx
from pypdf import PdfReader


@dataclass(frozen=True)
class Document:
    text: str
    location: str


def load_documents(source: str) -> tuple[str, list[Document]]:
    if urlsplit(source).scheme.lower() in {"http", "https"}:
        response = httpx.get(source, follow_redirects=True, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        return source, [Document(soup.get_text(" ", strip=True), "web page")]

    path = Path(source).resolve()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        documents = [
            Document(page.extract_text() or "", f"page {index}")
            for index, page in enumerate(PdfReader(path).pages, 1)
        ]
    elif suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            documents = [
                Document(", ".join(f"{key}: {value}" for key, value in row.items()), f"record {index}")
                for index, row in enumerate(csv.DictReader(stream), 1)
                if any(value for value in row.values())
            ]
    elif suffix in {".txt", ".md"}:
        documents = [Document(path.read_text(encoding="utf-8-sig"), "document")]
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    return str(path), documents
