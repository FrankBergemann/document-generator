"""Recipe-declared text substitutions run against the assembled Document."""

from __future__ import annotations

import pytest

from cv_generator.config import PostprocessingStep
from cv_generator.errors import DocParseError
from cv_generator.models import (
    Document,
    RichBlock,
    RichCell,
    RichParagraph,
    RichRun,
    RichTable,
    Section,
)
from cv_generator.postprocessing import apply_postprocessing

PATTERN = "Rechnungsbetrag von 0.000,00 € Euro zu stellen"
OLD = "0.000,00 €"


def step(
    *, on: bool = True, pattern: str = PATTERN, old: str = OLD, cell: str = "Gesamtbetrag"
) -> PostprocessingStep:
    return PostprocessingStep.model_validate(
        {
            "set-invoice-amount": on,
            "pattern": pattern,
            "old": old,
            "new": "${amount-from-invoice-table}",
            "cell": cell,
        }
    )


def run(text: str) -> RichRun:
    return RichRun(text=text)


def cell(text: str) -> RichCell:
    return RichCell(paragraphs=[RichParagraph(runs=[run(text)])])


def table(*rows: list[str]) -> RichTable:
    return RichTable(rows=[[cell(text) for text in row] for row in rows])


def doc_with_table(*, markdown: str = "", table_block: RichTable | None = None) -> Document:
    blocks: list[RichBlock] = [table_block] if table_block is not None else []
    return Document(
        sections=[Section(title="Rechnung", slug="rechnung", markdown=markdown, blocks=blocks)]
    )


class TestSetInvoiceAmount:
    def test_it_replaces_old_in_a_sections_markdown(self) -> None:
        doc = doc_with_table(
            markdown=f"Bitte ist der {PATTERN}.",
            table_block=table(["Gesamtbetrag", "1.275,00 €"]),
        )

        apply_postprocessing(doc, [step()])

        assert "1.275,00 €" in doc.sections[0].markdown
        assert OLD not in doc.sections[0].markdown

    def test_it_replaces_old_inside_a_single_run(self) -> None:
        letter = RichParagraph(runs=[run(f"Bitte ist der {PATTERN}.")])
        doc = Document(
            sections=[
                Section(title="Anschreiben", slug="anschreiben", markdown="", blocks=[letter]),
                Section(
                    title="Betrag",
                    slug="betrag",
                    markdown="",
                    blocks=[table(["Gesamtbetrag", "1.275,00 €"])],
                ),
            ]
        )

        apply_postprocessing(doc, [step()])

        text = letter.runs[0].text
        assert "1.275,00 €" in text
        assert OLD not in text

    def test_it_replaces_every_occurrence_of_the_pattern(self) -> None:
        doc = Document(
            sections=[
                Section(title="A", slug="a", markdown=f"{PATTERN}.", source=None),
                Section(title="B", slug="b", markdown=f"Nochmal: {PATTERN}.", source=None),
                Section(
                    title="C", slug="c", markdown="", blocks=[table(["Gesamtbetrag", "1.275,00 €"])]
                ),
            ]
        )

        apply_postprocessing(doc, [step()])

        assert OLD not in doc.sections[0].markdown
        assert OLD not in doc.sections[1].markdown
        assert "1.275,00 €" in doc.sections[0].markdown
        assert "1.275,00 €" in doc.sections[1].markdown

    def test_a_disabled_step_is_left_untouched(self) -> None:
        doc = doc_with_table(markdown=PATTERN, table_block=table(["Gesamtbetrag", "1.275,00 €"]))

        apply_postprocessing(doc, [step(on=False)])

        assert doc.sections[0].markdown == PATTERN

    def test_the_cell_may_come_from_the_page_header_or_footer(self) -> None:
        doc = Document(
            sections=[Section(title="Rechnung", slug="rechnung", markdown=PATTERN)],
            page_footer=[table(["Gesamtbetrag", "1.275,00 €"])],
        )

        apply_postprocessing(doc, [step()])

        assert "1.275,00 €" in doc.sections[0].markdown

    def test_old_not_in_pattern_is_an_error(self) -> None:
        doc = doc_with_table(markdown=PATTERN, table_block=table(["Gesamtbetrag", "1.275,00 €"]))

        with pytest.raises(DocParseError, match="does not occur in 'pattern'"):
            apply_postprocessing(doc, [step(old="nicht im Satz enthalten")])

    def test_no_matching_cell_is_an_error(self) -> None:
        doc = doc_with_table(markdown=PATTERN, table_block=table(["Anderes Label", "1.275,00 €"]))

        with pytest.raises(DocParseError, match="no table cell contains"):
            apply_postprocessing(doc, [step()])

    def test_several_matching_cells_is_an_error(self) -> None:
        doc = doc_with_table(
            markdown=PATTERN,
            table_block=table(["Gesamtbetrag", "1.275,00 €"], ["Gesamtbetrag", "999,00 €"]),
        )

        with pytest.raises(DocParseError, match="2 table cells contain"):
            apply_postprocessing(doc, [step()])

    def test_matched_cell_with_nothing_to_its_right_is_an_error(self) -> None:
        doc = doc_with_table(markdown=PATTERN, table_block=table(["Gesamtbetrag"]))

        with pytest.raises(DocParseError, match="has no cell to its right"):
            apply_postprocessing(doc, [step()])

    def test_pattern_not_found_anywhere_is_an_error(self) -> None:
        doc = doc_with_table(
            markdown="Ganz anderer Text.", table_block=table(["Gesamtbetrag", "1.275,00 €"])
        )

        with pytest.raises(DocParseError, match="does not occur anywhere"):
            apply_postprocessing(doc, [step()])

    def test_pattern_split_across_two_runs_is_not_found(self) -> None:
        split = RichParagraph(
            runs=[run("Bitte ist der Rechnungsbetrag von "), run("0.000,00 € Euro zu stellen.")]
        )
        doc = Document(
            sections=[
                Section(title="Anschreiben", slug="anschreiben", markdown="", blocks=[split]),
                Section(
                    title="Betrag",
                    slug="betrag",
                    markdown="",
                    blocks=[table(["Gesamtbetrag", "1.275,00 €"])],
                ),
            ]
        )

        with pytest.raises(DocParseError, match="does not occur anywhere"):
            apply_postprocessing(doc, [step()])
