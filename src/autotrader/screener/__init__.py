"""Cross-universe stock screener: rank, don't just react.

The strategies in :mod:`autotrader.strategy` decide entries/exits for the two
trading books. This package answers a different question — "of everything in
the universe, what does the evidence say about each name *right now*" —
independent of whether either book happens to hold or want it. It is read-only
with respect to the engine: nothing here places an order or feeds the backtest.
"""
