from pathlib import Path
from types import SimpleNamespace

from docx import Document
from fastapi.testclient import TestClient

from src.api.routes import create_app
from src.ingestion.folder_sync import FolderSync, LocalFileUnavailable
from src.ingestion.indexer import Indexer
from src.prompts.prompt_templates import render_question
from src.retrieval.retriever import Retriever
from src.vectordb.vector_store import VectorStore


def save_contract(path: Path, text: str) -> None:
    document = Document()
    document.add_heading("Рок плаћања", 1)
    document.add_paragraph(text)
    document.save(path)


def test_local_sync_lifecycle_through_api(tmp_path):
    root = tmp_path / "OneDrive" / "Sample"
    folder = root / "Ugovori"
    folder.mkdir(parents=True)
    contract = folder / "UG-42.docx"
    save_contract(contract, "Рачун доспева за 30 дана.")
    (folder / "~$UG-42.docx").write_bytes(b"Office lock file")
    (folder / "ignore.zip").write_bytes(b"unsupported")

    calls = []

    def embed(texts):
        calls.append(texts)
        return [[1.0, 0.0] for _ in texts]

    embedder = SimpleNamespace(embed=embed)
    path = tmp_path / "index.sqlite3"
    store = VectorStore(path, "example")
    indexer = Indexer(embedder, store, size=400, overlap=0)
    unrelated = tmp_path / "manual.txt"
    unrelated.write_text("Manual document", encoding="utf-8")
    indexer.index_source(str(unrelated))

    def answer(question, hits):
        assert "Ugovori/UG-42.docx" in render_question(question, hits)
        assert "Рок плаћања" in hits[0].location
        return "Rok je 30 dana [1]."

    sync = FolderSync(root, indexer)
    app = create_app(Retriever(embedder, store, 3, mode="hybrid"), SimpleNamespace(answer=answer), indexer, folder_sync=sync)
    with TestClient(app) as client:
        assert client.get("/sync").json() == {"configured": True}
        assert client.post("/sync", headers={"Origin": "https://other.example"}).status_code == 403
        assert client.post("/sync").json() == {
            "added": 1, "modified": 0, "unchanged": 0, "deleted": 0, "duplicates": {}, "missing": [], "errors": {},
        }
        contract.touch()
        before = len(calls)
        assert client.post("/sync").json()["unchanged"] == 1
        assert len(calls) == before

        result = client.post("/query", json={"question": "Koji je rok plaćanja za UG-42?"}).json()
        assert result["answer"] == "Rok je 30 dana [1]."
        assert result["sources"][0]["source"].endswith("/Ugovori/UG-42.docx")
        assert str(root) not in result["sources"][0]["source"]

        source = result["sources"][0]["source"]
        save_contract(contract, "Рачун доспева за 60 дана.")
        assert client.post("/sync").json()["modified"] == 1
        assert not [hit for hit, _ in store.search_keywords("30", [1.0, 0.0], 5)]
        assert store.search_keywords("60", [1.0, 0.0], 5)[0][0].source == source

        contract.unlink()
        assert client.post("/sync").json()["missing"] == ["Ugovori/UG-42.docx"]
        assert any(row.source == source for row in store.list_documents())
        assert client.post("/sync?remove_missing=true").json()["deleted"] == 1
        assert not store.search_keywords("60", [1.0, 0.0], 5)
        assert [row.source for row in VectorStore(path, "example").list_documents()] == [str(unrelated.resolve())]


def test_sync_retains_entries_if_root_or_files_are_unavailable(tmp_path, monkeypatch):
    from src.ingestion import folder_sync

    root = tmp_path / "OneDrive"
    root.mkdir()
    first = root / "present.txt"
    first.write_text("Previously indexed", encoding="utf-8")
    second = root / "missing.txt"
    second.write_text("Another document", encoding="utf-8")
    calls = []
    embedder = SimpleNamespace(embed=lambda texts: calls.append(texts) or [[1.0] for _ in texts])
    store = VectorStore(tmp_path / "vectors.sqlite3", "example")
    sync = FolderSync(root, Indexer(embedder, store, size=200, overlap=0))
    assert sync.run().added == 2

    second.unlink()
    original_stat = folder_sync.local_stat

    def online_only(path):
        if path == first:
            raise LocalFileUnavailable("Not fully downloaded.")
        return original_stat(path)

    monkeypatch.setattr(folder_sync, "local_stat", online_only)
    result = sync.run(remove_missing=True)
    assert result.deleted == 0
    assert "present.txt" in result.errors
    assert len(store.list_documents()) == 2
    assert len(calls) == 2

    moved = root.with_name("Temporarily unavailable")
    root.rename(moved)
    assert sync.run(remove_missing=True).errors.keys() == {"."}
    assert len(store.list_documents()) == 2


