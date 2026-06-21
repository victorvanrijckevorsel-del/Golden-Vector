from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.fundamentals.artifacts import normalize_fetched_fundamentals_frame
from golden_vector.serve.fundamentals_provenance import (
    fundamentals_provenance_lookup,
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
