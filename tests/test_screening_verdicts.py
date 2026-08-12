from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.verdicts import (
    FORWARD_PE_NON_POSITIVE_CODE,
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
    assert result["fundamental_check_fail_codes"] == "RESERVE_LIFE_FAIL"


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
    # N/A is not a failure — only the genuinely failed check earns a code.
    assert result["fundamental_check_fail_codes"] == "DATA_COMPLETE_FAIL"


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


def test_compute_fundamental_checks_emits_forward_pe_fail_code():
    thresholds = load_app_config(ProjectPaths.discover()).app.screening_params.verdict_thresholds
    all_pass_layer1 = {
        "data_complete": "PASS",
        "aisc": "PASS",
        "margin": "PASS",
        "aisc_margin_yield": "PASS",
        "reserve_life": "PASS",
        "leverage": "PASS",
    }

    failing = compute_fundamental_checks(
        layer1_check_statuses=all_pass_layer1,
        forward_pe=thresholds.strong_candidate_forward_pe_max + 1.0,
        thresholds=thresholds,
    )
    assert failing["fundamental_check_fail_codes"] == "FORWARD_PE_FAIL"

    healthy = compute_fundamental_checks(
        layer1_check_statuses=all_pass_layer1,
        forward_pe=thresholds.strong_candidate_forward_pe_max - 1.0,
        thresholds=thresholds,
    )
    assert healthy["fundamental_check_fail_codes"] is None


def test_non_positive_forward_pe_earns_its_own_code_not_the_threshold_code():
    """Two different failures, two different codes: a P/E built on non-positive
    earnings is not a multiple that was compared with the cut-off. Consumers
    route on the code, so the distinction must exist HERE and not be re-derived
    downstream from the value. The FAIL status itself is unchanged, so the
    counts and the display summary keep their existing meaning."""
    thresholds = load_app_config(ProjectPaths.discover()).app.screening_params.verdict_thresholds
    all_pass_layer1 = {
        "data_complete": "PASS",
        "aisc": "PASS",
        "margin": "PASS",
        "aisc_margin_yield": "PASS",
        "reserve_life": "PASS",
        "leverage": "PASS",
    }

    for value in (-4.2, 0.0):
        result = compute_fundamental_checks(
            layer1_check_statuses=all_pass_layer1,
            forward_pe=value,
            thresholds=thresholds,
        )
        assert result["fundamental_check_fail_codes"] == FORWARD_PE_NON_POSITIVE_CODE, value
        # the status vocabulary is untouched: it is still one failed check
        assert "Forward P/E FAIL" in result["fundamental_check_summary"], value
        assert result["fundamental_checks_passed"] == 6, value

    # the control: a positive P/E above the cut-off keeps the threshold code
    above = compute_fundamental_checks(
        layer1_check_statuses=all_pass_layer1,
        forward_pe=thresholds.strong_candidate_forward_pe_max + 1.0,
        thresholds=thresholds,
    )
    assert above["fundamental_check_fail_codes"] == "FORWARD_PE_FAIL"
