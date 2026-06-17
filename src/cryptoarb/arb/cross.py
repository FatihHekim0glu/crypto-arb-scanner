"""Two-leg cross-exchange arbitrage scan.

Given the same symbol on two (or more) venues, the cross-exchange gross spread
for a target notional ``Q`` is the **sell-VWAP on the rich venue** minus the
**buy-VWAP on the cheap venue**, both walked to ``Q``. Pricing the spread off
walked books (not top-of-book) is what makes the resulting edge honest: the
deeper the required ``Q``, the more the gross spread shrinks.

Importing this module has no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook


@dataclass(frozen=True, slots=True)
class CrossLeg:
    """One side of a cross-exchange pair: where to buy cheap and sell rich.

    Attributes
    ----------
    buy_venue:
        The venue whose asks are lifted (the cheap side).
    sell_venue:
        The venue whose bids are hit (the rich side).
    buy_vwap:
        The depth-aware buy fill price on ``buy_venue`` for the target notional.
    sell_vwap:
        The depth-aware sell fill price on ``sell_venue`` for the target notional.
    fillable_notional:
        The notional fully fillable on BOTH legs (the binding minimum), in quote
        units.
    gross_bps:
        ``1e4 * (sell_vwap - buy_vwap) / buy_vwap`` — the executable gross spread.
    """

    buy_venue: str
    sell_venue: str
    buy_vwap: float
    sell_vwap: float
    fillable_notional: float
    gross_bps: float

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this leg."""
        raise NotImplementedError


def best_cross_leg(books: dict[str, OrderBook], target_notional: float) -> CrossLeg:
    """Find the most profitable buy-cheap / sell-rich venue pair for ``target_notional``.

    For each ordered pair of venues, walk the buyer's asks and the seller's bids
    to ``target_notional`` and compute the executable gross spread; return the
    pair with the largest ``gross_bps``. The fillable notional is the binding
    minimum of the two legs' fills.

    Parameters
    ----------
    books:
        Mapping of venue identifier to its order book (same symbol on each).
    target_notional:
        The quote-notional ``Q`` to price the spread for; strictly positive.

    Returns
    -------
    CrossLeg
        The best buy/sell venue pairing and its executable gross spread.

    Raises
    ------
    ValidationError
        If fewer than two venues are supplied or ``target_notional`` is not
        strictly positive.
    """
    raise NotImplementedError


def cross_gross_bps(
    buy_book: OrderBook, sell_book: OrderBook, target_notional: float
) -> float:
    """Return the executable cross-exchange gross spread (bps) for one venue pair.

    Walks ``buy_book``'s asks and ``sell_book``'s bids to ``target_notional`` and
    returns ``1e4 * (sell_vwap - buy_vwap) / buy_vwap``. A negative result means
    the "rich" venue is not actually rich at this depth.

    Parameters
    ----------
    buy_book:
        The book whose asks are lifted (buy leg).
    sell_book:
        The book whose bids are hit (sell leg).
    target_notional:
        The quote-notional ``Q`` to walk both legs to.

    Returns
    -------
    float
        The executable gross spread in basis points.

    Raises
    ------
    ValidationError
        If ``target_notional`` is not strictly positive.
    BookError
        If either required ladder is empty.
    """
    raise NotImplementedError
