"""Walk-the-book VWAP: the executable price for a target notional.

The honest, depth-aware way to price a trade is to *walk the book*: consume
levels in priority order until the target quote-notional ``Q`` is filled,
accumulating a size-weighted average fill price. A buy consumes **asks** (best
ask first); a sell consumes **bids** (best bid first). Using top-of-book only is
a hidden over-claim, because top-of-book fillable size is almost always smaller
than a realistic ``Q``.

Importing this module has no side effects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from cryptoarb._exceptions import BookError, ValidationError

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook


class Side(StrEnum):
    """Trade direction relative to the book.

    ``BUY`` lifts offers (consumes the ask ladder); ``SELL`` hits bids (consumes
    the bid ladder).
    """

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class VWAPResult:
    """Outcome of walking a book to fill a target quote-notional.

    Attributes
    ----------
    side:
        The trade direction that was walked.
    target_notional:
        The requested quote-notional ``Q`` (in quote-asset units).
    filled_notional:
        The quote-notional actually filled (``<= target_notional``; equals it
        when ``fully_filled`` is ``True``).
    avg_price:
        The size-weighted average executable price across consumed levels, or
        ``nan`` if no size was available at all.
    filled_base:
        The base-asset quantity filled.
    fully_filled:
        Whether the book had enough depth to fill ``target_notional`` entirely.
    levels_consumed:
        The number of price levels (partially or fully) consumed.
    """

    side: Side
    target_notional: float
    filled_notional: float
    avg_price: float
    filled_base: float
    fully_filled: bool
    levels_consumed: int

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this result."""
        return {
            "side": self.side.value,
            "target_notional": float(self.target_notional),
            "filled_notional": float(self.filled_notional),
            "avg_price": float(self.avg_price),
            "filled_base": float(self.filled_base),
            "fully_filled": bool(self.fully_filled),
            "levels_consumed": int(self.levels_consumed),
        }


def vwap(book: OrderBook, side: Side, target_notional: float) -> VWAPResult:
    """Walk ``book`` on ``side`` to fill ``target_notional`` and return the VWAP.

    The relevant ladder is consumed in priority order (asks ascending for a buy,
    bids descending for a sell). Each level contributes ``min(remaining_notional,
    level_price * level_size)`` of fill; the average price is the filled
    quote-notional divided by the filled base quantity.

    GUARANTEES (property-tested):
    - Monotonicity: for a fixed book and side, a larger ``target_notional``
      yields an ``avg_price`` no better than a smaller one (worse-or-equal: a buy
      VWAP is non-decreasing in ``Q``; a sell VWAP is non-increasing in ``Q``).
    - Scale-invariance: scaling every price in the book by a constant scales
      ``avg_price`` by the same constant.

    Parameters
    ----------
    book:
        The order book to walk.
    side:
        ``Side.BUY`` (consume asks) or ``Side.SELL`` (consume bids).
    target_notional:
        The quote-notional ``Q`` to fill; must be strictly positive.

    Returns
    -------
    VWAPResult
        The fill outcome, including whether ``Q`` was fully fillable.

    Raises
    ------
    ValidationError
        If ``target_notional`` is not strictly positive.
    BookError
        If the relevant ladder is empty.
    """
    if not (target_notional > 0.0):
        raise ValidationError(
            f"vwap: target_notional must be strictly positive, got {target_notional}."
        )

    ladder = book.asks if side is Side.BUY else book.bids
    if not ladder:
        empty_side = "ask" if side is Side.BUY else "bid"
        raise BookError(f"{book.venue} {book.symbol}: {empty_side} side is empty; cannot quote.")

    remaining = float(target_notional)
    filled_notional = 0.0
    filled_base = 0.0
    levels_consumed = 0
    for price, size in ladder:
        if remaining <= 0.0:
            break
        level_notional = price * size
        take_notional = min(remaining, level_notional)
        # Base filled at this level is the notional taken divided by the level price.
        filled_base += take_notional / price
        filled_notional += take_notional
        remaining -= take_notional
        levels_consumed += 1

    fully_filled = remaining <= 0.0
    avg_price = filled_notional / filled_base if filled_base > 0.0 else math.nan
    return VWAPResult(
        side=side,
        target_notional=float(target_notional),
        filled_notional=filled_notional,
        avg_price=avg_price,
        filled_base=filled_base,
        fully_filled=fully_filled,
        levels_consumed=levels_consumed,
    )
