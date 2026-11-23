from collections.abc import Iterator
from typing import BinaryIO

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from src.ingestion.document import Document


def slide_shapes(shapes) -> Iterator:
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from slide_shapes(shape.shapes)
        else:
            yield shape


def load_powerpoint(stream: BinaryIO) -> list[Document]:
    documents = []
    for number, slide in enumerate(Presentation(stream).slides, 1):
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None else ""
        location = f"Slide {number} · {title}" if title else f"Slide {number}"
        for shape in slide_shapes(slide.shapes):
            if shape.has_text_frame and (text := shape.text.strip()):
                documents.append(Document(text, location, embed_location=True))
            if shape.has_table:
                for row_number, row in enumerate(shape.table.rows, 1):
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        reference = f"{location} · {shape.name}, row {row_number}"
                        documents.append(Document(" | ".join(cells), reference, embed_location=True))
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            if frame is not None and (text := frame.text.strip()):
                documents.append(Document(text, f"{location} · speaker notes", embed_location=True))
    return documents
