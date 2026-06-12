"""Manual holdings loader for hedge-readiness reports."""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from golden_vector.app.paths import ProjectPaths
from golden_vector.common.numeric import require_finite


@dataclass(frozen=True)
class Holding:
    ticker: str
    shares: float | None = None
    dollar_exposure: float | None = None

    def exposure_usd(self, *, share_price: float | None) -> float | None:
        if self.dollar_exposure is not None:
            return self.dollar_exposure
        if self.shares is None or share_price is None or share_price <= 0:
            return None
        return self.shares * share_price


def load_holdings(paths: ProjectPaths) -> list[Holding]:
    """Read holdings.yaml, returning an empty list when no file exists."""

    path = paths.holdings_path
    if not path.exists():
        return []

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload = {} if loaded is None else loaded
    if not isinstance(payload, dict):
        raise ValueError("holdings.yaml must contain a mapping.")
    raw_holdings = payload.get("holdings", [])
    if raw_holdings is None:
        return []
    if not isinstance(raw_holdings, list):
        raise ValueError("holdings.yaml field 'holdings' must be a list.")

    holdings = [
        _parse_holding(item, index=index)
        for index, item in enumerate(raw_holdings, start=1)
    ]
    seen: set[str] = set()
    for holding in holdings:
        if holding.ticker in seen:
            raise ValueError(f"holdings.yaml contains duplicate ticker: {holding.ticker}")
        seen.add(holding.ticker)
    return holdings


def _parse_holding(item: object, *, index: int) -> Holding:
    if not isinstance(item, dict):
        raise ValueError(f"holding #{index} must be a mapping.")

    ticker = item.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError(f"holding #{index} must include a non-empty ticker.")

    shares = _optional_positive_float(item.get("shares"), field="shares", index=index)
    dollar_exposure = _optional_positive_float(
        item.get("dollar_exposure"),
        field="dollar_exposure",
        index=index,
    )
    if (shares is None) == (dollar_exposure is None):
        raise ValueError(
            f"holding #{index} must set exactly one of shares or dollar_exposure."
        )

    return Holding(
        ticker=ticker.strip().upper(),
        shares=shares,
        dollar_exposure=dollar_exposure,
    )


def _optional_positive_float(value: object, *, field: str, index: int) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"holding #{index} field '{field}' must be numeric.") from exc
    require_finite(numeric, field=f"holding #{index} field '{field}'")
    if numeric <= 0:
        raise ValueError(f"holding #{index} field '{field}' must be positive.")
    return numeric
