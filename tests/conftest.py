from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cv_generator.models import Document
from cv_generator.parser import load_doc, parse_doc_file
from tests.support import DATA_DIR, PROJEKTLISTE_NAME, REPO_ROOT, write_projektliste

# The Markdown half of an assembled document. Its `## Projekte` section is the
# negative control: the recipe below never asks for it, so anything under it that
# reaches the output means a span was copied that nobody asked for.
#
# Deliberately not one of the files in tests/data: those are built from a single
# `.md` with no recipe at all, which is what keeps that path covered.
PROJECTS_MD = """---
name: Ada Lovelace
---

Ein Kurzprofil.

## Berufserfahrung

- Analyst

## Projekte

Dieser Text steht in der Markdown-Datei und darf nicht im Ergebnis landen.

## Kenntnisse

- Python
"""

# The canonical shape, and the one data/config.json has: a first entry with no
# `begin`, so it starts at the top of the Markdown file and brings the header
# with it, then Word, then Markdown again.
PROJECTS_CONFIG: dict[str, Any] = {
    "sections": [
        {"source": "document.md", "format": "md", "end": "Projekte"},
        {
            "source": PROJEKTLISTE_NAME,
            "format": "docx",
            "begin": "Projekthistorie",
            "end": "Ausbildung",
            "title": "Projekte",
        },
        {"source": "document.md", "format": "md", "begin": "Kenntnisse"},
    ],
}


def write_config(directory: Path, config: dict[str, Any]) -> Path:
    """Write a `config.json` into `directory` and return its path."""
    path = directory / "config.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def minimal_path() -> Path:
    return DATA_DIR / "minimal.md"


@pytest.fixture
def minimal_document(minimal_path: Path) -> Document:
    return parse_doc_file(minimal_path)


@pytest.fixture
def rich_path() -> Path:
    return DATA_DIR / "rich.md"


@pytest.fixture
def rich_document(rich_path: Path) -> Document:
    return parse_doc_file(rich_path)


@pytest.fixture
def photo_path() -> Path:
    return DATA_DIR / "photo.md"


@pytest.fixture
def photo_document(photo_path: Path) -> Document:
    return parse_doc_file(photo_path)


@pytest.fixture
def portrait_path() -> Path:
    """The image `photo.md` points at: 120x160 px, so 3:4 portrait."""
    return DATA_DIR / "portrait.png"


@pytest.fixture
def sample_doc_path() -> Path:
    return REPO_ROOT / "data" / "document.md"


@pytest.fixture
def sample_config_path() -> Path:
    return REPO_ROOT / "data" / "config.json"


@pytest.fixture
def projects_dir(tmp_path: Path) -> Path:
    """A directory holding a Markdown Document, a Word project list and a recipe."""
    write_projektliste(tmp_path / PROJEKTLISTE_NAME)
    (tmp_path / "document.md").write_text(PROJECTS_MD, encoding="utf-8")
    write_config(tmp_path, PROJECTS_CONFIG)
    return tmp_path


@pytest.fixture
def projects_path(projects_dir: Path) -> Path:
    """The recipe that assembles those files into one document."""
    return projects_dir / "config.json"


@pytest.fixture
def projects_document(projects_path: Path) -> Document:
    return load_doc(projects_path).doc
