# RAG

A local retrieval-augmented generation starter. Index PDFs with extractable text, UTF-8 CSVs, plain text, Markdown, and HTTP(S) pages. Ask questions through FastAPI and get an answer with numbered citations and the retrieved excerpts.

## Setup and run

Install Python 3.12 or later. From the repository root in PowerShell, run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in the local `.env` file. For a fresh clone, create it with `Copy-Item .env.example .env` first. Exported environment variables take precedence over `.env`.

Index a file or URL, then start the API:

```powershell
.\.venv\Scripts\python.exe main.py ingest "C:\path\to\document.pdf" "https://example.com"
.\.venv\Scripts\python.exe main.py serve
```

Open [Swagger UI](http://127.0.0.1:8000/docs) and call `POST /query` with a JSON body such as `{"question": "What does the document say about refunds?"}`. The response contains the answer and a list of excerpts with citation numbers, source paths or URLs, locations, and cosine scores. `GET /health` checks that the API responds.

## Architecture

```text
Index  File or URL -> loader -> overlapping chunks -> OpenAI embeddings -> SQLite
Query  Question -> OpenAI embedding -> SQLite cosine search -> prompt -> OpenAI answer
```

- `main.py` wires the CLI and API together. `src/ingestion` keeps PDF page and CSV record locations so the API can report where each excerpt came from.
- `src/chunking` uses character windows after normalizing whitespace. `src/embeddings` batches requests. `src/vectordb` stores normalized vectors and scans the active model's vectors for exact cosine similarity. This setup is suited to a small local corpus.
- `src/retrieval`, `src/prompts`, and `src/llm` build answers from the top matches. `src/api` exposes them on localhost.
- `config.yaml` sets the models, chunk size and overlap in characters, database path, and number of matches. Relative database paths are resolved from the repository root. Reingesting a source replaces its chunks for the active model after its embeddings succeed. Reingest after changing the embedding model or chunk settings.
- Logs go to `logs/app.log`. Git ignores logs, the local SQLite database under `data/`, and `.env`.

Ingestion sends chunks to OpenAI for embedding. Queries send the question and retrieved excerpts to OpenAI for answer generation. Website ingestion reads returned HTML and PDF ingestion extracts the text layer.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use a temporary SQLite database and simulated OpenAI responses, so they run without an API key.

## References

- [OpenAI Embeddings API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)
- [OpenAI Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
- [FastAPI testing guide](https://fastapi.tiangolo.com/tutorial/testing/)
