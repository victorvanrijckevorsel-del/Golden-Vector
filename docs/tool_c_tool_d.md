# Tool C and Tool D

Tool C and Tool D are descriptive ranking tools. They help compare gold-stock names in the local universe, but they are not forecasts and they do not decide whether a trade should be made.

## Tool C: Symmetric Gold Behavior

Tool C reads the latest Tool A output, the foundation weekly equity and gold series, and cached GDX/GDXJ benchmark histories. It reuses the same weekly structural series builder as Tool A so the stock and gold sampling rules stay aligned.

The output has two main ranks:

- `tool_c_downside_rank`: higher values mean the stock has shown more adverse behavior when gold fell, relative to the available peers and configured event thresholds.
- `tool_c_upside_rank`: higher values mean the stock has shown stronger behavior when gold rose, relative to the same universe.

Tool C also publishes event counts and tags. These are important because some tickers have thin usable history or few gold up/down events. Thin metrics are excluded from their component blend instead of being treated as bad data. A row with no rankable components receives a null rank.

The hit-rate thresholds live in `config/tool_c.yaml`. Change those thresholds there rather than adding ad hoc horizons or local constants in model code.

## Tool D: Gold-Stressed Quality

Tool D reads the latest Tool B context, manual company inputs, normalized market snapshots, and the foundation gold history. It reuses Tool B's in-memory earnings engine at a selected gold price `G`.

The output has one main rank:

- `tool_d_quality_rank`: higher values mean better gold-stressed quality at the selected gold price.

The quality rank is exactly an equal-weight blend of three components:

- margin headroom at `G`
- stressed leverage, computed as `net_debt_musd / forward_ebitda_musd_at_g`
- EV/EBITDA at `G`

Free-cash-flow yield is exported as context only. It is not part of the Tool D quality rank.

If EBITDA at `G` is zero or negative, stressed leverage and EV/EBITDA are null and the row is tagged with `leverage_undefined_at_G`. Tool D never creates infinite leverage values, and it never reads Tool B's trailing `leverage` column for its stressed leverage calculation.

## Candidate Finder Use

Candidate Finder consumes three static latest-output fields:

- `tool_c_downside_rank`
- `tool_c_upside_rank`
- `tool_d_quality_rank`

In this version, Candidate Finder uses the latest Tool D run computed at spot gold. It does not recompute Tool D inside each Finder lens, and it does not expose a per-lens gold-price dial. A future version can add that dial, but this version keeps Finder criteria simple and auditable: each criterion is a plain source field loaded from a latest parquet snapshot.

The bearish put preset uses Tool C downside behavior and lower spot Tool D quality as part of the screen. The bullish call preset uses Tool C upside behavior and higher spot Tool D quality.

## Provenance

Tool C and Tool D write retained full outputs, retained latest-per-run outputs, and stable latest aliases. Their source files are copied into replay snapshots and included in replay-manifest verification, alongside the config files that control the calculations.
