import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.api.routes import create_app
from src.chunking.chunker import split_documents
from src.embeddings.embedder import Embedder
from src.ingestion.loader import Document, load_documents
from src.llm.llm_client import LLMClient
from src.retrieval.retriever import Retriever
from src.vectordb.vector_store import VectorStore


def test_chunk_overlap_and_location():
    chunks = split_documents([Document("abcdefghi", "page 2")], size=5, overlap=2)
    assert [chunk.text for chunk in chunks] == ["abcde", "defgh", "ghi"]
    assert {chunk.location for chunk in chunks} == {"page 2"}


def test_csv_retrieval_and_query(tmp_path):
    def embed(model, input, encoding_format):
        return SimpleNamespace(data=[
            SimpleNamespace(index=index, embedding=[1.0, 0.0] if "pear" in text else [0.0, 1.0])
            for index, text in reversed(list(enumerate(input)))
        ])

    def respond(model, instructions, input, store):
        payload = json.loads(input)
        assert payload["excerpts"] == [{"citation": "[1]", "text": "fruit: pear, color: green"}]
        return SimpleNamespace(output_text="The pear is green [1].")

    provider = SimpleNamespace(
        embeddings=SimpleNamespace(create=embed),
        responses=SimpleNamespace(create=respond),
    )
    vector_store = VectorStore(tmp_path / "vectors.sqlite3", "test-model")
    embedder = Embedder(provider, "test-model")
    retriever = Retriever(embedder, vector_store, top_k=1)
    app = create_app(retriever, LLMClient(provider, "test-answer"))
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/query", json={"question": " "}).status_code == 422
        assert client.post("/query", json={"question": "pear"}).json()["sources"] == []

        path = tmp_path / "fruit.csv"
        path.write_text("fruit,color\napple,red\npear,green\n", encoding="utf-8")
        source, documents = load_documents(str(path))
        chunks = split_documents(documents, size=100, overlap=0)
        vector_store.replace(source, chunks, embedder.embed([chunk.text for chunk in chunks]))

        result = client.post("/query", json={"question": "What color is the pear?"})
        assert result.status_code == 200
        assert result.json()["answer"] == "The pear is green [1]."
        assert result.json()["sources"] == [
            {"citation": 1, "source": source, "location": "record 2",
             "text": "fruit: pear, color: green", "score": 1.0}
        ]

        vector_store.replace(source, chunks[:1], [[0.0, 1.0]])
        assert [hit.location for hit in vector_store.search([1.0, 0.0], 5)] == ["record 1"]
        assert not VectorStore(vector_store.path, "other-model").has_chunks()



def test_load_website(monkeypatch):
    import httpx

    def get(url, follow_redirects, timeout):
        return httpx.Response(
            200, text="<main>A reference.</main><script>hidden()</script>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", get)
    url = "https://example.com/reference"
    assert load_documents(url) == (url, [Document("A reference.", "web page")])


def test_load_pdf(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    path = tmp_path / "reference.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=100)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 50 Td (A PDF reference.) Tj ET")
    page.replace_contents(stream)
    writer.write(path)

    assert load_documents(str(path)) == (
        str(path.resolve()), [Document("A PDF reference.", "page 1")]
    )


def test_multi_file_upload_indexes_successes_for_immediate_retrieval(tmp_path):
    from src.ingestion.indexer import Indexer

    class TestEmbedder:
        def embed(self, texts):
            return [[1.0, 0.0] if "pear" in text else [0.0, 1.0] for text in texts]

    embedder = TestEmbedder()
    store = VectorStore(tmp_path / "vectors.sqlite3", "test-model")
    indexer = Indexer(embedder, store, size=100, overlap=0)
    llm = SimpleNamespace(answer=lambda question, hits: hits[0].text)
    app = create_app(Retriever(embedder, store, top_k=3), llm, indexer)
    with TestClient(app) as client:
        assert client.get("/documents").json() == []
        batch = [
            ("files", ("fruit.txt", b"Green pear")),
            ("files", ("bad.pdf", b"Invalid PDF")),
            ("files", ("fruit.txt", b"Red apple")),
        ]
        assert client.post("/ingest", files=batch, headers={"Origin": "https://other.example"}).status_code == 403
        upload = client.post("/ingest", files=batch, headers={"Origin": "http://testserver"})
        assert upload.status_code == 200
        first, failed, last = upload.json()
        assert first == last == {"filename": "fruit.txt", "chunks": 1, "error": None, "duplicate_source": None}
        assert failed["filename"] == "bad.pdf"
        assert failed["error"]
        duplicate = client.post("/ingest", files=[batch[0]]).json()[0]
        assert duplicate["duplicate_source"].endswith("/fruit.txt")
        assert duplicate["chunks"] is None
        assert client.post("/ingest?allow_duplicate=true", files=[batch[0]]).json() == [first]

        result = client.post("/query", json={"question": "pear"}).json()
        assert result["answer"] == "Green pear"
        assert [hit["text"] for hit in result["sources"]] == ["Green pear", "Red apple"]

    legacy_source = str(tmp_path / "imported.txt")
    cli_file = tmp_path / "imported.txt"
    cli_file.write_text("Imported document", encoding="utf-8")
    indexer.index_source(legacy_source)
    other_store = VectorStore(store.path, "other-model")
    other_file = tmp_path / "ignored.txt"
    other_file.write_text("Different model", encoding="utf-8")
    Indexer(embedder, other_store, size=100, overlap=0).index_source(str(other_file))

    reopened = VectorStore(store.path, "test-model")
    with TestClient(create_app(Retriever(embedder, reopened, top_k=3), llm)) as client:
        documents = client.get("/documents").json()
        assert len(documents) == 3
        assert sorted(document["source"].split("/")[-1] for document in documents if document["source"].startswith("uploads/")) == [
            "fruit.txt", "fruit.txt"
        ]
        assert {"source": legacy_source, "chunks": 1} in documents
        assert all(document["chunks"] == 1 for document in documents)


