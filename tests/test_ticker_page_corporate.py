"""M3b: corporate finance section, gold dial payload, and safe JSON embedding.

Everything here is fixture-driven — no test reads a real ``data/`` artifact.

**Recorded contract gap** (see the lane notes; not worked around by computing
anything in serve): there is no EV/EBITDA screening check at all (no threshold,
no code, no column), so no EV/EBITDA sentence can exist.

The forward-P/E gap is CLOSED. ``screening/verdicts.py`` now persists
``fundamental_check_fail_codes`` (+ ``_official``), so ``FORWARD_PE_FAIL`` is a
real machine-readable code and the notice renders it through the same registry
as the layer-1 codes. The column is absent on artifacts built before that
change, which must render silently rather than crash — locked below.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.ticker_page_state import TickerPageArtifactState
from golden_vector.contracts.ticker_page import (
    GOLD_RESPONSE_CONSTANT_COLUMNS,
    GOLD_RESPONSE_LINE_METRICS,
)
from golden_vector.serve.embed import embed_json_payload
from golden_vector.serve.ticker_page import (
    GOLD_DIAL_PAYLOAD_ID,
    TickerPageData,
    YAHOO_RESILIENCE_REASON,
    render_corporate_finance_section,
    render_gold_dial_control,
)
from golden_vector.serve.ticker_page.corporate import format_metric

PARITY_FIXTURE = Path(__file__).parent / "fixtures" / "gold_dial_parity.json"


def _app_config():
    return load_app_config(ProjectPaths.discover()).app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _gold_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "finance_source": "our",
        "line_slope_forward_revenue_musd": 5.9,
        "line_intercept_forward_revenue_musd": 0.0,
        "line_slope_forward_ebitda_musd": 5.723,
        "line_intercept_forward_ebitda_musd": -6962.0,
        "line_slope_forward_net_income_musd": 4.12056,
        "line_intercept_forward_net_income_musd": -6956.64,
        "line_slope_forward_eps": 0.003911,
        "line_intercept_forward_eps": -6.602155,
        "line_slope_aisc_margin_est_musd": 5.9,
        "line_intercept_aisc_margin_est_musd": -9239.4,
        "market_cap_musd": 123866.0,
        "enterprise_value_musd": 124362.0,
        "net_debt_musd": 500.0,
        "interest_expense_musd": 200.0,
        "share_price_usd": 117.57,
        "aisc_usd_per_oz": 1566.0,
        "cash_cost_usd_per_oz": 1180.0,
        "production_oz": 5900000.0,
        "ebitda_ltm_musd": 11850.0,
        "spot_gold_usd": 4452.0,
        "spot_gold_date": "2026-08-11",
        "spot_margin_usd_per_oz": 2886.0,
        "spot_margin_pct": 0.648248,
        "spot_aisc_margin_yield": 0.137465,
        "spot_ev_ebitda": 6.716432,
        "spot_forward_pe": 10.876869,
        "spot_leverage_stressed": 0.027003,
        "spot_margin_basis": "aisc",
        "gold_response_status": "OK",
        "gold_response_reason": None,
        "linearity_max_residual": 0.01,
        "schema_version": 1,
        "source_run_id": "run-1",
        "snapshot_refresh_run_id": "run-1",
        "parent_refresh_id": "run-1",
        "config_hash": "hash",
    }
    row.update(overrides)
    return row


def _data(
    *rows: dict[str, object],
    artifact_status: str = "OK",
    artifact_reason: str | None = None,
) -> TickerPageData:
    frame = pd.DataFrame(list(rows) or [_gold_row()])
    blank = TickerPageArtifactState(status="OK", reason=None, frame=pd.DataFrame())
    return TickerPageData(
        gold_response=TickerPageArtifactState(
            status=artifact_status, reason=artifact_reason, frame=frame
        ),
        percentiles=blank,
        performance=blank,
        research_series=blank,
        fx_attribution=blank,
    )


def _tool_b_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "as_of_date": "2026-08-11",
        "gold_price_assumption": 4452.0,
        "aisc_usd_per_oz": 1566.0,
        "margin_pct": 0.648248,
        "aisc_margin_yield": 0.137465,
        "reserve_life_years": 22.0,
        "leverage": 0.042,
        "forward_pe": 10.876869,
        "layer1_fail_reasons": None,
        "layer1_status": "PASS",
        # Present-and-null is the modern artifact's healthy state; the
        # absent-column case is built by popping these (older artifacts).
        "fundamental_check_fail_codes": None,
        "fundamental_check_fail_codes_official": None,
        "financial_data_status": "OK",
        "snapshot_as_of_date": "2026-08-11",
        "snapshot_normalization_status": "OK",
        "fx_staleness_days": 0.0,
    }
    row.update(overrides)
    return row


def _tool_d_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "as_of_date": "2026-08-11",
        "breaks_even_at_gold_usd": 1566.0,
        "interest_cover_gold_usd": 1251.44,
        "debt_stress_gold_usd": 1245.62,
        "survival_distance_to_interest_cover_pct": 0.718903,
        "fragility_ebitda_pct_per_10pct_gold": 0.137598,
        "cost_curve_aisc_percentile": 31.111,
        "resilience_data_status": "OK",
    }
    row.update(overrides)
    return row


def _render(
    *,
    data: TickerPageData | None = None,
    finance_source: str = "our",
    tool_b_row: dict[str, object] | None = None,
    tool_d_row: dict[str, object] | None = None,
    app_config=None,
) -> str:
    return render_corporate_finance_section(
        data if data is not None else _data(),
        ticker="NEM",
        finance_source=finance_source,
        tool_b_row=_tool_b_row() if tool_b_row is None else tool_b_row,
        tool_d_row=_tool_d_row() if tool_d_row is None else tool_d_row,
        app_config=app_config if app_config is not None else _app_config(),
    )


def _payload(html: str) -> dict[str, object]:
    marker = f'<script type="application/json" id="{GOLD_DIAL_PAYLOAD_ID}">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


# ---------------------------------------------------------------------------
# embed_json_payload — hostile strings must round-trip, never break out
# ---------------------------------------------------------------------------


def test_embed_json_payload_neutralises_hostile_strings():
    hostile = {
        "close": "</script><img src=x onerror=alert(1)>",
        "mixed_case": "</ScRiPt >",
        "comment": "<!-- <script> -->",
        "separators": "line\u2028paragraph\u2029end",
        "amp": "Tom & Jerry &amp; friends",
        "quotes": 'he said "hi" and \'bye\'',
        "cdata": "<![CDATA[x]]>",
    }
    html = embed_json_payload("hostile-payload", hostile)

    assert html.startswith('<script type="application/json" id="hostile-payload">')
    assert html.endswith("</script>")
    body = html[len('<script type="application/json" id="hostile-payload">') : -len("</script>")]

    # nothing that can terminate the block or start markup survives literally
    assert "</script" not in body.lower()
    assert "<" not in body and ">" not in body and "&" not in body
    assert "\u2028" not in body and "\u2029" not in body

    # ...and it is still exactly the same data
    assert json.loads(body) == hostile


def test_embed_json_payload_rejects_a_non_token_id():
    for bad in ("", "has space", '"><script>', "1leading-digit"):
        try:
            embed_json_payload(bad, {})
        except ValueError:
            continue
        raise AssertionError(f"payload_id {bad!r} should have been rejected")


def test_embed_json_payload_is_deterministic_and_rejects_nan():
    first = embed_json_payload("p", {"b": 1, "a": 2})
    assert first == embed_json_payload("p", {"a": 2, "b": 1})
    try:
        embed_json_payload("p", {"x": float("nan")})
    except ValueError:
        return
    raise AssertionError("NaN must not be embedded — JSON.parse would reject it")


# ---------------------------------------------------------------------------
# headline cards + scenario cells
# ---------------------------------------------------------------------------


def test_headline_cards_render_the_persisted_spot_values_verbatim():
    html = _render()
    # Each formatted string is the artifact column, formatted — never recomputed.
    assert "$2,886/oz" in html  # spot_margin_usd_per_oz
    assert "64.8%" in html  # spot_margin_pct
    assert "13.7%" in html  # spot_aisc_margin_yield
    assert "6.72×" in html  # spot_ev_ebitda
    assert "10.88×" in html  # spot_forward_pe
    assert "0.03×" in html  # spot_leverage_stressed
    assert 'id="corporate-headline"' in html
    for metric in (
        "margin_usd_per_oz",
        "margin_pct",
        "aisc_margin_yield",
        "ev_ebitda",
        "forward_pe",
        "leverage_stressed",
    ):
        assert f'data-metric-card="{metric}"' in html


def test_every_scenario_cell_is_hidden_by_default_and_carries_its_metric():
    html = _render()
    for metric in (
        "forward_revenue_musd",
        "forward_ebitda_musd",
        "forward_net_income_musd",
        "forward_eps",
        "aisc_margin_est_musd",
        "margin_usd_per_oz",
        "margin_pct",
        "aisc_margin_yield",
        "ev_ebitda",
        "forward_pe",
        "leverage_stressed",
    ):
        cell = f'data-metric="{metric}" data-basis="scenario" hidden'
        assert cell in html, metric
    # the scenario column heads are hidden too — clean by default (Q43)
    assert 'data-scenario-head="1" hidden' in html
    # ...and no scenario cell ships pre-filled content
    assert 'data-basis="scenario" hidden></td>' in html


def test_line_metric_spot_cells_are_dial_evaluated_and_say_so():
    """The gold-response contract persists spot display values for the six ratio

    metrics only, so a LINE metric's spot cell is evaluated client-side at
    g = spot. It must never be blank and never a fake zero."""
    html = _render()
    assert 'data-metric="forward_revenue_musd" data-basis="spot"' in html
    assert "needs the gold dial (JavaScript)" in html
    assert ">$0m<" not in html


# ---------------------------------------------------------------------------
# failing-checks notice — persisted codes only, fixed at spot (D-4)
# ---------------------------------------------------------------------------


def test_failing_check_sentence_names_the_measured_value_and_your_threshold():
    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons="AISC_MARGIN_YIELD_FAIL",
            aisc_margin_yield=0.126,
            layer1_status="FAIL",
        )
    )
    assert "AISC margin yield 12.6% is below your 15.0% floor." in html
    assert "These screening checks fail at spot gold" in html
    assert "$4,452/oz as of 2026-08-11" in html
    assert "screening basis $4,452/oz" in html
    assert "do not move with the dial" in html


def test_multiple_failing_codes_each_get_their_own_sentence():
    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons="AISC_FAIL;LEVERAGE_NON_POSITIVE_EBITDA;RESERVE_LIFE_FAIL",
            aisc_usd_per_oz=2100.0,
            reserve_life_years=4.0,
            layer1_status="FAIL",
        )
    )
    assert "AISC $2,100/oz is above your $1,850/oz cap." in html
    assert "Reserve life 4.0 years is below your 6.0 years floor." in html
    assert (
        "Trailing EBITDA is not positive, so net debt / EBITDA (LTM) cannot be measured."
        in html
    )


def test_healthy_control_row_renders_no_failing_check_notice():
    """The control: an otherwise identical row with no persisted FAIL code."""
    html = _render(tool_b_row=_tool_b_row(layer1_fail_reasons=None))
    assert "These screening checks fail" not in html
    assert 'id="corporate-failing-checks"' not in html
    # ...and an empty string must not be treated as a code either
    assert (
        "These screening checks fail"
        not in _render(tool_b_row=_tool_b_row(layer1_fail_reasons=""))
    )


def test_nullable_failure_code_cells_render_as_no_codes():
    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons=pd.NA,
            fundamental_check_fail_codes=pd.NA,
        )
    )

    assert "These screening checks fail" not in html


def test_forward_pe_is_not_judged_without_a_persisted_code():
    """Serve must never compare forward P/E to a threshold on its own.

    A row that carries the VALUE but no failing code gets no sentence — the
    code is the only thing that may put a check on this page.
    """
    html = _render(
        tool_b_row=_tool_b_row(
            forward_pe=10.9,
            layer1_fail_reasons=None,
            fundamental_check_fail_codes=None,
            layer1_status="PASS",
        )
    )
    assert "Forward P/E 10.9" not in html
    assert "is above your" not in html
    assert 'id="corporate-failing-checks"' not in html
    # the banned composite strings never appear either
    assert "fundamental_check_summary" not in html
    assert "screening_verdict" not in html


# ---------------------------------------------------------------------------
# M3f: the fundamental-check codes (forward P/E is the only NEW check)
# ---------------------------------------------------------------------------


def _forward_pe_cutoff() -> str:
    """The configured cut-off, formatted exactly as the page formats a ratio."""
    from golden_vector.serve.ticker_page.corporate import format_metric

    return format_metric(
        float(
            _app_config().screening_params.verdict_thresholds.strong_candidate_forward_pe_max
        ),
        "ratio",
    )


def test_forward_pe_fail_code_names_the_value_and_the_configured_cutoff():
    html = _render(
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        )
    )
    assert f"Forward P/E 12.60× is above your {_forward_pe_cutoff()} cut-off." in html
    # ...and it sits under the same "at spot gold" header as its siblings.
    assert "These screening checks fail at spot gold" in html


def test_serve_reads_one_materialized_codes_column_and_never_the_official_one():
    """Source resolution happens ONCE, upstream (``materialize_tool_b_finance_source``
    via ``OPTIONAL_YAHOO_FINANCE_SOURCE_COLUMN_MAP``). Serve reads the single
    resolved column in either mode and never inspects an ``_official`` twin."""
    yahoo_data = _data(_gold_row(finance_source="yahoo"))
    # the materialized row: the resolved column carries the Yahoo codes
    html = _render(
        data=yahoo_data,
        finance_source="yahoo",
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes="FORWARD_PE_FAIL",
            fundamental_check_fail_codes_official="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        ),
    )
    assert f"Forward P/E 12.60× is above your {_forward_pe_cutoff()} cut-off." in html

    # The control: only the RAW ``_official`` column says it failed. Serve must
    # stay silent — reading that column would be the per-source picker again.
    quiet = _render(
        data=yahoo_data,
        finance_source="yahoo",
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes=None,
            fundamental_check_fail_codes_official="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        ),
    )
    assert 'id="corporate-failing-checks"' not in quiet
    assert "is above your" not in quiet

    # ...and serve does not name the raw variant at all.
    source = Path("golden_vector/serve/ticker_page/corporate.py").read_text(
        encoding="utf-8"
    )
    assert "fundamental_check_fail_codes_official" not in source


def test_healthy_control_with_null_fundamental_codes_gets_no_sentence():
    """An otherwise-identical row whose codes column is present but null."""
    html = _render(
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes=None,
            layer1_fail_reasons=None,
        )
    )
    assert 'id="corporate-failing-checks"' not in html
    assert "is above your" not in html


def test_absent_fundamental_codes_column_renders_without_a_sentence():
    """Pre-existing artifacts have no such column at all — that is not an error
    and must never be a guess."""
    row = _tool_b_row(forward_pe=12.6, layer1_fail_reasons=None)
    row.pop("fundamental_check_fail_codes", None)
    row.pop("fundamental_check_fail_codes_official", None)
    html = _render(tool_b_row=row)
    assert 'id="corporate-failing-checks"' not in html
    # the rest of the section still renders
    assert 'id="corporate-headline"' in html
    assert "Forward P/E" in html  # the card label, not a failing sentence
    assert "is above your" not in html


def test_non_positive_earnings_sentence_is_chosen_by_the_persisted_code():
    """A P/E built on non-positive earnings is not a multiple. WHICH failure it
    was is decided upstream and persisted as its own code — serve routes on the
    code and compares nothing, so the value in the row cannot change the words.
    """
    from golden_vector.screening.verdicts import FORWARD_PE_NON_POSITIVE_CODE

    expected = "Forward P/E is not meaningful here (forward earnings are not positive)."
    for value in (-4.2, 0.0):
        html = _render(
            tool_b_row=_tool_b_row(
                forward_pe=value,
                fundamental_check_fail_codes=FORWARD_PE_NON_POSITIVE_CODE,
                layer1_fail_reasons=None,
            )
        )
        assert expected in html, value
        assert "is above your" not in html, value

    # The control: the SAME non-positive value under the THRESHOLD code prints
    # the threshold sentence. Serve does not second-guess the producer.
    threshold_html = _render(
        tool_b_row=_tool_b_row(
            forward_pe=-4.2,
            fundamental_check_fail_codes="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        )
    )
    assert expected not in threshold_html
    assert f"is above your {_forward_pe_cutoff()} cut-off." in threshold_html


def test_a_fired_code_with_no_measured_value_says_so_instead_of_guessing():
    """The code fired but the column it names is absent. Serve states WHICH
    check failed and that the measurement is missing — it never invents a
    reason (the fabricated "earnings are not positive" claim) and never prints
    a comparison against a value it does not have."""
    missing = _tool_b_row(
        fundamental_check_fail_codes="FORWARD_PE_FAIL", layer1_fail_reasons=None
    )
    missing.pop("forward_pe", None)
    html = _render(tool_b_row=missing)
    assert (
        "Forward P/E failed this check, but the measured value is unavailable." in html
    )
    assert "forward earnings are not positive" not in html
    assert "is above your" not in html
    assert "n/a is above" not in html

    # the healthy control: the same code WITH the value prints the comparison
    present = _render(
        tool_b_row=_tool_b_row(
            forward_pe=12.6,
            fundamental_check_fail_codes="FORWARD_PE_FAIL",
            layer1_fail_reasons=None,
        )
    )
    assert "the measured value is unavailable" not in present


def test_fundamental_codes_never_double_report_a_layer1_check():
    """Both columns can name the same failure. It must be printed ONCE, by the
    layer-1 sentence that owns it."""
    html = _render(
        tool_b_row=_tool_b_row(
            layer1_fail_reasons="AISC_FAIL",
            aisc_usd_per_oz=2100.0,
            fundamental_check_fail_codes="AISC_FAIL;DATA_COMPLETE_FAIL;FORWARD_PE_FAIL",
            forward_pe=12.6,
            layer1_status="FAIL",
        )
    )
    assert html.count("AISC $2,100/oz is above your") == 1
    assert html.count("Forward P/E 12.60× is above your") == 1
    # DATA_COMPLETE_FAIL restates layer 1's precise MISSING_* codes -> not shown.
    assert "DATA_COMPLETE" not in html


def test_every_upstream_fundamental_check_is_accounted_for():
    """Guardrail: a NEW check added to ``screening/verdicts.py`` must either
    gain a sentence here or be explicitly recorded as a layer-1 duplicate —
    it can never be added upstream and then silently never render."""
    from golden_vector.screening.verdicts import (
        FORWARD_PE_NON_POSITIVE_CODE,
        FUNDAMENTAL_CHECK_ORDER,
        LAYER1_CHECK_LABELS,
    )
    from golden_vector.serve.ticker_page import corporate as C

    #: Codes whose CONCEPT layer 1 already reports, built from LAYER 1's OWN
    #: vocabulary (plus data-completeness, which layer 1 states per missing
    #: input). Building this from the render registry instead makes the check
    #: vacuous: that registry now holds fundamental-only codes too, so every
    #: code would satisfy it and a forgotten wiring would still pass.
    layer1_duplicates = {"DATA_COMPLETE_FAIL"} | {
        f"{key.upper()}_FAIL" for key in LAYER1_CHECK_LABELS
    }

    for key in FUNDAMENTAL_CHECK_ORDER:
        code = f"{key.upper()}_FAIL"
        assert (
            code in C._FUNDAMENTAL_ONLY_CODES or code in layer1_duplicates
        ), f"unhandled fundamental check code: {code}"

    # ...and the codes we DO consume really are new to this page.
    assert C._FUNDAMENTAL_ONLY_CODES == {
        "FORWARD_PE_FAIL",
        FORWARD_PE_NON_POSITIVE_CODE,
    }
    # every consumed code can actually produce a sentence
    for code in C._FUNDAMENTAL_ONLY_CODES:
        assert code in C._FAIL_SENTENCES or code in C._FAIL_STATEMENTS, code
    # ...and every threshold sentence can degrade honestly when its column is gone
    assert set(C._CHECK_NAMES) == set(C._FAIL_SENTENCES)


# ---------------------------------------------------------------------------
# groups: leverage naming, resilience, data quality
# ---------------------------------------------------------------------------


def test_trailing_and_stressed_leverage_are_two_distinct_labelled_rows():
    html = _render()
    assert "Stressed forward leverage" in html
    assert "Net debt / EBITDA (LTM)" in html
    assert "last twelve months (LTM)" in html
    # the trailing value comes from Tool B, the stressed one from the artifact
    assert "0.04×" in html  # tool_b leverage 0.042
    assert "0.03×" in html  # spot_leverage_stressed 0.027003


def test_ev_ebitda_and_forward_pe_help_text_explain_the_inversion():
    html = _render()
    assert "RISES as gold FALLS" in html
    assert "earnings shrink" in html or "forward earnings shrink" in html
    assert "more expensive, not cheaper" in html.replace("MORE", "more")
    # both metrics carry an explainer button
    assert 'data-help-title="EV / EBITDA (forward)"' in html
    assert 'data-help-title="Forward P/E"' in html


def test_resilience_is_disabled_in_yahoo_mode_with_the_exact_reason():
    html = _render(
        data=_data(_gold_row(finance_source="yahoo")),
        finance_source="yahoo",
    )
    assert YAHOO_RESILIENCE_REASON == "resilience is computed on Our View inputs"
    assert (
        "Resilience is disabled in Yahoo Fundamentals mode: "
        "resilience is computed on Our View inputs." in html
    )
    # the Our-View numbers must not leak into Yahoo mode
    assert "Interest-cover gold" not in html
    assert "Survival distance" not in html


def test_resilience_renders_persisted_tool_d_values_in_our_view_mode():
    html = _render()
    assert "Operating breakeven gold" in html
    assert "$1,566/oz" in html
    assert "$1,251/oz" in html  # interest cover
    assert "71.9%" in html  # survival distance (a fraction column)
    assert "13.8%" in html  # EBITDA fragility
    assert "Resilience data status" in html


def test_data_quality_group_labels_every_basis():
    html = _render()
    assert "Data quality and sources" in html
    assert "Screening gold basis" in html
    assert "Margin cost basis" in html
    assert "Gold response artifact" in html
    assert "Our View mining assumption" in html


# ---------------------------------------------------------------------------
# degraded states
# ---------------------------------------------------------------------------


def test_degraded_gold_response_row_disables_the_dial_with_its_persisted_reason():
    reason = "linearity residual 41.2 exceeded tolerance at $6,000"
    data = _data(
        _gold_row(gold_response_status="DEGRADED_NONLINEAR", gold_response_reason=reason)
    )
    html = _render(data=data)
    assert "The gold dial is disabled for NEM" in html
    assert reason in html
    # the persisted spot values that DO exist are still shown
    assert "$2,886/oz" in html
    payload = _payload(html)
    assert payload["enabled"] is False
    assert payload["disabled_reason"] == reason
    assert payload["gold_response_status"] == "DEGRADED_NONLINEAR"
    assert payload["gold_response_reason"] == reason

    control = render_gold_dial_control(
        data, ticker="NEM", finance_source="our", app_config=_app_config()
    )
    assert "disabled>" in control
    assert reason in control


def test_missing_gold_response_row_is_reported_not_faked():
    data = _data(_gold_row(ticker="AEM"))
    html = _render(data=data)
    assert "The gold dial is disabled for NEM" in html
    assert "no gold-response row was published" in html
    assert "n/a" in html  # unavailable cells say so
    assert ">$0m<" not in html and ">0.00×<" not in html


def test_pending_artifact_renders_one_honest_degraded_notice():
    data = _data(
        artifact_status="PENDING_FIRST_PUBLISH",
        artifact_reason="the ticker-page stage has not published yet",
    )
    html = _render(data=data)
    assert "PENDING_FIRST_PUBLISH" in html
    assert "the ticker-page stage has not published yet" in html
    assert "nothing is estimated to fill the gap" in html
    assert _payload(html)["enabled"] is False


# ---------------------------------------------------------------------------
# dial control + payload
# ---------------------------------------------------------------------------


def test_dial_control_takes_its_range_from_config_and_defaults_to_spot():
    app_config = _app_config()
    control = render_gold_dial_control(
        _data(), ticker="NEM", finance_source="our", app_config=app_config
    )
    dial = app_config.ticker_page.dial
    assert f'min="{dial.min_gold_usd:g}"' in control
    assert f'max="{dial.max_gold_usd:g}"' in control
    assert f'step="{dial.step_usd:g}"' in control
    assert 'value="4452"' in control  # the artifact's spot, not a config scenario
    assert "$4,000" not in control  # never Tool B's configured default scenario
    assert '<output class="gold-dial-output"' in control
    assert 'id="gold-dial-reset"' in control
    assert 'aria-live="polite"' in control
    assert "spot $4,452.00 as of 2026-08-11" in control


def test_slider_value_is_step_aligned_while_the_payload_keeps_exact_spot():
    """A range control snaps ``value`` onto ``min + k*step`` before any script

    runs, so emitting the exact fractional spot ships a position the browser
    rewrites — and a client baseline that starts life in a false scenario
    (plan §4.3, D9). The EXACT spot still owns evaluation, display and
    provenance; only the control's own position is aligned."""
    data = _data(_gold_row(spot_gold_usd=4477.4))
    control = render_gold_dial_control(
        data, ticker="NEM", finance_source="our", app_config=_app_config()
    )

    assert 'step="1"' in control
    assert 'value="4477"' in control  # the position the control can actually hold
    assert 'value="4477.4"' not in control
    # ...while every human-readable basis keeps the true price, cents and all
    assert "spot $4,477.40 as of 2026-08-11" in control
    assert 'aria-valuetext="$4,477.40 per ounce, spot"' in control
    assert ">$4,477.40</output>" in control
    # Nothing to reset FROM at rest: rendered, disabled, out of the tab order.
    assert 'id="gold-dial-reset" disabled>' in control

    payload = _payload(_render(data=data))
    assert payload["spot_gold_usd"] == 4477.4


