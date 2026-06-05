"""Tool D gold-stressed quality scorecard."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.contracts.config_models import AppConfig, ToolDConfig
from golden_vector.features.percentile_ranks import oriented_percentile
from golden_vector.screening.manual_data import LoadedManualScreeningData
from golden_vector.screening.pipeline import compute_tool_b_in_memory

TOOL_D_OUTPUT_COLUMNS = [
    "ticker",
    "as_of_date",
    "source_run_id",
    "source_tool_b_run_id",
    "snapshot_refresh_run_id",
    "gold_price_used",
    "spot_gold_usd",
    "spot_gold_date",
    "market_cap_musd",
    "screening_verdict",
    "confidence",
    "fcf_yield",
    "reserve_life_years",
    "cash_cost_usd_per_oz",
    "best_upside_pct",
    "production_oz",
    "aisc_usd_per_oz",
    "net_debt_musd",
    "forward_ebitda_musd_at_g",
    "forward_ebitda_musd_at_spot",
    "margin_per_oz_at_g",
    "headroom_to_breakeven_pct_at_g",
    "breaks_even_at_gold_usd",
    "leverage_stressed_at_g",
    "ev_ebitda_at_g",
    "ebitda_pct_change_vs_spot",
    "tool_d_quality_score",
    "tool_d_quality_rank",
    "tool_d_tags",
    "tool_d_explanation",
    "missing_inputs",
]

TOOL_D_QUALITY_COMPONENTS = (
    "headroom_to_breakeven_pct_at_g",
    "leverage_stressed_at_g",
    "ev_ebitda_at_g",
)


@dataclass(frozen=True)
class ToolDExecutionInputs:
    app_config: AppConfig
    manual_data: LoadedManualScreeningData
    normalized_market_snapshots: pd.DataFrame
    tool_b_latest: pd.DataFrame
    spot_gold_usd: float
    spot_gold_date: str | None
    snapshot_refresh_run_id: str | None
    snapshot_as_of_date: object = None


def compute_tool_d_outputs(
    *,
    inputs: ToolDExecutionInputs,
    config: ToolDConfig,
    gold_price: float,
    source_run_id: str,
) -> pd.DataFrame:
    """Compute Tool D at one gold price."""

    if gold_price <= 0:
        raise ValueError("gold_price must be positive")
    if inputs.spot_gold_usd <= 0:
        raise ValueError("spot_gold_usd must be positive")

    stressed = compute_tool_b_in_memory(
        app_config=inputs.app_config,
        manual_data=inputs.manual_data,
        normalized_market_snapshots=inputs.normalized_market_snapshots,
        gold_price_assumption=gold_price,
        snapshot_refresh_run_id=inputs.snapshot_refresh_run_id,
        snapshot_as_of_date=inputs.snapshot_as_of_date,
        source_run_id=source_run_id,
    )
    spot = compute_tool_b_in_memory(
        app_config=inputs.app_config,
        manual_data=inputs.manual_data,
        normalized_market_snapshots=inputs.normalized_market_snapshots,
        gold_price_assumption=inputs.spot_gold_usd,
        snapshot_refresh_run_id=inputs.snapshot_refresh_run_id,
        snapshot_as_of_date=inputs.snapshot_as_of_date,
        source_run_id=source_run_id,
    )
    return build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=inputs.manual_data,
        tool_b_latest=inputs.tool_b_latest,
        config=config,
        gold_price=gold_price,
        spot_gold_usd=inputs.spot_gold_usd,
        spot_gold_date=inputs.spot_gold_date,
        source_run_id=source_run_id,
    )


def build_tool_d_output_frame(
    *,
    stressed_tool_b: pd.DataFrame,
    spot_tool_b: pd.DataFrame,
    manual_data: LoadedManualScreeningData,
    tool_b_latest: pd.DataFrame,
    config: ToolDConfig,
    gold_price: float,
    spot_gold_usd: float,
    spot_gold_date: str | None,
    source_run_id: str,
) -> pd.DataFrame:
    """Build Tool D output from Tool B in-memory frames."""

    stressed = _prepare_tool_b(stressed_tool_b)
    if stressed.empty:
        return pd.DataFrame(columns=TOOL_D_OUTPUT_COLUMNS)
    spot = _prepare_tool_b(spot_tool_b).set_index("ticker", drop=False)
    manual = _prepare_manual_company(manual_data.company_inputs).set_index(
        "ticker",
        drop=False,
    )
    latest = _prepare_tool_b_latest(tool_b_latest).set_index("ticker", drop=False)

    rows: list[dict[str, object]] = []
    for stressed_row in stressed.to_dict(orient="records"):
        ticker = str(stressed_row["ticker"])
        manual_row = manual.loc[ticker] if ticker in manual.index else pd.Series(dtype=object)
        spot_row = spot.loc[ticker] if ticker in spot.index else pd.Series(dtype=object)
        latest_row = latest.loc[ticker] if ticker in latest.index else pd.Series(dtype=object)
        rows.append(
            _build_tool_d_row(
                stressed_row=pd.Series(stressed_row),
                spot_row=spot_row,
                manual_row=manual_row,
                latest_row=latest_row,
                config=config,
                gold_price=gold_price,
                spot_gold_usd=spot_gold_usd,
                spot_gold_date=spot_gold_date,
                source_run_id=source_run_id,
            )
        )

    output = pd.DataFrame(rows, columns=TOOL_D_OUTPUT_COLUMNS)
    _add_quality_scores(output, config=config)
    output["tool_d_tags"] = output.apply(_tool_d_tags, axis=1)
    output["tool_d_explanation"] = output.apply(_tool_d_explanation, axis=1)
    return output[TOOL_D_OUTPUT_COLUMNS].sort_values(
        ["tool_d_quality_rank", "ticker"],
        ascending=[False, True],
        na_position="last",
    ).reset_index(drop=True)


def _build_tool_d_row(
    *,
    stressed_row: pd.Series,
    spot_row: pd.Series,
    manual_row: pd.Series,
    latest_row: pd.Series,
    config: ToolDConfig,
    gold_price: float,
    spot_gold_usd: float,
    spot_gold_date: str | None,
    source_run_id: str,
) -> dict[str, object]:
    ticker = str(stressed_row.get("ticker", "")).upper()
    production = _optional_float(manual_row.get("production_oz"))
    aisc = _optional_float(manual_row.get("aisc_usd_per_oz"))
    net_debt = _optional_float(manual_row.get("net_debt_musd"))
    forward_ebitda = _optional_float(stressed_row.get("forward_ebitda_musd"))
    spot_ebitda = _optional_float(spot_row.get("forward_ebitda_musd"))
    market_cap = _optional_float(stressed_row.get("market_cap_musd"))

    margin = gold_price - aisc if aisc is not None else None
    headroom = margin / gold_price if margin is not None else None
    leverage = _ratio(net_debt, forward_ebitda)
    ev_ebitda = _ev_ebitda(
        market_cap=market_cap,
        net_debt=net_debt,
        forward_ebitda=forward_ebitda,
        max_reasonable_ev_ebitda=config.max_reasonable_ev_ebitda,
    )
    ebitda_change = _ebitda_change(forward_ebitda, spot_ebitda)
    missing_inputs = _missing_inputs(
        production=production,
        aisc=aisc,
        net_debt=net_debt,
        forward_ebitda=forward_ebitda,
    )

    return {
        "ticker": ticker,
        "as_of_date": stressed_row.get("as_of_date"),
        "source_run_id": source_run_id,
        "source_tool_b_run_id": latest_row.get("source_run_id"),
        "snapshot_refresh_run_id": stressed_row.get("snapshot_refresh_run_id"),
        "gold_price_used": float(gold_price),
        "spot_gold_usd": float(spot_gold_usd),
        "spot_gold_date": spot_gold_date,
        "market_cap_musd": market_cap,
        "screening_verdict": stressed_row.get("screening_verdict"),
        "confidence": stressed_row.get("confidence"),
        "fcf_yield": _optional_float(spot_row.get("fcf_yield")),
        "reserve_life_years": _optional_float(manual_row.get("reserve_life_years")),
        "cash_cost_usd_per_oz": _optional_float(manual_row.get("cash_cost_usd_per_oz")),
        "best_upside_pct": _optional_float(stressed_row.get("best_upside_pct")),
        "production_oz": production,
        "aisc_usd_per_oz": aisc,
        "net_debt_musd": net_debt,
        "forward_ebitda_musd_at_g": forward_ebitda,
        "forward_ebitda_musd_at_spot": spot_ebitda,
        "margin_per_oz_at_g": margin,
        "headroom_to_breakeven_pct_at_g": headroom,
        "breaks_even_at_gold_usd": aisc,
        "leverage_stressed_at_g": leverage,
        "ev_ebitda_at_g": ev_ebitda,
        "ebitda_pct_change_vs_spot": ebitda_change,
        "tool_d_quality_score": None,
        "tool_d_quality_rank": None,
        "tool_d_tags": None,
        "tool_d_explanation": None,
        "missing_inputs": ";".join(missing_inputs) if missing_inputs else None,
    }


def _add_quality_scores(output: pd.DataFrame, *, config: ToolDConfig) -> None:
    component_percentiles = pd.concat(
        [
            oriented_percentile(
                pd.to_numeric(output[column], errors="coerce"),
                high_good=config.quality_components[column] == "high_good",
            )
            for column in TOOL_D_QUALITY_COMPONENTS
        ],
        axis=1,
    )
    output["tool_d_quality_score"] = component_percentiles.mean(axis=1, skipna=True)
    output["tool_d_quality_score"] = output["tool_d_quality_score"].where(
        component_percentiles.notna().sum(axis=1).gt(0)
    )
    output["tool_d_quality_rank"] = oriented_percentile(
        output["tool_d_quality_score"],
        high_good=True,
    )


def _tool_d_tags(row: pd.Series) -> str | None:
    tags: list[str] = []
    margin = _optional_float(row.get("margin_per_oz_at_g"))
    headroom = _optional_float(row.get("headroom_to_breakeven_pct_at_g"))
    ebitda = _optional_float(row.get("forward_ebitda_musd_at_g"))
    ebitda_change = _optional_float(row.get("ebitda_pct_change_vs_spot"))
    if margin is not None and margin < 0:
        tags.append("margin_negative_at_G")
    if ebitda is None or ebitda <= 0:
        tags.append("leverage_undefined_at_G")
    if headroom is not None and 0 <= headroom < 0.10:
        tags.append("thin_margin_at_G")
    if ebitda_change is not None and ebitda_change >= 0.25:
        tags.append("deleveraging_strongly")
    missing = str(row.get("missing_inputs") or "")
    if "aisc_usd_per_oz" in missing:
        tags.append("missing_aisc")
    if "production_oz" in missing:
        tags.append("missing_production")
    if "net_debt_musd" in missing:
        tags.append("missing_debt")
    verdict = str(row.get("screening_verdict") or "").upper()
    if verdict and verdict not in {"STRONG_CANDIDATE", "WATCHLIST"}:
        tags.append("screen_out_context")
    return ";".join(dict.fromkeys(tags)) if tags else None


def _tool_d_explanation(row: pd.Series) -> str:
    rank = _optional_float(row.get("tool_d_quality_rank"))
    gold = _optional_float(row.get("gold_price_used"))
    headroom = _optional_float(row.get("headroom_to_breakeven_pct_at_g"))
    leverage = _optional_float(row.get("leverage_stressed_at_g"))
    if rank is None:
        return "Not ranked because the stressed quality components are unavailable."
    return (
        f"Quality rank {rank:.1f} at gold ${gold:.0f}/oz; "
        f"margin headroom {_fmt_pct(headroom)}, stressed leverage {_fmt_multiple(leverage)}."
    )


def _prepare_tool_b(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=["ticker"])
    result = frame.copy()
    result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    result = result[result["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="last")
    return result.reset_index(drop=True)


def _prepare_tool_b_latest(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=["ticker", "source_run_id"])
    result = frame[["ticker", *[col for col in ["source_run_id"] if col in frame.columns]]].copy()
    result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    return result[result["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="last")


def _prepare_manual_company(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=["ticker"])
    result = frame.copy()
    result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    return result[result["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="last")


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _ev_ebitda(
    *,
    market_cap: float | None,
    net_debt: float | None,
    forward_ebitda: float | None,
    max_reasonable_ev_ebitda: float,
) -> float | None:
    if market_cap is None or net_debt is None or forward_ebitda is None:
        return None
    if forward_ebitda <= 0:
        return None
    value = (market_cap + net_debt) / forward_ebitda
    if value <= 0 or value > max_reasonable_ev_ebitda:
        return None
    return value


def _ebitda_change(
    forward_ebitda: float | None,
    spot_ebitda: float | None,
) -> float | None:
    if forward_ebitda is None or spot_ebitda is None or spot_ebitda <= 0:
        return None
    return (forward_ebitda - spot_ebitda) / spot_ebitda


def _missing_inputs(
    *,
    production: float | None,
    aisc: float | None,
    net_debt: float | None,
    forward_ebitda: float | None,
) -> list[str]:
    missing: list[str] = []
    if production is None:
        missing.append("production_oz")
    if aisc is None:
        missing.append("aisc_usd_per_oz")
    if net_debt is None:
        missing.append("net_debt_musd")
    if forward_ebitda is None:
        missing.append("forward_ebitda_musd_at_g")
    return missing


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) else None


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _fmt_multiple(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}x"
