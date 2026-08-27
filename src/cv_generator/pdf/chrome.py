"""PDF output via headless Chromium, driven by Playwright.

The browser can live in one of two places, and the engine picks by
configuration rather than by branching in the caller:

* **In this process** -- ``playwright install chromium`` puts a browser build
  next to the interpreter and :meth:`ChromeEngine.render` launches it.
* **In another container** -- ``CV_GENERATOR_BROWSER_WS`` points at a Playwright
  server (``playwright run-server``), and the engine connects to it over a
  websocket. This is what lets the Python image and the Playwright image run
  side by side; see ``.devcontainer/docker-compose.yml``.

Remote mode works only because :mod:`cv_generator.render` produces a
*self-contained* document -- stylesheet inlined, no external references. The
HTML travels over the websocket and the finished PDF comes back as bytes, so the
browser never touches this filesystem. A theme that referenced a local font or
image would still render locally and silently lose that resource remotely, which
is the reason to keep the document self-contained.

Playwright is an optional dependency (``pip install "document-generator[pdf]"``), so it
is imported inside the methods rather than at module scope: importing this
module must work on a machine that will only ever produce HTML or ``.docx``. The
pip package alone is enough for remote mode -- it ships the driver, and the
~150 MB browser download stays in the other container.

Page geometry comes from the stylesheet, not from here. ``@page { size: A4;
margin: ... }`` in the theme CSS is authoritative, which is why ``page.pdf()``
is called with ``prefer_css_page_size`` and zero margins -- otherwise Chromium's
own defaults would silently win and the HTML preview would stop matching the
PDF.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlparse

from cv_generator.errors import PdfEngineError

ZERO_MARGINS = {"top": "0", "right": "0", "bottom": "0", "left": "0"}

# Set this to a "ws://host:port/" Playwright server to use a browser running
# elsewhere instead of a locally installed one.
BROWSER_WS_ENV = "CV_GENERATOR_BROWSER_WS"

INSTALL_HINT = (
    'install the extra and the browser: pip install "document-generator[pdf]" '
    "&& playwright install chromium"
)

CONNECT_HINT = (
    "start the browser container (docker compose up -d playwright), or unset "
    f"{BROWSER_WS_ENV} to use a locally installed Chromium"
)

# Directory name Playwright gives a Chromium build inside its browser cache.
BROWSER_GLOB = "chromium-*"

# How long to wait for the browser server's TCP port when reporting status.
PROBE_TIMEOUT_S = 0.5

# Playwright's own wording when a browser build is missing.
_MISSING_BROWSER = "executable doesn't exist"

# Substrings Node puts in the error when the server cannot be reached at all,
# as opposed to being reached and failing to render.
_UNREACHABLE = ("econnrefused", "enotfound", "eai_again", "getaddrinfo", "socket hang up")

_WS_DEFAULT_PORTS = {"ws": 80, "wss": 443}


class ChromeEngine:
    """Prints a self-contained HTML document to PDF with headless Chromium.

    Args:
        ws_endpoint: Playwright server to connect to, overriding
            ``CV_GENERATOR_BROWSER_WS``. ``None`` (the default) means "read the
            environment", so that the zero-argument factory in
            :mod:`cv_generator.pdf.registry` still picks up a configured server.
    """

    name: ClassVar[str] = "chrome"

    def __init__(
        self,
        *,
        ws_endpoint: str | None = None,
        timeout_ms: int = 30_000,
        print_background: bool = True,
    ) -> None:
        self.ws_endpoint = ws_endpoint
        self.timeout_ms = timeout_ms
        self.print_background = print_background

    def endpoint(self) -> str | None:
        """The browser server to use, or ``None`` for a local browser."""
        return remote_endpoint(self.ws_endpoint)

    def is_available(self) -> bool:
        """Whether a browser -- local or remote -- looks reachable.

        Both answers are heuristics: a listening TCP port is not proof of a
        Playwright server, and a browser build on disk is not proof that it
        runs. That is why nothing *gates* on the result --
        :func:`cv_generator.pdf.registry.get_engine` hands the engine over
        regardless, and :meth:`render` reports the real failure. A wrong answer
        here only misreports ``document-generator engines``; it cannot block a working
        engine.

        The local check deliberately inspects the browser cache instead of
        asking Playwright: starting the driver only to read ``executable_path``
        and stopping it again leaves a pending asyncio task, which Python then
        reports on stderr at interpreter shutdown -- turning every PDF build
        into a wall of ``Task was destroyed but it is pending!``. It is also
        ~700x faster, which matters because it runs on every build.
        """
        endpoint = self.endpoint()
        if endpoint is not None:
            return server_listening(endpoint)
        return local_browser_installed()

    def render(self, html: str, output: Path) -> None:
        """Print ``html`` to ``output`` as a PDF.

        Raises:
            PdfEngineError: if Playwright is missing, if no browser can be
                launched or reached, or if Chromium fails to render.
        """
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise PdfEngineError(
                f"the 'chrome' PDF engine needs Playwright -- {INSTALL_HINT}"
            ) from exc

        output.parent.mkdir(parents=True, exist_ok=True)
        endpoint = self.endpoint()

        try:
            with sync_playwright() as playwright:
                if endpoint is None:
                    browser = playwright.chromium.launch()
                else:
                    browser = playwright.chromium.connect(endpoint, timeout=self.timeout_ms)
                try:
                    page = browser.new_page()
                    page.set_default_timeout(self.timeout_ms)
                    # The document is self-contained, so there is nothing to
                    # fetch and "load" settles immediately -- and nothing the
                    # remote browser would fail to find.
                    page.set_content(html, wait_until="load")
                    # Without this the PDF would use the screen stylesheet.
                    page.emulate_media(media="print")
                    # Written here rather than by passing ``path=``, because
                    # with a remote browser the file belongs on this side of
                    # the websocket, not the browser's.
                    output.write_bytes(
                        page.pdf(
                            prefer_css_page_size=True,
                            print_background=self.print_background,
                            # Playwright types this as a TypedDict it does not
                            # export publicly, so the shape cannot be declared.
                            margin=ZERO_MARGINS,  # type: ignore[arg-type]
                        )
                    )
                finally:
                    # For a connected browser this closes the connection; the
                    # server keeps running for the next build.
                    browser.close()
        except PlaywrightError as exc:
            raise self._failure(exc, output) from exc

    def _failure(self, exc: Exception, output: Path) -> PdfEngineError:
        """Turn a Playwright error into a message that says what to do next."""
        endpoint = self.endpoint()
        message = str(exc).lower()
        if endpoint is not None and any(hint in message for hint in _UNREACHABLE):
            return PdfEngineError(
                f"the 'chrome' PDF engine could not reach the browser server at {endpoint}.\n"
                f"  To fix: {CONNECT_HINT}\n"
                "  Or use --format html and print from your browser, or --format docx."
            )
        if endpoint is None and _MISSING_BROWSER in message:
            return PdfEngineError(
                "the 'chrome' PDF engine needs Chromium, which is not installed.\n"
                f"  To enable it: {INSTALL_HINT}\n"
                "  Or use --format html and print from your browser, or --format docx."
            )
        return PdfEngineError(f"headless Chromium failed to render {output}: {exc}")


def remote_endpoint(override: str | None = None) -> str | None:
    """The configured Playwright server, or ``None`` for a local browser.

    An empty value counts as unset, so ``CV_GENERATOR_BROWSER_WS=`` in a compose
    file or shell turns remote mode off rather than producing an unusable
    endpoint.
    """
    return override or os.environ.get(BROWSER_WS_ENV) or None


def server_listening(endpoint: str, timeout: float = PROBE_TIMEOUT_S) -> bool:
    """Whether something accepts TCP connections at ``endpoint``.

    A plain socket connect, because the alternative -- an actual Playwright
    handshake -- costs a driver start-up and would run on every build.
    """
    parsed = urlparse(endpoint)
    port = parsed.port or _WS_DEFAULT_PORTS.get(parsed.scheme)
    if not parsed.hostname or port is None:
        return False
    try:
        with socket.create_connection((parsed.hostname, port), timeout):
            return True
    except OSError:
        return False


def local_browser_installed() -> bool:
    """Whether a Chromium build is present in Playwright's browser cache."""
    return any(
        any(directory.glob(BROWSER_GLOB))
        for directory in browser_cache_dirs()
        if directory.is_dir()
    )


def browser_cache_dirs() -> list[Path]:
    """Where Playwright keeps browser builds, per its documented behaviour.

    ``PLAYWRIGHT_BROWSERS_PATH`` overrides the platform default; the special
    value ``0`` means the builds live inside the installed package. Returns an
    empty list when Playwright is not installed at all.
    """
    package = _package_dir()
    if package is None:
        return []

    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override == "0":
        return [package / "driver" / "package" / ".local-browsers"]
    if override:
        return [Path(override)]

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        return [Path(local_app_data) / "ms-playwright"] if local_app_data else []
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Caches" / "ms-playwright"]
    return [Path.home() / ".cache" / "ms-playwright"]


def _package_dir() -> Path | None:
    try:
        import playwright
    except ImportError:
        return None
    return Path(playwright.__file__).parent
