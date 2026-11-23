from pathlib import PureWindowsPath
import re
import unicodedata

SERBIAN_CYRILLIC = str.maketrans(dict(zip(
    "абвгдђежзијклљмнњопрстћуфхцчџш",
    ("a", "b", "v", "g", "d", "dj", "e", "ž", "z", "i", "j", "k", "l", "lj",
     "m", "n", "nj", "o", "p", "r", "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š"),
    strict=True,
)))

TERM = re.compile(r"[^\W_]+")
REFERENCE = re.compile(r"[a-z0-9]+(?:[-_/.:][a-z0-9]+)*")


def normalize_text(text: str) -> str:
    text = text.casefold().translate(SERBIAN_CYRILLIC).replace("đ", "dj")
    return "".join(
        character for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def reference_tokens(text: str) -> list[str]:
    tokens = []
    for match in REFERENCE.finditer(text):
        value = match.group()
        if any(character.isdigit() for character in value) and (
            any(character.isalpha() for character in value)
            or any(separator in value for separator in "-_/")
        ):
            tokens.append("ref" + value.encode("utf-8").hex())
    return list(dict.fromkeys(tokens))


def keyword_row(
    model: str, source: str, ordinal: int, location: str, content: str,
) -> tuple[str, str, str, str, str, int]:
    name = source if source.lower().startswith(("http://", "https://")) else PureWindowsPath(source).name
    context = normalize_text(f"{name}\n{location}")
    text = normalize_text(content)
    # Include the stem so identifiers in filenames survive the extension.
    stem = normalize_text(PureWindowsPath(name).stem)
    references = reference_tokens(f"{context}\n{text}\n{stem}")
    return text, context, " ".join(references), model, source, ordinal


def keyword_query(question: str) -> tuple[str, list[str]]:
    normalized = normalize_text(question)
    references = reference_tokens(normalized)[:16]
    terms = list(dict.fromkeys(TERM.findall(normalized)))[:64]
    clauses = [f'identifiers:"{token}"' for token in references]
    clauses.extend(f'{{body context}}:"{term}"' for term in terms)
    return " OR ".join(clauses), references
