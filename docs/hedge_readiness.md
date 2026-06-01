# Hedge Readiness

Hedge Readiness is the local CLI report for the downside-product line. It answers a practical question: which current or watched gold-stock names can be hedged directly with listed puts, which names have thin or no options, and what proxy path exists when direct options are unavailable.

This is not a trade ticket and it does not recommend one contract. It shows a shortlist, quote context, premium-vs-modeled-downside math, and basis-risk labels so the user can decide what deserves follow-up.

## Workflow

Refresh the local data and options snapshots:

```powershell
python main.py update-data
```

Render the markdown report:

```powershell
python main.py hedge-readiness
```

The report is written to:

```text
data/output/hedge_readiness/<YYYYMMDD>_<run_id>.md
data/output/hedge_readiness/latest.md
```

`latest.md` is a copy of the newest report for quick inspection. The run-specific file is the audit trail.

## Options Phase

`update-data` runs the hedge-readiness options phase by default. That phase:

- fetches listed Yahoo option chains for every active universe ticker
- writes run-local snapshots under `data/runs/<run_id>/snapshots/options/`
- writes `data/intermediate/status/latest_options_manifest.json`
- appends one derived feature row per ticker under `data/intermediate/options_features/`
- fetches hedge-side benchmarks from `config/benchmarks.yaml`
- records the options manifest in the run replay manifest

If the normal market-data refresh is needed but options should be skipped, use:

```powershell
python main.py update-data --no-options
```

The run metadata records that the options phase was intentionally skipped. The hedge-readiness report will continue to use the last successful `latest_options_manifest.json` until options are refreshed again.

## Holdings File

The report can run without a holdings file. In that case it says so clearly and shows cross-sectional hedge readiness only.

To enable position-aware exposure and premium-vs-downside cards, create:

```text
data/manual/holdings/holdings.yaml
```

Format:

```yaml
version: 1
holdings:
  - ticker: NEM
    shares: 500
  - ticker: AEM
    dollar_exposure: 50000
```

Each holding must set exactly one of `shares` or `dollar_exposure`, and each ticker can appear only once. The loader does not auto-create this file, and it fails loudly on malformed entries so exposure is not silently misread.

## Report Sections

The markdown report includes:

- snapshot summary: optionable, thin, non-optionable counts, and Tool A/Tool B snapshot alignment
- held-position sections when `holdings.yaml` exists
- candidate put tables for configured horizons
- premium-vs-modeled-downside cards using Tool A down beta
- cross-sectional 60-day ATM IV ranking
- proxy-hedge map for held non-optionable names
- source counts and manifest paths

Candidate puts use listed strikes only. The `delta_gap` column shows how close the selected listed contract is to the configured target delta.

## Recovery Notes

If `python main.py hedge-readiness` says there is no options snapshot, run:

```powershell
python main.py update-data
```

If Yahoo options are temporarily unreliable but the foundation refresh is still needed, run:

```powershell
python main.py update-data --no-options
```

That keeps Tool A and Tool B refreshes moving while preserving the last successful hedge-readiness options snapshot for reporting.

If the report shows `Analytical context alignment | WARN |` or `UNKNOWN`, the options snapshot is newer than the latest Tool A or Tool B output, or the older output does not carry a refresh id. Run the normal analytical steps again before using the report for decisions:

```powershell
python main.py tool-a
python main.py tool-b
python main.py hedge-readiness
```
