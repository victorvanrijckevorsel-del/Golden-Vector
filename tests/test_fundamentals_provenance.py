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
                    "value_origin": "yahoo_reported_component",
                    "calculation_formula": None,
                    "components_json": (
                        '[{"component":"interest_expense","normalized_value":25,'
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
    assert "Interest expense: taken directly from one Yahoo line item" in text
