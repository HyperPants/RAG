from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True)
class ProgressSnapshot:
    stage: Literal["scanning", "reading", "embedding", "saving", "removing"] = "scanning"
    total: int = 0
    completed: int = 0
    filename: str = ""
    excerpts_done: int = 0
    excerpts_total: int = 0


class IndexProgress:
    def __init__(self) -> None:
        self.snapshot = ProgressSnapshot()

    def file(self, total: int, completed: int, filename: str) -> None:
        self.snapshot = ProgressSnapshot("reading", total, completed, filename)

    def embedding(self, done: int, total: int) -> None:
        self.snapshot = replace(
            self.snapshot, stage="embedding", excerpts_done=done, excerpts_total=total,
        )

    def saving(self) -> None:
        self.snapshot = replace(self.snapshot, stage="saving")

    def removing(self) -> None:
        self.snapshot = ProgressSnapshot("removing")
