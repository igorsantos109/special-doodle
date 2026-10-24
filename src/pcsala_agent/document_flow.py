"""Fluxo documental basico: extracao e analise de documentos autorizados."""

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


class DocumentError(RuntimeError):
    pass


class UnauthorizedPath(DocumentError):
    pass


class ExtractionError(DocumentError):
    pass


AUTHORIZED_ROOTS: tuple[str, ...] = (
    "/home/igor/pc-sala-agent",
    "/home/igor/.config/pcsala-bonsai",
    "/tmp",
    "/var/lib/pcsala-worker",
)

EXTRACTION_METHODS_AVAILABLE: list[dict] = [
    {
        "method": "text-plain",
        "extensions": (".txt", ".md", ".py", ".sh", ".yaml", ".yml",
                       ".json", ".xml", ".csv", ".toml", ".cfg", ".conf",
                       ".ini", ".log", ".env", ".rst", ".tex", ".css",
                       ".js", ".html", ".htm", ".svg"),
        "description": "Leitura direta de texto UTF-8",
        "needs_dependency": None,
    },
    {
        "method": "text-with-fallback",
        "extensions": (),
        "description": "Leitura com fallback de codificacao (latin-1, cp1252)",
        "needs_dependency": None,
    },
]

DEPENDENCIES_SUGGESTED: list[dict] = [
    {
        "package": "pdfminer.six",
        "purpose": "Extracao de texto de PDF",
        "install_cmd": "pip install pdfminer.six",
        "extensions": (".pdf",),
    },
    {
        "package": "python-docx",
        "purpose": "Extracao de texto de DOCX",
        "install_cmd": "pip install python-docx",
        "extensions": (".docx",),
    },
    {
        "package": "openpyxl",
        "purpose": "Extracao de texto de XLSX",
        "install_cmd": "pip install openpyxl",
        "extensions": (".xlsx",),
    },
    {
        "package": "pytesseract + tesseract-ocr",
        "purpose": "OCR para imagens e PDFs escaneados",
        "install_cmd": "apt install tesseract-ocr && pip install pytesseract",
        "extensions": (".png", ".jpg", ".jpeg", ".tiff", ".bmp"),
    },
    {
        "package": "python-pptx",
        "purpose": "Extracao de texto de PPTX",
        "install_cmd": "pip install python-pptx",
        "extensions": (".pptx",),
    },
    {
        "package": "odfpy",
        "purpose": "Extracao de texto de ODT",
        "install_cmd": "pip install odfpy",
        "extensions": (".odt",),
    },
]


@dataclass(frozen=True)
class DocumentExtraction:
    origin: str
    hash_sha256: str
    method: str
    page: int | None = None
    total_pages: int | None = None
    text: str = ""
    error: str = ""
    result_reference: str = ""


def resolve_path(file_path: str) -> Path:
    path = Path(file_path).resolve()
    for root_str in AUTHORIZED_ROOTS:
        root = Path(root_str).resolve()
        try:
            path.relative_to(root)
            return path
        except ValueError:
            continue
    raise UnauthorizedPath(
        f"Caminho {file_path} nao esta em nenhuma raiz autorizada. "
        f"Raizes: {', '.join(AUTHORIZED_ROOTS)}"
    )


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def extract_text(path: Path) -> tuple[str, str]:
    """Extrai texto de um arquivo. Retorna (texto, metodo)."""
    if not path.is_file():
        raise ExtractionError(f"Arquivo nao encontrado: {path}")

    suffix = path.suffix.lower()

    try:
        text = path.read_text("utf-8")
        return text, "text-plain"
    except (UnicodeDecodeError, LookupError):
        pass

    for encoding in ("latin-1", "cp1252", "iso-8859-1"):
        try:
            text = path.read_text(encoding)
            return text, "text-plain-fallback"
        except (UnicodeDecodeError, LookupError):
            continue

    raise ExtractionError(
        f"Nao foi possivel extrair texto de {suffix}: "
        f"codificacao nao reconhecida. "
        f"Sugeridas: pdfminer.six para PDF, python-docx para DOCX."
    )


def extract_document(file_path: str) -> DocumentExtraction:
    path = resolve_path(file_path)
    original_bytes = path.read_bytes()
    content_hash = hash_file(path)
    text, method = extract_text(path)
    return DocumentExtraction(
        origin=str(path),
        hash_sha256=content_hash,
        method=method,
        text=text,
    )


def build_analysis_prompt(extraction: DocumentExtraction) -> str:
    lines = [
        "Analise o documento abaixo.",
        "",
        f"Origem: {extraction.origin}",
        f"Hash SHA-256: {extraction.hash_sha256}",
        f"Metodo de extracao: {extraction.method}",
    ]
    if extraction.page is not None:
        lines.append(f"Pagina: {extraction.page}")
    if extraction.total_pages is not None:
        lines.append(f"Total de paginas: {extraction.total_pages}")
    lines.append("")
    lines.append("--- CONTEUDO EXTRAIDO ---")
    lines.append(extraction.text)
    lines.append("--- FIM DO CONTEUDO EXTRAIDO ---")
    lines.append("")
    lines.append(
        "INSTRUCOES:\n"
        "- O que esta entre as marcacoes --- CONTEUDO EXTRAIDO --- "
        "e o que o documento diz literalmente.\n"
        "- Sua analise deve distinguir claramente "
        "o que e citacao direta do documento "
        "do que e inferencia sua.\n"
        "- Referencie sempre as unidades extraidas "
        "(paginas, linhas, secoes) quando possivel.\n"
        "- Nao invente informacoes que nao estao no documento."
    )
    return "\n".join(lines)