def test_a_spot_outside_the_configured_range_is_emitted_at_the_bound():
    """The browser clamps the position anyway — emitting the bound keeps the

    rendered control and the browser's own value in agreement. The payload and
    the visible basis text still carry the true, unclamped spot."""
    dial = _app_config().ticker_page.dial
    for spot, expected in ((7000.0, dial.max_gold_usd), (1000.0, dial.min_gold_usd)):
        data = _data(_gold_row(spot_gold_usd=spot))
        control = render_gold_dial_control(
            data, ticker="NEM", finance_source="our", app_config=_app_config()
        )
        assert f'value="{expected:g}"' in control, spot
        assert f"spot {format_metric(spot, 'usd2')} as of" in control, spot
        assert _payload(_render(data=data))["spot_gold_usd"] == spot


def test_headline_cards_carry_one_spot_value_and_one_hidden_scenario_slot():
    """The card contract (§4.4): the spot value gold-dial.js hides while a

    scenario is active, plus the empty slot it writes into — never two
    unlabelled numbers stacked in one card."""
    html = _render()
    for metric in (
        "margin_usd_per_oz",
        "margin_pct",
        "aisc_margin_yield",
        "ev_ebitda",
        "forward_pe",
        "leverage_stressed",
    ):
        assert f'data-metric="{metric}" data-basis="scenario" hidden></p>' in html, metric
    assert html.count('<p class="metric-card-value spot-cell" data-headline-spot="1">') == 6
    # the marker exists ONLY on the cards — expanded tables keep both columns
    assert html.count("data-headline-spot") == 6


