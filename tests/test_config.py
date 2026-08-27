"""The build recipe: reading `config.json`, and assembling the document it describes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cv_generator.config import BuildConfig, SectionSpec, load_config, resolve_source
from cv_generator.errors import CVParseError
from cv_generator.models import CV, RichTable
from cv_generator.parser import build_cv, load_cv
from tests.conftest import PROJECTS_CONFIG, PROJECTS_MD, write_config
from tests.support import (
    AFTER_SECTION,
    BEFORE_HEADING,
    PROJEKTLISTE_NAME,
    SAMPLE_PROJECTS,
    write_projektliste,
)

# A Markdown source with four headings, so a span can start late, stop early, or
# cover several at once.
FOUR_SECTIONS = """---
name: Ada Lovelace
---

Ein Kurzprofil.

## Berufserfahrung

- Analyst

## Projekte

Wird von keinem Eintrag angefordert.

## Kenntnisse

- Python

## Sprachen

- Deutsch
"""

# An entry that takes cv.md's header and none of its sections, by ending at the
# very first heading. Prepended by `recipe` so a test about spans can say only
# what it is about; the header has to come from somewhere in every recipe.
HEADER_ONLY: dict[str, Any] = {"source": "cv.md", "end": "Berufserfahrung"}


def recipe(*specs: dict[str, Any]) -> dict[str, Any]:
    return {"sections": [HEADER_ONLY, *specs]}


def build(directory: Path, config: dict[str, Any]) -> CV:
    return load_cv(write_config(directory, config)).cv


def spans(directory: Path, *specs: dict[str, Any]) -> CV:
    return build(directory, recipe(*specs))


@pytest.fixture
def four_sections(tmp_path: Path) -> Path:
    (tmp_path / "cv.md").write_text(FOUR_SECTIONS, encoding="utf-8")
    return tmp_path


class TestLoadConfig:
    def test_reads_the_recipe(self, tmp_path: Path) -> None:
        config = load_config(write_config(tmp_path, PROJECTS_CONFIG))
        assert [spec.source for spec in config.sections] == [
            "cv.md",
            PROJEKTLISTE_NAME,
            "cv.md",
        ]

    def test_begin_end_and_title_are_all_optional(self, tmp_path: Path) -> None:
        config = load_config(write_config(tmp_path, {"sections": [{"source": "cv.md"}]}))
        assert config.sections[0].begin is None
        assert config.sections[0].end is None
        assert config.sections[0].title is None

    def test_source_is_the_one_required_key_of_an_entry(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="source"):
            load_config(write_config(tmp_path, {"sections": [{"begin": "A"}]}))

    def test_rejects_an_unknown_key(self, tmp_path: Path) -> None:
        # A typo in a recipe must fail loudly, the way frontmatter does; silently
        # dropping "sektions" would render a document with no sections at all.
        path = write_config(tmp_path, {"sections": [], "outputs": "cv"})
        with pytest.raises(CVParseError, match="outputs"):
            load_config(path)

    def test_metadata_is_no_longer_a_key(self, tmp_path: Path) -> None:
        # It was replaced by an entry with no `begin`, and leaving both in would
        # be two ways to say where the header comes from.
        path = write_config(tmp_path, {"metadata": "cv.md", "sections": [{"source": "cv.md"}]})
        with pytest.raises(CVParseError, match="metadata"):
            load_config(path)

    def test_rejects_an_unknown_key_in_a_section(self, tmp_path: Path) -> None:
        config = {"sections": [{"source": "cv.md", "from": "A"}]}
        with pytest.raises(CVParseError, match="from"):
            load_config(write_config(tmp_path, config))

    def test_rejects_a_recipe_without_sections(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="sections"):
            load_config(write_config(tmp_path, {"sections": []}))

    def test_rejects_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text('{"sections": [],}', encoding="utf-8")
        with pytest.raises(CVParseError, match="invalid JSON"):
            load_config(path)

    def test_rejects_a_json_document_that_is_not_an_object(self, tmp_path: Path) -> None:
        path = tmp_path / "config.json"
        path.write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(CVParseError, match="must be a JSON object"):
            load_config(path)

    def test_missing_file_names_the_path(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="cannot read"):
            load_config(tmp_path / "nope.json")

    def test_a_recipe_needs_nothing_but_sections(self) -> None:
        config = BuildConfig(sections=[SectionSpec(source="cv.md")])
        assert config.output is None


class TestResolveSource:
    def test_a_plain_name_is_a_path(self, tmp_path: Path) -> None:
        (tmp_path / "cv.md").write_text("x", encoding="utf-8")
        assert resolve_source(tmp_path, "cv.md") == tmp_path / "cv.md"

    def test_a_subdirectory_works(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "cv.md").write_text("x", encoding="utf-8")
        assert resolve_source(tmp_path, "sub/cv.md") == tmp_path / "sub" / "cv.md"

    def test_an_absolute_path_is_used_as_is(self, tmp_path: Path) -> None:
        target = tmp_path / "cv.md"
        target.write_text("x", encoding="utf-8")
        assert resolve_source(Path("/nowhere"), str(target)) == target

    def test_a_missing_file_names_the_path(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="no such file"):
            resolve_source(tmp_path, "cv.md")

    def test_a_glob_finds_the_one_match(self, tmp_path: Path) -> None:
        # The point of allowing one: the real project list carries a date in its
        # name, so a literal name would go stale every time it is reissued.
        (tmp_path / "Bergemann-Projektliste_19_08_2026.docx").write_bytes(b"")
        found = resolve_source(tmp_path, "*Projektliste*.docx")
        assert found.name == "Bergemann-Projektliste_19_08_2026.docx"

    def test_a_glob_matching_nothing_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="matches"):
            resolve_source(tmp_path, "*Projektliste*.docx")

    def test_a_glob_matching_several_is_an_error(self, tmp_path: Path) -> None:
        # Picking one would quietly publish a CV built from last year's list.
        (tmp_path / "Projektliste_alt.docx").write_bytes(b"")
        (tmp_path / "Projektliste_neu.docx").write_bytes(b"")
        with pytest.raises(CVParseError, match="keep exactly one"):
            resolve_source(tmp_path, "*Projektliste*.docx")

    def test_word_s_lock_file_does_not_count_as_a_match(self, tmp_path: Path) -> None:
        # Otherwise having the document open in Word would break every build --
        # exactly when someone is most likely to rebuild.
        (tmp_path / "Projektliste.docx").write_bytes(b"")
        (tmp_path / "~$ojektliste.docx").write_bytes(b"")
        assert resolve_source(tmp_path, "*rojektliste*.docx").name == "Projektliste.docx"

    def test_an_empty_reference_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match="empty string"):
            resolve_source(tmp_path, "  ")

    def test_error_names_the_entry_it_came_from(self, tmp_path: Path) -> None:
        with pytest.raises(CVParseError, match=r"sections\[2\]"):
            resolve_source(tmp_path, "gone.md", source="config.json: sections[2]")


class TestMarkdownSpans:
    """`begin` and `end` pick a span out of a Markdown source."""

    def test_a_span_stops_before_its_end_headline(self, four_sections: Path) -> None:
        cv = spans(
            four_sections, {"source": "cv.md", "begin": "Berufserfahrung", "end": "Projekte"}
        )
        assert [s.title for s in cv.sections] == ["Berufserfahrung"]

    def test_a_span_without_an_end_runs_to_the_end_of_the_file(self, four_sections: Path) -> None:
        cv = spans(four_sections, {"source": "cv.md", "begin": "Kenntnisse"})
        assert [s.title for s in cv.sections] == ["Kenntnisse", "Sprachen"]

    def test_a_span_without_a_begin_starts_at_the_top_of_the_file(
        self, four_sections: Path
    ) -> None:
        cv = build(four_sections, {"sections": [{"source": "cv.md", "end": "Kenntnisse"}]})
        assert [s.title for s in cv.sections] == ["Berufserfahrung", "Projekte"]

    def test_a_span_with_neither_is_the_whole_file(self, four_sections: Path) -> None:
        cv = build(four_sections, {"sections": [{"source": "cv.md"}]})
        assert [s.title for s in cv.sections] == [
            "Berufserfahrung",
            "Projekte",
            "Kenntnisse",
            "Sprachen",
        ]

    def test_ending_at_the_first_heading_takes_the_header_and_no_sections(
        self, four_sections: Path
    ) -> None:
        # The idiom that replaces the old `metadata` key: an entry that wants a
        # file's frontmatter but none of its content.
        cv = build(four_sections, {"sections": [{"source": "cv.md", "end": "Berufserfahrung"}]})
        assert cv.name == "Ada Lovelace"
        assert cv.sections == []

    def test_a_span_is_split_at_its_own_headings(self, four_sections: Path) -> None:
        # One entry, several sections: each keeps its own heading and anchor
        # rather than becoming body text of the first.
        cv = spans(four_sections, {"source": "cv.md", "begin": "Kenntnisse"})
        assert [s.slug for s in cv.sections] == ["kenntnisse", "sprachen"]
        assert "## Sprachen" not in (cv.sections[0].markdown)

    def test_content_no_entry_asks_for_is_left_out(self, four_sections: Path) -> None:
        cv = spans(
            four_sections,
            {"source": "cv.md", "begin": "Berufserfahrung", "end": "Projekte"},
            {"source": "cv.md", "begin": "Kenntnisse"},
        )
        assert all("keinem Eintrag" not in section.markdown for section in cv.sections)

    def test_the_same_file_may_be_used_more_than_once(self, four_sections: Path) -> None:
        cv = spans(
            four_sections,
            {"source": "cv.md", "begin": "Sprachen"},
            {"source": "cv.md", "begin": "Berufserfahrung", "end": "Projekte"},
        )
        assert [s.title for s in cv.sections] == ["Sprachen", "Berufserfahrung"]

    def test_a_headline_may_be_written_with_its_hashes(self, four_sections: Path) -> None:
        cv = spans(four_sections, {"source": "cv.md", "begin": "## Sprachen"})
        assert [s.title for s in cv.sections] == ["Sprachen"]

    def test_matching_ignores_case(self, four_sections: Path) -> None:
        cv = spans(four_sections, {"source": "cv.md", "begin": "sprachen"})
        assert [s.title for s in cv.sections] == ["Sprachen"]

    def test_the_section_keeps_the_source_heading_s_own_wording(self, four_sections: Path) -> None:
        cv = spans(four_sections, {"source": "cv.md", "begin": "sprachen"})
        assert cv.sections[0].title == "Sprachen"

    def test_title_renames_the_first_section_of_a_span(self, four_sections: Path) -> None:
        cv = spans(four_sections, {"source": "cv.md", "begin": "Kenntnisse", "title": "Skills"})
        assert [s.title for s in cv.sections] == ["Skills", "Sprachen"]
        assert cv.sections[0].slug == "skills"

    def test_a_missing_begin_headline_lists_the_ones_there_are(self, four_sections: Path) -> None:
        with pytest.raises(CVParseError, match="no '## Hobbys' heading; it has 'Berufserfahrung'"):
            spans(four_sections, {"source": "cv.md", "begin": "Hobbys"})

    def test_an_end_headline_that_never_comes_is_an_error(self, four_sections: Path) -> None:
        # Not "run to the end of the file": the entry said where to stop, and
        # importing the rest would put another section's content in this one.
        with pytest.raises(CVParseError, match="no '## Hobbys' heading after '## Kenntnisse'"):
            spans(four_sections, {"source": "cv.md", "begin": "Kenntnisse", "end": "Hobbys"})

    def test_an_end_headline_before_begin_does_not_count(self, four_sections: Path) -> None:
        with pytest.raises(CVParseError, match="no '## Projekte' heading after"):
            spans(four_sections, {"source": "cv.md", "begin": "Kenntnisse", "end": "Projekte"})

    def test_a_missing_end_names_the_top_of_the_file_when_there_is_no_begin(
        self, four_sections: Path
    ) -> None:
        with pytest.raises(CVParseError, match="no '## Hobbys' heading after the top of the file"):
            build(four_sections, {"sections": [{"source": "cv.md", "end": "Hobbys"}]})

    def test_a_source_needs_no_frontmatter_of_its_own(self, tmp_path: Path) -> None:
        # Only the file supplying the header is a CV; anything else is Markdown.
        (tmp_path / "cv.md").write_text(FOUR_SECTIONS, encoding="utf-8")
        (tmp_path / "extra.md").write_text("## Hobbys\n\n- Segeln\n", encoding="utf-8")
        cv = spans(tmp_path, {"source": "extra.md", "begin": "Hobbys"})
        assert cv.sections[0].markdown == "- Segeln"

    def test_the_file_each_section_came_from_is_recorded(self, four_sections: Path) -> None:
        cv = spans(four_sections, {"source": "cv.md", "begin": "Sprachen"})
        assert cv.sections[0].source == str(four_sections / "cv.md")

    def test_duplicate_titles_from_two_files_get_distinct_slugs(self, tmp_path: Path) -> None:
        # Slugs are the HTML anchors, and two files easily use the same heading.
        (tmp_path / "cv.md").write_text(FOUR_SECTIONS, encoding="utf-8")
        (tmp_path / "other.md").write_text("## Kenntnisse\n\n- Rust\n", encoding="utf-8")
        cv = spans(
            tmp_path,
            {"source": "cv.md", "begin": "Kenntnisse", "end": "Sprachen"},
            {"source": "other.md", "begin": "Kenntnisse"},
        )
        assert [s.slug for s in cv.sections] == ["kenntnisse", "kenntnisse-2"]


class TestWordSpans:
    """A `.docx` entry brings in blocks, not Markdown."""

    def test_the_section_carries_the_imported_blocks(self, projects_cv: CV) -> None:
        projects = projects_cv.section("projekte")
        assert projects is not None
        assert [type(block) for block in projects.blocks] == [RichTable] * len(SAMPLE_PROJECTS)

    def test_the_section_has_no_markdown(self, projects_cv: CV) -> None:
        # Two sources for one section is how a stale paragraph ends up in
        # whichever output format happens to prefer one over the other.
        projects = projects_cv.section("projekte")
        assert projects is not None
        assert projects.markdown == ""

    def test_the_source_file_is_recorded(self, projects_cv: CV) -> None:
        projects = projects_cv.section("projekte")
        assert projects is not None
        assert projects.source is not None
        assert projects.source.endswith(PROJEKTLISTE_NAME)

    def test_title_renames_the_imported_section(self, projects_cv: CV) -> None:
        # "Projekthistorie" in Word, "Projekte" in the CV: without the override
        # the target would have to adopt the source document's wording.
        titles = [s.title for s in projects_cv.sections]
        assert titles == ["Berufserfahrung", "Projekte", "Kenntnisse"]

    def test_without_a_title_the_begin_headline_is_used(self, projects_dir: Path) -> None:
        cv = spans(
            projects_dir,
            {"source": PROJEKTLISTE_NAME, "begin": "Projekthistorie", "end": "Ausbildung"},
        )
        assert [s.title for s in cv.sections] == ["Projekthistorie"]

    def test_the_end_headline_bounds_the_import(self, projects_dir: Path) -> None:
        # "Ausbildung" is the heading after the project list; its one paragraph
        # must not be dragged in with the projects.
        cv = spans(
            projects_dir,
            {"source": PROJEKTLISTE_NAME, "begin": "Projekthistorie", "end": "Ausbildung"},
        )
        assert "Promotion Maschinenbau" not in json.dumps(cv.sections[0].model_dump(mode="json"))

    def test_omitting_the_end_falls_back_to_the_formatting_rule(self, projects_dir: Path) -> None:
        # A hand-made Word CV has no heading styles, so the import stops at the
        # next paragraph shaped like the heading it started from.
        cv = spans(projects_dir, {"source": PROJEKTLISTE_NAME, "begin": "Projekthistorie"})
        assert [type(block) for block in cv.sections[0].blocks] == [RichTable] * len(
            SAMPLE_PROJECTS
        )

    def test_omitting_the_begin_starts_at_the_top_of_the_document(self, projects_dir: Path) -> None:
        # No heading to start from means no shape to guess an end from either, so
        # this is the whole document -- including the section before the projects.
        cv = spans(projects_dir, {"source": PROJEKTLISTE_NAME, "title": "Alles"})
        texts = json.dumps(cv.sections[0].model_dump(mode="json"))
        assert BEFORE_HEADING in texts
        assert AFTER_SECTION in texts

    def test_omitting_the_begin_still_honours_an_end(self, projects_dir: Path) -> None:
        cv = spans(
            projects_dir, {"source": PROJEKTLISTE_NAME, "end": "Projekthistorie", "title": "Vorab"}
        )
        texts = json.dumps(cv.sections[0].model_dump(mode="json"))
        assert BEFORE_HEADING in texts
        assert AFTER_SECTION not in texts

    def test_without_a_begin_a_title_is_required(self, projects_dir: Path) -> None:
        # There is no headline to name the section after, and an untitled section
        # would render as an empty heading.
        with pytest.raises(CVParseError, match="needs a 'title'"):
            spans(projects_dir, {"source": PROJEKTLISTE_NAME, "end": "Projekthistorie"})

    def test_a_missing_begin_headline_is_an_error(self, projects_dir: Path) -> None:
        with pytest.raises(CVParseError, match="no heading 'Publikationen' found"):
            spans(projects_dir, {"source": PROJEKTLISTE_NAME, "begin": "Publikationen"})

    def test_an_end_headline_that_never_comes_is_an_error(self, projects_dir: Path) -> None:
        with pytest.raises(CVParseError, match="no heading 'Publikationen' follows"):
            spans(
                projects_dir,
                {"source": PROJEKTLISTE_NAME, "begin": "Projekthistorie", "end": "Publikationen"},
            )

    def test_a_missing_project_list_is_an_error_naming_the_entry(self, tmp_path: Path) -> None:
        # A recipe has many entries, so a message has to say which one failed.
        (tmp_path / "cv.md").write_text(PROJECTS_MD, encoding="utf-8")
        config = {
            "sections": [
                {"source": "cv.md", "end": "Projekte"},
                {"source": "*Projektliste*.docx", "begin": "Projekthistorie"},
            ],
        }
        with pytest.raises(CVParseError, match=r"sections\[1\]: no file in .* matches"):
            build(tmp_path, config)

    def test_two_project_lists_are_an_error(self, tmp_path: Path) -> None:
        write_projektliste(tmp_path / "Projektliste_alt.docx")
        write_projektliste(tmp_path / "Projektliste_neu.docx")
        (tmp_path / "cv.md").write_text(PROJECTS_MD, encoding="utf-8")
        config = {
            "sections": [
                {"source": "cv.md", "end": "Projekte"},
                {"source": "*Projektliste*.docx", "begin": "Projekthistorie"},
            ],
        }
        with pytest.raises(CVParseError, match="keep exactly one"):
            build(tmp_path, config)


class TestTheHeader:
    """No `metadata` key: the header rides along with a span that starts at the top."""

    def test_frontmatter_and_summary_come_from_that_file(self, four_sections: Path) -> None:
        cv = spans(four_sections, {"source": "cv.md", "begin": "Sprachen"})
        assert cv.name == "Ada Lovelace"
        assert cv.summary == "Ein Kurzprofil."

    def test_a_span_that_carries_sections_supplies_it_too(self, four_sections: Path) -> None:
        # The ordinary case: one entry brings the header *and* the first sections.
        cv = build(four_sections, {"sections": [{"source": "cv.md", "end": "Kenntnisse"}]})
        assert cv.name == "Ada Lovelace"
        assert cv.summary == "Ein Kurzprofil."
        assert [s.title for s in cv.sections] == ["Berufserfahrung", "Projekte"]

    def test_the_first_such_entry_wins(self, tmp_path: Path) -> None:
        # The CV has one name and one summary; the first entry to offer them is
        # the one that does, and a later file contributes only its sections.
        (tmp_path / "cv.md").write_text(FOUR_SECTIONS, encoding="utf-8")
        (tmp_path / "other.md").write_text(
            "---\nname: Grace Hopper\n---\n\nEin anderes Profil.\n\n## Hobbys\n\n- Segeln\n",
            encoding="utf-8",
        )
        cv = build(
            tmp_path,
            {
                "sections": [
                    {"source": "cv.md", "end": "Berufserfahrung"},
                    {"source": "other.md"},
                ]
            },
        )
        assert cv.name == "Ada Lovelace"
        assert cv.summary == "Ein Kurzprofil."
        assert [s.title for s in cv.sections] == ["Hobbys"]

    def test_a_docx_first_entry_does_not_supply_it(self, projects_dir: Path) -> None:
        # A Word document has no frontmatter, so the header comes from the later
        # Markdown entry instead of the recipe failing.
        cv = build(
            projects_dir,
            {
                "sections": [
                    {"source": PROJEKTLISTE_NAME, "begin": "Projekthistorie", "title": "Projekte"},
                    {"source": "cv.md", "begin": "Kenntnisse"},
                    {"source": "cv.md", "end": "Berufserfahrung"},
                ]
            },
        )
        assert cv.name == "Ada Lovelace"

    def test_no_entry_starting_at_the_top_is_an_error(self, four_sections: Path) -> None:
        with pytest.raises(CVParseError, match="no section starts at the beginning of a Markdown"):
            build(four_sections, {"sections": [{"source": "cv.md", "begin": "Sprachen"}]})

    def test_the_error_says_how_to_fix_it(self, four_sections: Path) -> None:
        with pytest.raises(CVParseError, match=r"Leave 'begin' out of the entry"):
            build(four_sections, {"sections": [{"source": "cv.md", "begin": "Sprachen"}]})

    def test_the_photo_is_relative_to_that_file(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "portrait.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        (sub / "cv.md").write_text(
            "---\nname: Ada\nphoto: portrait.png\n---\n\n## Sprachen\n\n- Deutsch\n",
            encoding="utf-8",
        )
        cv = build(tmp_path, {"sections": [{"source": "sub/cv.md"}]})
        assert cv.photo is not None

    def test_that_file_must_carry_frontmatter(self, tmp_path: Path) -> None:
        (tmp_path / "cv.md").write_text("## Sprachen\n\n- Deutsch\n", encoding="utf-8")
        with pytest.raises(CVParseError, match="supplies the CV's header -- missing YAML"):
            build(tmp_path, {"sections": [{"source": "cv.md"}]})


class TestUnsupportedSources:
    def test_a_format_neither_reader_handles_is_an_error(self, four_sections: Path) -> None:
        (four_sections / "notes.txt").write_text("Sprachen\n", encoding="utf-8")
        with pytest.raises(CVParseError, match=r"expected \.md or \.docx, got \.txt"):
            spans(four_sections, {"source": "notes.txt", "begin": "Sprachen"})


class TestLoadCV:
    def test_a_json_source_is_a_recipe(self, projects_path: Path) -> None:
        loaded = load_cv(projects_path)
        titles = [s.title for s in loaded.cv.sections]
        assert titles == ["Berufserfahrung", "Projekte", "Kenntnisse"]

    def test_a_markdown_source_is_a_whole_cv_on_its_own(self, minimal_path: Path) -> None:
        loaded = load_cv(minimal_path)
        assert loaded.cv.name == "Ada Lovelace"
        assert loaded.name == "minimal"

    def test_the_output_name_comes_from_the_recipe(self, projects_dir: Path) -> None:
        loaded = load_cv(write_config(projects_dir, PROJECTS_CONFIG | {"output": "lebenslauf"}))
        assert loaded.name == "lebenslauf"

    def test_it_otherwise_follows_the_file_the_header_came_from(self, projects_path: Path) -> None:
        # No `output` key in PROJECTS_CONFIG, and the header comes from cv.md.
        assert load_cv(projects_path).name == "cv"

    def test_the_recipe_s_own_name_is_not_the_output_name(self, projects_path: Path) -> None:
        # Otherwise every build would write dist/config.html.
        assert projects_path.stem == "config"
        assert load_cv(projects_path).name == "cv"

    def test_sources_are_resolved_relative_to_the_recipe_not_the_cwd(
        self,
        projects_path: Path,
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path_factory.mktemp("elsewhere"))
        projects = load_cv(projects_path).cv.section("projekte")
        assert projects is not None
        assert projects.blocks


class TestRepositoryRecipe:
    """`data/config.json` is the project's own example, so it has to work."""

    def test_it_assembles_the_sample_document(self, sample_config_path: Path) -> None:
        cv, name = load_cv(sample_config_path)
        assert name == "cv"
        assert [s.title for s in cv.sections] == [
            "Berufserfahrung",
            "Projekte",
            "Kenntnisse",
            "Ausbildung",
            "Sprachen",
        ]

    def test_the_projects_come_from_the_word_list(self, sample_config_path: Path) -> None:
        projects = load_cv(sample_config_path).cv.section("projekte")
        assert projects is not None
        assert projects.blocks
        assert projects.source is not None
        assert projects.source.endswith(".docx")

    def test_every_other_section_comes_from_the_markdown_file(
        self, sample_config_path: Path
    ) -> None:
        cv = load_cv(sample_config_path).cv
        markdown = [s for s in cv.sections if s.slug != "projekte"]
        assert all(s.source is not None and s.source.endswith("cv.md") for s in markdown)
        assert all(s.markdown for s in markdown)


def test_build_cv_takes_a_config_object(projects_dir: Path) -> None:
    # The API a caller assembling a recipe in Python uses; the CLI is one caller.
    config = BuildConfig.model_validate(PROJECTS_CONFIG)
    cv, name = build_cv(config, projects_dir)
    assert [s.title for s in cv.sections] == ["Berufserfahrung", "Projekte", "Kenntnisse"]
    assert name == "cv"
