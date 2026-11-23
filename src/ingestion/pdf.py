from contextlib import ExitStack, closing
from io import BytesIO
import os
import subprocess
from typing import BinaryIO

from pypdf import PdfReader
from pypdfium2 import PdfDocument, PdfiumError

from src.ingestion.document import Document

OCR_LANGUAGES = "srp_latn+srp+eng"


def recognize_page(png: bytes, page_number: int) -> str:
    executable = os.getenv("TESSERACT_CMD") or "tesseract"
    try:
        result = subprocess.run(
            [executable, "stdin", "stdout", "-l", OCR_LANGUAGES, "--dpi", "300", "--psm", "3"],
            input=png, capture_output=True, timeout=120,
        )
    except FileNotFoundError as error:
        raise ValueError(
            f"OCR is needed on PDF page {page_number}. Install Tesseract and add it to PATH "
            "or set TESSERACT_CMD to its executable."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"OCR timed out on PDF page {page_number}.") from error
    if result.returncode:
        raise ValueError(
            f"OCR failed on PDF page {page_number}. Check that Tesseract has the "
            "srp_latn, srp, and eng language packs."
        )
    return result.stdout.decode("utf-8").strip()


def render_page(pdf: PdfDocument, index: int) -> bytes:
    with closing(pdf[index]) as page, closing(page.render(scale=300 / 72)) as bitmap:
        with bitmap.to_pil() as image:
            with BytesIO() as png:
                image.save(png, format="PNG")
                return png.getvalue()


def load_pdf(stream: BinaryIO) -> list[Document]:
    reader = PdfReader(stream)
    documents = []
    rendered_pdf = None
    with ExitStack() as resources:
        for index, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if not text and len(page.images):
                # The renderer and the text reader both seek the shared input stream.
                try:
                    if rendered_pdf is None:
                        rendered_pdf = resources.enter_context(closing(PdfDocument(stream)))
                    text = recognize_page(render_page(rendered_pdf, index), index + 1)
                except PdfiumError as error:
                    raise ValueError(f"Could not render PDF page {index + 1} for OCR.") from error
            documents.append(Document(text, f"page {index + 1}"))
    return documents
