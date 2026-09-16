import io
import shutil
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from golden_vector.app.paths import ProjectPaths


def call_wsgi_app(
    app,
    *,
    method: str,
    path: str,
    body: str = "",
    data: dict[str, str] | None = None,
    environ_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Invoke a workspace WSGI app in-process and capture the response.

    Consolidated superset of the per-file ``_call_wsgi_app`` helpers (visual
    redesign plan, Phase 0 task 16). ``path`` may carry a query string;
    ``data`` is urlencoded into the body when given (``body`` used otherwise).
    Returns ``status``, ``headers`` (last-wins dict), ``headers_list`` (exact
    pairs), ``body`` (utf-8 text), and ``body_bytes``.
    """
    if data is not None:
        body = urlencode(data)
    payload = body.encode("utf-8")
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    path_info, _, query_string = path.partition("?")
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path_info,
        "QUERY_STRING": query_string,
        "CONTENT_LENGTH": str(len(payload)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(payload),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    environ.update(environ_overrides or {})
    body_bytes = b"".join(app(environ, start_response))
    return {
        "status": captured["status"],
        "headers": dict(captured["headers"]),
        "headers_list": list(captured["headers"]),
        "body": body_bytes.decode("utf-8"),
        "body_bytes": body_bytes,
    }


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
    ebitda_ltm_musd: float = 500.0,
    interest_expense_musd: float = 100.0,
    reserve_life_years: float = 10.0,
    cash_margin_usd_per_oz: float | None = None,
    margin_pct: float | None = None,
    forward_revenue_musd: float = 1200.0,
    forward_ebitda_musd: float = 500.0,
    forward_net_income_musd: float = 300.0,
    forward_eps: float = 5.0,
    forward_pe: float = 8.0,
    ev_ebitda: float = 2.4,
    ev_ebitda_official: float | None = None,
    ev_ebitda_differs: bool = False,
    aisc_margin_est_musd: float = 180.0,
    aisc_margin_yield: float = 0.18,
    leverage: float = 0.4,
    leverage_official: float | None = None,
    leverage_differs: bool = False,
    financial_data_status: str = "OK",
    divergent_field_count: int = 0,
    max_divergence_pct: float | None = None,
    gold_price_used: float | None = None,
    spot_gold_usd: float | None = None,
    spot_gold_date: str | None = "2026-04-22",
    gold_price_basis: str = "latest_daily_gold_close",
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
    if gold_price_used is None:
        gold_price_used = gold_price_assumption
    if spot_gold_usd is None:
        spot_gold_usd = gold_price_assumption
    if ev_ebitda_official is None:
        ev_ebitda_official = ev_ebitda
    if leverage_official is None:
        leverage_official = leverage
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "gold_price_assumption": gold_price_assumption,
        "gold_price_used": gold_price_used,
        "spot_gold_usd": spot_gold_usd,
        "spot_gold_date": spot_gold_date,
        "gold_price_basis": gold_price_basis,
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
        "ebitda_ltm_musd": ebitda_ltm_musd,
        "interest_expense_musd": interest_expense_musd,
        "reserve_life_years": reserve_life_years,
        "cash_margin_usd_per_oz": cash_margin_usd_per_oz,
        "margin_pct": margin_pct,
        "forward_revenue_musd": forward_revenue_musd,
        "forward_ebitda_musd": forward_ebitda_musd,
        "forward_net_income_musd": forward_net_income_musd,
        "forward_eps": forward_eps,
        "forward_pe": forward_pe,
        "ev_ebitda": ev_ebitda,
        "ev_ebitda_our_view": ev_ebitda,
        "ev_ebitda_official": ev_ebitda_official,
        "ev_ebitda_differs": ev_ebitda_differs,
        "ev_ebitda_alternate_value": ev_ebitda_official,
        "ev_ebitda_alternate_label": "Yahoo Fundamentals",
        "ev_ebitda_show_alternate": ev_ebitda_differs and ev_ebitda_official is not None,
        "ev_ebitda_trailing": ev_ebitda,
        "aisc_margin_est_musd": aisc_margin_est_musd,
        "aisc_margin_yield": aisc_margin_yield,
        "leverage": leverage,
        "leverage_our_view": leverage,
        "leverage_official": leverage_official,
        "leverage_differs": leverage_differs,
        "leverage_alternate_value": leverage_official,
        "leverage_alternate_label": "Yahoo Fundamentals",
        "leverage_show_alternate": leverage_differs and leverage_official is not None,
        "enterprise_value_musd_our_view": enterprise_value_musd,
        "enterprise_value_musd_official": enterprise_value_musd,
        "financial_data_status": financial_data_status,
        "financial_difference_summary": None,
        "divergent_field_count": divergent_field_count,
        "max_divergence_pct": max_divergence_pct,
        "fundamental_check_score_official": fundamental_check_score,
        "fundamental_check_rank_official": fundamental_check_rank,
        "fundamental_checks_passed_official": passed,
        "fundamental_checks_total_official": total,
        "fundamental_check_summary_official": f"{passed}/{total}: {check_summary}",
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
        "finance_source": "our",
        "screening_verdict_official": screening_verdict,
        "confidence_official": "ESTIMATED",
        "layer1_status_official": "PASS",
        "layer1_pass_official": True,
        "layer1_fail_reasons_official": None,
        "layer2_incomplete_reasons_official": None,
        "net_debt_musd_our_view": net_debt_musd,
        "net_debt_musd_official": net_debt_musd,
        "ebitda_ltm_musd_our_view": ebitda_ltm_musd,
        "ebitda_ltm_musd_official": ebitda_ltm_musd,
        "interest_expense_musd_our_view": interest_expense_musd,
        "interest_expense_musd_official": interest_expense_musd,
        "cash_margin_usd_per_oz_our_view": cash_margin_usd_per_oz,
        "cash_margin_usd_per_oz_official": cash_margin_usd_per_oz,
        "margin_pct_our_view": margin_pct,
        "margin_pct_official": margin_pct,
        "forward_revenue_musd_our_view": forward_revenue_musd,
        "forward_revenue_musd_official": forward_revenue_musd,
        "forward_ebitda_musd_our_view": forward_ebitda_musd,
        "forward_ebitda_musd_official": forward_ebitda_musd,
        "forward_net_income_musd_our_view": forward_net_income_musd,
        "forward_net_income_musd_official": forward_net_income_musd,
        "forward_eps_our_view": forward_eps,
        "forward_eps_official": forward_eps,
        "forward_pe_our_view": forward_pe,
        "forward_pe_official": forward_pe,
        "aisc_margin_est_musd_our_view": aisc_margin_est_musd,
        "aisc_margin_est_musd_official": aisc_margin_est_musd,
        "aisc_margin_yield_our_view": aisc_margin_yield,
        "aisc_margin_yield_official": aisc_margin_yield,
    }


def source_date_n_trading_days_old(n: int) -> str:
    """A source date with exactly ``n`` US trading days after it, through today.

    Freshness fixtures must not be pinned to a literal date: the shared
    classifier ages a snapshot against the CURRENT US trading calendar, so a
    hardcoded "2026-08-11" silently drifts into (or out of) the stale band as
    real time passes. Counted here independently of the classifier so the test
    is a real oracle rather than a restatement of the code under test.
    """

    from datetime import datetime, timedelta, timezone

    from golden_vector.app.market_hours_refresh import (
        US_MARKET_TIMEZONE,
        is_us_equity_trading_day,
    )

    day = datetime.now(timezone.utc).astimezone(US_MARKET_TIMEZONE).date()
    counted = 0
    while counted < n:
        if is_us_equity_trading_day(day):
            counted += 1
        day -= timedelta(days=1)
    return day.isoformat()
