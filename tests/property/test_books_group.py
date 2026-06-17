"""Property and parity tests for the ``books`` group.

Covers the invariants the brief pins for the order-book model, the walk-the-book
VWAP, and the deterministic synthetic generator:

- **Monotonicity** — a larger target notional ``Q`` yields a worse-or-equal VWAP
  (buy non-decreasing, sell non-increasing).
- **Partial fill** — ``fully_filled`` is ``False`` exactly when ``Q`` exceeds the
  book's total quotable depth.
- **VWAP parity** — the kernel matches a hand-rolled reference walk to ``1e-9``.
- **Scale-invariance** — scaling every price by a constant scales the VWAP by the
  same constant.
- **Determinism** — the synthetic generator emits byte-identical books for the
  same arguments.
- **Triangular no-arb identity** — three consistent legs multiply to ``1`` within
  ``1e-12``; a dislocation breaks it by the configured amount.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cryptoarb._exceptions import BookError, ValidationError
from cryptoarb.books.model import OrderBook, make_book
from cryptoarb.books.synthetic import (
    SyntheticConfig,
    VenueSpec,
    consistent_triangular_books,
    synthetic_book,
    synthetic_books,
)
from cryptoarb.books.vwap import Side, vwap

# --------------------------------------------------------------------------- #
# Reference oracle                                                            #
# --------------------------------------------------------------------------- #


def _reference_walk(
    book: OrderBook, side: Side, target_notional: float
) -> tuple[float, float, float, bool, int]:
    """Independent hand-rolled walk-the-book VWAP (the parity oracle)."""
    ladder = book.asks if side is Side.BUY else book.bids
    remaining = target_notional
    notion = 0.0
    base = 0.0
    levels = 0
    for price, size in ladder:
        if remaining <= 0.0:
            break
        take = min(remaining, price * size)
        base += take / price
        notion += take
        remaining -= take
        levels += 1
    avg = notion / base if base > 0.0 else math.nan
    return avg, notion, base, remaining <= 0.0, levels


# --------------------------------------------------------------------------- #
# Model                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_make_book_canonicalizes_and_exposes_top_of_book() -> None:
    """Out-of-order levels are sorted; best bid/ask/mid/spread are correct."""
    book = make_book(
        "binance",
        "BTC/USDT",
        bids=[(98.0, 1.0), (99.0, 2.0)],
        asks=[(102.0, 1.0), (101.0, 2.0)],
    )
    assert book.best_bid == 99.0
    assert book.best_ask == 101.0
    assert book.mid == 100.0
    assert book.spread_bps == pytest.approx(1e4 * 2.0 / 100.0)
    book.validate()  # does not raise


@pytest.mark.unit
def test_make_book_rejects_crossed_and_nonpositive() -> None:
    """A crossed book raises ``BookError``; a non-positive level ``ValidationError``."""
    with pytest.raises(BookError):
        make_book("x", "A/B", bids=[(101.0, 1.0)], asks=[(100.0, 1.0)])
    with pytest.raises(ValidationError):
        make_book("x", "A/B", bids=[(99.0, -1.0)], asks=[(101.0, 1.0)])
    with pytest.raises(ValidationError):
        make_book("x", "A/B", bids=[(-99.0, 1.0)], asks=[(101.0, 1.0)])


@pytest.mark.unit
def test_empty_side_raises_book_error() -> None:
    """Accessing top-of-book / mid on an empty side raises ``BookError``."""
    one_sided = OrderBook(venue="x", symbol="A/B", bids=(), asks=((101.0, 1.0),))
    with pytest.raises(BookError):
        _ = one_sided.best_bid
    with pytest.raises(BookError):
        _ = one_sided.mid


@pytest.mark.unit
def test_order_book_to_dict_roundtrips() -> None:
    """``to_dict`` is plain/JSON-serializable and preserves the ladders."""
    book = make_book("kraken", "ETH/USD", bids=[(99.0, 2.0)], asks=[(101.0, 3.0)])
    payload = book.to_dict()
    assert payload["venue"] == "kraken"
    assert payload["bids"] == [[99.0, 2.0]]
    assert payload["asks"] == [[101.0, 3.0]]
    assert isinstance(payload["ts_ms"], int)


# --------------------------------------------------------------------------- #
# VWAP                                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parity
def test_vwap_parity_against_reference(deep_vs_thin_book: dict[str, OrderBook]) -> None:
    """The VWAP kernel matches the hand-rolled reference walk to 1e-9."""
    for book in deep_vs_thin_book.values():
        for side in (Side.BUY, Side.SELL):
            for notional in (50.0, 1_000.0, 25_000.0, 9_999_999.0):
                result = vwap(book, side, notional)
                avg, notion, base, full, levels = _reference_walk(book, side, notional)
                if base > 0.0:
                    assert result.avg_price == pytest.approx(avg, abs=1e-9)
                assert result.filled_notional == pytest.approx(notion, abs=1e-9)
                assert result.filled_base == pytest.approx(base, abs=1e-9)
                assert result.fully_filled is full
                assert result.levels_consumed == levels


@pytest.mark.property
@given(
    q_small=st.floats(min_value=1.0, max_value=1e4, allow_nan=False),
    q_extra=st.floats(min_value=0.0, max_value=1e6, allow_nan=False),
)
def test_vwap_monotone_in_notional(q_small: float, q_extra: float) -> None:
    """A larger ``Q`` is worse-or-equal: buy VWAP up, sell VWAP down."""
    book = make_book(
        "v",
        "A/B",
        bids=[(100.0, 5.0), (99.0, 5.0), (98.0, 5.0), (97.0, 5.0)],
        asks=[(101.0, 5.0), (102.0, 5.0), (103.0, 5.0), (104.0, 5.0)],
    )
    q_large = q_small + q_extra
    buy_small = vwap(book, Side.BUY, q_small).avg_price
    buy_large = vwap(book, Side.BUY, q_large).avg_price
    sell_small = vwap(book, Side.SELL, q_small).avg_price
    sell_large = vwap(book, Side.SELL, q_large).avg_price
    assert buy_large >= buy_small - 1e-9
    assert sell_large <= sell_small + 1e-9


@pytest.mark.property
def test_vwap_partial_fill_flagged_past_depth(
    deep_vs_thin_book: dict[str, OrderBook],
) -> None:
    """``Q`` beyond total depth flags a partial fill; within depth fills fully."""
    thin = deep_vs_thin_book["thin"]
    total_ask_depth = sum(price * size for price, size in thin.asks)
    over = vwap(thin, Side.BUY, total_ask_depth * 2.0)
    assert over.fully_filled is False
    assert over.filled_notional < total_ask_depth * 2.0
    assert over.filled_notional == pytest.approx(total_ask_depth, rel=1e-9)
    within = vwap(thin, Side.BUY, total_ask_depth * 0.5)
    assert within.fully_filled is True


@pytest.mark.property
@given(scale=st.floats(min_value=1e-3, max_value=1e3, allow_nan=False))
def test_vwap_scale_invariance(scale: float) -> None:
    """Scaling every price by ``c`` scales the VWAP by ``c``."""
    base_book = make_book(
        "s", "A/B", bids=[(100.0, 5.0), (99.0, 5.0)], asks=[(101.0, 5.0), (102.0, 5.0)]
    )
    scaled_book = make_book(
        "s",
        "A/B",
        bids=[(100.0 * scale, 5.0), (99.0 * scale, 5.0)],
        asks=[(101.0 * scale, 5.0), (102.0 * scale, 5.0)],
    )
    notional = 400.0
    base_avg = vwap(base_book, Side.BUY, notional).avg_price
    scaled_avg = vwap(scaled_book, Side.BUY, notional * scale).avg_price
    assert scaled_avg == pytest.approx(base_avg * scale, rel=1e-9)


@pytest.mark.unit
def test_vwap_rejects_nonpositive_notional_and_empty_side() -> None:
    """A non-positive ``Q`` raises ``ValidationError``; an empty ladder ``BookError``."""
    book = make_book("v", "A/B", bids=[(99.0, 1.0)], asks=[(101.0, 1.0)])
    with pytest.raises(ValidationError):
        vwap(book, Side.BUY, 0.0)
    one_sided = OrderBook(venue="v", symbol="A/B", bids=(), asks=((101.0, 1.0),))
    with pytest.raises(BookError):
        vwap(one_sided, Side.SELL, 10.0)


# --------------------------------------------------------------------------- #
# Synthetic generator                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.property
def test_synthetic_books_are_deterministic() -> None:
    """The same ``(config, seed)`` yields byte-identical books, even with noise."""
    config = SyntheticConfig(
        venues=(VenueSpec("binance"), VenueSpec("coinbase"), VenueSpec("kraken")),
        size_noise=0.1,
    )
    first = synthetic_books(config, seed=11)
    second = synthetic_books(config, seed=11)
    assert {k: v.to_dict() for k, v in first.items()} == {k: v.to_dict() for k, v in second.items()}
    for book in first.values():
        book.validate()


@pytest.mark.property
def test_synthetic_books_dislocation_only_skews_last_venue() -> None:
    """A non-zero dislocation shifts only the last venue's mid; others are clean."""
    venues = (VenueSpec("binance"), VenueSpec("coinbase"), VenueSpec("kraken"))
    clean = synthetic_books(SyntheticConfig(venues=venues), seed=0)
    skewed = synthetic_books(SyntheticConfig(venues=venues, dislocation_bps=8.0), seed=0)
    assert clean["binance"].mid == pytest.approx(skewed["binance"].mid)
    assert clean["coinbase"].mid == pytest.approx(skewed["coinbase"].mid)
    assert skewed["kraken"].mid > clean["kraken"].mid


