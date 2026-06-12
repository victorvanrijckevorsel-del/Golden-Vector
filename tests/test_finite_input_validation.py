"""Every user-input numeric boundary rejects NaN/inf (expanded-review N-H6 + H2).

`nan <= 0` is False, so positivity checks silently passed non-finite values:
inf flowed into EV/EBITDA math as a "valid" number, and NaN was converted to
NULL by SQLite — typing "nan" into a form field silently wiped the stored
value while the UI said "saved".
"""

from __future__ import annotations

import pytest

from golden_vector.common.numeric import require_finite
from golden_vector.hedge.holdings import _optional_positive_float
from golden_vector.portfolio.manual_store import PortfolioValidationError, _positive_float
from golden_vector.screening.manual_store import _normalize_numeric_value
from golden_vector.serve.format_helpers import _coerce_form_numeric

NON_FINITE_TEXTS = ["nan", "inf", "Infinity", "1e400", "-inf"]


def test_require_finite_shared_validator() -> None:
    assert require_finite(1.5, field="x") == 1.5
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite"):
            require_finite(bad, field="x")


def test_screening_store_rejects_non_finite() -> None:
    assert _normalize_numeric_value("ebitda_musd", "12.5") == 12.5
    for bad in NON_FINITE_TEXTS:
        with pytest.raises(ValueError, match="finite"):
            _normalize_numeric_value("ebitda_musd", bad)


def test_portfolio_store_rejects_non_finite() -> None:
    assert _positive_float("10", field="shares") == 10.0
    for bad in NON_FINITE_TEXTS:
        with pytest.raises(PortfolioValidationError):
            _positive_float(bad, field="shares")


def test_workspace_form_coercer_rejects_non_finite() -> None:
    assert _coerce_form_numeric("3.5") == 3.5
    assert _coerce_form_numeric("") is None
    for bad in NON_FINITE_TEXTS:
        with pytest.raises(ValueError):
            _coerce_form_numeric(bad)


def test_holdings_loader_rejects_non_finite() -> None:
    assert _optional_positive_float("5", field="shares", index=1) == 5.0
    assert _optional_positive_float(None, field="shares", index=1) is None
    # YAML resolves .nan/.inf to real floats, so values arrive as floats.
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite"):
            _optional_positive_float(bad, field="shares", index=1)