def test_dial_payload_carries_the_artifact_row_and_nothing_computed():
    frame = pd.DataFrame([_gold_row()])
    html = _render(data=_data())
    payload = _payload(html)

    row = frame.iloc[0]
    for metric in GOLD_RESPONSE_LINE_METRICS:
        assert payload["lines"][metric]["slope"] == row[f"line_slope_{metric}"]
        assert payload["lines"][metric]["intercept"] == row[f"line_intercept_{metric}"]
    for column in GOLD_RESPONSE_CONSTANT_COLUMNS:
        assert payload["constants"][column] == row[column]
    assert payload["spot_gold_usd"] == 4452.0
    assert payload["spot_gold_date"] == "2026-08-11"
    assert payload["margin_basis"] == "aisc"
    assert payload["enabled"] is True

    assert set(payload["lines"]) == set(GOLD_RESPONSE_LINE_METRICS)
    assert set(payload["constants"]) == set(GOLD_RESPONSE_CONSTANT_COLUMNS)
    assert payload["gold_response_status"] == "OK"
    assert payload["gold_response_reason"] is None
    assert set(payload) == {
        "ticker",
        "finance_source",
        "gold_response_status",
        "gold_response_reason",
        "enabled",
        "disabled_reason",
        "spot_gold_usd",
        "spot_gold_date",
        "margin_basis",
        "lines",
        "constants",
        "spot_display",
        "formats",
    }


