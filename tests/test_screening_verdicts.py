from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.verdicts import (
    compute_fundamental_checks,
    determine_screening_verdict,
)


def test_determine_screening_verdict_prioritizes_incomplete_inputs():
    thresholds = load_app_config(ProjectPaths.discover()).app.screening_params.verdict_thresholds

    assert determine_screening_verdict(
        confidence="INCOMPLETE",
        layer1_status="PASS",
        forward_pe=5.0,
        thresholds=thresholds,
    ) == "INCOMPLETE"
    assert determine_screening_verdict(
        confidence="VERIFIED",
        layer1_status="INCOMPLETE",
        forward_pe=5.0,
        thresholds=thresholds,
    ) == "INCOMPLETE"


def test_determine_screening_verdict_distinguishes_strong_candidate_watchlist_and_screen_out():
    thresholds = load_app_config(ProjectPaths.discover()).app.screening_params.verdict_thresholds

    assert determine_screening_verdict(
        confidence="VERIFIED",
        layer1_status="PASS",
        forward_pe=7.0,
        thresholds=thresholds,
    ) == "STRONG_CANDIDATE"
    assert determine_screening_verdict(
        confidence="ESTIMATED",
        layer1_status="FAIL",
        forward_pe=9.0,
        thresholds=thresholds,
    ) == "WATCHLIST"
    assert determine_screening_verdict(
        confidence="VERIFIED",
        layer1_status="PASS",
        forward_pe=12.0,
        thresholds=thresholds,
    ) == "SCREEN_OUT"


def test_compute_fundamental_checks_counts_visible_passes():
    thresholds = load_app_config(ProjectPaths.discover()).app.screening_params.verdict_thresholds

    result = compute_fundamental_checks(
        layer1_check_statuses={
            "data_complete": "PASS",
            "aisc": "PASS",
            "margin": "PASS",
            "aisc_margin_yield": "PASS",
            "reserve_life": "FAIL",
            "leverage": "PASS",
        },
        forward_pe=7.0,
        thresholds=thresholds,
    )

    assert result["fundamental_checks_passed"] == 6
    assert result["fundamental_checks_total"] == 7
    assert result["fundamental_check_score"] == 85.7143
    assert result["fundamental_check_summary"].startswith("6/7:")
    assert "Reserve life FAIL" in result["fundamental_check_summary"]


def test_compute_fundamental_checks_marks_missing_forward_pe_as_not_passed():
    thresholds = load_app_config(ProjectPaths.discover()).app.screening_params.verdict_thresholds

    result = compute_fundamental_checks(
        layer1_check_statuses={
            "data_complete": "FAIL",
            "aisc": "N/A",
            "margin": "N/A",
            "aisc_margin_yield": "N/A",
            "reserve_life": "N/A",
            "leverage": "N/A",
        },
        forward_pe=None,
        thresholds=thresholds,
    )

    assert result["fundamental_checks_passed"] == 0
    assert result["fundamental_check_score"] == 0.0
    assert "Forward P/E N/A" in result["fundamental_check_summary"]


def test_compute_fundamental_checks_uses_strong_pe_cutoff_not_watchlist_cutoff():
    thresholds = load_app_config(ProjectPaths.discover()).app.screening_params.verdict_thresholds

    result = compute_fundamental_checks(
        layer1_check_statuses={
            "data_complete": "PASS",
            "aisc": "PASS",
            "margin": "PASS",
            "aisc_margin_yield": "PASS",
            "reserve_life": "PASS",
            "leverage": "PASS",
        },
        forward_pe=9.0,
        thresholds=thresholds,
    )

    assert determine_screening_verdict(
        confidence="VERIFIED",
        layer1_status="FAIL",
        forward_pe=9.0,
        thresholds=thresholds,
    ) == "WATCHLIST"
    assert result["fundamental_checks_passed"] == 6
    assert "Forward P/E FAIL" in result["fundamental_check_summary"]
