from __future__ import annotations

from pathlib import Path

import pytest

from cv_generator.errors import CVParseError
from cv_generator.models import CV
from cv_generator.parser import (
    load_photo,
    parse_cv,
    parse_cv_file,
    slugify,
    split_frontmatter,
    split_sections,
)
from tests.conftest import PROJECTS_MD
from tests.support import DATA_DIR, PROJEKTLISTE_NAME, write_projektliste


class TestSplitFrontmatter:
    def test_splits_metadata_from_body(self) -> None:
        meta, body = split_frontmatter("---\nname: Ada\n---\n\n## Skills\n")
        assert meta == "name: Ada"
        assert body.strip() == "## Skills"

    def test_body_may_contain_horizontal_rules(self) -> None:
        _, body = split_frontmatter("---\nname: Ada\n---\nintro\n\n---\n\n## Skills\n")
        assert "---" in body
        assert "## Skills" in body

    def test_rejects_missing_frontmatter(self) -> None:
        with pytest.raises(CVParseError, match="missing YAML frontmatter"):
            split_frontmatter("# Ada\n")

    def test_rejects_unterminated_frontmatter(self) -> None:
        with pytest.raises(CVParseError, match="unterminated"):
            split_frontmatter("---\nname: Ada\n")


class TestSplitSections:
    def test_text_before_first_heading_is_the_summary(self) -> None:
        summary, sections = split_sections("A summary.\n\n## Skills\n\n- Python\n")
        assert summary == "A summary."
        assert [title for title, _ in sections] == ["Skills"]
        assert sections[0][1] == "- Python"

    def test_h3_stays_inside_its_section(self) -> None:
        _, sections = split_sections("## Experience\n\n### Role\n\n## Skills\n")
        assert [title for title, _ in sections] == ["Experience", "Skills"]
        assert "### Role" in sections[0][1]

    def test_heading_inside_fenced_block_is_content(self) -> None:
        body = "## Code\n\n```md\n## Not a heading\n```\n\n## Real\n"
        _, sections = split_sections(body)
        assert [title for title, _ in sections] == ["Code", "Real"]
        assert "## Not a heading" in sections[0][1]

    def test_document_without_sections(self) -> None:
        summary, sections = split_sections("Just a summary.\n")
        assert summary == "Just a summary."
        assert sections == []


class TestSlugify:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Experience", "experience"),
            ("Berufserfahrung", "berufserfahrung"),
            ("Persönliches", "personliches"),
            ("Skills & Tools", "skills-tools"),
            ("  Spaced  Out  ", "spaced-out"),
        ],
    )
    def test_slugs(self, title: str, expected: str) -> None:
        assert slugify(title) == expected


class TestParseCV:
    def test_parses_metadata_and_sections(self, minimal_cv: CV) -> None:
        assert minimal_cv.name == "Ada Lovelace"
        assert minimal_cv.headline == "Mathematician"
        assert minimal_cv.contact.email == "ada@example.com"
        assert [s.title for s in minimal_cv.sections] == ["Experience", "Skills"]

    def test_section_body_stays_markdown(self, minimal_cv: CV) -> None:
        # The parser must not convert to HTML: docx output needs the structure,
        # not a string of tags.
        experience = minimal_cv.section("experience")
        assert experience is not None
        assert experience.markdown.startswith("### Analyst")
        assert "- Wrote Note G." in experience.markdown
        assert "<li>" not in experience.markdown

    def test_summary_stays_markdown(self, minimal_cv: CV) -> None:
        assert minimal_cv.summary == "First analytical engine programmer."

    def test_section_heading_line_is_dropped(self, minimal_cv: CV) -> None:
        skills = minimal_cv.section("skills")
        assert skills is not None
        assert not skills.markdown.startswith("## ")

    def test_defaults_applied(self, minimal_cv: CV) -> None:
        assert minimal_cv.lang == "de"
        assert minimal_cv.theme == "classic"

    def test_duplicate_titles_get_distinct_slugs(self) -> None:
        cv = parse_cv("---\nname: Ada\n---\n## Skills\na\n\n## Skills\nb\n")
        assert [s.slug for s in cv.sections] == ["skills", "skills-2"]

    def test_missing_summary_is_none(self) -> None:
        cv = parse_cv("---\nname: Ada\n---\n\n## Skills\n\n- Python\n")
        assert cv.summary is None

    def test_rejects_missing_name(self) -> None:
        with pytest.raises(CVParseError):
            parse_cv("---\nheadline: nope\n---\n")

    def test_rejects_unknown_frontmatter_key(self) -> None:
        with pytest.raises(CVParseError):
            parse_cv("---\nname: Ada\nnickname: typo\n---\n")

    def test_rejects_non_mapping_frontmatter(self) -> None:
        with pytest.raises(CVParseError, match="must be a YAML mapping"):
            parse_cv("---\n- just\n- a list\n---\n")

    def test_rejects_invalid_yaml(self) -> None:
        with pytest.raises(CVParseError, match="invalid YAML"):
            parse_cv("---\nname: [unclosed\n---\n")

    def test_error_message_names_the_source(self) -> None:
        with pytest.raises(CVParseError, match=r"document\.md"):
            parse_cv("---\nheadline: no name\n---\n", source="document.md")


