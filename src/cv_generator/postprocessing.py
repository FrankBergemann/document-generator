"""Recipe-declared text substitutions run against the assembled Document.

A recipe's ``postprocessing`` list (:class:`cv_generator.config.PostprocessingStep`)
names substitutions to make after every section has been copied into the
Document and before any output format is rendered -- see
:func:`cv_generator.parser.build_doc` -- so a substitution shows up in
``.html``, ``.docx`` and ``.pdf`` alike instead of being patched into one
format after the fact.

The one step implemented is ``set-invoice-amount``: it finds the one table
cell containing a given label (from *any* imported ``.docx``/``.xlsx``
section -- there is no separate notion of "the xlsx source" once sections
are assembled into one Document), takes the text of the cell to its right,
and substitutes that into a placeholder inside a given sentence, wherever
that sentence occurs in the Document.

A sentence split across two differently-formatted runs by the source
document's own formatting is *not* reassembled to search across the split --
the pattern has to sit whole inside one run (or one section's Markdown) to
be found. That covers a plain sentence in a Word paragraph, which is this
project's own use of the step and not usually split that way.
"""

from __future__ import annotations

from collections.abc import Iterator

from cv_generator.config import PostprocessingStep
from cv_generator.errors import DocParseError
from cv_generator.models import Document, RichBlock, RichCell, RichParagraph, RichTable


def apply_postprocessing(
    doc: Document, steps: list[PostprocessingStep], *, source: str = "<config>"
) -> None:
    """Run every enabled step in ``steps`` against ``doc``, in place.

    A step whose switch is off is skipped, not removed -- that is what makes
    it a switch rather than the entry's mere presence.

    Raises:
        DocParseError: if a step's ``old`` does not occur in its ``pattern``,
            its ``cell`` matches zero or several table cells, the matched
            cell has nothing to its right, or its ``pattern`` does not occur
            anywhere in the Document.
    """
    for index, step in enumerate(steps):
        if not step.set_invoice_amount:
            continue
        _set_invoice_amount(doc, step, source=f"{source}: postprocessing[{index}]")


def _set_invoice_amount(doc: Document, step: PostprocessingStep, *, source: str) -> None:
    if step.old not in step.pattern:
        raise DocParseError(
            f"{source}: 'old' {step.old!r} does not occur in 'pattern' {step.pattern!r}"
        )

    replacement = _cell_to_the_right_of(doc, step.cell, source=source)
    edited = step.pattern.replace(step.old, replacement)

    if _replace_everywhere(doc, step.pattern, edited) == 0:
        raise DocParseError(
            f"{source}: pattern {step.pattern!r} does not occur anywhere in the Document"
        )


def _cell_to_the_right_of(doc: Document, label: str, *, source: str) -> str:
    matches = []
    for table in _tables(doc):
        for row in table.rows:
            for column, cell in enumerate(row):
                if label not in _cell_text(cell):
                    continue
                if column + 1 >= len(row):
                    raise DocParseError(f"{source}: cell {label!r} has no cell to its right")
                matches.append(_cell_text(row[column + 1]))

    if not matches:
        raise DocParseError(f"{source}: no table cell contains {label!r}")
    if len(matches) > 1:
        raise DocParseError(
            f"{source}: {len(matches)} table cells contain {label!r}; keep exactly one"
        )
    return matches[0]


def _tables(doc: Document) -> Iterator[RichTable]:
    block_lists = [doc.page_header, doc.page_footer, *(section.blocks for section in doc.sections)]
    for blocks in block_lists:
        for block in blocks:
            if isinstance(block, RichTable):
                yield block


def _cell_text(cell: RichCell) -> str:
    return "\n".join(paragraph.text() for paragraph in cell.paragraphs).strip()


def _replace_everywhere(doc: Document, old: str, new: str) -> int:
    count = 0
    for section in doc.sections:
        count += section.markdown.count(old)
        section.markdown = section.markdown.replace(old, new)

    block_lists = [doc.page_header, doc.page_footer, *(section.blocks for section in doc.sections)]
    for blocks in block_lists:
        count += _replace_in_blocks(blocks, old, new)
    return count


def _replace_in_blocks(blocks: list[RichBlock], old: str, new: str) -> int:
    count = 0
    for block in blocks:
        if isinstance(block, RichParagraph):
            count += _replace_in_paragraph(block, old, new)
        else:
            for row in block.rows:
                for cell in row:
                    for paragraph in cell.paragraphs:
                        count += _replace_in_paragraph(paragraph, old, new)
    return count


def _replace_in_paragraph(paragraph: RichParagraph, old: str, new: str) -> int:
    count = 0
    for run in paragraph.runs:
        if old in run.text:
            count += run.text.count(old)
            run.text = run.text.replace(old, new)
    return count


__all__ = ["apply_postprocessing"]
