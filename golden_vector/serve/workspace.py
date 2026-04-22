"""Thin local workspace UI for Tool B manual inputs and latest outputs."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.manual_data import load_manual_screening_data
from golden_vector.screening.manual_store import (
    add_stock_note,
    upsert_company_input,
    upsert_reporting_calendar,
)


CompanyFieldSpec = tuple[str, str, str]
ReportingFieldSpec = tuple[str, str]

COMPANY_FORM_FIELDS: list[CompanyFieldSpec] = [
    ("production_oz", "Production (oz)", "number"),
    ("aisc_usd_per_oz", "AISC (USD/oz)", "number"),
    ("cash_cost_usd_per_oz", "Cash Cost (USD/oz)", "number"),
    ("royalty_rate", "Royalty Rate (%)", "number"),
    ("sustaining_capex_musd", "Sustaining Capex (M USD)", "number"),
    ("da_musd", "D&A (M USD)", "number"),
    ("interest_expense_musd", "Interest Expense (M USD)", "number"),
    ("tax_rate", "Tax Rate (%)", "number"),
    ("reserve_life_years", "Reserve Life (Years)", "number"),
    ("net_debt_musd", "Net Debt (M USD)", "number"),
    ("ebitda_ltm_musd", "EBITDA LTM (M USD)", "number"),
]

REPORTING_FORM_FIELDS: list[ReportingFieldSpec] = [
    ("next_financial_report_date", "Next Financial Report Date"),
    ("next_production_report_date", "Next Production Report Date"),
    ("notes", "Reporting Notes"),
]

RATE_FIELDS = {"royalty_rate", "tax_rate"}


@dataclass(frozen=True)
class WorkspaceState:
    tool_b_tickers: list[str]
    foundation_manifest: dict[str, Any] | None
    company_inputs: pd.DataFrame
    source_verification: pd.DataFrame
    reporting_calendar: pd.DataFrame
    stock_notes: pd.DataFrame
    latest_tool_a: pd.DataFrame
    latest_tool_b: pd.DataFrame


def create_workspace_app(
    paths: ProjectPaths,
    *,
    tool_b_tickers: list[str],
) -> Callable[..., Iterable[bytes]]:
    normalized_tickers = sorted({str(ticker).strip().upper() for ticker in tool_b_tickers if str(ticker).strip()})
    allowed_tickers = set(normalized_tickers)

    def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/")) or "/"

        try:
            if method == "GET" and path == "/":
                state = _load_workspace_state(paths, normalized_tickers)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                flash = _flash_message(query.get("saved", [""])[0])
                body = _render_overview_page(state, flash=flash)
                return _html_response(start_response, body)

            if path.startswith("/ticker/"):
                ticker, action = _parse_ticker_route(path)
                if ticker not in allowed_tickers:
                    return _html_response(
                        start_response,
                        _render_error_page(f"{ticker} is not an active Tool B ticker."),
                        status="404 Not Found",
                    )

                if method == "GET" and action is None:
                    state = _load_workspace_state(paths, normalized_tickers)
                    query = parse_qs(str(environ.get("QUERY_STRING", "")))
                    flash = _flash_message(query.get("saved", [""])[0])
                    body = _render_ticker_page(state, ticker=ticker, flash=flash)
                    return _html_response(start_response, body)

                if method == "POST":
                    form_data = _read_form_data(environ)
                    if action == "company":
                        try:
                            company_values = {
                                field_name: _coerce_form_numeric(form_data.get(field_name, [""])[0])
                                for field_name, _, _ in COMPANY_FORM_FIELDS
                            }
                            upsert_company_input(paths, ticker=ticker, values=company_values)
                        except ValueError as exc:
                            state = _load_workspace_state(paths, normalized_tickers)
                            body = _render_ticker_page(
                                state,
                                ticker=ticker,
                                flash=None,
                                error=str(exc),
                            )
                            return _html_response(start_response, body, status="400 Bad Request")
                        return _redirect_response(start_response, f"/ticker/{ticker}?saved=company")

                    if action == "reporting":
                        try:
                            reporting_values = {
                                "next_financial_report_date": _coerce_form_text(
                                    form_data.get("next_financial_report_date", [""])[0]
                                ),
                                "next_production_report_date": _coerce_form_text(
                                    form_data.get("next_production_report_date", [""])[0]
                                ),
                                "notes": _coerce_form_text(form_data.get("notes", [""])[0]),
                            }
                            upsert_reporting_calendar(paths, ticker=ticker, values=reporting_values)
                        except ValueError as exc:
                            state = _load_workspace_state(paths, normalized_tickers)
                            body = _render_ticker_page(
                                state,
                                ticker=ticker,
                                flash=None,
                                error=str(exc),
                            )
                            return _html_response(start_response, body, status="400 Bad Request")
                        return _redirect_response(start_response, f"/ticker/{ticker}?saved=reporting")

                    if action == "note":
                        try:
                            add_stock_note(
                                paths,
                                ticker=ticker,
                                note_text=str(form_data.get("note_text", [""])[0]),
                                note_tag=_coerce_form_text(form_data.get("note_tag", [""])[0]),
                                note_status=str(form_data.get("note_status", ["OPEN"])[0] or "OPEN").upper(),
                            )
                        except ValueError as exc:
                            state = _load_workspace_state(paths, normalized_tickers)
                            body = _render_ticker_page(
                                state,
                                ticker=ticker,
                                flash=None,
                                error=str(exc),
                            )
                            return _html_response(start_response, body, status="400 Bad Request")
                        return _redirect_response(start_response, f"/ticker/{ticker}?saved=note")

                return _html_response(
                    start_response,
                    _render_error_page("Unsupported workspace route."),
                    status="404 Not Found",
                )

            return _html_response(
                start_response,
                _render_error_page("Page not found."),
                status="404 Not Found",
            )
        except Exception as exc:
            error_body = _render_error_page(
                "The workspace hit an unexpected error.",
                detail=str(exc),
            )
            return _html_response(start_response, error_body, status="500 Internal Server Error")

    return app


def run_workspace_server(
    paths: ProjectPaths,
    *,
    tool_b_tickers: list[str],
    host: str = "127.0.0.1",
    port: int = 8765,
) -> int:
    app = create_workspace_app(paths, tool_b_tickers=tool_b_tickers)
    with make_server(host, port, app) as server:
        print(f"Golden Vector workspace running at http://{host}:{port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Golden Vector workspace stopped.")
    return 0


def _load_workspace_state(paths: ProjectPaths, tool_b_tickers: list[str]) -> WorkspaceState:
    loaded = load_manual_screening_data(paths, tickers=tool_b_tickers)
    foundation_manifest = _load_json_file(paths.latest_foundation_manifest_path)
    latest_tool_a = _read_optional_parquet(paths.latest_tool_a_snapshot_parquet_path)
    latest_tool_b = _read_optional_parquet(paths.latest_tool_b_snapshot_parquet_path)
    if not latest_tool_a.empty and "ticker" in latest_tool_a.columns:
        latest_tool_a["ticker"] = latest_tool_a["ticker"].astype(str).str.upper()
    if not latest_tool_b.empty and "ticker" in latest_tool_b.columns:
        latest_tool_b["ticker"] = latest_tool_b["ticker"].astype(str).str.upper()
    return WorkspaceState(
        tool_b_tickers=tool_b_tickers,
        foundation_manifest=foundation_manifest,
        company_inputs=loaded.company_inputs,
        source_verification=loaded.source_verification,
        reporting_calendar=loaded.reporting_calendar,
        stock_notes=loaded.stock_notes,
        latest_tool_a=latest_tool_a,
        latest_tool_b=latest_tool_b,
    )


def _parse_ticker_route(path: str) -> tuple[str, str | None]:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0] != "ticker":
        return "", None
    ticker = parts[1].strip().upper()
    action = parts[2] if len(parts) > 2 else None
    return ticker, action


def _render_overview_page(state: WorkspaceState, *, flash: str | None) -> str:
    note_counts = (
        state.stock_notes.groupby("ticker").size().to_dict()
        if not state.stock_notes.empty and "ticker" in state.stock_notes.columns
        else {}
    )
    company_index = _frame_index_by_ticker(state.company_inputs)
    tool_a_index = _frame_index_by_ticker(state.latest_tool_a)
    tool_b_index = _frame_index_by_ticker(state.latest_tool_b)
    rows_html: list[str] = []

    for ticker in state.tool_b_tickers:
        company_row = company_index.get(ticker, {})
        tool_a_row = tool_a_index.get(ticker, {})
        tool_b_row = tool_b_index.get(ticker, {})
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
            f"<td>{_fmt_number(company_row.get('production_oz'), decimals=0)}</td>"
            f"<td>{_fmt_number(company_row.get('aisc_usd_per_oz'), decimals=0)}</td>"
            f"<td>{_fmt_text(company_row.get('updated_at_utc'))}</td>"
            f"<td>{int(note_counts.get(ticker, 0))}</td>"
            f"<td>{_fmt_number(tool_a_row.get('tool_a_score'), decimals=1)}</td>"
            f"<td>{_fmt_number(tool_a_row.get('tool_a_rank'), decimals=0)}</td>"
            f"<td>{_fmt_text(tool_a_row.get('regime_tag'))}</td>"
            f"<td>{_fmt_number(tool_b_row.get('tool_b_score'), decimals=1)}</td>"
            f"<td>{_fmt_number(tool_b_row.get('tool_b_rank'), decimals=0)}</td>"
            f"<td>{_fmt_text(tool_b_row.get('screening_verdict'))}</td>"
            f"<td>{_fmt_text(tool_b_row.get('confidence'))}</td>"
            "</tr>"
        )

    body = [
        "<h1>Golden Vector Workspace</h1>",
        "<p>This is the local working view for Tool B manual inputs, stock notes, and the latest Tool A / Tool B outputs.</p>",
    ]
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        "<h2>Tool B Universe</h2>"
        "<table>"
        "<thead><tr>"
        "<th>Ticker</th><th>Production</th><th>AISC</th><th>Manual Updated</th><th>Notes</th>"
        "<th>Tool A Score</th><th>Tool A Rank</th><th>Regime</th>"
        "<th>Tool B Score</th><th>Tool B Rank</th><th>Verdict</th><th>Confidence</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    body.append(
        "<p class=\"hint\">Use <code>python main.py update-data</code> to refresh market data. "
        "Use the stock links above to edit manual company inputs and notes.</p>"
    )
    return _page_shell("Golden Vector Workspace", "".join(body))


def _render_ticker_page(
    state: WorkspaceState,
    *,
    ticker: str,
    flash: str | None,
    error: str | None = None,
) -> str:
    company_row = _frame_index_by_ticker(state.company_inputs).get(ticker, {})
    reporting_row = _frame_index_by_ticker(state.reporting_calendar).get(ticker, {})
    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
    tool_b_row = _frame_index_by_ticker(state.latest_tool_b).get(ticker, {})
    verification_rows = _ticker_rows(state.source_verification, ticker)
    note_rows = _ticker_rows(state.stock_notes, ticker)

    body = [f"<p><a href=\"/\">Back to workspace</a></p>", f"<h1>{escape(ticker)}</h1>"]
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if error:
        body.append(f"<div class=\"flash\">{escape(error)}</div>")
    body.append(_render_latest_panels(tool_a_row=tool_a_row, tool_b_row=tool_b_row))
    body.append(_render_company_form(ticker=ticker, company_row=company_row))
    body.append(_render_reporting_form(ticker=ticker, reporting_row=reporting_row))
    body.append(_render_verification_table(verification_rows))
    body.append(_render_note_section(ticker=ticker, note_rows=note_rows))
    return _page_shell(f"Golden Vector Workspace - {ticker}", "".join(body))


def _render_refresh_summary(manifest: dict[str, Any] | None) -> str:
    if not manifest:
        return (
            "<div class=\"panel\">"
            "<h2>Latest Market Snapshot</h2>"
            "<p>No validated local market-data snapshot is available yet.</p>"
            "</div>"
        )
    refresh_run_id = _fmt_text(manifest.get("refresh_run_id"))
    snapshot_as_of_date = _fmt_text(manifest.get("snapshot_as_of_date"))
    foundation_status = _fmt_text(manifest.get("foundation_status"))
    return (
        "<div class=\"panel\">"
        "<h2>Latest Market Snapshot</h2>"
        f"<p><strong>Refresh Run:</strong> {refresh_run_id}</p>"
        f"<p><strong>As Of:</strong> {snapshot_as_of_date}</p>"
        f"<p><strong>Status:</strong> {foundation_status}</p>"
        "</div>"
    )


def _render_latest_panels(*, tool_a_row: dict[str, Any], tool_b_row: dict[str, Any]) -> str:
    return (
        "<div class=\"two-up\">"
        f"{_render_small_table('Latest Tool A Snapshot', tool_a_row, ['as_of_date', 'tool_a_score', 'tool_a_rank', 'regime_tag', 'core_delta', 'stability_score', 'gamma_proxy'])}"
        f"{_render_small_table('Latest Tool B Snapshot', tool_b_row, ['as_of_date', 'gold_price_assumption', 'tool_b_score', 'tool_b_rank', 'screening_verdict', 'confidence', 'best_upside_pct'])}"
        "</div>"
    )


def _render_company_form(*, ticker: str, company_row: dict[str, Any]) -> str:
    fields_html: list[str] = []
    for field_name, label, input_type in COMPANY_FORM_FIELDS:
        value = _format_form_value(field_name, company_row.get(field_name))
        step = "0.01" if input_type == "number" else None
        step_attr = f" step=\"{step}\"" if step is not None else ""
        fields_html.append(
            "<label>"
            f"<span>{escape(label)}</span>"
            f"<input name=\"{escape(field_name)}\" type=\"{escape(input_type)}\" value=\"{escape(value)}\"{step_attr}>"
            "</label>"
        )
    updated_at = _fmt_text(company_row.get("updated_at_utc"))
    return (
        "<section class=\"panel\">"
        "<h2>Company Inputs</h2>"
        f"<p><strong>Last Updated:</strong> {updated_at}</p>"
        f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/company\" class=\"form-grid\">"
        f"{''.join(fields_html)}"
        "<div class=\"form-actions\"><button type=\"submit\">Save Company Inputs</button></div>"
        "</form>"
        "</section>"
    )


def _render_reporting_form(*, ticker: str, reporting_row: dict[str, Any]) -> str:
    fields_html = [
        "<label>"
        f"<span>{escape(label)}</span>"
        f"<input name=\"{escape(field_name)}\" type=\"date\" value=\"{escape(_format_form_value(field_name, reporting_row.get(field_name)))}\">"
        "</label>"
        for field_name, label in REPORTING_FORM_FIELDS[:2]
    ]
    fields_html.append(
        "<label class=\"full-width\">"
        "<span>Reporting Notes</span>"
        f"<textarea name=\"notes\" rows=\"3\">{escape(_format_form_value('notes', reporting_row.get('notes')))}</textarea>"
        "</label>"
    )
    updated_at = _fmt_text(reporting_row.get("updated_at_utc"))
    return (
        "<section class=\"panel\">"
        "<h2>Reporting Calendar</h2>"
        f"<p><strong>Last Updated:</strong> {updated_at}</p>"
        f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/reporting\" class=\"form-grid\">"
        f"{''.join(fields_html)}"
        "<div class=\"form-actions\"><button type=\"submit\">Save Reporting Calendar</button></div>"
        "</form>"
        "</section>"
    )


def _render_verification_table(verification_rows: list[dict[str, Any]]) -> str:
    if not verification_rows:
        return (
            "<section class=\"panel\">"
            "<h2>Source Verification</h2>"
            "<p>No source-verification rows yet. The CLI can still be used for detailed verification updates.</p>"
            "</section>"
        )
    rows_html = "".join(
        "<tr>"
        f"<td>{escape(str(row.get('field_name') or ''))}</td>"
        f"<td>{_fmt_text(row.get('verification_status'))}</td>"
        f"<td>{_fmt_text(row.get('source_date'))}</td>"
        f"<td>{_fmt_text(row.get('source_url'))}</td>"
        f"<td>{_fmt_text(row.get('updated_at_utc'))}</td>"
        "</tr>"
        for row in verification_rows
    )
    return (
        "<section class=\"panel\">"
        "<h2>Source Verification</h2>"
        "<table>"
        "<thead><tr><th>Field</th><th>Status</th><th>Source Date</th><th>Source URL</th><th>Updated</th></tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
        "</section>"
    )


def _render_note_section(*, ticker: str, note_rows: list[dict[str, Any]]) -> str:
    if not note_rows:
        note_table = "<p>No stock notes yet.</p>"
    else:
        note_table = (
            "<table>"
            "<thead><tr><th>Status</th><th>Tag</th><th>Note</th><th>Updated</th></tr></thead>"
            "<tbody>"
            + "".join(
                "<tr>"
                f"<td>{_fmt_text(row.get('note_status'))}</td>"
                f"<td>{_fmt_text(row.get('note_tag'))}</td>"
                f"<td>{_fmt_text(row.get('note_text'))}</td>"
                f"<td>{_fmt_text(row.get('updated_at_utc'))}</td>"
                "</tr>"
                for row in note_rows
            )
            + "</tbody></table>"
        )
    return (
        "<section class=\"panel\">"
        "<h2>Stock Notes</h2>"
        f"{note_table}"
        f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/note\" class=\"note-form\">"
        "<label class=\"full-width\"><span>Note</span><textarea name=\"note_text\" rows=\"3\" required></textarea></label>"
        "<label><span>Tag</span><input name=\"note_tag\" type=\"text\"></label>"
        "<label><span>Status</span>"
        "<select name=\"note_status\">"
        "<option value=\"OPEN\">OPEN</option>"
        "<option value=\"WATCH\">WATCH</option>"
        "<option value=\"DONE\">DONE</option>"
        "</select></label>"
        "<div class=\"form-actions\"><button type=\"submit\">Add Note</button></div>"
        "</form>"
        "</section>"
    )


def _render_small_table(title: str, row: dict[str, Any], columns: list[str]) -> str:
    if not row:
        return (
            "<section class=\"panel\">"
            f"<h2>{escape(title)}</h2>"
            "<p>No latest output is available yet.</p>"
            "</section>"
        )
    rows_html = "".join(
        "<tr>"
        f"<th>{escape(_humanize_column_name(column_name))}</th>"
        f"<td>{_fmt_value(row.get(column_name), column_name)}</td>"
        "</tr>"
        for column_name in columns
        if column_name in row
    )
    return (
        "<section class=\"panel\">"
        f"<h2>{escape(title)}</h2>"
        f"<table><tbody>{rows_html}</tbody></table>"
        "</section>"
    )


def _page_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f1e7;
      --panel: #fffdf8;
      --ink: #1f1d1a;
      --muted: #6f685c;
      --line: #d8cfbf;
      --accent: #b26700;
      --accent-soft: #f8ead4;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: linear-gradient(180deg, #f1eadb 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    h1, h2 {{
      margin-top: 0;
    }}
    p, li {{
      line-height: 1.5;
    }}
    a {{
      color: #1d4b73;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px 18px;
      margin-bottom: 18px;
      box-shadow: 0 8px 24px rgba(98, 83, 57, 0.08);
    }}
    .two-up {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
      margin-bottom: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
    }}
    thead th {{
      background: #f7f0e2;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .form-grid label, .note-form label {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 0.92rem;
    }}
    .full-width {{
      grid-column: 1 / -1;
    }}
    input, textarea, select, button {{
      font: inherit;
    }}
    input, textarea, select {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      background: white;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      background: var(--accent);
      color: white;
      cursor: pointer;
    }}
    .form-actions {{
      grid-column: 1 / -1;
      display: flex;
      justify-content: flex-start;
      align-items: end;
    }}
    .flash {{
      margin-bottom: 16px;
      padding: 12px 14px;
      background: var(--accent-soft);
      border: 1px solid #ebcd9f;
      border-radius: 10px;
    }}
    .hint {{
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <main>{body}</main>
</body>
</html>"""


