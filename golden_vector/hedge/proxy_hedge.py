"""Down-beta similarity proxy mapping for non-optionable holdings."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ProxyMatch:
    target_ticker: str
    proxy_ticker: str
    proxy_type: str
    target_down_beta: float | None
    proxy_down_beta: float | None
    down_beta_diff: float | None
    tool_a_confidence: float | None
    tool_b_verdict: str | None
    basis_risk_label: str
    reason: str


def map_proxy_hedges(
    *,
    non_optionable_tickers: list[str],
    optionable_tickers: list[str],
    tool_a_frame: pd.DataFrame,
    tool_b_frame: pd.DataFrame | None = None,
    benchmark_tickers: tuple[str, ...] = ("GDX", "GDXJ"),
    top_n: int = 3,
    max_beta_diff: float = 0.35,
) -> dict[str, list[ProxyMatch]]:
    """Map non-optionable tickers to optionable down-beta-similar proxies."""

    tool_a_indexed = _indexed_by_ticker(tool_a_frame)
    tool_b_indexed = _indexed_by_ticker(tool_b_frame) if tool_b_frame is not None else {}
    optionable = [ticker.upper() for ticker in optionable_tickers]
    result: dict[str, list[ProxyMatch]] = {}
    for target in [ticker.upper() for ticker in non_optionable_tickers]:
        target_row = tool_a_indexed.get(target)
        target_beta = _row_float(target_row, "down_beta_core")
        matches = [
            match
            for proxy in optionable
            if proxy != target
            for match in [
                _optionable_match(
                    target=target,
                    proxy=proxy,
                    target_beta=target_beta,
                    proxy_tool_a_row=tool_a_indexed.get(proxy),
                    proxy_tool_b_row=tool_b_indexed.get(proxy),
                    max_beta_diff=max_beta_diff,
                )
            ]
            if match is not None
        ]
        matches.sort(
            key=lambda item: (
                item.down_beta_diff is None,
                item.down_beta_diff if item.down_beta_diff is not None else float("inf"),
                item.proxy_ticker,
            )
        )
        selected = matches[:top_n]
        if len(selected) < top_n:
            selected.extend(
                _benchmark_match(
                    target=target,
                    benchmark=benchmark,
                    target_beta=target_beta,
                )
                for benchmark in benchmark_tickers[: top_n - len(selected)]
            )
        result[target] = selected
    return result


def _optionable_match(
    *,
    target: str,
    proxy: str,
    target_beta: float | None,
    proxy_tool_a_row: pd.Series | None,
    proxy_tool_b_row: pd.Series | None,
    max_beta_diff: float,
) -> ProxyMatch | None:
    proxy_beta = _row_float(proxy_tool_a_row, "down_beta_core")
    if target_beta is None or proxy_beta is None:
        return None
    beta_diff = abs(target_beta - proxy_beta)
    if beta_diff <= max_beta_diff:
        basis_label = "lower_basis_risk"
    else:
        basis_label = "elevated_basis_risk"
    return ProxyMatch(
        target_ticker=target,
        proxy_ticker=proxy,
        proxy_type="optionable_miner",
        target_down_beta=target_beta,
        proxy_down_beta=proxy_beta,
        down_beta_diff=beta_diff,
        tool_a_confidence=_row_float(proxy_tool_a_row, "confidence_score"),
        tool_b_verdict=_row_string(proxy_tool_b_row, "screening_verdict"),
        basis_risk_label=basis_label,
        reason="Closest optionable miner by Tool A down-beta.",
    )


def _benchmark_match(
    *,
    target: str,
    benchmark: str,
    target_beta: float | None,
) -> ProxyMatch:
    return ProxyMatch(
        target_ticker=target,
        proxy_ticker=benchmark,
        proxy_type="sector_etf",
        target_down_beta=target_beta,
        proxy_down_beta=None,
        down_beta_diff=None,
        tool_a_confidence=None,
        tool_b_verdict=None,
        basis_risk_label="high_basis_risk_sector_proxy",
        reason="Sector ETF fallback; useful only when miner-specific proxy quality is poor.",
    )


def _indexed_by_ticker(frame: pd.DataFrame) -> dict[str, pd.Series]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    result: dict[str, pd.Series] = {}
    for _, row in frame.iterrows():
        ticker = row.get("ticker")
        if isinstance(ticker, str) and ticker.strip():
            result[ticker.strip().upper()] = row
    return result


def _row_float(row: pd.Series | None, column: str) -> float | None:
    if row is None or column not in row.index:
        return None
    value = pd.to_numeric(row[column], errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def _row_string(row: pd.Series | None, column: str) -> str | None:
    if row is None or column not in row.index or pd.isna(row[column]):
        return None
    return str(row[column])
