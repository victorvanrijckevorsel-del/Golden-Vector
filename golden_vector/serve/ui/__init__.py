"""Pure presentation package for the workspace UI (plan section 10.1).

Modules here render escaped HTML from already-resolved inputs only. They must
never inspect DataFrames, calculate thresholds, choose a financial source, or
infer whether a number is good or bad — the serve no-arithmetic guardrails
scan this package like every other serve module.
"""
