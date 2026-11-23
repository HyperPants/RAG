# RAG

A local retrieval-augmented generation (RAG) app for asking questions about your documents. Its browser interface, **Marginalia**, supports batch uploads of PDFs and Office documents, combines keyword and semantic search, and answers in Serbian Latin with citations to the original source locations.

## Quick start

Install Python 3.12 or later. From the repository root in PowerShell, create a virtual environment and install the dependencies. If you already have a `.venv`, rerun just the second command to install the current dependencies.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in your local `.env`. On a fresh clone, create the file with `Copy-Item .env.example .env` first. An environment variable of the same name takes precedence. The key needs access to the OpenAI API.

Start the server:

```powershell
.\.venv\Scripts\python.exe main.py serve
```

## Upload and ask in Marginalia

1. Open [Marginalia](http://127.0.0.1:8000/).
2. In **Add documents**, click **Choose files** or drag files onto the drop zone. You can add multiple PDFs, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), UTF-8 CSV, plain text, or Markdown files in one batch. Scanned PDFs require the OCR setup below.
3. Wait for the per-file indexing results. Successful files are ready to query immediately, even if some files in the batch fail.
4. Ask a question, such as “Koji je rok plaćanja za ugovor UG-42/2025?” Select a numbered citation in the answer to open the retrieved excerpt and see its source location.

Open **Indexed documents** to see the saved sources and excerpt counts. The list updates after uploads. Use **Refresh** after indexing files or URLs from another terminal. To remove an outdated source, choose **Delete** next to it and confirm. This removes its excerpts and embeddings for the active model from the index. The original file stays on disk. The extracted excerpts and vectors persist in SQLite across restarts. Marginalia checks for matching files and identical indexed excerpts before embedding an upload. If it finds a match, you can skip the file or choose **Upload anyway**. Confirming an identical upload with the same name refreshes its existing entry. A matching file with a different name gets a separate entry.

## Document extraction

| Format | What is indexed | Citation location |
| --- | --- | --- |
| PDF | Native text and OCR on image pages without extractable text | One-based PDF page number |
| Word (.docx) | Body paragraphs, heading-styled sections, and table rows | Heading path and paragraph or table row |
| Excel (.xlsx) | Each populated worksheet row separately, with cell coordinates and column labels from Excel tables or filter ranges when available. For loose cells, a first multi-cell text row is treated as headers | Worksheet and physical row number |
| PowerPoint (.pptx) | Slide titles, text boxes, table rows, and speaker notes | Slide number, title, and notes or table row when applicable |

Excel formula cells use the values cached by Excel when the workbook was saved. If a calculated value is missing, open the workbook in Excel, recalculate it, and save it before reindexing. Conditional formatting is visual and ingestion reads the saved cell values without modifying the workbook. PowerPoint diagrams and embedded images need separate visual processing. Office files in the older .doc, .xls, and .ppt formats should be saved in their modern formats first.

Answers default to Serbian Latin script, with citations to the original files. Source names, identifiers, company names, and contract numbers are kept in their original form.

### Scanned PDF setup on Windows

1. Install Tesseract 5 using the Windows installer linked from the [Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation).
2. Put `eng.traineddata`, `srp_latn.traineddata`, and `srp.traineddata` in its `tessdata` folder. Use the language packs included in the installer or download the files from [Tesseract's language data repository](https://github.com/tesseract-ocr/tessdata_fast).
3. If Tesseract is outside your PATH, set `TESSERACT_CMD` in `.env` to the full executable path, for example `TESSERACT_CMD="C:/Program Files/Tesseract-OCR/tesseract.exe"`. Restart the server after editing `.env`.

Verify the installed language packs in PowerShell:

```powershell
& 'C:\Program Files\Tesseract-OCR\tesseract.exe' --list-langs
```

The list should include `eng` (English), `srp_latn` (Serbian Latin), and `srp` (Serbian Cyrillic). The app runs OCR locally and keeps the original PDF page number on each excerpt.

## CLI and API

The CLI also accepts HTTP(S) pages. To index multiple files or URLs, pass each as a separate argument.

```powershell
.\.venv\Scripts\python.exe main.py ingest ".\Documents\example.docx" ".\Documents\example.xlsx"
```

Use [Swagger UI](http://127.0.0.1:8000/docs) to try the API while the server is running.

| Endpoint | Purpose |
| --- | --- |
| `POST /ingest` | Upload a multipart request with one or more `files` fields. Returns a result for each file, including any duplicate match. Use `allow_duplicate=true` to explicitly index matching files. |
| `POST /query` | Send JSON such as `{"question": "What were the main findings?"}`. Returns an answer and retrieved excerpts with citations, locations, and cosine scores. Hybrid rank controls the order, and the score field still reports cosine similarity. |
| `GET /documents` | List indexed sources and their excerpt counts for the active embedding model. |
| `DELETE /documents?source=...` | Remove a source from the active model’s index. Use the exact source identifier from the list. |
| `GET /health` | Check whether the server is responding. |

## Architecture

```text
Upload or CLI source -> loader -> overlapping chunks -> OpenAI embeddings -> SQLite
Question -> SQLite keyword search + embedding similarity -> merged ranking -> Serbian answer
```

- `main.py` wires together the CLI and FastAPI server. Both ingestion paths share the indexer and loader in `src/ingestion`, with separate parsers in `pdf.py`, `word.py`, `excel.py`, and `powerpoint.py`.
- `src/api` provides the upload and query endpoints. `src/api/web` contains the HTML, CSS, and JavaScript for Marginalia.
- `src/chunking` normalizes whitespace and creates overlapping character windows. `src/embeddings` batches embedding requests. `src/vectordb` runs exact cosine search over the stored vectors for the active embedding model.
- `src/retrieval`, `src/prompts`, and `src/llm` use the top matches to generate answers. Source metadata preserves page numbers, section headings, worksheet rows, slide numbers, and CSV record numbers.
- `config.yaml` sets the models, chunk size and overlap, database path, and number of matches. Relative database paths are resolved from the repository root. Reindex your sources after changing the embedding model or chunk settings.
- Keep local source files under `Documents/` or point the CLI to another folder. Git ignores new files under `Documents/`, plus `.env`, the default database under `data/`, and logs.

Ingestion sends extracted text to OpenAI for embedding. Queries send the question and retrieved excerpts to OpenAI for answer generation.

## Hybrid retrieval

Marginalia combines vector similarity with SQLite FTS5 search over excerpt text, filenames, and source locations such as Word headings and Excel sheet names. Keyword search matches Serbian Latin and Cyrillic through a normalized index. Reciprocal Rank Fusion merges the two ranked lists. Exact references such as `UG-42/2025` or `C12` get a ranking boost, and citations retain the original text and location.

The first startup builds the keyword index from existing SQLite chunks. It uses no new embedding requests and requires no reuploads. Adds, replacements, and deletions update both indexes in the same transaction.

In `config.yaml`, set `retrieval.mode` to `vector` to compare against vector-only search. The default is `hybrid`. `candidate_k` controls the number of candidates from each search, and `top_k` controls how many excerpts are passed to the answer model.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use a temporary SQLite database and simulated model responses, so they run without an API key. They cover document loading, chunking, retrieval, partial success in a multi-file upload, Office citations, and the PDF OCR path with a simulated Tesseract process, and hybrid ranking with a backfilled keyword index.

## References

- [OpenAI Embeddings API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)
- [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
- [FastAPI testing guide](https://fastapi.tiangolo.com/tutorial/testing/)
