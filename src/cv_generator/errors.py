"""Exception hierarchy for cv-generator."""

from __future__ import annotations


class CVError(Exception):
    """Base class for every error this package raises deliberately."""


class CVParseError(CVError):
    """The source Markdown file could not be parsed or validated."""


class RenderError(CVError):
    """A template could not be found or rendered."""


class PdfEngineError(CVError):
    """A PDF engine was requested that is unavailable or failed."""
