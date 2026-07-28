"""Shared pytest fixtures."""

from io import BytesIO

import pytest
from docx import Document

from job_application_copilot.config.document_b_routing import (
    load_document_b_routing_config,
)
from job_application_copilot.ui.dependencies import get_database


@pytest.fixture(autouse=True)
def clear_ui_database_cache() -> None:
    """Isolate Streamlit's cached database resource between tests."""

    get_database.clear()
    yield
    get_database.clear()


def make_routable_document_b(
    text: str = "Configured section content.",
    *,
    omitted_heading_paths: frozenset[tuple[str, ...]] = frozenset(),
) -> bytes:
    """Build a complete synthetic DOCX from the canonical exact heading paths."""

    config = load_document_b_routing_config()
    tree: dict[str, dict] = {}
    for catalog in config.section_catalog.values():
        if catalog.heading_path in omitted_heading_paths:
            continue
        node = tree
        for heading in catalog.heading_path:
            node = node.setdefault(heading, {})

    document = Document()

    def add_nodes(nodes: dict[str, dict], level: int) -> None:
        for heading, children in nodes.items():
            document.add_heading(heading, level=level)
            document.add_paragraph(text)
            add_nodes(children, level + 1)

    add_nodes(tree, 1)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
