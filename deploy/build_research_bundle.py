"""Create a reviewed research-only projection; never modify the source data store.

The original research artifact paths, checksums, refresh identity and freshness
remain authoritative. Portfolio artifacts are explicitly out of publication scope,
not silently treated as missing research. Only the manual store is transformed:
new SQLite pages contain company inputs but no free-text notes or stock notes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tarfile

from golden_vector.common.files import atomic_write_text, sha256_file
from golden_vector.screening.manual_store import _create_schema
from golden_vector.lab.conditional_dial import DIAL_ARTIFACT_META_FILENAME
from golden_vector.lab.behavior_engine import BEHAVIOR_META_FILENAME
from golden_vector.lab.scorecard import SCORECARD_META_FILENAME


RESEARCH_ARTIFACTS = frozenset({
    "foundation", "options", "fundamentals_official", "benchmark_betas",
    "tool_a", "tool_a_structural_metrics", "tool_b", "tool_c", "tool_d", "tool_d_spot",
    "candidate_finder_inputs", "option_availability", "option_candidate_slots",
    "option_chain_history_daily", "option_contract_metrics", "option_liquidity_measurements",
    "option_oi_strike_points", "option_selected_candidates", "option_signal_history_points",
    "option_signal_summary", "option_skew_curve_points", "option_trading_overview",
    "ticker_page_downside_context", "ticker_page_fx_attribution", "ticker_page_gold_response",
    "ticker_page_percentiles", "ticker_page_performance", "ticker_page_research_series",
})
PRIVATE_ARTIFACTS = frozenset({
    "portfolio_correlations", "portfolio_hedge_sizing", "portfolio_lines", "portfolio_positions",
    "portfolio_reconciliation", "portfolio_reconciliation_export", "portfolio_reconciliation_export_csv",
    "portfolio_summary", "portfolio_value_history",
})
POINTER = "data/intermediate/status/latest_model_state.json"
MANUAL = "data/manual/screening/manual_screening.sqlite3"
FOUNDATION_INPUTS = (
    "gold_history_path", "normalized_equities_snapshot_path", "normalized_market_snapshots_snapshot_path",
    "raw_equities_snapshot_path", "raw_fx_snapshot_path",
)


def safe_source(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative
            or not path.parts or path.parts[0] != "data"):
        raise ValueError(f"Unsafe research path: {relative}")
    resolved = (root / relative).resolve(strict=True)
    if not resolved.is_relative_to(root.resolve() / "data") or not resolved.is_file():
        raise ValueError(f"Research path escapes source data: {relative}")
    return resolved


def clean_manual_store(source: Path, target: Path) -> dict[str, int]:
    """Create a new allowlisted database; never copy pages containing deleted notes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)
    counts = {}
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        original.execute("BEGIN")  # one consistent read transaction
        with sqlite3.connect(target) as output:
            _create_schema(output)
            for table in ("company_inputs", "source_verification", "reporting_calendar"):
                columns = [row[1] for row in output.execute(f"PRAGMA table_info({table})") if row[1] != "notes"]
                quoted = ",".join(f'"{name}"' for name in columns)
                rows = original.execute(f"SELECT {quoted} FROM {table}").fetchall()
                output.executemany(f"INSERT INTO {table} ({quoted}) VALUES ({','.join('?' for _ in columns)})", rows)
                counts[table] = len(rows)
            assert output.execute("SELECT COUNT(*) FROM stock_notes").fetchone()[0] == 0
            assert output.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    return counts


