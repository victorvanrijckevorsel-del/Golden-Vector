# Codex Working Rule: Simple First

Added: 2026-04-24

Before proposing any implementation:

1. ask: **what is the simplest thing that could work?**
2. write that version down first
3. only add complexity if a concrete concern forces it

Default preferences:

- prefer fewer files
- prefer one generic mechanism over many parallel ones
- prefer data-driven designs over string-assembled code
- do not polish a complex design when a simpler one is available

Review reminder:

- do not only review for correctness inside the proposed architecture
- also step back and challenge whether the architecture itself is unnecessarily complicated
