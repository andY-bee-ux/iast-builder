"""app/extract_text.py"""
from pathlib import Path

NATIVE_TEXT_EXT = {".txt", ".md", ".csv", ".json", ".rtf"}


def extract_text(path: Path) -> tuple[str, str | None]:
    """Returns (text, error). error is None on success."""
    ext = path.suffix.lower()
    try:
        if ext in NATIVE_TEXT_EXT:
            return path.read_text(encoding="utf-8", errors="replace"), None

        if ext == ".docx":
            import docx

            d = docx.Document(str(path))
            return "\n".join(p.text for p in d.paragraphs), None

        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages), None

        return "", f"Format non pris en charge pour l'extraction automatique : {ext}"
    except Exception as exc:  # noqa: BLE001 — surfaced to the admin panel, not swallowed
        return "", str(exc)
