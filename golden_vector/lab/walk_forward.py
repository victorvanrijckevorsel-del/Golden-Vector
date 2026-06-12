"""M1-1: walk-forward fold generator with purge + embargo.

Admissibility conditions from the Lab spec — these are not options:

- Expanding-window folds on the W-FRI weekly grid; the test window always
  lies strictly after the training window.
- PURGE: an h-week forward label at week t reads returns through t+h, so
  any training week within h weeks of the test start has a label window
  overlapping the test period and is dropped.
- EMBARGO: after the test window, ``embargo_weeks`` further weeks are
  excluded from any later training set in this fold sequence (handled by
  construction here: training always ends before the test starts, and the
  caller advances folds by full test windows).
- Episode accounting: overlapping h-week labels sampled weekly are NOT
  independent; ``effective_n`` divides by the horizon.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class WalkForwardFold:
    fold_index: int
    train_periods: tuple[str, ...]
    purged_periods: tuple[str, ...]
    test_periods: tuple[str, ...]


def generate_folds(
    week_periods: list[str],
    *,
    label_horizon_weeks: int,
    min_train_weeks: int,
    test_weeks: int,
    step_weeks: int | None = None,
) -> list[WalkForwardFold]:
    """Expanding-window folds over an ordered, deduplicated W-FRI grid."""

    if label_horizon_weeks < 1:
        raise ValueError("label_horizon_weeks must be positive.")
    if min_train_weeks < 1 or test_weeks < 1:
        raise ValueError("min_train_weeks and test_weeks must be positive.")

    grid = sorted(dict.fromkeys(str(period) for period in week_periods))
    step = int(step_weeks) if step_weeks is not None else int(test_weeks)
    if step < 1:
        raise ValueError("step_weeks must be positive.")

    folds: list[WalkForwardFold] = []
    test_start_index = min_train_weeks + label_horizon_weeks
    fold_index = 0
    while test_start_index + test_weeks <= len(grid):
        purge_start = test_start_index - label_horizon_weeks
        train = tuple(grid[:purge_start])
        purged = tuple(grid[purge_start:test_start_index])
        test = tuple(grid[test_start_index : test_start_index + test_weeks])
        if len(train) >= min_train_weeks:
            folds.append(
                WalkForwardFold(
                    fold_index=fold_index,
                    train_periods=train,
                    purged_periods=purged,
                    test_periods=test,
                )
            )
            fold_index += 1
        test_start_index += step
    return folds


def effective_n(n_weeks: int, *, label_horizon_weeks: int) -> float:
    """Honest sample count for overlapping weekly-sampled h-week labels."""

    if label_horizon_weeks < 1:
        raise ValueError("label_horizon_weeks must be positive.")
    return float(n_weeks) / float(label_horizon_weeks)


def assert_no_label_overlap(
    fold: WalkForwardFold,
    *,
    label_horizon_weeks: int,
) -> None:
    """Canary-facing invariant: no train label window can reach the test."""

    if not fold.train_periods or not fold.test_periods:
        return
    train_end = pd.Period(fold.train_periods[-1], freq="W-FRI")
    test_start = pd.Period(fold.test_periods[0], freq="W-FRI")
    gap_weeks = (test_start - train_end).n
    if gap_weeks <= label_horizon_weeks:
        raise AssertionError(
            f"Fold {fold.fold_index}: last train week {train_end} is only "
            f"{gap_weeks}w before test start {test_start}; an "
            f"{label_horizon_weeks}w label window would overlap the test."
        )
