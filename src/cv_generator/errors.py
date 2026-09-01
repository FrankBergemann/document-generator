"""Exception hierarchy for document-generator."""

from __future__ import annotations


class DocError(Exception):
    """Base class for every error this package raises deliberately."""


class DocParseError(DocError):
    """The source Markdown file could not be parsed or validated."""


class RenderError(DocError):
    """A template could not be found or rendered."""


class PdfEngineError(DocError):
    """A PDF engine was requested that is unavailable or failed."""
