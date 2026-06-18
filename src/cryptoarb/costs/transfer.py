"""Per-asset withdrawal + network/settlement transfer cost.

Cross-exchange arbitrage requires moving the asset (or its quote) between
venues, which costs a flat withdrawal fee plus a network/settlement latency
penalty. The latency penalty is real: while the asset is in transit the quoted
edge can evaporate, so it is amortized into the cost in basis points. Transfer
cost is the leg that most often flips a positive gross edge negative.

Schedules are loaded from the reference ``profiles/*.yaml`` files. Importing
this module has no side effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cryptoarb._exceptions import ValidationError
from cryptoarb.costs._profiles import load_profile

_BPS_PER_UNIT = 1.0e4


@dataclass(frozen=True, slots=True)
class TransferSchedule:
    """Per-asset withdrawal + settlement-latency cost parameters.

    Attributes
    ----------
    asset:
        Base-asset symbol (e.g. ``"BTC"``, ``"ETH"``, ``"USDT"``).
    withdrawal_flat:
        Flat withdrawal fee in units of the asset (converted to bps against the
        moved notional).
    network_minutes:
        Expected settlement/confirmation time in minutes; drives the
        latency-risk penalty.
    latency_bps_per_min:
        Basis points of edge-decay risk charged per minute in transit.
    """

    asset: str
    withdrawal_flat: float
    network_minutes: float
    latency_bps_per_min: float

    @property
    def latency_bps(self) -> float:
        """Notional-invariant latency penalty (``network_minutes * latency_bps_per_min``)."""
        return self.network_minutes * self.latency_bps_per_min

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this schedule."""
        return {
            "asset": self.asset,
            "withdrawal_flat": self.withdrawal_flat,
            "network_minutes": self.network_minutes,
            "latency_bps_per_min": self.latency_bps_per_min,
            "latency_bps": self.latency_bps,
        }


def transfer_cost_bps(
    schedule: TransferSchedule, *, notional_usd: float, asset_price_usd: float
) -> float:
    """Return the total transfer cost (bps) of moving ``notional_usd`` of the asset.

    Combines the flat withdrawal fee - converted to bps via
    ``1e4 * withdrawal_flat * asset_price_usd / notional_usd`` - with the latency
    penalty ``network_minutes * latency_bps_per_min``. Larger notionals dilute
    the flat fee's bps contribution; the latency penalty is notional-invariant.

    Parameters
    ----------
    schedule:
        The per-asset transfer schedule.
    notional_usd:
        The notional being moved, in USD; strictly positive.
    asset_price_usd:
        The USD price of one unit of the asset, used to value the flat fee.

    Returns
    -------
    float
        The total transfer cost in basis points.

    Raises
    ------
    ValidationError
        If ``notional_usd`` or ``asset_price_usd`` is not strictly positive.
    """
    if not notional_usd > 0.0:
        raise ValidationError(f"notional_usd must be strictly positive, got {notional_usd}.")
    if not asset_price_usd > 0.0:
        raise ValidationError(f"asset_price_usd must be strictly positive, got {asset_price_usd}.")
    withdrawal_bps = _BPS_PER_UNIT * schedule.withdrawal_flat * asset_price_usd / notional_usd
    return withdrawal_bps + schedule.latency_bps


def _build_transfer_schedule(asset: str, raw: object) -> TransferSchedule:
    """Validate and construct a single :class:`TransferSchedule` from raw profile data."""
    if not isinstance(raw, Mapping):
        raise ValidationError(f"transfer schedule for asset {asset!r} must be a mapping.")
    try:
        withdrawal_flat = float(raw["withdrawal_flat"])
        network_minutes = float(raw["network_minutes"])
        latency_bps_per_min = float(raw["latency_bps_per_min"])
    except KeyError as exc:
        raise ValidationError(
            f"transfer schedule for asset {asset!r} is missing key {exc.args[0]!r}."
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"transfer schedule for asset {asset!r} has a non-numeric value."
        ) from exc
    if withdrawal_flat < 0.0 or network_minutes < 0.0 or latency_bps_per_min < 0.0:
        raise ValidationError(
            f"transfer schedule for asset {asset!r} has a negative value "
            f"(withdrawal_flat={withdrawal_flat}, network_minutes={network_minutes}, "
            f"latency_bps_per_min={latency_bps_per_min})."
        )
    return TransferSchedule(
        asset=asset,
        withdrawal_flat=withdrawal_flat,
        network_minutes=network_minutes,
        latency_bps_per_min=latency_bps_per_min,
    )


def load_transfer_schedules(profile: str = "default") -> dict[str, TransferSchedule]:
    """Load per-asset transfer schedules from a reference profile.

    Reads ``profiles/{profile}.yaml`` (bundled with the package) and returns a
    mapping of asset symbol to :class:`TransferSchedule`. ``pyyaml`` is imported
    lazily inside the function.

    Parameters
    ----------
    profile:
        Profile name: ``"default"``, ``"low"``, or ``"high"``.

    Returns
    -------
    dict[str, TransferSchedule]
        Mapping of asset symbol to its transfer schedule.

    Raises
    ------
    ValidationError
        If ``profile`` is unknown or the file is malformed / has a negative value.
    """
    data = load_profile(profile)
    raw_transfers = data.get("transfers")
    if not isinstance(raw_transfers, Mapping) or not raw_transfers:
        raise ValidationError(f"profile {profile!r} has no usable 'transfers' section.")
    return {
        str(asset): _build_transfer_schedule(str(asset), raw)
        for asset, raw in raw_transfers.items()
    }
