"""On-disk L2 order-book cache.

A thin, typed wrapper around ``diskcache`` for memoizing fetched L2 books so the
live path can fall back to a recent cached snapshot before resorting to
synthetic data. ``diskcache`` is imported LAZILY inside the methods so importing
this module has no side effects and pulls in no optional dependency at import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cryptoarb.books.model import OrderBook


@dataclass(frozen=True, slots=True)
class BookCache:
    """Disk-backed cache of recently-fetched order books.

    Attributes
    ----------
    cache_dir:
        Filesystem directory the cache is stored in.
    ttl_seconds:
        Time-to-live for a cached book; reads older than this are treated as a
        miss so the staleness guard is never silently violated.
    """

    cache_dir: str
    ttl_seconds: float = 5.0

    def key(self, venue: str, symbol: str) -> str:
        """Return the canonical cache key for a ``(venue, symbol)`` pair."""
        raise NotImplementedError

    def get(self, venue: str, symbol: str) -> OrderBook | None:
        """Return a cached book for ``(venue, symbol)`` if fresh, else ``None``.

        Parameters
        ----------
        venue:
            Venue identifier.
        symbol:
            Unified ``BASE/QUOTE`` symbol.

        Returns
        -------
        OrderBook | None
            The cached book if present and within ``ttl_seconds``, else ``None``.
        """
        raise NotImplementedError

    def put(self, book: OrderBook) -> None:
        """Store ``book`` under its ``(venue, symbol)`` key with the current time.

        Parameters
        ----------
        book:
            The order book to cache.
        """
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this cache's config."""
        raise NotImplementedError
