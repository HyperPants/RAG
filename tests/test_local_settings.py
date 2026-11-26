import json

from fastapi.testclient import TestClient
import httpx
from openai import OpenAI

from src.api import local_app
from src.utils.settings import LocalSettings


class MemoryVault:
    key = None

    def get_password(self, service, username):
        return self.key

    def set_password(self, service, username, password):
        self.key = password


def test_first_run_settings_enable_sync_without_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MARGINALIA_DOCUMENT_FOLDER", raising=False)
    folder = tmp_path / "OneDrive" / "Documents"
    folder.mkdir(parents=True)
    (folder / "plan.txt").write_text("Rok je 30 dana.", encoding="utf-8")
    requests = []

    def fake_openai(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    monkeypatch.setattr(local_app, "OpenAI", lambda **kwargs: OpenAI(
        **kwargs, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(fake_openai)),
    ))
    vault = MemoryVault()
    data = tmp_path / "settings"
    settings = LocalSettings(data, vault=vault)
    config = {
        "models": {"embedding": "test-embedding", "answer": "test-answer"},
        "chunking": {"size": 100, "overlap": 0},
        "retrieval": {"top_k": 2},
    }
    with local_app.browser_app(
        config, database=tmp_path / "index.sqlite3", settings=settings, folder_picker=lambda: str(folder),
    ) as app, TestClient(app, base_url="http://localhost:8000") as client:
        home = client.get("/")
        assert home.status_code == 200
        assert 'href="/ocr-setup"' in home.text
        guide = client.get("/ocr-setup")
        assert guide.status_code == 200
        assert 'id="macos"' in guide.text and 'id="windows"' in guide.text
        assert "brew install tesseract-lang" in guide.text
        assert "srp_latn" in guide.text
        assert client.get("/settings").json() == {
            "key_configured": False, "document_folder": "", "can_browse": True,
        }
        assert client.post("/query", json={"question": "Koji je rok?"}).status_code == 503
        assert client.post("/sync").status_code == 503
        denied = client.put("/settings", json={"api_key": "test-key"}, headers={"Origin": "http://other.local"})
        assert denied.status_code == 403
        assert client.get("/settings", headers={"Host": "example.com"}).status_code == 400
        assert client.post("/settings/browse").json() == {"folder": str(folder)}
        invalid = client.put("/settings", json={"api_key": "test-key", "document_folder": "invalid"})
        assert invalid.status_code == 422
        assert vault.key is None

        saved = client.put("/settings", json={"api_key": "test-key", "document_folder": str(folder)})
        assert saved.status_code == 200
        assert saved.json()["key_configured"] is True
        assert "test-key" not in saved.text
        assert client.get("/sync").json() == {"configured": True}
        assert client.post("/sync").json()["added"] == 1
        assert client.get("/documents").json()[0]["source"].endswith("/plan.txt")

    assert len(requests) == 1
    assert json.loads((data / "settings.json").read_text(encoding="utf-8")) == {"document_folder": str(folder)}
    reloaded = LocalSettings(data, vault=vault)
    assert reloaded.api_key() == "test-key"
    assert reloaded.folder() == str(folder)


def test_missing_credential_store_does_not_prevent_first_run(tmp_path, monkeypatch):
    import keyring
    import pytest

    class UnavailableVault:
        def get_password(self, service, username):
            raise RuntimeError("Credential store unavailable")

        def set_password(self, service, username, password):
            raise RuntimeError("Credential store unavailable")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = LocalSettings(tmp_path, vault=UnavailableVault())
    assert settings.api_key() == ""
    with pytest.raises(keyring.errors.KeyringError):
        settings.save("test-key", None)
    assert not (tmp_path / "settings.json").exists()
