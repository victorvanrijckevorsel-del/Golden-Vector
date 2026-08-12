"""Formatting and small row helpers for the local workspace UI."""

from __future__ import annotations

import re as _re
from html import escape
from typing import Any

import pandas as pd

from golden_vector.common.numeric import optional_float as _optional_float
from golden_vector.common.numeric import require_finite
from golden_vector.common.strings import normalize_ticker


RATE_FIELDS = {"royalty_rate", "tax_rate"}


TOOL_A_PERCENT_FIELDS = {
    "total_volatility_52w",
    "residual_volatility_52w",
    "downside_volatility_52w",
}


TOOL_A_NUMERIC_FIELDS = {
    "structural_delta_core",
    "structural_delta_6m",
    "structural_delta_12m",
    "structural_delta_3y",
    "structural_gamma_core",
    "gamma_6m",
    "gamma_12m",
    "gamma_3y",
    "up_beta_6m",
    "down_beta_6m",
    "up_beta_12m",
    "down_beta_12m",
    "up_beta_3y",
    "down_beta_3y",
    "asymmetry_ratio_6m",
    "asymmetry_ratio_12m",
    "asymmetry_ratio_3y",
    "asymmetry_ratio_core",
    "confidence_score",
    "tool_a_score",
}


def _fmt_form_number(value: float) -> str:
    """Format a number for HTML input value attributes without trailing .0."""
    if value is None:
        return ""
    return f"{value:g}"


def _column_unique(frame: pd.DataFrame, column_name: str) -> set[str]:
    if frame.empty or column_name not in frame.columns:
        return set()
    series = frame[column_name].dropna().astype(str)
    return {value for value in series.unique() if value and value.lower() != "nan"}


