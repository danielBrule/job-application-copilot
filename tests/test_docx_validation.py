"""Tests for uploaded DOCX validation."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from docx import Document

from job_application_copilot.documents import (
    MAX_DOCX_BYTES,
    DocxValidationError,
    docx_validation,
    validate_docx,
)


def make_docx(text: str = "Reference content") -> bytes:
    buffer = BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


def make_zip(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_accepts_readable_docx_with_case_insensitive_extension() -> None:
    validate_docx("Document-A.DOCX", make_docx())


@pytest.mark.parametrize("filename", ["document.doc", "document.docm", "document", "document.txt"])
def test_rejects_unsupported_extension(filename: str) -> None:
    with pytest.raises(DocxValidationError, match=r"\.docx extension"):
        validate_docx(filename, make_docx())


def test_rejects_empty_file() -> None:
    with pytest.raises(DocxValidationError, match="empty"):
        validate_docx("document.docx", b"")


def test_rejects_upload_larger_than_five_mib() -> None:
    with pytest.raises(DocxValidationError, match="5 MiB"):
        validate_docx("document.docx", b"x" * (MAX_DOCX_BYTES + 1))


def test_rejects_non_zip_content_renamed_as_docx() -> None:
    with pytest.raises(DocxValidationError, match="not a valid DOCX archive"):
        validate_docx("document.docx", b"not a zip archive")


def test_rejects_zip_that_is_not_a_docx() -> None:
    content = make_zip({"notes.txt": b"not an office package"})

    with pytest.raises(DocxValidationError, match="not a readable DOCX"):
        validate_docx("document.docx", content)


def test_rejects_docx_with_malformed_xml() -> None:
    source = ZipFile(BytesIO(make_docx()))
    entries = {name: source.read(name) for name in source.namelist()}
    source.close()
    entries["word/document.xml"] = b"<w:document>"

    with pytest.raises(DocxValidationError, match="not a readable DOCX"):
        validate_docx("document.docx", make_zip(entries))


def test_rejects_archive_over_uncompressed_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docx_validation, "MAX_DOCX_UNCOMPRESSED_BYTES", 10)
    content = make_zip({"large.txt": b"x" * 11})

    with pytest.raises(DocxValidationError, match="100 MiB uncompressed"):
        validate_docx("document.docx", content)
