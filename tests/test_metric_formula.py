from __future__ import annotations

from golden_vector.serve.metric_formula import (
    _METRIC_FORMULAS,
    _fmt,
    has_metric_formula,
    metric_formula_icon,
    metric_result_text,
    metric_value_text,
    metric_values_text,
)


def _row() -> dict[str, float]:
    # Mirrors a real tool_b row (AAUC.TO-like): EV = market cap + net debt; pct fields are fractions.
    return {
        "market_cap_musd": 3227.88,
        "net_debt_musd": -94.0,
        "ebitda_ltm_musd": 240.0,
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
        "aisc_margin_est_musd": 1270.17,
        "aisc_margin_yield": 0.3935,
        "leverage": -0.3917,
    }


def test_values_line_shows_components_and_result_without_a_formula_head():
    # metric_values_text is the "This stock" instantiation: components -> result, with the FULL
    # unit. The generic formula head now lives in the panel's FORMULA box (COLUMN_HELP), not here.
    text = metric_values_text("ev_ebitda", _row())
    assert "Market cap 3,228" in text
    assert "Net debt -94" in text
    assert "forward EBITDA 1,565" in text
    assert text.endswith("→ 2.0x")
    assert "EV/EBITDA =" not in text  # no head in the values line


def test_percent_ratios_render_as_percent():
    # margin_pct / aisc_margin_yield are stored as fractions and must display as percents, with the
    # component value bits present.
    margin = metric_values_text("margin_pct", _row())
    assert "Cash margin 2,383" in margin and "Gold price 4,173" in margin
    assert margin.endswith("→ 57.1%")  # 0.5710 -> 57.1%
    fcf = metric_values_text("aisc_margin_yield", _row())
    assert "AISC margin est. 1,270" in fcf and "Market cap 3,228" in fcf
    assert fcf.endswith("→ 39.4%")  # 0.3935 -> 39.4%


def test_component_scale_renders_a_fraction_as_a_percent():
    # The per-INPUT scale path (display = raw * scale) — exercise scale != 1.0 directly so a
    # future fraction-valued component is guarded, not just the result-level scaling.
    assert _fmt(0.5710, 1, 100.0) == "57.1"
    assert _fmt(2382.9, 0, 1.0) == "2,383"
    assert _fmt(None, 1, 100.0) is None
    assert _fmt(float("inf"), 1, 100.0) is None  # non-finite degrades to None


def test_forward_pe_and_cash_margin_values():
    pe = metric_values_text("forward_pe", _row())
    assert "Share price 25.64" in pe and "forward EPS 7.79" in pe
    assert pe.endswith("→ 3.29x")
    cm = metric_values_text("cash_margin_usd_per_oz", _row())
    assert "Gold price 4,173" in cm and "AISC 1,790" in cm
    assert cm.endswith("→ 2,383 $/oz")


def test_missing_result_or_unknown_metric_returns_none():
    assert metric_values_text("ev_ebitda", {}) is None  # no row
    assert metric_values_text("ev_ebitda", {"ev_ebitda": None}) is None  # value unavailable
    assert metric_values_text("not_a_metric", _row()) is None
    assert metric_formula_icon("ev_ebitda", {}) == ""


def test_missing_component_is_omitted_but_result_still_shown():
    row = _row()
    del row["net_debt_musd"]  # one input absent -> degrade per item
    text = metric_values_text("ev_ebitda", row)
    assert "Market cap 3,228" in text  # present input still shown
    assert "Net debt -94" not in text  # the absent input's value bit is gone
    assert text.endswith("→ 2.0x")  # result still shown


def test_cell_is_compact_but_values_line_keeps_full_unit():
    # Product decision: in-table CELLS are compact — no "x"/"$/oz" suffix (the column header + the
    # info button carry the unit). Percent fields keep "%". The "This stock" values line keeps the
    # full unit (it's the explanatory instantiation).
    row = _row()
    assert metric_result_text("ev_ebitda", row) == "2.0"  # not "2.0x"
    assert metric_result_text("forward_pe", row) == "3.29"  # not "3.29x"
    assert metric_result_text("leverage", row) == "-0.39"  # not "-0.39x"
    assert metric_result_text("cash_margin_usd_per_oz", row) == "2,383"  # not "2,383 $/oz"
    assert metric_result_text("margin_pct", row) == "57.1%"  # % stays
    assert metric_result_text("aisc_margin_yield", row) == "39.4%"
    # The values line still spells out the full unit.
    assert metric_values_text("ev_ebitda", row).endswith("→ 2.0x")
    assert metric_values_text("cash_margin_usd_per_oz", row).endswith("→ 2,383 $/oz")
    assert metric_result_text("ev_ebitda", {"ev_ebitda": None}) is None
    assert metric_result_text("not_a_metric", row) is None


def test_metric_value_text_formats_an_arbitrary_value_compactly():
    # Used to render the "(Yahoo X)" divergence accent on the detail snapshot: format a given
    # value with the metric's scale/decimals and COMPACT cell unit.
    assert metric_value_text("ev_ebitda", 2.5) == "2.5"  # no "x"
    assert metric_value_text("margin_pct", 0.42) == "42.0%"  # fraction -> percent
    assert metric_value_text("ev_ebitda", None) is None
    assert metric_value_text("not_a_metric", 1.0) is None


def test_leverage_values_line():
    text = metric_values_text("leverage", _row())
    assert "Net debt -94" in text
    assert "EBITDA LTM 240" in text
    assert text.endswith("→ -0.39x")


def test_all_components_missing_renders_no_orphan_arrow():
    # Result present but every input degraded away: the values line is just "-> result", no
    # dangling components or punctuation.
    text = metric_values_text("ev_ebitda", {"ev_ebitda": 2.0019})
    assert text == "→ 2.0x"


def test_metric_formula_icon_renders_the_shared_structured_panel():
    # The cell "i" uses the SAME structured panel as the column header (title + meaning + formula
    # from COLUMN_HELP[help_key]), PLUS a "This stock" values slot with this row's numbers.
    html = metric_formula_icon("cash_margin_usd_per_oz", _row())
    assert 'class="help-icon"' in html
    assert 'data-help-title="Cash margin"' in html
    assert 'data-help-meaning="' in html and 'data-help-meaning=""' not in html
    assert 'data-help-formula="' in html and 'data-help-formula=""' not in html
    assert 'data-help-values="' in html
    assert "Gold price 4,173" in html and "AISC 1,790" in html  # this stock's numbers
    assert "→ 2,383 $/oz" in html


def test_metric_formula_icon_appends_provenance_extra_to_values():
    html = metric_formula_icon("ev_ebitda", _row(), extra="Yahoo Fundamentals: as of 2024-Q3")
    assert "Yahoo Fundamentals: as of 2024-Q3" in html


def test_every_metric_help_key_is_registered():
    # Guards the silent-empty-icon risk: a typo'd/removed help_key would make help_icon return ""
    # (no cell "i") instead of crashing — so pin that every spec's help_key exists in the registry.
    from golden_vector.serve.column_help import COLUMN_HELP

    for metric_key, spec in _METRIC_FORMULAS.items():
        assert spec.help_key in COLUMN_HELP, f"{metric_key} -> {spec.help_key} not in COLUMN_HELP"
        assert COLUMN_HELP[spec.help_key].meaning, f"{spec.help_key} has no meaning"


def test_has_metric_formula():
    assert has_metric_formula("ev_ebitda")
    assert not has_metric_formula("not_a_metric")
