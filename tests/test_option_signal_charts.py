"""Render-layer tests for option-signal charts (OI-by-strike trimming)."""

from __future__ import annotations

from golden_vector.serve.option_signal_charts import (
    _select_oi_strikes,
    render_option_signal_charts,
)


def _strike_point(strike: float, open_interest: float) -> dict[str, object]:
    return {
        "side": "P" if strike < 50 else "C",
        "strike": strike,
        "open_interest": open_interest,
        "volume": 1.0,
        "expiration": "2026-12-18",
        "days_to_expiry": 200,
        "liquidity_flag": "OK",
        "quote_flags": "",
    }


def _wide_chain() -> list[dict[str, object]]:
    # 41 strikes from 30..70 in $1 steps, modest OI everywhere...
    points = [_strike_point(float(strike), 10.0) for strike in range(30, 71)]
    # ...plus two far-out strikes carrying huge open interest.
    points.append(_strike_point(95.0, 9000.0))
    points.append(_strike_point(5.0, 8000.0))
    return points


def test_select_oi_strikes_keeps_near_money_and_busiest() -> None:
    points = _wide_chain()
    shown, omitted = _select_oi_strikes(points, underlying_price=50.0)
    shown_strikes = {point["strike"] for point in shown}

    # Near the money (±5 around 50) is kept.
    assert {48.0, 49.0, 50.0, 51.0, 52.0}.issubset(shown_strikes)
    # The far-out high-open-interest strikes survive on the OI rule.
    assert 95.0 in shown_strikes
    assert 5.0 in shown_strikes
    # A far, low-OI strike is dropped.
    assert 65.0 not in shown_strikes
    # The dump was actually trimmed, and the count is reported (no silent cap).
    assert omitted > 0
    assert omitted == len(points) - len(shown)


def test_select_oi_strikes_falls_back_to_median_without_price() -> None:
    points = _wide_chain()
    shown, _ = _select_oi_strikes(points, underlying_price=None)
    # Median strike of 30..70 is 50; the near-money window should still center there.
    assert 50.0 in {point["strike"] for point in shown}


def test_select_oi_strikes_keeps_everything_for_a_small_chain() -> None:
    points = [_strike_point(float(strike), 10.0) for strike in range(48, 53)]
    shown, omitted = _select_oi_strikes(points, underlying_price=50.0)
    assert omitted == 0
    assert len(shown) == len(points)


def test_render_charts_shows_trim_note_only_when_rows_omitted() -> None:
    wide = render_option_signal_charts([], _wide_chain(), [], underlying_price=50.0)
    assert "Open Interest by Strike" in wide
    assert "further strike rows are omitted" in wide

    small = render_option_signal_charts(
        [],
        [_strike_point(float(strike), 10.0) for strike in range(48, 53)],
        [],
        underlying_price=50.0,
    )
    assert "further strike rows are omitted" not in small
