# Codex Review - Options Liquidity & Scenario Lab Build Brief

Grade: NEEDS CHANGES

The direction is right, especially the move away from one hidden 25-delta pick toward a liquidity lab with tiers, horizon buckets, and selected-contract scenarios. The staging for Job 1 is mostly sound. The brief is not ready to code as written because Job 2 depends on data and portfolio primitives that do not exist yet in the current codebase, and Step 0 will currently stop immediately.

## Findings

### [Blocker] Step 0 cannot prove GDX/GDXJ liquidity from current cached option chains

The brief correctly says GDX/GDXJ liquidity must be measured before any proxy or portfolio-hedge work (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:32`-`38`). Current cached options data does not include those ETF chains: `latest_options_manifest.json` has 60 option snapshots, with `has_GDX=False` and `has_GDXJ=False` from the local manifest diagnostic. The code explains why: options ingestion builds `active_tickers` only from the universe (`golden_vector/ingestion/options_phase.py:73`) and fetches options only for that list (`golden_vector/ingestion/options_phase.py:97`), while benchmarks are persisted as price-history snapshots (`golden_vector/ingestion/options_phase.py:288`, `golden_vector/ingestion/options_phase.py:292`) and merely attached to the options manifest as benchmark paths (`golden_vector/ingestion/options_phase.py:177`). `config/benchmarks.yaml:2`-`8` defines GDX/GDXJ as benchmarks, not as option-chain fetch targets. The brief should add an explicit pre-step to include benchmark ETF option chains in the options snapshot/manifest path, or state that Job 2 is blocked until a separate options refresh includes ETFs. Without that, a literal implementation reaches Step 0 and stops before the planned build starts.

### [Blocker] Job 2 overstates reuse of portfolio_totals/proxy_hedge/holdings

Milestone G says it reuses `hedge/portfolio_totals.py`, `hedge/proxy_hedge.py`, and the Milestone-B engine (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:107`-`114`). That is directionally true but technically too optimistic. `compute_portfolio_totals` currently aggregates existing `Holding` objects and uses a per-holding 60d single-name put candidate for hedge cost (`golden_vector/hedge/portfolio_totals.py:60`, `golden_vector/hedge/portfolio_totals.py:157`, `golden_vector/hedge/portfolio_totals.py:241`-`258`). It does not size a portfolio-level GDX/GDXJ option payoff. `Holding` currently stores only ticker, shares, and optional USD dollar exposure (`golden_vector/hedge/holdings.py:13`-`20`) and `load_holdings` reads only `holdings.yaml` (`golden_vector/hedge/holdings.py:26`-`41`), not the IBKR CSV. `proxy_hedge` can append GDX/GDXJ as sector ETF fallbacks (`golden_vector/hedge/proxy_hedge.py:30`-`36`, `golden_vector/hedge/proxy_hedge.py:85`-`91`), but benchmark matches deliberately have no proxy beta or beta diff (`golden_vector/hedge/proxy_hedge.py:168`-`181`). Treat Job 2 as a separate foundation-plus-hedge milestone: extend holdings ingestion, define symbol mapping and currency/notional handling, then add GDX/GDXJ payoff sizing. Do not present it as mostly reusing the current modules.

### [High] The real portfolio needs explicit symbol mapping and missing-beta rules before hedge math

The brief says to aggregate portfolio downside using Tool A down-betas and flag/proxy missing betas (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:109`-`110`). That needs more precision before coding. The real portfolio README confirms the book is multi-currency small/mid miners (`data/manual/portfolio/README.md:6`-`18`) and says single-name options are essentially unavailable (`data/manual/portfolio/README.md:21`). A local CSV-to-Tool-A check found clean matches for only some raw IBKR symbols: `WAF -> WAF.AX`, `AAZ -> AAZ.L`, `EDVL -> EDV.L`, `MTL -> MTL.L`, `PAFL -> PAF.L`, `SRB -> SRB.L`; `AAR`, `CLA`, `SBI`, and `ALTNL` did not map by simple suffix rules. Also, the brief's "sector/GDX beta proxy" fallback is undefined in code: benchmark fallback proxy rows have `proxy_beta=None` (`golden_vector/hedge/proxy_hedge.py:176`-`179`), and GDX/GDXJ are benchmarks in config, not Tool A universe rows. Add a small mapping table/design and a hard display rule for unmapped or low-confidence names before portfolio totals are shown. Otherwise the portfolio hedge output will look precise while a meaningful slice of the real book is estimated or skipped.

### [High] The combined Job 1 + Job 2 milestone is over-scoped for one coding pass

The Job 1 sequence A-D is coherent: clean the current UI, build pure liquidity metrics, add bucket selection, then rebuild the display (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:43`-`102`). Job 2 adds a different product: ETF chain ingestion, ETF liquidity measurement, per-name proxy, IBKR portfolio parsing, currency normalization, beta mapping/fallbacks, GDX/GDXJ option payoff sizing, and basis/FX caveats (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:104`-`115`). That is too much risk to bundle into the same implementation run, especially because Step 0 currently fails. Recommended staging: ship Job 1 through Checkpoint 1 first; separately add "ETF options included in cached data + Step 0 report"; then implement portfolio hedge as its own Job 2 milestone after the data gate is proven.

### [Medium] Liquidity tiers and weights are good starting points, but a few rules need exact failure semantics

The proposed tiers are broadly right: three states, spread-dominant, OI present, minimum premium, and volume weakly weighted (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:55`-`70`). The 0.55 spread / 0.25 OI / 0.10 premium / 0.05 depth / 0.05 volume split is acceptable for a first config because it prevents volume from rescuing a bad spread. Before coding, define exact handling for zero/negative/NaN bid, ask, mid, OI, and volume; whether OI>=1 is acceptable only for "Watch" while "Tradable" may need a higher empirical floor after Step 0; and how depth is computed for near-spot two-sided contracts. The current code already treats missing or non-positive bid/ask/mid as failing quote gates (`golden_vector/features/options_chain.py:212`-`228`), so the new engine should preserve that strictness and not silently score invalid quotes.