def _is_na(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _fmt_note_tag(value: Any) -> str:
    text = _fmt_text(value)
    if text == "-":
        return text
    return f"<span class=\"badge note-tag\">{text}</span>"


def _metric_card(
    title: str,
    value: str,
    *,
    help_text: str | None = None,
    help_key: str | None = None,
    app_config: Any = None,
) -> str:
    """The one shared metric-card renderer (plan section 10.2).

    Two ways to opt into the standard click-to-explain icon next to the title:
    ``help_key`` reads the shared ``COLUMN_HELP`` registry (preferred — one copy
    of the wording, and thresholds resolve from config), ``help_text`` passes
    free text for the few cards with no registry entry. Both import lazily so
    this formatting module stays import-light for callers that never use help.
    """
    if help_key:
        from golden_vector.serve.column_help import help_icon

        heading = escape(title) + help_icon(title, key=help_key, app_config=app_config)
    elif help_text:
        from golden_vector.serve.column_help import help_term

        heading = help_term(title, text=help_text)
    else:
        heading = escape(title)
    from golden_vector.serve.ui.components import data_card

    return data_card(
        "",
        value,
        label_html=heading,
        legacy=True,
    )


def _frame_index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for record in frame.to_dict(orient="records"):
        # The ONE ticker normalizer (common.strings): it strips as well as
        # upper-cases, so a padded symbol in a manual-input frame indexes to the
        # same key the routes look up.
        ticker = normalize_ticker(record.get("ticker"))
        if ticker:
            indexed[ticker] = record
    return indexed


def _ticker_rows(frame: pd.DataFrame, ticker: str) -> list[dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return frame[frame["ticker"].astype(str).str.upper() == ticker].to_dict(orient="records")


def _humanize_column_name(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _fmt_text(value: Any) -> str:
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except TypeError:
        pass
    text = str(value).strip()
    return escape(text) if text else "-"


def collapsible_text_td(value: Any, *, threshold: int = 60) -> str:
    """A table cell that keeps rows even-height: short text renders inline, but long
    text (or several joined notes/tags) collapses behind a click-to-expand summary so
    the cell never becomes a tall free-text tower. Accepts a string or a list/tuple of
    strings (joined with '; ')."""

    if isinstance(value, (list, tuple)):
        # Drop null-like members (None, pd.NA, NaN) before stringifying so they
        # never render as the literal "None" / "<NA>".
        items = [
            str(item).strip()
            for item in value
            if not _is_na(item) and str(item).strip()
        ]
        text = "; ".join(items)
    else:
        if value is None:
            text = ""
        else:
            try:
                text = "" if pd.isna(value) else str(value).strip()
            except (TypeError, ValueError):
                text = str(value).strip()
    if not text or text == "-":
        return "<td>-</td>"
    if len(text) <= threshold:
        return f"<td>{escape(text)}</td>"
    first = text.split(";")[0].strip()
    summary = first if len(first) <= 52 else first[:51] + "…"
    return (
        "<td><details class=\"cell-notes\"><summary>"
        f"{escape(summary)}</summary><span>{escape(text)}</span></details></td>"
    )


def _fmt_number(value: Any, *, decimals: int) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _fmt_text(value)
    if pd.isna(numeric):
        return "-"
    return escape(f"{numeric:,.{decimals}f}")


def _fmt_percent(value: Any, *, decimals: int = 1) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _fmt_text(value)
    if pd.isna(numeric):
        return "-"
    return escape(f"{numeric * 100:,.{decimals}f}%")


def source_alternate_span(alternate_label: str, value_text: str) -> str:
    """The compact "(Yahoo 2.5)" divergence accent shown next to a dual-source ratio value."""
    short = "Yahoo" if alternate_label == "Yahoo Fundamentals" else alternate_label
    return f"<span class=\"source-alternate\">({escape(short)} {value_text})</span>"


def format_dte_suffix(days_to_expiry: object) -> str:
    numeric = _optional_float(days_to_expiry)
    if numeric is None:
        return ""
    return f" ({_fmt_number(numeric, decimals=0)} DTE)"


# Sentinel sort key for missing numeric cells. Within JS's safe-integer
# range (MAX_SAFE_INTEGER ≈ 9.007e15) and well above any realistic Tool B
# target price or Tool A score, so it reliably sorts last ascending /
# first descending without colliding with a real value. Per Codex's
# v3 review.
_MISSING_SORT_SENTINEL = "9000000000000000"


def _fmt_numeric_td(
    value: Any, *, decimals: int, as_percent: bool = False, extra: str = ""
) -> str:
    """Render a numeric <td> with a DataTables-compatible sort key.

    Returns HTML like `<td data-order="1.074">107.4%</td>`. The
    `data-order` attribute is the raw number (unformatted) so
    DataTables' numeric sort works correctly; the cell text is the
    human-facing formatted display. For missing/None values, the
    display is "-" and the sort key is the `_MISSING_SORT_SENTINEL`.

    `extra` is trusted HTML appended inside the cell after the value (e.g. a help/info
    icon); it must NOT affect the sort key, so it lives outside `data-order`.

    Use this instead of wrapping `_fmt_number(...)` / `_fmt_percent(...)`
    inline in table rows whenever the column should be sortable
    numerically.
    """
    if value is None:
        return f"<td data-order=\"{_MISSING_SORT_SENTINEL}\">-{extra}</td>"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        # Non-numeric fallback: still wrap so the column stays sortable
        # by text; sentinel keeps the sort predictable.
        return f"<td data-order=\"{_MISSING_SORT_SENTINEL}\">{_fmt_text(value)}{extra}</td>"
    if pd.isna(numeric):
        return f"<td data-order=\"{_MISSING_SORT_SENTINEL}\">-{extra}</td>"
    display = (
        f"{numeric * 100:,.{decimals}f}%" if as_percent else f"{numeric:,.{decimals}f}"
    )
    return f"<td data-order=\"{numeric}\">{escape(display)}{extra}</td>"


def _fmt_value(value: Any, column_name: str) -> str:
    if column_name in RATE_FIELDS.union(TOOL_A_PERCENT_FIELDS):
        return _fmt_percent(value)
    if column_name.endswith("_rank"):
        return _fmt_number(value, decimals=0)
    if column_name in TOOL_A_NUMERIC_FIELDS:
        return _fmt_number(value, decimals=2)
    if isinstance(value, (int, float)):
        return _fmt_number(value, decimals=2)
    return _fmt_text(value)


def _format_form_value(field_name: str, value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    if field_name in RATE_FIELDS:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{numeric * 100:g}"
    return str(value)


def _coerce_form_numeric(value: str) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    # One normalize boundary (deep-review M2): a trailing "%" is stripped as a
    # COSMETIC suffix only — no division here. The manual store owns percent→
    # fraction conversion for rate fields (percent_to_fraction), so dividing
    # here too turned "30%" into 0.3% (double divide).
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        numeric = float(text)
    except ValueError as exc:
        raise ValueError("Numeric fields must be numeric.") from exc
    require_finite(numeric, field="Numeric fields")
    return numeric


def _coerce_form_text(value: str) -> str | None:
    text = str(value).strip()
    return text or None


def _first_frame_number(frame: pd.DataFrame, column: str) -> float | None:
    """First non-null numeric value of a column, or None.

    Shared by the Tool B and Tool D overview pages to derive the
    displayed gold price from the rendered frame's provenance columns —
    the frame, not the request, is the source of truth for what is shown.
    """
    if frame.empty or column not in frame.columns:
        return None
    series = frame[column].dropna()
    if series.empty:
        return None
    try:
        return float(series.iloc[0])
    except (TypeError, ValueError):
        return None


def _first_frame_text(frame: pd.DataFrame, column: str) -> str | None:
    """First non-null value of a column as text, or None."""
    if frame.empty or column not in frame.columns:
        return None
    series = frame[column].dropna()
    if series.empty:
        return None
    text = str(series.iloc[0]).strip()
    return text or None


def id_token(value: object) -> str:
    """Lowercase, id-safe slug for element ids and in-page anchors (``BHP.AX`` -> ``bhp-ax``).

    ONE copy of the slug rule: runs of non-alphanumerics collapse to a single dash,
    leading/trailing dashes are stripped, and an empty result falls back to ``x`` so
    an id is never blank.
    """

    slug = _re.sub(r"[^A-Za-z0-9]+", "-", str(value)).strip("-").lower()
    return slug or "x"
