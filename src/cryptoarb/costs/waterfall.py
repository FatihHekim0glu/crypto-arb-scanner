"""Gross -> net cost waterfall.

This module assembles the honest headline: it starts from the executable gross
spread (already depth-/slippage-aware from VWAP-walked books) and subtracts, in
order, round-trip taker fees and transfer cost to arrive at the **net edge**.
The result is a :class:`Waterfall` whose stages render directly as the frontend
gross -> net waterfall bar. A :class:`CompositeCost` bundles the fee + transfer
schedules loaded from a single profile so callers configure costs once.

Importing this module has no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cryptoarb._exceptions import ValidationError
from cryptoarb.costs.fees import FeeSchedule, load_fee_schedules, round_trip_taker_bps
from cryptoarb.costs.transfer import (
    TransferSchedule,
    load_transfer_schedules,
    transfer_cost_bps,
)


@dataclass(frozen=True, slots=True)
class CompositeCost:
    """Bundle of fee + transfer schedules for one cost profile.

    Attributes
    ----------
    profile:
        The profile name these schedules were loaded from.
    fees:
        Mapping of venue identifier to :class:`FeeSchedule`.
    transfers:
        Mapping of asset symbol to :class:`TransferSchedule`.
    """

    profile: str
    fees: dict[str, FeeSchedule]
    transfers: dict[str, TransferSchedule]

    @classmethod
    def from_profile(cls, profile: str = "default") -> CompositeCost:
        """Load both fee and transfer schedules for ``profile`` into a bundle.

        Parameters
        ----------
        profile:
            Profile name: ``"default"``, ``"low"``, or ``"high"``.

        Returns
        -------
        CompositeCost
            The assembled cost bundle.

        Raises
        ------
        ValidationError
            If ``profile`` is unknown or a schedule file is malformed.
        """
        return cls(
            profile=profile,
            fees=load_fee_schedules(profile),
            transfers=load_transfer_schedules(profile),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this bundle."""
        return {
            "profile": self.profile,
            "fees": {venue: fee.to_dict() for venue, fee in self.fees.items()},
            "transfers": {asset: transfer.to_dict() for asset, transfer in self.transfers.items()},
        }


@dataclass(frozen=True, slots=True)
class WaterfallStage:
    """One labeled step in the gross -> net decomposition.

    Attributes
    ----------
    label:
        Stage label (e.g. ``"gross"``, ``"taker_fees"``, ``"transfer"``, ``"net"``).
    delta_bps:
        The signed change applied at this stage, in basis points (negative for a
        cost; the ``gross`` and ``net`` anchor stages carry the running level).
    running_bps:
        The cumulative edge in basis points after this stage is applied.
    """

    label: str
    delta_bps: float
    running_bps: float

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this stage."""
        return {
            "label": self.label,
            "delta_bps": self.delta_bps,
            "running_bps": self.running_bps,
        }


@dataclass(frozen=True, slots=True)
class Waterfall:
    """The full gross -> net decomposition for one opportunity.

    Attributes
    ----------
    gross_bps:
        The executable gross spread entering the waterfall.
    net_bps:
        The net edge after all cost stages - the honest headline number.
    stages:
        Ordered cost stages from ``gross`` to ``net`` (renders as the bar chart).
    dominant_cost_leg:
        The label of the single largest cost stage by magnitude.
    """

    gross_bps: float
    net_bps: float
    stages: tuple[WaterfallStage, ...]
    dominant_cost_leg: str

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this waterfall."""
        return {
            "gross_bps": self.gross_bps,
            "net_bps": self.net_bps,
            "stages": [stage.to_dict() for stage in self.stages],
            "dominant_cost_leg": self.dominant_cost_leg,
        }


def build_waterfall(
    *,
    gross_bps: float,
    buy_fee: FeeSchedule,
    sell_fee: FeeSchedule,
    transfer: TransferSchedule | None,
    notional_usd: float,
    asset_price_usd: float,
) -> Waterfall:
    """Decompose an executable gross spread into its net edge.

    Stages, in order: ``gross`` (anchor) -> ``-taker_fees`` (both legs) ->
    ``-transfer`` (if ``transfer`` is given) -> ``net`` (anchor). Slippage is NOT
    a separate stage because it is already baked into ``gross_bps`` by walking
    the books; double-counting it would understate the edge.

    GUARANTEE (property-tested): ``net_bps <= gross_bps`` always (costs are
    non-negative), so the net edge can never exceed the gross edge.

    Parameters
    ----------
    gross_bps:
        The executable (depth-aware) gross spread in basis points.
    buy_fee, sell_fee:
        Fee schedules for the buy and sell legs (both pay taker).
    transfer:
        Transfer schedule for the moved asset, or ``None`` to exclude transfer
        cost (e.g. when ``include_transfer_cost`` is off, or for triangular
        single-venue cycles with no cross-venue move).
    notional_usd:
        The notional priced, in USD; strictly positive.
    asset_price_usd:
        The USD price of the moved asset, used to value the flat withdrawal fee.

    Returns
    -------
    Waterfall
        The full decomposition with stages and net edge.

    Raises
    ------
    ValidationError
        If ``notional_usd`` or ``asset_price_usd`` is not strictly positive.
    """
    if not notional_usd > 0.0:
        raise ValidationError(f"notional_usd must be strictly positive, got {notional_usd}.")
    if not asset_price_usd > 0.0:
        raise ValidationError(f"asset_price_usd must be strictly positive, got {asset_price_usd}.")

    gross = float(gross_bps)
    stages: list[WaterfallStage] = [
        WaterfallStage(label="gross", delta_bps=gross, running_bps=gross)
    ]

    # Cost stages are NEVER zeroed: round-trip taker on both legs is always paid.
    fee_cost_bps = round_trip_taker_bps(buy=buy_fee, sell=sell_fee)
    running = gross - fee_cost_bps
    stages.append(WaterfallStage(label="taker_fees", delta_bps=-fee_cost_bps, running_bps=running))

    # Track cost magnitudes so the dominant leg is the single largest cost.
    cost_magnitudes: dict[str, float] = {"taker_fees": fee_cost_bps}

    if transfer is not None:
        transfer_bps = transfer_cost_bps(
            transfer, notional_usd=notional_usd, asset_price_usd=asset_price_usd
        )
        running = running - transfer_bps
        stages.append(
            WaterfallStage(label="transfer", delta_bps=-transfer_bps, running_bps=running)
        )
        cost_magnitudes["transfer"] = transfer_bps

    net = running
    stages.append(WaterfallStage(label="net", delta_bps=net, running_bps=net))

    # Dominant cost leg = the label of the single largest cost by magnitude.
    dominant_cost_leg = max(cost_magnitudes, key=lambda label: cost_magnitudes[label])

    return Waterfall(
        gross_bps=gross,
        net_bps=net,
        stages=tuple(stages),
        dominant_cost_leg=dominant_cost_leg,
    )
