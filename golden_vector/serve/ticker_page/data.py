"""M2 read-only spine: manifest-first loading + per-ticker view selection.

``load_ticker_page_data`` resolves the five persisted artifacts through the
validated ``ticker_page_state`` loaders (manifest-first, schema-checked,
explicit MISSING/STALE/CORRUPT states). ``TickerPageData`` then only *selects*
rows for one ticker — never computes, never coalesces.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.common.strings import clean_string
from golden_vector.app.ticker_page_state import (
    STATUS_CORRUPT,
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

    def research_rows(self, ticker: str, *, kind: str) -> pd.DataFrame:
        """Published research-series rows for one ticker and kind.

        Only ``kind_status == "OK"`` rows are data: the producer writes a single
        marker row (with a reason) for a kind it could not build, and a marker
        must never be drawn as an observation.
        """
        rows = _ticker_rows(self.research_series.frame, ticker)
        if rows.empty or "kind" not in rows.columns:
            return rows.iloc[0:0]
        kind_rows = rows.loc[rows["kind"].eq(kind)]
        if kind_rows.empty or "kind_status" not in kind_rows.columns:
            return kind_rows
        return kind_rows.loc[kind_rows["kind_status"].eq("OK")]

    def research_kind_state(self, ticker: str, *, kind: str) -> tuple[str, str]:
        """``(status, reason)`` for one ticker/kind — selection, never inference.

        The artifact's own state wins when it is not OK (a MISSING artifact
        cannot have per-kind rows). Otherwise the persisted ``kind_status`` /
        ``kind_reason`` are reported verbatim.
        """
        if self.research_series.status != "OK":
            return (
                self.research_series.status,
                self.research_series.reason or "research series unavailable",
            )
        rows = _ticker_rows(self.research_series.frame, ticker)
        if rows.empty or "kind" not in rows.columns:
            return ("MISSING", "no research series published for this ticker")
        kind_rows = rows.loc[rows["kind"].eq(kind)]
        if kind_rows.empty:
            return ("MISSING", f"no {kind} rows published for this ticker")
        first = kind_rows.iloc[0]
        # Parquet nullable-string columns return ``pd.NA`` for missing cells.
        # Never use Python truthiness on those scalars: ``bool(pd.NA)`` raises.
        status = clean_string(first.get("kind_status")) or "MISSING"
        reason = clean_string(first.get("kind_reason")) or ""
        if status == "OK":
            return ("OK", reason)
        return (status, reason or f"{kind} series unavailable")

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


#: Bounded generation cache (plan §5.4, Codex 2026-08-12 P2). The five loaders
#: are manifest-first: everything they read is resolved through the model-state
#: pointer, so an unchanged pointer stat means an unchanged generation. Alias
#: refreshes without a pointer publish deliberately do NOT serve (standalone
#: runs are non-authoritative), so the pointer stat is the complete identity.
#: Two entries give hysteresis across a publish flip; the lock is cheap on the
#: single-threaded local server and correct if that ever changes.
_DATA_CACHE: OrderedDict[tuple[object, ...], TickerPageData] = OrderedDict()
_DATA_CACHE_MAX = 2
_DATA_CACHE_LOCK = threading.Lock()


def _generation_key(paths: ProjectPaths) -> tuple[object, ...]:
    pointer = paths.latest_model_state_manifest_path
    try:
        stat = pointer.stat()
    except OSError:
        # No manifest yet (or unreadable): key on absence so the first publish
        # invalidates. The loaders themselves report the honest pending state.
        return (str(pointer), None)
    return (str(pointer), stat.st_mtime_ns, stat.st_size)


def load_ticker_page_data(paths: ProjectPaths) -> TickerPageData:
    key = _generation_key(paths)
    with _DATA_CACHE_LOCK:
        cached = _DATA_CACHE.get(key)
        if cached is not None:
            _DATA_CACHE.move_to_end(key)
            return cached
    loaded = TickerPageData(
        gold_response=load_gold_response(paths),
        percentiles=load_score_percentiles(paths),
        performance=load_performance_series(paths),
        research_series=load_research_series(paths),
        fx_attribution=load_fx_attribution(paths),
    )
    states = (
        loaded.gold_response,
        loaded.percentiles,
        loaded.performance,
        loaded.research_series,
        loaded.fx_attribution,
    )
    # An OSError can be transient while the manifest pointer stat remains the
    # same. Do not turn that one failed read into a permanent process-level
    # CORRUPT state; the next request must be able to recover.
    if all(state.status != STATUS_CORRUPT for state in states):
        with _DATA_CACHE_LOCK:
            _DATA_CACHE[key] = loaded
            while len(_DATA_CACHE) > _DATA_CACHE_MAX:
                _DATA_CACHE.popitem(last=False)
    return loaded


def _ticker_rows(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(columns=getattr(frame, "columns", []))
    return frame.loc[frame["ticker"].eq(str(ticker).upper())]
