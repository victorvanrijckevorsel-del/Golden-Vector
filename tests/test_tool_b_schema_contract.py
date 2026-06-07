from golden_vector.screening.schema import (
    REMOVED_TOOL_B_TARGET_COLUMNS,
    REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS,
    TOOL_B_OUTPUT_COLUMNS,
    ToolBStaleSchemaError,
    validate_tool_b_output_schema,
)


def test_tool_b_schema_excludes_removed_target_and_best_fields():
    assert not REMOVED_TOOL_B_TARGET_COLUMNS.intersection(TOOL_B_OUTPUT_COLUMNS)


def test_tool_b_schema_includes_simple_fundamental_fields():
    assert REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS.issubset(TOOL_B_OUTPUT_COLUMNS)


def test_tool_b_schema_guard_rejects_any_target_upside_or_best_column():
    import pandas as pd

    row = {column: None for column in TOOL_B_OUTPUT_COLUMNS}
    row["ticker"] = "AEM"
    frame = pd.DataFrame([{**row, "target_price_new_variant": 123.0}])

    try:
        validate_tool_b_output_schema(frame)
    except ToolBStaleSchemaError as exc:
        assert "target_price_new_variant" in str(exc)
    else:
        raise AssertionError("schema guard should reject target-price columns")


def test_tool_b_schema_guard_checks_empty_stale_artifact_columns():
    import pandas as pd

    frame = pd.DataFrame(columns=["ticker", "target_price_peer_pe"])

    try:
        validate_tool_b_output_schema(frame)
    except ToolBStaleSchemaError as exc:
        assert "target_price_peer_pe" in str(exc)
    else:
        raise AssertionError("schema guard should reject empty stale artifacts")
