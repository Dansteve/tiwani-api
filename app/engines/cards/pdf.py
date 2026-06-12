"""The Continuity Card PDF renderer (the paid convenience export, Product.md section 4.6).

A PURE function that turns an already-assembled CardContent (the SAFE, governed,
first-name-only card the web card shows) into PDF bytes. It renders the SAME content
the public web card renders, nothing more: the supportive intro, the participation
tier in plain words, the top strategies, the standing health-and-safety line, the calm
"if things get difficult" line, and (when present) the freshness note. The web card is
the source of truth; this is just a printable rendering of it.

Why this is a thin renderer and not a second assembler: the card is assembled once, by
app/engines/cards/builder.py (which runs the SHARED non-clinical guard over every
helper-facing string), and the data service hands the route the governed CardContent
through read_card_content_by_id (the owner re-open-by-id path). This module receives
that CardContent and only LAYS IT OUT. It re-scores nothing and re-shapes nothing.

THE SAFETY RULES (the same that bind the assembler, root CLAUDE.md / the cards module):
  - FIRST name only, no extra PII. The renderer draws ONLY fields already on
    CardContent (child_first_name, the tier label, the governed copy, the strategies);
    there is no name, contact detail, user_id, child_id, or activity_id to draw.
  - NO clinical language. Every string this module draws onto the page is run through
    the ONE SHARED guard (app/engines/alerts/guard.py: assert_clean) before it is
    emitted, the same guard the assembler uses. There is no second prohibited-words
    list. The content arriving here is already guarded at build time; this is the
    render-time backstop the hard rules require, so a prohibited word can never reach a
    printed page even if a future change introduced one upstream.

PDF library: reportlab (pinned in requirements.txt), the lightweight, pure-Python PDF
toolkit. We use the low-level canvas (no platypus flow framework) so the layout is
explicit and dependency-light: one A4 page, a wrapped paragraph helper, no images, no
fonts beyond the built-in Helvetica family.
"""

from __future__ import annotations

import io
from typing import List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.engines.alerts.guard import assert_clean
from app.models.card import CardContent

# Page geometry (A4, comfortable reading margins). All positions derive from these, so
# the layout is one source of truth and reflows if a margin changes.
_PAGE_WIDTH, _PAGE_HEIGHT = A4
_MARGIN_X = 20 * mm
_MARGIN_TOP = 22 * mm
_MARGIN_BOTTOM = 18 * mm
_CONTENT_WIDTH = _PAGE_WIDTH - 2 * _MARGIN_X

# The one font family on the card (a built-in, so no font file ships). Sizes step down
# from the title, mirroring the type hierarchy of the on-screen card.
_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_ITALIC = "Helvetica-Oblique"

_TITLE_SIZE = 20
_HEADING_SIZE = 12
_BODY_SIZE = 11
_NOTE_SIZE = 10

# Vertical rhythm: the leading (line height) per text size and the gaps between blocks,
# kept in one place so spacing is consistent down the page.
_BODY_LEADING = 15
_NOTE_LEADING = 13
_GAP_AFTER_TITLE = 6 * mm
_GAP_BETWEEN_BLOCKS = 5 * mm
_GAP_AFTER_HEADING = 2 * mm
_GAP_BETWEEN_STRATEGIES = 3 * mm


def _wrap(text: str, font: str, size: float, max_width: float) -> List[str]:
    """Greedy word-wrap `text` to lines no wider than max_width at (font, size).

    Uses reportlab's exact stringWidth metrics so a line never overruns the text
    column. A single word longer than the column is left on its own line (it cannot be
    split without hyphenation, which the governed copy never needs).
    """
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class _Cursor:
    """A top-down draw cursor: tracks the y baseline and emits wrapped paragraphs.

    reportlab's canvas origin is the BOTTOM-left and y grows upward, which is awkward
    for a top-to-bottom document. This wrapper starts at the top margin and moves DOWN
    as it draws, so the calling layout reads in document order. It does not paginate:
    the card is a one-page summary by design (section 4.6), and the governed content is
    bounded (a short intro, <=5 strategies, three fixed lines), so it fits one A4 page.
    """

    def __init__(self, pdf: canvas.Canvas):
        self._pdf = pdf
        self._y = _PAGE_HEIGHT - _MARGIN_TOP

    def paragraph(
        self,
        text: str,
        *,
        font: str = _FONT,
        size: float = _BODY_SIZE,
        leading: float = _BODY_LEADING,
        indent: float = 0.0,
    ) -> None:
        """Draw one wrapped paragraph at the current baseline, advancing downward."""
        x = _MARGIN_X + indent
        width = _CONTENT_WIDTH - indent
        self._pdf.setFont(font, size)
        for line in _wrap(text, font, size, width):
            self._y -= leading
            self._pdf.drawString(x, self._y, line)

    def gap(self, amount: float) -> None:
        """Advance the baseline down by `amount` (a blank block of vertical space)."""
        self._y -= amount


