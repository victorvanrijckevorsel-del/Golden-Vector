"""Portfolio reconciliation status scaffolding."""

from __future__ import annotations

import pandas as pd

from golden_vector.portfolio.models import PORTFOLIO_SCHEMA_VERSION

RECONCILIATION_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "source_export_sha256",
    "portfolio_source_version",
    "stage",
    "status",
    "status_reason",
    "is_hard_gate",
    "broker_statement_date",
    "gv_price_date",
    "account_tolerance_usd",
    "account_tolerance_bps",
]


def build_manual_reconciliation_frame(
    *,
    source_run_id: str,
    snapshot_refresh_run_id: str,
    source_hash: str | None,
    portfolio_source_version: str,
    gv_price_date: str | None,
) -> pd.DataFrame:
    rows = [
        {
            "schema_version": PORTFOLIO_SCHEMA_VERSION,
            "source_run_id": source_run_id,
            "snapshot_refresh_run_id": snapshot_refresh_run_id,
            "source_export_sha256": source_hash,
            "portfolio_source_version": portfolio_source_version,
            "stage": "broker_totals",
            "status": "MANUAL_ENTRY_NO_BROKER_TOTALS",
            "status_reason": (
                "Manual M1 lots do not include broker-statement NAV, cash, or "
                "broker market values. Broker-total reconciliation starts with "
                "the later import milestone."
            ),
            "is_hard_gate": False,
            "broker_statement_date": None,
            "gv_price_date": gv_price_date,
            "account_tolerance_usd": 2.0,
            "account_tolerance_bps": 5.0,
        },
        {
            "schema_version": PORTFOLIO_SCHEMA_VERSION,
            "source_run_id": source_run_id,
            "snapshot_refresh_run_id": snapshot_refresh_run_id,
            "source_export_sha256": source_hash,
            "portfolio_source_version": portfolio_source_version,
            "stage": "gv_price_drift",
            "status": "MANUAL_ENTRY_NO_BROKER_PRICES",
            "status_reason": (
                "Manual M1 lots have buy prices and current Golden Vector "
                "snapshot prices, but no broker current prices to compare."
            ),
            "is_hard_gate": False,
            "broker_statement_date": None,
            "gv_price_date": gv_price_date,
            "account_tolerance_usd": 2.0,
            "account_tolerance_bps": 5.0,
        },
    ]
    frame = pd.DataFrame(rows, columns=RECONCILIATION_COLUMNS)
    frame.attrs["schema_version"] = PORTFOLIO_SCHEMA_VERSION
    frame.attrs["source_run_id"] = source_run_id
    frame.attrs["snapshot_refresh_run_id"] = snapshot_refresh_run_id
    return frame
