from __future__ import annotations

from pathlib import Path

import pytest

from cv_generator.models import CV
from cv_generator.parser import parse_cv_file
from tests.support import DATA_DIR, PROJEKTLISTE_NAME, REPO_ROOT, write_projektliste

# A CV with a `## Projekte` section, whose body must be ignored in favour of the
# project list next to it. Deliberately not one of the files in tests/data: those
# have no such section, which is what keeps the plain Markdown path covered.
PROJECTS_MD = """---
name: Ada Lovelace
---

## Projekte

Dieser Text steht in der Markdown-Datei und darf nicht im Ergebnis landen.

## Kenntnisse

- Python
"""


@pytest.fixture
def minimal_path() -> Path:
    return DATA_DIR / "minimal.md"


@pytest.fixture
def minimal_cv(minimal_path: Path) -> CV:
    return parse_cv_file(minimal_path)


@pytest.fixture
def rich_path() -> Path:
    return DATA_DIR / "rich.md"


@pytest.fixture
def rich_cv(rich_path: Path) -> CV:
    return parse_cv_file(rich_path)


@pytest.fixture
def photo_path() -> Path:
    return DATA_DIR / "photo.md"


@pytest.fixture
def photo_cv(photo_path: Path) -> CV:
    return parse_cv_file(photo_path)


@pytest.fixture
def portrait_path() -> Path:
    """The image `photo.md` points at: 120x160 px, so 3:4 portrait."""
    return DATA_DIR / "portrait.png"


@pytest.fixture
def sample_cv_path() -> Path:
    return REPO_ROOT / "data" / "cv.md"


@pytest.fixture
def projects_path(tmp_path: Path) -> Path:
    """A CV file with a `## Projekte` section, next to a Word project list."""
    write_projektliste(tmp_path / PROJEKTLISTE_NAME)
    path = tmp_path / "cv.md"
    path.write_text(PROJECTS_MD, encoding="utf-8")
    return path


@pytest.fixture
def projects_cv(projects_path: Path) -> CV:
    return parse_cv_file(projects_path)
