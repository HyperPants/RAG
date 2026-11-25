from io import BytesIO
from types import SimpleNamespace

from docx import Document as WordDocument
from fastapi.testclient import TestClient
from openpyxl import Workbook
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfWriter

from src.api.routes import create_app
from src.ingestion import pdf
from src.ingestion.indexer import Indexer
from src.ingestion.loader import load_file
from src.retrieval.retriever import Retriever
from src.vectordb.vector_store import VectorStore


def as_stream(office_document):
    stream = BytesIO()
    office_document.save(stream)
    stream.seek(0)
    return stream


def test_mixed_pdf_ocr_preserves_physical_page_number(monkeypatch):
    scan = BytesIO()
    with Image.new("RGB", (100, 100), "white") as image:
        image.save(scan, format="PDF")
    scan.seek(0)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.append(scan)
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    stream.seek(0)

    def ocr(command, *, input, capture_output, timeout, creationflags):
        assert command[command.index("-l") + 1] == "srp_latn+srp+eng"
        assert input.startswith(b"\x89PNG")
        return SimpleNamespace(returncode=0, stdout="Račun · Рачун · Invoice".encode())

    monkeypatch.setattr(pdf.subprocess, "run", ocr)
    pages = load_file(stream, ".pdf")
    assert [(page.text, page.location) for page in pages] == [
        ("", "page 1"), ("Račun · Рачун · Invoice", "page 2"), ("", "page 3"),
    ]


def test_office_uploads_preserve_structured_citations(tmp_path):
    word = WordDocument()
    word.add_heading("Uslovi ugovora", 1)
    word.add_heading("Rokovi", 2)
    word.add_paragraph("Plaćanje dospeva za 30 dana.")
    table = word.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Broj ugovora"
    table.cell(0, 1).text = "UG-42"

    excel = Workbook()
    sheet = excel.active
    sheet.title = "Troškovi"
    sheet["A3"] = "Opis"
    sheet["C3"] = "Iznos"
    sheet["A5"] = "Prevoz"
    sheet["C5"] = 200
    excel.create_sheet("Rokovi").append(["Mesec", "Obaveza"])

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Plan rada"
    slide.shapes.add_textbox(Inches(1), Inches(2), Inches(2), Inches(1)).text = "Faza jedan"
    grid = slide.shapes.add_table(1, 2, Inches(1), Inches(3), Inches(2), Inches(1))
    grid.table.cell(0, 0).text = "Tim"
    grid.table.cell(0, 1).text = "Prodaja"
    slide.notes_slide.notes_text_frame.text = "Potvrditi budžet."

    inputs = []

    def embed(texts):
        inputs.extend(texts)
        return [[1.0] for _ in texts]

    embedder = SimpleNamespace(embed=embed)
    store = VectorStore(tmp_path / "vectors.sqlite3", "test")
    indexer = Indexer(embedder, store, size=200, overlap=0)
    llm = SimpleNamespace(answer=lambda question, hits: "Odgovor [1].")
    with TestClient(create_app(Retriever(embedder, store, top_k=30), llm, indexer)) as client:
        result = client.post("/ingest", files=[
            ("files", ("ugovor.docx", as_stream(word).getvalue())),
            ("files", ("invalid.xlsx", b"not a workbook")),
            ("files", ("budzet.xlsx", as_stream(excel).getvalue())),
            ("files", ("plan.pptx", as_stream(deck).getvalue())),
        ])
        assert result.status_code == 200
        assert [entry["chunks"] for entry in result.json()] == [4, None, 3, 4]
        assert "Could not read this XLSX" in result.json()[1]["error"]
        hits = client.post("/query", json={"question": "Koji su rokovi?"}).json()["sources"]

    excerpts = {(hit["location"], hit["text"]) for hit in hits}
    assert ("Uslovi ugovora > Rokovi · Paragraph 3", "Plaćanje dospeva za 30 dana.") in excerpts
    assert ("Uslovi ugovora > Rokovi · Table 1, row 1", "Broj ugovora | UG-42") in excerpts
    assert ("Sheet Troškovi · row 5", "Opis [A5]: Prevoz | Iznos [C5]: 200") in excerpts
    assert ("Slide 1 · Plan rada", "Faza jedan") in excerpts
    assert ("Slide 1 · Plan rada · speaker notes", "Potvrditi budžet.") in excerpts
    assert any(location.startswith("Slide 1 · Plan rada") and text == "Tim | Prodaja" for location, text in excerpts)
    assert any("Uslovi ugovora > Rokovi" in text and "Plaćanje" in text for text in inputs)


def test_excel_table_headers_and_conditional_formatting_extension():
    import warnings
    from zipfile import ZipFile

    from openpyxl.worksheet.table import Table

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Troškovi"
    sheet.merge_cells("B1:C1")
    sheet["B1"] = "Budžet 2026"
    sheet["B4"], sheet["C4"] = "Stavka", "Iznos"
    sheet["B5"], sheet["C5"] = "Prevoz", 200
    sheet["E4"], sheet["F4"] = "Tim", "Sati"
    sheet["E5"], sheet["F5"] = "Prodaja", 0
    sheet.add_table(Table(displayName="Budzet", ref="B4:C5"))
    sheet.add_table(Table(displayName="Rad", ref="E4:F5"))
    sheet["XFD1048576"].number_format = "0.00"

    loose = workbook.create_sheet("Izvoz")
    loose["A1"] = "Izveštaj"
    loose.append(["Opis", "Vrednost"])
    loose.append(["Put", 50])

    filtered = workbook.create_sheet("Filter")
    filtered["C5"], filtered["D5"] = "Region", "Prodaja"
    filtered["C6"], filtered["D6"] = "Jug", 65
    filtered.auto_filter.ref = "C5:D6"

    modified = BytesIO()
    with ZipFile(as_stream(workbook)) as original, ZipFile(modified, "w") as output:
        for filename in original.namelist():
            content = original.read(filename)
            if filename == "xl/worksheets/sheet1.xml":
                content = content.replace(
                    b"</worksheet>",
                    b'<extLst><ext uri="{78C0D931-6437-407D-A8EE-F0AAD7539E65}"/></extLst></worksheet>',
                )
            output.writestr(filename, content)
    original_bytes = modified.getvalue()
    modified.seek(0)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        documents = load_file(modified, ".xlsx")

    assert not any("Conditional Formatting" in str(w.message) for w in captured)
    assert modified.getvalue() == original_bytes
    by_location = {document.location: document.text for document in documents}
    assert by_location["Sheet Troškovi · row 1"] == "B1: Budžet 2026"
    assert by_location["Sheet Troškovi · table Budzet · row 5"] == "Stavka [B5]: Prevoz | Iznos [C5]: 200"
    assert by_location["Sheet Troškovi · table Rad · row 5"] == "Tim [E5]: Prodaja | Sati [F5]: 0"
    assert by_location["Sheet Izvoz · row 3"] == "Opis [A3]: Put | Vrednost [B3]: 50"
    assert by_location["Sheet Filter · row 6"] == "Region [C6]: Jug | Prodaja [D6]: 65"
