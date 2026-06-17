"""Order-book data model.

A frozen, slotted :class:`OrderBook` holds one venue's level-2 (L2) depth for a
single symbol at a single timestamp: a sorted ladder of ``(price, size)`` levels
on each side. Bids are sorted **descending** (best/highest first); asks are
sorted **ascending** (best/lowest first). Sizes are in base-asset units; prices
are in quote-asset units.

Importing this module has no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class OrderBook:
    """Immutable L2 order book for one venue/symbol at one timestamp.

    Attributes
    ----------
    venue:
        Venue identifier (e.g. ``"binance"``, ``"coinbase"``, ``"kraken"``).
    symbol:
        Unified symbol in ``BASE/QUOTE`` form (e.g. ``"BTC/USDT"``).
    bids:
        Buy-side ladder as a tuple of ``(price, size)`` levels, sorted by price
        **descending** (best bid first). Prices and sizes are strictly positive.
    asks:
        Sell-side ladder as a tuple of ``(price, size)`` levels, sorted by price
        **ascending** (best ask first). Prices and sizes are strictly positive.
    ts_ms:
        Exchange timestamp in milliseconds since the Unix epoch. Used by the
        replay path's staleness/embargo guard; never used for compute.
    """

    venue: str
    symbol: str
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    ts_ms: int = 0

    @property
    def best_bid(self) -> float:
        """Highest bid price, or raise :class:`BookError` if the bid side is empty."""
        raise NotImplementedError

    @property
    def best_ask(self) -> float:
        """Lowest ask price, or raise :class:`BookError` if the ask side is empty."""
        raise NotImplementedError

    @property
    def mid(self) -> float:
        """Mid price ``(best_bid + best_ask) / 2``.

        Raises
        ------
        BookError
            If either side is empty.
        """
        raise NotImplementedError

    @property
    def spread_bps(self) -> float:
        """Top-of-book spread in basis points: ``1e4 * (best_ask - best_bid) / mid``.

        NOTE: top-of-book is a *diagnostic only*; executable spreads MUST be
        measured by walking the book (see :func:`cryptoarb.books.vwap.vwap`).

        Raises
        ------
        BookError
            If either side is empty.
        """
        raise NotImplementedError

    def validate(self) -> None:
        """Assert the book's structural invariants.

        Checks: every level has strictly positive price and size; bids are
        sorted strictly descending in price; asks are sorted strictly ascending
        in price; the book is not crossed (``best_bid < best_ask``) when both
        sides are non-empty.

        Raises
        ------
        ValidationError
            If any level has a non-positive price/size or a side is mis-sorted.
        BookError
            If the book is crossed (``best_bid >= best_ask``).
        """
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this book."""
        raise NotImplementedError


def make_book(
    venue: str,
    symbol: str,
    bids: Sequence[tuple[float, float]],
    asks: Sequence[tuple[float, float]],
    *,
    ts_ms: int = 0,
    sort: bool = True,
) -> OrderBook:
    """Construct a validated :class:`OrderBook` from raw level sequences.

    Parameters
    ----------
    venue:
        Venue identifier.
    symbol:
        Unified ``BASE/QUOTE`` symbol.
    bids, asks:
        Sequences of ``(price, size)`` levels. If ``sort`` is ``True`` they are
        sorted into canonical order (bids descending, asks ascending) before
        the book is built; otherwise they are assumed already canonical.
    ts_ms:
        Exchange timestamp in milliseconds.
    sort:
        Whether to canonically sort each side before validating.

    Returns
    -------
    OrderBook
        A frozen, validated order book.

    Raises
    ------
    ValidationError
        If a level is malformed (non-positive price/size).
    BookError
        If the resulting book is crossed.
    """
    raise NotImplementedError
