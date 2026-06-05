import pandas as pd
import pytest

from golden_vector.common.parquet import ParquetSchemaError, read_required_parquet


def test_read_required_parquet_validates_required_columns_and_schema_version(tmp_path):
    path = tmp_path / "artifact.parquet"
    pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "schema_version": 1,
                "source_run_id": "run-1",
            }
        ]
    ).to_parquet(path, index=False)

    frame = read_required_parquet(
        path,
        label="test artifact",
        required_columns=("ticker", "source_run_id"),
        schema_version=1,
    )

    assert frame["ticker"].tolist() == ["AEM"]


def test_read_required_parquet_raises_one_schema_error_for_missing_columns(tmp_path):
    path = tmp_path / "artifact.parquet"
    pd.DataFrame([{"ticker": "AEM", "schema_version": 1}]).to_parquet(
        path,
        index=False,
    )

    with pytest.raises(
        ParquetSchemaError,
        match="test artifact schema validation failed: missing columns: source_run_id",
    ):
        read_required_parquet(
            path,
            label="test artifact",
            required_columns=("ticker", "source_run_id"),
            schema_version=1,
        )


def test_read_required_parquet_validates_schema_version_from_attrs_on_empty_frame(tmp_path):
    path = tmp_path / "empty_artifact.parquet"
    frame = pd.DataFrame(
        {
            "schema_version": pd.Series(dtype="object"),
            "source_run_id": pd.Series(dtype="object"),
        }
    )
    frame.attrs["schema_version"] = 2
    frame.to_parquet(path, index=False)

    with pytest.raises(
        ParquetSchemaError,
        match="schema_version expected 1, got 2",
    ):
        read_required_parquet(
            path,
            label="empty artifact",
            required_columns=("schema_version", "source_run_id"),
            schema_version=1,
        )


def test_read_required_parquet_rejects_mixed_schema_versions(tmp_path):
    path = tmp_path / "mixed_schema.parquet"
    pd.DataFrame(
        [
            {"ticker": "AEM", "schema_version": 1, "source_run_id": "run-1"},
            {"ticker": "NEM", "schema_version": 2, "source_run_id": "run-1"},
        ]
    ).to_parquet(path, index=False)

    with pytest.raises(
        ParquetSchemaError,
        match="schema_version expected 1, got multiple values: 1, 2",
    ):
        read_required_parquet(
            path,
            label="mixed artifact",
            required_columns=("ticker", "source_run_id"),
            schema_version=1,
        )