def test_duplicate_upload_skips_embeddings_until_confirmed(tmp_path):
    from src.ingestion.indexer import Indexer

    calls = []

    def embed(texts):
        calls.append(texts)
        return [[1.0] for _ in texts]

    embedder = SimpleNamespace(embed=embed)
    store = VectorStore(tmp_path / "vectors.sqlite3", "test-model")
    indexer = Indexer(embedder, store, size=100, overlap=0)
    path = tmp_path / "cli.txt"
    path.write_text("Existing excerpt", encoding="utf-8")
    indexer.index_source(str(path))

    app = create_app(Retriever(embedder, store, top_k=1), None, indexer)
    with TestClient(app) as client:
        duplicate = ("files", ("renamed.txt", b"Existing  excerpt"))
        new_file = ("files", ("fresh.txt", b"New excerpt"))
        renamed_new_file = ("files", ("another.txt", b"New excerpt"))
        response = client.post("/ingest", files=[duplicate, new_file, renamed_new_file])
        assert response.status_code == 200
        matched, indexed, matched_in_batch = response.json()
        assert matched["duplicate_source"] == str(path.resolve())
        assert indexed["chunks"] == 1
        assert matched_in_batch["duplicate_source"].endswith("/fresh.txt")
        assert calls == [["Existing excerpt"], ["New excerpt"]]
        assert len(client.get("/documents").json()) == 2

        confirmed = client.post("/ingest?allow_duplicate=true", files=[duplicate]).json()[0]
        assert confirmed["chunks"] == 1
        assert confirmed["duplicate_source"] is None
        assert len(client.get("/documents").json()) == 3
        assert calls[-1] == ["Existing excerpt"]


def test_delete_document_removes_only_selected_source_and_model(tmp_path):
    from src.ingestion.indexer import Indexer

    embedder = SimpleNamespace(embed=lambda texts: [[1.0] for _ in texts])
    store = VectorStore(tmp_path / "vectors.sqlite3", "active-model")
    other_model = VectorStore(store.path, "other-model")
    old_file = tmp_path / "old & outdated.txt"
    old_file.write_text("Old document", encoding="utf-8")
    current_file = tmp_path / "current.txt"
    current_file.write_text("Current document", encoding="utf-8")
    indexer = Indexer(embedder, store, size=5, overlap=0)
    indexer.index_source(str(old_file))
    indexer.index_source(str(current_file))
    Indexer(embedder, other_model, size=5, overlap=0).index_source(str(old_file))

    llm = SimpleNamespace(answer=lambda question, hits: hits[0].text)
    app = create_app(Retriever(embedder, store, top_k=10), llm, indexer)
    params = {"source": str(old_file)}
    with TestClient(app) as client:
        forbidden = client.delete("/documents", params=params, headers={"Origin": "https://other.example"})
        assert forbidden.status_code == 403
        assert len(client.get("/documents").json()) == 2
        removed = client.delete("/documents", params=params, headers={"Origin": "http://testserver"})
        assert removed.status_code == 204
        assert client.delete("/documents", params=params).status_code == 404
        response = client.post("/query", json={"question": "What is indexed?"})
        assert response.status_code == 200
        assert {hit["source"] for hit in response.json()["sources"]} == {str(current_file)}

    assert old_file.read_text(encoding="utf-8") == "Old document"
    assert [row.source for row in other_model.list_documents()] == [str(old_file)]
    reopened = VectorStore(store.path, "active-model")
    assert [row.source for row in reopened.list_documents()] == [str(current_file)]
