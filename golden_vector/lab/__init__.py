"""Predictive Lab: point-in-time vintages, variant ledger, backtest harness.

Backend-only data product (build-order rule from the Lab spec): everything
here computes and persists artifacts; serve may only render them. Never
imports serve. Gold-return prediction targets are banned by contract — gold
data enters only as conditioning/regime/abstention variables.
"""
