"""Tool B verdict and fundamental-check helpers."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import VerdictThresholds

LAYER1_CHECK_LABELS = {
    "data_complete": "Data complete",
    "aisc": "AISC",
    "margin": "Margin",
    "aisc_margin_yield": "AISC margin yield",
    "reserve_life": "Reserve life",
    "leverage": "Net Debt/EBITDA",
}

FUNDAMENTAL_CHECK_ORDER = (
    "data_complete",
    "aisc",
    "margin",
    "aisc_margin_yield",
    "reserve_life",
    "leverage",
    "forward_pe",
)

FUNDAMENTAL_CHECK_LABELS = {
    **LAYER1_CHECK_LABELS,
    "forward_pe": "Forward P/E",
}

#: The forward-P/E check fails in TWO different ways and the persisted code says
#: which: above the configured cut-off (``FORWARD_PE_FAIL``) or built on
#: non-positive forward earnings, where no multiple exists to compare at all.
#: Consumers route on the code and never re-run the comparison themselves.
FORWARD_PE_NON_POSITIVE_CODE = "FORWARD_PE_NON_POSITIVE_EARNINGS"


def determine_screening_verdict(
    *,
    confidence: str,
    layer1_status: str,
    forward_pe: float | None,
    thresholds: VerdictThresholds,
) -> str:
    if confidence == "INCOMPLETE" or layer1_status == "INCOMPLETE":
        return "INCOMPLETE"
    if (
        forward_pe is not None
        and forward_pe > 0
        and layer1_status == "PASS"
        and forward_pe < thresholds.strong_candidate_forward_pe_max
    ):
        return "STRONG_CANDIDATE"
    if (
        forward_pe is not None
        and forward_pe > 0
        and forward_pe < thresholds.watchlist_forward_pe_max
    ):
        return "WATCHLIST"
    return "SCREEN_OUT"


def compute_fundamental_checks(
    *,
    layer1_check_statuses: dict[str, str],
    forward_pe: float | None,
    thresholds: VerdictThresholds,
) -> dict[str, object]:
    """Summarize visible, rule-based Tool B checks.

    Layer 1 owns the mining threshold checks. This helper only adds the
    forward-P/E check that already sits next to the Tool B verdict logic.
    """
    statuses = {
        key: _clean_status(layer1_check_statuses.get(key))
        for key in LAYER1_CHECK_LABELS
    }
    forward_pe_status, forward_pe_fail_code = _forward_pe_check(
        forward_pe,
        thresholds=thresholds,
    )
    statuses["forward_pe"] = forward_pe_status
    passed = sum(1 for status in statuses.values() if status == "PASS")
    total = len(FUNDAMENTAL_CHECK_ORDER)
    summary_parts = [
        f"{FUNDAMENTAL_CHECK_LABELS[key]} {statuses[key]}"
        for key in FUNDAMENTAL_CHECK_ORDER
    ]
    # Machine-readable failure codes (e.g. FORWARD_PE_FAIL) so serve can render
    # per-check sentences without parsing the display summary. The ticker page
    # surfaces a check only when it FAILS; N/A is not a failure. A check with
    # more than one way to fail names WHICH way here, so no reader ever
    # re-derives the rule from the value.
    fail_codes_by_key = {"forward_pe": forward_pe_fail_code}
    fail_codes = [
        fail_codes_by_key.get(key) or f"{key.upper()}_FAIL"
        for key in FUNDAMENTAL_CHECK_ORDER
        if statuses[key] == "FAIL"
    ]
    return {
        "fundamental_check_score": round(100.0 * passed / total, 4),
        "fundamental_checks_passed": passed,
        "fundamental_checks_total": total,
        "fundamental_check_summary": f"{passed}/{total}: " + "; ".join(summary_parts),
        "fundamental_check_fail_codes": ";".join(fail_codes) if fail_codes else None,
    }


def _forward_pe_check(
    forward_pe: float | None,
    *,
    thresholds: VerdictThresholds,
) -> tuple[str, str | None]:
    """``(status, fail code)`` for the forward-P/E check.

    The status keeps the PASS / FAIL / N/A vocabulary the pass counts and the
    display summary read — a fail is a fail either way. The CODE distinguishes
    the two genuinely different failures so no consumer has to re-derive the
    rule from the value: a non-positive forward P/E is not a multiple that may
    be compared with a cut-off, it is a statement about earnings.
    """

    if forward_pe is None or pd.isna(forward_pe):
        return "N/A", None
    if forward_pe <= 0:
        return "FAIL", FORWARD_PE_NON_POSITIVE_CODE
    if forward_pe < thresholds.strong_candidate_forward_pe_max:
        return "PASS", None
    return "FAIL", "FORWARD_PE_FAIL"


def _clean_status(value: object) -> str:
    status = str(value or "N/A").upper()
    if status in {"PASS", "FAIL", "N/A"}:
        return status
    return "N/A"
