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
        batch = [
            ("files", ("fruit.txt", b"Green pear")),
            ("files", ("bad.pdf", b"Invalid PDF")),
            ("files", ("fruit.txt", b"Red apple")),
        ]
        assert client.post("/ingest", files=batch, headers={"Origin": "https://other.example"}).status_code == 403
        upload = client.post("/ingest", files=batch, headers={"Origin": "http://testserver"})
        assert upload.status_code == 200
        first, failed, last = upload.json()
        assert first == last == {"filename": "fruit.txt", "chunks": 1, "error": None}
        assert failed["filename"] == "bad.pdf"
        assert failed["error"]
        assert client.post("/ingest", files=[batch[0]]).json() == [first]

        result = client.post("/query", json={"question": "pear"}).json()
        assert result["answer"] == "Green pear"
        assert [hit["text"] for hit in result["sources"]] == ["Green pear", "Red apple"]
