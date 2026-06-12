"""Backend portfolio analytics built from persisted tool artifacts."""

from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd

from golden_vector.common.eligibility import is_score_eligible
from golden_vector.common.frames import latest_records_by_key
from golden_vector.common.numeric import optional_float, sum_optional_floats
from golden_vector.model.gold_shock import (
    DEFAULT_GOLD_DOWN_MIN_BETA,
    DEFAULT_GOLD_DOWN_SCENARIO_FRACTION,
    compute_gold_shock_exposure,
)

GOLD_DOWN_SCENARIO_FRACTION = DEFAULT_GOLD_DOWN_SCENARIO_FRACTION
PUBLISHABLE_TOOL_A_CONFIDENCE = {"HIGH", "MEDIUM"}
DEGRADED_EXPOSURE_STATUS_TOKENS = frozenset({"STALE_FX", "WARN", "FAIL"})


def enrich_portfolio_analytics(
    *,
    positions: pd.DataFrame,
    summary: pd.DataFrame,
    tool_a: pd.DataFrame,
    tool_d: pd.DataFrame,
    benchmark_betas: pd.DataFrame,
    reconciliation: pd.DataFrame,
    gold_down_min_beta: float = DEFAULT_GOLD_DOWN_MIN_BETA,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach M3 analytics to persisted position and summary artifacts."""

    enriched_positions = positions.copy()
    if enriched_positions.empty:
        return _empty_positions(enriched_positions), _summary_with_analytics(
            summary,
            positions=enriched_positions,
            data_issues=[],
            benchmark_betas=benchmark_betas,
            reconciliation=reconciliation,
        )

    tool_a_by_ticker = latest_records_by_key(tool_a, "ticker", sort_column="as_of_date")
    tool_d_by_ticker = latest_records_by_key(tool_d, "ticker", sort_column="as_of_date")
    data_issues: list[dict[str, object]] = []

    rows: list[dict[str, object]] = []
    for row in enriched_positions.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "").upper()
        value_usd = optional_float(row.get("value_usd"))
        tool_a_row = tool_a_by_ticker.get(ticker)
        tool_d_row = tool_d_by_ticker.get(ticker)
        row.update(
            _tool_a_exposure_fields(
                ticker,
                value_usd,
                tool_a_row,
                data_issues,
                position_status=row.get("position_status"),
                gold_down_min_beta=gold_down_min_beta,
            )
        )
        row.update(_tool_d_resilience_fields(ticker, tool_d_row, data_issues))
        rows.append(row)

    enriched_positions = pd.DataFrame(rows)
    total_loss = sum_optional_floats(enriched_positions.get("gold_down_10_loss_usd"))
    if total_loss and total_loss > 0:
        enriched_positions["beta_contribution_fraction"] = enriched_positions[
            "gold_down_10_loss_usd"
        ].apply(lambda value: (optional_float(value) or 0.0) / total_loss)
    else:
        enriched_positions["beta_contribution_fraction"] = None

    return enriched_positions, _summary_with_analytics(
        summary,
        positions=enriched_positions,
        data_issues=data_issues,
        benchmark_betas=benchmark_betas,
        reconciliation=reconciliation,
    )


def _empty_positions(positions: pd.DataFrame) -> pd.DataFrame:
    for column in ANALYTICS_POSITION_COLUMNS:
        if column not in positions.columns:
            positions[column] = pd.Series(dtype="object")
    return positions


def _tool_a_exposure_fields(
    ticker: str,
    value_usd: float | None,
    tool_a_row: dict[str, object] | None,
    data_issues: list[dict[str, object]],
    *,
    position_status: object,
    gold_down_min_beta: float,
) -> dict[str, object]:
    if value_usd is None or value_usd <= 0:
        _add_issue(data_issues, ticker, "missing_price", "Position has no usable USD value.")
        return {
            "down_beta_core": None,
            "tool_a_confidence_label": None,
            "tool_a_score_eligible": False,
            "gold_down_10_pnl_usd": None,
            "gold_down_10_loss_usd": None,
            "effective_exposure_bucket": "Missing price",
        }
    degraded_status = _degraded_position_status(position_status)
    if tool_a_row is None:
        _add_issue(data_issues, ticker, "missing_tool_a", "No current Tool A beta artifact row.")
        if degraded_status:
            _add_issue(
                data_issues,
                ticker,
                "degraded_position_data",
                f"Portfolio valuation status is {degraded_status}.",
            )
            return {
                "down_beta_core": None,
                "tool_a_confidence_label": None,
                "tool_a_score_eligible": False,
                "gold_down_10_pnl_usd": None,
                "gold_down_10_loss_usd": None,
                "effective_exposure_bucket": "Degraded data",
            }
        return {
            "down_beta_core": None,
            "tool_a_confidence_label": None,
            "tool_a_score_eligible": False,
            "gold_down_10_pnl_usd": None,
            "gold_down_10_loss_usd": None,
            "effective_exposure_bucket": "Missing beta",
        }

    down_beta = optional_float(tool_a_row.get("down_beta_core"))
    confidence = str(tool_a_row.get("confidence_label") or "").upper() or None
    score_eligible = is_score_eligible(tool_a_row.get("score_eligible"), default=False)
    if degraded_status:
        _add_issue(
            data_issues,
            ticker,
            "degraded_position_data",
            f"Portfolio valuation status is {degraded_status}.",
        )
        return {
            "down_beta_core": down_beta,
            "tool_a_confidence_label": confidence,
            "tool_a_score_eligible": score_eligible,
            "gold_down_10_pnl_usd": None,
            "gold_down_10_loss_usd": None,
            "effective_exposure_bucket": "Degraded data",
        }
    publishable = (
        down_beta is not None
        and score_eligible
        and confidence in PUBLISHABLE_TOOL_A_CONFIDENCE
    )
    if not publishable:
        _add_issue(
            data_issues,
            ticker,
            "low_confidence_tool_a",
            f"Tool A beta is not publishable for portfolio analytics ({confidence or 'UNKNOWN'}).",
        )
        return {
            "down_beta_core": down_beta,
            "tool_a_confidence_label": confidence,
            "tool_a_score_eligible": score_eligible,
            "gold_down_10_pnl_usd": None,
            "gold_down_10_loss_usd": None,
            "effective_exposure_bucket": "Low-confidence beta",
        }

    shock = compute_gold_shock_exposure(
        value_usd=value_usd,
        beta=down_beta,
        shock_fraction=GOLD_DOWN_SCENARIO_FRACTION,
        min_effective_beta=gold_down_min_beta,
    )
    if not shock.modelable:
        _add_issue(
            data_issues,
            ticker,
            "low_or_negative_gold_beta",
            shock.reason or "Tool A beta is not usable for modeled gold-down exposure.",
        )
        return {
            "down_beta_core": down_beta,
            "tool_a_confidence_label": confidence,
            "tool_a_score_eligible": score_eligible,
            "gold_down_10_pnl_usd": None,
            "gold_down_10_loss_usd": None,
            "effective_exposure_bucket": "Low/negative beta",
        }
    return {
        "down_beta_core": down_beta,
        "tool_a_confidence_label": confidence,
        "tool_a_score_eligible": score_eligible,
        "gold_down_10_pnl_usd": shock.pnl_usd,
        "gold_down_10_loss_usd": shock.loss_usd,
        "effective_exposure_bucket": "Measured beta",
    }


def _degraded_position_status(position_status: object) -> str | None:
    tokens = [
        token.strip().upper()
        for token in str(position_status or "").split(";")
        if token.strip()
    ]
    for token in tokens:
        if token in DEGRADED_EXPOSURE_STATUS_TOKENS:
            return token
    return None


def _tool_d_resilience_fields(
    ticker: str,
    tool_d_row: dict[str, object] | None,
    data_issues: list[dict[str, object]],
) -> dict[str, object]:
    if tool_d_row is None:
        _add_issue(data_issues, ticker, "missing_tool_d", "No current Tool D resilience row.")
        return {
            "tool_d_quality_rank": None,
            "tool_d_quality_score": None,
            "tool_d_tags": None,
            "resilience_bucket": "Missing Tool D",
        }
    rank = optional_float(tool_d_row.get("tool_d_quality_rank"))
    score = optional_float(tool_d_row.get("tool_d_quality_score"))
    if rank is None:
        _add_issue(data_issues, ticker, "missing_tool_d_rank", "Tool D row has no quality rank.")
    return {
        "tool_d_quality_rank": rank,
        "tool_d_quality_score": score,
        "tool_d_tags": _optional_text(tool_d_row.get("tool_d_tags")),
        "resilience_bucket": _resilience_bucket(rank),
    }


def _summary_with_analytics(
    summary: pd.DataFrame,
    *,
    positions: pd.DataFrame,
    data_issues: list[dict[str, object]],
    benchmark_betas: pd.DataFrame,
    reconciliation: pd.DataFrame,
) -> pd.DataFrame:
    frame = summary.copy()
    if frame.empty:
        return frame
    for text_column in (
        "effective_exposure_json",
        "data_issues_json",
        "benchmark_beta_status",
        "reconciliation_status",
    ):
        if text_column in frame.columns:
            frame[text_column] = frame[text_column].astype("object")

    equity_value = optional_float(frame.iloc[0].get("total_value_usd")) or 0.0
    # Manual-entry M1-M4 has no broker-cash import yet. Keep cash at zero so
    # NAV is explicitly "entered stock positions" until the import milestone.
    cash_value = 0.0
    nav_value = equity_value + cash_value
    positions = _with_weight_columns(positions, equity_value=equity_value, nav_value=nav_value)
    coverage_value = _sum_if_bucket(positions, "Measured beta")
    # None means NO position had a modelable loss (e.g. every beta is
    # low-confidence). Keep it None: coercing to 0.0 would headline a
    # confidently wrong "$0 loss if gold -10%" - degraded data must be
    # excluded from confident headlines, not flagged next to them.
    total_loss = sum_optional_floats(positions.get("gold_down_10_loss_usd"))
    top_weights = sorted(
        [
            optional_float(value) or 0.0
            for value in positions.get("nav_weight_fraction", pd.Series(dtype="float")).tolist()
        ],
        reverse=True,
    )

    issues = list(data_issues)
    issues.extend(_position_data_issues(positions))
    issues.extend(_benchmark_issues(benchmark_betas))
    issues.extend(_reconciliation_issues(reconciliation))
    issues = _dedupe_issues(issues)

    _set_summary_value(frame, "equity_value_usd", equity_value)
    _set_summary_value(frame, "cash_value_usd", cash_value)
    _set_summary_value(frame, "nav_value_usd", nav_value)
    _set_summary_value(
        frame,
        "cash_weight_fraction",
        cash_value / nav_value if nav_value > 0 else None,
    )
    _set_summary_value(frame, "tool_a_coverage_value_usd", coverage_value)
    _set_summary_value(
        frame,
        "tool_a_coverage_fraction",
        coverage_value / equity_value if equity_value > 0 else None,
    )
    _set_summary_value(frame, "modeled_gold_down_10_loss_usd", total_loss)
    _set_summary_value(
        frame,
        "largest_position_weight_fraction",
        top_weights[0] if top_weights else None,
    )
    _set_summary_value(
        frame,
        "top3_position_weight_fraction",
        sum(top_weights[:3]) if top_weights else None,
    )
    _set_summary_value(
        frame,
        "effective_exposure_json",
        json.dumps(_effective_exposure_summary(positions, nav_value=nav_value), sort_keys=True),
    )
    _set_summary_value(frame, "data_issues_json", json.dumps(issues, sort_keys=True))
    _set_summary_value(frame, "benchmark_beta_status", _benchmark_status_summary(benchmark_betas))
    _set_summary_value(frame, "reconciliation_status", _reconciliation_status_summary(reconciliation))
    _set_summary_value(
        frame,
        "resilience_coverage_fraction",
        _coverage_fraction(
            positions.get("tool_d_quality_rank"),
            denominator=positions.get("value_usd"),
        ),
    )
    return frame


def apply_position_weights(
    positions: pd.DataFrame,
    summary: pd.DataFrame,
) -> pd.DataFrame:
    """Return positions with final equity/NAV weights from an enriched summary."""

    if positions.empty or summary.empty:
        return positions
    row = summary.iloc[0]
    return _with_weight_columns(
        positions.copy(),
        equity_value=optional_float(row.get("equity_value_usd")) or 0.0,
        nav_value=optional_float(row.get("nav_value_usd")) or 0.0,
    )


def _with_weight_columns(
    positions: pd.DataFrame,
    *,
    equity_value: float,
    nav_value: float,
) -> pd.DataFrame:
    if positions.empty:
        return _empty_positions(positions.copy())
    positions = positions.copy()
    positions["equity_weight_fraction"] = positions["value_usd"].apply(
        lambda value: (optional_float(value) or 0.0) / equity_value if equity_value > 0 else None
    )
    positions["nav_weight_fraction"] = positions["value_usd"].apply(
        lambda value: (optional_float(value) or 0.0) / nav_value if nav_value > 0 else None
    )
    return positions


def _set_summary_value(frame: pd.DataFrame, column: str, value: object) -> None:
    dtype = "object" if value is None or isinstance(value, str) else None
    frame[column] = pd.Series([value], index=frame.index, dtype=dtype)


def _sum_if_bucket(positions: pd.DataFrame, bucket: str) -> float:
    if positions.empty:
        return 0.0
    total = 0.0
    for row in positions.to_dict(orient="records"):
        if row.get("effective_exposure_bucket") != bucket:
            continue
        total += optional_float(row.get("value_usd")) or 0.0
    return total


def _coverage_fraction(values: object, *, denominator: object) -> float | None:
    value_items = list(values) if values is not None else []
    denominator_items = list(denominator) if denominator is not None else []
    denominator_total = sum_optional_floats(denominator_items) or 0.0
    if denominator_total <= 0:
        return None
    covered = 0.0
    for value, weight in zip(value_items, denominator_items, strict=False):
        if optional_float(value) is not None:
            covered += optional_float(weight) or 0.0
    return covered / denominator_total


def _effective_exposure_summary(positions: pd.DataFrame, *, nav_value: float) -> list[dict[str, object]]:
    buckets: dict[str, dict[str, object]] = defaultdict(
        lambda: {"bucket": "", "position_count": 0, "value_usd": 0.0, "nav_weight_fraction": None}
    )
    for row in positions.to_dict(orient="records"):
        bucket_name = str(row.get("effective_exposure_bucket") or "Unknown")
        bucket = buckets[bucket_name]
        bucket["bucket"] = bucket_name
        bucket["position_count"] = int(bucket["position_count"]) + 1
        bucket["value_usd"] = float(bucket["value_usd"]) + (optional_float(row.get("value_usd")) or 0.0)
    output = []
    for bucket in buckets.values():
        value_usd = float(bucket["value_usd"])
        bucket["nav_weight_fraction"] = value_usd / nav_value if nav_value > 0 else None
        output.append(bucket)
    return sorted(output, key=lambda item: str(item["bucket"]))


def _benchmark_issues(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return [
            {
                "ticker": None,
                "issue": "missing_benchmark_betas",
                "message": "Benchmark beta artifact is empty.",
            }
        ]
    issues = []
    for row in frame.to_dict(orient="records"):
        status = str(row.get("benchmark_status") or "")
        if status != "OK":
            issues.append(
                {
                    "ticker": row.get("benchmark_ticker"),
                    "issue": "benchmark_beta_not_publishable",
                    "message": row.get("benchmark_status_reason") or f"Benchmark status is {status}.",
                }
            )
    return issues


def _position_data_issues(positions: pd.DataFrame) -> list[dict[str, object]]:
    if positions.empty or "position_status" not in positions.columns:
        return []
    issues: list[dict[str, object]] = []
    for row in positions.to_dict(orient="records"):
        status = str(row.get("position_status") or "").strip()
        if not status or status == "OK":
            continue
        ticker = str(row.get("ticker") or "").strip().upper() or None
        for part in [item.strip() for item in status.split(";") if item.strip()]:
            issues.append(
                {
                    "ticker": ticker,
                    "issue": _position_issue_code(part),
                    "message": f"Portfolio valuation status is {part}.",
                }
            )
    return issues


def _position_issue_code(status: str) -> str:
    normalized = status.strip().lower().replace(" ", "_")
    if "missing_price" in normalized:
        return "missing_price"
    if "missing_fx" in normalized:
        return "missing_fx"
    if "stale_fx" in normalized:
        return "stale_fx"
    if "currency_mismatch" in normalized:
        return "currency_mismatch"
    if "normalization" in normalized or normalized in {"warn", "fail"}:
        return "snapshot_not_ok"
    return f"portfolio_{normalized}"


def _dedupe_issues(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (
            str(issue.get("ticker") or ""),
            str(issue.get("issue") or ""),
            str(issue.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _reconciliation_issues(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return [
            {
                "ticker": None,
                "issue": "missing_reconciliation",
                "message": "Portfolio reconciliation scaffold is missing.",
            }
        ]
    issues = []
    for row in frame.to_dict(orient="records"):
        status = str(row.get("status") or "")
        if status and status != "PASS":
            issues.append(
                {
                    "ticker": None,
                    "issue": "reconciliation_status",
                    "message": row.get("status_reason") or status,
                }
            )
    return issues


def _benchmark_status_summary(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "MISSING"
    statuses = sorted({str(value) for value in frame.get("benchmark_status", []) if str(value)})
    return "OK" if statuses == ["OK"] else "; ".join(statuses)


def _reconciliation_status_summary(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "MISSING"
    statuses = sorted({str(value) for value in frame.get("status", []) if str(value)})
    return "PASS" if statuses == ["PASS"] else "; ".join(statuses)


def _add_issue(
    issues: list[dict[str, object]],
    ticker: str | None,
    issue: str,
    message: str,
) -> None:
    issues.append({"ticker": ticker, "issue": issue, "message": message})


def _optional_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _resilience_bucket(rank: float | None) -> str:
    if rank is None:
        return "Unavailable"
    if rank >= 75:
        return "Strong resilience"
    if rank >= 50:
        return "Average resilience"
    return "Weak resilience"


ANALYTICS_POSITION_COLUMNS = [
    "equity_weight_fraction",
    "nav_weight_fraction",
    "down_beta_core",
    "tool_a_confidence_label",
    "tool_a_score_eligible",
    "gold_down_10_pnl_usd",
    "gold_down_10_loss_usd",
    "beta_contribution_fraction",
    "effective_exposure_bucket",
    "tool_d_quality_rank",
    "tool_d_quality_score",
    "tool_d_tags",
    "resilience_bucket",
]
