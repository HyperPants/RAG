import csv
from zipfile import BadZipFile
from io import TextIOWrapper
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import httpx
from openpyxl.utils.exceptions import InvalidFileException

from src.ingestion.document import Document
from src.ingestion.excel import load_excel
from src.ingestion.pdf import load_pdf
from src.ingestion.powerpoint import load_powerpoint
from src.ingestion.word import load_word

OFFICE_LOADERS = {".docx": load_word, ".xlsx": load_excel, ".pptx": load_powerpoint}
SUPPORTED_SUFFIXES = frozenset({".pdf", ".csv", ".txt", ".md", *OFFICE_LOADERS})


def load_file(stream: BinaryIO, suffix: str) -> list[Document]:
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Supported formats are PDF, DOCX, XLSX, PPTX, CSV, TXT, and Markdown.")
    if suffix == ".pdf":
        return load_pdf(stream)
    if suffix in OFFICE_LOADERS:
        try:
            return OFFICE_LOADERS[suffix](stream)
        except (BadZipFile, KeyError, InvalidFileException, SyntaxError, ValueError) as error:
            raise ValueError(f"Could not read this {suffix.upper()[1:]} file. Check that it is valid and unencrypted.") from error

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
