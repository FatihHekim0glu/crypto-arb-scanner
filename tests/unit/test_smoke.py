"""Smoke tests: the package imports cleanly and stubs expose their contracts.

These are deliberately minimal - they guard import-purity and the public API
surface while the real behaviour is filled in by parallel authors. They must
keep passing for the build to stay green.
"""

from __future__ import annotations

import pytest

import cryptoarb
from cryptoarb.books.model import OrderBook


@pytest.mark.unit
def test_package_imports_and_has_version() -> None:
    """The top-level package imports and exposes a version string."""
    assert isinstance(cryptoarb.__version__, str)
    assert cryptoarb.__version__


@pytest.mark.unit
def test_public_api_is_exported() -> None:
    """Every name in ``__all__`` is actually importable from the package."""
    for name in cryptoarb.__all__:
        assert hasattr(cryptoarb, name), f"missing public export: {name}"


@pytest.mark.unit
def test_consistent_books_fixture_is_well_formed(
    consistent_books: dict[str, OrderBook],
) -> None:
    """The consistent-books fixture yields canonically-sorted, uncrossed books."""
    assert set(consistent_books) == {"binance", "coinbase", "kraken"}
    for book in consistent_books.values():
        assert book.bids and book.asks
        # bids descending, asks ascending (canonical order).
        bid_prices = [p for p, _ in book.bids]
        ask_prices = [p for p, _ in book.asks]
        assert bid_prices == sorted(bid_prices, reverse=True)
        assert ask_prices == sorted(ask_prices)
        # not crossed at top of book.
        assert book.bids[0][0] < book.asks[0][0]


@pytest.mark.unit
def test_deep_vs_thin_book_depth_ordering(
    deep_vs_thin_book: dict[str, OrderBook],
) -> None:
    """The deep book carries strictly more top-of-book size than the thin book."""
    deep = deep_vs_thin_book["deep"]
    thin = deep_vs_thin_book["thin"]
    assert deep.asks[0][1] > thin.asks[0][1]
    assert deep.bids[0][1] > thin.bids[0][1]
