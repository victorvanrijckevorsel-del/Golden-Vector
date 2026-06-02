"""Down-beta similarity proxy mapping for non-optionable holdings."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.hedge._helpers import (
    row_float as _row_float,
    row_string as _row_string,
    rows_by_ticker_series,
)


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
    low_basis_max_beta_diff: float = 0.10,
    medium_basis_max_beta_diff: float = 0.30,
    low_basis_min_confidence: float = 0.70,
) -> dict[str, list[ProxyMatch]]:
    """Map non-optionable tickers to optionable down-beta-similar proxies."""

    tool_a_indexed = rows_by_ticker_series(tool_a_frame, strip=True, require_string=True)
    tool_b_indexed = (
        rows_by_ticker_series(tool_b_frame, strip=True, require_string=True)
        if tool_b_frame is not None
        else {}
    )
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
                    target_tool_a_row=target_row,
                    target_beta=target_beta,
                    proxy_tool_a_row=tool_a_indexed.get(proxy),
                    proxy_tool_b_row=tool_b_indexed.get(proxy),
                    max_beta_diff=max_beta_diff,
                    low_basis_max_beta_diff=low_basis_max_beta_diff,
                    medium_basis_max_beta_diff=medium_basis_max_beta_diff,
                    low_basis_min_confidence=low_basis_min_confidence,
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
    target_tool_a_row: pd.Series | None,
    target_beta: float | None,
    proxy_tool_a_row: pd.Series | None,
    proxy_tool_b_row: pd.Series | None,
    max_beta_diff: float,
    low_basis_max_beta_diff: float,
    medium_basis_max_beta_diff: float,
    low_basis_min_confidence: float,
) -> ProxyMatch | None:
    proxy_beta = _row_float(proxy_tool_a_row, "down_beta_core")
    if target_beta is None or proxy_beta is None:
        return None
    beta_diff = abs(target_beta - proxy_beta)
    target_confidence = _row_float(target_tool_a_row, "confidence_score")
    proxy_confidence = _row_float(proxy_tool_a_row, "confidence_score")
    basis_label = _basis_risk_label(
        beta_diff=beta_diff,
        target_confidence=target_confidence,
        proxy_confidence=proxy_confidence,
        max_beta_diff=max_beta_diff,
        low_basis_max_beta_diff=low_basis_max_beta_diff,
        medium_basis_max_beta_diff=medium_basis_max_beta_diff,
        low_basis_min_confidence=low_basis_min_confidence,
    )
    return ProxyMatch(
        target_ticker=target,
        proxy_ticker=proxy,
        proxy_type="optionable_miner",
        target_down_beta=target_beta,
        proxy_down_beta=proxy_beta,
        down_beta_diff=beta_diff,
        tool_a_confidence=proxy_confidence,
        tool_b_verdict=_row_string(proxy_tool_b_row, "screening_verdict"),
        basis_risk_label=basis_label,
        reason="Closest optionable miner by Tool A down-beta.",
    )


def _basis_risk_label(
    *,
    beta_diff: float,
    target_confidence: float | None,
    proxy_confidence: float | None,
    max_beta_diff: float,
    low_basis_max_beta_diff: float,
    medium_basis_max_beta_diff: float,
    low_basis_min_confidence: float,
) -> str:
    medium_limit = min(medium_basis_max_beta_diff, max_beta_diff)
    if (
        beta_diff <= low_basis_max_beta_diff
        and _confidence_meets(target_confidence, low_basis_min_confidence)
        and _confidence_meets(proxy_confidence, low_basis_min_confidence)
    ):
        return "low_basis_risk"
    if beta_diff <= medium_limit and (
        _confidence_meets(target_confidence, low_basis_min_confidence)
        or _confidence_meets(proxy_confidence, low_basis_min_confidence)
    ):
        return "medium_basis_risk"
    return "high_basis_risk"


def _confidence_meets(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


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


