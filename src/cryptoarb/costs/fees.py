"""Per-venue maker/taker fee schedules.

Fees are REAL schedules, never zeroed — zeroing fees is the classic way to
manufacture a phantom edge. A :class:`FeeSchedule` holds a venue's maker and
taker rates (as fractions, e.g. ``0.001`` = 10 bps); a cross-exchange leg pays
taker on BOTH sides by default. Schedules are loaded from the reference
``profiles/*.yaml`` files. Importing this module has no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    """A single venue's maker/taker fee rates.

    Attributes
    ----------
    venue:
        Venue identifier.
    maker:
        Maker fee as a fraction of notional (e.g. ``0.0010`` = 10 bps).
    taker:
        Taker fee as a fraction of notional (e.g. ``0.0010`` = 10 bps).
    """

    venue: str
    maker: float
    taker: float

    @property
    def taker_bps(self) -> float:
        """Taker fee in basis points (``taker * 1e4``)."""
        raise NotImplementedError

    @property
    def maker_bps(self) -> float:
        """Maker fee in basis points (``maker * 1e4``)."""
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this schedule."""
        raise NotImplementedError


def round_trip_taker_bps(buy: FeeSchedule, sell: FeeSchedule) -> float:
    """Return the combined taker cost (bps) of buying on one venue and selling on another.

    A cross-exchange trade pays taker on both legs, so the cost is
    ``buy.taker_bps + sell.taker_bps``.

    Parameters
    ----------
    buy:
        Fee schedule of the venue the position is bought on.
    sell:
        Fee schedule of the venue the position is sold on.

    Returns
    -------
    float
        The summed round-trip taker fee in basis points.
    """
    raise NotImplementedError


def load_fee_schedules(profile: str = "default") -> dict[str, FeeSchedule]:
    """Load per-venue fee schedules from a reference profile.

    Reads ``profiles/{profile}.yaml`` (bundled with the package) and returns a
    mapping of venue identifier to :class:`FeeSchedule`. ``pyyaml`` is imported
    lazily inside the function so importing this module stays side-effect-free.

    Parameters
    ----------
    profile:
        Profile name: ``"default"``, ``"low"``, or ``"high"``.

    Returns
    -------
    dict[str, FeeSchedule]
        Mapping of venue identifier to its fee schedule.

    Raises
    ------
    ValidationError
        If ``profile`` is unknown or the file is malformed / has a negative rate.
    """
    raise NotImplementedError
