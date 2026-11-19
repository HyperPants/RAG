# RAG

A local retrieval-augmented generation (RAG) app for asking questions about your documents. Its browser interface, **Marginalia**, lets you upload multiple files, ask questions, and inspect the source excerpts behind each answer.

## Quick start

Install Python 3.12 or later. From the repository root in PowerShell, create a virtual environment and install the dependencies. If you already have a `.venv`, rerun just the second command to install the upload dependency.

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
2. In **Add documents**, click **Choose files** or drag files onto the drop zone. You can add multiple PDFs, UTF-8 CSVs, plain text files, or Markdown files in one batch. PDFs need an extractable text layer.
3. Wait for the per-file indexing results. Successful files are ready to query immediately, even if some files in the batch fail.
4. Ask a question, such as “What methods did the papers use?” Select a numbered citation in the answer to open the retrieved excerpt and see its source location.

Open **Indexed documents** to see the saved sources and excerpt counts. The list updates after uploads. Use **Refresh** after indexing files or URLs from another terminal. To remove an outdated source, choose **Delete** next to it and confirm. This removes its excerpts and embeddings for the active model from the index. The original file stays on disk. The extracted excerpts and vectors persist in SQLite across restarts. Marginalia checks for matching files and identical indexed excerpts before embedding an upload. If it finds a match, you can skip the file or choose **Upload anyway**. Confirming an identical upload with the same name refreshes its existing entry. A matching file with a different name gets a separate entry.

## CLI and API

The CLI also accepts HTTP(S) pages. To index multiple files or URLs, pass each as a separate argument.

```powershell
.\.venv\Scripts\python.exe main.py ingest ".\Documents\2404.03936v2.pdf" "https://example.com"
```

Use [Swagger UI](http://127.0.0.1:8000/docs) to try the API while the server is running.

| Endpoint | Purpose |
| --- | --- |
| `POST /ingest` | Upload a multipart request with one or more `files` fields. Returns a result for each file, including any duplicate match. Use `allow_duplicate=true` to explicitly index matching files. |
| `POST /query` | Send JSON such as `{"question": "What were the main findings?"}`. Returns an answer and retrieved excerpts with citations, locations, and cosine scores. |
| `GET /documents` | List indexed sources and their excerpt counts for the active embedding model. |
| `DELETE /documents?source=...` | Remove a source from the active model’s index. Use the exact source identifier from the list. |
| `GET /health` | Check whether the server is responding. |

## Architecture

```text
Upload or CLI source -> loader -> overlapping chunks -> OpenAI embeddings -> SQLite
Question -> OpenAI embedding -> SQLite cosine search -> prompt -> OpenAI answer
```

- `main.py` wires together the CLI and FastAPI server. Both ingestion paths share the indexer in `src/ingestion`.
- `src/api` provides the upload and query endpoints. `src/api/web` contains the HTML, CSS, and JavaScript for Marginalia.
- `src/chunking` normalizes whitespace and creates overlapping character windows. `src/embeddings` batches embedding requests. `src/vectordb` runs exact cosine search over the stored vectors for the active embedding model.
- `src/retrieval`, `src/prompts`, and `src/llm` use the top matches to generate answers. Source metadata preserves PDF page numbers and CSV record numbers.
- `config.yaml` sets the models, chunk size and overlap, database path, and number of matches. Relative database paths are resolved from the repository root. Reindex your sources after changing the embedding model or chunk settings.
- Git ignores `.env`, the default database under `data/`, and `logs/app.log`.

Ingestion sends extracted text to OpenAI for embedding. Queries send the question and retrieved excerpts to OpenAI for answer generation.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use a temporary SQLite database and simulated model responses, so they run without an API key. They cover document loading, chunking, retrieval, and partial success in a multi-file upload.

## References

- [OpenAI Embeddings API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)
- [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
- [FastAPI testing guide](https://fastapi.tiangolo.com/tutorial/testing/)
