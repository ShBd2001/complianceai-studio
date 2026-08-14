"""Depot, verification d'integrite et decoupage des documents audites."""

from __future__ import annotations

import hashlib
import io
import logging
import re
import uuid
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

# Une politique de confidentialite type fait 3 a 5 pages. A 1400 caracteres,
# elle ne produisait que 3 fragments : la section securite se retrouvait noyee
# avec les durees de conservation et les sous-traitants, et la recherche par
# similarite rendait un contexte flou. A 700, chaque section du document forme
# un fragment distinct.
CHUNK_CHARS = 700
CHUNK_OVERLAP = 150


def storage_root() -> Path:
    root = Path(settings.STORAGE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_document(org_id: uuid.UUID, filename: str, content: bytes) -> tuple[str, str]:
    """Ecrit le fichier et retourne (cle de stockage, empreinte SHA-256).

    Le nom d'origine n'est jamais utilise comme chemin : un nom controle par
    l'utilisateur permettrait une traversee de repertoire.
    """
    digest = hashlib.sha256(content).hexdigest()
    suffix = Path(filename).suffix.lower()[:10] or ".bin"
    key = f"{org_id}/{digest[:2]}/{digest}{suffix}"

    target = storage_root() / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return key, digest


def read_document(storage_key: str) -> bytes:
    return (storage_root() / storage_key).read_bytes()


def extract_text(content: bytes, mime_type: str) -> str:
    if mime_type == "application/pdf":
        return _extract_pdf(content)
    if mime_type.endswith("wordprocessingml.document"):
        return _extract_docx(content)
    return content.decode("utf-8", errors="replace")


def _extract_pdf(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.error("pypdf absent : impossible de lire le PDF.")
        return ""
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(content: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        logger.error("python-docx absent : impossible de lire le DOCX.")
        return ""
    document = docx.Document(io.BytesIO(content))
    return "\n".join(p.text for p in document.paragraphs)


def chunk_text(text: str) -> list[str]:
    """Decoupage par paragraphes agreges, avec recouvrement.

    Contrairement aux exigences reglementaires (decoupees par article), un
    document client n'a pas de structure juridique fiable : on agrege donc les
    paragraphes jusqu'a une taille cible, avec un recouvrement pour ne pas
    perdre le sens a la frontiere de deux fragments.
    """
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buffer = ""

    for paragraph in paragraphs:
        if len(buffer) + len(paragraph) + 2 <= CHUNK_CHARS:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
            continue
        if buffer:
            chunks.append(buffer)
            buffer = buffer[-CHUNK_OVERLAP:] + "\n\n" + paragraph
        else:
            # Paragraphe seul plus long que la cible : decoupage dur.
            for i in range(0, len(paragraph), CHUNK_CHARS):
                chunks.append(paragraph[i : i + CHUNK_CHARS])
            buffer = ""

    if buffer:
        chunks.append(buffer)
    return chunks
