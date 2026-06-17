"""Deterministic synthetic consistent-order-book generator.

This is the backbone of the offline test suite. Given a true mid, per-venue
spread/offset/depth parameters, and a seed, it emits internally consistent
per-venue L2 books. With **no cross-venue dislocation** every venue is centered
on the same true mid (up to its own half-spread), so the cross-exchange no-arb
condition holds and the net edge collapses — the honest-null fixture. A small
dislocation can be injected to produce an *apparently* exploitable gap that the
cost waterfall is expected to erase.

For triangular scans the generator builds three single-venue books
(``A/B``, ``B/C``, ``C/A``) whose mids multiply to ``1`` (the no-arb identity)
to within ``1e-12`` on the consistent fixture.

All randomness flows through :func:`cryptoarb._rng.make_rng`; the same arguments
always produce byte-identical books. Importing this module has no side effects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from cryptoarb._exceptions import ValidationError
from cryptoarb._rng import make_rng, spawn_substreams
from cryptoarb.books.model import OrderBook

#: Significant figures retained when rounding generated prices. Rounding to
#: significant figures (not fixed decimals) keeps ladders clean and strictly
#: monotone at ANY price scale — from ~50_000 (BTC) down to the ~1e-8 third leg
#: of a triangular cycle — where fixed-decimal rounding would collapse adjacent
#: levels onto the same grid value and break the strict-ordering invariant.
_PRICE_SIG_FIGS: int = 12


@dataclass(frozen=True, slots=True)
class VenueSpec:
    """Per-venue order-book shape parameters.

    Attributes
    ----------
    venue:
        Venue identifier.
    half_spread_bps:
        Half the top-of-book spread, in basis points, applied symmetrically
        around the venue's mid.
    mid_offset_bps:
        Signed offset of this venue's mid from the global true mid, in basis
        points. Zero on every venue means no cross-venue dislocation.
    depth_base:
        Base-asset size available at the first level; deeper levels decay by
        ``depth_decay`` per level.
    n_levels:
        Number of price levels generated per side.
    depth_decay:
        Multiplicative size decay per level (``0 < depth_decay <= 1``).
    tick_bps:
        Price increment between consecutive levels, in basis points of the mid.
    """

    venue: str
    half_spread_bps: float = 2.0
    mid_offset_bps: float = 0.0
    depth_base: float = 5.0
    n_levels: int = 25
    depth_decay: float = 0.85
    tick_bps: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this spec."""
        return {
            "venue": self.venue,
            "half_spread_bps": float(self.half_spread_bps),
            "mid_offset_bps": float(self.mid_offset_bps),
            "depth_base": float(self.depth_base),
            "n_levels": int(self.n_levels),
            "depth_decay": float(self.depth_decay),
            "tick_bps": float(self.tick_bps),
        }


@dataclass(frozen=True, slots=True)
class SyntheticConfig:
    """Top-level configuration for a synthetic multi-venue snapshot.

    Attributes
    ----------
    symbol:
        Unified ``BASE/QUOTE`` symbol for the generated books.
    true_mid:
        The global "fair" mid price all venues are referenced to.
    venues:
        Per-venue shape specs.
    dislocation_bps:
        If non-zero, an extra signed mid offset (in bps) applied to the LAST
        venue in ``venues`` to manufacture an apparently exploitable gap. Zero
        produces the consistent (no-arb) fixture.
    size_noise:
        Relative multiplicative noise applied to level sizes (``0`` = none).
    ts_ms:
        Exchange timestamp stamped onto every generated book.
    """

    symbol: str = "BTC/USDT"
    true_mid: float = 50_000.0
    venues: tuple[VenueSpec, ...] = field(default_factory=tuple)
    dislocation_bps: float = 0.0
    size_noise: float = 0.0
    ts_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-serializable ``dict`` of this config."""
        return {
            "symbol": self.symbol,
            "true_mid": float(self.true_mid),
            "venues": [spec.to_dict() for spec in self.venues],
            "dislocation_bps": float(self.dislocation_bps),
            "size_noise": float(self.size_noise),
            "ts_ms": int(self.ts_ms),
        }


def _validate_spec(spec: VenueSpec) -> None:
    """Assert a :class:`VenueSpec`'s shape parameters are in domain."""
    if not (spec.half_spread_bps > 0.0):
        raise ValidationError(
            f"{spec.venue}: half_spread_bps must be positive, got {spec.half_spread_bps}."
        )
    if not (spec.depth_base > 0.0):
        raise ValidationError(f"{spec.venue}: depth_base must be positive, got {spec.depth_base}.")
    if spec.n_levels < 1:
        raise ValidationError(f"{spec.venue}: n_levels must be >= 1, got {spec.n_levels}.")
    if not (0.0 < spec.depth_decay <= 1.0):
        raise ValidationError(
            f"{spec.venue}: depth_decay must be in (0, 1], got {spec.depth_decay}."
        )
    if not (spec.tick_bps > 0.0):
        raise ValidationError(f"{spec.venue}: tick_bps must be positive, got {spec.tick_bps}.")


