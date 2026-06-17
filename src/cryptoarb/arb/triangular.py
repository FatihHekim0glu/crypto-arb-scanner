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

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook


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
        raise NotImplementedError


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
    raise NotImplementedError


def triangular_cycle(
    books: dict[str, OrderBook], target_notional: float
) -> TriangularCycle:
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
    raise NotImplementedError