# ---------------------------------------------------------------------------
# backend/JS parity: the formula contract the real-JS gate verifies at M4
# ---------------------------------------------------------------------------

_PROBE_GOLDS = (2000.0, 4000.0, 6000.0)


def _mirror_line(payload: dict, metric: str, gold: float):
    line = payload["lines"].get(metric)
    if not line or line["slope"] is None or line["intercept"] is None:
        return None, "no published line here"
    return line["slope"] * gold + line["intercept"], None


def _mirror_ratio(numerator, denominator, guard_reason):
    if numerator is None or denominator is None:
        return None, "input unavailable here"
    if not denominator > 0:
        return None, guard_reason
    return numerator / denominator, None


def mirror_evaluate(payload: dict, metric: str, gold: float):
    """Python mirror of gold-dial.js ``evaluate`` — same guards, same order.

    The guards are the ones in ``screening/layer1.py`` (market cap > 0) and
    ``screening/layer2.py`` (forward EBITDA > 0, forward EPS > 0).
    """
    if metric in payload["lines"]:
        return _mirror_line(payload, metric, gold)
    constants = payload["constants"]
    if metric == "margin_usd_per_oz":
        column = {"aisc": "aisc_usd_per_oz", "cash_cost": "cash_cost_usd_per_oz"}.get(
            payload["margin_basis"]
        )
        if column is None:
            return None, "margin cost basis unavailable"
        cost = constants.get(column)
        if cost is None:
            return None, "cost basis unavailable here"
        return gold - cost, None
    if metric == "margin_pct":
        margin, reason = mirror_evaluate(payload, "margin_usd_per_oz", gold)
        if margin is None:
            return None, reason
        return _mirror_ratio(margin, gold, "gold price ≤ 0 here")
    if metric == "aisc_margin_yield":
        value, reason = mirror_evaluate(payload, "aisc_margin_est_musd", gold)
        if value is None:
            return None, reason
        return _mirror_ratio(value, constants.get("market_cap_musd"), "market cap ≤ 0 here")
    if metric == "ev_ebitda":
        ebitda, reason = mirror_evaluate(payload, "forward_ebitda_musd", gold)
        if ebitda is None:
            return None, reason
        return _mirror_ratio(
            constants.get("enterprise_value_musd"), ebitda, "EBITDA ≤ 0 here"
        )
    if metric == "forward_pe":
        eps, reason = mirror_evaluate(payload, "forward_eps", gold)
        if eps is None:
            return None, reason
        return _mirror_ratio(constants.get("share_price_usd"), eps, "EPS ≤ 0 here")
    if metric == "leverage_stressed":
        ebitda, reason = mirror_evaluate(payload, "forward_ebitda_musd", gold)
        if ebitda is None:
            return None, reason
        return _mirror_ratio(constants.get("net_debt_musd"), ebitda, "EBITDA ≤ 0 here")
    raise AssertionError(f"unknown metric {metric}")


