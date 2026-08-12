from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.fundamentals.artifacts import normalize_fetched_fundamentals_frame
from golden_vector.serve.fundamentals_provenance import (
    fundamentals_provenance_lookup,
    fundamentals_statement_periods,
    provenance_text_for_fields,
)


def test_fundamentals_provenance_explains_calculated_and_reported_fields():
    frame = normalize_fetched_fundamentals_frame(
        pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "field_name": "net_debt_musd",
                    "value": 500.0,
                    "source": "YAHOO",
                    "source_run_id": "run",
                    "fetched_at_utc": "2026-06-10T12:00:00Z",
                    "statement_period": "FY2025",
                    "period_end": date(2025, 12, 31),
                    "period_type": "ANNUAL",
                    "statement_currency": "USD",
                    "statement_scale": "absolute_to_usd_millions",
                    "value_status": "OK",
                    "value_origin": "calculated_from_yahoo_fields",
                    "calculation_formula": "total_debt - cash",
                    "components_json": (
                        '[{"component":"total_debt","normalized_value":700,'
                        '"yahoo_line_item":"Total Debt","status":"OK"},'
                        '{"component":"cash","normalized_value":200,'
                        '"contribution_musd":-200,'
                        '"yahoo_line_item":"Cash And Cash Equivalents","status":"OK"}]'
                    ),
                },
                {
                    "ticker": "AEM",
                    "field_name": "interest_expense_musd",
                    "value": 25.0,
                    "source": "YAHOO",
                    "source_run_id": "run",
                    "fetched_at_utc": "2026-06-10T12:00:00Z",
                    "statement_period": "FY2025",
                    "period_end": date(2025, 12, 31),
                    "period_type": "ANNUAL",
                    "statement_currency": "USD",
                    "statement_scale": "absolute_to_usd_millions",
                    "value_status": "OK",
                    "value_origin": "sign_normalized_yahoo_component",
                    "calculation_formula": None,
                    "components_json": (
                        '[{"component":"interest_expense","normalized_value":25,'
                        '"normalization":"absolute_value",'
                        '"yahoo_line_item":"Interest Expense","status":"OK"}]'
                    ),
                },
            ]
        ),
        source_run_id="run",
    )

    lookup = fundamentals_provenance_lookup(frame)
    text = provenance_text_for_fields(
        "AEM",
        ["net_debt_musd", "interest_expense_musd"],
        lookup,
    )

    assert "Net debt: calculated from multiple Yahoo line items" in text
    assert "Formula: total_debt - cash" in text
    assert "total debt (= 700 MUSD, Yahoo line: Total Debt)" in text
    assert "cash (= 200 MUSD, subtracts 200 MUSD in formula" in text
    assert "Interest expense: taken from one Yahoo line item with the sign normalized" in text
    assert "sign normalized to positive expense" in text


def test_fundamentals_provenance_keeps_zero_component_values_and_omits_manual_tax():
    frame = normalize_fetched_fundamentals_frame(
        pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "field_name": "net_debt_musd",
                    "value": 700.0,
                    "source": "YAHOO",
                    "source_run_id": "run",
                    "fetched_at_utc": "2026-06-10T12:00:00Z",
                    "statement_period": "FY2025",
                    "period_end": date(2025, 12, 31),
                    "period_type": "ANNUAL",
                    "statement_currency": "USD",
                    "statement_scale": "absolute_to_usd_millions",
                    "value_status": "MISSING",
                    "value_origin": "cash_missing_assumed_zero",
                    "calculation_formula": "Net Debt = Total Debt - Cash",
                    "components_json": (
                        '[{"component":"cash","normalized_value":0.0,'
                        '"contribution_musd":0.0,"formula_sign":-1,'
                        '"status":"MISSING_ASSUMED_ZERO"}]'
                    ),
                },
                {
                    "ticker": "AEM",
                    "field_name": "tax_rate",
                    "value": None,
                    "source": "YAHOO",
                    "source_run_id": "run",
                    "fetched_at_utc": "2026-06-10T12:00:00Z",
                    "statement_period": "FY2025",
                    "period_end": date(2025, 12, 31),
                    "period_type": "ANNUAL",
                    "statement_currency": "USD",
                    "statement_scale": "not_applicable",
                    "value_status": "MISSING",
                    "value_origin": "missing_yahoo_inputs",
                    "calculation_formula": None,
                    "components_json": None,
                },
            ]
        ),
        source_run_id="run",
    )

    lookup = fundamentals_provenance_lookup(frame)
    text = provenance_text_for_fields("AEM", ["net_debt_musd"], lookup)

    assert (
        "cash (= 0.0 MUSD, subtracts 0.0 MUSD in formula, "
        "status: MISSING_ASSUMED_ZERO)"
    ) in text
    assert ("AEM", "tax_rate") in lookup
    assert "Tax rate" not in provenance_text_for_fields(
        "AEM",
        ["net_debt_musd", "ebitda_ltm_musd", "da_musd", "interest_expense_musd"],
        lookup,
    )


