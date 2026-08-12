"""Tool D corporate resilience stress model."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.common.numeric import optional_float as _optional_float
from golden_vector.common.numeric import ratio_over_positive as _ratio
from golden_vector.common.numeric import require_finite_positive as _require_finite_positive
from golden_vector.contracts.config_models import AppConfig, ToolDConfig
from golden_vector.features.percentile_ranks import oriented_percentile
from golden_vector.model.gold_lines import GoldLine, line_from_two_points, x_for_value
from golden_vector.screening.manual_data import LoadedManualScreeningData
from golden_vector.screening.pipeline import compute_tool_b_in_memory

TOOL_D_SCHEMA_VERSION = 3

TOOL_D_OUTPUT_COLUMNS = [
    "ticker",
    "tool_d_schema_version",
    "as_of_date",
    "source_run_id",
    "finance_source",
    "source_tool_b_run_id",
    "snapshot_refresh_run_id",
    "gold_price_used",
    "spot_gold_usd",
    "spot_gold_date",
    "gold_price_delta_vs_spot_pct",
    "market_cap_musd",
    "screening_verdict",
    "confidence",
    "aisc_margin_yield_at_g",
    "aisc_margin_yield_at_spot",
    "reserve_life_years",
    "cash_cost_usd_per_oz",
    "production_oz",
    "aisc_usd_per_oz",
    "sustaining_capex_musd",
    "interest_expense_musd",
    "net_debt_musd",
    "forward_ebitda_musd_at_g",
    "forward_ebitda_musd_at_spot",
    "margin_per_oz_at_g",
    "margin_per_oz_at_spot",
    "margin_per_oz_delta_vs_spot",
    "headroom_to_breakeven_pct_at_g",
    "headroom_to_breakeven_pct_at_spot",
    "headroom_delta_vs_spot",
    "breaks_even_at_gold_usd",
    "interest_cover_gold_usd",
    "debt_stress_gold_usd",
    "survival_distance_to_interest_cover_pct",
    "cost_curve_aisc_percentile",
    "fragility_ebitda_pct_per_10pct_gold",
    "leverage_stressed_at_g",
    "leverage_stressed_at_spot",
    "leverage_delta_vs_spot",
    "ev_ebitda_at_g",
    "ebitda_pct_change_vs_spot",
    "survival_order_ladder",
    "resilience_flip_flags",
    "resilience_data_status",
    "survival_distance_component",
    "cost_curve_resilience_component",
    "fragility_resilience_component",
    "balance_sheet_resilience_component",
    "tool_d_quality_score",
    "tool_d_quality_rank",
    "tool_d_tags",
    "tool_d_explanation",
    "missing_inputs",
]

TOOL_D_RANK_COMPONENTS = {
    "survival_distance_to_interest_cover_pct": "survival_distance_component",
    "cost_curve_aisc_percentile": "cost_curve_resilience_component",
    "fragility_ebitda_pct_per_10pct_gold": "fragility_resilience_component",
    "leverage_stressed_at_g": "balance_sheet_resilience_component",
}

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
    official_fundamentals: pd.DataFrame | None = None
    finance_source: str = "our"


def compute_tool_d_outputs(
    *,
    inputs: ToolDExecutionInputs,
    config: ToolDConfig,
    gold_price: float,
    source_run_id: str,
) -> pd.DataFrame:
    """Compute Tool D at one gold price."""

    _require_finite_positive("gold_price", gold_price)
    _require_finite_positive("spot_gold_usd", inputs.spot_gold_usd)

    same_as_spot = abs(gold_price - inputs.spot_gold_usd) < 0.01
    spot = compute_tool_b_in_memory(
        app_config=inputs.app_config,
        manual_data=inputs.manual_data,
        normalized_market_snapshots=inputs.normalized_market_snapshots,
        gold_price_assumption=inputs.spot_gold_usd,
        snapshot_refresh_run_id=inputs.snapshot_refresh_run_id,
        snapshot_as_of_date=inputs.snapshot_as_of_date,
        source_run_id=source_run_id,
        official_fundamentals=inputs.official_fundamentals,
        finance_source=inputs.finance_source,
    )
    if same_as_spot:
        stressed = spot
        ebitda_anchor_gold_price = max(inputs.spot_gold_usd * 0.90, 1.0)
        ebitda_anchor = compute_tool_b_in_memory(
            app_config=inputs.app_config,
            manual_data=inputs.manual_data,
            normalized_market_snapshots=inputs.normalized_market_snapshots,
            gold_price_assumption=ebitda_anchor_gold_price,
            snapshot_refresh_run_id=inputs.snapshot_refresh_run_id,
            snapshot_as_of_date=inputs.snapshot_as_of_date,
            source_run_id=source_run_id,
            official_fundamentals=inputs.official_fundamentals,
            finance_source=inputs.finance_source,
        )
    else:
        stressed = compute_tool_b_in_memory(
            app_config=inputs.app_config,
            manual_data=inputs.manual_data,
            normalized_market_snapshots=inputs.normalized_market_snapshots,
            gold_price_assumption=gold_price,
            snapshot_refresh_run_id=inputs.snapshot_refresh_run_id,
            snapshot_as_of_date=inputs.snapshot_as_of_date,
            source_run_id=source_run_id,
            official_fundamentals=inputs.official_fundamentals,
            finance_source=inputs.finance_source,
        )
        ebitda_anchor_gold_price = inputs.spot_gold_usd
        ebitda_anchor = spot
    return build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        ebitda_anchor_tool_b=ebitda_anchor,
        ebitda_anchor_gold_price=ebitda_anchor_gold_price,
        manual_data=inputs.manual_data,
        tool_b_latest=inputs.tool_b_latest,
        config=config,
        gold_price=gold_price,
        spot_gold_usd=inputs.spot_gold_usd,
        spot_gold_date=inputs.spot_gold_date,
        source_run_id=source_run_id,
        finance_source=inputs.finance_source,
    )


def tool_d_stress_scenario_presets(spot_gold_usd: float) -> list[tuple[str, float]]:
    """Return the standard Tool D stress-lens scenario prices."""

    _require_finite_positive("spot_gold_usd", spot_gold_usd)
    return [
        ("Spot", float(spot_gold_usd)),
        ("-15%", float(spot_gold_usd) * 0.85),
        ("-25%", float(spot_gold_usd) * 0.75),
        ("-35%", float(spot_gold_usd) * 0.65),
        ("~$1,830", 1830.0),
        ("~$1,050", 1050.0),
    ]


def latest_gold_price_from_history(gold_history: pd.DataFrame) -> tuple[float, str | None]:
    """Return the latest usable gold price and date from a normalized gold history."""

    if gold_history.empty:
        raise ValueError("gold history is empty")
    working = gold_history.copy()
    if "date" not in working.columns:
        raise ValueError("gold history is missing date")
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    if "adj_close_usd" in working.columns:
        working["spot_gold_usd"] = pd.to_numeric(working["adj_close_usd"], errors="coerce")
    else:
        working["spot_gold_usd"] = pd.NA
    if "close_usd" in working.columns:
        working["spot_gold_usd"] = working["spot_gold_usd"].where(
            working["spot_gold_usd"].notna(),
            pd.to_numeric(working["close_usd"], errors="coerce"),
        )
    if "close" in working.columns:
        working["spot_gold_usd"] = working["spot_gold_usd"].where(
            working["spot_gold_usd"].notna(),
            pd.to_numeric(working["close"], errors="coerce"),
        )
    working = working[
        working["date"].notna() & pd.to_numeric(working["spot_gold_usd"], errors="coerce").gt(0)
    ]
    if working.empty:
        raise ValueError("gold history has no positive latest gold price")
    row = working.sort_values("date").iloc[-1]
    return float(row["spot_gold_usd"]), str(pd.Timestamp(row["date"]).date())


def build_tool_d_output_frame(
    *,
    stressed_tool_b: pd.DataFrame,
    spot_tool_b: pd.DataFrame,
    ebitda_anchor_tool_b: pd.DataFrame | None = None,
    ebitda_anchor_gold_price: float | None = None,
    manual_data: LoadedManualScreeningData,
    tool_b_latest: pd.DataFrame,
    config: ToolDConfig,
    gold_price: float,
    spot_gold_usd: float,
    spot_gold_date: str | None,
    source_run_id: str,
    finance_source: str = "our",
) -> pd.DataFrame:
    """Build Tool D output from Tool B in-memory frames."""

    _require_finite_positive("gold_price", gold_price)
    _require_finite_positive("spot_gold_usd", spot_gold_usd)
    stressed = _prepare_tool_b(stressed_tool_b)
    if stressed.empty:
        return pd.DataFrame(columns=TOOL_D_OUTPUT_COLUMNS)
    spot = _prepare_tool_b(spot_tool_b).set_index("ticker", drop=False)
    anchor = _prepare_tool_b(
        ebitda_anchor_tool_b if ebitda_anchor_tool_b is not None else spot_tool_b
    ).set_index("ticker", drop=False)
    resolved_anchor_gold = (
        ebitda_anchor_gold_price
        if ebitda_anchor_gold_price is not None
        else spot_gold_usd
    )
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
        anchor_row = anchor.loc[ticker] if ticker in anchor.index else pd.Series(dtype=object)
        latest_row = latest.loc[ticker] if ticker in latest.index else pd.Series(dtype=object)
        rows.append(
            _build_tool_d_row(
                stressed_row=pd.Series(stressed_row),
                spot_row=spot_row,
                anchor_row=anchor_row,
                manual_row=manual_row,
                latest_row=latest_row,
                config=config,
                gold_price=gold_price,
                ebitda_anchor_gold_price=resolved_anchor_gold,
                spot_gold_usd=spot_gold_usd,
                spot_gold_date=spot_gold_date,
                source_run_id=source_run_id,
                finance_source=finance_source,
            )
        )

    output = pd.DataFrame(rows, columns=TOOL_D_OUTPUT_COLUMNS)
    _add_quality_scores(output, config=config)
    output["tool_d_tags"] = output.apply(_tool_d_tags, axis=1)
    output["resilience_flip_flags"] = output.apply(_resilience_flip_flags, axis=1)
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
    anchor_row: pd.Series,
    manual_row: pd.Series,
    latest_row: pd.Series,
    config: ToolDConfig,
    gold_price: float,
    ebitda_anchor_gold_price: float,
    spot_gold_usd: float,
    spot_gold_date: str | None,
    source_run_id: str,
    finance_source: str,
) -> dict[str, object]:
    ticker = str(stressed_row.get("ticker", "")).upper()
    production = _optional_float(manual_row.get("production_oz"))
    aisc = _optional_float(manual_row.get("aisc_usd_per_oz"))
    sustaining_capex = _optional_float(manual_row.get("sustaining_capex_musd"))
    interest_expense = _optional_float(stressed_row.get("interest_expense_musd"))
    if interest_expense is None and not _is_yahoo_finance_source(finance_source):
        interest_expense = _optional_float(manual_row.get("interest_expense_musd"))
    cash_cost = _optional_float(manual_row.get("cash_cost_usd_per_oz"))
    net_debt = _optional_float(stressed_row.get("net_debt_musd"))
    if net_debt is None and not _is_yahoo_finance_source(finance_source):
        net_debt = _optional_float(manual_row.get("net_debt_musd"))
    forward_ebitda = _optional_float(stressed_row.get("forward_ebitda_musd"))
    spot_ebitda = _optional_float(spot_row.get("forward_ebitda_musd"))
    anchor_ebitda = _optional_float(anchor_row.get("forward_ebitda_musd"))
    market_cap = _optional_float(stressed_row.get("market_cap_musd"))

    margin = _margin(gold_price, aisc)
    spot_margin = _margin(spot_gold_usd, aisc)
    headroom = _headroom(gold_price, aisc)
    spot_headroom = _headroom(spot_gold_usd, aisc)
    leverage = _ratio(net_debt, forward_ebitda)
    spot_leverage = _ratio(net_debt, spot_ebitda)
    ev_ebitda = _ev_ebitda(
        market_cap=market_cap,
        net_debt=net_debt,
        forward_ebitda=forward_ebitda,
        max_reasonable_ev_ebitda=config.max_reasonable_ev_ebitda,
    )
    ebitda_change = _ebitda_change(forward_ebitda, spot_ebitda)
    ebitda_model = _ebitda_line_from_tool_b(
        gold_price=gold_price,
        ebitda_at_gold=forward_ebitda,
        anchor_gold_price=ebitda_anchor_gold_price,
        ebitda_at_anchor=anchor_ebitda,
    )
    interest_cover_gold = _threshold_gold(
        ebitda_model=ebitda_model,
        target_ebitda=interest_expense,
    )
    debt_stress_gold = _debt_stress_gold(
        ebitda_model=ebitda_model,
        net_debt=net_debt,
        danger_threshold=config.debt_stress_leverage_danger_threshold,
    )
    survival_distance = _survival_distance(
        gold_price=gold_price,
        survival_line=interest_cover_gold,
    )
    fragility = _fragility_slope(
        gold_price=gold_price,
        forward_ebitda=forward_ebitda,
        ebitda_model=ebitda_model,
    )
    missing_inputs = _missing_inputs(
        production=production,
        aisc=aisc,
        interest_expense=interest_expense,
        net_debt=net_debt,
        forward_ebitda=forward_ebitda,
    )
    data_status = _resilience_data_status(
        production=production,
        aisc=aisc,
        interest_expense=interest_expense,
        ebitda_model=ebitda_model,
    )

    return {
        "ticker": ticker,
        "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
        "as_of_date": stressed_row.get("as_of_date"),
        "source_run_id": source_run_id,
        "finance_source": finance_source,
        "source_tool_b_run_id": _source_tool_b_run_id(
            latest_row=latest_row,
            stressed_row=stressed_row,
            source_run_id=source_run_id,
            finance_source=finance_source,
        ),
        "snapshot_refresh_run_id": stressed_row.get("snapshot_refresh_run_id"),
        "gold_price_used": float(gold_price),
        "spot_gold_usd": float(spot_gold_usd),
        "spot_gold_date": spot_gold_date,
        "gold_price_delta_vs_spot_pct": _safe_ratio(gold_price - spot_gold_usd, spot_gold_usd),
        "market_cap_musd": market_cap,
        "screening_verdict": stressed_row.get("screening_verdict"),
        "confidence": stressed_row.get("confidence"),
        "aisc_margin_yield_at_g": _optional_float(stressed_row.get("aisc_margin_yield")),
        "aisc_margin_yield_at_spot": _optional_float(spot_row.get("aisc_margin_yield")),
        "reserve_life_years": _optional_float(manual_row.get("reserve_life_years")),
        "cash_cost_usd_per_oz": cash_cost,
        "production_oz": production,
        "aisc_usd_per_oz": aisc,
        "sustaining_capex_musd": sustaining_capex,
        "interest_expense_musd": interest_expense,
        "net_debt_musd": net_debt,
        "forward_ebitda_musd_at_g": forward_ebitda,
        "forward_ebitda_musd_at_spot": spot_ebitda,
        "margin_per_oz_at_g": margin,
        "margin_per_oz_at_spot": spot_margin,
        "margin_per_oz_delta_vs_spot": _difference(margin, spot_margin),
        "headroom_to_breakeven_pct_at_g": headroom,
        "headroom_to_breakeven_pct_at_spot": spot_headroom,
        "headroom_delta_vs_spot": _difference(headroom, spot_headroom),
        "breaks_even_at_gold_usd": aisc,
        "interest_cover_gold_usd": interest_cover_gold,
        "debt_stress_gold_usd": debt_stress_gold,
        "survival_distance_to_interest_cover_pct": survival_distance,
        "cost_curve_aisc_percentile": None,
        "fragility_ebitda_pct_per_10pct_gold": fragility,
        "leverage_stressed_at_g": leverage,
        "leverage_stressed_at_spot": spot_leverage,
        "leverage_delta_vs_spot": _difference(leverage, spot_leverage),
        "ev_ebitda_at_g": ev_ebitda,
        "ebitda_pct_change_vs_spot": ebitda_change,
        "survival_order_ladder": _survival_order_ladder(
            breakeven=aisc,
            interest_cover=interest_cover_gold,
        ),
        "resilience_flip_flags": None,
        "resilience_data_status": data_status,
        "survival_distance_component": None,
        "cost_curve_resilience_component": None,
        "fragility_resilience_component": None,
        "balance_sheet_resilience_component": None,
        "tool_d_quality_score": None,
        "tool_d_quality_rank": None,
        "tool_d_tags": None,
        "tool_d_explanation": None,
        "missing_inputs": ";".join(missing_inputs) if missing_inputs else None,
    }


def _add_quality_scores(output: pd.DataFrame, *, config: ToolDConfig) -> None:
    # C5: percentile pools contain ELIGIBLE rows only. Degraded rows are
    # excluded BEFORE any percentile is computed — a broken company must not be
    # able to move a healthy company's component, score, or rank (masking after
    # the pool still let it shift every healthy percentile).
    eligible = output["resilience_data_status"].eq("OK")
    output["cost_curve_aisc_percentile"] = oriented_percentile(
        pd.to_numeric(output.loc[eligible, "aisc_usd_per_oz"], errors="coerce"),
        high_good=True,
    ).reindex(output.index)
    component_percentiles = pd.DataFrame(index=output.index)
    for raw_column, component_column in TOOL_D_RANK_COMPONENTS.items():
        component_percentiles[component_column] = oriented_percentile(
            pd.to_numeric(output.loc[eligible, raw_column], errors="coerce"),
            high_good=config.quality_components[raw_column] == "high_good",
        ).reindex(output.index)
        output[component_column] = component_percentiles[component_column]

    component_count = component_percentiles.notna().sum(axis=1)
    output["tool_d_quality_score"] = component_percentiles.mean(axis=1, skipna=True)
    output["tool_d_quality_score"] = output["tool_d_quality_score"].where(
        component_count.eq(len(TOOL_D_RANK_COMPONENTS)) & eligible
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
    leverage = _optional_float(row.get("leverage_stressed_at_g"))
    if margin is not None and margin < 0:
        tags.append("margin_negative_at_G")
    if ebitda is None or ebitda <= 0:
        tags.append("leverage_undefined_at_G")
    if headroom is not None and 0 <= headroom < 0.10:
        tags.append("thin_margin_at_G")
    missing = str(row.get("missing_inputs") or "")
    if "aisc_usd_per_oz" in missing:
        tags.append("missing_aisc")
    if "production_oz" in missing:
        tags.append("missing_production")
    if "net_debt_musd" in missing:
        tags.append("missing_debt")
    if "interest_expense_musd" in missing:
        tags.append("missing_interest")
    danger_line = _optional_float(row.get("debt_stress_gold_usd"))
    gold = _optional_float(row.get("gold_price_used"))
    if (
        leverage is not None
        and danger_line is not None
        and gold is not None
        and gold <= danger_line
    ):
        tags.append("over_debt_stress_line_at_G")
    return ";".join(dict.fromkeys(tags)) if tags else None


def _resilience_flip_flags(row: pd.Series) -> str | None:
    flags: list[str] = []
    margin = _optional_float(row.get("margin_per_oz_at_g"))
    spot_margin = _optional_float(row.get("margin_per_oz_at_spot"))
    headroom = _optional_float(row.get("headroom_to_breakeven_pct_at_g"))
    spot_headroom = _optional_float(row.get("headroom_to_breakeven_pct_at_spot"))
    ebitda = _optional_float(row.get("forward_ebitda_musd_at_g"))
    spot_ebitda = _optional_float(row.get("forward_ebitda_musd_at_spot"))
    leverage = _optional_float(row.get("leverage_stressed_at_g"))
    spot_leverage = _optional_float(row.get("leverage_stressed_at_spot"))
    if margin is not None and margin < 0 and (spot_margin is None or spot_margin >= 0):
        flags.append("flips_margin_negative")
    if (
        headroom is not None
        and 0 <= headroom < 0.10
        and (spot_headroom is None or spot_headroom >= 0.10)
    ):
        flags.append("flips_thin_margin")
    if ebitda is not None and ebitda <= 0 and (spot_ebitda is None or spot_ebitda > 0):
        flags.append("flips_leverage_undefined")
    debt_line = _optional_float(row.get("debt_stress_gold_usd"))
    gold = _optional_float(row.get("gold_price_used"))
    spot_gold = _optional_float(row.get("spot_gold_usd"))
    if (
        debt_line is not None
        and gold is not None
        and spot_gold is not None
        and leverage is not None
        and (spot_leverage is None or spot_leverage < leverage)
        and gold <= debt_line < spot_gold
    ):
        flags.append("flips_over_debt_stress_line")
    return ";".join(flags) if flags else None


def _tool_d_explanation(row: pd.Series) -> str:
    rank = _optional_float(row.get("tool_d_quality_rank"))
    gold = _optional_float(row.get("gold_price_used"))
    interest_line = _optional_float(row.get("interest_cover_gold_usd"))
    debt_line = _optional_float(row.get("debt_stress_gold_usd"))
    status = str(row.get("resilience_data_status") or "")
    if rank is None:
        return (
            "Not scored because the survival inputs are incomplete."
            if status != "OK"
            else "Not scored because the resilience components are unavailable."
        )
    return (
        f"Resilience score {rank:.1f} at gold ${gold:.0f}/oz; "
        f"interest-cover line {_fmt_usd(interest_line)}, "
        f"debt-stress line {_fmt_usd(debt_line)}."
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


def _source_tool_b_run_id(
    *,
    latest_row: pd.Series,
    stressed_row: pd.Series,
    source_run_id: str,
    finance_source: str,
) -> object:
    if _is_yahoo_finance_source(finance_source) or source_run_id in {
        "candidate-finder-scenario",
        "workspace-tool-d-scenario",
    }:
        return stressed_row.get("source_run_id") or source_run_id
    return latest_row.get("source_run_id")


def _is_yahoo_finance_source(finance_source: str) -> bool:
    return str(finance_source or "").strip().lower() == "yahoo"


def _prepare_manual_company(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=["ticker"])
    result = frame.copy()
    result["ticker"] = result["ticker"].astype(str).str.upper().str.strip()
    return result[result["ticker"] != ""].drop_duplicates(subset=["ticker"], keep="last")


def _margin(gold_price: float, aisc: float | None) -> float | None:
    return gold_price - aisc if aisc is not None else None


def _headroom(gold_price: float, aisc: float | None) -> float | None:
    if aisc is None or gold_price <= 0:
        return None
    return (gold_price - aisc) / gold_price


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _difference(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return value - baseline


def _ebitda_line_from_tool_b(
    *,
    gold_price: float,
    ebitda_at_gold: float | None,
    anchor_gold_price: float,
    ebitda_at_anchor: float | None,
) -> GoldLine | None:
    line = line_from_two_points(
        gold_price,
        ebitda_at_gold,
        anchor_gold_price,
        ebitda_at_anchor,
    )
    # Tool D only trusts a rising EBITDA-vs-gold line; a flat or falling fit
    # means the two Tool B evaluations disagree with the model and is dropped.
    if line is None or line.slope <= 0:
        return None
    return line


def _threshold_gold(
    *,
    ebitda_model: GoldLine | None,
    target_ebitda: float | None,
) -> float | None:
    if target_ebitda is None or target_ebitda <= 0:
        return None
    return x_for_value(ebitda_model, target_ebitda)


def _debt_stress_gold(
    *,
    ebitda_model: GoldLine | None,
    net_debt: float | None,
    danger_threshold: float,
) -> float | None:
    if ebitda_model is None or net_debt is None or net_debt <= 0 or danger_threshold <= 0:
        return None
    return _threshold_gold(
        ebitda_model=ebitda_model,
        target_ebitda=net_debt / danger_threshold,
    )


def _survival_distance(
    *,
    gold_price: float,
    survival_line: float | None,
) -> float | None:
    if survival_line is None or gold_price <= 0:
        return None
    return (gold_price - survival_line) / gold_price


def _fragility_slope(
    *,
    gold_price: float,
    forward_ebitda: float | None,
    ebitda_model: GoldLine | None,
) -> float | None:
    if ebitda_model is None or forward_ebitda is None or forward_ebitda <= 0 or gold_price <= 0:
        return None
    return (ebitda_model.slope * gold_price * 0.10) / forward_ebitda


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
    interest_expense: float | None,
    net_debt: float | None,
    forward_ebitda: float | None,
) -> list[str]:
    missing: list[str] = []
    if production is None:
        missing.append("production_oz")
    if aisc is None:
        missing.append("aisc_usd_per_oz")
    if interest_expense is None:
        missing.append("interest_expense_musd")
    if net_debt is None:
        missing.append("net_debt_musd")
    if forward_ebitda is None:
        missing.append("forward_ebitda_musd_at_g")
    return missing


def _resilience_data_status(
    *,
    production: float | None,
    aisc: float | None,
    interest_expense: float | None,
    ebitda_model: GoldLine | None,
) -> str:
    if production is None or aisc is None:
        return "INSUFFICIENT_DATA"
    if interest_expense is None or interest_expense <= 0:
        return "INSUFFICIENT_INTEREST_DATA"
    if ebitda_model is None:
        return "INSUFFICIENT_EBITDA_MODEL"
    return "OK"


def _survival_order_ladder(
    *,
    breakeven: float | None,
    interest_cover: float | None,
) -> str | None:
    levels = [
        ("Breakeven", breakeven),
        ("Interest cover", interest_cover),
    ]
    available = [(label, value) for label, value in levels if value is not None]
    if not available:
        return None
    available.sort(key=lambda item: item[1], reverse=True)
    return " -> ".join(f"{label} ${value:,.0f}/oz" for label, value in available)


def _fmt_usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}/oz"
