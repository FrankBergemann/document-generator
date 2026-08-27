"""Generate a CV from Markdown and Word sources, as HTML, PDF or MS Word."""

from cv_generator.config import BuildConfig, SectionSpec, load_config
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
from cv_generator.parser import build_cv, load_cv, parse_config_file, parse_cv, parse_cv_file
from cv_generator.render import Renderer
from cv_generator.word import WordRenderer, WordTheme

__version__ = "0.2.0"

__all__ = [
    "CV",
    "BuildConfig",
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
    "SectionSpec",
    "WordRenderer",
    "WordTheme",
    "__version__",
    "build_cv",
    "load_config",
    "load_cv",
    "parse_config_file",
    "parse_cv",
    "parse_cv_file",
]
