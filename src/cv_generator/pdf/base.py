"""The contract every PDF engine must satisfy.

Deliberately narrow: an engine receives a self-contained HTML document (styles
already inlined by the renderer) and writes a PDF. That keeps the choice of
engine -- headless Chrome, WeasyPrint, LaTeX via an intermediate conversion, or
something else -- an implementation detail.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable


@runtime_checkable
class PdfEngine(Protocol):
    """Writes a PDF from a self-contained HTML document."""

    name: ClassVar[str]

    def is_available(self) -> bool:
        """Whether this engine's runtime dependencies are installed."""
        ...

    def render(self, html: str, output: Path) -> None:
        """Write ``html`` to ``output`` as a PDF.

        Raises:
            PdfEngineError: if the engine is unavailable or conversion fails.
        """
        ...
