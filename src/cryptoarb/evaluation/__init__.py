"""Honest-statistics layer: DSR/PSR, net-edge accounting, and verdicts.

The headline verdict is a pure function of the net-edge inference. Importing
this subpackage has no side effects.
"""

from __future__ import annotations

from cryptoarb.evaluation.dsr import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
)
from cryptoarb.evaluation.netedge import (
    CostSensitivityPoint,
    NetEdgeStats,
    cost_sensitivity_grid,
    effective_n_trials,
    net_edge_stats,
)
from cryptoarb.evaluation.verdict import Verdict, derive_verdict, is_within_noise

__all__ = [
    "CostSensitivityPoint",
    "NetEdgeStats",
    "Verdict",
    "cost_sensitivity_grid",
    "deflated_sharpe_ratio",
    "derive_verdict",
    "effective_n_trials",
    "is_within_noise",
    "net_edge_stats",
    "probabilistic_sharpe_ratio",
]
