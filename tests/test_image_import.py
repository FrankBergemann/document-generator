"""PNG/JPEG recipe entries: the whole image, centered, sized to fit the page."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import docx
import pytest
from docx.shared import Emu
from PIL import Image as PILImage

from cv_generator.config import BuildConfig
from cv_generator.errors import DocParseError
from cv_generator.image_import import MAX_WIDTH_MM, load_image
from cv_generator.models import Document, RichParagraph
from cv_generator.parser import build_doc
from cv_generator.render import Renderer
from cv_generator.word import WordRenderer
from tests.conftest import PROJECTS_MD
from tests.support import png

_EMU_PER_MM = 36000
_EMU_PER_PX_96DPI = 9525


def jpeg(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    PILImage.new("RGB", (width, height), "white").save(buffer, format="JPEG", dpi=(96, 96))
    return buffer.getvalue()


def build(directory: Path, *specs: dict[str, Any]) -> Document:
    config = BuildConfig.model_validate(
        {"sections": [{"source": "document.md", "format": "md"}, *specs]}
    )
    return build_doc(config, directory, project_root=directory).doc


@pytest.fixture
def image_dir(tmp_path: Path) -> Path:
    (tmp_path / "document.md").write_text(PROJECTS_MD, encoding="utf-8")
    (tmp_path / "small.png").write_bytes(png(200, 100))
    (tmp_path / "wide.png").write_bytes(png(2000, 500))
    (tmp_path / "photo.jpg").write_bytes(jpeg(300, 150))
    return tmp_path


class TestLoadImage:
    def test_a_png_becomes_one_centered_picture(self, image_dir: Path) -> None:
        blocks = load_image(image_dir / "small.png", image_format="png")
        assert len(blocks) == 1
        paragraph = blocks[0]
        assert isinstance(paragraph, RichParagraph)
        assert paragraph.alignment == "center"
        image = paragraph.runs[0].image
        assert image is not None
        assert image.media_type == "image/png"
        assert image.data == (image_dir / "small.png").read_bytes()

    def test_a_jpeg_keeps_its_media_type(self, image_dir: Path) -> None:
        paragraph = load_image(image_dir / "photo.jpg", image_format="jpeg")[0]
        assert isinstance(paragraph, RichParagraph)
        image = paragraph.runs[0].image
        assert image is not None
        assert image.media_type == "image/jpeg"

    def test_a_small_image_keeps_its_natural_size(self, image_dir: Path) -> None:
        paragraph = load_image(image_dir / "small.png", image_format="png")[0]
        assert isinstance(paragraph, RichParagraph)
        image = paragraph.runs[0].image
        assert image is not None
        assert image.width_emu == 200 * _EMU_PER_PX_96DPI
        assert image.height_emu == 100 * _EMU_PER_PX_96DPI

    def test_a_wide_image_shrinks_to_the_page_keeping_its_aspect_ratio(
        self, image_dir: Path
    ) -> None:
        paragraph = load_image(image_dir / "wide.png", image_format="png")[0]
        assert isinstance(paragraph, RichParagraph)
        image = paragraph.runs[0].image
        assert image is not None
        assert image.width_emu == MAX_WIDTH_MM * _EMU_PER_MM
        assert image.height_emu == pytest.approx(MAX_WIDTH_MM * _EMU_PER_MM / 4, abs=1)

    def test_content_must_match_the_declared_format(self, image_dir: Path) -> None:
        with pytest.raises(DocParseError, match="not a PNG image"):
            load_image(image_dir / "photo.jpg", image_format="png")
        with pytest.raises(DocParseError, match="not a JPEG image"):
            load_image(image_dir / "small.png", image_format="jpeg")


class TestImageEntries:
    def test_the_section_holds_the_picture_and_no_markdown(self, image_dir: Path) -> None:
        doc = build(image_dir, {"source": "small.png", "format": "png", "title": "Bild"})
        section = doc.sections[-1]
        assert section.title == "Bild"
        assert section.markdown == ""
        paragraph = section.blocks[0]
        assert isinstance(paragraph, RichParagraph)
        assert paragraph.runs[0].image is not None

    def test_without_a_title_no_heading_is_shown(self, image_dir: Path) -> None:
        doc = build(image_dir, {"source": "photo.jpg", "format": "jpeg"})
        assert doc.sections[-1].title is None
        assert doc.sections[-1].slug == "photo"

    def test_the_picture_sits_where_the_entry_stands(self, image_dir: Path) -> None:
        config = BuildConfig.model_validate(
            {
                "sections": [
                    {"source": "document.md", "format": "md", "end": "Projekte"},
                    {"source": "small.png", "format": "png", "title": "Bild"},
                    {"source": "document.md", "format": "md", "begin": "Kenntnisse"},
                ]
            }
        )
        doc = build_doc(config, image_dir, project_root=image_dir).doc
        assert [s.title for s in doc.sections] == ["Berufserfahrung", "Bild", "Kenntnisse"]

    def test_a_wrongly_declared_format_names_the_entry(self, image_dir: Path) -> None:
        with pytest.raises(DocParseError, match=r"sections\[1\]: .*not a JPEG image"):
            build(image_dir, {"source": "small.png", "format": "jpeg"})

    @pytest.mark.parametrize("key", ["begin", "end"])
    def test_headlines_are_rejected(self, key: str) -> None:
        with pytest.raises(ValueError, match=f"'{key}' does not apply to format 'png'"):
            BuildConfig.model_validate(
                {"sections": [{"source": "a.png", "format": "png", key: "X"}]}
            )

    def test_xlsx_keys_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="'tab' only applies to format 'xlsx'"):
            BuildConfig.model_validate(
                {"sections": [{"source": "a.png", "format": "png", "tab": "X"}]}
            )


class TestRenderedOutput:
    def test_html_embeds_the_picture(self, image_dir: Path) -> None:
        doc = build(image_dir, {"source": "small.png", "format": "png"})
        assert "data:image/png;base64," in Renderer().render_html(doc)

    def test_docx_embeds_the_picture_at_its_size(self, image_dir: Path, tmp_path: Path) -> None:
        doc = build(image_dir, {"source": "wide.png", "format": "png"})
        output = tmp_path / "out.docx"
        WordRenderer().render(doc, output)
        shapes = docx.Document(str(output)).inline_shapes
        assert len(shapes) == 1
        assert shapes[0].width == Emu(round(MAX_WIDTH_MM * _EMU_PER_MM))