def _round_sig(value: float, sig_figs: int) -> float:
    """Round ``value`` to ``sig_figs`` significant figures (scale-independent).

    Keeps the synthetic books' price grid clean and JSON-friendly while
    preserving strict price ordering across many orders of magnitude. ``0`` is
    returned unchanged (it has no significant figures to round to).
    """
    if value == 0.0 or not math.isfinite(value):
        return value
    digits = sig_figs - 1 - math.floor(math.log10(abs(value)))
    return round(value, digits)


def _build_ladders(
    venue_mid: float,
    spec: VenueSpec,
    *,
    size_noise: float,
    seed: int,
) -> tuple[tuple[tuple[float, float], ...], tuple[tuple[float, float], ...]]:
    """Build canonically-sorted ``(bids, asks)`` ladders around ``venue_mid``.

    Bids descend from just below the mid by ``half_spread_bps``; asks ascend from
    just above it; deeper levels step away by ``tick_bps`` and decay in size by
    ``depth_decay``. When ``size_noise`` is non-zero each level's size is
    perturbed by a deterministic, seeded multiplicative factor. Prices are
    rounded to significant figures so the strict-ordering invariant holds at any
    price scale.
    """
    half = venue_mid * spec.half_spread_bps / 1e4
    tick = venue_mid * spec.tick_bps / 1e4

    rng = make_rng(seed) if size_noise > 0.0 else None
    bids: list[tuple[float, float]] = []
    asks: list[tuple[float, float]] = []
    for level in range(spec.n_levels):
        base_size = spec.depth_base * (spec.depth_decay**level)
        if rng is not None:
            # Symmetric multiplicative noise in [1 - size_noise, 1 + size_noise],
            # floored away from zero so every level keeps strictly positive size.
            bid_factor = 1.0 + size_noise * float(rng.uniform(-1.0, 1.0))
            ask_factor = 1.0 + size_noise * float(rng.uniform(-1.0, 1.0))
            bid_size = max(base_size * bid_factor, base_size * 1e-3)
            ask_size = max(base_size * ask_factor, base_size * 1e-3)
        else:
            bid_size = ask_size = base_size
        bid_price = venue_mid - half - level * tick
        ask_price = venue_mid + half + level * tick
        bids.append((_round_sig(bid_price, _PRICE_SIG_FIGS), _round_sig(bid_size, 10)))
        asks.append((_round_sig(ask_price, _PRICE_SIG_FIGS), _round_sig(ask_size, 10)))
    # Bids already descending (best/highest first); asks already ascending.
    return tuple(bids), tuple(asks)


def synthetic_book(spec: VenueSpec, *, symbol: str, true_mid: float, seed: int) -> OrderBook:
    """Generate one venue's L2 book from a :class:`VenueSpec`.

    The venue mid is ``true_mid * (1 + mid_offset_bps / 1e4)``; the best bid/ask
    straddle it by ``half_spread_bps``; deeper levels step away by ``tick_bps``
    with sizes decaying by ``depth_decay``. Sizes are perturbed only if the
    caller's generator is seeded for noise.

    Parameters
    ----------
    spec:
        The venue shape parameters.
    symbol:
        Unified ``BASE/QUOTE`` symbol.
    true_mid:
        The global fair mid the venue is referenced to.
    seed:
        Master seed feeding :func:`cryptoarb._rng.make_rng`.

    Returns
    -------
    OrderBook
        A validated, frozen order book for the venue.

    Raises
    ------
    ValidationError
        If ``spec`` parameters are out of domain (non-positive depth, etc.).
    """
    _validate_spec(spec)
    if not (true_mid > 0.0):
        raise ValidationError(f"{spec.venue}: true_mid must be positive, got {true_mid}.")
    venue_mid = true_mid * (1.0 + spec.mid_offset_bps / 1e4)
    if not (venue_mid > 0.0):
        raise ValidationError(
            f"{spec.venue}: venue mid is non-positive after offset "
            f"(true_mid={true_mid}, mid_offset_bps={spec.mid_offset_bps})."
        )
    # Pure (no-noise) generation by default; a noise sub-stream is only drawn
    # when the multi-venue caller threads ``size_noise`` through ``_build_ladders``.
    bids, asks = _build_ladders(venue_mid, spec, size_noise=0.0, seed=seed)
    return OrderBook(venue=spec.venue, symbol=symbol, bids=bids, asks=asks)


