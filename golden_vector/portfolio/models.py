"""Typed portfolio models for manual lots and persisted M1 artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from golden_vector.contracts.config_models import SUPPORTED_CURRENCIES

PORTFOLIO_SCHEMA_VERSION = 5
PORTFOLIO_STORE_SCHEMA_VERSION = 2
ALLOWED_PORTFOLIO_CURRENCIES = tuple(sorted(SUPPORTED_CURRENCIES))
MAX_LOT_NOTE_LENGTH = 500


class PortfolioError(ValueError):
    """Base class for portfolio user-facing validation and data errors."""


class PortfolioValidationError(PortfolioError):
    """Raised when a manual portfolio input is invalid."""


class PortfolioStaleSchemaError(PortfolioError):
    """Raised when a persisted portfolio artifact is from an old schema."""


@dataclass(frozen=True)
class PortfolioLot:
    id: str
    ticker: str
    shares: float
    buy_price: float
    buy_currency: str
    buy_date: date
    note: str | None
    created_at: datetime
    updated_at: datetime
    # --- schema v2 (expand phase) ---
    # The cost basis can be recorded in a different currency than the ticker's
    # quote currency (e.g. a GBP broker cost on an AUD-quoted stock). These are
    # populated at construction and by the v1->v2 read-migration; the legacy
    # buy_price/buy_currency stay until every consumer is migrated, then drop.
    cost_currency: str | None = None
    cost_basis_total: float | None = None
    raw_broker_symbol: str | None = None
    source_name: str = "manual"
    source_file: str | None = None
    cost_basis_as_of_date: date | None = None

    @property
    def cost_local(self) -> float:
        return self.shares * self.buy_price

    @property
    def cost_per_share(self) -> float:
        if self.cost_basis_total is not None and self.shares:
            return self.cost_basis_total / self.shares
        return self.buy_price


@dataclass(frozen=True)
class LotInput:
    ticker: str
    shares: float
    buy_price: float
    buy_currency: str
    buy_date: date
    note: str | None = None


@dataclass(frozen=True)
class TickerInfo:
    ticker: str
    currency: str
    company: str | None = None
    active: bool = True


@dataclass(frozen=True)
class LineValuation:
    lot: PortfolioLot
    company: str | None
    current_price_local: float | None
    current_price_usd: float | None
    fx_rate_to_usd: float | None
    snapshot_date: str | None
    value_local: float | None
    value_usd: float | None
    cost_local: float
    cost_usd_at_current_fx: float | None
    pnl_local: float | None
    pnl_fraction_local: float | None
    pnl_usd_at_current_fx: float | None
    status: str
    status_reason: str | None
    price_scale_factor: float
    minor_unit_adjusted: bool
    # --- schema v2: cost-currency leg + backend GBP presentation ---
    # quote_currency is the ticker's trading currency; cost_currency is the
    # currency the cost basis is recorded in. cost_usd_at_current_fx now uses the
    # COST currency's FX. GBP fields are backend-computed (value_usd / GBPUSD).
    # fx_issues names which FX leg degraded (quote_fx / cost_fx / gbp_presentation_fx).
    quote_currency: str | None = None
    cost_currency: str | None = None
    value_gbp: float | None = None
    cost_gbp_at_current_fx: float | None = None
    pnl_gbp_at_current_fx: float | None = None
    fx_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortfolioBuildResult:
    source_run_id: str
    lines_count: int
    positions_count: int
    summary_status: str
