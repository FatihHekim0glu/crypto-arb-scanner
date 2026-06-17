"""Order-book modelling, VWAP walking, and the synthetic generator.

Importing this subpackage has no side effects.
"""

from __future__ import annotations

from cryptoarb.books.model import OrderBook, make_book
from cryptoarb.books.synthetic import (
    SyntheticConfig,
    VenueSpec,
    consistent_triangular_books,
    synthetic_book,
    synthetic_books,
)
from cryptoarb.books.vwap import Side, VWAPResult, vwap

__all__ = [
    "OrderBook",
    "Side",
    "SyntheticConfig",
    "VWAPResult",
    "VenueSpec",
    "consistent_triangular_books",
    "make_book",
    "synthetic_book",
    "synthetic_books",
    "vwap",
]
