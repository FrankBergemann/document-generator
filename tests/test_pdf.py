from __future__ import annotations

import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pypdf import PdfReader

from cv_generator.errors import PdfEngineError
from cv_generator.models import Document
from cv_generator.pdf import (
    KNOWN_ENGINES,
    ChromeEngine,
    PdfEngine,
    available_engines,
    engine_info,
    get_engine,
    implemented_engines,
)
from cv_generator.pdf.chrome import (
    BROWSER_GLOB,
    BROWSER_WS_ENV,
    ZERO_MARGINS,
    browser_cache_dirs,
    remote_endpoint,
    server_listening,
)
from cv_generator.render import Renderer
from tests.support import CHROME_AVAILABLE, LOCAL_CHROME_INSTALLED, requires_chromium

A4_POINTS = (595, 842)


class TestKnownEngines:
    def test_documented_names(self) -> None:
        assert {info.name for info in KNOWN_ENGINES} == {"chrome", "weasyprint", "latex"}

    def test_every_entry_explains_its_trade_off(self) -> None:
        for info in KNOWN_ENGINES:
            assert info.summary
            assert info.trade_off
            assert info.dependencies

    def test_chrome_is_the_implemented_one(self) -> None:
        assert implemented_engines() == ["chrome"]

    def test_lookup_by_name(self) -> None:
        info = engine_info("chrome")
        assert info is not None and info.name == "chrome"

    def test_lookup_miss(self) -> None:
        assert engine_info("nope") is None


class TestGetEngine:
    def test_documented_but_unbuilt_engine_says_so(self) -> None:
        with pytest.raises(PdfEngineError) as excinfo:
            get_engine("weasyprint")
        message = str(excinfo.value)
        assert "documented but not implemented" in message
        assert "chrome" in message

    def test_unknown_engine_lists_known_names(self) -> None:
        with pytest.raises(PdfEngineError, match="unknown PDF engine"):
            get_engine("imagemagick")

    def test_returns_the_engine_without_probing_for_a_browser(self) -> None:
        # Availability detection is a heuristic, so it must not be able to
        # withhold an engine that would work.
        assert isinstance(get_engine("chrome"), ChromeEngine)


class TestChromeEngine:
    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(ChromeEngine(), PdfEngine)

    def test_name(self) -> None:
        assert ChromeEngine.name == "chrome"

    def test_margins_are_deferred_to_the_stylesheet(self) -> None:
        # Any non-zero margin here would be added on top of the CSS @page
        # margin, so the HTML preview would stop matching the PDF.
        assert set(ZERO_MARGINS.values()) == {"0"}

    def test_availability_reports_a_bool(self) -> None:
        assert isinstance(ChromeEngine().is_available(), bool)


class TestBrowserDetection:
    """The local half: where a browser build lives on this machine."""

    @pytest.fixture(autouse=True)
    def local_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A browser server configured for the dev container would otherwise
        # take priority and make every assertion here about the wrong branch.
        monkeypatch.delenv(BROWSER_WS_ENV, raising=False)

    def test_honours_the_documented_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/somewhere/else")
        assert browser_cache_dirs() == [Path("/somewhere/else")]

    def test_zero_means_inside_the_package(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")
        assert [d.name for d in browser_cache_dirs()] == [".local-browsers"]

    def test_default_location_is_used_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        assert [d.name for d in browser_cache_dirs()] == ["ms-playwright"]

    def test_reports_unavailable_for_an_empty_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert ChromeEngine().is_available() is False

    def test_reports_available_when_a_build_is_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / BROWSER_GLOB.replace("*", "1181")).mkdir()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert ChromeEngine().is_available() is True


