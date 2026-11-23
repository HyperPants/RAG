import re
from typing import BinaryIO

from docx import Document as WordDocument
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from src.ingestion.document import Document


def heading_level(paragraph: Paragraph) -> int | None:
    properties = paragraph._p.pPr
    style = paragraph.style
    while True:
        outline = properties.find(qn("w:outlineLvl")) if properties is not None else None
        if outline is not None:
            level = int(outline.get(qn("w:val")))
            return level + 1 if level < 9 else None
        if style is None:
            return None
        if match := re.fullmatch(r"Heading([1-9])", style.style_id, flags=re.IGNORECASE):
            return int(match[1])
        properties = style.element.pPr
        style = style.base_style


def load_word(stream: BinaryIO) -> list[Document]:
    documents = []
    headings = []
    paragraph_number = table_number = 0
    for block in WordDocument(stream).iter_inner_content():
        if isinstance(block, Paragraph):
            paragraph_number += 1
            text = block.text.strip()
            if not text:
                continue
            level = heading_level(block)
            if level is not None:
                headings = [(depth, name) for depth, name in headings if depth < level]
                headings.append((level, text))
            reference = f"Paragraph {paragraph_number}"
            section = " > ".join(name for _, name in headings)
            location = f"{section} · {reference}" if section else reference
            documents.append(Document(text, location, embed_location=True))
        else:
            table_number += 1
            section = " > ".join(name for _, name in headings)
            for row_number, row in enumerate(block.rows, 1):
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    reference = f"Table {table_number}, row {row_number}"
                    location = f"{section} · {reference}" if section else reference
                    documents.append(Document(" | ".join(cells), location, embed_location=True))
    return documents