def _parity_expectations(payload: dict) -> dict:
    from golden_vector.serve.ticker_page.corporate import METRIC_FORMATS, format_metric

    out: dict[str, dict[str, dict[str, object]]] = {}
    for gold in _PROBE_GOLDS:
        per_gold: dict[str, dict[str, object]] = {}
        for metric, unit in METRIC_FORMATS.items():
            value, reason = mirror_evaluate(payload, metric, gold)
            per_gold[metric] = {
                "value": None if value is None else round(value, 9),
                "reason": reason,
                "formatted": reason if value is None else format_metric(value, unit),
            }
        out[f"{gold:.0f}"] = per_gold
    return out


def _stressed_gold_row() -> dict[str, object]:
    """A high-cost miner whose forward EBITDA and EPS go NEGATIVE at $2,000 and

    recover by $6,000 — the exclusion subject plus its own healthy control."""
    return _gold_row(
        ticker="NEM",
        line_slope_forward_ebitda_musd=1.0,
        line_intercept_forward_ebitda_musd=-5000.0,
        line_slope_forward_eps=0.001,
        line_intercept_forward_eps=-3.0,
    )


def _parity_cases() -> dict[str, dict]:
    cases: dict[str, dict] = {}
    for name, row in (("healthy", _gold_row()), ("stressed", _stressed_gold_row())):
        payload = _payload(_render(data=_data(row)))
        cases[name] = {"payload": payload, "expected": _parity_expectations(payload)}
    return cases


