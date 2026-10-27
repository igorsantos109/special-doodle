import hashlib
from dataclasses import dataclass
from pathlib import Path

AUTHORIZED_ROOTS = [
    "/tmp",
    "/home/igor/pc-sala-agent",
]

DEPENDENCIES_SUGGESTED = [
    {"package": "pdfminer.six", "import": "pdfminer.high_level"},
    {"package": "python-docx", "import": "docx"},
    {"package": "openpyxl", "import": "openpyxl"},
    {"package": "Pillow", "import": "PIL"},
]


class DocumentError(Exception):
    pass


class UnauthorizedPath(Exception):
    pass


class ExtractionError(Exception):
    pass


@dataclass
class DocumentExtraction:
    origin: str
    hash_sha256: str
    method: str
    text: str
    error: str = ""
    page: int = 0
    total_pages: int = 0

    @property
    def has_text(self):
        return bool(self.text)


def resolve_path(path):
    p = Path(path)
    try:
        resolved = p.resolve(strict=False)
    except (OSError, RuntimeError):
        raise UnauthorizedPath(str(p))
    root = str(resolved)
    authorized = False
    for base in AUTHORIZED_ROOTS:
        try:
            resolved.relative_to(Path(base).resolve())
            authorized = True
            break
        except ValueError:
            pass
    if not authorized:
        raise UnauthorizedPath(str(resolved))
    return resolved


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract_text(path):
    p = resolve_path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise ExtractionError(str(exc))
    for encoding in ("utf-8",):
        try:
            return data.decode(encoding), "text-plain"
        except UnicodeDecodeError:
            continue
    try:
        return data.decode("latin-1"), "text-plain-fallback"
    except UnicodeDecodeError as exc:
        raise ExtractionError(str(exc))


def extract_document(path):
    p = resolve_path(path)
    origin = str(p)
    try:
        text, method = extract_text(p)
    except ExtractionError as exc:
        return DocumentExtraction(
            origin=origin, hash_sha256="", method="", text="", error=str(exc),
        )
    digest = hash_file(p)
    return DocumentExtraction(
        origin=origin, hash_sha256=digest, method=method, text=text, error="",
    )


def build_analysis_prompt(ext):
    parts = [
        "CONTEUDO EXTRAIDO",
        f"Origem: {ext.origin}",
        f"SHA-256: {ext.hash_sha256}",
        f"Metodo: {ext.method}",
    ]
    if ext.page:
        parts.append(f"Pagina: {ext.page}")
    if ext.total_pages:
        parts.append(f"Total de paginas: {ext.total_pages}")
    parts.extend([
        "citacao direta",
        "inferencia",
        ext.text,
        "FIM DO CONTEUDO EXTRAIDO",
    ])
    return "\n".join(parts)
