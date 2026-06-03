from __future__ import annotations

from golden_vector.cli import build_parser, run_options_liquidity_summary
from golden_vector.serve.option_trading_data import clear_option_trading_cache
from tests.helpers import build_test_paths
from tests.test_option_trading_data import _write_option_inputs


def test_options_liquidity_summary_parser_accepts_optional_ticker():
    args = build_parser().parse_args(["options-liquidity-summary", "--ticker", "aem"])

    assert args.command == "options-liquidity-summary"
    assert args.ticker == "aem"


def test_run_options_liquidity_summary_prints_cached_tier_counts(tmp_path, capsys):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
    )

    exit_code = run_options_liquidity_summary(paths, ticker="AEM")

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Ticker | Put Tradable | Put Watch | Put No-trade" in output
    assert "AEM |" in output