class TestPhoto:
    def test_absent_by_default(self, minimal_cv: CV) -> None:
        assert minimal_cv.photo is None

    def test_image_is_read_into_the_model(self, photo_cv: CV, portrait_path: Path) -> None:
        # Bytes, not a path: the HTML has to be self-contained and the PDF
        # browser may be in a container that cannot see this filesystem.
        assert photo_cv.photo is not None
        assert photo_cv.photo.data == portrait_path.read_bytes()

    def test_media_type_is_sniffed_from_the_content(self, photo_cv: CV) -> None:
        assert photo_cv.photo is not None
        assert photo_cv.photo.media_type == "image/png"

    def test_path_is_relative_to_the_cv_file_not_the_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        cv = parse_cv_file(DATA_DIR / "photo.md")
        assert cv.photo is not None

    def test_absolute_path_is_used_as_is(self, portrait_path: Path) -> None:
        cv = parse_cv(f"---\nname: Ada\nphoto: {portrait_path.as_posix()}\n---\n")
        assert cv.photo is not None

    def test_jpeg_is_recognised(self, tmp_path: Path) -> None:
        path = tmp_path / "shot.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)
        photo = load_photo("shot.jpg", tmp_path)
        assert photo.media_type == "image/jpeg"

    def test_missing_image_names_the_path(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="cannot read photo"):
            load_photo("nope.png", tmp_path)

    def test_wrong_extension_does_not_fool_the_sniffer(self, tmp_path: Path) -> None:
        # A .png that is really a text file must fail here rather than in Word.
        (tmp_path / "fake.png").write_text("not an image", encoding="utf-8")
        with pytest.raises(CVParseError, match="not a supported image"):
            load_photo("fake.png", tmp_path)

    def test_format_neither_backend_shares_is_rejected(self, tmp_path: Path) -> None:
        # WebP renders in a browser but not in Word; rejecting it keeps the
        # output formats from drifting apart.
        (tmp_path / "p.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
        with pytest.raises(CVParseError, match="not a supported image"):
            load_photo("p.webp", tmp_path)

    def test_non_path_value_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="must be a path"):
            load_photo({"data": "..."}, tmp_path)

    def test_explicit_null_is_the_same_as_absent(self) -> None:
        assert parse_cv("---\nname: Ada\nphoto:\n---\n").photo is None

    def test_error_names_the_source_file(self, tmp_path: Path) -> None:
        source = tmp_path / "document.md"
        source.write_text("---\nname: Ada\nphoto: gone.png\n---\n", encoding="utf-8")
        with pytest.raises(CVParseError, match=r"document\.md"):
            parse_cv_file(source)


class TestSingleFileHasNoImports:
    """A lone `.md` is the whole document; only a recipe reaches other files."""

    def test_every_section_is_markdown(self, tmp_path: Path) -> None:
        path = tmp_path / "document.md"
        path.write_text(PROJECTS_MD, encoding="utf-8")
        cv = parse_cv_file(path)
        assert [s.title for s in cv.sections] == ["Berufserfahrung", "Projekte", "Kenntnisse"]
        assert all(section.blocks == [] for section in cv.sections)

    def test_a_projekte_section_is_no_longer_special(self, tmp_path: Path) -> None:
        # It used to be filled from a *Projektliste*.docx next to the file, by
        # name alone. Composition is a recipe's job now, so the heading is just a
        # heading -- and a directory holding such a document changes nothing.
        write_projektliste(tmp_path / PROJEKTLISTE_NAME)
        path = tmp_path / "document.md"
        path.write_text(PROJECTS_MD, encoding="utf-8")
        projects = parse_cv_file(path).section("projekte")
        assert projects is not None
        assert projects.blocks == []
        assert "darf nicht" in projects.markdown

    def test_no_section_records_a_source(self, minimal_cv: CV) -> None:
        # There is only one file, so there is nothing to disambiguate.
        assert all(section.source is None for section in minimal_cv.sections)


class TestParseCVFile:
    def test_reads_from_disk(self, minimal_path: Path) -> None:
        assert parse_cv_file(minimal_path).name == "Ada Lovelace"

    def test_strips_byte_order_mark(self, tmp_path: Path) -> None:
        path = tmp_path / "bom.md"
        path.write_text("---\nname: Ada\n---\n", encoding="utf-8-sig")
        assert parse_cv_file(path).name == "Ada"

    def test_missing_file_raises_cv_error(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="cannot read"):
            parse_cv_file(tmp_path / "nope.md")

    def test_repository_sample_is_valid(self, sample_cv_path: Path) -> None:
        cv = parse_cv_file(sample_cv_path)
        assert cv.name
        assert cv.sections
