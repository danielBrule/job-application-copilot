"""Safety-focused validation for uploaded DOCX files."""

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.opc.exceptions import OpcError
from lxml.etree import XMLSyntaxError

MAX_DOCX_UPLOAD_SIZE_MB = 5
MAX_DOCX_BYTES = MAX_DOCX_UPLOAD_SIZE_MB * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


class DocxValidationError(ValueError):
    """Raised when uploaded content is not a safe, readable DOCX package."""


def validate_docx(filename: str, content: bytes) -> None:
    """Validate the extension, upload size, archive size, and DOCX package."""

    if Path(filename).suffix.lower() != ".docx":
        raise DocxValidationError("The uploaded file must use the .docx extension.")
    if not content:
        raise DocxValidationError("The uploaded DOCX is empty.")
    if len(content) > MAX_DOCX_BYTES:
        raise DocxValidationError("The uploaded DOCX exceeds the 5 MiB safety limit.")

    try:
        with ZipFile(BytesIO(content)) as archive:
            if any(info.flag_bits & 0x1 for info in archive.infolist()):
                raise DocxValidationError("Encrypted DOCX archives are not supported.")
            uncompressed_size = sum(info.file_size for info in archive.infolist())
            if uncompressed_size > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocxValidationError(
                    "The DOCX archive exceeds the 100 MiB uncompressed safety limit."
                )
            if archive.testzip() is not None:
                raise DocxValidationError("The uploaded DOCX archive is corrupt.")
    except BadZipFile as error:
        raise DocxValidationError("The uploaded file is not a valid DOCX archive.") from error

    try:
        Document(BytesIO(content))
    except (BadZipFile, KeyError, OpcError, ValueError, XMLSyntaxError) as error:
        raise DocxValidationError("The uploaded file is not a readable DOCX document.") from error
