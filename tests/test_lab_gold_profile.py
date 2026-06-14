"""v2 gold-profile tilt label: config validation, the build-side equal-weighted
tilt math + the three label statuses, the persisted artifact contract, and the
config-hash staleness wiring. The label is build-decided and honest by
construction — null unless both sides clear the usable-bucket floor."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import GoldProfileConfig
from golden_vector.lab.conditional_dial import (
    DIAL_BENCHMARKS,
    DIAL_HORIZONS_WEEKS,
    PROFILE_COLUMNS,
    build_profile_artifact,
    cell_bucket_is_usable,
    default_gold_profile_config,
    dial_config_hash,
)


def _cells(rows):
    """rows: (ticker, bucket, horizon, shrunk, insufficient) -> a minimal wide
    cells frame with just the columns the profile build reads."""
    return pd.DataFrame(
        [
            {
                "ticker": t,
                "bucket": bk,
                "horizon_weeks": h,
                "p_beat_gdx": s,
                "p_beat_gdx_shrunk": s,
                "gdx_insufficient_history": ins,
            }
            for (t, bk, h, s, ins) in rows
        ]
    )


def _one(cells, **kw):
    df = build_profile_artifact(cells, horizons=[13], benchmarks=["GDX"], **kw)
    assert len(df) == 1
    return df.iloc[0].to_dict()


# ---- config validation -------------------------------------------------------


def test_default_config_loads_from_yaml_and_validates() -> None:
    cfg = default_gold_profile_config()
    assert cfg.tilt_threshold == 0.10
    assert cfg.down_buckets == ["gold_down_big", "gold_down"]
    assert cfg.up_buckets == ["gold_up", "gold_up_big"]
    assert cfg.default_profile_horizon == 13


# (GoldProfileConfig field validation — threshold/min-bucket/disjoint/unknown-name
# — lives with the other config models in tests/test_config_models.py.)


# ---- the tilt math + the three statuses --------------------------------------


def test_defensive_tilt_is_equal_weighted_down_minus_up() -> None:
    r = _one(
        _cells(
            [
                ("A", "gold_down_big", 13, 0.9, False),
                ("A", "gold_down", 13, 0.7, False),
                ("A", "gold_up", 13, 0.3, False),
                ("A", "gold_up_big", 13, 0.1, False),
            ]
        )
    )
    assert r["down_mean_p_beat"] == 0.8  # equal-weighted (0.9 + 0.7) / 2
    assert r["up_mean_p_beat"] == 0.2  # (0.3 + 0.1) / 2
    assert r["gold_tilt"] == 0.6
    assert r["gold_tilt_label"] == "Defensive"
    assert r["label_status"] == "OK"
    assert r["usable_down_bucket_count"] == 2
    assert r["usable_up_bucket_count"] == 2
    assert set(r["used_buckets"].split(",")) == {
        "gold_down_big", "gold_down", "gold_up", "gold_up_big"
    }


def test_equal_weighting_not_episode_weighting() -> None:
    """A down bucket cannot dominate by having more episodes — the build sees only
    one shrunk number per bucket and averages buckets equally."""
    r = _one(
        _cells(
            [
                ("A", "gold_down_big", 13, 1.0, False),
                ("A", "gold_down", 13, 0.0, False),
                ("A", "gold_up", 13, 0.4, False),
            ]
        )
    )
    assert r["down_mean_p_beat"] == 0.5  # (1.0 + 0.0) / 2, not weighted by anything


def test_threshold_edges_are_inclusive() -> None:
    defensive = _one(
        _cells([("A", "gold_down", 13, 0.6, False), ("A", "gold_up", 13, 0.5, False)])
    )
    assert defensive["gold_tilt"] == 0.1  # exactly +threshold
    assert defensive["gold_tilt_label"] == "Defensive"

    pro = _one(
        _cells([("A", "gold_down", 13, 0.4, False), ("A", "gold_up", 13, 0.5, False)])
    )
    assert pro["gold_tilt"] == -0.1  # exactly -threshold
    assert pro["gold_tilt_label"] == "Pro-cyclical"

    steady = _one(
        _cells([("A", "gold_down", 13, 0.55, False), ("A", "gold_up", 13, 0.50, False)])
    )
    assert steady["gold_tilt_label"] == "Steady"


def test_one_sided_history_is_insufficient_not_labelled() -> None:
    r = _one(
        _cells(
            [
                ("A", "gold_down", 13, 0.7, False),
                ("A", "gold_up", 13, 0.0, True),  # up bucket insufficient
            ]
        )
    )
    assert r["label_status"] == "INSUFFICIENT_CROSS_SCENARIO_HISTORY"
    assert pd.isna(r["gold_tilt"])
    assert pd.isna(r["gold_tilt_label"])
    assert r["usable_down_bucket_count"] == 1
    assert r["usable_up_bucket_count"] == 0


def test_null_shrunk_bucket_is_excluded_from_the_mean() -> None:
    r = _one(
        _cells(
            [
                ("A", "gold_down_big", 13, float("nan"), False),  # NaN shrunk, not flagged
                ("A", "gold_down", 13, 0.7, False),
                ("A", "gold_up", 13, 0.3, False),
            ]
        )
    )
    assert r["usable_down_bucket_count"] == 1  # the NaN-shrunk down bucket is dropped
    assert r["down_mean_p_beat"] == 0.7
    assert r["label_status"] == "OK"


def test_missing_components_when_no_down_up_cells() -> None:
    r = _one(_cells([("A", "gold_flat", 13, 0.5, False)]))
    assert r["label_status"] == "MISSING_COMPONENTS"
    assert pd.isna(r["gold_tilt_label"])
    assert r["usable_down_bucket_count"] == 0
    assert r["usable_up_bucket_count"] == 0


def test_present_but_all_insufficient_is_insufficient_not_missing() -> None:
    """The MISSING vs INSUFFICIENT split: down/up rows PRESENT but all flagged
    insufficient is INSUFFICIENT (thin history), not MISSING (no rows at all)."""
    r = _one(
        _cells(
            [
                ("A", "gold_down", 13, 0.0, True),  # present, but insufficient
                ("A", "gold_up", 13, 0.0, True),
            ]
        )
    )
    assert r["label_status"] == "INSUFFICIENT_CROSS_SCENARIO_HISTORY"
    assert r["usable_down_bucket_count"] == 0
    assert r["usable_up_bucket_count"] == 0


def test_threshold_just_below_is_steady_and_label_uses_rounded_tilt() -> None:
    """The interior boundary + the design choice that the label is decided on the
    ROUNDED tilt, so the persisted number and the word can never disagree."""
    steady = _one(
        _cells([("A", "gold_down", 13, 0.599, False), ("A", "gold_up", 13, 0.500, False)])
    )
    assert abs(steady["gold_tilt"] - 0.099) < 1e-9  # just inside the threshold
    assert steady["gold_tilt_label"] == "Steady"
    # A raw tilt 0.0999996 rounds to exactly 0.10 at 6dp -> Defensive, and the
    # persisted tilt equals the rounded value the label was decided on.
    edge = _one(
        _cells([("A", "gold_down", 13, 0.5999996, False), ("A", "gold_up", 13, 0.5, False)])
    )
    assert edge["gold_tilt"] == 0.1
    assert edge["gold_tilt_label"] == "Defensive"


def test_label_tracks_the_configured_threshold_not_a_constant() -> None:
    """The label boundary must read cfg.tilt_threshold, not a hardcoded 0.10 twin:
    a tilt of 0.15 is Defensive at the default 0.10 but Steady at a 0.20 threshold."""
    cells = _cells([("A", "gold_down", 13, 0.65, False), ("A", "gold_up", 13, 0.50, False)])
    assert _one(cells)["gold_tilt_label"] == "Defensive"  # default 0.10
    relaxed = _one(cells, config=GoldProfileConfig(tilt_threshold=0.20))
    assert abs(relaxed["gold_tilt"] - 0.15) < 1e-9
    assert relaxed["gold_tilt_label"] == "Steady"  # 0.15 < 0.20
    assert relaxed["tilt_threshold"] == 0.20  # the configured threshold is persisted


def test_cell_bucket_is_usable_is_na_safe() -> None:
    """pd.NA in the flag or the shrunk value must read as 'not usable', never crash
    (bool(pd.NA) / NA == NA would otherwise raise)."""
    assert (
        cell_bucket_is_usable(
            {"gdx_insufficient_history": pd.NA, "p_beat_gdx_shrunk": 0.7}, "GDX"
        )
        is False
    )
    assert (
        cell_bucket_is_usable(
            {"gdx_insufficient_history": False, "p_beat_gdx_shrunk": pd.NA}, "GDX"
        )
        is False
    )


def test_defensive_and_procyclical_survive_persist_and_read(tmp_path) -> None:
    """End-to-end for the NON-trivial labels (the parity fixture only yields Steady):
    build -> parquet -> the exact reader load_ticker_curve uses -> the literal label.
    Guards against a wrong-column / renamed-key read that a Steady-only fixture can't
    catch."""
    from golden_vector.lab.conditional_dial import DIAL_PROFILE_FILENAME
    from golden_vector.serve.lab_curve_data import _ticker_profile_label

    cells = _cells(
        [
            ("DEF", "gold_down_big", 13, 0.9, False), ("DEF", "gold_down", 13, 0.9, False),
            ("DEF", "gold_up", 13, 0.1, False), ("DEF", "gold_up_big", 13, 0.1, False),
            ("PRO", "gold_down_big", 13, 0.1, False), ("PRO", "gold_down", 13, 0.1, False),
            ("PRO", "gold_up", 13, 0.9, False), ("PRO", "gold_up_big", 13, 0.9, False),
        ]
    )
    profile = build_profile_artifact(cells, horizons=[13], benchmarks=["GDX"])
    path = tmp_path / DIAL_PROFILE_FILENAME
    profile.to_parquet(path, index=False)
    frame = pd.read_parquet(path)

    defn = _ticker_profile_label(frame, ticker="DEF", horizon=13, benchmark="GDX")
    pro = _ticker_profile_label(frame, ticker="PRO", horizon=13, benchmark="GDX")
    assert defn["label_status"] == "OK" and defn["gold_tilt_label"] == "Defensive"
    assert pro["label_status"] == "OK" and pro["gold_tilt_label"] == "Pro-cyclical"
    assert defn["gold_tilt"] > 0 and pro["gold_tilt"] < 0  # real numbers, not NaN/None


def test_label_and_tilt_are_null_unless_status_ok() -> None:
    df = build_profile_artifact(
        _cells(
            [
                ("A", "gold_down", 13, 0.7, False),
                ("A", "gold_up", 13, 0.0, True),  # -> INSUFFICIENT
                ("B", "gold_flat", 13, 0.5, False),  # -> MISSING_COMPONENTS
            ]
        ),
        horizons=[13],
        benchmarks=["GDX"],
    )
    for _, row in df.iterrows():
        if row["label_status"] != "OK":
            assert pd.isna(row["gold_tilt_label"])
            assert pd.isna(row["gold_tilt"])


def test_cell_bucket_is_usable_rule() -> None:
    assert cell_bucket_is_usable(
        {"gdx_insufficient_history": False, "p_beat_gdx_shrunk": 0.7}, "GDX"
    )
    assert not cell_bucket_is_usable(
        {"gdx_insufficient_history": True, "p_beat_gdx_shrunk": 0.7}, "GDX"
    )
    assert not cell_bucket_is_usable(
        {"gdx_insufficient_history": False, "p_beat_gdx_shrunk": float("nan")}, "GDX"
    )
    assert not cell_bucket_is_usable(None, "GDX")
    assert not cell_bucket_is_usable({}, "GDX")  # missing flag -> not usable


# ---- artifact contract + staleness ------------------------------------------


def test_profile_artifact_has_exact_required_columns() -> None:
    df = build_profile_artifact(
        _cells([("A", "gold_down", 13, 0.7, False), ("A", "gold_up", 13, 0.3, False)]),
        horizons=[13],
        benchmarks=["GDX"],
    )
    assert list(df.columns) == PROFILE_COLUMNS


def test_one_row_per_ticker_horizon_benchmark() -> None:
    df = build_profile_artifact(
        _cells(
            [
                ("A", "gold_down", 13, 0.7, False),
                ("A", "gold_up", 13, 0.3, False),
                ("A", "gold_down", 26, 0.6, False),
                ("A", "gold_up", 26, 0.4, False),
            ]
        ),
        horizons=[13, 26],
        benchmarks=["GDX"],
    )
    assert len(df) == 2  # (A,13,GDX) and (A,26,GDX)
    assert set(df["horizon_weeks"]) == {13, 26}


def test_empty_cells_yields_empty_profile_with_columns() -> None:
    df = build_profile_artifact(
        pd.DataFrame(), horizons=[13], benchmarks=["GDX"]
    )
    assert df.empty
    assert list(df.columns) == PROFILE_COLUMNS


def test_changing_tilt_threshold_changes_the_config_hash() -> None:
    """The contract's staleness guarantee: editing any gold-profile threshold must
    invalidate the artifact (different config hash), not silently reinterpret old
    labels."""
    base = dial_config_hash(DIAL_HORIZONS_WEEKS, DIAL_BENCHMARKS)
    changed_threshold = dial_config_hash(
        DIAL_HORIZONS_WEEKS, DIAL_BENCHMARKS, GoldProfileConfig(tilt_threshold=0.2)
    )
    changed_floor = dial_config_hash(
        DIAL_HORIZONS_WEEKS, DIAL_BENCHMARKS, GoldProfileConfig(min_usable_up_buckets=2)
    )
    assert base != changed_threshold
    assert base != changed_floor
    # The stamped config_hash on the artifact equals the live one (round-trips).
    assert build_profile_artifact(
        _cells([("A", "gold_down", 13, 0.7, False), ("A", "gold_up", 13, 0.3, False)]),
        horizons=DIAL_HORIZONS_WEEKS,
        benchmarks=DIAL_BENCHMARKS,
    ).iloc[0]["config_hash"] == base
