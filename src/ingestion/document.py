from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    text: str
    location: str
    embed_location: bool = False
