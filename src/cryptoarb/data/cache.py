"""On-disk L2 order-book cache.

A thin, typed wrapper around ``diskcache`` for memoizing fetched L2 books so the
live path can fall back to a recent cached snapshot before resorting to
synthetic data. ``diskcache`` is imported LAZILY inside the methods so importing
this module has no side effects and pulls in no optional dependency at import.

A cached entry stores the :class:`~cryptoarb.books.model.OrderBook` together with
the wall-clock time it was written. Reads older than ``ttl_seconds`` are treated
as a miss so the live path never silently serves a stale book past its embargo.
"""

from __future__ import annotations

import time
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
        """Return the canonical cache key for a ``(venue, symbol)`` pair.

        The key is namespaced and normalized so equivalent identifiers collapse
        to one slot regardless of surrounding whitespace or letter case.
        """
        return f"book::{venue.strip().lower()}::{symbol.strip().upper()}"

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
            A missing/corrupt entry or an unavailable ``diskcache`` backend is a
            silent miss — the cache is a best-effort accelerator, never a hard
            dependency.
        """
        try:
            import diskcache
        except Exception:  # pragma: no cover - diskcache is a declared dep
            return None

        try:
            with diskcache.Cache(self.cache_dir) as store:
                entry = store.get(self.key(venue, symbol))
        except Exception:
            return None

        if not isinstance(entry, tuple) or len(entry) != 2:
            return None
        book, stored_at = entry
        try:
            age = time.time() - float(stored_at)
        except (TypeError, ValueError):
            return None
        if age < 0.0 or age > self.ttl_seconds:
            return None
        return book  # type: ignore[no-any-return]

    def put(self, book: OrderBook) -> None:
        """Store ``book`` under its ``(venue, symbol)`` key with the current time.

        Parameters
        ----------
        book:
            The order book to cache. Its ``venue``/``symbol`` form the key.

        Notes
        -----
        A failure to open or write the backing store is swallowed: caching is a
        best-effort optimization and must never break the live fetch path.
        """
        try:
            import diskcache
        except Exception:  # pragma: no cover - diskcache is a declared dep
            return

        try:
            with diskcache.Cache(self.cache_dir) as store:
                store.set(self.key(book.venue, book.symbol), (book, time.time()))
        except Exception:
            return

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this cache's config."""
        return {"cache_dir": self.cache_dir, "ttl_seconds": float(self.ttl_seconds)}
