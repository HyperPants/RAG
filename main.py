import argparse
import csv
from dataclasses import asdict
import json
import os
from pathlib import Path

from openai import OpenAI, OpenAIError
import httpx
from pypdf.errors import PyPdfError
import uvicorn

from src.api.routes import create_app
from src.embeddings.embedder import Embedder
from src.embeddings.errors import embedding_error_message
from src.ingestion.folder_sync import FolderSync
from src.ingestion.indexer import Indexer
from src.llm.llm_client import LLMClient
from src.retrieval.retriever import Retriever
from src.utils.helpers import ROOT, configure_logging, load_config
from src.vectordb.vector_store import VectorStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Index documents and serve the RAG API.")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Index local files and HTTP(S) pages.")
    ingest.add_argument("sources", nargs="+")
    sync = commands.add_parser("sync", help="Synchronize the configured local document folder.")
    sync.add_argument("--remove-missing", action="store_true", help="Remove missing documents from the index.")
    serve = commands.add_parser("serve", help="Start the query API on localhost.")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    configure_logging()
    config = load_config()
    if not os.getenv("OPENAI_API_KEY", "").strip():
        parser.error("Set OPENAI_API_KEY in .env or in your environment.")

    with OpenAI() as client:
        models = config["models"]
        embedder = Embedder(client, models["embedding"])
        store = VectorStore(ROOT / config["database"]["path"], embedder.model)
        indexer = Indexer(embedder, store, **config["chunking"])
        folder_setting = os.getenv("MARGINALIA_DOCUMENT_FOLDER", "").strip()
        folder_sync = FolderSync(ROOT / Path(os.path.expandvars(folder_setting)).expanduser(), indexer) if folder_setting else None
        if args.command == "sync":
            if folder_sync is None:
                parser.error("Set MARGINALIA_DOCUMENT_FOLDER in .env before running sync.")
            report = folder_sync.run(remove_missing=args.remove_missing)
            print(json.dumps(asdict(report), indent=2))
            if report.errors:
                raise SystemExit(1)
            return
        if args.command == "serve":
            retriever = Retriever(embedder, store, **config["retrieval"])
            uvicorn.run(create_app(retriever, LLMClient(client, models["answer"]), indexer, folder_sync=folder_sync),
                        host="127.0.0.1", port=args.port)
            return

        for source in args.sources:
            try:
                count = indexer.index_source(source)
            except OpenAIError as error:
                parser.exit(1, f"{embedding_error_message(error)}\n")
            except (OSError, ValueError, httpx.HTTPError, PyPdfError, csv.Error) as error:
                parser.exit(1, f"Cannot index {source}: {error}\n")
            print(f"Indexed {count} chunks from {source}")


if __name__ == "__main__":
    main()
