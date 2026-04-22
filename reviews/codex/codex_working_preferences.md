# Codex Working Preferences

This file captures repo-specific working preferences that should remain explicit across milestones.

## Approval behavior

Emanuel prefers low-interruption execution.

Implications for Codex:

- do not trigger many small approval requests in sequence for one task
- batch related shell work into fewer larger steps
- reuse already approved command patterns whenever possible
- assume approval for clearly necessary, non-destructive continuation work when the platform allows it
- only trigger escalation prompts when the sandbox genuinely requires them
- avoid separate approval prompts for small read/inspection commands if they can be bundled into an already necessary step

## Goal

The user should see progress, results, and summaries, not a stream of avoidable approval popups.