def build_bundle(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination == source or destination.is_relative_to(source / "data"):
        raise ValueError("Publication must be outside the production data directory")
    if destination.exists():
        raise FileExistsError("Use a new publication directory; existing outputs are preserved")
    pointer = safe_source(source, POINTER)
    pointer_hash = sha256_file(pointer)
    model = json.loads(pointer.read_text(encoding="utf-8"))
    if model.get("state") != "complete" or model.get("alignment", {}).get("status") != "OK":
        raise ValueError("A complete, aligned source research generation is required")
    unknown = set(model["artifacts"]) - RESEARCH_ARTIFACTS - PRIVATE_ARTIFACTS
    if unknown:
        raise ValueError(f"Unreviewed artifact types: {sorted(unknown)}")
    missing = RESEARCH_ARTIFACTS - set(model["artifacts"])
    if missing:
        raise ValueError(f"Missing declared research artifacts: {sorted(missing)}")
    destination.mkdir(parents=True)
    inventory = {}

    def copy(relative: str, expected: str | None = None, *, purpose: str) -> None:
        original = safe_source(source, relative)
        # Only explicit research roots and named dependencies are admitted.
        parts = PurePosixPath(relative).parts
        if parts[1] in {"manual", "access"} or "holdings" in parts or "portfolio" in parts:
            if not (purpose == "benchmark_betas" and original.name.startswith("benchmark_betas_")):
                raise ValueError(f"Private data cannot be copied: {relative}")
        if original.suffix not in {".parquet", ".json"}:
            raise ValueError(f"Unreviewed research format: {relative}")
        digest = sha256_file(original)
        if expected and digest != expected:
            raise ValueError(f"Source checksum mismatch: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        if sha256_file(target) != digest:
            raise ValueError(f"Copy changed during publication: {relative}")
        inventory[relative] = {"sha256": digest, "size_bytes": target.stat().st_size, "purpose": purpose}

    published = deepcopy(model)
    published["artifacts"] = {}
    for name in sorted(RESEARCH_ARTIFACTS):
        artifact = model["artifacts"][name]
        if not artifact.get("usable") or not artifact.get("immutable") or not artifact.get("sha256"):
            raise ValueError(f"Research artifact is not verified immutable data: {name}")
        copy(artifact["path"], artifact["sha256"], purpose=name)
        published["artifacts"][name] = deepcopy(artifact)
    # The benchmark file lives under portfolio/ but has no positions or holdings.
    import pyarrow.parquet as pq
    benchmark = pq.read_table(destination / model["artifacts"]["benchmark_betas"]["path"])
    if set(benchmark.column("benchmark_ticker").to_pylist()) - {"GDX", "GDXJ"}:
        raise ValueError("Unexpected symbols in benchmark-only publication")
    if any(token in name.lower() for name in benchmark.column_names for token in ("holding", "position", "quantity", "cost_basis")):
        raise ValueError("Private fields found in benchmark artifact")
    foundation = json.loads((destination / model["artifacts"]["foundation"]["path"]).read_text())
    for key in FOUNDATION_INPUTS:
        copy(foundation[key], purpose="foundation_input")
    options = json.loads((destination / model["artifacts"]["options"]["path"]).read_text())
    for relative in options.get("benchmark_snapshot_paths", []):
        copy(relative, purpose="benchmark_history")
        filename = PurePosixPath(relative).name
        if filename not in {"GDX.parquet", "GDXJ.parquet"}:
            raise ValueError(f"Unreviewed benchmark history: {filename}")
        # The existing chart reader uses this compatibility path. Materialize
        # it from the selected immutable run, never from a mutable local alias.
        alias = "data/intermediate/benchmarks/" + filename
        (destination / alias).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination / relative, destination / alias)
        inventory[alias] = {**inventory[relative], "purpose": "benchmark chart compatibility copy", "source": relative}
    for record in options["snapshots"]:
        for key, hash_key in (("snapshot_path", "sha256"), ("feature_path", "feature_sha256")):
            if record.get(key):
                copy(record[key], record.get(hash_key), purpose="option_dependency")
    # Lab/Scorecard have their own atomic metadata pointer; preserve their true ages.
    optional_surfaces = {}
    for meta_name in (DIAL_ARTIFACT_META_FILENAME, BEHAVIOR_META_FILENAME, SCORECARD_META_FILENAME):
        relative = "data/lab/" + meta_name
        if not (source / relative).is_file():
            optional_surfaces[meta_name] = "not present in source; not fabricated"
            continue
        copy(relative, purpose="lab_metadata")
        meta = json.loads((destination / relative).read_text())
        filenames = list(meta.get("run_stamped_artifacts", {}).values())
        if meta.get("run_stamped_artifact"):
            filenames.append(meta["run_stamped_artifact"])
        if not filenames:
            raise ValueError(f"Lab metadata lacks immutable artifact references: {relative}")
        for filename in filenames:
            if PurePosixPath(filename).name != filename:
                raise ValueError(f"Unsafe Lab artifact: {filename}")
            copy("data/lab/" + filename, purpose="lab_artifact")
        optional_surfaces[meta_name] = meta.get("built_at_utc", "published")
        if sha256_file(source / relative) != inventory[relative]["sha256"]:
            raise ValueError("Lab publication changed during copy; retry with a new destination")

    manual_source = safe_source(source, MANUAL)
    expected_manual_hash = model["manual_data"].get("sha256")
    if not expected_manual_hash or sha256_file(manual_source) != expected_manual_hash:
        raise ValueError("Manual inputs changed since this research generation was published")
    wal = manual_source.with_name(manual_source.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("Manual store has pending WAL changes; publish a coherent source generation first")
    manual_counts = clean_manual_store(manual_source, destination / MANUAL)
    if sha256_file(manual_source) != expected_manual_hash or (wal.exists() and wal.stat().st_size):
        raise ValueError("Manual inputs changed during publication")
    manual_hash = sha256_file(destination / MANUAL)
    manual_size = (destination / MANUAL).stat().st_size
    published["manual_data"].update(sha256=manual_hash, size_bytes=manual_size)
    inventory[MANUAL] = {"sha256": manual_hash, "size_bytes": manual_size, "purpose": "notes-free company inputs"}
    published["alignment"].pop("portfolio_artifact_refresh_run_ids", None)
    # Source stage timings may contain portfolio details; not needed by readers.
    published.pop("stage_timings", None)
    publication = {
        "version": 1, "scope": "invite-only research snapshot", "source_manifest_sha256": pointer_hash,
        "excluded_artifacts": sorted(PRIVATE_ARTIFACTS & set(model["artifacts"])),
        "manual_projection": "Company inputs and source/calendar facts only; all notes omitted in a fresh database",
        "optional_surfaces": optional_surfaces,
    }
    published["research_publication"] = publication
    if sha256_file(pointer) != pointer_hash:
        raise ValueError("Source current pointer changed during copy; retry with a new destination")
    atomic_write_text(destination / POINTER, json.dumps(published, indent=2, sort_keys=True) + "\n")
    inventory[POINTER] = {"sha256": sha256_file(destination / POINTER), "purpose": "scoped atomic research pointer"}
    # All retained research artifact entries remain identical, including checksum and age.
    assert all(published["artifacts"][name] == model["artifacts"][name] for name in RESEARCH_ARTIFACTS)
    report = {**publication, "parent_refresh_id": model["parent_refresh_id"],
              "full_refresh_completed_at_utc": model["full_refresh_completed_at_utc"],
              "manual_row_counts": manual_counts, "files": inventory}
    atomic_write_text(destination / "publication.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    report = build_bundle(args.source, args.destination)
    archive = args.destination.with_suffix(".tar.gz")
    if archive.exists():
        raise FileExistsError(archive)
    with tarfile.open(archive, "w:gz") as output:
        for relative in sorted([*report["files"], "publication.json"]):
            output.add(args.destination / relative, arcname=relative, recursive=False)
    print(json.dumps({"archive": str(archive), "sha256": sha256_file(archive),
                      "files": len(report["files"]), "bytes": archive.stat().st_size,
                      "refresh": report["full_refresh_completed_at_utc"],
                      "manual_row_counts": report["manual_row_counts"],
                      "optional_surfaces": report["optional_surfaces"]}, indent=2))


if __name__ == "__main__":
    main()
