from golden_vector.screening.schema import (
    REMOVED_TOOL_B_TARGET_COLUMNS,
    REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS,
    TOOL_B_OUTPUT_COLUMNS,
    ToolBStaleSchemaError,
    validate_tool_b_output_schema,
)
from golden_vector.screening.pipeline import YAHOO_FINANCE_SOURCE_COLUMN_MAP


def test_tool_b_schema_excludes_removed_target_and_best_fields():
    assert not REMOVED_TOOL_B_TARGET_COLUMNS.intersection(TOOL_B_OUTPUT_COLUMNS)


def test_tool_b_schema_includes_simple_fundamental_fields():
    assert REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS.issubset(TOOL_B_OUTPUT_COLUMNS)


def test_tool_b_schema_requires_all_yahoo_materialization_source_columns():
    assert set(YAHOO_FINANCE_SOURCE_COLUMN_MAP).issubset(TOOL_B_OUTPUT_COLUMNS)
    assert set(YAHOO_FINANCE_SOURCE_COLUMN_MAP.values()).issubset(
        REQUIRED_TOOL_B_FUNDAMENTAL_COLUMNS
    )


def test_tool_b_schema_guard_requires_our_view_comparison_columns():
    import pandas as pd

    row = {column: None for column in TOOL_B_OUTPUT_COLUMNS}
    row["ticker"] = "AEM"
    frame = pd.DataFrame([row]).drop(columns=["enterprise_value_musd_our_view"])

    try:
        validate_tool_b_output_schema(frame)
    except ToolBStaleSchemaError as exc:
        assert "enterprise_value_musd_our_view" in str(exc)
    else:
        raise AssertionError("schema guard should reject missing Our View comparison columns")


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


def test_tool_b_schema_requires_spot_gold_provenance_columns():
    """A pre-gold-dial parquet (no spot columns) must trip the calm refresh
    message, not silently pass and 500 later in a reader."""
    import pandas as pd

    spot_columns = {"gold_price_used", "spot_gold_usd", "spot_gold_date", "gold_price_basis"}
    row = {
        column: None for column in TOOL_B_OUTPUT_COLUMNS if column not in spot_columns
    }
    row["ticker"] = "AEM"
    frame = pd.DataFrame([row])

    try:
        validate_tool_b_output_schema(frame)
    except ToolBStaleSchemaError as exc:
        assert "spot_gold_usd" in str(exc)
        assert "gold_price_basis" in str(exc)
    else:
        raise AssertionError("schema guard should reject pre-spot-provenance artifacts")


def test_tool_b_schema_guard_checks_empty_stale_artifact_columns():
    import pandas as pd

    frame = pd.DataFrame(columns=["ticker", "target_price_peer_pe"])

    try:
        validate_tool_b_output_schema(frame)
    except ToolBStaleSchemaError as exc:
        assert "target_price_peer_pe" in str(exc)
    else:
        raise AssertionError("schema guard should reject empty stale artifacts")
