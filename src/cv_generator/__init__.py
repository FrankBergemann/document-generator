"""Generate a Document from Markdown and Word sources, as HTML, PDF or MS Word."""

from cv_generator.config import BuildConfig, SectionSpec, load_config
from cv_generator.errors import DocError, DocParseError, PdfEngineError, RenderError
from cv_generator.models import (
    Contact,
    Document,
    Link,
    Photo,
    RichCell,
    RichParagraph,
    RichRun,
    RichTable,
    Section,
)
from cv_generator.parser import build_doc, load_doc, parse_config_file, parse_doc, parse_doc_file
from cv_generator.render import Renderer
from cv_generator.word import WordRenderer, WordTheme

__version__ = "0.2.0"

__all__ = [
    "BuildConfig",
    "Contact",
    "DocError",
    "DocParseError",
    "Document",
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
    "SectionSpec",
    "WordRenderer",
    "WordTheme",
    "__version__",
    "build_doc",
    "load_config",
    "load_doc",
    "parse_config_file",
    "parse_doc",
    "parse_doc_file",
]