def test_file_that_changes_during_embedding_keeps_previous_index(tmp_path):
    root = tmp_path / "OneDrive"
    root.mkdir()
    file = root / "plan.txt"
    file.write_text("Original", encoding="utf-8")

    def embed(texts):
        if texts == ["Intermediate"]:
            file.write_text("Final changed content", encoding="utf-8")
        return [[1.0] for _ in texts]

    store = VectorStore(tmp_path / "vectors.sqlite3", "example")
    sync = FolderSync(root, Indexer(SimpleNamespace(embed=embed), store, size=200, overlap=0))
    assert sync.run().added == 1
    file.write_text("Intermediate", encoding="utf-8")
    assert "plan.txt" in sync.run().errors
    assert store.search([1.0], 1)[0].text == "Original"
    assert sync.run().modified == 1
    assert store.search([1.0], 1)[0].text == "Final changed content"


def test_sync_indexes_one_copy_and_reuses_it_when_original_moves(tmp_path):
    root = tmp_path / "OneDrive"
    first = root / "Elaborati" / "CV.txt"
    second = root / "Prezentacije" / "CV.txt"
    different = root / "Razno" / "CV.txt"
    for path, content in [(first, "Unique biography"), (second, "Unique biography"), (different, "Another biography")]:
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")

    embedding_calls = []
    embedder = SimpleNamespace(embed=lambda texts: embedding_calls.append(texts) or [[1.0] for _ in texts])
    store = VectorStore(tmp_path / "index.sqlite3", "test")
    sync = FolderSync(root, Indexer(embedder, store, size=100, overlap=0))
    report = sync.run()
    assert report.added == 2
    assert report.duplicates == {"Prezentacije/CV.txt": "Elaborati/CV.txt"}
    assert len(embedding_calls) == 2
    assert store.search_keywords("unique", [1.0], 10)[0][0].source.endswith("/Elaborati/CV.txt")
    assert sync.run().unchanged == 2
    assert len(embedding_calls) == 2

    first.unlink()
    report = sync.run()
    assert not report.errors and not report.missing
    assert len(embedding_calls) == 2
    assert store.search_keywords("unique", [1.0], 10)[0][0].source.endswith("/Prezentacije/CV.txt")
    assert second.read_text(encoding="utf-8") == "Unique biography"
    assert len(store.list_documents()) == 2


def test_sync_consolidates_old_duplicates_without_reembedding(tmp_path):
    from hashlib import sha256

    from src.chunking.chunker import Chunk

    root = tmp_path / "OneDrive"
    content = b"Previously indexed"
    digest = sha256(content).hexdigest()
    embedder = SimpleNamespace(embed=lambda texts: (_ for _ in ()).throw(AssertionError("Unexpected embedding")))
    store = VectorStore(tmp_path / "index.sqlite3", "test")
    sync = FolderSync(root, Indexer(embedder, store, size=100, overlap=0))
    for relative in ("Elaborati/CV.txt", "Prezentacije/CV.txt"):
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
        store.replace(
            sync.prefix + relative, [Chunk(content.decode(), "document")], [[1.0]], sync_digest=digest,
        )

    report = sync.run()
    assert not report.errors
    assert report.duplicates == {"Prezentacije/CV.txt": "Elaborati/CV.txt"}
    assert len(store.list_documents()) == 1
    assert len(store.search_keywords("previously", [1.0], 10)) == 1
    assert (root / "Elaborati" / "CV.txt").is_file()
    assert (root / "Prezentacije" / "CV.txt").is_file()
