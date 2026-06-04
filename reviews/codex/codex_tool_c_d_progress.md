# Tool C / Tool D Build Progress

## Batch 1 - Tool C

### Step 1 - Config and paths

- Added Tool C and Tool D config contracts with safe defaults for direct `AppConfig` tests.
- Added `config/tool_c.yaml` with hit-rate event thresholds and `config/tool_d.yaml` with the stressed gold assumption.
- Registered both config files in `EXPECTED_CONFIG_FILES` so replay manifests retain them.
- Added Tool C and Tool D intermediate/output path properties.
- Added focused config validation tests.

Self-review notes:

- The Tool C hit-rate thresholds live in YAML and validation enforces down/up ordering.
- Defaults avoid breaking unit tests that instantiate `AppConfig` directly.
- Replay coverage is inherited from `expected_config_paths`; the existing replay test now verifies the expanded list.
