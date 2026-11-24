from contextlib import contextmanager
import csv
import logging
from pathlib import PureWindowsPath
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import OpenAIError
from pydantic import BaseModel, StringConstraints
from pypdf.errors import PyPdfError

from src.embeddings.errors import embedding_error_message
from src.ingestion.folder_sync import FolderSync, SyncBusy, SyncReport
from src.ingestion.indexer import DuplicateUpload, Indexer
from src.ingestion.progress import IndexProgress, ProgressSnapshot
from src.llm.llm_client import LLMClient
from src.prompts.prompt_templates import NO_SOURCES
from src.retrieval.retriever import Retriever
from src.vectordb.vector_store import IndexedDocument


class Question(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class Source(BaseModel):
    citation: int
    source: str
    location: str
    text: str
    score: float


class Answer(BaseModel):
    answer: str
    sources: list[Source]


class UploadResult(BaseModel):
    filename: str
    chunks: int | None = None
    error: str | None = None
    duplicate_source: str | None = None


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(status_code=403, detail="This action must come from this site.")


def create_app(
    retriever: Retriever, llm: LLMClient, indexer: Indexer | None = None, *,
    folder_sync: FolderSync | None = None,
) -> FastAPI:
    app = FastAPI(title="RAG")
    web_dir = Path(__file__).with_name("web")
    app.mount("/assets", StaticFiles(directory=web_dir), name="assets")

    active_progress: dict[UUID, IndexProgress] = {}
    progress_lock = Lock()

    @contextmanager
    def track_progress(progress_id: UUID | None):
        if progress_id is None:
            yield None
            return

        progress = IndexProgress()
        with progress_lock:
            if progress_id in active_progress:
                raise HTTPException(status_code=409, detail="This indexing request is already running.")
            active_progress[progress_id] = progress
        try:
            yield progress
        finally:
            with progress_lock:
                del active_progress[progress_id]

    @app.get("/indexing-progress/{progress_id}")
    def indexing_progress(progress_id: UUID) -> ProgressSnapshot | None:
        with progress_lock:
            progress = active_progress.get(progress_id)
            return progress.snapshot if progress is not None else None

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_dir / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/sync")
    def sync_configuration() -> dict[str, bool]:
        return {"configured": folder_sync is not None}

    @app.post("/sync")
    def synchronize(request: Request, remove_missing: bool = False, progress_id: UUID | None = None) -> SyncReport:
        require_same_origin(request)
        if folder_sync is None:
            raise HTTPException(status_code=503, detail="Set MARGINALIA_DOCUMENT_FOLDER in .env and restart Marginalia.")
        try:
            with track_progress(progress_id) as progress:
                return folder_sync.run(remove_missing=remove_missing, progress=progress)
        except SyncBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/documents")
    def documents() -> list[IndexedDocument]:
        return retriever.store.list_documents()

    @app.delete("/documents", status_code=204)
    def delete_document(request: Request, source: str) -> Response:
        require_same_origin(request)
        if not retriever.store.delete_document(source):
            raise HTTPException(status_code=404, detail="This document is no longer indexed.")
        return Response(status_code=204)

    @app.post("/ingest", response_model=list[UploadResult])
    def ingest(
        request: Request,
        files: Annotated[list[UploadFile], File()],
        allow_duplicate: bool = False,
        progress_id: UUID | None = None,
    ) -> list[UploadResult]:
        require_same_origin(request)
        if indexer is None:
            raise HTTPException(status_code=503, detail="Document indexing is unavailable.")

        with track_progress(progress_id) as progress:
            results = []
            for completed, upload in enumerate(files):
                filename = PureWindowsPath(upload.filename or "").name or "Unnamed file"
                if progress is not None:
                    progress.file(len(files), completed, filename)
                try:
                    count = indexer.index_upload(filename, upload.file, allow_duplicate=allow_duplicate, progress=progress)
                    results.append(UploadResult(filename=filename, chunks=count))
                except DuplicateUpload as error:
                    results.append(UploadResult(filename=filename, duplicate_source=error.source))
                except OpenAIError as error:
                    results.append(UploadResult(filename=filename, error=embedding_error_message(error)))
                except UnicodeError:
                    results.append(UploadResult(filename=filename, error="Save the file as UTF-8 and try again."))
                except (PyPdfError, csv.Error):
                    results.append(UploadResult(filename=filename, error="The document could not be read."))
                except ValueError as error:
                    results.append(UploadResult(filename=filename, error=str(error)))
                except (OSError, sqlite3.Error):
                    logging.exception("Failed to index uploaded document")
                    results.append(UploadResult(filename=filename, error="The server could not index this file."))
            return results

    @app.post("/query", response_model=Answer)
    def query(payload: Question) -> Answer:
        try:
            hits = retriever.retrieve(payload.question)
            answer = llm.answer(payload.question, hits) if hits else NO_SOURCES
        except OpenAIError as error:
            logging.error("OpenAI request failed (%s)", type(error).__name__)
            raise HTTPException(status_code=502, detail="The model provider request failed.") from error
        sources = [
            Source(citation=index, source=hit.source, location=hit.location, text=hit.text, score=hit.score)
            for index, hit in enumerate(hits, 1)
        ]
        return Answer(answer=answer, sources=sources)

    return app
