"""Cross-exchange and triangular arbitrage scanners.

Importing this subpackage has no side effects.
"""

from __future__ import annotations

from cryptoarb.arb.cross import CrossLeg, best_cross_leg, cross_gross_bps
from cryptoarb.arb.feasibility import ArbKind, ArbResult
from cryptoarb.arb.triangular import (
    TriangularCycle,
    no_arb_residual,
    triangular_cycle,
)

__all__ = [
    "ArbKind",
    "ArbResult",
    "CrossLeg",
    "TriangularCycle",
    "best_cross_leg",
    "cross_gross_bps",
    "no_arb_residual",
    "triangular_cycle",
]
