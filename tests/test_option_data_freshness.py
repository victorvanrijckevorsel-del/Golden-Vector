"""The ONE option-staleness authority and the generation-carry resolution.

Two promises are pinned here:

* the "how many US trading days is too old" number lives once, in config. Every
  screen keys off the STALE status the shared classifier emits, so no render
  site can restate (and drift from) the threshold;
* the per-ticker ``display_*`` columns are BUILD-time output. A carried-forward
  generation never rebuilds them, so a page that trusted them alone would show
  a week-old chain as "LATEST". The resolution shows the worse of the two ages.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from golden_vector.app import market_hours_refresh
from golden_vector.app.market_hours_refresh import (
    OPTION_FRESHNESS_LATEST,
    OPTION_FRESHNESS_STALE,
    OPTION_FRESHNESS_STORED,
    classify_us_trading_day_freshness,
)
from golden_vector.contracts.config_models import OPTION_STALENESS_WARNING_TRADING_DAYS
from golden_vector.serve.option_data_freshness import (
    OptionGenerationFreshness,
    OptionRowFreshness,
    option_generation_freshness,
    option_generation_freshness_from_manifest,
    resolve_option_row_freshness,
    stored_snapshot_warning,
)


# ---------------------------------------------------------------------------
# 1. one threshold, one comparison
# ---------------------------------------------------------------------------


def test_the_classifier_is_the_only_place_the_threshold_is_compared():
    classifier_source = Path("golden_vector/app/market_hours_refresh.py").read_text(
        encoding="utf-8"
    )

    # The classifier consumes the config constant; it does not own a twin.
    assert (
        market_hours_refresh.OPTION_STALENESS_WARNING_TRADING_DAYS
        == OPTION_STALENESS_WARNING_TRADING_DAYS
    )
    assert "OPTION_STALENESS_WARNING_TRADING_DAYS = " not in classifier_source
    assert "< OPTION_STALENESS_WARNING_TRADING_DAYS" in classifier_source

    for module in (
        "golden_vector/serve/option_data_freshness.py",
        "golden_vector/serve/overview_option_trading.py",
        "golden_vector/serve/ticker_page/options.py",
        "golden_vector/serve/candidate_finder_page.py",
        "golden_vector/app/market_hours_refresh.py",
        "golden_vector/app/scheduled_refresh.py",
    ):
        source = Path(module).read_text(encoding="utf-8")
        for forbidden in (
            ">= 3",
            "> 2",
            "< 3",
            "<= 2",
            "least 3 US",
            "is 3 US",
            "3 US trading days",
        ):
            assert forbidden not in source, f"{module}: {forbidden}"


def test_the_stale_boundary_follows_the_configured_threshold():
    """The status flips exactly AT the configured number of trading days.

    Walked from a fixed Friday so weekends cannot make the count ambiguous.
    """

    source = date(2026, 8, 7)  # Friday
    trading_days = [
        date(2026, 8, 10),
        date(2026, 8, 11),
        date(2026, 8, 12),
        date(2026, 8, 13),
    ]
    verdicts = [
        classify_us_trading_day_freshness(source, through_date=day)
        for day in trading_days
    ]

    for verdict in verdicts:
        expected = (
            OPTION_FRESHNESS_STALE
            if verdict.trading_days >= OPTION_STALENESS_WARNING_TRADING_DAYS
            else OPTION_FRESHNESS_STORED
        )
        assert verdict.status == expected, verdict


def test_the_warning_keys_off_the_status_not_the_number():
    """A big number with a non-stale status must NOT warn, and vice versa.

    This is what stops a second threshold comparison from creeping back into a
    render site: the wording never decides staleness, it only reports it.
    """

    assert stored_snapshot_warning(
        OptionRowFreshness(trading_days=9, status=OPTION_FRESHNESS_STORED)
    ) is None
    assert stored_snapshot_warning(
        OptionRowFreshness(trading_days=1, status=OPTION_FRESHNESS_LATEST)
    ) is None
    assert stored_snapshot_warning(None) is None

    warning = stored_snapshot_warning(
        OptionRowFreshness(trading_days=4, status=OPTION_FRESHNESS_STALE)
    )
    assert warning is not None
    assert "4 US trading days old" in warning


def test_a_stale_verdict_without_a_number_still_warns():
    warning = stored_snapshot_warning(
        OptionRowFreshness(trading_days=None, status=OPTION_FRESHNESS_STALE)
    )

    assert warning is not None
    assert "too old to trade from" in warning


# ---------------------------------------------------------------------------
# 2. generation carry
# ---------------------------------------------------------------------------


def test_only_a_carried_generation_is_aged():
    fresh = option_generation_freshness(
        freshness_status="OK", as_of_date="2026-01-02", through_date=date(2026, 3, 2)
    )

    assert fresh == OptionGenerationFreshness(carried_forward=False)
    assert fresh.stale is False


def test_a_carried_generation_is_aged_through_the_shared_classifier():
    generation = option_generation_freshness(
        freshness_status="carried_forward",  # case/whitespace tolerant
        as_of_date="2026-08-07",
        through_date=date(2026, 8, 12),
    )

    assert generation.carried_forward is True
    assert generation.trading_days == 3
    assert generation.status == OPTION_FRESHNESS_STALE
    assert generation.stale is True


def test_the_manifest_entry_point_reads_the_option_freshness_domain():
    generation = option_generation_freshness_from_manifest(
        {
            "state": "complete",
            "freshness_domains": {
                "option_artifacts": {
                    "status": "CARRIED_FORWARD",
                    "as_of_date": "2026-08-07",
                }
            },
        },
        through_date=date(2026, 8, 12),
    )

    assert (generation.carried_forward, generation.trading_days) == (True, 3)
    # A manifest with no freshness domain (or none at all) is simply not carried.
    assert option_generation_freshness_from_manifest(None).carried_forward is False
    assert option_generation_freshness_from_manifest({}).carried_forward is False


@pytest.mark.parametrize(
    "row_days,row_status,generation_days,expected_days,expected_stale",
    [
        # The reported bug: the row's columns are frozen at build time.
        (0, OPTION_FRESHNESS_LATEST, 4, 4, True),
        (0, OPTION_FRESHNESS_LATEST, 1, 1, False),
        # The row's own verdict is never thrown away.
        (5, OPTION_FRESHNESS_STALE, 1, 5, True),
        # A row with no stamped columns at all still gets the generation's age.
        (None, None, 3, 3, True),
    ],
)
def test_the_worse_of_the_row_and_the_generation_is_shown(
    row_days, row_status, generation_days, expected_days, expected_stale
):
    generation = OptionGenerationFreshness(
        carried_forward=True,
        trading_days=generation_days,
        status=(
            OPTION_FRESHNESS_STALE
            if generation_days >= OPTION_STALENESS_WARNING_TRADING_DAYS
            else OPTION_FRESHNESS_STORED
        ),
    )
    resolved = resolve_option_row_freshness(
        trading_days=row_days,
        status=row_status,
        carried_forward=False,
        generation=generation,
    )

    assert resolved.trading_days == expected_days
    assert resolved.stale is expected_stale
    # A carried generation makes every row it serves a stored snapshot.
    assert resolved.carried_forward is True


def test_a_current_generation_leaves_the_row_verdict_untouched():
    resolved = resolve_option_row_freshness(
        trading_days=2,
        status=OPTION_FRESHNESS_STORED,
        carried_forward=False,
        generation=OptionGenerationFreshness(carried_forward=False),
    )

    assert resolved == OptionRowFreshness(
        trading_days=2, status=OPTION_FRESHNESS_STORED, carried_forward=False
    )
    assert resolved.stale is False
