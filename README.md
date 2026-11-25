# Atlas

Atlas is a local document assistant with a browser interface and a portable Windows app. It supports batch uploads of PDFs and Office documents, combines keyword and semantic search, and answers in Serbian Latin with citations to the original source locations.

## Windows desktop app

Extract `Atlas-Windows-x64.zip`, open the `Atlas` folder, and double-click `Atlas.exe`. Keep the executable and its `_internal` folder together. The app opens in your default browser. Use **Zatvori aplikaciju** in the small Atlas window to stop it.

1. Open **Podešavanja** if it did not open automatically. Follow the on-page links to create an OpenAI API key and check API billing for the key’s organization. Paste the key and select **Sačuvaj podešavanja**. API billing is separate from ChatGPT billing.
2. In **Fascikla sa dokumentima**, use **Izaberi** to choose your local OneDrive folder or paste its path. For OneDrive, make the folder available offline in File Explorer. Save, then use **Sync folder** in the **Document library**.
3. Ask a question after indexing finishes. If you want to use scanned PDFs, follow the optional Tesseract instructions in **Podešavanja**. Tesseract is a separate Windows installation.

The Windows app saves the OpenAI key in Windows Credential Manager. Its settings, logs, and SQLite index live under `%LOCALAPPDATA%\Marginalia`. Atlas uses the same Windows Credential Manager entry and data folder as earlier Marginalia builds, so your saved setup and index carry over. The developer server continues to use the repository’s configured database.

### Build the Windows bundle

From a Windows checkout with a working project virtual environment, install PyInstaller in that environment and run the build script in PowerShell.

```powershell
.\.venv\Scripts\python.exe -m pip install "pyinstaller>=6,<7"
.\build_windows.ps1
```

The bundle is in `dist/Atlas/`. Distribute that entire folder, for example as a ZIP. The build includes the application, Python runtime, and browser assets. It does not copy the repository’s `.env`, index, or documents.


## Developer quick start

Install Python 3.12 or later. From the repository root in PowerShell, create a virtual environment and install the dependencies. If you already have a `.venv`, rerun just the second command to install the current dependencies.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Set the OpenAI API key in **Podešavanja** when you open the browser interface. For CLI ingestion and sync, set `OPENAI_API_KEY` in your local `.env` or environment. On a fresh clone, run `Copy-Item .env.example .env` first. The browser server uses the key saved in your system credential store when one is available, and uses the environment or `.env` as a fallback.

Start the server:

```powershell
.\.venv\Scripts\python.exe main.py serve
```

## Upload and ask in Atlas

1. Open Atlas from the Windows launcher, or open [the developer server](http://127.0.0.1:8000/) if you started it manually. Use **Documents** in the header to jump to the **Document library**.
2. In **Add documents**, click **Choose files** or drag files onto the drop zone. You can add multiple PDFs, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), UTF-8 CSV, plain text, or Markdown files in one batch. Scanned PDFs require the OCR setup below.
3. Watch the progress bar for the current file, indexing stage, and embedding progress. The upload summary reports the result for each file. Successful files are ready to query immediately, even if some files in the batch fail.
4. Ask a question, such as “Koji je rok plaćanja za ugovor UG-42/2025?” The **Answer** and **Sources** panels sit beside the library on wider screens and stack on smaller screens. Select a numbered citation to open the original excerpt and see its source location.

Open **Indexed documents** to see the first five sources and their excerpt counts. **Show more** reveals five more at a time, and **Show less** returns to the first five. Search by filename or folder path to see every match across the full index. The list updates after uploads and folder sync. Use **Refresh** after indexing files or URLs from another terminal. To remove an outdated source, choose **Delete** next to it and confirm. This removes its excerpts and embeddings for the active model from the index. The original file stays on disk. The extracted excerpts and vectors persist in SQLite across restarts. Atlas checks for matching files and identical indexed excerpts before embedding an upload. If it finds a match, you can skip the file or choose **Upload anyway**. Confirming an identical upload with the same name refreshes its existing entry. A matching file with a different name gets a separate entry.

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

## Sync a local OneDrive folder

Folder sync uses the files available in Windows File Explorer. It searches subfolders and uses the same parsers, citations, and OpenAI models as browser uploads. It runs manually and uses the local filesystem without Microsoft Graph.

