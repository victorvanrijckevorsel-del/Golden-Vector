"""Atomic JSON store for manually entered portfolio lots."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import uuid4

from golden_vector.app.paths import ProjectPaths
from golden_vector.common.files import atomic_write_text
from golden_vector.common.strings import clean_string, normalize_ticker
from golden_vector.portfolio.models import (
    ALLOWED_PORTFOLIO_CURRENCIES,
    LotInput,
    MAX_LOT_NOTE_LENGTH,
    PortfolioLot,
    PortfolioValidationError,
    PORTFOLIO_STORE_SCHEMA_VERSION,
    TickerInfo,
)


def portfolio_store_exists(paths: ProjectPaths) -> bool:
    return paths.manual_portfolio_lots_path.exists()


def load_lots(paths: ProjectPaths) -> list[PortfolioLot]:
    path = paths.manual_portfolio_lots_path
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PortfolioValidationError(f"Portfolio store is not valid JSON: {exc}") from exc
    return _parse_store_payload(payload)


def add_lot(
    paths: ProjectPaths,
    raw: dict[str, object],
    *,
    ticker_info: dict[str, TickerInfo],
) -> PortfolioLot:
    lot_input = validate_lot_input(raw, ticker_info=ticker_info)
    now = _utc_now()
    lot = PortfolioLot(
        id=_new_lot_id(),
        ticker=lot_input.ticker,
        shares=lot_input.shares,
        buy_price=lot_input.buy_price,
        buy_currency=lot_input.buy_currency,
        buy_date=lot_input.buy_date,
        note=lot_input.note,
        created_at=now,
        updated_at=now,
    )
    lots = [*load_lots(paths), lot]
    _write_lots(paths, lots)
    return lot


def edit_lot(
    paths: ProjectPaths,
    lot_id: str,
    raw: dict[str, object],
    *,
    ticker_info: dict[str, TickerInfo],
) -> PortfolioLot:
    clean_id = _clean_lot_id(lot_id)
    lot_input = validate_lot_input(raw, ticker_info=ticker_info)
    lots = load_lots(paths)
    edited: PortfolioLot | None = None
    updated_lots: list[PortfolioLot] = []
    for lot in lots:
        if lot.id != clean_id:
            updated_lots.append(lot)
            continue
        edited = PortfolioLot(
            id=lot.id,
            ticker=lot_input.ticker,
            shares=lot_input.shares,
            buy_price=lot_input.buy_price,
            buy_currency=lot_input.buy_currency,
            buy_date=lot_input.buy_date,
            note=lot_input.note,
            created_at=lot.created_at,
            updated_at=_utc_now(),
        )
        updated_lots.append(edited)
    if edited is None:
        raise PortfolioValidationError("Position lot not found.")
    _write_lots(paths, updated_lots)
    return edited


def delete_lot(paths: ProjectPaths, lot_id: str) -> None:
    clean_id = _clean_lot_id(lot_id)
    lots = load_lots(paths)
    updated_lots = [lot for lot in lots if lot.id != clean_id]
    if len(updated_lots) == len(lots):
        raise PortfolioValidationError("Position lot not found.")
    _write_lots(paths, updated_lots)


def validate_lot_input(
    raw: dict[str, object],
    *,
    ticker_info: dict[str, TickerInfo],
    today: date | None = None,
) -> LotInput:
    ticker = normalize_ticker(raw.get("ticker"))
    if not ticker:
        raise PortfolioValidationError("Choose a ticker.")
    info = ticker_info.get(ticker)
    if info is None or not info.active:
        raise PortfolioValidationError(f"{ticker} is not in the active universe. Add it to the universe first.")

    shares = _positive_float(raw.get("shares"), field="shares")
    buy_price = _positive_float(raw.get("buy_price"), field="buy price")
    buy_currency = _clean_currency(raw.get("buy_currency")) or info.currency
    if buy_currency not in ALLOWED_PORTFOLIO_CURRENCIES:
        supported = ", ".join(ALLOWED_PORTFOLIO_CURRENCIES)
        raise PortfolioValidationError(f"Currency must be one of: {supported}.")
    if buy_currency != info.currency:
        raise PortfolioValidationError(
            f"M1 uses the ticker's configured currency ({info.currency}) for {ticker}."
        )
    buy_date = _parse_buy_date(raw.get("buy_date"))
    today = today or date.today()
    if buy_date > today:
        raise PortfolioValidationError("Buy date cannot be in the future.")
    note = clean_string(raw.get("note"))
    if note is not None and len(note) > MAX_LOT_NOTE_LENGTH:
        raise PortfolioValidationError(
            f"Note must be {MAX_LOT_NOTE_LENGTH} characters or fewer."
        )
    return LotInput(
        ticker=ticker,
        shares=shares,
        buy_price=buy_price,
        buy_currency=buy_currency,
        buy_date=buy_date,
        note=note,
    )


def _parse_store_payload(payload: object) -> list[PortfolioLot]:
    if not isinstance(payload, dict):
        raise PortfolioValidationError("Portfolio store must contain a JSON object.")
    schema_version = payload.get("schema_version")
    if schema_version != PORTFOLIO_STORE_SCHEMA_VERSION:
        raise PortfolioValidationError(
            "Portfolio store schema is not supported. Export it before changing versions."
        )
    raw_lots = payload.get("lots", [])
    if not isinstance(raw_lots, list):
        raise PortfolioValidationError("Portfolio store field 'lots' must be a list.")
    return [_parse_lot(item, index=index) for index, item in enumerate(raw_lots, start=1)]


def _parse_lot(item: object, *, index: int) -> PortfolioLot:
    if not isinstance(item, dict):
        raise PortfolioValidationError(f"Portfolio lot #{index} must be an object.")
    return PortfolioLot(
        id=_clean_lot_id(item.get("id")),
        ticker=normalize_ticker(item.get("ticker")) or _raise_invalid_lot(index, "ticker"),
        shares=_positive_float(item.get("shares"), field=f"lot #{index} shares"),
        buy_price=_positive_float(item.get("buy_price"), field=f"lot #{index} buy price"),
        buy_currency=_clean_currency(item.get("buy_currency")),
        buy_date=_parse_buy_date(item.get("buy_date")),
        note=clean_string(item.get("note")),
        created_at=_parse_datetime(item.get("created_at"), field=f"lot #{index} created_at"),
        updated_at=_parse_datetime(item.get("updated_at"), field=f"lot #{index} updated_at"),
    )


def _write_lots(
    paths: ProjectPaths,
    lots: list[PortfolioLot],
) -> None:
    payload = {
        "schema_version": PORTFOLIO_STORE_SCHEMA_VERSION,
        "lots": [_serialize_lot(lot) for lot in lots],
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    atomic_write_text(paths.manual_portfolio_lots_path, serialized)


def _serialize_lot(lot: PortfolioLot) -> dict[str, object]:
    return {
        "id": lot.id,
        "ticker": lot.ticker,
        "shares": lot.shares,
        "buy_price": lot.buy_price,
        "buy_currency": lot.buy_currency,
        "buy_date": lot.buy_date.isoformat(),
        "note": lot.note,
        "created_at": lot.created_at.isoformat(),
        "updated_at": lot.updated_at.isoformat(),
    }


def _positive_float(value: object, *, field: str) -> float:
    try:
        numeric = float(str(value).strip())
    except (TypeError, ValueError, AttributeError) as exc:
        raise PortfolioValidationError(f"{field.title()} must be a number.") from exc
    if numeric <= 0:
        raise PortfolioValidationError(f"{field.title()} must be greater than zero.")
    return numeric


def _parse_buy_date(value: object) -> date:
    text = clean_string(value)
    if not text:
        raise PortfolioValidationError("Buy date is required.")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise PortfolioValidationError("Buy date must be a valid YYYY-MM-DD date.") from exc


def _parse_datetime(value: object, *, field: str) -> datetime:
    text = clean_string(value)
    if not text:
        raise PortfolioValidationError(f"{field} is required.")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PortfolioValidationError(f"{field} must be an ISO datetime.") from exc
    return parsed


def _clean_currency(value: object) -> str:
    text = clean_string(value)
    return text.upper() if text else ""


def _clean_lot_id(value: object) -> str:
    text = clean_string(value)
    if not text:
        raise PortfolioValidationError("Position lot id is required.")
    return text


def _new_lot_id() -> str:
    return f"lot_{uuid4().hex}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _raise_invalid_lot(index: int, field: str) -> str:
    raise PortfolioValidationError(f"Portfolio lot #{index} field '{field}' is invalid.")
