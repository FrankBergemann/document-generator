"""Import a PNG or JPEG file as one centered picture.

A ``"png"``/``"jpeg"`` recipe entry places the whole image where the entry
stands, the way an ``"xlsx"`` ``diagram`` places a chart: one centered
:class:`RichParagraph` whose one run carries the picture as a
:class:`~cv_generator.models.Photo`. That reuses ``RichRun.image``, which both
backends already render, so an image section needed no backend change and
cannot differ between output formats.

The display size is the image's own: its pixel size at 96 DPI -- CSS's own
pixel, so the HTML shows exactly what a browser shows for the bare file --
shrunk, never enlarged, to the page's content width (:data:`MAX_WIDTH_MM`) with
the aspect ratio kept. A DPI the file declares is ignored: python-docx reports
72 both for "declared 72" and "declared nothing", so it cannot be trusted.
Setting the size explicitly matters: without ``width_emu``/``height_emu``,
Word would place a large bitmap at its full natural size, off the page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from docx.image.exceptions import UnrecognizedImageError
from docx.image.image import Image

from cv_generator.errors import DocParseError
from cv_generator.models import Photo, RichBlock, RichParagraph, RichRun

ImageFormat = Literal["png", "jpeg"]

# What each recipe `format` promises about the file's content -- checked
# against the bytes, so a JPEG named in a "png" entry fails instead of being
# quietly accepted under the wrong label.
_MAGIC: dict[ImageFormat, tuple[bytes, str]] = {
    "png": (b"\x89PNG\r\n\x1a\n", "image/png"),
    "jpeg": (b"\xff\xd8\xff", "image/jpeg"),
}

_EMU_PER_MM = 36000
_EMU_PER_PX = 9525  # 914400 EMU per inch / 96 px per inch
# The page's content width (A4 less 15mm margins, `WordTheme.content_width_mm`),
# the same width an imported chart takes.
MAX_WIDTH_MM = 180.0


def load_image(path: Path, *, image_format: ImageFormat) -> list[RichBlock]:
    """Read ``path`` as one centered picture.

    Raises:
        DocParseError: if the file cannot be read, its content is not the
            declared ``image_format``, or its header cannot be parsed.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DocParseError(f"cannot read {path}: {exc}") from exc

    magic, media_type = _MAGIC[image_format]
    if not data.startswith(magic):
        raise DocParseError(f"{path} is not a {image_format.upper()} image")

    try:
        header = Image.from_blob(data)
    except (UnrecognizedImageError, ValueError, IndexError) as exc:
        raise DocParseError(f"{path}: cannot read the image's size: {exc}") from exc

    width_emu = header.px_width * _EMU_PER_PX
    height_emu = header.px_height * _EMU_PER_PX
    max_width_emu = round(MAX_WIDTH_MM * _EMU_PER_MM)
    if width_emu > max_width_emu:
        height_emu = round(height_emu * max_width_emu / width_emu)
        width_emu = max_width_emu

    image = Photo(data=data, media_type=media_type, width_emu=width_emu, height_emu=height_emu)
    return [RichParagraph(runs=[RichRun(text="", image=image)], alignment="center")]