1. In your OneDrive, create a small test folder with non-sensitive sample files. Right-click the folder in File Explorer, choose **Always keep on this device**, and wait for OneDrive to finish downloading it. [OneDrive Files On-Demand states](https://learn.microsoft.com/en-us/onedrive/files-on-demand-windows)
2. Add the folder path to your local `.env`. Use the path from your own laptop.

   ```dotenv
   MARGINALIA_DOCUMENT_FOLDER="C:/Users/YourName/OneDrive/Atlas-Test"
   ```

3. Restart Atlas and select **Sync folder** under **Local folder sync**. The progress bar shows what is being processed, and the summary gives the counts for added, updated, unchanged, missing, and removed files. Ask a question about a known fact, such as “Koji je rok plaćanja za ugovor UG-42?” Open the citation to check the relative filename and its page, section, worksheet row, or slide.
4. Select **Sync folder** again. The same files should be reported as unchanged, with no new embedding calls. Add or edit a sample file, wait for OneDrive to finish, and sync again to see it marked as added or updated.
5. Move a sample file out of the folder and sync again. Atlas reports it as missing and keeps its indexed copy until you select **Remove missing** and confirm. That action rescans before removing entries from SQLite.

Run the same workflow from PowerShell, including when the browser server is stopped:

```powershell
.\.venv\Scripts\python.exe main.py sync
.\.venv\Scripts\python.exe main.py sync --remove-missing
```

A sync with unreadable files, online-only placeholders, or inaccessible subfolders keeps the previously indexed copies and skips removal. After OneDrive finishes downloading or a file is repaired, sync again. Atlas skips temporary Office owner files, symbolic links, and directory junctions. The app never deletes files from OneDrive.

The sync stores a SHA-256 digest for each managed source in SQLite. It reads locally available files to check their digests and embeds only new or changed files. The digest, excerpts, vectors, and keyword index are updated together after a successful import. Synced documents are scoped to their configured folder and embedding model. Browser uploads and standalone CLI imports remain separate. Switching folders preserves entries from earlier folders. Use a fresh database for a separate company collection or remove old entries through **Indexed documents**.


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
| `GET /sync` | Check whether a local sync folder is configured. |
| `POST /sync` | Scan and index folder changes. Add `?remove_missing=true` to remove missing entries after a clean scan. |
| `GET /documents` | List indexed sources and their excerpt counts for the active embedding model. |
| `DELETE /documents?source=...` | Remove a source from the active model’s index. Use the exact source identifier from the list. |
| `GET /health` | Check whether the server is responding. |

## Architecture

```text
Upload, CLI source, or local folder -> loader -> overlapping chunks -> OpenAI embeddings -> SQLite
Question -> SQLite keyword search + embedding similarity -> merged ranking -> Serbian answer
```

- `main.py` wires together the CLI and FastAPI server. Uploads, CLI imports, and folder sync share the indexer and loader in `src/ingestion`, with separate parsers in `pdf.py`, `word.py`, `excel.py`, and `powerpoint.py`.
- `src/api` provides the upload and query endpoints. `src/api/web` contains the HTML, CSS, and JavaScript for Atlas.
- `src/chunking` normalizes whitespace and creates overlapping character windows. `src/embeddings` batches embedding requests. `src/vectordb` runs exact cosine search over the stored vectors for the active embedding model.
- `src/retrieval`, `src/prompts`, and `src/llm` use the top matches to generate answers. Source metadata preserves page numbers, section headings, worksheet rows, slide numbers, and CSV record numbers.
- `config.yaml` sets the models, chunk size and overlap, database path, and number of matches. Relative database paths are resolved from the repository root. Reindex your sources after changing the embedding model or chunk settings.
- Keep local source files under `Documents/` or point the CLI to another folder. Git ignores new files under `Documents/`, plus `.env`, the default database under `data/`, and logs.

Ingestion sends extracted text to OpenAI for embedding. Queries send the question and retrieved excerpts to OpenAI for answer generation.

## Hybrid retrieval

Atlas combines vector similarity with SQLite FTS5 search over excerpt text, filenames, and source locations such as Word headings and Excel sheet names. Keyword search matches Serbian Latin and Cyrillic through a normalized index. Reciprocal Rank Fusion merges the two ranked lists. Exact references such as `UG-42/2025` or `C12` get a ranking boost, and citations retain the original text and location.

The first startup builds the keyword index from existing SQLite chunks. It uses no new embedding requests and requires no reuploads. Adds, replacements, and deletions update both indexes in the same transaction.

In `config.yaml`, set `retrieval.mode` to `vector` to compare against vector-only search. The default is `hybrid`. `candidate_k` controls the number of candidates from each search, and `top_k` controls how many excerpts are passed to the answer model.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use a temporary SQLite database and simulated model responses, so they run without an API key. They cover document loading, Office citations, PDF rendering with simulated OCR, hybrid retrieval and keyword backfill, multi-file uploads, the local sync lifecycle, and live indexing progress for uploads and sync.

## References

- [OpenAI Embeddings API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)
- [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
- [FastAPI testing guide](https://fastapi.tiangolo.com/tutorial/testing/)