def _fundamentals_frame(*rows: dict) -> pd.DataFrame:
    """Minimal well-formed provenance rows through the real normalizer."""

    return normalize_fetched_fundamentals_frame(
        pd.DataFrame(
            [
                {
                    "value": 1.0,
                    "source": "YAHOO",
                    "source_run_id": "run",
                    "period_type": "ANNUAL",
                    "statement_currency": "USD",
                    "statement_scale": "absolute_to_usd_millions",
                    "value_status": "OK",
                    "value_origin": "yahoo_reported_component",
                    "calculation_formula": None,
                    "components_json": None,
                    **row,
                }
                for row in rows
            ]
        ),
        source_run_id="run",
    )


def test_statement_periods_report_the_same_facts_the_tooltip_prints():
    """The data-quality table needs the statement period as a VALUE, and it must
    be the same persisted field the "Period end: ..." tooltip renders — read
    from the same rows, never derived from a run date."""

    frame = _fundamentals_frame(
        {
            "ticker": "aem",
            "field_name": "net_debt_musd",
            "fetched_at_utc": "2026-06-10T12:00:00Z",
            "period_end": date(2025, 12, 31),
        },
        {
            "ticker": "AEM",
            "field_name": "ebitda_ltm_musd",
            "fetched_at_utc": "2026-06-10T12:00:00Z",
            "period_end": date(2025, 12, 31),
        },
    )

    periods = fundamentals_statement_periods(frame)

    # One ticker key (case/space normalized), and the repeated facts collapse.
    assert set(periods) == {"AEM"}
    assert periods["AEM"].period_end_text == "2025-12-31"
    assert periods["AEM"].fetched_at_text == "2026-06-10T12:00:00Z"
    # ...and the tooltip's own text still states the same period.
    assert "Period end: 2025-12-31" in fundamentals_provenance_lookup(frame)[
        ("AEM", "net_debt_musd")
    ]


def test_statement_periods_keep_every_distinct_value_when_fields_disagree():
    """Two fields from different statements is a real state. Picking one would
    label the whole table with a period half the numbers do not come from."""

    frame = _fundamentals_frame(
        {
            "ticker": "AEM",
            "field_name": "net_debt_musd",
            "fetched_at_utc": "2026-06-10T12:00:00Z",
            "period_end": date(2025, 12, 31),
        },
        {
            "ticker": "AEM",
            "field_name": "ebitda_ltm_musd",
            "fetched_at_utc": "2026-06-10T12:00:00Z",
            "period_end": date(2025, 9, 30),
        },
    )

    assert fundamentals_statement_periods(frame)["AEM"].period_ends == (
        "2025-12-31",
        "2025-09-30",
    )


def test_statement_periods_are_empty_when_nothing_was_published():
    assert fundamentals_statement_periods(pd.DataFrame()) == {}
    frame = _fundamentals_frame(
        {
            "ticker": "AEM",
            "field_name": "net_debt_musd",
            "fetched_at_utc": None,
            "period_end": None,
        }
    )
    assert fundamentals_statement_periods(frame) == {}