def render_card_pdf(content: CardContent) -> bytes:
    """Render a governed CardContent to one-page PDF bytes (the printable card).

    Lays out, in the same order the web card shows them: a title naming the care
    recipient's FIRST name, the activity, the participation tier in plain words, the
    supportive intro, the top strategies (title + detail), the standing health-and-safety
    line, the calm "if things get difficult" line, and (when the card carries one) the
    freshness note. When the card is stale (is_stale), a short caution prefixes the
    freshness note, mirroring the on-screen "this may be out of date" signal.

    Every string drawn onto the page is first passed through the SHARED non-clinical
    guard (app/engines/alerts/guard.py). The content is already guarded at build time, so
    this is the render-time backstop the hard rules mandate: a prohibited clinical word
    can never reach the page. A violation raises ProhibitedWordError (a governance error
    to fix, never silently scrubbed), exactly as it does in the assembler.

    Returns the PDF as bytes so the route can hand it back as an application/pdf download
    without touching the filesystem.
    """
    first_name = content.child_first_name
    title = f"{first_name}'s support card"
    activity_line = f"Activity: {content.activity_name}"
    tier_line = f"How {first_name} is taking part: {content.tier_label}"
    strategies_heading = "What helps most"
    stale_caution = (
        "Please note: this card may be out of date. Ask the family for an up to date version."
    )

    # The render-time guard over EVERY string that will be drawn: the fixed labels we
    # compose here AND the governed copy carried on the content (intro, each strategy
    # title/detail, the safety + if-difficult + freshness lines). One shared definition,
    # the same guard the builder uses; nothing reaches the page unguarded.
    guarded: List[str] = [
        title,
        activity_line,
        tier_line,
        strategies_heading,
        content.intro,
        content.safety_note,
        content.if_difficult,
        *[s.title for s in content.strategies],
        *[s.detail for s in content.strategies],
    ]
    if content.freshness_note:
        guarded.append(content.freshness_note)
    if content.is_stale:
        guarded.append(stale_caution)
    assert_clean(*guarded)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(title)
    cursor = _Cursor(pdf)

    # Title block: the care recipient's first name (the largest text), then the activity
    # and the plain-words tier just under it.
    cursor.paragraph(title, font=_FONT_BOLD, size=_TITLE_SIZE, leading=_TITLE_SIZE + 4)
    cursor.gap(_GAP_AFTER_TITLE)
    cursor.paragraph(activity_line, font=_FONT_BOLD, size=_HEADING_SIZE, leading=_BODY_LEADING)
    cursor.paragraph(tier_line, font=_FONT, size=_BODY_SIZE, leading=_BODY_LEADING)
    cursor.gap(_GAP_BETWEEN_BLOCKS)

    # The supportive intro.
    cursor.paragraph(content.intro, font=_FONT, size=_BODY_SIZE, leading=_BODY_LEADING)
    cursor.gap(_GAP_BETWEEN_BLOCKS)

    # The top strategies: a section heading, then each strategy as a bold title and a
    # wrapped, indented detail. When the source phrase is flat (title == detail), the
    # detail line is skipped so the same sentence is not printed twice.
    if content.strategies:
        cursor.paragraph(
            strategies_heading, font=_FONT_BOLD, size=_HEADING_SIZE, leading=_BODY_LEADING
        )
        cursor.gap(_GAP_AFTER_HEADING)
        for strategy in content.strategies:
            cursor.paragraph(
                strategy.title, font=_FONT_BOLD, size=_BODY_SIZE, leading=_BODY_LEADING
            )
            if strategy.detail and strategy.detail != strategy.title:
                cursor.paragraph(
                    strategy.detail,
                    font=_FONT,
                    size=_BODY_SIZE,
                    leading=_BODY_LEADING,
                    indent=4 * mm,
                )
            cursor.gap(_GAP_BETWEEN_STRATEGIES)
        cursor.gap(_GAP_BETWEEN_BLOCKS - _GAP_BETWEEN_STRATEGIES)

    # The standing health-and-safety line (on every card).
    cursor.paragraph(content.safety_note, font=_FONT, size=_BODY_SIZE, leading=_BODY_LEADING)
    cursor.gap(_GAP_BETWEEN_BLOCKS)

    # The calm "if things get difficult" line (on every card).
    cursor.paragraph(content.if_difficult, font=_FONT, size=_BODY_SIZE, leading=_BODY_LEADING)

    # The freshness note (when present), prefixed by a stale caution when the card is old.
    if content.freshness_note:
        cursor.gap(_GAP_BETWEEN_BLOCKS)
        if content.is_stale:
            cursor.paragraph(
                stale_caution, font=_FONT_BOLD, size=_NOTE_SIZE, leading=_NOTE_LEADING
            )
        cursor.paragraph(
            content.freshness_note, font=_FONT_ITALIC, size=_NOTE_SIZE, leading=_NOTE_LEADING
        )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
