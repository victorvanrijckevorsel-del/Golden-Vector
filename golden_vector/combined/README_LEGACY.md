# Legacy Combined Backend

This folder preserves the old Combined backend implementation so it is not lost.

It is **not part of the active Golden Vector product anymore**.

Current product direction:

- Tool A is a standalone engine
- Tool B is a standalone engine
- Combined will return later only as a lightweight side-by-side compare view

Why this backend was de-scoped:

- it acted like a third engine instead of a compare view
- it added backend complexity the product does not currently need
- the historical outer-join model did not match the real user workflow

What is preserved here:

- [join.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/combined/join.py)
- [ranking.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/combined/ranking.py)
- [pipeline.py](C:/Users/Emanuel/code/Golden-Vector/golden_vector/combined/pipeline.py)

How to recover ideas later:

- use git history for the full active CLI integration that previously called this backend
- use the redesign plan in [product_runtime_redesign_plan.md](C:/Users/Emanuel/code/Golden-Vector/reviews/codex/product_runtime_redesign_plan.md)
- when Combined returns, rebuild it as a latest-first compare view instead of a scoring engine
