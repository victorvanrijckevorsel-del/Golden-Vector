"""Fetch and standardize Yahoo options chains."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from time import perf_counter
from typing import Literal

import pandas as pd

from golden_vector.common.numeric import optional_float as _as_float
from golden_vector.features.options_chain import midpoint
from golden_vector.ingestion.yahoo_client import YahooClient

OPTIONS_STATUS_SUCCESS = "SUCCESS"
OPTIONS_STATUS_EMPTY = "EMPTY"
OPTIONS_STATUS_ERROR = "ERROR"
RAW_OPTIONS_COLUMNS = [
    "ticker",
    "as_of_date",
    "expiration",
    "option_type",
    "strike",
    "bid",
    "ask",
    "mid",
    "last_price",
    "volume",
    "open_interest",
    "implied_volatility",
    "underlying_price",
    "moneyness",
    "days_to_expiry",
]


@dataclass(frozen=True)
class OptionsChainResult:
    ticker: str
    as_of_date: date
    status: str
    frame: pd.DataFrame
    message: str | None = None
    collection_stats: dict[str, object] = field(default_factory=dict)

    @property
    def options_available(self) -> bool:
        return self.status == OPTIONS_STATUS_SUCCESS and not self.frame.empty


def fetch_options_chain(
    *,
    ticker: str,
    as_of_date: date,
    yahoo_client: YahooClient,
    expiry_fetch_mode: Literal["all", "targeted"] = "all",
    target_dte_bands: dict[int, list[int]] | None = None,
) -> OptionsChainResult:
    """Fetch all available Yahoo option expirations for one ticker."""

    started_at = perf_counter()
    all_expirations: list[str] = []
    selected_expirations: list[str] = []
    expiration_errors: list[dict[str, str]] = []
    try:
        all_expirations = yahoo_client.fetch_options_expirations(ticker)
        selected_expirations = _selected_expirations(
            all_expirations,
            as_of_date=as_of_date,
            expiry_fetch_mode=expiry_fetch_mode,
            target_dte_bands=target_dte_bands,
        )
        if not all_expirations:
            return OptionsChainResult(
                ticker=ticker,
                as_of_date=as_of_date,
                status=OPTIONS_STATUS_EMPTY,
                frame=_empty_options_frame(),
                message="No listed options returned by Yahoo.",
                collection_stats=_collection_stats(
                    ticker=ticker,
                    status=OPTIONS_STATUS_EMPTY,
                    started_at=started_at,
                    expiry_fetch_mode=expiry_fetch_mode,
                    all_expirations=all_expirations,
                    selected_expirations=selected_expirations,
                    expiration_errors=expiration_errors,
                ),
            )
        if not selected_expirations:
            return OptionsChainResult(
                ticker=ticker,
                as_of_date=as_of_date,
                status=OPTIONS_STATUS_EMPTY,
                frame=_empty_options_frame(),
                message="No listed options matched the configured expiry fetch mode.",
                collection_stats=_collection_stats(
                    ticker=ticker,
                    status=OPTIONS_STATUS_EMPTY,
                    started_at=started_at,
                    expiry_fetch_mode=expiry_fetch_mode,
                    all_expirations=all_expirations,
                    selected_expirations=selected_expirations,
                    expiration_errors=expiration_errors,
                ),
            )

        underlying_price = _extract_underlying_price(yahoo_client.fetch_fast_info(ticker))
        if underlying_price is None:
            return OptionsChainResult(
                ticker=ticker,
                as_of_date=as_of_date,
                status=OPTIONS_STATUS_ERROR,
                frame=_empty_options_frame(),
                message="Could not determine underlying price.",
                collection_stats=_collection_stats(
                    ticker=ticker,
                    status=OPTIONS_STATUS_ERROR,
                    started_at=started_at,
                    expiry_fetch_mode=expiry_fetch_mode,
                    all_expirations=all_expirations,
                    selected_expirations=selected_expirations,
                    expiration_errors=expiration_errors,
                ),
            )

        frames: list[pd.DataFrame] = []
        for expiration in selected_expirations:
            try:
                chain = yahoo_client.fetch_option_chain(ticker, expiration)
            except Exception as exc:  # noqa: BLE001 - one bad expiry should not hide the rest.
                expiration_errors.append(
                    {"expiration": str(expiration), "message": str(exc)}
                )
                continue
            frames.append(
                _standardize_option_side(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    expiration=expiration,
                    option_type="P",
                    frame=pd.DataFrame(chain.puts),
                    underlying_price=underlying_price,
                )
            )
            frames.append(
                _standardize_option_side(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    expiration=expiration,
                    option_type="C",
                    frame=pd.DataFrame(chain.calls),
                    underlying_price=underlying_price,
                )
            )

        frame = pd.concat(frames, ignore_index=True) if frames else _empty_options_frame()
        if frame.empty:
            message = "Yahoo returned expirations but no option rows."
            if expiration_errors:
                message = (
                    "Yahoo returned no usable option rows; "
                    f"{len(expiration_errors)} expiration fetches failed."
                )
            return OptionsChainResult(
                ticker=ticker,
                as_of_date=as_of_date,
                status=OPTIONS_STATUS_ERROR if expiration_errors else OPTIONS_STATUS_EMPTY,
                frame=_empty_options_frame(),
                message=message,
                collection_stats=_collection_stats(
                    ticker=ticker,
                    status=OPTIONS_STATUS_ERROR if expiration_errors else OPTIONS_STATUS_EMPTY,
                    started_at=started_at,
                    expiry_fetch_mode=expiry_fetch_mode,
                    all_expirations=all_expirations,
                    selected_expirations=selected_expirations,
                    expiration_errors=expiration_errors,
                ),
            )
        message = None
        if expiration_errors:
            message = f"{len(expiration_errors)} expiration fetches failed; remaining rows were used."
        return OptionsChainResult(
            ticker=ticker,
            as_of_date=as_of_date,
            status=OPTIONS_STATUS_SUCCESS,
            frame=frame[RAW_OPTIONS_COLUMNS].reset_index(drop=True),
            message=message,
            collection_stats=_collection_stats(
                ticker=ticker,
                status=OPTIONS_STATUS_SUCCESS,
                started_at=started_at,
                expiry_fetch_mode=expiry_fetch_mode,
                all_expirations=all_expirations,
                selected_expirations=selected_expirations,
                expiration_errors=expiration_errors,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - per-ticker options fetch is best-effort.
        return OptionsChainResult(
            ticker=ticker,
            as_of_date=as_of_date,
            status=OPTIONS_STATUS_ERROR,
            frame=_empty_options_frame(),
            message=str(exc),
            collection_stats=_collection_stats(
                ticker=ticker,
                status=OPTIONS_STATUS_ERROR,
                started_at=started_at,
                expiry_fetch_mode=expiry_fetch_mode,
                all_expirations=all_expirations,
                selected_expirations=selected_expirations,
                expiration_errors=expiration_errors,
                top_level_error=str(exc),
            ),
        )


def _standardize_option_side(
    *,
    ticker: str,
    as_of_date: date,
    expiration: str,
    option_type: Literal["P", "C"],
    frame: pd.DataFrame,
    underlying_price: float,
) -> pd.DataFrame:
    if frame.empty:
        return _empty_options_frame()

    expiration_date = pd.to_datetime(expiration).date()
    standardized = pd.DataFrame(
        {
            "ticker": ticker,
            "as_of_date": as_of_date.isoformat(),
            "expiration": expiration_date.isoformat(),
            "option_type": option_type,
            "strike": pd.to_numeric(frame.get("strike"), errors="coerce"),
            "bid": pd.to_numeric(frame.get("bid"), errors="coerce"),
            "ask": pd.to_numeric(frame.get("ask"), errors="coerce"),
            "last_price": pd.to_numeric(frame.get("lastPrice"), errors="coerce"),
            "volume": pd.to_numeric(frame.get("volume"), errors="coerce"),
            "open_interest": pd.to_numeric(frame.get("openInterest"), errors="coerce"),
            "implied_volatility": pd.to_numeric(frame.get("impliedVolatility"), errors="coerce"),
            "underlying_price": float(underlying_price),
        }
    )
    standardized["mid"] = [
        midpoint(bid, ask)
        for bid, ask in zip(standardized["bid"], standardized["ask"], strict=False)
    ]
    standardized["moneyness"] = standardized["strike"] / float(underlying_price)
    standardized["days_to_expiry"] = (expiration_date - as_of_date).days
    return standardized[RAW_OPTIONS_COLUMNS]


def _extract_underlying_price(fast_info: object) -> float | None:
    if not isinstance(fast_info, dict):
        return None
    for key in ("last_price", "lastPrice", "regularMarketPrice", "previousClose"):
        value = _as_float(fast_info.get(key))
        if value is not None and value > 0:
            return value
    return None


def _selected_expirations(
    expirations: list[str],
    *,
    as_of_date: date,
    expiry_fetch_mode: Literal["all", "targeted"],
    target_dte_bands: dict[int, list[int]] | None,
) -> list[str]:
    if expiry_fetch_mode == "all" or not target_dte_bands:
        return list(expirations)
    selected: list[str] = []
    for expiration in expirations:
        days_to_expiry = _days_to_expiry(expiration, as_of_date=as_of_date)
        if days_to_expiry is None:
            continue
        if any(
            int(band[0]) <= days_to_expiry <= int(band[1])
            for band in target_dte_bands.values()
            if len(band) == 2
        ):
            selected.append(expiration)
    return selected


def _days_to_expiry(expiration: str, *, as_of_date: date) -> int | None:
    try:
        return (pd.to_datetime(expiration).date() - as_of_date).days
    except Exception:
        return None


def _collection_stats(
    *,
    ticker: str,
    status: str,
    started_at: float,
    expiry_fetch_mode: str,
    all_expirations: list[str],
    selected_expirations: list[str],
    expiration_errors: list[dict[str, str]],
    top_level_error: str | None = None,
) -> dict[str, object]:
    stats: dict[str, object] = {
        "ticker": ticker,
        "status": status,
        "duration_seconds": round(perf_counter() - started_at, 3),
        "expiry_fetch_mode": expiry_fetch_mode,
        "expiration_count_available": len(all_expirations),
        "expiration_count_selected": len(selected_expirations),
        "expiration_error_count": len(expiration_errors),
        "expiration_errors": expiration_errors[:10],
    }
    if top_level_error:
        stats["message"] = top_level_error
    return stats


def _empty_options_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=RAW_OPTIONS_COLUMNS)
