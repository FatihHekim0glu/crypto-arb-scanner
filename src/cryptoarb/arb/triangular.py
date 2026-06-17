"""Single-venue triangular arbitrage scan.

A triangular cycle on one venue chains three pairs — ``A/B``, ``B/C``, ``C/A`` —
so that converting one unit of ``A`` all the way around returns a quantity of
``A``. The **no-arb identity** is that the product of the three executable
exchange rates equals ``1``; any deviation is the triangular gross edge. On the
consistent synthetic books the identity holds to ``1e-12`` (parity-tested).

Importing this module has no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cryptoarb._exceptions import BookError, ValidationError
from cryptoarb.books.vwap import Side, vwap

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook

#: A triangular cycle is exactly three chained legs.
_N_LEGS = 3


@dataclass(frozen=True, slots=True)
class TriangularCycle:
    """A three-leg single-venue cycle and its no-arb deviation.

    Attributes
    ----------
    venue:
        The venue hosting all three legs.
    legs:
        The three leg symbols in cycle order (``("A/B", "B/C", "C/A")``).
    rate_product:
        The product of the three executable rates; ``1`` under no-arb.
    gross_bps:
        ``1e4 * (rate_product - 1)`` — the triangular gross edge in bps.
    fillable_notional:
        The notional fully fillable around the whole cycle (binding minimum),
        in quote units of the entry leg.
    """

    venue: str
    legs: tuple[str, str, str]
    rate_product: float
    gross_bps: float
    fillable_notional: float

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this cycle."""
        return {
            "venue": self.venue,
            "legs": list(self.legs),
            "rate_product": float(self.rate_product),
            "gross_bps": float(self.gross_bps),
            "fillable_notional": float(self.fillable_notional),
        }


def _ordered_legs(books: dict[str, OrderBook]) -> tuple[str, str, str]:
    """Return the three leg symbols in stable cycle order, validating the shape.

    The cycle order is the books' insertion order (the generator yields
    ``("A/B", "B/C", "C/A")``); the mid product is order-invariant, so this only
    fixes a deterministic label tuple for the result.

    Raises
    ------
    ValidationError
        If ``books`` does not contain exactly three legs.
    """
    if len(books) != _N_LEGS:
        raise ValidationError(
            f"triangular cycle needs exactly {_N_LEGS} chained legs, got {len(books)}: "
            f"{sorted(books)}."
        )
    legs = tuple(books)
    return (legs[0], legs[1], legs[2])


def no_arb_residual(books: dict[str, OrderBook]) -> float:
    """Return the no-arb identity residual ``rate_product - 1`` for a triangular cycle.

    Uses each leg's mid (or top-of-book rate) to form the cycle product. On the
    consistent synthetic books this is ``0`` to within ``1e-12``; the parity
    suite pins this tolerance.

    Parameters
    ----------
    books:
        Mapping of leg symbol to its order book (exactly three chained legs).

    Returns
    -------
    float
        The signed residual ``rate_product - 1``.

    Raises
    ------
    ValidationError
        If the books do not form exactly three chained legs.
    BookError
        If the legs do not compose into a closed cycle.
    """
    legs = _ordered_legs(books)
    rate_product = 1.0
    for leg in legs:
        book = books[leg]
        # ``mid`` raises BookError if either side of a leg is empty, which is the
        # right signal that the legs do not compose into a closeable cycle.
        rate_product *= book.mid
    if not (rate_product > 0.0):
        raise BookError(f"triangular cycle {legs} has a non-positive mid product ({rate_product}).")
    return rate_product - 1.0


def triangular_cycle(books: dict[str, OrderBook], target_notional: float) -> TriangularCycle:
    """Price a triangular cycle for ``target_notional`` using VWAP-walked legs.

    Each leg's executable rate is the VWAP needed to convert the running balance
    through that pair; the product of the three rates gives the gross edge. The
    fillable notional is the binding minimum across the three legs.

    Parameters
    ----------
    books:
        Mapping of leg symbol to its order book (three chained legs on one venue).
    target_notional:
        The entry-leg quote-notional ``Q`` to walk the cycle for; strictly
        positive.

    Returns
    -------
    TriangularCycle
        The priced cycle and its gross edge.

    Raises
    ------
    ValidationError
        If the legs are malformed or ``target_notional`` is not strictly positive.
    BookError
        If the legs do not compose into a closed cycle.
    """
    if not (target_notional > 0.0):
        raise ValidationError(
            f"triangular_cycle: target_notional must be strictly positive, got {target_notional}."
        )
    legs = _ordered_legs(books)
    venue = books[legs[0]].venue

    # Walk each leg's bid side (selling the running balance into the next asset).
    # The executable rate per leg is its sell VWAP; the product of the three is
    # the depth-aware cycle return, which is < 1 (negative gross) on consistent
    # books because every leg pays its half-spread. The fillable notional is the
    # binding minimum filled-notional across the three legs.
    rate_product = 1.0
    fillable_notional = float("inf")
    for leg in legs:
        result = vwap(books[leg], Side.SELL, target_notional)
        rate_product *= result.avg_price
        fillable_notional = min(fillable_notional, result.filled_notional)

    gross_bps = 1e4 * (rate_product - 1.0)
    return TriangularCycle(
        venue=venue,
        legs=legs,
        rate_product=rate_product,
        gross_bps=gross_bps,
        fillable_notional=fillable_notional,
    )
