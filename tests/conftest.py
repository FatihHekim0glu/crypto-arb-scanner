"""Shared, seeded test fixtures.

Every fixture is deterministic and returns plain :class:`cryptoarb.books.model.OrderBook`
instances built from explicit sorted ``(price, size)`` ladders, so the suite
shares identical synthetic books with known structure WITHOUT depending on the
(stubbed) synthetic generator:

- ``consistent_books`` - per-venue L2 books all centered on the same true mid
  with NO cross-venue dislocation, so the cross-exchange no-arb condition holds
  and the net edge is expected to collapse (the honest-null fixture).
- ``dislocated_books`` - the same venues but with one venue skewed by a small
  signed offset, manufacturing an *apparently* exploitable gap that the cost
  waterfall is expected to erase.
- ``deep_vs_thin_book`` - a pair of books for the SAME mid where one side is deep
  and the other thin, used to pin the VWAP monotonicity / depth-realism guards.

Importing this module has no side effects beyond fixture registration.
"""

from __future__ import annotations

import pytest

from cryptoarb.books.model import OrderBook

_SEED = 20260617

#: Global true mid all consistent venues are referenced to.
_TRUE_MID = 50_000.0


def _ladder(
    mid: float,
    *,
    half_spread_bps: float,
    depth_base: float,
    n_levels: int = 10,
    tick_bps: float = 1.0,
    depth_decay: float = 0.85,
) -> tuple[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...]]:
    """Build a ``(bids, asks)`` pair of canonically-sorted ``(price, size)`` ladders.

    Bids descend from just below ``mid``; asks ascend from just above it. Sizes
    decay geometrically with depth. Deterministic (no randomness): a pure
    function of its arguments.
    """
    half = mid * half_spread_bps / 1e4
    tick = mid * tick_bps / 1e4
    bids: list[tuple[float, float]] = []
    asks: list[tuple[float, float]] = []
    for level in range(n_levels):
        size = depth_base * (depth_decay**level)
        bid_price = mid - half - level * tick
        ask_price = mid + half + level * tick
        bids.append((round(bid_price, 8), round(size, 8)))
        asks.append((round(ask_price, 8), round(size, 8)))
    # Bids already descending (best/highest first); asks already ascending.
    return tuple(bids), tuple(asks)


def _book(
    venue: str,
    mid: float,
    *,
    symbol: str = "BTC/USDT",
    half_spread_bps: float = 2.0,
    depth_base: float = 5.0,
    n_levels: int = 10,
    ts_ms: int = 1_700_000_000_000,
) -> OrderBook:
    """Construct a frozen :class:`OrderBook` from an explicit ladder."""
    bids, asks = _ladder(
        mid,
        half_spread_bps=half_spread_bps,
        depth_base=depth_base,
        n_levels=n_levels,
    )
    return OrderBook(venue=venue, symbol=symbol, bids=bids, asks=asks, ts_ms=ts_ms)


@pytest.fixture
def seed() -> int:
    """The shared deterministic seed for tests that need raw randomness."""
    return _SEED


@pytest.fixture
def consistent_books() -> dict[str, OrderBook]:
    """Three per-venue books with NO cross-venue dislocation (no-arb holds).

    All three venues straddle the same ``_TRUE_MID`` with their own symmetric
    half-spreads. The best bid on any venue sits below the best ask on every
    venue, so no cross-exchange spread survives even before costs - the honest
    null on which ``net_bps`` must be ``<= 0`` / ``no_feasible_edge``.
    """
    return {
        "binance": _book("binance", _TRUE_MID, half_spread_bps=1.5, depth_base=8.0),
        "coinbase": _book("coinbase", _TRUE_MID, half_spread_bps=2.5, depth_base=4.0),
        "kraken": _book("kraken", _TRUE_MID, half_spread_bps=2.0, depth_base=5.0),
    }


@pytest.fixture
def dislocated_books() -> dict[str, OrderBook]:
    """Three books where one venue is skewed to fake a small exploitable gap.

    ``kraken``'s mid is shifted up by ~8 bps, so its bids sit above the other
    venues' asks at the top of book - an *apparent* cross-exchange opportunity.
    The headline claim is that the cost waterfall erases it; this fixture is the
    input that proves the collapse rather than the absence of a raw spread.
    """
    dislocation = _TRUE_MID * (1.0 + 8.0 / 1e4)  # +8 bps on kraken
    return {
        "binance": _book("binance", _TRUE_MID, half_spread_bps=1.5, depth_base=8.0),
        "coinbase": _book("coinbase", _TRUE_MID, half_spread_bps=2.5, depth_base=4.0),
        "kraken": _book("kraken", dislocation, half_spread_bps=2.0, depth_base=5.0),
    }


@pytest.fixture
def deep_vs_thin_book() -> dict[str, OrderBook]:
    """A deep book and a thin book at the SAME mid, for VWAP depth-realism tests.

    Both straddle ``_TRUE_MID`` with the same spread; ``deep`` carries ~20x the
    size per level of ``thin``. Walking a large notional on ``thin`` must produce
    a materially worse VWAP than on ``deep`` (and a partial fill past its depth),
    pinning the "larger Q => worse VWAP" and fillability guards.
    """
    return {
        "deep": _book("deep", _TRUE_MID, half_spread_bps=2.0, depth_base=50.0, n_levels=20),
        "thin": _book("thin", _TRUE_MID, half_spread_bps=2.0, depth_base=0.05, n_levels=6),
    }