@pytest.fixture
def listening_port() -> Iterator[int]:
    """A port with a real listener on it, for the duration of one test."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        yield int(server.getsockname()[1])


@pytest.fixture
def closed_port() -> int:
    """A port nothing is listening on: bound to learn the number, then freed."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class TestRemoteBrowser:
    """The other half: a browser served by the playwright container."""

    def test_no_endpoint_means_a_local_browser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(BROWSER_WS_ENV, raising=False)
        assert remote_endpoint() is None
        assert ChromeEngine().endpoint() is None

    def test_endpoint_comes_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(BROWSER_WS_ENV, "ws://playwright:3000/")
        # Through the zero-argument factory, because that is how the registry
        # builds engines: a configured server must survive that indirection.
        engine = get_engine("chrome")
        assert isinstance(engine, ChromeEngine)
        assert engine.endpoint() == "ws://playwright:3000/"

    def test_an_explicit_endpoint_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(BROWSER_WS_ENV, "ws://from-env:3000/")
        assert ChromeEngine(ws_endpoint="ws://explicit:3000/").endpoint() == "ws://explicit:3000/"

    def test_an_empty_value_switches_remote_mode_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # `CV_GENERATOR_BROWSER_WS: ""` in a compose override must mean "use a
        # local browser", not "connect to nowhere".
        monkeypatch.setenv(BROWSER_WS_ENV, "")
        assert ChromeEngine().endpoint() is None

    def test_available_when_the_server_accepts_connections(
        self, listening_port: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BROWSER_WS_ENV, f"ws://127.0.0.1:{listening_port}/")
        assert ChromeEngine().is_available() is True

    def test_unavailable_when_the_server_is_down(
        self, closed_port: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BROWSER_WS_ENV, f"ws://127.0.0.1:{closed_port}/")
        assert ChromeEngine().is_available() is False

    def test_a_local_browser_does_not_stand_in_for_a_stopped_server(
        self, tmp_path: Path, closed_port: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reporting "ready" off the local cache while renders go to a dead
        # container would be the worst of both answers.
        (tmp_path / BROWSER_GLOB.replace("*", "1181")).mkdir()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        monkeypatch.setenv(BROWSER_WS_ENV, f"ws://127.0.0.1:{closed_port}/")
        assert ChromeEngine().is_available() is False

    def test_a_malformed_endpoint_is_not_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(BROWSER_WS_ENV, "not-a-url")
        assert ChromeEngine().is_available() is False

    def test_a_portless_url_needs_a_scheme_with_a_known_port(self) -> None:
        # ws/wss imply 80/443; anything else has no port to probe, so the probe
        # must say "no" instead of guessing.
        assert server_listening("stdio://127.0.0.1") is False

    def test_an_unreachable_server_is_reported_with_its_address(
        self, tmp_path: Path, closed_port: int, minimal_document: Document
    ) -> None:
        endpoint = f"ws://127.0.0.1:{closed_port}/"
        html = Renderer().render_html(minimal_document)
        engine = ChromeEngine(ws_endpoint=endpoint, timeout_ms=5_000)
        with pytest.raises(PdfEngineError) as excinfo:
            engine.render(html, tmp_path / "document.pdf")
        message = str(excinfo.value)
        assert endpoint in message
        assert "docker compose up -d playwright" in message


class TestMissingBrowser:
    @pytest.mark.skipif(CHROME_AVAILABLE or LOCAL_CHROME_INSTALLED, reason="a browser is available")
    def test_render_explains_the_install(
        self, tmp_path: Path, minimal_document: Document, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(BROWSER_WS_ENV, raising=False)
        html = Renderer().render_html(minimal_document)
        with pytest.raises(PdfEngineError) as excinfo:
            ChromeEngine().render(html, tmp_path / "document.pdf")
        message = str(excinfo.value)
        assert "playwright install chromium" in message
        assert "--format docx" in message


@requires_chromium
class TestChromePrinting:
    @pytest.fixture
    def pdf(self, tmp_path: Path, minimal_document: Document) -> Path:
        html = Renderer().render_html(minimal_document)
        output = tmp_path / "out" / "document.pdf"
        ChromeEngine().render(html, output)
        return output

    def test_writes_a_pdf(self, pdf: Path) -> None:
        assert pdf.is_file()
        assert pdf.read_bytes().startswith(b"%PDF-")

    def test_creates_missing_directories(self, pdf: Path) -> None:
        assert pdf.parent.name == "out"

    def test_uses_the_a4_page_size_from_the_stylesheet(self, pdf: Path) -> None:
        page = PdfReader(str(pdf)).pages[0]
        actual = (round(float(page.mediabox.width)), round(float(page.mediabox.height)))
        assert actual == A4_POINTS

    def test_contains_the_cv_text(self, pdf: Path) -> None:
        text = "".join(page.extract_text() for page in PdfReader(str(pdf)).pages)
        assert "Ada Lovelace" in text
        assert "Note G" in text

    def test_a_short_cv_is_one_page(self, pdf: Path) -> None:
        assert len(PdfReader(str(pdf)).pages) == 1

    def test_reported_as_available(self) -> None:
        assert "chrome" in available_engines()

    def test_a_photo_reaches_the_pdf(self, tmp_path: Path, photo_document: Document) -> None:
        # The proof that a data URL survives the round trip to the browser: with
        # a file reference the container would print a Document with a hole in it.
        output = tmp_path / "photo.pdf"
        ChromeEngine().render(Renderer().render_html(photo_document), output)
        reader = PdfReader(str(output))
        assert len(reader.pages) == 1
        assert reader.pages[0].images

    def test_build_writes_nothing_to_stderr(self, tmp_path: Path, minimal_path: Path) -> None:
        # Regression guard: probing Playwright by starting its driver left a
        # pending asyncio task, and Python dumped "Task was destroyed but it is
        # pending!" plus a traceback after every successful build. Only a real
        # subprocess sees that, because it is printed at interpreter shutdown.
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "cv_generator",
                "build",
                str(minimal_path),
                "-f",
                "pdf",
                "-o",
                str(tmp_path / "document.pdf"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
