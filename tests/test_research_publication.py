"""Publication fails closed on missing/corrupt research and excludes private data."""
import json
from pathlib import Path
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from deploy.build_research_bundle import (
    FOUNDATION_INPUTS, MANUAL, POINTER, PRIVATE_ARTIFACTS, RESEARCH_ARTIFACTS,
    build_bundle, clean_manual_store, safe_source,
)
from golden_vector.common.files import sha256_file
from golden_vector.screening.manual_store import _create_schema


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    def write(relative, content):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path
    foundation = {}
    for key in FOUNDATION_INPUTS:
        relative = f"data/runs/fixture/snapshots/{key}.parquet"
        write(relative, b"fixture")
        foundation[key] = relative
    artifacts = {}
    for name in RESEARCH_ARTIFACTS | PRIVATE_ARTIFACTS:
        if name in PRIVATE_ARTIFACTS or name == "benchmark_betas":
            relative = f"data/output/portfolio/{name}_fixture.parquet"
        else:
            relative = f"data/output/research/{name}_fixture.parquet"
        path = write(relative, b"PRIVATE_HOLDINGS" if name in PRIVATE_ARTIFACTS else b"fixture")
        if name == "benchmark_betas":
            pq.write_table(pa.table({"benchmark_ticker": ["GDX", "GDXJ"]}), path)
        elif name == "foundation":
            path.write_text(json.dumps(foundation))
        elif name == "options":
            path.write_text(json.dumps({"snapshots": [], "benchmark_snapshot_paths": []}))
        artifacts[name] = {"path": relative, "usable": True, "immutable": True, "sha256": sha256_file(path)}
    db_path = root / MANUAL
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as db:
        _create_schema(db)
        db.execute("INSERT INTO company_inputs (ticker,production_oz) VALUES ('NEM',123)")
        db.execute("INSERT INTO source_verification (ticker,field_name,verification_status,notes) VALUES ('NEM','production_oz','verified','PRIVATE_VERIFICATION')")
        db.execute("INSERT INTO reporting_calendar (ticker,notes) VALUES ('NEM','PRIVATE_CALENDAR')")
        db.execute("INSERT INTO stock_notes (ticker,note_text,note_status,created_at_utc,updated_at_utc) VALUES ('NEM','PRIVATE_STOCK_NOTE','open','date','date')")
    model = {"state": "complete", "alignment": {"status": "OK", "portfolio_artifact_refresh_run_ids": {"portfolio_positions": ["fixture"]}},
             "artifacts": artifacts, "manual_data": {"path": MANUAL, "sha256": sha256_file(db_path)},
             "parent_refresh_id": "fixture", "full_refresh_completed_at_utc": "2026-09-16T23:10:03Z",
             "freshness_domains": {"core": {"status": "OK", "as_of_date": "2026-09-16"}}}
    write(POINTER, json.dumps(model).encode())
    return root


def test_publication_preserves_verified_research_and_removes_private_content(source, tmp_path):
    original = json.loads((source / POINTER).read_text())
    before = sha256_file(source / MANUAL), sha256_file(source / POINTER)
    target = tmp_path / "publication"
    report = build_bundle(source, target)
    published = json.loads((target / POINTER).read_text())
    assert set(published["artifacts"]) == RESEARCH_ARTIFACTS
    assert published["freshness_domains"] == original["freshness_domains"]
    assert published["full_refresh_completed_at_utc"] == original["full_refresh_completed_at_utc"]
    for name in RESEARCH_ARTIFACTS:
        assert published["artifacts"][name] == original["artifacts"][name]
    assert set(report["excluded_artifacts"]) == PRIVATE_ARTIFACTS
    assert "portfolio_artifact_refresh_run_ids" not in published["alignment"]
    assert before == (sha256_file(source / MANUAL), sha256_file(source / POINTER))
    for name in PRIVATE_ARTIFACTS:
        assert not (target / original["artifacts"][name]["path"]).exists()
    assert b"PRIVATE_" not in (target / MANUAL).read_bytes()
    with sqlite3.connect(target / MANUAL) as db:
        assert db.execute("SELECT production_oz FROM company_inputs").fetchone()[0] == 123
        assert db.execute("SELECT COUNT(*) FROM stock_notes").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["corrupt", "missing", "unknown", "incomplete", "unaligned"])
def test_bad_generation_never_publishes_pointer(source, tmp_path, change):
    model = json.loads((source / POINTER).read_text())
    if change == "corrupt":
        (source / model["artifacts"]["tool_a"]["path"]).write_bytes(b"changed")
    elif change == "missing":
        model["artifacts"]["tool_a"]["path"] = "data/missing.parquet"
    elif change == "unknown":
        model["artifacts"]["future_private_artifact"] = {}
    elif change == "incomplete":
        model["state"] = "incomplete"
    else:
        model["alignment"]["status"] = "MISMATCH"
    (source / POINTER).write_text(json.dumps(model))
    target = tmp_path / "failed"
    with pytest.raises((ValueError, FileNotFoundError)):
        build_bundle(source, target)
    assert not (target / POINTER).exists()


@pytest.mark.parametrize("path", ["data/../secret.json", "/data/secret.json", "data\\secret.json", "C:/data/secret.json", "config/secret.json"])
def test_rejects_unsafe_paths(tmp_path, path):
    with pytest.raises(ValueError):
        safe_source(tmp_path, path)


def test_refuses_existing_destination_and_production_data(source, tmp_path):
    with pytest.raises(ValueError):
        build_bundle(source, source / "data/new")
    with pytest.raises(FileExistsError):
        build_bundle(source, tmp_path)
    with pytest.raises(FileExistsError):
        clean_manual_store(source / MANUAL, source / MANUAL)


def test_changed_manual_inputs_cannot_mix_with_published_research(source, tmp_path):
    with sqlite3.connect(source / MANUAL) as db:
        db.execute("UPDATE company_inputs SET production_oz=456")
    target = tmp_path / "changed-manual"
    with pytest.raises(ValueError, match="Manual inputs changed"):
        build_bundle(source, target)
    assert not (target / POINTER).exists()


def test_benchmark_chart_copy_comes_from_selected_run_not_mutable_alias(source, tmp_path):
    model = json.loads((source / POINTER).read_text())
    relative = "data/runs/fixture/snapshots/benchmarks/GDX.parquet"
    original = source / relative
    original.parent.mkdir(parents=True)
    original.write_bytes(b"selected immutable benchmark")
    alias = source / "data/intermediate/benchmarks/GDX.parquet"
    alias.parent.mkdir(parents=True)
    alias.write_bytes(b"different newer mutable history")
    options = source / model["artifacts"]["options"]["path"]
    options.write_text(json.dumps({"snapshots": [], "benchmark_snapshot_paths": [relative]}))
    model["artifacts"]["options"]["sha256"] = sha256_file(options)
    (source / POINTER).write_text(json.dumps(model))
    target = tmp_path / "benchmark-copy"
    report = build_bundle(source, target)
    result = target / "data/intermediate/benchmarks/GDX.parquet"
    assert result.read_bytes() == original.read_bytes()
    assert report["files"]["data/intermediate/benchmarks/GDX.parquet"]["source"] == relative