### [Medium] DTE bands and delta buckets are sound, but the acceptance wording is too strong

The proposed DTE bands are good as search windows, and the delta buckets are reasonable beginner conventions: calls 0.35-0.50, directional puts -0.50 to -0.35, tail puts -0.30 to -0.15 (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:79`-`97`). The issue is the acceptance line "each horizon shows >=1 bucket" (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:97`). It should say each horizon renders its bucket states, with "No usable contract" and best near-miss diagnostics when nothing qualifies. For thin miners, forcing at least one displayed candidate per horizon risks recreating the current bad behavior where an obviously wrong strike appears important. Also define how to detect and prefer standard monthly expiries, because the brief says to prefer monthlies but does not specify the rule.

### [Medium] Milestone A needs a concrete UI stopgap, not just "make table not-broken"

The immediate cleanup is correct: remove the wall of text, keep stock price/snapshot/source visible, and move caveats into a disclosure (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:43`-`48`). But "make the current candidate table not-broken (reduce columns)" is too vague for a step intended to stabilize the visible app before the new engine exists. Define the exact columns to keep, the long fields to hide, and whether rows remain one per horizon or one per selected candidate. This is important because Emanuel has already objected to the current text-heavy UI and unreadable table, so Step A should have crisp acceptance beyond "no wall of text."

### [Low] The refresh button remains correctly out of scope, but the header placeholder must avoid implying live quotes

Milestone D asks for a header strip with source and refresh placeholder (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:100`), while Milestone F explicitly keeps the actual refresh button out of scope (`reviews/codex/claude_codex_options_liquidity_lab_build_brief.md:117`-`118`). That is the right call. The UI copy should be strict: "Cached options snapshot: <date>; screening only" and no button-like control unless it is disabled or clearly non-interactive. Otherwise the user will expect live Yahoo prices to match the cached screen.

### [Low] Add replay/audit expectations if ETF option chains become cached artifacts

If the implementation adds GDX/GDXJ option-chain snapshots, those are new inputs to option selection and portfolio hedge outputs. The brief should say the latest options manifest and replay metadata must include them, just as current options ingestion writes the latest manifest (`golden_vector/ingestion/options_phase.py:171`) and updates the run manifest (`golden_vector/ingestion/options_phase.py:180`). This is not a product blocker, but it preserves Golden Vector's auditability rule.

## Direct Answers

- Staging sound? Job 1 A-D is sound. Job 2 should be split behind a proven ETF-chain data gate.
- Liquidity tiers/weights right? Yes as initial config, with spread dominant and volume minimal. Tighten invalid-data semantics and consider a stronger empirical Tradable OI floor after Step 0.
- DTE bands/delta buckets right? Yes as conventions. Do not force a candidate when all contracts are bad.
- Step 0 feasible with cached data? Feasible as a check, but it currently proves absence: GDX/GDXJ option chains are not cached.
- Job 2 reuse correct? Not as written. The named modules are useful starting points but do not yet implement IBKR portfolio loading, multi-currency notional normalization for holdings, benchmark beta fallback, or GDX/GDXJ portfolio option payoff sizing.
- Missing/over-scoped? Missing: ETF option-chain ingestion, portfolio symbol mapping, explicit missing-beta fallback, monthly-expiry detection, audit/manifest handling for ETF chains. Over-scoped: combining Job 1 and full portfolio hedge in one run.

