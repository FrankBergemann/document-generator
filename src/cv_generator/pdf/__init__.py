"""PDF output.

Everything here talks to the :class:`~cv_generator.pdf.base.PdfEngine` protocol,
so adding a backend is one class plus one registry entry -- no changes to the
parser, model, templates or CLI.

``chrome`` (headless Chromium via Playwright) is the implemented engine; see
``registry.py`` for the alternatives that were considered. Its browser may be
installed locally or reached over a websocket in another container -- see
``chrome.py``.
"""

from __future__ import annotations

from cv_generator.pdf.base import PdfEngine
from cv_generator.pdf.chrome import BROWSER_WS_ENV, ChromeEngine, remote_endpoint
from cv_generator.pdf.registry import (
    KNOWN_ENGINES,
    EngineInfo,
    available_engines,
    engine_info,
    get_engine,
    implemented_engines,
)

DEFAULT_ENGINE = "chrome"

__all__ = [
    "BROWSER_WS_ENV",
    "DEFAULT_ENGINE",
    "KNOWN_ENGINES",
    "ChromeEngine",
    "EngineInfo",
    "PdfEngine",
    "available_engines",
    "engine_info",
    "get_engine",
    "implemented_engines",
    "remote_endpoint",
]
