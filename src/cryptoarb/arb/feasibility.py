"""Arbitrage result container and feasibility classification.

A frozen :class:`ArbResult` is the common output of both the cross-exchange and
triangular scanners. It carries the gross spread, the executable (depth-aware)
spread, the fully-decomposed net edge after costs, the fillable notional, and
the dominant cost leg, so the verdict layer can classify feasibility from a
single object. Importing this module has no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ArbKind(StrEnum):
    """The kind of arbitrage a result describes (stable serialized string values)."""

    CROSS_EXCHANGE = "cross_exchange"
    TRIANGULAR = "triangular"


@dataclass(frozen=True, slots=True)
class ArbResult:
    """Immutable decomposition of a single arbitrage opportunity.

    Attributes
    ----------
    kind:
        Whether this is a cross-exchange or triangular opportunity.
    symbol:
        The primary symbol (cross) or cycle label (triangular).
    legs:
        Human-readable description of the legs (e.g. ``("buy@kraken", "sell@binance")``).
    notional_usd:
        The target notional the scan was priced for, in USD-equivalent.
    gross_bps:
        The raw top-of-book spread, in basis points (the over-claim baseline).
    executable_bps:
        The depth-aware spread from VWAP-walked books, in basis points
        (``<= gross_bps`` once depth is accounted for).
    net_bps:
        The net edge after fees, slippage (already in executable), and transfer
        cost, in basis points. The honest headline number.
    fillable_notional:
        The notional that is actually fully fillable across both legs, in USD.
    dominant_cost_leg:
        The single largest cost contributor (e.g. ``"taker_fee"``,
        ``"slippage"``, ``"transfer"``).
    feasible:
        Whether ``net_bps`` clears the feasibility threshold (set by the verdict
        layer). NOTE: structurally ``False`` whenever ``net_bps <= 0``.
    """

    kind: ArbKind
    symbol: str
    legs: tuple[str, ...]
    notional_usd: float
    gross_bps: float
    executable_bps: float
    net_bps: float
    fillable_notional: float
    dominant_cost_leg: str
    feasible: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this result."""
        raise NotImplementedError
