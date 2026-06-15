# Fast local test run — parallelized across CPU cores via pytest-xdist.
#
# Plain `pytest` stays the canonical/serial path (clean pdb, -s, single-file
# debugging, deterministic CI). Use this script for the inner build->review loop.
#
#   .\scripts\test_fast.ps1            # 4 workers (safe default; pandas/parquet-heavy suite)
#   .\scripts\test_fast.ps1 -Auto     # one worker per logical core (faster if you have the RAM)
#   .\scripts\test_fast.ps1 tests/test_tool_c.py   # extra args pass through to pytest
#
# --dist loadscope keeps same-module tests on one worker (preserves module
# fixtures + contains module-level caches like the AppConfig lru_cache).
param([switch]$Auto)

$ErrorActionPreference = "Stop"
$workers = if ($Auto) { "auto" } else { "4" }
$python = Join-Path $PSScriptRoot "..\venv\Scripts\python.exe"

Write-Host "pytest -n $workers --dist loadscope $args"
& $python -m pytest -n $workers --dist loadscope @args
exit $LASTEXITCODE
