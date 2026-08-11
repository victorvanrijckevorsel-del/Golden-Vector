"""Shared straight-line helpers for gold-price response models.

A "gold line" is a simple two-parameter linear model ``y = slope * x + intercept``
fitted through two evaluations of a downstream model at two gold prices. Tool D
uses it for EBITDA-vs-gold; the ticker-page gold-response producer is the second
consumer. Keep one implementation here — divergent copies would give different
answers on different screens.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Two gold prices closer than this are treated as the same point (degenerate).
MIN_X_SEPARATION = 0.01

#: Slopes with magnitude at or below this cannot be inverted safely.
MIN_INVERTIBLE_SLOPE = 0.0


@dataclass(frozen=True)
class GoldLine:
    """A straight line in gold-price space: ``value = slope * gold + intercept``."""

    slope: float
    intercept: float


def line_from_two_points(
    x1: float | None,
    y1: float | None,
    x2: float | None,
    y2: float | None,
) -> GoldLine | None:
    """Fit a line through two points, or ``None`` on degenerate inputs.

    Degenerate means: either value is missing, or the two x values are closer
    together than :data:`MIN_X_SEPARATION` (the slope would be meaningless).
    """
    if x1 is None or x2 is None or y1 is None or y2 is None:
        return None
    if abs(x1 - x2) < MIN_X_SEPARATION:
        return None
    slope = (y1 - y2) / (x1 - x2)
    intercept = y1 - (slope * x1)
    return GoldLine(slope=slope, intercept=intercept)


def evaluate(line: GoldLine | None, x: float | None) -> float | None:
    """Value of the line at ``x``, or ``None`` when either input is missing."""
    if line is None or x is None:
        return None
    return (line.slope * x) + line.intercept


def x_for_value(line: GoldLine | None, y: float | None) -> float | None:
    """Invert the line: the x at which it reaches ``y``.

    Returns ``None`` when the line is missing, the target is missing, or the
    slope is flat enough that the inversion is undefined.
    """
    if line is None or y is None:
        return None
    if abs(line.slope) <= MIN_INVERTIBLE_SLOPE:
        return None
    return (y - line.intercept) / line.slope
