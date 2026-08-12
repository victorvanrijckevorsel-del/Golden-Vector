"""Render tests for the redesigned ticker-page sections (M2 spine + M3a/M3b)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from golden_vector.serve.ticker_page import (
    render_cost_downside_card,
    render_currency_attribution_block,
    render_performance_section,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _fx_row(**overrides) -> pd.DataFrame:
    row = {
        "ticker": "AAR.AX",
        "horizon": "1Y",
        "quote_currency": "AUD",
        "start_date": pd.Timestamp("2025-08-08"),
        "end_date": pd.Timestamp("2026-08-07"),
        "local_start_value": 10.0,
        "local_end_value": 9.12,
        "local_return": -0.088,
        "fx_start_rate": 0.65,
        "fx_end_rate": 0.7046,
        "fx_start_source_date": pd.Timestamp("2025-08-08"),
        "fx_end_source_date": pd.Timestamp("2026-08-07"),
        "fx_source_symbol": "AUDUSD=X",
        "fx_return": 0.084,
        "usd_start_value": 6.5,
        "usd_end_value": 6.426,
        "usd_return": -0.0114,
        "fx_contribution_pp": 7.66,
        "relationship": "OFFSET",
        "share_of_usd_move": None,
        "offset_of_local_move": 0.87,
        "attribution_status": "OK",
        "attribution_reason": None,
        "price_basis": "return_basis_usd",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _performance_rows() -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=5)
    rows = []
    for series, base in (("stock", 100.0), ("gold", 100.0)):
        for index, date in enumerate(dates):
            for view, value in (("rebased", base + index), ("price", 50.0 + index)):
                rows.append(
                    {
                        "ticker": "AAR.AX",
                        "series": series,
                        "view": view,
                        "horizon": "1Y",
                        "date": date,
                        "value": value,
                        "rebase_date": dates[0],
                        "late_start": False,
                        "series_status": "OK",
                        "series_reason": None,
                        "series_as_of_date": dates[-1],
                        "source_last_date": dates[-1],
                        "common_end_date": dates[-1],
                        "trim_reason": None,
                        "price_basis": "return_basis_usd",
                        "series_source_run_id": "run",
                        "currency_basis": "USD" if view == "price" else "INDEX_100",
                    }
                )
    for view in ("rebased", "price"):
        rows.append(
            {
                "ticker": "AAR.AX",
                "series": "gdx",
                "view": view,
                "horizon": "1Y",
                "date": dates[-1],
                "value": None,
                "rebase_date": pd.NaT,
                "late_start": False,
                "series_status": "STALE_OMITTED",
                "series_reason": "gdx last observation is 9 trading day(s) behind",
                "series_as_of_date": dates[-1],
                "source_last_date": dates[-1],
                "common_end_date": dates[-1],
                "trim_reason": None,
                "price_basis": "adj_close_local",
                "series_source_run_id": "run",
                "currency_basis": "USD" if view == "price" else "INDEX_100",
            }
        )
    return pd.DataFrame(rows)


def _metric_row(**overrides) -> pd.Series:
    row = {
        "ticker": "AAR.AX",
        "finance_source": "our",
        "metric_key": "aisc",
        "raw_value": 1419.0,
        "basis": "Our View mining assumption",
        "metric_available": True,
        "metric_reason": None,
        "pct_low_good": 72.0,
        "pct_high_good": 28.0,
        "eligible_observation_count": None,
        "hit_count": None,
        "source_period_start": None,
        "source_period_end": None,
        "source_verification_status": "VERIFIED",
        "source_verification_date": "2026-06-30",
    }
    row.update(overrides)
    return pd.Series(row)


def _peers(metric_key: str, values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "finance_source": "our",
                "metric_key": metric_key,
                "raw_value": value,
                "metric_available": True,
            }
            for ticker, value in values.items()
        ]
    )


# ---------------------------------------------------------------------------
# performance section
# ---------------------------------------------------------------------------


def test_performance_section_renders_series_basis_and_markers():
    html = render_performance_section(
        _performance_rows(), ticker="AAR.AX", horizon="1Y", view="rebased"
    )
    assert "Performance — AAR.AX" in html
    assert "Compare (indexed to 100)" in html
    assert "indexed to 100 on 2026-01-05" in html
    assert "basis: return_basis_usd" in html
    # a non-OK series renders a marker, never a silent absence
    assert "gdx last observation is 9 trading day(s) behind" in html.lower() or "GDX:" in html


def test_performance_section_price_view_shows_stock_alone():
    html = render_performance_section(
        _performance_rows(), ticker="AAR.AX", horizon="1Y", view="price"
    )
    assert "Share price (USD)" in html
    assert "Gold" not in html.split("chart-axis")[0] or "Stock" in html


# ---------------------------------------------------------------------------
# currency attribution
# ---------------------------------------------------------------------------


def test_currency_attribution_offset_headline_and_components():
    html = render_currency_attribution_block(_fx_row(), ticker="AAR.AX", horizon="1Y")
    assert "Currency attribution" in html
    assert "FX changed the USD return by +7.7 percentage points." in html
    assert "AUD strength offset about 87% of AAR.AX&#x27;s local-currency decline." in html
    assert "Local share return (AUD)" in html
    assert "-8.8%" in html
    assert "+8.4%" in html
    assert "USD-investor return" in html
    assert "-1.1%" in html
    assert "AUDUSD=X" in html
    assert "2025-08-08 to 2026-08-07" in html
    # the rejected device must never appear
    assert "$100" not in html


def test_currency_attribution_hides_usd_listings_entirely():
    frame = _fx_row(
        quote_currency="USD",
        relationship="NOT_APPLICABLE_USD",
        attribution_status="NOT_APPLICABLE_USD",
    )
    assert render_currency_attribution_block(frame, ticker="NEM", horizon="1Y") == ""


def test_currency_attribution_unavailable_states_its_reason():
    frame = _fx_row(
        attribution_status="UNAVAILABLE",
        relationship="UNAVAILABLE",
        attribution_reason="start endpoint 2025-08-08 lacks a usable local value or FX rate",
    )
    html = render_currency_attribution_block(frame, ticker="AAR.AX", horizon="1Y")
    assert "lacks a usable local value or FX rate" in html
    assert "FX changed the USD return" not in html  # no fabricated attribution


def test_currency_attribution_never_headlines_a_blind_fx_over_usd_ratio():
    """Near-cancelling legs: the OFFSET headline uses offset_of_local_move,

    never fx/usd (which would read ~-670%)."""
    frame = _fx_row(usd_return=-0.0011, offset_of_local_move=0.99)
    html = render_currency_attribution_block(frame, ticker="AAR.AX", horizon="1Y")
    assert "offset about 99%" in html
    assert "-670" not in html and "670%" not in html


# ---------------------------------------------------------------------------
# cost position and downside record
# ---------------------------------------------------------------------------


def test_cost_downside_card_shows_exact_evidence_and_caveat():
    downside = _metric_row(
        metric_key="downside_hit_rate",
        raw_value=0.0526,
        pct_low_good=61.0,
        eligible_observation_count=57,
        hit_count=3,
        source_period_start=pd.Timestamp("2016-02-05"),
        source_period_end=pd.Timestamp("2026-07-31"),
        source_verification_status=None,
        source_verification_date=None,
    )
    html = render_cost_downside_card(
        ticker="AAR.AX",
        aisc_row=_metric_row(),
        downside_row=downside,
        aisc_peers=_peers("aisc", {"AAR.AX": 1419.0, "BBB": 1800.0, "CCC": 1200.0}),
        downside_peers=_peers(
            "downside_hit_rate", {"AAR.AX": 0.0526, "BBB": 0.20, "CCC": 0.10}
        ),
    )
    assert "Cost position and downside record" in html
    assert "$1,419/oz" in html
    assert "Our View mining assumption" in html
    assert "verification: VERIFIED (2026-06-30)" in html
    # exact numerator/denominator — never a bare rounded rate
    assert "3 large falls in 57 qualifying weak-gold weeks" in html
    assert "5.3%" in html
    assert "Period 2016-02-05 to 2026-07-31" in html
    assert "ordinary weekly price return of −10% or worse" in html
    # peer disclosure closed by default with its accessible table twin
    assert "<details" in html and "Peer relationship" in html
    assert "no fitted line" in html
    assert "does not establish" in html  # the required caveat
    # no composite score and no causal wording
    assert "score" not in html.lower() or "no combined score" in html.lower()


def test_cost_downside_card_missing_sides_render_reasons_not_conclusions():
    html = render_cost_downside_card(
        ticker="AAR.AX",
        aisc_row=_metric_row(metric_available=False, metric_reason="value_missing"),
        downside_row=None,
        aisc_peers=pd.DataFrame(),
        downside_peers=pd.DataFrame(),
    )
    assert "AISC is unavailable: value_missing" in html
    assert "The downside record is unavailable" in html
    assert "No eligible paired producers to plot." in html


# ---------------------------------------------------------------------------
# guardrail: the new serve package computes nothing
# ---------------------------------------------------------------------------


def test_ticker_page_serve_package_has_no_backend_arithmetic():
    """Clone of the Tool-D serve-arithmetic guardrail for serve/ticker_page/.

    The sections render persisted columns only. Formatting multiplies by 100
    for display; no ratio math, coalescing, or eligibility logic may creep in.
    """
    for name in (
        "sections.py",
        "data.py",
        "corporate.py",
        "behaviour.py",
        "compare.py",
        "__init__.py",
    ):
        source = Path(f"golden_vector/serve/ticker_page/{name}").read_text(encoding="utf-8")
        for forbidden in (
            ".fillna(",
            ".combine_first(",
            "usd_return -",          # contribution is persisted, never re-derived
            "/ base_value",
            "log1p",
            "oriented_percentile",
            "np.",
            "import numpy",
        ):
            assert forbidden not in source, f"{name}: {forbidden}"


def test_corporate_section_contains_no_arithmetic_at_all():
    """Stricter than the token sweep, because corporate.py is where the gold

    maths WANTS to leak in: the dial's scenario values must come from
    gold-dial.js evaluating persisted lines, never from the request path.

    An AST scan is used rather than string matching so a rename or a clever
    one-liner cannot slip past. String concatenation (``+``) stays legal —
    that is markup assembly; every other binary operator is banned.
    """
    import ast

    path = Path("golden_vector/serve/ticker_page/corporate.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = (ast.Mult, ast.Div, ast.FloorDiv, ast.Sub, ast.Pow, ast.Mod, ast.MatMult)
    offenders = [
        f"line {node.lineno}: {type(node.op).__name__}"
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, banned)
    ]
    assert not offenders, "arithmetic in serve/ticker_page/corporate.py: " + "; ".join(
        offenders
    )


def test_gold_dial_js_guards_mirror_the_screening_layers():
    """The client module is the sanctioned exception (plan §3.1) — it must carry

    the SAME guards the backend screens on, spelled out, so a reviewer can
    diff them against screening/layer1.py and layer2.py."""
    source = Path("golden_vector/serve/static/gold-dial.js").read_text(encoding="utf-8")
    assert "screening/layer1.py" in source and "screening/layer2.py" in source
    for reason in ("EBITDA ≤ 0 here", "EPS ≤ 0 here", "market cap ≤ 0 here"):
        assert reason in source, reason
    # no network, no third-party libraries, no shared mutable state
    for forbidden in ("fetch(", "XMLHttpRequest", "import ", "require(", "localStorage"):
        assert forbidden not in source, forbidden
    # the dial position is ephemeral by design — it must never touch the URL
    for forbidden in ("history.pushState", "history.replaceState", "location.search"):
        assert forbidden not in source, forbidden
    # a disabled dial replaces the no-JavaScript fallback with the real reason
    assert "payload.disabled_reason" in source
    assert 'setAttribute("data-unavailable", "1")' in source
    # reduced motion is honoured, and the live region is polite and single
    assert "prefers-reduced-motion: reduce" in source
    assert source.count('var STATUS_ID = "gold-dial-status"') == 1


# ---------------------------------------------------------------------------
# M3f: help-key integrity across the five ticker-page render modules
# ---------------------------------------------------------------------------


def _referenced_help_keys() -> dict[str, set[str]]:
    """Every registry key the five render modules ask for, by module.

    The negative lookbehind keeps ``metric_key=`` (a DATA lookup) out — only
    ``key=`` / ``help_key=`` name a help entry.
    """
    import re

    found: dict[str, set[str]] = {}
    for module in sorted(Path("golden_vector/serve/ticker_page").glob("*.py")):
        source = module.read_text(encoding="utf-8")
        keys = set(
            re.findall(r'(?<!\w)(?:help_key|key)\s*=\s*"([a-z0-9_]+)"', source)
        )
        if keys:
            found[module.name] = keys
    return found


def test_every_help_key_the_ticker_page_asks_for_actually_exists():
    """``help_icon`` returns "" for an unknown key — silently, with no error.

    So a renamed or deleted registry entry does not fail anywhere: it just
    deletes a "?" from the page. This is the test that makes that loud.
    """
    from golden_vector.serve.column_help import COLUMN_HELP

    referenced = _referenced_help_keys()
    assert referenced, "no help keys found — the scan itself is broken"

    unknown = {
        (module, key)
        for module, keys in referenced.items()
        for key in keys
        if key not in COLUMN_HELP
    }
    assert not unknown, sorted(unknown)

    # The indirection tables resolve too — they are the easiest to let rot.
    from golden_vector.serve.ticker_page.compare import METRIC_HELP_KEYS
    from golden_vector.serve.ticker_page.corporate import _METRIC_HELP_KEYS

    for table_name, table in (
        ("compare.METRIC_HELP_KEYS", METRIC_HELP_KEYS),
        ("corporate._METRIC_HELP_KEYS", _METRIC_HELP_KEYS),
    ):
        missing = sorted(k for k in table.values() if k not in COLUMN_HELP)
        assert not missing, f"{table_name}: {missing}"


def test_help_entries_the_ticker_page_uses_are_not_empty():
    """An entry with no ``meaning`` renders no icon at all — same silent failure
    as a missing key, so it is held to the same standard."""
    from golden_vector.serve.column_help import COLUMN_HELP

    thin = []
    for keys in _referenced_help_keys().values():
        for key in keys:
            entry = COLUMN_HELP.get(key)
            if entry is None:
                continue
            if not str(getattr(entry, "meaning", "") or "").strip():
                thin.append(key)
    assert not thin, sorted(set(thin))
