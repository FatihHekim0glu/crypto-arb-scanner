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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from cryptoarb.costs.fees import FeeSchedule
    from cryptoarb.costs.transfer import TransferSchedule


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
        return {
            "kind": self.kind.value,
            "symbol": self.symbol,
            "legs": list(self.legs),
            "notional_usd": float(self.notional_usd),
            "gross_bps": float(self.gross_bps),
            "executable_bps": float(self.executable_bps),
            "net_bps": float(self.net_bps),
            "fillable_notional": float(self.fillable_notional),
            "dominant_cost_leg": self.dominant_cost_leg,
            "feasible": bool(self.feasible),
        }


def assemble_arb_result(
    *,
    kind: ArbKind,
    symbol: str,
    legs: Sequence[str],
    notional_usd: float,
    gross_bps: float,
    executable_bps: float,
    fillable_notional: float,
    buy_fee: FeeSchedule,
    sell_fee: FeeSchedule,
    transfer: TransferSchedule | None,
    asset_price_usd: float,
) -> ArbResult:
    """Assemble a frozen :class:`ArbResult` by running the gross -> net waterfall.

    This is the single seam between the arb scanners and the cost layer: it takes
    the depth-aware ``executable_bps`` (already net of slippage from VWAP-walked
    books), runs it through :func:`cryptoarb.costs.waterfall.build_waterfall` to
    subtract round-trip taker fees and (optionally) transfer cost, and packs the
    result with its dominant cost leg.

    The ``feasible`` flag is set conservatively here - ``True`` only when
    ``net_bps > 0`` - so an :class:`ArbResult` can NEVER be flagged feasible on a
    non-positive net edge regardless of any later thresholding. The authoritative
    verdict (with its noise band and confidence bound) is still produced by
    :func:`cryptoarb.evaluation.verdict.derive_verdict`; this flag is the
    structural honest-null floor.

    Parameters
    ----------
    kind:
        Whether this is a cross-exchange or triangular opportunity.
    symbol:
        The primary symbol (cross) or cycle label (triangular).
    legs:
        Human-readable leg descriptions (e.g. ``("buy@kraken", "sell@binance")``).
    notional_usd:
        The target notional the scan was priced for, in USD; strictly positive.
    gross_bps:
        The raw top-of-book spread, in basis points (the over-claim baseline).
    executable_bps:
        The depth-aware spread from VWAP-walked books; the waterfall entry level.
    fillable_notional:
        The notional actually fillable across the legs, in USD.
    buy_fee, sell_fee:
        Fee schedules for the buy and sell legs (both pay taker).
    transfer:
        Transfer schedule for the moved asset, or ``None`` to exclude transfer
        cost (e.g. a single-venue triangular cycle, or transfer cost disabled).
    asset_price_usd:
        The USD price of the moved asset, used to value the flat withdrawal fee;
        strictly positive.

    Returns
    -------
    ArbResult
        The fully decomposed, frozen opportunity.

    Raises
    ------
    ValidationError
        If ``notional_usd`` or ``asset_price_usd`` is not strictly positive
        (propagated from the waterfall builder).
    """
    # Imported lazily (inside the function) so this module stays import-pure and
    # free of a costs <-> arb import cycle at module load.
    from cryptoarb.costs.waterfall import build_waterfall

    waterfall = build_waterfall(
        gross_bps=executable_bps,
        buy_fee=buy_fee,
        sell_fee=sell_fee,
        transfer=transfer,
        notional_usd=notional_usd,
        asset_price_usd=asset_price_usd,
    )
    net_bps = waterfall.net_bps
    return ArbResult(
        kind=kind,
        symbol=symbol,
        legs=tuple(legs),
        notional_usd=float(notional_usd),
        gross_bps=float(gross_bps),
        executable_bps=float(executable_bps),
        net_bps=float(net_bps),
        fillable_notional=float(fillable_notional),
        dominant_cost_leg=waterfall.dominant_cost_leg,
        feasible=net_bps > 0.0,
    )
