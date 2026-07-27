"""Extract deterministic, ordered sections from a Document B DOCX."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from io import BytesIO
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import OpcError
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError

HEADING_STYLE_NAME_PATTERN = re.compile(r"^heading\s+(\d+)$", re.IGNORECASE)
HEADING_STYLE_ID_PATTERN = re.compile(r"^heading(\d+)$", re.IGNORECASE)
NUMBERED_HEADING_PATTERN = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+)*)(?:[.)])?\s+(?P<title>.+?)\s*$"
)
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")
MAX_SECTION_ID_LENGTH = 255


class DocumentBExtractionError(ValueError):
    """Raised when a DOCX cannot provide a reliable heading structure."""


@dataclass(frozen=True, slots=True)
class ExtractedDocumentBSection:
    """One non-overlapping Document B section in source order."""

    section_id: str
    heading_number: str | None
    heading_title: str
    heading_level: int
    sequence: int
    section_text: str


@dataclass(slots=True)
class _SectionBuilder:
    heading_number: str | None
    heading_title: str
    heading_level: int
    path_slugs: tuple[str, ...]
    blocks: list[str] = field(default_factory=list)


def extract_document_b_sections(content: bytes) -> tuple[ExtractedDocumentBSection, ...]:
    """Extract heading sections, tables, and preamble content from DOCX bytes."""

    try:
        document = Document(BytesIO(content))
    except (BadZipFile, KeyError, OpcError, ValueError, XMLSyntaxError) as error:
        raise DocumentBExtractionError(
            "The stored Document B is not a readable DOCX document."
        ) from error

    builders: list[_SectionBuilder] = []
    hierarchy: dict[int, str] = {}
    current: _SectionBuilder | None = None
    preamble: _SectionBuilder | None = None
    heading_count = 0

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            heading = _heading(item)
            if heading is not None:
                heading_number, heading_title, heading_level = heading
                heading_count += 1
                hierarchy = {
                    level: slug for level, slug in hierarchy.items() if level < heading_level
                }
                title_slug = _slug(heading_title)
                hierarchy[heading_level] = title_slug
                path_slugs = tuple(
                    hierarchy[level] for level in sorted(hierarchy) if level <= heading_level
                )
                current = _SectionBuilder(
                    heading_number=heading_number,
                    heading_title=heading_title,
                    heading_level=heading_level,
                    path_slugs=path_slugs,
                )
                builders.append(current)
                continue
            block = _paragraph_block(item)
        elif isinstance(item, Table):
            block = _table_block(item)
        else:
            continue

        if not block:
            continue
        if current is None:
            if preamble is None:
                preamble = _SectionBuilder(
                    heading_number=None,
                    heading_title="Document preamble",
                    heading_level=0,
                    path_slugs=("document-preamble",),
                )
                builders.append(preamble)
            preamble.blocks.append(block)
        else:
            current.blocks.append(block)

    if heading_count == 0:
        raise DocumentBExtractionError(
            "Document B contains no recognised headings. Apply Word Heading styles "
            "or use bold numbered headings."
        )

    identifiers: dict[str, int] = {}
    extracted: list[ExtractedDocumentBSection] = []
    for sequence, builder in enumerate(builders, start=1):
        base_id = (
            f"section-{_slug(builder.heading_number)}"
            if builder.heading_number is not None
            else "-".join(builder.path_slugs)
        )
        base_id = _bounded_id(base_id)
        occurrence = identifiers.get(base_id, 0) + 1
        identifiers[base_id] = occurrence
        section_id = base_id if occurrence == 1 else _bounded_id(f"{base_id}-{occurrence}")
        extracted.append(
            ExtractedDocumentBSection(
                section_id=section_id,
                heading_number=builder.heading_number,
                heading_title=builder.heading_title,
                heading_level=builder.heading_level,
                sequence=sequence,
                section_text="\n\n".join(builder.blocks),
            )
        )
    return tuple(extracted)


def _heading(paragraph: Paragraph) -> tuple[str | None, str, int] | None:
    text = _normalise_text(paragraph.text)
    if not text:
        return None

    style_level = _style_heading_level(paragraph)
    numbered = NUMBERED_HEADING_PATTERN.match(text)
    if style_level is not None:
        if numbered is None:
            return None, text, style_level
        number = numbered.group("number").rstrip(".")
        return number, numbered.group("title").strip(), style_level

    if numbered is None or not _is_conservative_numbered_fallback(paragraph):
        return None
    number = numbered.group("number").rstrip(".")
    title = numbered.group("title").strip()
    return number, title, number.count(".") + 1


def _style_heading_level(paragraph: Paragraph) -> int | None:
    for value, pattern in (
        (paragraph.style.style_id, HEADING_STYLE_ID_PATTERN),
        (paragraph.style.name, HEADING_STYLE_NAME_PATTERN),
    ):
        match = pattern.fullmatch(value)
        if match is not None:
            return int(match.group(1))
    return None


def _is_conservative_numbered_fallback(paragraph: Paragraph) -> bool:
    """Require heading-like formatting so numbered body lists remain body content."""

    visible_runs = [run for run in paragraph.runs if run.text.strip()]
    all_bold = bool(visible_runs) and all(run.bold is True for run in visible_runs)
    style_name = paragraph.style.name.casefold()
    heading_named_style = "heading" in style_name or "title" in style_name
    return all_bold or heading_named_style


def _paragraph_block(paragraph: Paragraph) -> str:
    text = _normalise_text(paragraph.text)
    if not text:
        return ""
    if paragraph.style.name.casefold().startswith("list") and not re.match(
        r"^(?:[-*•]|\d+[.)])\s+",
        text,
    ):
        return f"- {text}"
    return text


def _table_block(table: Table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells = [" ".join(_normalise_text(cell.text).splitlines()) for cell in row.cells]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _normalise_text(value: str) -> str:
    return " ".join(value.split())


def _slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").casefold()
    )
    slug = SLUG_PATTERN.sub("-", ascii_value).strip("-")
    return slug or "untitled"


def _bounded_id(value: str) -> str:
    if len(value) <= MAX_SECTION_ID_LENGTH:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    prefix_length = MAX_SECTION_ID_LENGTH - len(digest) - 1
    return f"{value[:prefix_length].rstrip('-')}-{digest}"
