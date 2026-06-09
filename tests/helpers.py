import shutil
from datetime import date
from pathlib import Path

from golden_vector.app.paths import ProjectPaths


def build_test_paths(root: Path) -> ProjectPaths:
    root.mkdir(parents=True, exist_ok=True)
    data_dir = root / "data"
    paths = ProjectPaths(
        repo_root=root,
        config_dir=root / "config",
        data_dir=data_dir,
        raw_dir=data_dir / "raw",
        intermediate_dir=data_dir / "intermediate",
        output_dir=data_dir / "output",
        manual_dir=data_dir / "manual",
        runs_dir=data_dir / "runs",
        reviews_dir=root / "reviews",
        tests_dir=root / "tests",
    )
    shutil.copytree(
        ProjectPaths.discover().config_dir,
        paths.config_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("portfolio.local.yaml"),
    )
    return paths


def tool_b_output_row(
    ticker: str,
    *,
    as_of_date: date = date(2026, 4, 22),
    gold_price_assumption: float = 4000.0,
    screening_verdict: str = "WATCHLIST",
    confidence: str = "VERIFIED",
    fundamental_check_score: float = 85.7143,
    fundamental_check_rank: int | None = 1,
    snapshot_refresh_run_id: str = "refresh-run",
    source_run_id: str = "tool-b-run",
    market_cap_musd: float = 1000.0,
    share_price_usd: float = 100.0,
    enterprise_value_musd: float | None = None,
    production_oz: float = 1_000_000.0,
    aisc_usd_per_oz: float = 1500.0,
    cash_cost_usd_per_oz: float = 1000.0,
    net_debt_musd: float = 200.0,
    reserve_life_years: float = 10.0,
    cash_margin_usd_per_oz: float | None = None,
    margin_pct: float | None = None,
    forward_revenue_musd: float = 1200.0,
    forward_ebitda_musd: float = 500.0,
    forward_net_income_musd: float = 300.0,
    forward_eps: float = 5.0,
    forward_pe: float = 8.0,
    ev_ebitda: float = 2.4,
    sustainable_fcf_musd: float = 180.0,
    fcf_yield: float = 0.18,
    leverage: float = 0.4,
) -> dict[str, object]:
    passed = round((fundamental_check_score / 100.0) * 7)
    total = 7
    check_labels = (
        "Data complete",
        "AISC",
        "Margin",
        "FCF yield",
        "Reserve life",
        "Net Debt/EBITDA",
        "Forward P/E",
    )
    check_summary = "; ".join(
        f"{label} {'PASS' if index < passed else 'FAIL'}"
        for index, label in enumerate(check_labels)
    )
    enterprise_value_musd = (
        market_cap_musd + net_debt_musd
        if enterprise_value_musd is None
        else enterprise_value_musd
    )
    cash_margin_usd_per_oz = (
        gold_price_assumption - aisc_usd_per_oz
        if cash_margin_usd_per_oz is None
        else cash_margin_usd_per_oz
    )
    margin_pct = (
        cash_margin_usd_per_oz / gold_price_assumption
        if margin_pct is None
        else margin_pct
    )
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "gold_price_assumption": gold_price_assumption,
        "layer1_status": "PASS",
        "layer1_pass": True,
        "layer1_fail_reasons": None,
        "layer2_incomplete_reasons": None,
        "screening_verdict": screening_verdict,
        "confidence": confidence,
        "jurisdiction_tier": 1,
        "market_cap_musd": market_cap_musd,
        "share_price_usd": share_price_usd,
        "enterprise_value_musd": enterprise_value_musd,
        "production_oz": production_oz,
        "aisc_usd_per_oz": aisc_usd_per_oz,
        "cash_cost_usd_per_oz": cash_cost_usd_per_oz,
        "net_debt_musd": net_debt_musd,
        "reserve_life_years": reserve_life_years,
        "cash_margin_usd_per_oz": cash_margin_usd_per_oz,
        "margin_pct": margin_pct,
        "forward_revenue_musd": forward_revenue_musd,
        "forward_ebitda_musd": forward_ebitda_musd,
        "forward_net_income_musd": forward_net_income_musd,
        "forward_eps": forward_eps,
        "forward_pe": forward_pe,
        "ev_ebitda": ev_ebitda,
        "sustainable_fcf_musd": sustainable_fcf_musd,
        "fcf_yield": fcf_yield,
        "leverage": leverage,
        "fundamental_check_score": fundamental_check_score,
        "fundamental_check_rank": fundamental_check_rank,
        "fundamental_checks_passed": passed,
        "fundamental_checks_total": total,
        "fundamental_check_summary": f"{passed}/{total}: {check_summary}",
        "missing_manual_fields": None,
        "next_financial_report_date": None,
        "next_production_report_date": None,
        "snapshot_refresh_run_id": snapshot_refresh_run_id,
        "snapshot_as_of_date": as_of_date,
        "snapshot_normalization_status": "PASS",
        "fx_staleness_days": 0,
        "fx_policy_max_staleness_days": 5,
        "fx_policy_block_on_stale_fx": False,
        "source_run_id": source_run_id,
    }
