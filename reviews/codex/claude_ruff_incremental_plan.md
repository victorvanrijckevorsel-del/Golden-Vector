# Ruff — incremental adoption plan ("slowly but surely")

**Principle (Emanuel, 2026-06-09):** clean the code with ruff **gradually** — one rule category at a time, fixed to zero and locked green before moving on. **Never** a big-bang sweep that floods the codebase with violations nobody reviews. Each step is a small, self-contained, reviewable commit.

## Current state
- `ruff.toml`: `[lint] select = ["F"]` (pyflakes), `line-length = 100`, excludes `data/`, `reviews/`, `venv/`.
- **`F` is at ZERO** — `python -m ruff check golden_vector/ tests/` passes clean.
- `ruff` is in `requirements-dev.txt` (installed locally, v0.15.16).

## The ratchet — enable in this order (low-noise / high-value first)
Each is its own small PR. Do NOT enable more than one category per step.

1. **`F` — pyflakes** ✅ DONE (unused imports/vars, undefined names — real bug-catching).
2. **`I` — import sorting** (isort). Almost fully `--fix`-able; mechanical; low risk. Good next.
3. **`UP` — pyupgrade** (modernize syntax for the target Python). Mostly `--fix`-able.
4. **`B` — flake8-bugbear** (likely bugs / footguns, e.g. mutable defaults, loop-var binding). High value; some manual.
5. **`SIM` / `C4` / `RET`** — simplifications, comprehensions, return style. Quality nits; mostly mechanical.
6. **`E` / `W` — pycodestyle style/whitespace** — LOTS of nits. Prefer running **`ruff format`** (the formatter) for whitespace instead of enabling these as lint rules. Apply the formatter **gradually** (per-directory) so the diff stays reviewable, or defer entirely — formatting is cosmetic.

(Stop and reassess after `B`; the later categories are optional polish.)

## Per-step recipe (every category)
1. Add the category to `select` in `ruff.toml` (one new category only).
2. `python -m ruff check golden_vector/ tests/ --statistics` to see the count.
3. `python -m ruff check golden_vector/ tests/ --fix` for the safe auto-fixes.
4. Fix the rest **by hand** — never blind-delete a variable whose RHS has a side effect (e.g. a `parser.add_parser(...)` registration), and rename rather than delete for shadowing/ambiguity.
5. Run the **full test suite** — must stay green.
6. Confirm `ruff check` is **clean (0)**, then commit just that category as one small change (`chore(ruff): enable <CATEGORY>`).

## When to do it
- As **small standalone commits between features**, or
- Opportunistically when Codex is already editing an area.
- It must **never block or bloat a feature commit** — keep lint-ratchet steps separate from feature work so reviews stay clean.

## Guardrails
- The suite stays green at every step (non-negotiable).
- Keep `data/`, `reviews/`, `venv/` excluded.
- `mypy`/`pyright` (type-checking) is a separate, later decision — not part of this ruff ratchet.
