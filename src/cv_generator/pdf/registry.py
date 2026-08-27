"""Engine lookup.

``chrome`` is implemented. The other entries are backends that were considered
and not built; they are recorded here so the trade-off stays visible in code
rather than only in a chat log, and so ``cv-generator engines`` can explain why
a name is rejected.

To implement one: add a module in this package with a class satisfying
:class:`~cv_generator.pdf.base.PdfEngine`, then map its name to a zero-argument
factory in ``_FACTORIES``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cv_generator.errors import PdfEngineError
from cv_generator.pdf.base import PdfEngine
from cv_generator.pdf.chrome import BROWSER_WS_ENV, ChromeEngine


@dataclass(frozen=True)
class EngineInfo:
    """Documentation for a PDF backend, implemented or not."""

    name: str
    summary: str
    trade_off: str
    dependencies: str


KNOWN_ENGINES: tuple[EngineInfo, ...] = (
    EngineInfo(
        name="chrome",
        summary=(
            "Render the HTML in headless Chromium via Playwright and print to PDF. "
            "The browser runs here, or in another container over a websocket."
        ),
        trade_off=(
            "Best CSS fidelity and debuggable in a real browser; needs a ~150 MB browser "
            "download, unless a Playwright server supplies one."
        ),
        dependencies=(
            'pip install "cv-generator[pdf]", then either `playwright install chromium` '
            f"or {BROWSER_WS_ENV}=ws://host:port/ pointing at `playwright run-server`"
        ),
    ),
    EngineInfo(
        name="weasyprint",
        summary="Pure-Python HTML/CSS to PDF, no browser involved.",
        trade_off="Lightweight and hermetic; supports only a subset of CSS (flex/grid gaps).",
        dependencies="weasyprint (needs pango/cairo system libraries)",
    ),
    EngineInfo(
        name="latex",
        summary="Emit LaTeX from the model instead of HTML, then compile with pdflatex.",
        trade_off="Best typography; needs a TeX install and a second template language.",
        dependencies="a TeX distribution (texlive-latex-recommended or similar)",
    ),
)

_FACTORIES: dict[str, Callable[[], PdfEngine]] = {
    "chrome": ChromeEngine,
}


def engine_info(name: str) -> EngineInfo | None:
    """Look up the documentation for an engine by name."""
    return next((info for info in KNOWN_ENGINES if info.name == name), None)


def implemented_engines() -> list[str]:
    """Names of engines that have an implementation, installed or not."""
    return sorted(_FACTORIES)


def available_engines() -> list[str]:
    """Names of engines that are implemented *and* whose dependencies resolve."""
    return sorted(name for name, factory in _FACTORIES.items() if factory().is_available())


def get_engine(name: str) -> PdfEngine:
    """Instantiate the engine called ``name``.

    Availability is deliberately *not* checked here. Probing whether a browser
    is installed is a heuristic (see :meth:`ChromeEngine.is_available`), and a
    false negative must never block an engine that would in fact work. An engine
    reports missing runtime dependencies itself, from the real failure.

    Raises:
        PdfEngineError: if the name is unknown or names a documented but unbuilt
            backend.
    """
    factory = _FACTORIES.get(name)
    if factory is None:
        info = engine_info(name)
        if info is not None:
            raise PdfEngineError(
                f"PDF engine {name!r} is documented but not implemented.\n"
                f"  {info.summary}\n"
                f"  Trade-off:    {info.trade_off}\n"
                f"  Dependencies: {info.dependencies}\n"
                f"Implemented engines: {', '.join(implemented_engines())}."
            )
        names = ", ".join(info.name for info in KNOWN_ENGINES)
        raise PdfEngineError(f"unknown PDF engine {name!r}; known names are: {names}")

    return factory()