def test_gold_dial_backend_parity_fixture_pins_the_formula_contract():
    """The formula contract the real-browser M4 gate re-verifies against the

    actual JS. If gold-dial.js and this mirror ever disagree, the fixture is
    the record of which one changed."""
    cases = _parity_cases()

    if os.environ.get("GV_WRITE_PARITY_FIXTURE") == "1":
        PARITY_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        PARITY_FIXTURE.write_text(
            json.dumps({"cases": cases}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    assert PARITY_FIXTURE.exists(), (
        "tests/fixtures/gold_dial_parity.json is missing — regenerate deliberately "
        "with GV_WRITE_PARITY_FIXTURE=1"
    )
    stored = json.loads(PARITY_FIXTURE.read_text(encoding="utf-8"))
    assert stored["cases"] == cases, (
        "the embedded payload or the client formula chain drifted from the pinned "
        "backend/JS parity fixture"
    )


def test_ratio_guards_mirror_layer1_and_layer2_exactly():
    """Exclusion subject + healthy control, in the same fixture.

    Guards are ``forward EBITDA > 0`` (EV/EBITDA, stressed leverage, both from
    ``screening/layer2.py`` and Tool D), ``forward EPS > 0`` (forward P/E,
    ``layer2.py``) and ``market cap > 0`` (AISC margin yield, ``layer1.py``)."""
    payload = _payload(_render(data=_data(_stressed_gold_row())))

    for metric, reason in (
        ("ev_ebitda", "EBITDA ≤ 0 here"),
        ("leverage_stressed", "EBITDA ≤ 0 here"),
        ("forward_pe", "EPS ≤ 0 here"),
    ):
        value, got = mirror_evaluate(payload, metric, 2000.0)
        assert value is None and got == reason, metric
        # the healthy control: the SAME miner at a gold price that clears the guard
        healthy_value, healthy_reason = mirror_evaluate(payload, metric, 6000.0)
        assert healthy_value is not None and healthy_reason is None, metric

    # market cap ≤ 0 excludes the yield rather than dividing by it
    zero_cap = _payload(_render(data=_data(_gold_row(market_cap_musd=0.0))))
    value, reason = mirror_evaluate(zero_cap, "aisc_margin_yield", 4452.0)
    assert value is None and reason == "market cap ≤ 0 here"


def test_spot_evaluation_reproduces_the_persisted_spot_display_values():
    """The client formula must agree with the backend at spot, or the two

    columns on screen would disagree about the same gold price."""
    payload = _payload(_render())
    spot = payload["spot_gold_usd"]
    for metric, persisted in payload["spot_display"].items():
        value, reason = mirror_evaluate(payload, metric, spot)
        assert value is not None, (metric, reason)
        assert abs(value - persisted) <= max(1e-4, abs(persisted) * 1e-4), metric
