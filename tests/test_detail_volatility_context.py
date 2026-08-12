"""Volatility diagnostics are PUBLISHED, never estimated in the request path.

Originally a regression for the expanded-review HIGH finding: a serve-side fork
recomputed volatility for non-canonical windows, read a misspelled config
attribute, swallowed the AttributeError, and classified EVERY non-canonical
window as UNKNOWN — rendering "Residual volatility is moderate" copy for an
89%-vol window.

M3c deleted that recompute (``_compute_window_volatility``) outright, so the
guarantee is now the opposite and stronger: a non-canonical window is never given
numbers at all — it gets the canonical-window note; the canonical window renders
the published values verbatim; an ineligible window is suppressed with its
status.
"""

from __future__ import annotations

from golden_vector.serve.ticker_page.behaviour import (
    VOLATILITY_CANONICAL_NOTE,
    render_volatility_panel,
)


def _tool_a_row(**overrides) -> dict:
    """An otherwise-healthy published row; each test perturbs ONE field."""

    row = {
        "ticker": "NEM",
        "volatility_anchor_window_id": "12M",
        "window_status_6m": "ELIGIBLE",
        "window_status_12m": "ELIGIBLE",
        "total_volatility_52w": 0.42,
        "residual_volatility_52w": 0.31,
        "downside_volatility_52w": 0.27,
        "volatility_context": "LOW_NOISE",
    }
    row.update(overrides)
    return row


def test_non_canonical_window_is_never_given_numbers() -> None:
    """The old fork estimated 6M live; the panel must now refuse and say why."""

    html = render_volatility_panel(_tool_a_row(), active_window="6M")
    assert "<h4>Volatility diagnostics (6M)" in html
    assert VOLATILITY_CANONICAL_NOTE in html
    # It names the window that DOES publish them, and shows no published number
    # under the 6M heading.
    assert "For this ticker that window is 1Y" in html
    assert "LOW_NOISE" not in html
    assert "42.0%" not in html
    assert "31.0%" not in html
    assert "27.0%" not in html


def test_canonical_window_renders_the_published_values_verbatim() -> None:
    """Control: on the canonical window every published field is shown as-is."""

    html = render_volatility_panel(_tool_a_row(), active_window="12M")
    assert "<h4>Volatility diagnostics (1Y)" in html
    assert VOLATILITY_CANONICAL_NOTE not in html
    assert "42.0%" in html  # total_volatility_52w
    assert "31.0%" in html  # residual_volatility_52w
    assert "27.0%" in html  # downside_volatility_52w
    assert "LOW_NOISE" in html
    assert "Published 52-week values for the canonical window." in html


def test_ineligible_window_is_suppressed_with_its_status() -> None:
    html = render_volatility_panel(
        _tool_a_row(window_status_6m="INELIGIBLE_LOW_OBSERVATIONS"), active_window="6M"
    )
    assert "The 6M window is not eligible for this ticker" in html
    assert "INELIGIBLE_LOW_OBSERVATIONS" in html
    assert "LOW_NOISE" not in html


def test_ineligible_beats_canonical_so_a_bad_canonical_window_shows_no_numbers() -> None:
    """Eligibility is checked FIRST: an ineligible canonical window is suppressed
    rather than publishing its (untrustworthy) 52-week values."""

    html = render_volatility_panel(
        _tool_a_row(window_status_12m="INELIGIBLE_LOW_OBSERVATIONS"), active_window="12M"
    )
    assert "The 1Y window is not eligible for this ticker" in html
    assert "42.0%" not in html
    assert "LOW_NOISE" not in html