def synthetic_books(config: SyntheticConfig, *, seed: int = 0) -> dict[str, OrderBook]:
    """Generate the full per-venue snapshot for a :class:`SyntheticConfig`.

    With ``config.dislocation_bps == 0`` the returned books share a common true
    mid (no cross-venue arb survives costs); a non-zero dislocation skews the
    last venue to manufacture an apparent gap.

    Parameters
    ----------
    config:
        The multi-venue snapshot configuration.
    seed:
        Master seed; each venue draws an independent substream.

    Returns
    -------
    dict[str, OrderBook]
        Mapping of venue identifier to its generated order book.

    Raises
    ------
    ValidationError
        If ``config`` has no venues or any spec is out of domain.
    """
    if not config.venues:
        raise ValidationError("synthetic_books: config has no venues.")
    if not (config.true_mid > 0.0):
        raise ValidationError(f"synthetic_books: true_mid must be positive, got {config.true_mid}.")

    n = len(config.venues)
    substreams = spawn_substreams(seed, n)
    books: dict[str, OrderBook] = {}
    for index, (spec, child) in enumerate(zip(config.venues, substreams, strict=True)):
        _validate_spec(spec)
        # The final venue carries any manufactured cross-venue dislocation on top
        # of its own configured offset; every other venue is referenced cleanly
        # to the shared true mid (the honest-null fixture when dislocation == 0).
        extra_bps = config.dislocation_bps if index == n - 1 else 0.0
        venue_mid = config.true_mid * (1.0 + (spec.mid_offset_bps + extra_bps) / 1e4)
        if not (venue_mid > 0.0):
            raise ValidationError(
                f"{spec.venue}: venue mid is non-positive after offset/dislocation."
            )
        # Derive a stable per-venue noise seed from the spawned child so the same
        # (seed, config) always yields byte-identical books.
        noise_seed = int(child.integers(0, 2**32 - 1))
        bids, asks = _build_ladders(venue_mid, spec, size_noise=config.size_noise, seed=noise_seed)
        book = OrderBook(
            venue=spec.venue,
            symbol=config.symbol,
            bids=bids,
            asks=asks,
            ts_ms=config.ts_ms,
        )
        book.validate()
        books[spec.venue] = book
    return books


def consistent_triangular_books(
    *,
    venue: str = "binance",
    mid_ab: float = 50_000.0,
    mid_bc: float = 3_000.0,
    half_spread_bps: float = 2.0,
    seed: int = 0,
    dislocation_bps: float = 0.0,
) -> dict[str, OrderBook]:
    """Generate three single-venue books forming a triangular cycle ``A/B·B/C·C/A``.

    The third leg's mid is set to ``1 / (mid_ab * mid_bc)`` so the product of the
    three mids is exactly ``1`` — the no-arb identity that the parity suite
    checks to ``1e-12`` when ``dislocation_bps == 0``. A non-zero
    ``dislocation_bps`` perturbs the ``C/A`` mid to break the identity by a known
    amount.

    Parameters
    ----------
    venue:
        The single venue hosting all three legs.
    mid_ab, mid_bc:
        The mids of the ``A/B`` and ``B/C`` legs; the ``C/A`` mid is derived.
    half_spread_bps:
        Symmetric half-spread applied to each leg.
    seed:
        Master seed feeding the generator.
    dislocation_bps:
        Signed perturbation of the ``C/A`` mid, in bps (``0`` = consistent).

    Returns
    -------
    dict[str, OrderBook]
        Mapping of leg symbol (``"A/B"``, ``"B/C"``, ``"C/A"``) to its book.

    Raises
    ------
    ValidationError
        If any derived price is non-positive.
    """
    if not (mid_ab > 0.0):
        raise ValidationError(
            f"consistent_triangular_books: mid_ab must be positive, got {mid_ab}."
        )
    if not (mid_bc > 0.0):
        raise ValidationError(
            f"consistent_triangular_books: mid_bc must be positive, got {mid_bc}."
        )
    if not (half_spread_bps > 0.0):
        raise ValidationError(
            f"consistent_triangular_books: half_spread_bps must be positive, got {half_spread_bps}."
        )

    # Close the loop: A/B * B/C * C/A == 1 exactly when mid_ca = 1 / (mid_ab * mid_bc).
    # A signed dislocation perturbs the C/A leg to break the identity by a known amount.
    mid_ca = 1.0 / (mid_ab * mid_bc)
    mid_ca *= 1.0 + dislocation_bps / 1e4
    if not (mid_ca > 0.0):
        raise ValidationError(
            "consistent_triangular_books: derived C/A mid is non-positive "
            f"(mid_ab={mid_ab}, mid_bc={mid_bc}, dislocation_bps={dislocation_bps})."
        )

    legs = (("A/B", mid_ab), ("B/C", mid_bc), ("C/A", mid_ca))
    substreams = spawn_substreams(seed, len(legs))
    books: dict[str, OrderBook] = {}
    for (leg_symbol, leg_mid), child in zip(legs, substreams, strict=True):
        spec = VenueSpec(
            venue=venue,
            half_spread_bps=half_spread_bps,
            depth_base=5.0,
            n_levels=10,
        )
        noise_seed = int(child.integers(0, 2**32 - 1))
        # No size noise: a symmetric ladder makes each leg's mid equal leg_mid
        # exactly, so the no-arb product holds to machine precision (~1e-12).
        bids, asks = _build_ladders(leg_mid, spec, size_noise=0.0, seed=noise_seed)
        book = OrderBook(venue=venue, symbol=leg_symbol, bids=bids, asks=asks)
        book.validate()
        books[leg_symbol] = book
    return books
