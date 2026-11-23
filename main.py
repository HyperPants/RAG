import argparse
import csv
import os

from openai import OpenAI, OpenAIError
import httpx
from pypdf.errors import PyPdfError
import uvicorn

from src.api.routes import create_app
from src.embeddings.embedder import Embedder
from src.embeddings.errors import embedding_error_message
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
        if args.command == "serve":
            retriever = Retriever(embedder, store, **config["retrieval"])
            uvicorn.run(create_app(retriever, LLMClient(client, models["answer"]), indexer),
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
