from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.verdicts import compute_tool_b_score, determine_screening_verdict


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


def test_compute_tool_b_score_handles_incomplete_and_clips_extreme_upside_values():
    assert compute_tool_b_score(screening_verdict="INCOMPLETE", best_upside_pct=0.8) is None

    capped_high = compute_tool_b_score(screening_verdict="WATCHLIST", best_upside_pct=3.0)
    capped_low = compute_tool_b_score(screening_verdict="SCREEN_OUT", best_upside_pct=-5.0)

    assert capped_high == 72.0
    assert capped_low == 14.0
