"""Geometry contract for the shared grouped bar builder.

The builder is used for both the up/down beta chart (mixed sign) and the
downside comparison (all negative). Those two need OPPOSITE baseline treatment,
and getting one right previously broke the other: reserving label room beneath
downward bars is necessary when every value is negative, but applying it to a
mixed-sign chart shortens the downward bars alone, so equal magnitudes draw
unequal lengths and the chart misstates its own data.

These tests pin the geometry directly off the emitted SVG rather than trusting a
visual check, because the failure is a quiet few-pixel asymmetry rather than
anything that looks broken.
"""

from __future__ import annotations

import re

from golden_vector.serve.charts import _build_grouped_beta_bar_svg


def _bar_rects(svg: str) -> list[dict[str, float]]:
    """Every data rect in draw order, with its geometry."""

    return [
        {
            "x": float(m.group("x")),
            "y": float(m.group("y")),
            "height": float(m.group("h")),
        }
        for m in re.finditer(
            r'<rect x="(?P<x>[-\d.]+)" y="(?P<y>[-\d.]+)" width="[\d.]+" '
            r'height="(?P<h>[-\d.]+)" class="series-',
            svg,
        )
    ]


def _group(label: str, *values: float | None) -> dict[str, object]:
    return {
        "label": label,
        "bars": [
            {"label": f"s{i}", "value": value, "series": "stock"}
            for i, value in enumerate(values)
        ],
    }


def test_equal_magnitudes_draw_equal_lengths_when_both_signs_are_present():
    """A +0.5 and a -0.5 must be the same length.

    This is the regression guard: the all-negative layout reserves 18px under the
    bars for their labels, and letting that reservation leak into the mixed-sign
    path made every downward bar shorter than its upward twin — down beta would
    have looked milder than an identical up beta on the same chart.
    """

    svg = _build_grouped_beta_bar_svg(groups=[_group("Beta", 0.5, -0.5)])
    rects = _bar_rects(svg)

    assert len(rects) == 2
    up, down = rects
    assert up["height"] == down["height"], (
        "equal magnitudes drew unequal bars: "
        f"up={up['height']} down={down['height']}"
    )


def test_all_negative_data_uses_the_full_canvas_instead_of_half_of_it():
    """With no positive side, a centred baseline wastes the whole upper half.

    The severity comparison is entirely negative. Centring left its bars crushed
    into the bottom half with their labels colliding with the series labels, so
    the all-negative case anchors at the top. The control is the mixed-sign
    chart above: this must not be achieved by simply making every chart taller.
    """

    all_negative = _build_grouped_beta_bar_svg(
        groups=[_group("Loss", -0.174, -0.126)]
    )
    mixed = _build_grouped_beta_bar_svg(groups=[_group("Beta", 0.174, -0.126)])

    deepest = max(r["height"] for r in _bar_rects(all_negative))
    mixed_deepest = max(r["height"] for r in _bar_rects(mixed))

    # The all-negative chart gives its longest bar substantially more room than
    # the centred layout would have done for the same magnitude.
    assert deepest > mixed_deepest * 1.5


def test_a_missing_value_is_not_drawn_as_a_zero_bar():
    """``None`` means "not available", which is not the same as a measured zero."""

    svg = _build_grouped_beta_bar_svg(groups=[_group("Beta", 0.4, None)])

    assert len(_bar_rects(svg)) == 1
    assert "n/a" in svg


def test_the_caller_supplies_its_own_units_and_wording():
    """Percentages and betas share the geometry but never the labels."""

    svg = _build_grouped_beta_bar_svg(
        groups=[_group("Full history", 0.217)],
        value_formatter=lambda value: f"{value * 100:.1f}%",
        aria_label="How often a large fall happened",
    )

    assert "21.7%" in svg
    assert "0.22" not in svg  # the beta default must not leak through
    assert 'aria-label="How often a large fall happened"' in svg


def test_an_empty_chart_says_so_in_the_caller_s_words():
    svg = _build_grouped_beta_bar_svg(
        groups=[], empty_message="No comparison evidence was published."
    )

    assert "No comparison evidence was published." in svg
    assert "beta" not in svg.lower()
