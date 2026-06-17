"""Per-venue maker/taker fee schedules.

Fees are REAL schedules, never zeroed — zeroing fees is the classic way to
manufacture a phantom edge. A :class:`FeeSchedule` holds a venue's maker and
taker rates (as fractions, e.g. ``0.001`` = 10 bps); a cross-exchange leg pays
taker on BOTH sides by default. Schedules are loaded from the reference
``profiles/*.yaml`` files. Importing this module has no side effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cryptoarb._exceptions import ValidationError
from cryptoarb.costs._profiles import load_profile

_BPS_PER_UNIT = 1.0e4


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
        return self.taker * _BPS_PER_UNIT

    @property
    def maker_bps(self) -> float:
        """Maker fee in basis points (``maker * 1e4``)."""
        return self.maker * _BPS_PER_UNIT

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this schedule."""
        return {
            "venue": self.venue,
            "maker": self.maker,
            "taker": self.taker,
            "maker_bps": self.maker_bps,
            "taker_bps": self.taker_bps,
        }


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
    return buy.taker_bps + sell.taker_bps


def _build_fee_schedule(venue: str, raw: object) -> FeeSchedule:
    """Validate and construct a single :class:`FeeSchedule` from raw profile data."""
    if not isinstance(raw, Mapping):
        raise ValidationError(f"fee schedule for venue {venue!r} must be a mapping.")
    try:
        maker = float(raw["maker"])
        taker = float(raw["taker"])
    except KeyError as exc:
        raise ValidationError(
            f"fee schedule for venue {venue!r} is missing key {exc.args[0]!r}."
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"fee schedule for venue {venue!r} has a non-numeric rate.") from exc
    if maker < 0.0 or taker < 0.0:
        raise ValidationError(
            f"fee schedule for venue {venue!r} has a negative rate (maker={maker}, taker={taker})."
        )
    return FeeSchedule(venue=venue, maker=maker, taker=taker)


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
    data = load_profile(profile)
    raw_fees = data.get("fees")
    if not isinstance(raw_fees, Mapping) or not raw_fees:
        raise ValidationError(f"profile {profile!r} has no usable 'fees' section.")
    return {str(venue): _build_fee_schedule(str(venue), raw) for venue, raw in raw_fees.items()}
