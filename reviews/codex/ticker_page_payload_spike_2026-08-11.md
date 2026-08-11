# Ticker-page payload spike — measured 2026-08-11 (plan v2 §12)

Measured from REAL local artifacts (script in session scratchpad `payload_spike.py`), worst-case
assumption: every section's data embedded as raw JSON. Serving is localhost `wsgiref` (no gzip),
so RAW bytes are what transfers; gzip shown as the compressibility signal.

| Payload | raw JSON | gzip |
|---|---|---|
| score percentiles (61 tickers × 20 metrics × value+2 orientations) | 48.6 KB | 5.8 KB |
| chain history NEM (36 days) | 7.1 KB | 1.4 KB |
| chain history GDX (35 days — heaviest chain, 2.43M OI) | 7.0 KB | 1.3 KB |
| signal history NEM (111 rows) | 28.0 KB | 4.3 KB |
| signal history GDX (118 rows) | 25.8 KB | 2.1 KB |
| lab episodes NEM h8 GDX (1,046 weeks, full records) | **131.0 KB** | 16.1 KB |
| lab cells NEM (20 rows) | 11.8 KB | 1.6 KB |
| performance (4 series × 3 horizons × 2 views, weekly 3Y/5Y) | 56.8 KB | 6.4 KB |
| gold response pack (2 sources, lines+constants+spot) | 1.2 KB | 0.3 KB |
| **TOTAL worst-case embed** | **317.2 KB** | |
| mock3.html full-page baseline | 144.4 KB | 33.6 KB |

## Conclusions (binding on M1/M3 design)

1. **Never embed raw Lab episodes.** 41% of the worst-case total is one Lab chart's raw rows.
   The design already renders charts as server-side SVG; the Lab charts embed only per-tick
   display attributes (like the existing rug ticks), and the scatter is trimmed to 2016+
   (requirements Q44). Kills ~131 KB.
2. **Round embedded floats** — 4 significant figures for series, 1 decimal for percentiles;
   display formatting happens anyway, full float64 text is pure waste.
3. With rules 1–2 the realistic embedded total is ≈ **120–140 KB** on top of a ~150–250 KB page
   → inside the ≤ 300 KB HTML working budget. Budget confirmed feasible; re-measured with the
   real page at M4.
4. **Producer note (M1b):** benchmark parquets (`data/intermediate/benchmarks/GDX.parquet`)
   carry only `*_local` columns — no `*_usd`. They are US-listed USD ETFs, but the performance
   producer must resolve this through the one normalize boundary explicitly, not by silently
   reading `close_local`.
5. The option-heaviest chain (GDX, 2.43M OI) produces the SAME payload size as NEM — chain
   history is per-day aggregates, so chain size does not scale the page. The heaviest
   *corporate* payload ≈ NEM's.
