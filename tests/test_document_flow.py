import hashlib
import tempfile
from pathlib import Path

import pytest

from pcsala_agent.document_flow import (
    DocumentError, UnauthorizedPath, ExtractionError,
    extract_document, extract_text, resolve_path, hash_file,
    build_analysis_prompt, DocumentExtraction,
    AUTHORIZED_ROOTS, DEPENDENCIES_SUGGESTED,
)


def test_authorized_roots_include_working_dir():
    assert any("/home/igor/pc-sala-agent" in r for r in AUTHORIZED_ROOTS)


def test_resolve_path_authorized_tmp():
    path = resolve_path("/tmp/test.txt")
    assert str(path) == "/tmp/test.txt"


def test_resolve_path_authorized_project():
    path = resolve_path("/home/igor/pc-sala-agent/src/pcsala_agent/document_flow.py")
    assert "document_flow.py" in str(path)


def test_resolve_path_unauthorized():
    with pytest.raises(UnauthorizedPath):
        resolve_path("/etc/shadow")


def test_resolve_path_relative_escapes():
    with pytest.raises(UnauthorizedPath):
        resolve_path("/home/igor/../../etc/shadow")


def test_hash_file():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("conteudo de teste")
        f.flush()
        path = Path(f.name)
    try:
        h = hash_file(path)
        expected = hashlib.sha256(b"conteudo de teste").hexdigest()
        assert h == expected
    finally:
        path.unlink(missing_ok=True)


def test_extract_text_utf8():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt",
                                      encoding="utf-8") as f:
        f.write("Texto UTF-8: Olá Mundo!")
        f.flush()
        path = Path(f.name)
    try:
        text, method = extract_text(path)
        assert text == "Texto UTF-8: Olá Mundo!"
        assert method == "text-plain"
    finally:
        path.unlink(missing_ok=True)


def test_extract_text_latin1():
    import os
    data = "Texto Latin-1: Olá Mundo!".encode("latin-1")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        f.write(data)
        f.flush()
        path = Path(f.name)
    try:
        text, method = extract_text(path)
        assert method == "text-plain-fallback"
    finally:
        path.unlink(missing_ok=True)


def test_extract_text_nonexistent():
    with pytest.raises(ExtractionError):
        extract_text(Path("/tmp/nao_existe_12345.txt"))


def test_extract_document_synthetic():
    content = "Documento sintetico de teste.\nLinha 2.\nLinha 3."
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt",
                                      encoding="utf-8") as f:
        f.write(content)
        f.flush()
        path = Path(f.name)
    try:
        result = extract_document(str(path))
        assert isinstance(result, DocumentExtraction)
        assert result.origin == str(path)
        assert len(result.hash_sha256) == 64
        assert result.method == "text-plain"
        assert "sintetico" in result.text
        assert result.error == ""
    finally:
        path.unlink(missing_ok=True)


def test_build_analysis_prompt():
    ext = DocumentExtraction(
        origin="/tmp/teste.txt",
        hash_sha256="a" * 64,
        method="text-plain",
        text="Conteudo do documento.",
    )
    prompt = build_analysis_prompt(ext)
    assert "CONTEUDO EXTRAIDO" in prompt
    assert "FIM DO CONTEUDO EXTRAIDO" in prompt
    assert "inferencia" in prompt.lower()
    assert "citacao direta" in prompt
    assert "Conteudo do documento." in prompt


def test_build_analysis_prompt_with_pages():
    ext = DocumentExtraction(
        origin="/tmp/relatorio.pdf",
        hash_sha256="b" * 64,
        method="pdfminer",
        page=3,
        total_pages=10,
        text="Texto da pagina 3.",
    )
    prompt = build_analysis_prompt(ext)
    assert "Pagina: 3" in prompt
    assert "Total de paginas: 10" in prompt


def test_dependencies_listed():
    assert len(DEPENDENCIES_SUGGESTED) >= 4
    names = [d["package"] for d in DEPENDENCIES_SUGGESTED]
    assert "pdfminer.six" in names
    assert "python-docx" in names