def _frame_index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for record in frame.to_dict(orient="records"):
        ticker = str(record.get("ticker") or "").upper()
        if ticker:
            indexed[ticker] = record
    return indexed


def _ticker_rows(frame: pd.DataFrame, ticker: str) -> list[dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return frame[frame["ticker"].astype(str).str.upper() == ticker].to_dict(orient="records")


def _flash_message(saved_token: str) -> str | None:
    messages = {
        "company": "Company inputs saved.",
        "reporting": "Reporting calendar saved.",
        "note": "Stock note added.",
    }
    return messages.get(saved_token)


def _render_error_page(message: str, *, detail: str | None = None) -> str:
    detail_html = f"<p class=\"hint\">{escape(detail)}</p>" if detail else ""
    return _page_shell(
        "Golden Vector Workspace Error",
        f"<h1>Workspace Error</h1><div class=\"panel\"><p>{escape(message)}</p>{detail_html}<p><a href=\"/\">Back to workspace</a></p></div>",
    )


def _humanize_column_name(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _fmt_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    text = str(value).strip()
    return escape(text) if text else "—"


def _fmt_number(value: Any, *, decimals: int) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _fmt_text(value)
    if pd.isna(numeric):
        return "—"
    return escape(f"{numeric:,.{decimals}f}")


def _fmt_percent(value: Any, *, decimals: int = 1) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _fmt_text(value)
    if pd.isna(numeric):
        return "—"
    return escape(f"{numeric * 100:,.{decimals}f}%")


def _fmt_value(value: Any, column_name: str) -> str:
    if column_name in {"royalty_rate", "tax_rate", "best_upside_pct", "core_delta", "gamma_proxy", "stability_score"}:
        return _fmt_percent(value)
    if column_name.endswith("_rank"):
        return _fmt_number(value, decimals=0)
    if isinstance(value, (int, float)):
        return _fmt_number(value, decimals=2)
    return _fmt_text(value)


def _format_form_value(field_name: str, value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if field_name in RATE_FIELDS:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{numeric * 100:g}"
    return str(value)


def _coerce_form_numeric(value: str) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError("Numeric fields must be numeric.") from exc


def _coerce_form_text(value: str) -> str | None:
    text = str(value).strip()
    return text or None


def _read_optional_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_form_data(environ: dict[str, Any]) -> dict[str, list[str]]:
    try:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = 0
    body = environ.get("wsgi.input", io.BytesIO()).read(content_length)
    return parse_qs(body.decode("utf-8"), keep_blank_values=True)


def _html_response(
    start_response: Callable[..., Any],
    body: str,
    *,
    status: str = "200 OK",
) -> Iterable[bytes]:
    payload = body.encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(payload))),
        ],
    )
    return [payload]


def _redirect_response(start_response: Callable[..., Any], location: str) -> Iterable[bytes]:
    start_response("303 See Other", [("Location", location), ("Content-Length", "0")])
    return [b""]
