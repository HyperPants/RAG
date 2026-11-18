import csv
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import httpx
from pypdf import PdfReader

SUPPORTED_SUFFIXES = frozenset({".pdf", ".csv", ".txt", ".md"})


@dataclass(frozen=True)
class Document:
    text: str
    location: str


def load_file(stream: BinaryIO, suffix: str) -> list[Document]:
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Supported formats are PDF, CSV, TXT, and Markdown.")
    if suffix == ".pdf":
        return [
            Document(page.extract_text() or "", f"page {index}")
            for index, page in enumerate(PdfReader(stream).pages, 1)
        ]

    text = TextIOWrapper(stream, encoding="utf-8-sig", newline="")
    try:
        if suffix == ".csv":
            return [
                Document(", ".join(f"{key}: {value}" for key, value in row.items()), f"record {index}")
                for index, row in enumerate(csv.DictReader(text), 1)
                if any(value for value in row.values())
            ]
        return [Document(text.read(), "document")]
    finally:
        text.detach()


def load_documents(source: str) -> tuple[str, list[Document]]:
    if urlsplit(source).scheme.lower() in {"http", "https"}:
        response = httpx.get(source, follow_redirects=True, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        return source, [Document(soup.get_text(" ", strip=True), "web page")]

    path = Path(source).resolve()
    with path.open("rb") as stream:
        return str(path), load_file(stream, path.suffix.lower())
