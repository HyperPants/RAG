import csv
from dataclasses import dataclass, field
from hashlib import file_digest, sha256
import os
from pathlib import Path
import sqlite3
import stat
from threading import Lock

from openai import OpenAIError
from pypdf.errors import PyPdfError

from src.embeddings.errors import embedding_error_message
from src.ingestion.indexer import Indexer
from src.ingestion.loader import SUPPORTED_SUFFIXES
from src.ingestion.progress import IndexProgress

# Win32 FILE_ATTRIBUTE_OFFLINE, RECALL_ON_OPEN and RECALL_ON_DATA_ACCESS.
CLOUD_ONLY_ATTRIBUTES = 0x1000 | 0x40000 | 0x400000


class LocalFileUnavailable(OSError):
    pass


class SyncBusy(RuntimeError):
    pass


@dataclass
class SyncReport:
    added: int = 0
    modified: int = 0
    unchanged: int = 0
    deleted: int = 0
    missing: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def local_stat(path: Path) -> os.stat_result:
    status = path.lstat()
    if getattr(status, "st_file_attributes", 0) & CLOUD_ONLY_ATTRIBUTES:
        raise LocalFileUnavailable("Not fully downloaded. In OneDrive, choose Always keep on this device.")
    return status


def signature(status: os.stat_result) -> tuple[int, int, int, int, int]:
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns


class FolderSync:
    def __init__(self, root: Path, indexer: Indexer):
        self.root = Path(os.path.abspath(root))
        self.indexer = indexer
        self.store = indexer.store
        root_key = sha256(os.path.normcase(str(self.root)).encode("utf-8")).hexdigest()
        self.prefix = f"onedrive/{root_key}/"
        self.lock = Lock()

    def _root_identity(self) -> tuple[int, int]:
        status = local_stat(self.root)
        if not stat.S_ISDIR(status.st_mode) or self.root.is_junction():
            raise LocalFileUnavailable("The configured path must be a local directory.")
        return status.st_dev, status.st_ino

    def _scan(self, errors: dict[str, str]) -> dict[str, Path]:
        files = {}
        folders = [self.root]
        while folders:
            folder = folders.pop()
            try:
                if not stat.S_ISDIR(local_stat(folder).st_mode) or folder.is_junction():
                    raise LocalFileUnavailable("A folder changed or is unavailable.")
                with os.scandir(folder) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        relative = path.relative_to(self.root).as_posix()
                        if entry.name.startswith("~$"):
                            continue
                        try:
                            status = entry.stat(follow_symlinks=False)
                            if stat.S_ISLNK(status.st_mode) or entry.is_junction():
                                if entry.is_dir() or path.suffix.lower() in SUPPORTED_SUFFIXES:
                                    errors[relative] = "Links and junctions are skipped."
                                continue
                            is_directory = stat.S_ISDIR(status.st_mode)
                            if not is_directory and path.suffix.lower() not in SUPPORTED_SUFFIXES:
                                continue
                            if getattr(status, "st_file_attributes", 0) & CLOUD_ONLY_ATTRIBUTES:
                                raise LocalFileUnavailable("Not fully downloaded. Make it available offline in OneDrive.")
                            if is_directory:
                                folders.append(path)
                            elif stat.S_ISREG(status.st_mode):
                                files[relative] = path
                        except LocalFileUnavailable as error:
                            errors[relative] = str(error)
                        except OSError:
                            errors[relative] = "Could not inspect this entry."
            except OSError:
                errors[folder.relative_to(self.root).as_posix()] = "Could not list this folder."
        return files

    def _process_file(
        self, path: Path, source: str, previous: str | None, progress: IndexProgress | None,
    ) -> str:
        before = local_stat(path)
        if not stat.S_ISREG(before.st_mode):
            raise LocalFileUnavailable("This path is no longer a regular file.")
        expected = signature(before)

        def check_current() -> None:
            if signature(local_stat(path)) != expected:
                raise LocalFileUnavailable("The file changed during synchronization. Try again after OneDrive finishes.")

        with path.open("rb") as stream:
            # Windows may expose creation time through lstat and change time through fstat.
            if signature(os.fstat(stream.fileno()))[:4] != expected[:4]:
                raise LocalFileUnavailable("The file changed before it could be read. Try again.")
            digest = file_digest(stream, "sha256").hexdigest()
            check_current()
            if digest == previous:
                return "unchanged"
            stream.seek(0)
            self.indexer.index_synced_file(source, stream, path.suffix.lower(), digest, previous, check_current, progress)
        return "added" if previous is None else "modified"

    def run(
        self, *, remove_missing: bool = False, progress: IndexProgress | None = None,
    ) -> SyncReport:
        if not self.lock.acquire(blocking=False):
            raise SyncBusy("A folder sync is already running.")
        try:
            return self._run(remove_missing=remove_missing, progress=progress)
        finally:
            self.lock.release()

    def _run(self, *, remove_missing: bool, progress: IndexProgress | None) -> SyncReport:
        report = SyncReport()
        try:
            identity = self._root_identity()
        except OSError:
            report.errors["."] = "The configured folder is unavailable. The index was left intact."
            return report

        previous = self.store.synced_documents(self.prefix)
        files = self._scan(report.errors)
        for completed, (relative, path) in enumerate(sorted(files.items())):
            if progress is not None:
                progress.file(len(files), completed, relative)
            source = self.prefix + relative
            try:
                outcome = self._process_file(path, source, previous.get(source), progress)
                setattr(report, outcome, getattr(report, outcome) + 1)
            except OpenAIError as error:
                report.errors[relative] = embedding_error_message(error)
            except (LocalFileUnavailable, ValueError) as error:
                report.errors[relative] = str(error)
            except (OSError, PyPdfError, csv.Error, sqlite3.Error):
                report.errors[relative] = "Could not read or index this file. Any existing entry was kept."

        if not report.errors:
            report.missing = sorted(source[len(self.prefix):] for source in previous if source[len(self.prefix):] not in files)
            if remove_missing and report.missing:
                if progress is not None:
                    progress.removing()
                self._remove_missing(report, previous, files, identity)
        return report

    def _remove_missing(
        self, report: SyncReport, previous: dict[str, str],
        files: dict[str, Path], identity: tuple[int, int],
    ) -> None:
        rescanned = self._scan(report.errors)
        try:
            if self._root_identity() != identity or files.keys() != rescanned.keys():
                raise LocalFileUnavailable("The folder changed while syncing. No missing documents were removed.")
        except OSError:
            report.errors["."] = "The folder changed or became unavailable. No missing documents were removed."
        if report.errors:
            return

        for relative in report.missing[:]:
            path = self.root / relative
            try:
                path.lstat()
            except FileNotFoundError:
                source = self.prefix + relative
                try:
                    deleted = self.store.delete_document(source, expected_digest=previous[source])
                except sqlite3.Error:
                    report.errors[relative] = "Could not update the index. Try again."
                    continue
                if deleted:
                    report.deleted += 1
                    report.missing.remove(relative)
                else:
                    report.errors[relative] = "The index changed during synchronization. Try again."
            except OSError:
                report.errors[relative] = "Could not verify that the file is absent. The indexed version was kept."
            else:
                report.errors[relative] = "The file is present locally. The indexed version was kept."
