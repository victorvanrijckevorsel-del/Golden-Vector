"""Shared scalar numeric coercion helpers."""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import ROUND_FLOOR, Decimal

import pandas as pd


def optional_float(value: object) -> float | None:
    """Return a float for scalar numeric input, otherwise ``None``.

    Note: this uses ``float()``, so it accepts Python underscore-grouped numeric
    strings (``"1_000"`` -> 1000.0) that ``pd.to_numeric`` would reject. The
    option-chain ``as_float`` alias relies on this; real feed/parquet inputs are
    numeric scalars (never underscore strings), so the difference is dormant —
    documented here so the consolidation's widening is intentional, not a surprise.
    """

    if is_missing(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if is_missing(numeric) else numeric


def align_to_step(
    value: float,
    *,
    minimum: float,
    step: float,
    maximum: float | None = None,
) -> float:
    """Nearest value an HTML ``min``/``step`` grid can hold (range-input snap).

    The ONE copy of the slider-grid math. Serve-layer formatters are barred from
    arithmetic, so they call this to emit a range ``value`` the browser will not
    silently rewrite (ticker gold dial, redesign plan D9). Exact-half ties go to
    the higher value, matching HTML's positive-infinity rule rather than Python's
    ties-to-even ``round``. When ``maximum`` is supplied, the result is capped at
    the highest legal grid point at or below it. Callers still own the lower-bound
    availability decision.
    """

    if (
        step <= 0
        or not math.isfinite(value)
        or not math.isfinite(minimum)
        or not math.isfinite(step)
    ):
        return value

    decimal_value = Decimal(str(value))
    decimal_minimum = Decimal(str(minimum))
    decimal_step = Decimal(str(step))
    delta = (decimal_value - decimal_minimum) / decimal_step
    index = int((delta + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))

    if maximum is not None and math.isfinite(maximum):
        maximum_index = int(
            ((Decimal(str(maximum)) - decimal_minimum) / decimal_step).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        index = min(index, maximum_index)

    return float(decimal_minimum + Decimal(index) * decimal_step)


def optional_finite_float(value: object) -> float | None:
    """Return a finite float for scalar numeric input, otherwise ``None``."""

    numeric = optional_float(value)
    if numeric is None or not math.isfinite(numeric):
        return None
    return numeric


def percent_to_fraction(value: float) -> float:
    """Convert a possibly-percent-scaled rate to a fraction using the screening
    convention: a value > 1.0 is read as a percent (5 -> 0.05); a value already <= 1.0
    is assumed to already be a fraction. ONE copy of this magnitude heuristic for the
    screening / manual rate inputs (royalty, tax) where the typed unit is ambiguous.

    Note: a feed whose unit is KNOWN (e.g. ^IRX is always a percent) must convert by
    that known unit, NOT this magnitude heuristic — see fetch_risk_free_rate."""

    return value / 100.0 if value > 1.0 else value


def strict_optional_float(value: object) -> float | None:
    """Return a float or ``None`` for missing values, raising on invalid text."""

    if is_missing(value):
        return None
    return float(value)


def require_finite_number(name: str, value: object) -> float:
    """Return a finite float, raising a clear error otherwise."""

    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be a finite number")
    return numeric


def require_finite_positive(name: str, value: object) -> float:
    """Return a finite positive float, raising a clear error otherwise."""

    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return numeric


def optional_int(value: object) -> int | None:
    """Return an int for scalar numeric input, otherwise ``None``."""

    numeric = optional_float(value)
    return int(numeric) if numeric is not None else None


def int_or_zero(value: object) -> int:
    """Return an int for scalar numeric input, otherwise zero."""

    return optional_int(value) or 0


def sum_optional_floats(values: object) -> float | None:
    """Sum numeric values, ignoring missing entries; return None if none are numeric."""

    if values is None:
        return None
    total = 0.0
    seen = False
    for value in values:
        numeric = optional_float(value)
        if numeric is None:
            continue
        total += numeric
        seen = True
    return total if seen else None


def ratio_over_positive(numerator: float | None, denominator: float | None) -> float | None:
    """Ratio that only exists over a strictly positive denominator.

    The guard is semantic, not just divide-by-zero safety: consumers use it for
    quantities like net debt / EBITDA where a non-positive denominator makes
    the ratio meaningless rather than merely infinite.
    """

    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def require_finite(numeric: float, *, field: str) -> float:
    """Reject NaN/inf at input boundaries.

    `nan <= 0` is False, so positivity checks silently pass non-finite
    values: inf flows into ratio math as a "valid" number and NaN is
    converted to NULL by SQLite (a silent field wipe). Every user-input
    numeric must pass through this gate.
    """

    if not math.isfinite(numeric):
        raise ValueError(f"{field} must be a finite number.")
    return numeric


def is_missing(value: object) -> bool:
    """Scalar-safe missing-value check."""

    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except Exception:
        return False
    return bool(missing) if isinstance(missing, bool) else False


def bool_or_false(value: object) -> bool:
    """Return scalar truthiness while treating every missing form as ``False``.

    Persisted nullable-boolean columns can yield ``pd.NA``. Calling ``bool`` on
    that scalar raises, so UI readers use this shared boundary helper instead.
    """

    return False if is_missing(value) else bool(value)


def rebase_to_base(values: Iterable[object], *, base: float = 100.0) -> list[float | None]:
    """Index a numeric series to ``base`` at its first finite, non-zero value.

    Each point becomes ``value / anchor * base``; non-finite/None points (and any point before
    the anchor) become ``None``. Returns all-``None`` when there is no usable anchor. This is the
    ONE copy of the rebasing math, used by the gold/stock/GDX/GDXJ overlay so series on very
    different price scales share one honest indexed axis."""

    rebased: list[float | None] = []
    anchor: float | None = None
    for value in values:
        numeric = optional_float(value)
        if numeric is not None and not math.isfinite(numeric):
            numeric = None
        if anchor is None and numeric is not None and numeric != 0.0:
            anchor = numeric
        rebased.append(None if (numeric is None or anchor is None) else numeric / anchor * base)
    return rebased
