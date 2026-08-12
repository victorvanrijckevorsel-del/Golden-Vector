"""M2 read-only spine: manifest-first loading + per-ticker view selection.

``load_ticker_page_data`` resolves the five persisted artifacts through the
validated ``ticker_page_state`` loaders (manifest-first, schema-checked,
explicit MISSING/STALE/CORRUPT states). ``TickerPageData`` then only *selects*
rows for one ticker — never computes, never coalesces.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.ticker_page_state import (
    TickerPageArtifactState,
    load_fx_attribution,
    load_gold_response,
    load_performance_series,
    load_research_series,
    load_score_percentiles,
)


@dataclass(frozen=True)
class TickerPageData:
    """The five artifact states, loaded once per request path."""

    gold_response: TickerPageArtifactState
    percentiles: TickerPageArtifactState
    performance: TickerPageArtifactState
    research_series: TickerPageArtifactState
    fx_attribution: TickerPageArtifactState

    def performance_rows(self, ticker: str) -> pd.DataFrame:
        return _ticker_rows(self.performance.frame, ticker)

    def fx_attribution_rows(self, ticker: str) -> pd.DataFrame:
        return _ticker_rows(self.fx_attribution.frame, ticker)

    def gold_response_row(
        self, ticker: str, *, finance_source: str
    ) -> pd.Series | None:
        """The one gold-response row for (ticker, finance_source), or ``None``.

        Selection only — the key is (ticker, finance_source) by contract, so a
        miss is a genuine absence and is reported as one, never back-filled
        from the other source.
        """
        rows = _ticker_rows(self.gold_response.frame, ticker)
        if rows.empty or "finance_source" not in rows.columns:
            return None
        match = rows.loc[rows["finance_source"].eq(finance_source)]
        if match.empty:
            return None
        return match.iloc[0]

    def percentile_rows(self, ticker: str, *, finance_source: str) -> pd.DataFrame:
        rows = _ticker_rows(self.percentiles.frame, ticker)
        if rows.empty or "finance_source" not in rows.columns:
            return rows
        return rows.loc[rows["finance_source"].eq(finance_source)]

    def metric_row(
        self, ticker: str, *, metric_key: str, finance_source: str
    ) -> pd.Series | None:
        rows = self.percentile_rows(ticker, finance_source=finance_source)
        if rows.empty or "metric_key" not in rows.columns:
            return None
        match = rows.loc[rows["metric_key"].eq(metric_key)]
        if match.empty:
            return None
        return match.iloc[0]

    def metric_peers(self, *, metric_key: str, finance_source: str) -> pd.DataFrame:
        """All tickers' rows for one metric — for peer strips/scatters.

        Only rank-eligible rows carry percentiles (the model layer guarantees
        it); the caller filters on the columns it renders.
        """
        frame = self.percentiles.frame
        if frame.empty or "metric_key" not in frame.columns:
            return frame
        return frame.loc[
            frame["metric_key"].eq(metric_key)
            & frame["finance_source"].eq(finance_source)
        ]


def load_ticker_page_data(paths: ProjectPaths) -> TickerPageData:
    return TickerPageData(
        gold_response=load_gold_response(paths),
        percentiles=load_score_percentiles(paths),
        performance=load_performance_series(paths),
        research_series=load_research_series(paths),
        fx_attribution=load_fx_attribution(paths),
    )


def _ticker_rows(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=getattr(frame, "columns", []))
    return frame.loc[frame["ticker"].eq(str(ticker).upper())]
