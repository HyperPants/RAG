import json
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Protocol

import keyring

from src.ingestion.folder_sync import FolderSync
from src.ingestion.indexer import Indexer

SERVICE = "Marginalia"
ACCOUNT = "OpenAI API key"


class CredentialVault(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...


class LocalSettings:
    def __init__(self, directory: Path, *, vault: CredentialVault = keyring) -> None:
        self.path = directory / "settings.json"
        self.vault = vault
        self.lock = RLock()
        self._key = None
        self._sync = None
        self._folder = None
        try:
            self._key = vault.get_password(SERVICE, ACCOUNT)
        except Exception as error:
            # Keep setup available even if the credential store cannot be opened.
            logging.warning("Could not read the system credential store (%s)", type(error).__name__)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._folder = data.get("document_folder")

    def api_key(self) -> str:
        with self.lock:
            return self._key or os.getenv("OPENAI_API_KEY", "").strip()

    def folder(self) -> str:
        with self.lock:
            if self._folder is not None:
                return self._folder
            return os.getenv("MARGINALIA_DOCUMENT_FOLDER", "").strip()

    def folder_sync(self, root: Path, indexer: Indexer) -> FolderSync | None:
        with self.lock:
            value = self.folder()
            if not value:
                self._sync = None
                return None
            path = Path(os.path.abspath(root / Path(os.path.expandvars(value)).expanduser()))
            if self._sync is None or self._sync.root != path:
                self._sync = FolderSync(path, indexer)
            return self._sync

    def save(self, api_key: str | None, folder: str | None) -> None:
        key = api_key.strip() if api_key else ""
        if key and (len(key) > 1024 or any(not char.isascii() or char.isspace() for char in key)):
            raise ValueError("Paste the secret API key as a single line.")
        if folder is not None:
            folder = folder.strip().strip('"')
            if folder:
                path = Path(os.path.expandvars(folder)).expanduser()
                if not path.is_absolute() or not path.is_dir():
                    raise ValueError("Choose an existing folder on this computer.")
                folder = str(path)

        with self.lock:
            if key:
                try:
                    self.vault.set_password(SERVICE, ACCOUNT, key)
                except Exception as error:
                    raise keyring.errors.KeyringError("Could not write to the system credential store.") from error
                self._key = key
            if folder is not None and folder != self.folder():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent, delete=False,
                ) as stream:
                    temp_path = Path(stream.name)
                    try:
                        json.dump({"document_folder": folder}, stream)
                    except BaseException:
                        stream.close()
                        temp_path.unlink(missing_ok=True)
                        raise
                try:
                    temp_path.replace(self.path)
                finally:
                    temp_path.unlink(missing_ok=True)
                self._folder = folder
