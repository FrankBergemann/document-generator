"""Generate a CV from a single Markdown file, as HTML, PDF or MS Word."""

from cv_generator.errors import CVError, CVParseError, PdfEngineError, RenderError
from cv_generator.models import (
    CV,
    Contact,
    Link,
    Photo,
    RichCell,
    RichParagraph,
    RichRun,
    RichTable,
    Section,
)
from cv_generator.parser import parse_cv, parse_cv_file
from cv_generator.render import Renderer
from cv_generator.word import WordRenderer, WordTheme

__version__ = "0.2.0"

__all__ = [
    "CV",
    "CVError",
    "CVParseError",
    "Contact",
    "Link",
    "PdfEngineError",
    "Photo",
    "RenderError",
    "Renderer",
    "RichCell",
    "RichParagraph",
    "RichRun",
    "RichTable",
    "Section",
    "WordRenderer",
    "WordTheme",
    "__version__",
    "parse_cv",
    "parse_cv_file",
]
