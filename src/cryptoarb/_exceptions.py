"""Typed exception hierarchy for the cryptoarb library.

A single base (:class:`CryptoArbError`) lets callers catch any library-raised
error with one ``except`` clause, while the specific subclasses let them
distinguish input-shape problems from order-book / liquidity-degeneracy
problems. Importing this module has no side effects.
"""

from __future__ import annotations

# quantcore-candidate: mirrors risk-metrics:src/riskmetrics/_exceptions.py


class CryptoArbError(Exception):
    """Base class for every exception raised by :mod:`cryptoarb`.

    Catching ``CryptoArbError`` catches all library-specific failures while
    letting unrelated exceptions (e.g. ``KeyboardInterrupt``) propagate.
    """


class ValidationError(CryptoArbError):
    """Raised when an input fails a shape, dtype, ordering, or domain check.

    Examples: a negative price or size in an order-book level, a notional that
    is non-positive, an unsorted bid/ask ladder, a fee schedule with a negative
    rate, or an unknown venue/fee-profile identifier.
    """


class InsufficientDataError(ValidationError):
    """Raised when there are too few observations to estimate the requested quantity.

    For example, an empty net-edge series passed to the DSR/PSR effective-trials
    machinery, or a replay window with no quotes at or before the decision time.
    It subclasses :class:`ValidationError` because "not enough data" is a special
    case of a failed input precondition.
    """


class BookError(CryptoArbError):
    """Raised when an order book is structurally invalid or empty where depth is required.

    Examples: a book whose best bid exceeds (or crosses) its best ask, a side
    with no levels when one is required to quote, or a triangular cycle whose
    legs do not chain (the quote/base currencies fail to compose into a loop).
    """


class LiquidityError(CryptoArbError):
    """Raised when a book cannot fill a requested notional and the caller demands a full fill.

    Walking the book for a target notional ``Q`` may exhaust every level before
    ``Q`` is reached. Callers that require a *fully fillable* quote (rather than a
    partial fill flag) receive this error; callers that tolerate partial fills
    inspect the ``fully_filled`` flag on the VWAP result instead.
    """
