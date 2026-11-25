from types import SimpleNamespace

from src.api import local_app
from src.ingestion import folder_sync, pdf


def test_windows_data_directory_stays_compatible(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(local_app, "sys", SimpleNamespace(platform="win32"))
    assert local_app.user_data_directory() == tmp_path / "Marginalia"


def test_macos_data_directory_uses_application_support(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "unrelated"))
    monkeypatch.setattr(local_app, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(local_app.Path, "home", staticmethod(lambda: tmp_path))
    assert local_app.user_data_directory() == tmp_path / "Library" / "Application Support" / "Atlas"


def test_macos_and_windows_cloud_flags(monkeypatch):
    monkeypatch.setattr(folder_sync, "platform", "darwin")
    assert folder_sync.is_cloud_only(SimpleNamespace(st_flags=0x40000000))
    assert not folder_sync.is_cloud_only(SimpleNamespace(st_flags=0))
    monkeypatch.setattr(folder_sync, "platform", "win32")
    assert folder_sync.is_cloud_only(SimpleNamespace(st_file_attributes=0x400000))
    assert not folder_sync.is_cloud_only(SimpleNamespace(st_file_attributes=0))


def test_macos_ocr_finds_homebrew_from_finder(monkeypatch):
    from pathlib import PurePosixPath

    class HomebrewPath(PurePosixPath):
        def is_file(self):
            return str(self) == "/opt/homebrew/bin/tesseract"

    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    monkeypatch.setattr(pdf, "os", SimpleNamespace(name="posix", getenv=pdf.os.getenv))
    monkeypatch.setattr(pdf, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(pdf, "Path", HomebrewPath)
    monkeypatch.setattr(pdf.shutil, "which", lambda command: None)

    def run(command, **kwargs):
        assert command[0] == "/opt/homebrew/bin/tesseract"
        return SimpleNamespace(returncode=0, stdout=b"OCR text")

    monkeypatch.setattr(pdf.subprocess, "run", run)
    assert pdf.recognize_page(b"image", 1) == "OCR text"