@pytest.mark.unit
def test_synthetic_book_applies_mid_offset() -> None:
    """A single venue's mid equals ``true_mid * (1 + offset_bps/1e4)``."""
    true_mid = 50_000.0
    spec = VenueSpec("binance", mid_offset_bps=5.0)
    book = synthetic_book(spec, symbol="BTC/USDT", true_mid=true_mid, seed=0)
    book.validate()
    assert book.mid == pytest.approx(true_mid * (1.0 + 5.0 / 1e4), rel=1e-9)


@pytest.mark.unit
def test_synthetic_books_rejects_empty_config() -> None:
    """A config with no venues raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        synthetic_books(SyntheticConfig(venues=()))


@pytest.mark.unit
def test_synthetic_book_rejects_bad_spec() -> None:
    """Out-of-domain venue parameters raise ``ValidationError``."""
    with pytest.raises(ValidationError):
        synthetic_book(VenueSpec("x", half_spread_bps=0.0), symbol="A/B", true_mid=100.0, seed=0)
    with pytest.raises(ValidationError):
        synthetic_book(VenueSpec("x", depth_decay=1.5), symbol="A/B", true_mid=100.0, seed=0)


@pytest.mark.parity
@pytest.mark.parametrize("seed", [0, 1, 7, 42, 123])
def test_triangular_no_arb_identity_holds_to_1e_12(seed: int) -> None:
    """Three consistent legs multiply to 1 within 1e-12 (the no-arb identity)."""
    legs = consistent_triangular_books(seed=seed)
    product = legs["A/B"].mid * legs["B/C"].mid * legs["C/A"].mid
    assert abs(product - 1.0) < 1e-12
    for book in legs.values():
        book.validate()


@pytest.mark.property
def test_triangular_dislocation_breaks_identity_by_known_amount() -> None:
    """A dislocation perturbs the cycle product by ~the configured bps."""
    dislocation_bps = 25.0
    legs = consistent_triangular_books(seed=3, dislocation_bps=dislocation_bps)
    product = legs["A/B"].mid * legs["B/C"].mid * legs["C/A"].mid
    assert product == pytest.approx(1.0 + dislocation_bps / 1e4, rel=1e-6)


@pytest.mark.unit
def test_triangular_rejects_nonpositive_mids() -> None:
    """Non-positive leg mids and half-spreads raise ``ValidationError``."""
    with pytest.raises(ValidationError):
        consistent_triangular_books(mid_ab=0.0)
    with pytest.raises(ValidationError):
        consistent_triangular_books(mid_bc=-1.0)
    with pytest.raises(ValidationError):
        consistent_triangular_books(half_spread_bps=0.0)


# --------------------------------------------------------------------------- #
# to_dict / serialization coverage                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_spec_and_config_to_dict_are_plain() -> None:
    """``VenueSpec`` / ``SyntheticConfig`` ``to_dict`` are JSON-friendly and nested."""
    spec = VenueSpec("binance", half_spread_bps=1.5, depth_base=8.0, n_levels=3)
    spec_payload = spec.to_dict()
    assert spec_payload["venue"] == "binance"
    assert spec_payload["n_levels"] == 3

    config = SyntheticConfig(venues=(spec,), size_noise=0.05)
    config_payload = config.to_dict()
    assert config_payload["venues"] == [spec_payload]
    assert config_payload["size_noise"] == pytest.approx(0.05)


@pytest.mark.unit
def test_vwap_result_to_dict_is_plain() -> None:
    """``VWAPResult.to_dict`` returns plain JSON-serializable scalars."""
    book = make_book("v", "A/B", bids=[(99.0, 5.0)], asks=[(101.0, 5.0)])
    payload = vwap(book, Side.BUY, 100.0).to_dict()
    assert payload["side"] == "buy"
    assert payload["fully_filled"] is True
    assert isinstance(payload["levels_consumed"], int)
    assert payload["avg_price"] == pytest.approx(101.0)


# --------------------------------------------------------------------------- #
# Remaining domain guards                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_synthetic_book_rejects_more_bad_specs_and_mids() -> None:
    """Each out-of-domain spec parameter and a non-positive true mid is rejected."""
    good_args = {"symbol": "A/B", "true_mid": 100.0, "seed": 0}
    with pytest.raises(ValidationError):
        synthetic_book(VenueSpec("x", depth_base=0.0), **good_args)
    with pytest.raises(ValidationError):
        synthetic_book(VenueSpec("x", n_levels=0), **good_args)
    with pytest.raises(ValidationError):
        synthetic_book(VenueSpec("x", tick_bps=0.0), **good_args)
    with pytest.raises(ValidationError):
        synthetic_book(VenueSpec("x"), symbol="A/B", true_mid=0.0, seed=0)


@pytest.mark.unit
def test_synthetic_books_rejects_nonpositive_true_mid() -> None:
    """A non-positive ``true_mid`` on the multi-venue config is rejected."""
    with pytest.raises(ValidationError):
        synthetic_books(SyntheticConfig(true_mid=0.0, venues=(VenueSpec("x"),)))


@pytest.mark.unit
def test_one_sided_ask_empty_raises() -> None:
    """An empty ask side raises ``BookError`` on ``best_ask``."""
    bids_only = OrderBook(venue="x", symbol="A/B", bids=((99.0, 1.0),), asks=())
    with pytest.raises(BookError):
        _ = bids_only.best_ask


@pytest.mark.unit
def test_validate_rejects_mis_sorted_ask_side() -> None:
    """An unsorted ask ladder (``sort=False``) trips the ascending-order guard."""
    with pytest.raises(ValidationError):
        make_book(
            "x",
            "A/B",
            bids=[(99.0, 1.0)],
            asks=[(102.0, 1.0), (101.0, 1.0)],
            sort=False,
        )
