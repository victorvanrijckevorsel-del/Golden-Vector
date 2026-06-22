from __future__ import annotations

from golden_vector.serve.metric_formula import (
    _fmt,
    has_metric_formula,
    metric_formula_icon,
    metric_formula_text,
    metric_result_text,
)


def _row() -> dict[str, float]:
    # Mirrors a real tool_b row (AAUC.TO-like): EV = market cap + net debt; pct fields are fractions.
    return {
        "market_cap_musd": 3227.88,
        "net_debt_musd": -94.0,
        "forward_ebitda_musd": 1565.45,
        "enterprise_value_musd": 3133.88,
        "ev_ebitda": 2.0019,
        "share_price_usd": 25.64,
        "forward_eps": 7.79,
        "forward_pe": 3.293,
        "gold_price_assumption": 4172.9,
        "aisc_usd_per_oz": 1790.0,
        "cash_margin_usd_per_oz": 2382.9,
        "margin_pct": 0.5710,
        "sustainable_fcf_musd": 1270.17,
        "fcf_yield": 0.3935,
        "leverage": -0.3917,
    }


def test_ev_ebitda_shows_formula_inputs_and_result():
    text = metric_formula_text("ev_ebitda", _row())
    assert "EV/EBITDA = (Market cap + net debt) / forward EBITDA" in text
    assert "Market cap 3,228" in text
    assert "Net debt -94" in text
    assert "forward EBITDA 1,565" in text
    assert "→ 2.0x" in text


def test_percent_ratios_render_as_percent():
    # margin_pct / fcf_yield are stored as fractions and must display as percents — and the
    # formula HEAD + component value bits must render too (not only the trailing result).
    margin = metric_formula_text("margin_pct", _row())
    assert margin.startswith("Margin % =")
    assert "Cash margin 2,383" in margin and "Gold price 4,173" in margin
    assert "→ 57.1%" in margin  # 0.5710 -> 57.1%
    fcf = metric_formula_text("fcf_yield", _row())
    assert fcf.startswith("FCF yield =")
    assert "Sustainable FCF 1,270" in fcf and "Market cap 3,228" in fcf
    assert "→ 39.4%" in fcf  # 0.3935 -> 39.4%


def test_component_scale_renders_a_fraction_as_a_percent():
    # The per-INPUT scale path (display = raw * scale) — exercise scale != 1.0 directly so a
    # future fraction-valued component is guarded, not just the result-level scaling.
    assert _fmt(0.5710, 1, 100.0) == "57.1"
    assert _fmt(2382.9, 0, 1.0) == "2,383"
    assert _fmt(None, 1, 100.0) is None
    assert _fmt(float("inf"), 1, 100.0) is None  # non-finite degrades to None


def test_forward_pe_and_cash_margin_formulas():
    pe = metric_formula_text("forward_pe", _row())
    assert "Forward P/E = Share price / forward EPS" in pe
    assert "Share price 25.64" in pe and "forward EPS 7.79" in pe
    assert "→ 3.29x" in pe
    cm = metric_formula_text("cash_margin_usd_per_oz", _row())
    assert "Cash margin = Gold price minus AISC" in cm
    assert "→ 2,383 $/oz" in cm


def test_missing_result_or_unknown_metric_returns_none():
    assert metric_formula_text("ev_ebitda", {}) is None  # no row
    assert metric_formula_text("ev_ebitda", {"ev_ebitda": None}) is None  # value unavailable
    assert metric_formula_text("not_a_metric", _row()) is None
    assert metric_formula_icon("ev_ebitda", {}) == ""


def test_missing_component_is_omitted_but_result_still_shown():
    row = _row()
    del row["net_debt_musd"]  # one input absent -> degrade per item
    text = metric_formula_text("ev_ebitda", row)
    assert "Market cap 3,228" in text  # present input still shown
    # Assert the absent input's VALUE bit is gone (not just the label — the lowercase formula
    # clause "(Market cap + net debt) ..." legitimately contains "net debt").
    assert "Net debt -94" not in text
    assert "→ 2.0x" in text  # result still shown


def test_cell_is_compact_but_popover_keeps_full_unit():
    # Product decision: in-table CELLS are compact — no "x"/"$/oz" suffix (the column header + the
    # info button carry the unit), matching the Tool B overview. Percent fields keep "%" because
    # the cell needs it to be read. The formula POPOVER keeps the full unit.
    row = _row()
    assert metric_result_text("ev_ebitda", row) == "2.0"  # not "2.0x"
    assert metric_result_text("forward_pe", row) == "3.29"  # not "3.29x"
    assert metric_result_text("leverage", row) == "-0.39"  # not "-0.39x"
    assert metric_result_text("cash_margin_usd_per_oz", row) == "2,383"  # not "2,383 $/oz"
    assert metric_result_text("margin_pct", row) == "57.1%"  # % stays
    assert metric_result_text("fcf_yield", row) == "39.4%"
    # The popover still spells out the full unit.
    assert metric_formula_text("ev_ebitda", row).endswith("→ 2.0x")
    assert metric_formula_text("cash_margin_usd_per_oz", row).endswith("→ 2,383 $/oz")
    assert metric_result_text("ev_ebitda", {"ev_ebitda": None}) is None
    assert metric_result_text("not_a_metric", row) is None


def test_metric_value_text_formats_an_arbitrary_value_compactly():
    # Used to render the "(Yahoo X)" divergence accent on the detail snapshot: format a given
    # value with the metric's scale/decimals and COMPACT cell unit.
    from golden_vector.serve.metric_formula import metric_value_text

    assert metric_value_text("ev_ebitda", 2.5) == "2.5"  # no "x"
    assert metric_value_text("margin_pct", 0.42) == "42.0%"  # fraction -> percent
    assert metric_value_text("ev_ebitda", None) is None
    assert metric_value_text("not_a_metric", 1.0) is None


def test_leverage_shows_net_debt_and_result():
    text = metric_formula_text("leverage", _row())
    assert "Net Debt/EBITDA = Net debt / trailing (LTM) EBITDA" in text
    assert "Net debt -94" in text
    assert "→ -0.39x" in text


def test_all_components_missing_renders_no_orphan_arrow():
    # Result present but every input degraded away: formula flows straight into the arrow,
    # no awkward "formula. -> result" dangling punctuation.
    text = metric_formula_text("ev_ebitda", {"ev_ebitda": 2.0019})
    assert ". →" not in text
    assert text == "EV/EBITDA = (Market cap + net debt) / forward EBITDA → 2.0x"


def test_icon_renders_and_appends_extra_provenance():
    icon = metric_formula_icon("ev_ebitda", _row(), extra="Net debt: source Yahoo.")
    assert "help-icon" in icon
    assert "EV/EBITDA =" in icon  # formula text in the popover
    assert "Net debt: source Yahoo." in icon  # appended provenance
    assert has_metric_formula("ev_ebitda")
    assert not has_metric_formula("market_cap_musd")
