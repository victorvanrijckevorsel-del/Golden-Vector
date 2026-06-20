"""Map durable raw Yahoo statements into canonical official fundamentals."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

import pandas as pd

from golden_vector.common.numeric import optional_float
from golden_vector.contracts.fundamentals import (
    FETCHED_FUNDAMENTALS_COLUMNS,
    FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
)
from golden_vector.fundamentals.artifacts import normalize_fetched_fundamentals_frame
from golden_vector.fundamentals.raw_store import RAW_FETCH_STATUS_PASS, validate_raw_fundamentals_frame
from golden_vector.normalize.calendar import merge_fx_asof
from golden_vector.screening.manual_store import FINANCIAL_DUAL_SOURCE_FIELDS

TOTAL_DEBT_ALIASES = (
    "Total Debt",
    "TotalDebt",
)
LONG_TERM_DEBT_ALIASES = (
    "Long Term Debt",
    "Long Term Debt And Capital Lease Obligation",
)
CURRENT_DEBT_ALIASES = (
    "Current Debt",
    "Current Debt And Capital Lease Obligation",
)
CASH_ALIASES = (
    "Cash And Cash Equivalents",
    "Cash Cash Equivalents And Short Term Investments",
)
OPERATING_INCOME_ALIASES = (
    "Operating Income",
    "EBIT",
)
DA_ALIASES = (
    "Depreciation And Amortization",
    "Depreciation Amortization Depletion",
    "Reconciled Depreciation",
)
INTEREST_EXPENSE_ALIASES = (
    "Interest Expense",
    "Interest Expense Non Operating",
)
REPORTED_EBITDA_ALIASES = (
    "EBITDA",
    "Normalized EBITDA",
)


@dataclass(frozen=True)
class _MappedField:
    field_name: str
    value: float | None
    value_status: str
    period_end: date | None
    period_type: str
    statement_currency: str
    statement_scale: str
    value_origin: str
    calculation_formula: str | None = None
    components: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class _MatchedValue:
    value: float
    line_item_original: str


@dataclass(frozen=True)
class _ConvertedValue:
    value_musd: float | None
    value_status: str


def map_raw_fundamentals_to_official(
    raw_frame: pd.DataFrame,
    *,
    fx_histories: dict[str, pd.DataFrame] | None = None,
    source_run_id: str,
    max_statement_age_days: int,
    ebitda_reconciliation_max_pct: float,
) -> pd.DataFrame:
    """Map persisted raw Yahoo statements into official fundamental rows."""

    raw = validate_raw_fundamentals_frame(raw_frame)
    fx_histories = {str(key).upper(): value for key, value in (fx_histories or {}).items()}
    rows: list[dict[str, object]] = []
    for ticker in _raw_tickers(raw):
        ticker_raw = raw[raw["ticker"].eq(ticker)].copy()
        fetched_at_utc = _first_string(ticker_raw, "fetched_at_utc")
        for mapped in _map_ticker(
            ticker_raw,
            max_statement_age_days=max_statement_age_days,
            ebitda_reconciliation_max_pct=ebitda_reconciliation_max_pct,
            fx_histories=fx_histories,
        ):
            rows.append(
                {
                    "schema_version": FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
                    "ticker": ticker,
                    "field_name": mapped.field_name,
                    "value": mapped.value,
                    "source": "YAHOO",
                    "source_run_id": source_run_id,
                    "fetched_at_utc": fetched_at_utc,
                    "statement_period": _statement_period(mapped.period_end),
                    "period_end": mapped.period_end,
                    "period_type": mapped.period_type,
                    "statement_currency": mapped.statement_currency,
                    "statement_scale": mapped.statement_scale,
                    "value_status": mapped.value_status,
                    "value_origin": mapped.value_origin,
                    "calculation_formula": mapped.calculation_formula,
                    "components_json": _components_json(mapped.components),
                }
            )
    frame = pd.DataFrame(rows, columns=FETCHED_FUNDAMENTALS_COLUMNS)
    return normalize_fetched_fundamentals_frame(frame, source_run_id=source_run_id)


def _map_ticker(
    raw: pd.DataFrame,
    *,
    max_statement_age_days: int,
    ebitda_reconciliation_max_pct: float,
    fx_histories: dict[str, pd.DataFrame],
) -> list[_MappedField]:
    balance = _latest_statement_rows(raw, "balance_sheet")
    income = _latest_statement_rows(raw, "income_stmt")
    cashflow = _latest_statement_rows(raw, "cashflow")
    fields = {
        "net_debt_musd": _map_net_debt(
            balance,
            fetched_at_utc=_first_string(raw, "fetched_at_utc"),
            max_statement_age_days=max_statement_age_days,
            fx_histories=fx_histories,
        ),
        "ebitda_ltm_musd": _map_ebitda(
            income,
            cashflow,
            fetched_at_utc=_first_string(raw, "fetched_at_utc"),
            max_statement_age_days=max_statement_age_days,
            ebitda_reconciliation_max_pct=ebitda_reconciliation_max_pct,
            fx_histories=fx_histories,
        ),
        "da_musd": _map_da(
            income,
            cashflow,
            fetched_at_utc=_first_string(raw, "fetched_at_utc"),
            max_statement_age_days=max_statement_age_days,
            fx_histories=fx_histories,
        ),
        "interest_expense_musd": _map_interest(
            income,
            fetched_at_utc=_first_string(raw, "fetched_at_utc"),
            max_statement_age_days=max_statement_age_days,
            fx_histories=fx_histories,
        ),
        "tax_rate": _missing_field("tax_rate", period_type="ANNUAL"),
    }
    return [fields[field_name] for field_name in sorted(FINANCIAL_DUAL_SOURCE_FIELDS)]


def _map_net_debt(
    balance: pd.DataFrame,
    *,
    fetched_at_utc: str,
    max_statement_age_days: int,
    fx_histories: dict[str, pd.DataFrame],
) -> _MappedField:
    period_end = _period_end(balance)
    currency = _statement_currency(balance)
    total_debt = _find_value(balance, TOTAL_DEBT_ALIASES)
    components: list[dict[str, object]] = []
    if total_debt is None:
        long_debt = _find_value(balance, LONG_TERM_DEBT_ALIASES)
        current_debt = _find_value(balance, CURRENT_DEBT_ALIASES)
        if long_debt is None or current_debt is None:
            return _missing_field(
                "net_debt_musd",
                period_end=period_end,
                currency=currency,
                calculation_formula="Net Debt = Total Debt - Cash",
                components=tuple(
                    component
                    for component in (
                        _component(
                            component="long_term_debt",
                            matched=long_debt,
                            currency=currency,
                            period_end=period_end,
                            fx_histories=fx_histories,
                        )
                        if long_debt is not None
                        else None,
                        _component(
                            component="current_debt",
                            matched=current_debt,
                            currency=currency,
                            period_end=period_end,
                            fx_histories=fx_histories,
                        )
                        if current_debt is not None
                        else None,
                    )
                    if component is not None
                ),
            )
        components.extend(
            [
                _component(
                    component="long_term_debt",
                    matched=long_debt,
                    currency=currency,
                    period_end=period_end,
                    fx_histories=fx_histories,
                ),
                _component(
                    component="current_debt",
                    matched=current_debt,
                    currency=currency,
                    period_end=period_end,
                    fx_histories=fx_histories,
                ),
            ]
        )
        total_debt_value = long_debt.value + current_debt.value
        formula = "Net Debt = Long-term debt + Current debt - Cash"
    else:
        components.append(
            _component(
                component="total_debt",
                matched=total_debt,
                currency=currency,
                period_end=period_end,
                fx_histories=fx_histories,
            )
        )
        total_debt_value = total_debt.value
        formula = "Net Debt = Total Debt - Cash"
    cash = _find_value(balance, CASH_ALIASES)
    cash_missing = cash is None
    if cash_missing:
        cash_value = 0.0
        components.append(
            _assumed_zero_component(
                component="cash",
                status="MISSING_ASSUMED_ZERO",
                currency=currency,
            )
        )
    else:
        cash_value = cash.value
        components.append(
            _component(
                component="cash",
                matched=cash,
                currency=currency,
                period_end=period_end,
                fx_histories=fx_histories,
                sign=-1,
            )
        )
    converted = _convert_money(
        total_debt_value - cash_value,
        currency=currency,
        period_end=period_end,
        fx_histories=fx_histories,
    )
    status = _with_staleness(
        converted.value_status,
        period_end=period_end,
        fetched_at_utc=fetched_at_utc,
        max_statement_age_days=max_statement_age_days,
    )
    if cash_missing and status == "OK":
        status = "MISSING"
    return _MappedField(
        field_name="net_debt_musd",
        value=converted.value_musd,
        value_status=status,
        period_end=period_end,
        period_type="ANNUAL",
        statement_currency=currency,
        statement_scale=(
            "absolute_to_usd_millions_cash_missing_assumed_zero"
            if cash_missing
            else "absolute_to_usd_millions"
        ),
        value_origin=(
            "cash_missing_assumed_zero"
            if cash_missing
            else "calculated_from_yahoo_fields"
        ),
        calculation_formula=formula,
        components=tuple(components),
    )


def _map_ebitda(
    income: pd.DataFrame,
    cashflow: pd.DataFrame,
    *,
    fetched_at_utc: str,
    max_statement_age_days: int,
    ebitda_reconciliation_max_pct: float,
    fx_histories: dict[str, pd.DataFrame],
) -> _MappedField:
    income_period_end = _period_end(income)
    cashflow_period_end = _period_end(cashflow)
    period_end = income_period_end or cashflow_period_end
    currency = _statement_currency(income) or _statement_currency(cashflow)
    if _periods_conflict(income_period_end, cashflow_period_end):
        return _missing_field("ebitda_ltm_musd", period_end=period_end, currency=currency)
    operating_income = _find_value(income, OPERATING_INCOME_ALIASES)
    da = _find_value(cashflow, DA_ALIASES)
    if da is None:
        da = _find_value(income, DA_ALIASES)
    if operating_income is None or da is None:
        return _missing_field(
            "ebitda_ltm_musd",
            period_end=period_end,
            currency=currency,
            calculation_formula="EBITDA = Operating income + D&A",
            components=tuple(
                component
                for component in (
                    _component(
                        component="operating_income",
                        matched=operating_income,
                        currency=currency,
                        period_end=period_end,
                        fx_histories=fx_histories,
                    )
                    if operating_income is not None
                    else None,
                    _component(
                        component="depreciation_and_amortization",
                        matched=da,
                        currency=currency,
                        period_end=period_end,
                        fx_histories=fx_histories,
                    )
                    if da is not None
                    else None,
                )
                if component is not None
            ),
        )
    converted = _convert_money(
        operating_income.value + da.value,
        currency=currency,
        period_end=period_end,
        fx_histories=fx_histories,
    )
    status = _with_staleness(
        converted.value_status,
        period_end=period_end,
        fetched_at_utc=fetched_at_utc,
        max_statement_age_days=max_statement_age_days,
    )
    reported = _find_value(income, REPORTED_EBITDA_ALIASES)
    value_origin = (
        "reconciled_with_reported_field"
        if status == "OK" and reported is not None
        else "calculated_from_yahoo_fields"
    )
    components = [
        _component(
            component="operating_income",
            matched=operating_income,
            currency=currency,
            period_end=period_end,
            fx_histories=fx_histories,
        ),
        _component(
            component="depreciation_and_amortization",
            matched=da,
            currency=currency,
            period_end=period_end,
            fx_histories=fx_histories,
        ),
    ]
    if status == "OK" and reported is not None and converted.value_musd not in (None, 0.0):
        reported_converted = _convert_money(
            reported.value,
            currency=currency,
            period_end=period_end,
            fx_histories=fx_histories,
        )
        components.append(
            _component(
                component="reported_ebitda_cross_check",
                matched=reported,
                currency=currency,
                period_end=period_end,
                fx_histories=fx_histories,
            )
        )
        if reported_converted.value_status == "OK" and reported_converted.value_musd is not None:
            divergence = abs(reported_converted.value_musd - converted.value_musd) / abs(
                converted.value_musd
            )
            if divergence > ebitda_reconciliation_max_pct:
                status = "CONTAMINATED"
                value_origin = "reported_field_diverged"
    return _MappedField(
        field_name="ebitda_ltm_musd",
        value=converted.value_musd,
        value_status=status,
        period_end=period_end,
        period_type="ANNUAL",
        statement_currency=currency,
        statement_scale="absolute_to_usd_millions",
        value_origin=value_origin,
        calculation_formula="EBITDA = Operating income + D&A",
        components=tuple(components),
    )


def _map_da(
    income: pd.DataFrame,
    cashflow: pd.DataFrame,
    *,
    fetched_at_utc: str,
    max_statement_age_days: int,
    fx_histories: dict[str, pd.DataFrame],
) -> _MappedField:
    income_period_end = _period_end(income)
    cashflow_period_end = _period_end(cashflow)
    period_end = cashflow_period_end or income_period_end
    currency = _statement_currency(cashflow) or _statement_currency(income)
    if _periods_conflict(income_period_end, cashflow_period_end):
        return _missing_field("da_musd", period_end=period_end, currency=currency)
    da = _find_value(cashflow, DA_ALIASES)
    if da is None:
        da = _find_value(income, DA_ALIASES)
    if da is None:
        return _missing_field(
            "da_musd",
            period_end=period_end,
            currency=currency,
            calculation_formula="D&A = Yahoo depreciation and amortization",
        )
    converted = _convert_money(
        da.value,
        currency=currency,
        period_end=period_end,
        fx_histories=fx_histories,
    )
    status = _with_staleness(
        converted.value_status,
        period_end=period_end,
        fetched_at_utc=fetched_at_utc,
        max_statement_age_days=max_statement_age_days,
    )
    return _MappedField(
        field_name="da_musd",
        value=converted.value_musd,
        value_status=status,
        period_end=period_end,
        period_type="ANNUAL",
        statement_currency=currency,
        statement_scale="absolute_to_usd_millions",
        value_origin="yahoo_reported_component",
        calculation_formula="D&A = Yahoo depreciation and amortization",
        components=(
            _component(
                component="depreciation_and_amortization",
                matched=da,
                currency=currency,
                period_end=period_end,
                fx_histories=fx_histories,
            ),
        ),
    )


def _map_interest(
    income: pd.DataFrame,
    *,
    fetched_at_utc: str,
    max_statement_age_days: int,
    fx_histories: dict[str, pd.DataFrame],
) -> _MappedField:
    period_end = _period_end(income)
    currency = _statement_currency(income)
    interest = _find_value(income, INTEREST_EXPENSE_ALIASES)
    if interest is None:
        return _missing_field(
            "interest_expense_musd",
            period_end=period_end,
            currency=currency,
            calculation_formula="Interest expense = absolute Yahoo interest expense",
        )
    converted = _convert_money(
        abs(interest.value),
        currency=currency,
        period_end=period_end,
        fx_histories=fx_histories,
    )
    status = _with_staleness(
        converted.value_status,
        period_end=period_end,
        fetched_at_utc=fetched_at_utc,
        max_statement_age_days=max_statement_age_days,
    )
    return _MappedField(
        field_name="interest_expense_musd",
        value=converted.value_musd,
        value_status=status,
        period_end=period_end,
        period_type="ANNUAL",
        statement_currency=currency,
        statement_scale="absolute_to_usd_millions",
        value_origin="yahoo_reported_component",
        calculation_formula="Interest expense = absolute Yahoo interest expense",
        components=(
            _component(
                component="interest_expense",
                matched=interest,
                currency=currency,
                period_end=period_end,
                fx_histories=fx_histories,
                absolute=True,
            ),
        ),
    )


def _missing_field(
    field_name: str,
    *,
    period_end: date | None = None,
    currency: str = "",
    period_type: str = "ANNUAL",
    calculation_formula: str | None = None,
    components: tuple[dict[str, object], ...] = (),
) -> _MappedField:
    return _MappedField(
        field_name=field_name,
        value=None,
        value_status="MISSING",
        period_end=period_end,
        period_type=period_type,
        statement_currency=currency,
        statement_scale="not_applicable",
        value_origin="missing_yahoo_inputs",
        calculation_formula=calculation_formula,
        components=components,
    )


def _latest_statement_rows(raw: pd.DataFrame, statement_type: str) -> pd.DataFrame:
    rows = raw[
        raw["statement_type"].eq(statement_type)
        & raw["fetch_status"].eq(RAW_FETCH_STATUS_PASS)
        & raw["period_end"].notna()
    ].copy()
    if rows.empty:
        return rows
    rows["period_end"] = pd.to_datetime(rows["period_end"]).dt.date
    latest_period = rows["period_end"].max()
    return rows[rows["period_end"].eq(latest_period)].copy()


def _find_value(rows: pd.DataFrame, aliases: tuple[str, ...]) -> _MatchedValue | None:
    if rows.empty:
        return None
    working = rows.copy()
    working["_label_key"] = working["line_item_original"].fillna("").astype(str).map(
        _normalize_label
    )
    for alias in aliases:
        matches = working[working["_label_key"].eq(_normalize_label(alias))]
        if not matches.empty:
            value = optional_float(matches.iloc[0].get("value_raw"))
            if value is None:
                return None
            return _MatchedValue(
                value=value,
                line_item_original=str(matches.iloc[0].get("line_item_original") or alias),
            )
    return None


def _components_json(components: tuple[dict[str, object], ...]) -> str | None:
    if not components:
        return None
    return json.dumps(list(components), sort_keys=True, separators=(",", ":"))


def _component(
    *,
    component: str,
    matched: _MatchedValue | None,
    currency: str,
    period_end: date | None,
    fx_histories: dict[str, pd.DataFrame],
    sign: int = 1,
    absolute: bool = False,
    status: str | None = None,
) -> dict[str, object]:
    raw_value = matched.value if matched is not None else None
    conversion_value = abs(raw_value) if absolute and raw_value is not None else raw_value
    converted = _convert_money(
        conversion_value,
        currency=currency,
        period_end=period_end,
        fx_histories=fx_histories,
    )
    normalized_value = converted.value_musd
    if normalized_value is not None:
        normalized_value *= sign
    return {
        "component": component,
        "yahoo_line_item": matched.line_item_original if matched is not None else None,
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "unit": "MUSD",
        "statement_currency": currency,
        "status": status or converted.value_status,
    }


def _assumed_zero_component(
    *,
    component: str,
    status: str,
    currency: str,
) -> dict[str, object]:
    return {
        "component": component,
        "yahoo_line_item": None,
        "raw_value": None,
        "normalized_value": 0.0,
        "unit": "MUSD",
        "statement_currency": currency,
        "status": status,
    }


def _convert_money(
    value: float | None,
    *,
    currency: str,
    period_end: date | None,
    fx_histories: dict[str, pd.DataFrame],
) -> _ConvertedValue:
    numeric = optional_float(value)
    if numeric is None:
        return _ConvertedValue(None, "MISSING")
    currency = str(currency or "").upper().strip()
    if currency == "USD":
        return _ConvertedValue(numeric / 1_000_000.0, "OK")
    if not currency or period_end is None:
        return _ConvertedValue(None, "CURRENCY_UNCONVERTIBLE")
    fx_history = fx_histories.get(currency)
    if fx_history is None or fx_history.empty:
        return _ConvertedValue(None, "CURRENCY_UNCONVERTIBLE")
    aligned = merge_fx_asof(
        pd.DataFrame({"period_end": [period_end], "value_raw": [numeric]}),
        date_column="period_end",
        fx_history=fx_history,
    )
    rate = optional_float(aligned.iloc[0].get("fx_rate_to_usd"))
    if rate is None:
        return _ConvertedValue(None, "CURRENCY_UNCONVERTIBLE")
    return _ConvertedValue(numeric * rate / 1_000_000.0, "OK")


def _with_staleness(
    status: str,
    *,
    period_end: date | None,
    fetched_at_utc: str,
    max_statement_age_days: int,
) -> str:
    if status != "OK" or period_end is None:
        return status
    fetched_at = pd.to_datetime(fetched_at_utc, utc=True, errors="coerce")
    if pd.isna(fetched_at):
        return status
    age_days = (fetched_at.date() - period_end).days
    return "STALE" if age_days > max_statement_age_days else status


def _raw_tickers(raw: pd.DataFrame) -> list[str]:
    return sorted(raw["ticker"].dropna().astype(str).str.upper().str.strip().unique())


def _period_end(rows: pd.DataFrame) -> date | None:
    if rows.empty or "period_end" not in rows.columns:
        return None
    values = pd.to_datetime(rows["period_end"], errors="coerce").dropna()
    if values.empty:
        return None
    return values.max().date()


def _periods_conflict(left: date | None, right: date | None) -> bool:
    return left is not None and right is not None and left != right


def _statement_currency(rows: pd.DataFrame) -> str:
    if rows.empty or "financial_currency" not in rows.columns:
        return ""
    values = rows["financial_currency"].dropna().astype(str).str.upper().str.strip()
    values = values[values != ""]
    return "" if values.empty else str(values.iloc[0])


def _first_string(frame: pd.DataFrame, column: str) -> str:
    if column not in frame.columns:
        return ""
    values = frame[column].dropna().astype(str).str.strip()
    values = values[values != ""]
    return "" if values.empty else str(values.iloc[0])


def _statement_period(period_end: date | None) -> str | None:
    return f"FY{period_end.year}" if period_end is not None else None


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())
